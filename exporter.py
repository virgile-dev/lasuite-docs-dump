"""
Core LaSuite Docs export logic. Used by both the CLI (export_docs.py) and the web app.
"""

import io
import re
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import requests


UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
MEDIA_RE = re.compile(r"(!?\[[^\]]*\])\(([^)\s]+)\)")
MEDIA_EXTS = {
    ".mp4", ".webm", ".mov", ".avi", ".mkv",
    ".mp3", ".wav", ".ogg", ".m4a", ".m4v",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf",
}


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
    """Return (base_url, doc_id) from either a full doc URL or raise ExportError."""
    url = url.strip().rstrip("/")
    match = UUID_RE.search(url)
    if not match:
        raise ExportError("No document UUID found in the URL.")
    doc_id = match.group(0)
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    return base_url, doc_id


class DocsExporter:
    def __init__(self, base_url: str, session: requests.Session, output_dir: Path, delay: float = 0.1):
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.output_dir = output_dir
        self.delay = delay
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

    def get_formatted_content(self, doc_id: str) -> str:
        params = {"content_format": "markdown"}
        for path in (
            f"/api/v1.0/documents/{doc_id}/formatted-content/",
            f"/api/v1.0/documents/{doc_id}/content/",
        ):
            url = f"{self.base_url}{path}"
            resp = self.session.get(url, params=params)
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

    def localise_media(self, markdown: str, dest_dir: Path, title_slug: str) -> str:
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

        indent = "  " * depth
        print(f"{indent}Exporting: {title}")

        markdown = self.get_formatted_content(doc_id)
        markdown = self.localise_media(markdown, doc_dir, title_slug)

        with open(doc_dir / "content.md", "w", encoding="utf-8") as f:
            f.write(markdown)

        for i, child in enumerate(self.get_children(doc_id), start=1):
            child_id = child.get("id")
            if child_id:
                self.export_doc(child_id, doc_dir, depth + 1, index=i)


def export_to_zip(url: str) -> tuple[bytes, str]:
    """Export a doc tree and return (zip_bytes, suggested_filename)."""
    import tempfile

    base_url, doc_id = parse_doc_url(url)

    session = requests.Session()
    session.headers["Accept"] = "application/json"

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        exporter = DocsExporter(base_url, session, output_dir, delay=0.1)
        exporter.export_doc(doc_id, output_dir)

        # Determine zip name from the root folder created
        root_folders = [p for p in output_dir.iterdir() if p.is_dir()]
        zip_name = (root_folders[0].name if root_folders else "docs-export") + ".zip"

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for filepath in sorted(output_dir.rglob("*")):
                if filepath.is_file():
                    zf.write(filepath, filepath.relative_to(output_dir))
        return buf.getvalue(), zip_name
