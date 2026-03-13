"""
wasi_main.py — WASI 0.3 entrypoint for rufus-sdk-edge.

Compiled to ``dist/rufus_edge.wasm`` via::

    bash scripts/build_wasi.sh

The WASI event loop does not use ``asyncio.run()`` — instead we use
``asyncio.get_event_loop().run_until_complete()`` which py2wasm maps to the
WASI async executor provided by the host.

Environment variables consumed (all optional):
    RUFUS_DEVICE_ID      — unique device identifier (default: "wasi-device")
    RUFUS_CLOUD_URL      — cloud control plane URL   (default: "")
    RUFUS_API_KEY        — API key for authentication
    RUFUS_DB_PATH        — SQLite database path       (default: "rufus_edge.db")
    RUFUS_SYNC_INTERVAL  — seconds between SAF syncs  (default: 30)
    RUFUS_LOG_LEVEL      — Python logging level        (default: "INFO")
"""

import asyncio
import logging
import os
import sys


def _configure_logging():
    level_name = os.environ.get("RUFUS_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


async def _main():
    from rufus_edge.agent import RufusEdgeAgent
    from rufus_edge.platform.wasi import WasiPlatformAdapter

    device_id = os.environ.get("RUFUS_DEVICE_ID", "wasi-device")
    cloud_url = os.environ.get("RUFUS_CLOUD_URL", "")
    api_key = os.environ.get("RUFUS_API_KEY", "")
    db_path = os.environ.get("RUFUS_DB_PATH", "rufus_edge.db")
    sync_interval = int(os.environ.get("RUFUS_SYNC_INTERVAL", "30"))

    adapter = WasiPlatformAdapter(
        default_headers={
            "X-API-Key": api_key,
            "X-Device-ID": device_id,
        }
    )

    agent = RufusEdgeAgent(
        device_id=device_id,
        cloud_url=cloud_url,
        api_key=api_key,
        db_path=db_path,
        sync_interval=sync_interval,
        platform_adapter=adapter,
    )

    logging.getLogger(__name__).info(
        f"Rufus Edge Agent (WASI) starting — device={device_id}"
    )
    await agent.start()

    # In a WASI context the process runs until the host sends a signal or
    # the event loop is drained.  Keep alive by waiting forever.
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await agent.stop()


if __name__ == "__main__":
    _configure_logging()
    asyncio.get_event_loop().run_until_complete(_main())
