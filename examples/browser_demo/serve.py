#!/usr/bin/env python3
"""
Compressed static server for the Rufus browser demo.

Drop-in replacement for `python -m http.server`:

    python examples/browser_demo/serve.py [port]   # default 8080

Negotiates brotli (if installed) or gzip compression for text-based assets,
reducing the rufus-sdk wheel transfer size by ~25–35%.

Optional brotli support:
    pip install brotli
"""

import gzip
import http.server
import os
import socketserver
import sys
from pathlib import Path

COMPRESSIBLE = {".whl", ".js", ".mjs", ".html", ".css", ".json", ".txt", ".py", ".yaml", ".yml"}

# (path, encoding, mtime) → compressed bytes
_cache: dict = {}

try:
    import brotli as _brotli
    _HAS_BROTLI = True
except ImportError:
    _HAS_BROTLI = False


class CompressedHandler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            return super().do_GET()

        ext = Path(path).suffix.lower()
        if ext not in COMPRESSIBLE:
            return super().do_GET()

        accept = self.headers.get("Accept-Encoding", "")
        encoding = None
        if _HAS_BROTLI and "br" in accept:
            encoding = "br"
        elif "gzip" in accept:
            encoding = "gzip"

        if encoding is None:
            return super().do_GET()

        mtime = os.path.getmtime(path)
        cache_key = (path, encoding, mtime)
        if cache_key not in _cache:
            data = Path(path).read_bytes()
            if encoding == "br":
                _cache[cache_key] = _brotli.compress(data, quality=6)
            else:
                _cache[cache_key] = gzip.compress(data, compresslevel=6)

        compressed = _cache[cache_key]

        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Encoding", encoding)
        self.send_header("Content-Length", str(len(compressed)))
        self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        self.wfile.write(compressed)

    def log_message(self, fmt, *args):
        # Suppress 200/304 noise; still show errors
        if len(args) >= 2 and args[1] in ("200", "304"):
            return
        super().log_message(fmt, *args)


PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
mode = "brotli + gzip" if _HAS_BROTLI else "gzip"

print(f"Serving on http://localhost:{PORT}  [{mode} compression]")
print("Press Ctrl-C to stop.")
print()

# Serve from the repo root so /dist/rufus_sdk-*.whl resolves correctly
repo_root = Path(__file__).resolve().parents[2]
os.chdir(repo_root)

with socketserver.TCPServer(("", PORT), CompressedHandler) as httpd:
    httpd.allow_reuse_address = True
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
