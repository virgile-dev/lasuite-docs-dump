#!/usr/bin/env python3
"""
Export a LaSuite Docs document tree to local files.

Usage:
    python export_docs.py <base_url> <doc_id> [options]
    python export_docs.py <full_doc_url> [options]

Examples:
    # Full URL form (doc id extracted automatically)
    python export_docs.py https://docs.numerique.gouv.fr/docs/335e43b5-9e16-4798-a0b4-912e44c7135e/

    # Explicit base URL + doc id
    python export_docs.py https://docs.numerique.gouv.fr 335e43b5-9e16-4798-a0b4-912e44c7135e

    # With auth token
    python export_docs.py <url> --token YOUR_TOKEN

    # With session cookie
    python export_docs.py <url> --cookie "sessionid=abc123"

Output structure:
    output/
      Document-Title/
        content.md
        video_Document-Title_filename.mp4
        img_Document-Title_filename.png
        Child-Title/
          content.md
          ...
"""

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests


UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
# Matches markdown image and link syntax: ![alt](url) or [text](url)
MEDIA_RE = re.compile(r"(!?\[[^\]]*\])\(([^)\s]+)\)")


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")[:80]


def media_type_prefix(url: str) -> str:
    lower = url.lower()
    if any(ext in lower for ext in [".mp4", ".webm", ".mov", ".avi", ".mkv"]):
        return "video"
    if any(ext in lower for ext in [".mp3", ".wav", ".ogg", ".m4a"]):
        return "audio"
    if any(ext in lower for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"]):
        return "img"
    if ".pdf" in lower:
        return "pdf"
    return "file"


class DocsExporter:
    def __init__(self, base_url: str, session: requests.Session, output_dir: Path, delay: float = 0.3):
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.output_dir = output_dir
        self.delay = delay
        self._visited: set[str] = set()

    def api_get(self, path: str, params: dict = None) -> dict | None:
        url = f"{self.base_url}{path}"
        resp = self.session.get(url, params=params)
        if resp.status_code == 401:
            print("  ERROR 401 Unauthorized — provide --token or --cookie", file=sys.stderr)
            sys.exit(1)
        if resp.status_code == 403:
            print(f"  ERROR 403 Forbidden on {url}", file=sys.stderr)
            return None
        resp.raise_for_status()
        time.sleep(self.delay)
        return resp.json()

    def get_document(self, doc_id: str) -> dict | None:
        return self.api_get(f"/api/v1.0/documents/{doc_id}/")

    def get_formatted_content(self, doc_id: str) -> str:
        """Fetch document content as markdown via the formatted-content endpoint."""
        data = self.api_get(
            f"/api/v1.0/documents/{doc_id}/formatted-content/",
            params={"content_format": "markdown"},
        )
        if not data:
            return ""
        return data.get("content") or ""

    def get_children(self, doc_id: str) -> list:
        children = []
        path = f"/api/v1.0/documents/{doc_id}/children/"
        params = {"page_size": 100}
        while path:
            data = self.api_get(path, params)
            if not data:
                break
            results = data.get("results", data if isinstance(data, list) else [])
            children.extend(results)
            next_url = data.get("next")
            if next_url:
                parsed = urlparse(next_url)
                path = parsed.path
                params = dict(p.split("=") for p in parsed.query.split("&") if "=" in p)
            else:
                path = None
        return children

    def download_media(self, url: str, dest_dir: Path, title_slug: str) -> str:
        """Download a media file and return its local filename."""
        try:
            parsed = urlparse(url)
            original_name = Path(parsed.path).name or "file"
            prefix = media_type_prefix(url)
            local_name = f"{prefix}_{title_slug}_{original_name}"
            dest = dest_dir / local_name
            if dest.exists():
                return local_name
            resp = self.session.get(url, stream=True, timeout=60)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"    Downloaded: {local_name}")
            return local_name
        except Exception as e:
            print(f"    WARNING: could not download {url}: {e}", file=sys.stderr)
            return url

    def localise_media(self, markdown: str, dest_dir: Path, title_slug: str) -> str:
        """Download remote media referenced in markdown and rewrite URLs to local paths.

        Always downloads inline images (![...](...)).
        Only downloads regular links ([...](...)) when the URL has a media file extension.
        """
        MEDIA_EXTS = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".mp3", ".wav",
                      ".ogg", ".m4a", ".m4v", ".jpg", ".jpeg", ".png", ".gif",
                      ".webp", ".svg", ".pdf"}

        def replace(m):
            label = m.group(1)
            url = m.group(2)
            try:
                parsed = urlparse(url)
            except ValueError:
                return m.group(0)
            if parsed.scheme not in ("http", "https"):
                return m.group(0)
            is_inline_image = label.startswith("!")
            has_media_ext = Path(parsed.path).suffix.lower() in MEDIA_EXTS
            if not is_inline_image and not has_media_ext:
                return m.group(0)
            local = self.download_media(url, dest_dir, title_slug)
            return f"{label}({local})"

        return MEDIA_RE.sub(replace, markdown)

    def export_doc(self, doc_id: str, parent_dir: Path, depth: int = 0, index: int = 0) -> None:
        prefix = "  " * depth
        if doc_id in self._visited:
            print(f"{prefix}Skipping {doc_id} (already exported, circular reference)")
            return
        self._visited.add(doc_id)

        doc = self.get_document(doc_id)
        if not doc:
            print(f"{prefix}Skipping {doc_id} (no data)")
            return

        title = doc.get("title") or doc.get("name") or doc_id
        title_slug = slugify(title)
        # Prefix with order index for all non-root nodes so filesystem sort matches doc order.
        folder_name = f"{index:02d}_{title_slug}" if index > 0 else title_slug
        doc_dir = parent_dir / folder_name
        doc_dir.mkdir(parents=True, exist_ok=True)

        print(f"{prefix}Exporting: {title}")

        markdown = self.get_formatted_content(doc_id)
        markdown = self.localise_media(markdown, doc_dir, title_slug)

        content_file = doc_dir / "content.md"
        with open(content_file, "w", encoding="utf-8") as f:
            f.write(markdown)
        print(f"{prefix}  -> {content_file.relative_to(self.output_dir)}")

        for i, child in enumerate(self.get_children(doc_id), start=1):
            child_id = child.get("id")
            if child_id:
                self.export_doc(child_id, doc_dir, depth + 1, index=i)


