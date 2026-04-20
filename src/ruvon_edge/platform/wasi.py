"""
WasiPlatformAdapter — WASI 0.3 implementation.

Used when ruvon-edge is compiled to a WASM/WASI target via py2wasm.

HTTP is performed through the `wasi:http/outgoing-handler` host binding.
Because WASI 0.3 supports async natively, we can await the response directly.

SQLite access is via aiosqlite + `wasi:filesystem` (unchanged from native).

psutil is not available → SystemMetrics always returns zeros.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, Optional

from ruvon_edge.platform.base import HttpResponse, SystemMetrics

logger = logging.getLogger(__name__)


class WasiPlatformAdapter:
    """
    PlatformAdapter for WASI 0.3 environments.

    HTTP is routed through the WASI outgoing-handler import.  The host
    (e.g. wasmtime with --wasi http) must grant the `wasi:http` capability.

    When running native Python (e.g. tests), falls back to httpx so the
    adapter is still exercisable without a WASI runtime.
    """

    def __init__(self, default_headers: Optional[Dict[str, str]] = None):
        self._default_headers: Dict[str, str] = default_headers or {}
        self._in_wasi = self._detect_wasi()

    @staticmethod
    def _detect_wasi() -> bool:
        import sys
        return sys.platform == "wasm32"

    async def http_get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        if self._in_wasi:
            return await self._wasi_request("GET", url, None, headers)
        # Fallback to httpx when running tests natively
        return await self._httpx_get(url, headers, timeout)

    async def http_post(
        self,
        url: str,
        body: bytes,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        if self._in_wasi:
            return await self._wasi_request("POST", url, body, headers)
        return await self._httpx_post(url, body, headers, timeout)

    def get_system_metrics(self) -> SystemMetrics:
        # psutil / procfs are unavailable in a WASI sandbox
        return SystemMetrics()

    # ------------------------------------------------------------------
    # WASI outgoing-handler path
    # ------------------------------------------------------------------

    async def _wasi_request(
        self,
        method: str,
        url: str,
        body: Optional[bytes],
        extra_headers: Optional[Dict[str, str]],
    ) -> HttpResponse:
        """Route through wasi:http/outgoing-handler."""
        try:
            # wasi:http Python bindings (generated from WIT)
            from wasi.http.outgoing_handler import handle  # type: ignore[import]
            from wasi.http.types import (  # type: ignore[import]
                OutgoingRequest,
                Headers,
                Method,
                Scheme,
            )
        except ImportError as exc:
            raise ImportError(
                "wasi:http bindings not found. "
                "This adapter must run inside a WASI 0.3 environment."
            ) from exc

        merged = {**self._default_headers, **(extra_headers or {})}
        req = OutgoingRequest(
            Headers.from_list(list(merged.items())),
            Method.get if method == "GET" else Method.post,
            None,   # path-with-query set below
            Scheme.https if url.startswith("https") else Scheme.http,
            url,
        )
        if body:
            stream = req.body()
            stream.write(body)
            OutgoingRequest.finish(stream)

        future = handle(req, None)
        resp = future.get()

        status = resp.status()
        resp_body = b"".join(resp.consume().read(65536) for _ in range(1024))
        return HttpResponse(
            status_code=status,
            body=resp_body,
            headers=dict(resp.headers().entries()),
        )

    # ------------------------------------------------------------------
    # httpx fallback (native tests only)
    # ------------------------------------------------------------------

    async def _httpx_get(self, url, headers, timeout):
        import httpx
        merged = {**self._default_headers, **(headers or {})}
        async with httpx.AsyncClient() as c:
            r = await c.get(url, headers=merged, timeout=timeout)
            return HttpResponse(r.status_code, r.content, dict(r.headers))

    async def _httpx_post(self, url, body, headers, timeout):
        import httpx
        merged = {
            "Content-Type": "application/json",
            **self._default_headers,
            **(headers or {}),
        }
        async with httpx.AsyncClient() as c:
            r = await c.post(url, content=body, headers=merged, timeout=timeout)
            return HttpResponse(r.status_code, r.content, dict(r.headers))
