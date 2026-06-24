#!/usr/bin/env python3
"""
Export a LaSuite Docs document tree to local files.

Usage:
    python export_docs.py <base_url> <doc_id> [options]

Examples:
    # Public doc, no auth needed
    python export_docs.py https://docs.numerique.gouv.fr 335e43b5-9e16-4798-a0b4-912e44c7135e

    # With auth token (from browser devtools: Application > Cookies > sessionid, or Authorization header)
    python export_docs.py https://docs.numerique.gouv.fr 335e43b5-9e16-4798-a0b4-912e44c7135e --token YOUR_TOKEN

    # With session cookie
    python export_docs.py https://docs.numerique.gouv.fr 335e43b5-9e16-4798-a0b4-912e44c7135e --cookie "sessionid=abc123"

Output structure:
    output/
      Document-Title/
        content.md                           # page content as markdown
        video_Document-Title_filename.mp4    # downloaded media
        img_Document-Title_filename.png
        Child-Title/
          content.md
          ...
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests


def slugify(text: str) -> str:
    """Convert text to a safe folder/file name."""
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")[:80]


def media_type_prefix(url: str) -> str:
    """Guess a short media type prefix from URL or extension."""
    lower = url.lower()
    if any(ext in lower for ext in [".mp4", ".webm", ".mov", ".avi", ".mkv"]):
        return "video"
    if any(ext in lower for ext in [".mp3", ".wav", ".ogg", ".m4a"]):
        return "audio"
    if any(ext in lower for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"]):
        return "img"
    if any(ext in lower for ext in [".pdf"]):
        return "pdf"
    return "file"


class DocsExporter:
    def __init__(self, base_url: str, session: requests.Session, output_dir: Path, delay: float = 0.3):
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.output_dir = output_dir
        self.delay = delay

    def api_get(self, path: str, params: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        resp = self.session.get(url, params=params)
        if resp.status_code == 401:
            print(f"  ERROR 401 Unauthorized — provide --token or --cookie", file=sys.stderr)
            sys.exit(1)
        if resp.status_code == 403:
            print(f"  ERROR 403 Forbidden on {url}", file=sys.stderr)
            return None
        resp.raise_for_status()
        time.sleep(self.delay)
        return resp.json()

    def get_children(self, doc_id: str) -> list:
        """Fetch all children pages (handles pagination)."""
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
                # Use just the path+query from the next URL
                parsed = urlparse(next_url)
                path = parsed.path
                params = dict(p.split("=") for p in parsed.query.split("&") if "=" in p)
            else:
                path = None
        return children
