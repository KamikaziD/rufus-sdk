"""
PyodidePlatformAdapter — platform adapter for browser (Pyodide + JSPI).

HTTP:    js.fetch via Pyodide's JS bridge
Metrics: stub (no psutil / /proc in browser sandbox)
SQLite:  wa-sqlite JS API (see PyodideSQLiteProvider note below)
WASM:    js.WebAssembly + cm-js Component Model polyfill

This module is safe to import on native CPython; the js module is only
available inside a Pyodide runtime. Importing the adapter outside Pyodide
is allowed for type-checking and testing purposes.

## PyodideSQLiteProvider

SQLite in the browser is provided by wa-sqlite (SQLite compiled to WASM,
exposed via a JavaScript API). The Python-side shim wraps the JS API using
Pyodide's `js` module and `pyodide.ffi.to_js` / `from_js` helpers.

Usage (browser_loader.js orchestrates this before importing rufus_edge):

    // 1. Load wa-sqlite
    const { default: SQLiteESMFactory } = await import('./wa-sqlite.mjs');
    const sqlite3 = await SQLiteESMFactory();
    const db = await sqlite3.open_v2('rufus_edge', sqlite3.SQLITE_OPEN_CREATE | sqlite3.SQLITE_OPEN_READWRITE);

    // 2. Expose the db handle to Python
    window._rufus_wa_sqlite_db = db;
    window._rufus_wa_sqlite3   = sqlite3;

    // 3. Python code uses PyodidePlatformAdapter which reads window._rufus_wa_sqlite_db
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class _PyodideHttpResponse:
    """Wraps a Pyodide js.fetch Response to satisfy HttpResponse."""

    def __init__(self, status: int, body: bytes, hdrs: Dict[str, str]) -> None:
        self._status = status
        self._body = body
        self._headers = hdrs

    @property
    def status_code(self) -> int:
        return self._status

    def json(self) -> dict:
        return json.loads(self._body.decode("utf-8"))

    def text(self) -> str:
        return self._body.decode("utf-8")

    @property
    def headers(self) -> Dict[str, str]:
        return self._headers

    @property
    def content(self) -> bytes:
        return self._body


class PyodidePlatformAdapter:
    """
    Platform adapter for Pyodide (browser target).

    Requires Pyodide runtime with js module available.
    Falls back to urllib on native CPython for testing.
    """

    async def http_get(
        self,
        url: str,
        headers: Dict[str, str],
        timeout: float = 30.0,
    ) -> _PyodideHttpResponse:
        return await self._fetch("GET", url, headers=headers, body=None)

    async def http_post(
        self,
        url: str,
        json: dict,
        headers: Dict[str, str],
        timeout: float = 30.0,
    ) -> _PyodideHttpResponse:
        body = json.dumps(json).encode("utf-8")  # type: ignore[arg-type]
        import json as _json
        body = _json.dumps(json).encode("utf-8")
        merged = {"Content-Type": "application/json", **headers}
        return await self._fetch("POST", url, headers=merged, body=body)

    async def _fetch(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: bytes | None,
    ) -> _PyodideHttpResponse:
        try:
            import js  # only available inside Pyodide  # noqa: F401
            return await self._js_fetch(method, url, headers, body)
        except ImportError:
            # Native CPython fallback for tests
            return await self._urllib_fetch(method, url, headers, body)

    @staticmethod
    async def _js_fetch(
        method: str,
        url: str,
        headers: Dict[str, str],
        body: bytes | None,
    ) -> _PyodideHttpResponse:
        import js
        from pyodide.ffi import to_js

        init = {"method": method, "headers": to_js(headers)}
        if body is not None:
            init["body"] = to_js(body)

        response = await js.fetch(url, to_js(init))
        array_buf = await response.arrayBuffer()
        body_bytes = bytes(js.Uint8Array.new(array_buf))

        hdrs = {}
        try:
            for k in js.Object.keys(response.headers):
                hdrs[k] = response.headers.get(k)
        except Exception:
            pass

        return _PyodideHttpResponse(
            status=response.status,
            body=body_bytes,
            hdrs=hdrs,
        )

    @staticmethod
    async def _urllib_fetch(
        method: str,
        url: str,
        headers: Dict[str, str],
        body: bytes | None,
    ) -> _PyodideHttpResponse:
        import asyncio
        import urllib.request

        def _sync():
            req = urllib.request.Request(url, data=body, method=method)
            for k, v in headers.items():
                req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return _PyodideHttpResponse(
                    status=resp.status,
                    body=resp.read(),
                    hdrs=dict(resp.headers),
                )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync)

    def system_metrics(self) -> Dict[str, Any]:
        # psutil unavailable in browser
        return {}

    def is_wasm_capable(self) -> bool:
        # Browser can execute CM components via js.WebAssembly
        try:
            import js  # noqa: F401
            return True
        except ImportError:
            return False
