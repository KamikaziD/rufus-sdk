"""
serve.py — Dev server for Browser Demo 2.

Serves with Cross-Origin-Opener-Policy / Cross-Origin-Embedder-Policy headers
so SharedArrayBuffer is available if needed in future, and to allow fetch()
against localhost:8000 without CORS issues.

Usage:
    cd examples/browser_demo_2 && python serve.py
    # Open http://localhost:8082
"""

import os
from http.server import HTTPServer, SimpleHTTPRequestHandler


class CrossOriginHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, format, *args):
        pass  # Suppress per-request noise


os.chdir(os.path.dirname(os.path.abspath(__file__)))
print("Rufus Browser Demo 2 — http://localhost:8082 - http://localhost:8082/architecture.html")
print("Press Ctrl+C to stop.")
HTTPServer(("", 8082), CrossOriginHandler).serve_forever()
