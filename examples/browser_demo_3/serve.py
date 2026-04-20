"""
serve.py — Dev server for Browser Demo 3: Tab-to-Tab Pod Mesh.

Serves with COOP/COEP headers required for SharedArrayBuffer + Pyodide.
Binds to 0.0.0.0 so other devices on the same LAN can connect.

Usage:
    cd examples/browser_demo_3 && python serve.py
    # Open the printed URL on this machine or any LAN device.
    # For cross-device mesh: start the Ruvon server first:
    #   uvicorn ruvon_server.main:app --host 0.0.0.0 --port 8000
"""

import os
import socket
from http.server import HTTPServer, SimpleHTTPRequestHandler

DEMO_PORT   = 8083
SERVER_PORT = 8000


def local_ip() -> str:
    """Return the LAN IP of this machine (not 127.0.0.1)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class CrossOriginHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, format, *args):
        pass  # Suppress per-request noise


os.chdir(os.path.dirname(os.path.abspath(__file__)))

ip = local_ip()
print()
print("  Ruvon Browser Demo 3 — Regenerative Pod Mesh")
print("  ─────────────────────────────────────────────")
print(f"  This machine : http://localhost:{DEMO_PORT}")
print(f"  Other devices: http://{ip}:{DEMO_PORT}")
print()
print("  Cross-device mesh requires the Ruvon server:")
print(f"    uvicorn ruvon_server.main:app --host 0.0.0.0 --port {SERVER_PORT}")
print()
print("  Tip: share this link to add a remote pod to your mesh:")
print(f"    http://{ip}:{DEMO_PORT}?group=<your-group-key>")
print()
print("  Press Ctrl+C to stop.")
print()

HTTPServer(("", DEMO_PORT), CrossOriginHandler).serve_forever()
