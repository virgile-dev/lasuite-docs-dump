#!/usr/bin/env python3
"""
Flask web server for the Docs export web app.

Dev:
    cd webapp && flask --app server run --port 8000

Prod (after building the frontend):
    cd webapp && flask --app server run --port 8000
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, Response, jsonify, request, send_from_directory

from export_docs import ExportError, export_to_zip

FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")

app = Flask(__name__, static_folder=FRONTEND_DIST, static_url_path="")


@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIST, "index.html")


@app.route("/api/export", methods=["POST"])
def export():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()

    if not url:
        return jsonify({"error": "Missing url parameter."}), 400

    try:
        zip_bytes, zip_name = export_to_zip(url)
    except ExportError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500

    return Response(
        zip_bytes,
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


if __name__ == "__main__":
    app.run(debug=True, port=8000)
