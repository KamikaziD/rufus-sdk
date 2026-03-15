#!/usr/bin/env python3
"""
Rufus Edge Runner for MacBook (Apple Silicon)

Demonstrates running a Rufus Edge agent on a MacBook Pro M-series chip,
with hardware detection and live workflow-push support.

Usage:
    # First, start the cloud platform:
    cd docker && docker compose up -d

    # Then run this script:
    python examples/edge_deployment/run_edge_macbook.py

Requirements:
    - MacBook with Apple Silicon (M1/M2/M3/M4)
    - Docker running the cloud platform on localhost:8000
    - Python 3.10+ with rufus-sdk installed (pip install -e ".[postgres,performance,cli]")
"""

import asyncio
import logging
import os
import sys

import httpx

# Add project root to path (for local dev without pip install)
project_root = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(project_root, "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("rufus.edge.macbook")

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

CLOUD_URL = os.getenv("RUFUS_CLOUD_URL", "http://localhost:8000")
DEVICE_ID = os.getenv("RUFUS_DEVICE_ID", "macbook-m4-001")
DB_PATH = os.getenv("RUFUS_DB_PATH", "/tmp/rufus_macbook_edge.db")
ENCRYPTION_KEY = os.getenv("RUFUS_ENCRYPTION_KEY", "") or None
REGISTRATION_KEY = os.getenv("RUFUS_REGISTRATION_KEY", "dev-registration-key")


# ─────────────────────────────────────────────────────────────────────────────
# Hardware Detection
# ─────────────────────────────────────────────────────────────────────────────

async def detect_hardware():
    """Detect and display hardware capabilities."""
    print("\n" + "=" * 60)
    print("  HARDWARE DETECTION")
    print("=" * 60 + "\n")

    try:
        from rufus.utils.platform import (
            get_platform_info,
            has_apple_neural_engine,
            get_recommended_onnx_providers,
            get_recommended_runtime,
        )

        info = get_platform_info()
        print(f"  Platform:        {info.system} {info.machine}")
        print(f"  Apple Silicon:   {'Yes' if info.is_apple_silicon else 'No'}")
        print(
            f"  Neural Engine:   {'Yes' if has_apple_neural_engine() else 'No'}")
        print(f"  Accelerators:    {[a.value for a in info.accelerators]}")
        print(f"  Recommended:     {get_recommended_runtime()}")
        print(f"  ONNX Providers:  {get_recommended_onnx_providers()}")
        return info
    except ImportError:
        print("  (platform detection module not available — skipping)")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Device Registration
# ─────────────────────────────────────────────────────────────────────────────

async def register_device(hw_info=None) -> str:
    """
    Register this MacBook as an edge device with the cloud control plane.

    Returns the api_key from the server, or empty string if already registered.
    """
    print("\n" + "=" * 60)
    print("  DEVICE REGISTRATION")
    print("=" * 60 + "\n")

    capabilities = ["workflow_execution", "update_workflow"]
    if hw_info and getattr(hw_info, "is_apple_silicon", False):
        capabilities.append("apple_silicon")
    if hw_info and getattr(hw_info, "accelerators", []):
        capabilities.append("neural_engine")

    async with httpx.AsyncClient(base_url=CLOUD_URL, timeout=15) as client:
        try:
            resp = await client.post(
                "/api/v1/devices/register",
                json={
                    "device_id": DEVICE_ID,
                    "device_type": "macbook",
                    "device_name": f"MacBook {DEVICE_ID}",
                    "merchant_id": "dev-merchant",
                    "firmware_version": "macOS-14",
                    "sdk_version": "1.0.0rc2",
                    "location": "local",
                    "capabilities": capabilities,
                },
                headers={"X-Registration-Key": REGISTRATION_KEY},
            )

            if resp.status_code in (200, 201):
                data = resp.json()
                api_key = data.get("api_key", "")
                print(f"  Device registered: {DEVICE_ID}")
                print(f"  API key:           {api_key[:8]}...")
                return api_key

            if resp.status_code == 400 and "already registered" in resp.text:
                print(f"  Device {DEVICE_ID} already registered — continuing")
                return ""

            print(
                f"  Registration failed: HTTP {resp.status_code}: {resp.text}")
            return ""

        except httpx.ConnectError:
            print(f"  ERROR: Cannot connect to cloud at {CLOUD_URL}")
            print(
                "         Make sure Docker is running: cd docker && docker compose up -d")
            return ""


# ─────────────────────────────────────────────────────────────────────────────
# Main Edge Agent Loop
# ─────────────────────────────────────────────────────────────────────────────

async def run_edge_agent(api_key: str):
    """Start the RufusEdgeAgent and keep it running for workflow push testing."""
    print("\n" + "=" * 60)
    print("  EDGE AGENT")
    print("=" * 60 + "\n")
    print(f"  Cloud URL: {CLOUD_URL}")
    print(f"  Device ID: {DEVICE_ID}")
    print(f"  DB path:   {DB_PATH}")
    print("\n  Agent running. Press Ctrl+C to stop.")
    print("  Push workflow YAMLs via the dashboard → Admin → Server → Push to Devices\n")

    from rufus_edge import RufusEdgeAgent

    agent = RufusEdgeAgent(
        device_id=DEVICE_ID,
        cloud_url=CLOUD_URL,
        api_key=api_key,
        db_path=DB_PATH,
        encryption_key=ENCRYPTION_KEY,
        heartbeat_interval=30,
        config_poll_interval=60,
        sync_interval=60,
    )

    await agent.start()

    try:
        while True:
            health = await agent.get_health()
            logger.debug(
                f"Health: status={health.status.value}  online={health.is_online}  "
                f"pending_sync={health.pending_sync}"
            )
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        pass
    finally:
        await agent.stop()
        print("\n  Edge agent stopped.")


async def main():
    print("\n" + "#" * 60)
    print("#" + " " * 58 + "#")
    print("#    RUFUS EDGE — MacBook" + " " * 34 + "#")
    print("#" + " " * 58 + "#")
    print("#" * 60)

    hw_info = await detect_hardware()

    api_key = await register_device(hw_info)

    print("\n" + "=" * 60)
    print("  OPTIONS")
    print("=" * 60 + "\n")
    print("  1. Run edge agent loop (stays alive, receives workflow pushes)")
    print("  2. Exit")
    print()

    try:
        choice = input("  Enter choice [1/2]: ").strip()
        if choice == "1":
            await run_edge_agent(api_key)
    except KeyboardInterrupt:
        print("\n\n  Shutting down...")

    print("\n  Done.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  Interrupted by user.")
