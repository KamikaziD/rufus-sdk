"""
NativePlatformAdapter — CPython implementation using httpx + psutil.

This is the default adapter used on native Python deployments (POS terminals,
server-side workers, development machines).
"""

from __future__ import annotations

import json
import logging
from typing import Dict, Optional

from rufus_edge.platform.base import HttpResponse, PlatformAdapter, SystemMetrics

logger = logging.getLogger(__name__)


class NativePlatformAdapter:
    """Concrete PlatformAdapter backed by httpx and psutil."""

    def __init__(self, default_headers: Optional[Dict[str, str]] = None):
        """
        Args:
            default_headers: Headers merged into every request (e.g. auth headers).
        """
        self._default_headers: Dict[str, str] = default_headers or {}
        self._client = None  # Lazy; created on first use

    async def _get_client(self):
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:
                raise ImportError(
                    "httpx is required for NativePlatformAdapter. "
                    "Install it with: pip install httpx"
                ) from exc
            self._client = httpx.AsyncClient()
        return self._client

    async def http_get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        merged = {**self._default_headers, **(headers or {})}
        client = await self._get_client()
        try:
            import httpx
            resp = await client.get(url, headers=merged, timeout=timeout)
            return HttpResponse(
                status_code=resp.status_code,
                body=resp.content,
                headers=dict(resp.headers),
            )
        except Exception as exc:  # network errors → status 0
            logger.debug(f"http_get error [{url}]: {exc}")
            raise

    async def http_post(
        self,
        url: str,
        body: bytes,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        merged = {
            "Content-Type": "application/json",
            **self._default_headers,
            **(headers or {}),
        }
        client = await self._get_client()
        try:
            resp = await client.post(url, content=body, headers=merged, timeout=timeout)
            return HttpResponse(
                status_code=resp.status_code,
                body=resp.content,
                headers=dict(resp.headers),
            )
        except Exception as exc:
            logger.debug(f"http_post error [{url}]: {exc}")
            raise

    def get_system_metrics(self) -> SystemMetrics:
        try:
            import psutil
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            return SystemMetrics(
                cpu_percent=psutil.cpu_percent(interval=None),
                memory_used_mb=mem.used / 1_048_576,
                memory_total_mb=mem.total / 1_048_576,
                disk_free_mb=disk.free / 1_048_576,
            )
        except Exception:
            return SystemMetrics()

    async def aclose(self):
        """Release the underlying httpx client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
