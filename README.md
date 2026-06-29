# scrap_user-docs

Export a [LaSuite Docs](https://docs.numerique.gouv.fr) document tree to local markdown files, mirroring the parent/child structure and downloading all media.

## Usage

```bash
python3 export_docs.py <url> [options]
```

The URL can be either a full doc URL or a base URL + doc ID:

```bash
# Full URL (doc ID extracted automatically)
python3 export_docs.py https://docs.numerique.gouv.fr/docs/335e43b5-9e16-4798-a0b4-912e44c7135e/

# Base URL + doc ID
python3 export_docs.py https://docs.numerique.gouv.fr 335e43b5-9e16-4798-a0b4-912e44c7135e
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
