#!/usr/bin/env python3
"""
Export a LaSuite Docs document tree to local files.

Usage:
    python export_docs.py <full_doc_url> [options]
    python export_docs.py <base_url> <doc_id> [options]

Options:
    --format  markdown|html|pdf   (default: markdown)
    --no-media                    Skip downloading media files
    --output, -o                  Output directory (default: output/)
    --delay                       Seconds between API calls (default: 0.3)
    --token                       Bearer token for private docs
    --cookie                      Cookie string for private docs
"""

import argparse
import io
import re
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import requests


UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
MEDIA_RE = re.compile(r"(!?\[[^\]]*\])\(([^)\s]+)\)")
HTML_SRC_RE = re.compile(r'(src)="(https?://[^"]+)"')
MEDIA_EXTS = {
    ".mp4", ".webm", ".mov", ".avi", ".mkv",
    ".mp3", ".wav", ".ogg", ".m4a", ".m4v",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf",
}

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 860px; margin: 40px auto; padding: 0 24px; line-height: 1.6; color: #1a1a2e; }}
  h1, h2, h3, h4 {{ line-height: 1.3; }}
  img {{ max-width: 100%; height: auto; border-radius: 4px; }}
  video {{ max-width: 100%; }}
  pre {{ background: #f5f5fe; padding: 1em; border-radius: 6px; overflow-x: auto; }}
  code {{ background: #f5f5fe; padding: 0.15em 0.4em; border-radius: 3px; font-size: 0.9em; }}
  blockquote {{ border-left: 4px solid #ccc; margin: 0; padding-left: 1em; color: #555; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
  th {{ background: #f5f5fe; }}
</style>
</head>
<body>
{content}
</body>
</html>"""


class ExportError(Exception):
    pass


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


def parse_doc_url(url: str) -> tuple[str, str]:
    url = url.strip().rstrip("/")
    match = UUID_RE.search(url)
    if not match:
        raise ExportError("No document UUID found in the URL.")
    doc_id = match.group(0)
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}", doc_id


def html_to_pdf(html: str) -> bytes:
    from weasyprint import HTML
    return HTML(string=html).write_pdf()


class DocsExporter:
    def __init__(
        self,
        base_url: str,
        session: requests.Session,
        output_dir: Path,
        delay: float = 0.1,
        content_format: str = "markdown",
        include_media: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.output_dir = output_dir
        self.delay = delay
        self.content_format = content_format
        self.include_media = include_media
        self._visited: set[str] = set()

    def api_get(self, path: str, params: dict = None) -> dict | None:
        url = f"{self.base_url}{path}"
        resp = self.session.get(url, params=params)
        if resp.status_code == 401:
            raise ExportError("Authentication required — this document is not public.")
        if resp.status_code == 403:
            raise ExportError(f"Access denied to {url}.")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        time.sleep(self.delay)
        return resp.json()

    def get_document(self, doc_id: str) -> dict | None:
        return self.api_get(f"/api/v1.0/documents/{doc_id}/")

    def get_formatted_content(self, doc_id: str, api_format: str) -> str:
        params = {"content_format": api_format}
        for path in (
            f"/api/v1.0/documents/{doc_id}/formatted-content/",
            f"/api/v1.0/documents/{doc_id}/content/",
        ):
            resp = self.session.get(f"{self.base_url}{path}", params=params)
            if resp.status_code == 404:
                continue
            if resp.status_code == 401:
                raise ExportError("Authentication required — this document is not public.")
            resp.raise_for_status()
            time.sleep(self.delay)
            return resp.json().get("content") or ""
        return ""

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
            return local_name
        except Exception as e:
            print(f"WARNING: could not download {url}: {e}", file=sys.stderr)
            return url

    def localise_md_media(self, markdown: str, dest_dir: Path, title_slug: str) -> str:
        def replace(m):
            label, url = m.group(1), m.group(2)
            try:
                parsed = urlparse(url)
            except ValueError:
                return m.group(0)
            if parsed.scheme not in ("http", "https"):
                return m.group(0)
            if not label.startswith("!") and Path(parsed.path).suffix.lower() not in MEDIA_EXTS:
                return m.group(0)
            return f"{label}({self.download_media(url, dest_dir, title_slug)})"
        return MEDIA_RE.sub(replace, markdown)

    def localise_html_media(self, html: str, dest_dir: Path, title_slug: str) -> str:
        def replace(m):
            attr, url = m.group(1), m.group(2)
            try:
                parsed = urlparse(url)
            except ValueError:
                return m.group(0)
            if Path(parsed.path).suffix.lower() not in MEDIA_EXTS:
                return m.group(0)
            return f'{attr}="{self.download_media(url, dest_dir, title_slug)}"'
        return HTML_SRC_RE.sub(replace, html)

    def export_doc(self, doc_id: str, parent_dir: Path, depth: int = 0, index: int = 0) -> None:
        if doc_id in self._visited:
            return
        self._visited.add(doc_id)

        doc = self.get_document(doc_id)
        if not doc:
            return

        title = doc.get("title") or doc.get("name") or doc_id
        title_slug = slugify(title)
        folder_name = f"{index:02d}_{title_slug}" if index > 0 else title_slug
        doc_dir = parent_dir / folder_name
        doc_dir.mkdir(parents=True, exist_ok=True)

        print("  " * depth + f"Exporting: {title}")

        fmt = self.content_format
        # PDF is generated from HTML
        api_format = "html" if fmt == "pdf" else fmt

        content = self.get_formatted_content(doc_id, api_format)

        if fmt == "markdown":
            if self.include_media:
                content = self.localise_md_media(content, doc_dir, title_slug)
            with open(doc_dir / "content.md", "w", encoding="utf-8") as f:
                f.write(content)

        elif fmt == "html":
            if self.include_media:
                content = self.localise_html_media(content, doc_dir, title_slug)
            html = HTML_TEMPLATE.format(title=title, content=content)
            with open(doc_dir / "content.html", "w", encoding="utf-8") as f:
                f.write(html)

        elif fmt == "pdf":
            if not self.include_media:
                # Strip image tags when media is excluded
                content = re.sub(r"<img[^>]*/?>", "", content)
            # Strip video tags (can't embed video in PDF)
            content = re.sub(r"<video[^>]*>.*?</video>", "", content, flags=re.DOTALL)
            html = HTML_TEMPLATE.format(title=title, content=content)
            pdf_bytes = html_to_pdf(html)
            with open(doc_dir / "content.pdf", "wb") as f:
                f.write(pdf_bytes)

        for i, child in enumerate(self.get_children(doc_id), start=1):
            child_id = child.get("id")
            if child_id:
                self.export_doc(child_id, doc_dir, depth + 1, index=i)


def export_to_zip(
    url: str,
    content_format: str = "markdown",
    include_media: bool = True,
) -> tuple[bytes, str]:
    """Export a doc tree to an in-memory zip. Returns (zip_bytes, filename)."""
    base_url, doc_id = parse_doc_url(url)
    session = requests.Session()
    session.headers["Accept"] = "application/json"

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        exporter = DocsExporter(
            base_url, session, output_dir,
            content_format=content_format,
            include_media=include_media,
        )
        exporter.export_doc(doc_id, output_dir)

        root_folders = [p for p in output_dir.iterdir() if p.is_dir()]
        zip_name = (root_folders[0].name if root_folders else "docs-export") + ".zip"

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for filepath in sorted(output_dir.rglob("*")):
                if filepath.is_file():
                    zf.write(filepath, filepath.relative_to(output_dir))
        return buf.getvalue(), zip_name


def main():
    parser = argparse.ArgumentParser(description="Export a LaSuite Docs document tree to local files.")
    parser.add_argument("url_or_base", help="Full doc URL or base URL")
    parser.add_argument("doc_id", nargs="?", help="Document UUID (omit when passing a full URL)")
    parser.add_argument("--format", choices=["markdown", "html", "pdf"], default="markdown")
    parser.add_argument("--no-media", action="store_true", help="Skip downloading media files")
    parser.add_argument("--token", help="Bearer token for authentication")
    parser.add_argument("--cookie", help='Cookie string (e.g. "sessionid=abc123")')
    parser.add_argument("--output", "-o", default="output", help="Output directory (default: output/)")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between API calls in seconds")
    args = parser.parse_args()

    url = args.url_or_base.rstrip("/")
    doc_id = args.doc_id

    if doc_id is None:
        try:
            base_url, doc_id = parse_doc_url(url)
        except ExportError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
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
    print(f"Format   : {args.format}")
    print(f"Media    : {'yes' if not args.no_media else 'no'}")
    print(f"Output   : {output_dir.resolve()}")
    print()

    try:
        exporter = DocsExporter(
            base_url, session, output_dir,
            delay=args.delay,
            content_format=args.format,
            include_media=not args.no_media,
        )
        exporter.export_doc(doc_id, output_dir)
    except ExportError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nDone. Files saved to: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
