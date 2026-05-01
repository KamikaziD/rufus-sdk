"""
EchoForge Quickstart — full stack demo in a single script.

Starts:
  1. Mock VALR exchange (port 8766)
  2. EchoForge bridge (port 8765)
  3. Browser node server (port 8080)

After 15s injects a VPIN toxicity spike and prints the sentinel alert
received on the metrics WebSocket. Shuts everything down cleanly on exit.

Usage:
    python examples/echoforge_quickstart/run_quickstart.py
"""

import asyncio
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import websockets

REPO_ROOT   = Path(__file__).resolve().parents[2]
EF_DIR      = REPO_ROOT / "packages" / "ruvon-echoforge"
BRIDGE_URL  = "http://localhost:8765"
MOCK_URL    = "http://localhost:8766"
BROWSER_URL = "http://localhost:8080"


# ── Process management ────────────────────────────────────────────────────

_procs: list[subprocess.Popen] = []

def _start(cmd: list[str], cwd: Path, label: str) -> subprocess.Popen:
    p = subprocess.Popen(
        cmd, cwd=cwd,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    _procs.append(p)
    print(f"[start] {label} (pid {p.pid})")
    return p


def _stop_all():
    for p in _procs:
        try:
            p.terminate()
            p.wait(timeout=5)
        except Exception:
            p.kill()
    print("[stop] all processes terminated")


def _wait_http(url: str, label: str, timeout: int = 20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            httpx.get(url, timeout=2).raise_for_status()
            print(f"[ready] {label}")
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"{label} did not become ready at {url}")


# ── Sentinel listener ─────────────────────────────────────────────────────

async def _listen_for_sentinel(timeout: float = 40.0):
    print(f"[ws] connecting to {BRIDGE_URL.replace('http', 'ws')}/api/v1/metrics")
    deadline = asyncio.get_event_loop().time() + timeout
    async with websockets.connect(
        f"{BRIDGE_URL.replace('http', 'ws')}/api/v1/metrics"
    ) as ws:
        while asyncio.get_event_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                continue
            msg = json.loads(raw)
            if msg.get("type") == "sentinel_alert":
                print(f"\n[SENTINEL] {msg['sentinel_type']} → {msg['action']}")
                print(f"           severity={msg['severity']}  detail={msg['detail']}")
                return True
    print("[ws] no sentinel received within timeout")
    return False


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    signal.signal(signal.SIGINT,  lambda *_: (_stop_all(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda *_: (_stop_all(), sys.exit(0)))

    print("=" * 60)
    print("EchoForge Quickstart")
    print("=" * 60)

    # 1 — Mock VALR
    _start(
        [sys.executable, "-m", "ruvon_echoforge.tests.mock_valr.server"],
        cwd=EF_DIR,
        label="Mock VALR (port 8766)",
    )
    _wait_http(f"{MOCK_URL}/v1/public/time", "Mock VALR")

    # 2 — Bridge
    _start(
        [sys.executable, "-m", "uvicorn", "ruvon_echoforge.bridge.main:app",
         "--host", "0.0.0.0", "--port", "8765", "--log-level", "warning"],
        cwd=EF_DIR,
        label="EchoForge bridge (port 8765)",
    )
    _wait_http(f"{BRIDGE_URL}/docs", "Bridge")

    # 3 — Browser node server
    _start(
        [sys.executable, str(EF_DIR / "browser" / "serve.py"), "8080"],
        cwd=EF_DIR,
        label="Browser node server (port 8080)",
    )
    _wait_http(BROWSER_URL, "Browser node server")

    print(f"\n{'─'*60}")
    print(f"  Browser node:   {BROWSER_URL}")
    print(f"  Bridge docs:    {BRIDGE_URL}/docs")
    print(f"  PHIC config:    {BRIDGE_URL}/api/v1/phic/config")
    print(f"{'─'*60}\n")

    # Show initial PHIC config
    cfg = httpx.get(f"{BRIDGE_URL}/api/v1/phic/config").json()
    print(f"[phic] autonomy={cfg['autonomy_level']}  "
          f"stop_loss={cfg['stop_loss_pct']}%  "
          f"max_exposure={cfg['max_total_exposure_pct']}%")

    # Wait 15s then inject toxicity
    print("\n[wait] 15s before toxicity injection …")
    time.sleep(15)

    print("[inject] VPIN toxicity spike (30s duration)")
    httpx.post(
        f"{MOCK_URL}/mock/toxicity",
        json={"duration_seconds": 30.0, "volatility_spike": 0.008},
    )

    # Listen for the Nociceptor sentinel on the metrics WebSocket
    got_alert = asyncio.run(_listen_for_sentinel(timeout=40.0))

    if got_alert:
        print("\n[ok] Nociceptor fired as expected — demo complete.")
    else:
        print("\n[note] No sentinel received — open the browser node to "
              "connect to the exchange and trigger the full flow.")

    print("\nPress Ctrl+C to stop all processes, or wait 10s …")
    time.sleep(10)
    _stop_all()


if __name__ == "__main__":
    main()