def main():
    parser = argparse.ArgumentParser(description="Export a LaSuite Docs document tree to local files.")
    parser.add_argument("url_or_base", help="Full doc URL or base URL (e.g. https://docs.numerique.gouv.fr)")
    parser.add_argument("doc_id", nargs="?", help="Document UUID (omit when passing a full URL)")
    parser.add_argument("--token", help="Bearer token for authentication")
    parser.add_argument("--cookie", help='Cookie string (e.g. "sessionid=abc123")')
    parser.add_argument("--output", "-o", default="output", help="Output directory (default: output/)")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between API calls in seconds (default: 0.3)")
    args = parser.parse_args()

    url = args.url_or_base.rstrip("/")
    doc_id = args.doc_id

    if doc_id is None:
        match = UUID_RE.search(url)
        if not match:
            print("ERROR: no UUID found in URL. Provide <base_url> <doc_id> separately.", file=sys.stderr)
            sys.exit(1)
        doc_id = match.group(0)
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
    else:
        base_url = url

    session = requests.Session()
    session.headers["Accept"] = "application/json"
    if args.token:
        session.headers["Authorization"] = f"Bearer {args.token}"
    if args.cookie:
        session.headers["Cookie"] = args.cookie

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Base URL : {base_url}")
    print(f"Doc ID   : {doc_id}")
    print(f"Output   : {output_dir.resolve()}")
    print()

    exporter = DocsExporter(base_url, session, output_dir, delay=args.delay)
    exporter.export_doc(doc_id, output_dir)

    print()
    print(f"Done. Files saved to: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
