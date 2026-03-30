"""
WasiPlatformAdapter — platform adapter for WASI 0.3 target.

HTTP is routed through the wasi:http/outgoing-handler interface.
System metrics are stubbed (no /proc in WASI sandbox).
WASM steps execute via the host's component runtime.

This module is imported at runtime only when sys.platform == 'wasm32'.
On native CPython the import succeeds but the adapter should not be
instantiated directly — use detect_platform() from __init__.py instead.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class _WasiHttpResponse:
    """Wraps a wasi:http response to satisfy the HttpResponse protocol."""

    def __init__(self, status: int, body: bytes, headers: Dict[str, str]) -> None:
        self._status = status
        self._body = body
        self._headers = headers

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


class WasiPlatformAdapter:
    """
    Platform adapter for WASI 0.3 (py2wasm / wasi-python build target).

    Uses the wasi:http/outgoing-handler WIT interface for network I/O.
    All system metrics return empty dicts — /proc is not available in the
    WASI sandbox.

    Note: The wasi_http_bindings shim is generated from the wasi:http WIT
    definition and must be bundled with the component. Until that shim is
    available this adapter falls back to a minimal urllib-based implementation
    for development/testing purposes.
    """

    async def http_get(
        self,
        url: str,
        headers: Dict[str, str],
        timeout: float = 30.0,
    ) -> _WasiHttpResponse:
        return await self._request("GET", url, headers=headers, body=None)

    async def http_post(
        self,
        url: str,
        json: dict,
        headers: Dict[str, str],
        timeout: float = 30.0,
    ) -> _WasiHttpResponse:
        import json as _json
        body = _json.dumps(json).encode("utf-8")
        merged = {"Content-Type": "application/json", **headers}
        return await self._request("POST", url, headers=merged, body=body)

    async def _request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: bytes | None,
    ) -> _WasiHttpResponse:
        """
        Dispatch an HTTP request via wasi:http or urllib fallback.

        In a compiled WASI component the wasi_http_client shim is used.
        Outside a WASI host we fall back to urllib so the adapter can be
        tested on native CPython.
        """
        try:
            # Future: from wasi_http import outgoing_handler
            # For now fall back to urllib (works on WASI via wasi:filesystem + wasi:sockets)
            return await self._urllib_request(method, url, headers, body)
        except Exception as exc:
            logger.error(f"WasiPlatformAdapter request failed: {exc}")
            raise

    @staticmethod
    async def _urllib_request(
        method: str,
        url: str,
        headers: Dict[str, str],
        body: bytes | None,
    ) -> _WasiHttpResponse:
        import asyncio
        import urllib.request

        def _sync():
            req = urllib.request.Request(url, data=body, method=method)
            for k, v in headers.items():
                req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return _WasiHttpResponse(
                    status=resp.status,
                    body=resp.read(),
                    headers=dict(resp.headers),
                )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync)

    def system_metrics(self) -> Dict[str, Any]:
        # /proc is unavailable in WASI sandbox
        return {}

    def is_wasm_capable(self) -> bool:
        # Inside a WASI host the engine executes components natively
        return True
