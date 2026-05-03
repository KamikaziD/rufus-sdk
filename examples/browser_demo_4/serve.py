#!/usr/bin/env python3
"""
Compressed static server for the Ruvon browser demo.

Drop-in replacement for `python -m http.server`:

    python examples/browser_demo/serve.py [port]   # default 8080

Negotiates brotli (if installed) or gzip compression for text-based assets,
reducing the ruvon-sdk wheel transfer size by ~25–35%.

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
        # Redirect bare root to the demo page
        if self.path in ("/", ""):
            self.send_response(302)
            self.send_header("Location", "/index.html")
            self.end_headers()
            return

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
        self.end_headers()  # _send_security_headers called here via override
        self.wfile.write(compressed)

    def _send_security_headers(self):
        """Required for SharedArrayBuffer → wllama multi-thread WASM (2-4× faster)."""
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin")

    def end_headers(self):
        self._send_security_headers()
        super().end_headers()

    def log_message(self, fmt, *args):
        # Suppress 200/304 noise; still show errors
        if len(args) >= 2 and args[1] in ("200", "304"):
            return
        super().log_message(fmt, *args)


PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
mode = "brotli + gzip" if _HAS_BROTLI else "gzip"

print(f"Serving on http://localhost:{PORT}  [{mode} compression]")
print("Press Ctrl-C to stop.")
print()

# Serve from the demo directory so localhost:8081/ → index.html directly
demo_dir = Path(__file__).resolve().parent
os.chdir(demo_dir)

socketserver.TCPServer.allow_reuse_address = True
httpd = socketserver.TCPServer(("", PORT), CompressedHandler)
try:
    httpd.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    httpd.shutdown()
    httpd.server_close()
    print("\nStopped.")
    sys.exit(0)
