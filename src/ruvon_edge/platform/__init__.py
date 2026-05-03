"""
ruvon_edge.platform — Environment-aware I/O abstraction.

Usage::

    from ruvon_edge.platform import detect_platform, get_adapter, PlatformAdapter

    adapter = detect_platform()   # auto-selects based on sys.platform / Pyodide
    adapter = get_adapter()       # module-level singleton (created on first call)
"""

from __future__ import annotations

import sys
from typing import Optional

from ruvon_edge.platform.base import HttpResponse, PlatformAdapter, SystemMetrics
from ruvon_edge.platform.wasm_bridge import (
    WasmBridgeProtocol,
    NativeWasmBridge,
    PyodideWasmBridge,
    WasiWasmBridge,
    detect_wasm_bridge,
)

_adapter: Optional[PlatformAdapter] = None


def detect_platform() -> "PlatformAdapter":
    """
    Return the most appropriate PlatformAdapter for the current environment.

    Detection order:
    1. WASI (`sys.platform == 'wasm32'`) → WasiPlatformAdapter
    2. Pyodide (`pyodide` or `js` in sys.modules) → PyodidePlatformAdapter
    3. Everything else → NativePlatformAdapter
    """
    if sys.platform == "wasm32":
        from ruvon_edge.platform.wasi import WasiPlatformAdapter
        return WasiPlatformAdapter()

    if "pyodide" in sys.modules or "js" in sys.modules:
        from ruvon_edge.platform.pyodide import PyodidePlatformAdapter
        return PyodidePlatformAdapter()

    from ruvon_edge.platform.native import NativePlatformAdapter
    return NativePlatformAdapter()


def get_adapter() -> "PlatformAdapter":
    """
    Return the module-level singleton adapter, creating it on first call.

    Individual components (SyncManager, ConfigManager) may also accept an
    explicit platform_adapter= argument to override the singleton.
    """
    global _adapter
    if _adapter is None:
        _adapter = detect_platform()
    return _adapter


__all__ = [
    "PlatformAdapter",
    "HttpResponse",
    "SystemMetrics",
    "detect_platform",
    "get_adapter",
    "WasmBridgeProtocol",
    "NativeWasmBridge",
    "PyodideWasmBridge",
    "WasiWasmBridge",
    "detect_wasm_bridge",
]
