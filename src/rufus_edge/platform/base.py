"""
PlatformAdapter — Abstract I/O interface for rufus-sdk-edge.

Abstracts HTTP and system-metrics access so the edge agent can run in three
environments without code changes:
  - Native CPython  (NativePlatformAdapter)
  - Browser/Pyodide (PyodidePlatformAdapter)
  - WASI 0.3        (WasiPlatformAdapter)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Shared data structures
# ---------------------------------------------------------------------------

@dataclass
class HttpResponse:
    """Minimal HTTP response carrier."""
    status_code: int
    body: bytes
    headers: Dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        import json
        return json.loads(self.body)

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    @property
    def content(self) -> bytes:
        return self.body


@dataclass
class SystemMetrics:
    """Lightweight system-metrics snapshot."""
    cpu_percent: float = 0.0
    memory_used_mb: float = 0.0
    memory_total_mb: float = 0.0
    disk_free_mb: float = 0.0


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class PlatformAdapter(Protocol):
    """
    Minimal I/O surface required by SyncManager and ConfigManager.

    Implementations must be safe to call from inside an asyncio event loop.
    """

    async def http_get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        """Perform an async HTTP GET."""
        ...

    async def http_post(
        self,
        url: str,
        body: bytes,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        """Perform an async HTTP POST with a raw bytes body."""
        ...

    def get_system_metrics(self) -> SystemMetrics:
        """Return current system metrics.  Stubs return all-zeros."""
        ...
