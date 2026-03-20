"""
rufus_edge.platform — Environment-aware I/O abstraction.

Usage::

    from rufus_edge.platform import detect_platform, PlatformAdapter

    adapter = detect_platform()   # auto-selects based on sys.platform / Pyodide
"""

from __future__ import annotations

import sys
from typing import Optional

from rufus_edge.platform.base import HttpResponse, PlatformAdapter, SystemMetrics
from rufus_edge.platform.wasm_bridge import (
    WasmBridgeProtocol,
    NativeWasmBridge,
    PyodideWasmBridge,
    WasiWasmBridge,
    detect_wasm_bridge,
)


def detect_platform(
    default_headers: Optional[dict] = None,
) -> "PlatformAdapter":
    """
    Return the most appropriate PlatformAdapter for the current environment.

    Detection order:
    1. WASI (`sys.platform == 'wasm32'`) → WasiPlatformAdapter
    2. Pyodide (`js` module importable)  → PyodidePlatformAdapter
    3. Everything else                   → NativePlatformAdapter
    """
    if sys.platform == "wasm32":
        from rufus_edge.platform.wasi import WasiPlatformAdapter
        return WasiPlatformAdapter(default_headers=default_headers)

    try:
        import js  # noqa: F401 — only present in Pyodide
        from rufus_edge.platform.pyodide import PyodidePlatformAdapter
        return PyodidePlatformAdapter(default_headers=default_headers)
    except ImportError:
        pass

    from rufus_edge.platform.native import NativePlatformAdapter
    return NativePlatformAdapter(default_headers=default_headers)


__all__ = [
    "PlatformAdapter",
    "HttpResponse",
    "SystemMetrics",
    "detect_platform",
    "WasmBridgeProtocol",
    "NativeWasmBridge",
    "PyodideWasmBridge",
    "WasiWasmBridge",
    "detect_wasm_bridge",
]
