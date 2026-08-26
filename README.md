# LaSuite Docs dump

Export a [LaSuite Docs](https://github.com/suitenumerique/docs/) document tree to local markdown files, mirroring the parent/child structure and downloading all media.

## Usage

```bash
python3 export_docs.py <url> [options]
```

The URL can be either a full doc URL or a base URL + doc ID:

```bash
# Full URL (doc ID extracted automatically)
python3 export_docs.py https://{YOUR-DOMAIN}/docs/{YOUR-DOCUMENT-ID}/

# Base URL + doc ID
python3 export_docs.py {YOUR-DOMAIN} {YOUR-DOC-ID}
```

Works with any LaSuite Docs instance (v5+ and older versions).

## Options

| Option | Default | Description |
|---|---|---|
| `-o`, `--output` | `output/` | Output directory |
| `--delay` | `0.3` | Seconds between API calls |
| `--token` | — | Bearer token for private docs |
| `--cookie` | — | Cookie string for private docs (e.g. `sessionid=abc123`) |

## Output structure

```
output/
  Document-Title/
    content.md
    video_Document-Title_filename.mp4
    img_Document-Title_filename.png
    01_Child-Title/
      content.md
      img_Child-Title_filename.png
      01_Grandchild/
        content.md
```

- Each page becomes a folder containing `content.md` (the page content as markdown)
- Child folders are prefixed with a zero-padded index (`01_`, `02_`, ...) to preserve the original document order
- Media files (images, videos, PDFs) referenced in the content are downloaded alongside `content.md` and links are rewritten to point to the local files

## Authentication

For private documents, grab your session cookie from the browser (DevTools → Application → Cookies) and pass it with `--cookie`:

```bash
python3 export_docs.py <url> --cookie "sessionid=abc123"
```

## Requirements

```bash
pip install requests
```

---

## Web app

A simple browser interface — paste a URL, get a `.zip`.

### Run in dev mode

```bash
# Terminal 1 — Flask backend (port 8000)
cd webapp
pip install flask requests
python3 server.py

# Terminal 2 — Vite frontend (port 5173, proxies /api to Flask)
cd webapp/frontend
npm install
npm run dev
```

Open http://localhost:5173.

### Build for production

```bash
cd webapp/frontend
npm run build          # outputs to webapp/frontend/dist/

cd ..
python3 server.py      # serves the built frontend + API on port 8000
```

Open http://localhost:8000.
