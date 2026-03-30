"""
NativePlatformAdapter — default adapter for CPython on native OS.

Uses httpx for HTTP and psutil (optional) for system metrics.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class _HttpxResponseWrapper:
    """Wraps an httpx.Response to satisfy the HttpResponse protocol."""

    def __init__(self, response) -> None:
        self._r = response

    @property
    def status_code(self) -> int:
        return self._r.status_code

    def json(self) -> dict:
        return self._r.json()

    def text(self) -> str:
        return self._r.text

    @property
    def headers(self) -> Dict[str, str]:
        return dict(self._r.headers)

    @property
    def content(self) -> bytes:
        return self._r.content


class NativePlatformAdapter:
    """
    Platform adapter for native CPython (POS terminals, ATMs, servers).

    HTTP:    httpx.AsyncClient (persistent connection pool)
    Metrics: psutil (optional; empty dict if not installed)
    WASM:    wasmtime ComponentModel (if wasmtime is installed)
    """

    def __init__(
        self,
        default_headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> None:
        self._default_headers = default_headers or {}
        self._timeout = timeout
        self._client = None  # lazy-initialised on first use

    # ------------------------------------------------------------------
    # Internal: ensure httpx client is alive
    # ------------------------------------------------------------------

    async def _get_client(self):
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:
                raise ImportError(
                    "httpx is required for NativePlatformAdapter. "
                    "Install it with: pip install httpx"
                ) from exc
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers=self._default_headers,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying httpx client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    async def http_get(
        self,
        url: str,
        headers: Dict[str, str],
        timeout: float = 30.0,
    ) -> _HttpxResponseWrapper:
        client = await self._get_client()
        response = await client.get(url, headers=headers, timeout=timeout)
        return _HttpxResponseWrapper(response)

    async def http_post(
        self,
        url: str,
        json: dict,
        headers: Dict[str, str],
        timeout: float = 30.0,
    ) -> _HttpxResponseWrapper:
        client = await self._get_client()
        response = await client.post(url, json=json, headers=headers, timeout=timeout)
        return _HttpxResponseWrapper(response)

    # ------------------------------------------------------------------
    # System metrics
    # ------------------------------------------------------------------

    def system_metrics(self) -> Dict[str, Any]:
        try:
            import psutil
            return {
                "cpu_percent": psutil.cpu_percent(interval=None),
                "mem_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage("/").percent,
            }
        except ImportError:
            return {}
        except Exception as exc:
            logger.debug(f"system_metrics error: {exc}")
            return {}

    # ------------------------------------------------------------------
    # WASM capability
    # ------------------------------------------------------------------

    def is_wasm_capable(self) -> bool:
        try:
            import wasmtime  # noqa: F401
            return True
        except ImportError:
            return False
