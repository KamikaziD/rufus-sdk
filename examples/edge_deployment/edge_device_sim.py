"""
edge_device_sim.py — Minimal Rufus edge device emulator for docker-compose testing.

1. Registers the device with the cloud control plane.
2. Starts RufusEdgeAgent (heartbeat + config polling).
3. Keeps running so push-workflow / update_workflow commands can be tested live.

Environment variables:
    CLOUD_URL           Cloud control plane URL (default: http://rufus-server:8000)
    DEVICE_ID           Unique device identifier (default: sim-device-001)
    RUFUS_API_KEY       API key returned after registration (leave blank; set after register)
    RUFUS_ENCRYPTION_KEY  Encryption key for workflow state (optional)
    DB_PATH             SQLite database path (default: /tmp/edge_sim.db)
    RUFUS_REGISTRATION_KEY  Key required for /api/v1/devices/register (default: test-registration-key)
"""

import asyncio
import logging
import os

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("edge-sim")

CLOUD_URL = os.getenv("CLOUD_URL", "http://rufus-server:8000")
DEVICE_ID = os.getenv("DEVICE_ID", "sim-device-001")
DB_PATH = os.getenv("DB_PATH", "/tmp/edge_sim.db")
ENCRYPTION_KEY = os.getenv("RUFUS_ENCRYPTION_KEY", "") or None
REGISTRATION_KEY = os.getenv("RUFUS_REGISTRATION_KEY", "test-registration-key")

# Persist API key alongside the SQLite DB so it survives container restarts
_API_KEY_FILE = DB_PATH + ".apikey"


async def register_device() -> str:
    """
    Register the device with the cloud control plane.

    Returns the api_key (from server on first registration, or from local
    cache on subsequent starts). The server only returns the key once, so
    we persist it to _API_KEY_FILE for use across restarts.
    """
    # Load cached key if available (device already registered and key persisted)
    try:
        with open(_API_KEY_FILE) as f:
            cached = f.read().strip()
        if cached:
            logger.info(f"Loaded persisted API key for {DEVICE_ID}")
            return cached
    except FileNotFoundError:
        pass

    async with httpx.AsyncClient(base_url=CLOUD_URL, timeout=15) as client:
        resp = await client.post(
            "/api/v1/devices/register",
            json={
                "device_id": DEVICE_ID,
                "device_type": "sim",
                "device_name": f"Sim Device {DEVICE_ID}",
                "merchant_id": "test-merchant-001",
                "firmware_version": "1.0.0",
                "sdk_version": "0.7.5",
                "capabilities": ["workflow_execution", "update_workflow"],
            },
            headers={"X-Registration-Key": REGISTRATION_KEY},
        )

        if resp.status_code in (200, 201):
            data = resp.json()
            api_key = data.get("api_key", "")
            logger.info(f"Device registered: {DEVICE_ID}  api_key={api_key[:8]}...")
            # Persist for future restarts
            try:
                with open(_API_KEY_FILE, "w") as f:
                    f.write(api_key)
            except OSError as e:
                logger.warning(f"Could not persist API key: {e}")
            return api_key

        if resp.status_code == 400 and "already registered" in resp.text:
            logger.warning(
                f"Device {DEVICE_ID} already registered but no local key file found — "
                "config endpoint will 401 until the device is re-registered"
            )
            return ""

        logger.warning(f"Registration returned {resp.status_code}: {resp.text}")
        return ""


async def main():
    # Wait for server to be reachable
    for attempt in range(20):
        try:
            async with httpx.AsyncClient(base_url=CLOUD_URL, timeout=5) as client:
                resp = await client.get("/health")
                if resp.status_code == 200:
                    logger.info("Cloud control plane is healthy")
                    break
        except Exception as exc:
            logger.info(f"Waiting for cloud ({attempt + 1}/20): {exc}")
            await asyncio.sleep(5)
    else:
        logger.error("Cloud control plane did not become healthy — exiting")
        raise SystemExit(1)

    api_key = await register_device()

    from rufus_edge import RufusEdgeAgent

    agent = RufusEdgeAgent(
        device_id=DEVICE_ID,
        cloud_url=CLOUD_URL,
        api_key=api_key,
        db_path=DB_PATH,
        encryption_key=ENCRYPTION_KEY,
        heartbeat_interval=30,   # poll for commands every 30 s
        config_poll_interval=60,
        sync_interval=60,
    )

    await agent.start()
    logger.info("Edge agent running. Waiting for workflow push commands...")

    try:
        await asyncio.sleep(999_999)
    except asyncio.CancelledError:
        pass
    finally:
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
