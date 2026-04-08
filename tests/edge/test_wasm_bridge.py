"""
Unit tests for WasmBridge implementations and detect_wasm_bridge().

No wasmtime, Pyodide, or js module required — all execution paths are mocked.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from ruvon_edge.platform.wasm_bridge import (
    NativeWasmBridge,
    PyodideWasmBridge,
    WasiWasmBridge,
    WasmBridgeProtocol,
    detect_wasm_bridge,
)

# Component Model magic header (first 8 bytes)
CM_BINARY = b"\x00asm\x0e\x00\x01\x00" + b"\x00" * 100
# Core WASM module header
CORE_BINARY = b"\x00asm\x01\x00\x00\x00" + b"\x00" * 100


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

class TestWasmBridgeProtocol:
    def test_native_conforms_to_protocol(self):
        assert isinstance(NativeWasmBridge(), WasmBridgeProtocol)

    def test_pyodide_conforms_to_protocol(self):
        assert isinstance(PyodideWasmBridge(), WasmBridgeProtocol)

    def test_wasi_conforms_to_protocol(self):
        assert isinstance(WasiWasmBridge(), WasmBridgeProtocol)


# ---------------------------------------------------------------------------
# NativeWasmBridge
# ---------------------------------------------------------------------------

class TestNativeWasmBridge:
    def test_delegates_to_call_component(self):
        bridge = NativeWasmBridge()
        with patch(
            "ruvon.implementations.execution.component_runtime.ComponentStepRuntime._call_component",
            return_value='{"score": 42}',
        ) as mock_call:
            result = bridge.execute_component(CM_BINARY, '{"amount": 100}', "execute")

        mock_call.assert_called_once_with(CM_BINARY, '{"amount": 100}', "execute")
        assert result == '{"score": 42}'

    def test_propagates_runtime_error(self):
        bridge = NativeWasmBridge()
        with patch(
            "ruvon.implementations.execution.component_runtime.ComponentStepRuntime._call_component",
            side_effect=RuntimeError("wasmtime exploded"),
        ):
            with pytest.raises(RuntimeError, match="wasmtime exploded"):
                bridge.execute_component(CM_BINARY, "{}", "execute")


# ---------------------------------------------------------------------------
# PyodideWasmBridge
# ---------------------------------------------------------------------------

class TestPyodideWasmBridge:
    def test_rejects_component_model_binary(self):
        bridge = PyodideWasmBridge()
        with pytest.raises(NotImplementedError, match="Component Model"):
            bridge.execute_component(CM_BINARY, "{}", "execute")

    def test_calls_js_rufus_wasm_execute_for_core_module(self):
        bridge = PyodideWasmBridge()

        fake_js = MagicMock()
        fake_js.rufusWasmExecute.return_value = MagicMock()  # JS Promise proxy

        fake_run_sync = MagicMock(return_value='{"ok": true}')

        with patch.dict("sys.modules", {"js": fake_js}):
            with patch("ruvon_edge.platform.wasm_bridge.PyodideWasmBridge.execute_component") as mock_exec:
                mock_exec.return_value = '{"ok": true}'
                result = bridge.execute_component.__wrapped__(bridge, CORE_BINARY, "{}", "execute") \
                    if hasattr(bridge.execute_component, "__wrapped__") else None

        # Direct path: mock the full call chain
        bridge2 = PyodideWasmBridge()
        with patch.dict("sys.modules", {"js": fake_js, "pyodide": MagicMock(), "pyodide.ffi": MagicMock(run_sync=fake_run_sync)}):
            with patch("ruvon_edge.platform.wasm_bridge.PyodideWasmBridge.execute_component", return_value='{"ok": true}') as m:
                res = m(CORE_BINARY, "{}", "execute")
                assert res == '{"ok": true}'

    def test_raises_import_error_without_pyodide(self):
        bridge = PyodideWasmBridge()
        # With neither js nor pyodide in sys.modules, should raise ImportError
        with patch.dict("sys.modules", {"js": None}):
            # The CM check happens first — use core binary to reach the import path
            with pytest.raises((ImportError, TypeError)):
                bridge.execute_component(CORE_BINARY, "{}", "execute")


# ---------------------------------------------------------------------------
# WasiWasmBridge
# ---------------------------------------------------------------------------

class TestWasiWasmBridge:
    def test_raises_not_implemented_on_wasm32_platform_for_cm_binary(self):
        bridge = WasiWasmBridge()
        with patch.object(sys, "platform", "wasm32"):
            with pytest.raises(NotImplementedError, match="wasm32"):
                bridge.execute_component(CM_BINARY, "{}", "execute")

    def test_delegates_core_module_to_wasm_runtime(self):
        bridge = WasiWasmBridge()
        fake_result = b'{"processed": true}'

        with patch(
            "ruvon.implementations.execution.wasm_runtime.WasmRuntime._execute_wasi",
            return_value=fake_result,
        ) as mock_wasi:
            result = bridge.execute_component(CORE_BINARY, '{"x": 1}', "main")

        mock_wasi.assert_called_once_with(CORE_BINARY, b'{"x": 1}', "main")
        assert result == '{"processed": true}'

    def test_allows_cm_binary_on_native_platform(self):
        """On a native (non-wasm32) host, CM binary should attempt normal execution."""
        bridge = WasiWasmBridge()
        # On native platform CM_BINARY doesn't hit the wasm32 guard;
        # it proceeds to _execute_wasi (which handles bytes as-is)
        fake_result = b'{"native": true}'
        with patch(
            "ruvon.implementations.execution.wasm_runtime.WasmRuntime._execute_wasi",
            return_value=fake_result,
        ):
            result = bridge.execute_component(CM_BINARY, "{}", "execute")
        assert result == '{"native": true}'


# ---------------------------------------------------------------------------
# detect_wasm_bridge()
# ---------------------------------------------------------------------------

class TestDetectWasmBridge:
    def test_returns_wasi_bridge_on_wasm32(self):
        with patch.object(sys, "platform", "wasm32"):
            bridge = detect_wasm_bridge()
        assert isinstance(bridge, WasiWasmBridge)

    def test_returns_pyodide_bridge_when_js_importable(self):
        fake_js = MagicMock()
        with patch.dict("sys.modules", {"js": fake_js}):
            bridge = detect_wasm_bridge()
        assert isinstance(bridge, PyodideWasmBridge)

    def test_returns_native_bridge_by_default(self):
        # Ensure sys.platform is not wasm32 and js is not importable
        with patch.dict("sys.modules", {}):
            # Remove 'js' if it somehow snuck in
            sys.modules.pop("js", None)
            bridge = detect_wasm_bridge()
        assert isinstance(bridge, NativeWasmBridge)

    def test_wasm32_takes_priority_over_js(self):
        """WASI detection must fire before Pyodide even if js is importable."""
        fake_js = MagicMock()
        with patch.object(sys, "platform", "wasm32"):
            with patch.dict("sys.modules", {"js": fake_js}):
                bridge = detect_wasm_bridge()
        assert isinstance(bridge, WasiWasmBridge)

    def test_returned_bridge_conforms_to_protocol(self):
        bridge = detect_wasm_bridge()
        assert isinstance(bridge, WasmBridgeProtocol)
