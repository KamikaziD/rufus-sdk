"""
rufus_edge.platform — Platform I/O abstraction layer.

Exports:
  PlatformAdapter     — Protocol (for type hints / isinstance checks)
  NullSystemMetrics   — Stub metrics for WASM/browser environments
  detect_platform()   — Auto-selects the right adapter for the current runtime
  get_adapter()       — Module-level singleton accessor
"""

from __future__ import annotations

import sys
from typing import Optional

from rufus_edge.platform.base import HttpResponse, NullSystemMetrics, PlatformAdapter

__all__ = [
    "HttpResponse",
    "NullSystemMetrics",
    "PlatformAdapter",
    "detect_platform",
    "get_adapter",
]

_adapter: Optional[PlatformAdapter] = None


def detect_platform() -> PlatformAdapter:
    """
    Detect the current runtime and return the appropriate PlatformAdapter.

    Detection order:
      1. sys.platform == 'wasm32'  → WasiPlatformAdapter
      2. 'pyodide' in sys.modules  → PyodidePlatformAdapter
      3. otherwise                 → NativePlatformAdapter
    """
    if sys.platform == "wasm32":
        from rufus_edge.platform.wasi import WasiPlatformAdapter
        return WasiPlatformAdapter()

    if "pyodide" in sys.modules or "js" in sys.modules:
        from rufus_edge.platform.pyodide import PyodidePlatformAdapter
        return PyodidePlatformAdapter()

    from rufus_edge.platform.native import NativePlatformAdapter
    return NativePlatformAdapter()


def get_adapter() -> PlatformAdapter:
    """
    Return the module-level singleton adapter, creating it on first call.

    Individual components (SyncManager, ConfigManager) may also accept an
    explicit adapter= argument to override the singleton.
    """
    global _adapter
    if _adapter is None:
        _adapter = detect_platform()
    return _adapter
