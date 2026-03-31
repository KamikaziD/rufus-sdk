"""
serve.py — Dev server for Browser Demo 3: Tab-to-Tab Pod Mesh.

Serves with COOP/COEP headers required for SharedArrayBuffer + Pyodide.
Opens the same page in two browser tabs to form a 2-pod RUVON mesh via
BroadcastChannel (no server required for pod-to-pod communication).

Usage:
    cd examples/browser_demo_3 && python serve.py
    # Open http://localhost:8083
    # Click "Open Second Pod" to spawn a second tab
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
print("Rufus Browser Demo 3 — Tab-to-Tab Pod Mesh")
print("Open: http://localhost:8083")
print("Click 'Open Second Pod' to spawn a second browser tab and form a 2-pod mesh.")
print("Press Ctrl+C to stop.")
HTTPServer(("", 8083), CrossOriginHandler).serve_forever()
