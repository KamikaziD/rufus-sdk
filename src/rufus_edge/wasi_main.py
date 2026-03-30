"""
wasi_main.py — WASI 0.3 entrypoint for rufus-sdk-edge.

This module is the entry point when the edge agent is compiled to a WASI
component via py2wasm / wasi-python.

Key differences from native CPython startup:

  1. No asyncio.run() — the WASI event loop is provided by the surrounding
     host runtime (wasmtime, WasmEdge, wasm-micro-runtime, etc.).
     We use asyncio.get_event_loop().run_until_complete() which is patched
     by the WASI Python runtime to use the host-provided loop.

  2. No subprocess — sys.platform == 'wasm32'; all subprocess.run() calls
     in rufus.utils.platform are guarded behind this check.

  3. HTTP via wasi:http — WasiPlatformAdapter is selected automatically by
     detect_platform() when sys.platform == 'wasm32'.

  4. SQLite via wasi:filesystem — aiosqlite works unchanged because the WASI
     host maps wasi:filesystem to a directory on the host OS.

  5. Configuration is passed via environment variables (WASI component model
     env-inherit proposal or host-side env injection):
       RUFUS_DEVICE_ID       — required
       RUFUS_CLOUD_URL       — required
       RUFUS_API_KEY         — required
       RUFUS_DB_PATH         — optional, default "rufus_edge.db"
       RUFUS_SYNC_INTERVAL   — optional, default "30"
       RUFUS_CONFIG_INTERVAL — optional, default "60"
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)


def _get_env(key: str, default: str = "") -> str:
    value = os.environ.get(key, default)
    if not value:
        logger.warning(f"Environment variable {key} is not set")
    return value


async def _run_agent() -> None:
    from rufus_edge.agent import RufusEdgeAgent
    from rufus_edge.platform.wasi import WasiPlatformAdapter

    device_id = _get_env("RUFUS_DEVICE_ID")
    cloud_url = _get_env("RUFUS_CLOUD_URL")
    api_key = _get_env("RUFUS_API_KEY")
    db_path = _get_env("RUFUS_DB_PATH", "rufus_edge.db")
    sync_interval = int(_get_env("RUFUS_SYNC_INTERVAL", "30"))
    config_interval = int(_get_env("RUFUS_CONFIG_INTERVAL", "60"))

    if not device_id or not cloud_url:
        logger.error("RUFUS_DEVICE_ID and RUFUS_CLOUD_URL must be set")
        sys.exit(1)

    adapter = WasiPlatformAdapter()

    agent = RufusEdgeAgent(
        device_id=device_id,
        cloud_url=cloud_url,
        api_key=api_key,
        db_path=db_path,
        sync_interval=sync_interval,
        config_poll_interval=config_interval,
        platform_adapter=adapter,
    )

    logger.info(f"Starting Rufus Edge Agent (WASI): device={device_id}")
    await agent.start()

    # In WASI the process runs until the host terminates it.
    # We keep the event loop alive by waiting on a never-resolving future.
    try:
        await asyncio.get_event_loop().create_future()
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        await agent.stop()


def main() -> None:
    """WASI entrypoint — called by the host runtime."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(_run_agent())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
