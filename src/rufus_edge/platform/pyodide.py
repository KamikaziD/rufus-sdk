"""
PyodidePlatformAdapter — Browser implementation using js.fetch + JSPI.

Used when rufus-sdk-edge is loaded inside a Pyodide Web Worker.  All asyncio
awaits are handled by the browser event loop via JSPI (JS-Promise Integration).

SQLite is provided by wa-sqlite (WebAssembly SQLite) via PyodideSQLiteProvider
(see rufus_edge/implementations/persistence/pyodide_sqlite.py).

Limitations in the browser sandbox:
  - psutil is unavailable → SystemMetrics always returns zeros
  - No subprocess, no raw sockets
  - Fetch is subject to CORS rules of the host page
"""

from __future__ import annotations

import json
import logging
from typing import Dict, Optional

from rufus_edge.platform.base import HttpResponse, SystemMetrics

logger = logging.getLogger(__name__)


class PyodidePlatformAdapter:
    """
    PlatformAdapter backed by js.fetch (Pyodide browser environment).

    Requires Pyodide ≥ 0.25 and a browser that supports JSPI (Chrome 117+ or
    any environment with JSPI enabled via flag).
    """

    def __init__(self, default_headers: Optional[Dict[str, str]] = None):
        self._default_headers: Dict[str, str] = default_headers or {}

    async def http_get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        from js import fetch, Object  # type: ignore[import]
        from pyodide.ffi import to_js  # type: ignore[import]

        merged = {**self._default_headers, **(headers or {})}
        opts = to_js({"method": "GET", "headers": merged}, dict_converter=Object.fromEntries)
        resp = await fetch(url, opts)
        body = bytes(await resp.arrayBuffer().then(lambda b: b))
        return HttpResponse(
            status_code=resp.status,
            body=body,
            headers={k: v for k, v in resp.headers},
        )

    async def http_post(
        self,
        url: str,
        body: bytes,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        from js import fetch, Object, Uint8Array  # type: ignore[import]
        from pyodide.ffi import to_js  # type: ignore[import]

        merged = {
            "Content-Type": "application/json",
            **self._default_headers,
            **(headers or {}),
        }
        js_body = Uint8Array.new(body)
        opts = to_js(
            {"method": "POST", "headers": merged, "body": js_body},
            dict_converter=Object.fromEntries,
        )
        resp = await fetch(url, opts)
        resp_body = bytes(await resp.arrayBuffer().then(lambda b: b))
        return HttpResponse(
            status_code=resp.status,
            body=resp_body,
            headers={k: v for k, v in resp.headers},
        )

    def get_system_metrics(self) -> SystemMetrics:
        # psutil is not available in the browser sandbox
        return SystemMetrics()
