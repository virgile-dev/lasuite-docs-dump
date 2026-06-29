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
        01_Child-Title/
          content.md
          ...
"""

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

from exporter import UUID_RE, DocsExporter, ExportError


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

    try:
        exporter = DocsExporter(base_url, session, output_dir, delay=args.delay)
        exporter.export_doc(doc_id, output_dir)
    except ExportError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print()
    print(f"Done. Files saved to: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
