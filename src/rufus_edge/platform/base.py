"""
Platform Adapter Protocol — shared I/O abstraction for native, WASI, and browser targets.

All network I/O and system metrics in rufus_edge go through a PlatformAdapter so that
the same Python code can run on:

  - Native CPython  (NativePlatformAdapter  — httpx + psutil)
  - WASI 0.3        (WasiPlatformAdapter    — wasi:http shim + stubs)
  - Pyodide/browser (PyodidePlatformAdapter — js.fetch + wa-sqlite + stub metrics)
"""

from __future__ import annotations

from typing import Any, Dict, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# HTTP response wrapper
# ---------------------------------------------------------------------------

class HttpResponse(Protocol):
    """Minimal HTTP response surface used by SyncManager / ConfigManager."""

    @property
    def status_code(self) -> int: ...

    def json(self) -> dict: ...

    def text(self) -> str: ...

    @property
    def headers(self) -> Dict[str, str]: ...

    @property
    def content(self) -> bytes: ...


# ---------------------------------------------------------------------------
# Null / stub metrics (used by WASI + Pyodide where psutil is unavailable)
# ---------------------------------------------------------------------------

class NullSystemMetrics:
    """Returns empty metrics dict; used when psutil is not available."""

    def collect(self) -> Dict[str, Any]:
        return {}


# ---------------------------------------------------------------------------
# PlatformAdapter Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class PlatformAdapter(Protocol):
    """
    Abstraction layer for platform-specific I/O operations.

    Implementations:
      NativePlatformAdapter  — uses httpx + psutil (default on CPython)
      WasiPlatformAdapter    — uses wasi:http + stubs (WASI 0.3 target)
      PyodidePlatformAdapter — uses js.fetch + stub metrics (browser/Pyodide)
    """

    async def http_get(
        self,
        url: str,
        headers: Dict[str, str],
        timeout: float = 30.0,
    ) -> HttpResponse:
        """Perform an HTTP GET request."""
        ...

    async def http_post(
        self,
        url: str,
        json: dict,
        headers: Dict[str, str],
        timeout: float = 30.0,
    ) -> HttpResponse:
        """Perform an HTTP POST request with a JSON body."""
        ...

    def system_metrics(self) -> Dict[str, Any]:
        """
        Return a dict with cpu_percent, mem_percent, disk_percent (0–100).
        Return an empty dict if metrics are unavailable on this platform.
        """
        ...

    def is_wasm_capable(self) -> bool:
        """Return True if this platform can execute WASM Component steps inline."""
        ...
