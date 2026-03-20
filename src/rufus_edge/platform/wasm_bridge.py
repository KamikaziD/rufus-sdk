"""
WasmBridge — Platform-aware WASM component execution abstraction.

Mirrors the structure of platform/base.py: a @runtime_checkable Protocol
plus three concrete implementations (Native / Pyodide / WASI) and an
auto-detect factory function.

The bridge is injected into ComponentStepRuntime so that WASM execution
transparently uses the correct runtime for the deployment environment
without any code changes in the workflow engine itself.
"""

from __future__ import annotations

import concurrent.futures
import os
import sys
from typing import Protocol, runtime_checkable


@runtime_checkable
class WasmBridgeProtocol(Protocol):
    """Minimal interface for executing a WASM/Component binary."""

    def execute_component(
        self,
        binary: bytes,
        state_json: str,
        step_name: str,
    ) -> str:
        """Synchronously execute a WASM component and return JSON string result.

        Args:
            binary:     Raw .wasm bytes (Component Model or core module).
            state_json: Serialized workflow state as a JSON object string.
            step_name:  The name of the step being executed.

        Returns:
            A JSON object string to be merged into workflow state.

        Raises:
            RuntimeError: On execution failure when the component returns an error.
        """
        ...

    def execute_batch(
        self,
        binary: bytes,
        states_json: list,
        step_name: str,
    ) -> list:
        """Execute N states through the component. Default: sequential loop.

        Override in platform bridges that support parallel execution
        (e.g. NativeWasmBridge with a dedicated ThreadPoolExecutor).

        Returns:
            List of JSON result strings, one per input state, in order.
        """
        return [self.execute_component(binary, s, step_name) for s in states_json]


# ---------------------------------------------------------------------------
# Native CPython implementation (wasmtime via ComponentStepRuntime)
# ---------------------------------------------------------------------------

class NativeWasmBridge:
    """CPython bridge: thin delegate to ComponentStepRuntime._call_component.

    Used on cloud servers and native edge devices where wasmtime is installed.
    This is the "zero overhead" path — no extra abstraction layer at runtime.
    """

    def execute_component(
        self,
        binary: bytes,
        state_json: str,
        step_name: str,
    ) -> str:
        from rufus.implementations.execution.component_runtime import (
            ComponentStepRuntime,
        )
        return ComponentStepRuntime._call_component(binary, state_json, step_name)

    def execute_batch(
        self,
        binary: bytes,
        states_json: list,
        step_name: str,
    ) -> list:
        """Parallel batch execution via a sized ThreadPoolExecutor.

        Each state is dispatched to a separate thread so N concurrent
        wasmtime calls run simultaneously instead of sequentially.
        Falls back to the sovereign-dispatcher Rust binary when available.
        """
        from rufus.implementations.execution.component_runtime import (
            ComponentStepRuntime,
        )
        _sovereign = _find_sovereign_dispatcher()
        if _sovereign is not None:
            return _run_sovereign_dispatcher(_sovereign, binary, states_json, step_name)
        max_workers = os.cpu_count() or 4
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            return list(pool.map(
                lambda s: ComponentStepRuntime._call_component(binary, s, step_name),
                states_json,
            ))


# ---------------------------------------------------------------------------
# Sovereign Dispatcher helpers (Rust subprocess fallback)
# ---------------------------------------------------------------------------

def _find_sovereign_dispatcher():
    """Return path to sovereign-dispatcher binary, or None if unavailable."""
    import pathlib
    import shutil

    env_path = os.environ.get("SOVEREIGN_DISPATCHER_PATH")
    if env_path:
        p = pathlib.Path(env_path)
        if p.is_file():
            return p

    # Relative path from this file: ../../../../src/rufus/wasm_component/sovereign_dispatcher/target/release/sovereign-dispatcher
    candidate = (
        pathlib.Path(__file__).resolve().parents[3]
        / "rufus"
        / "wasm_component"
        / "sovereign_dispatcher"
        / "target"
        / "release"
        / "sovereign-dispatcher"
    )
    if candidate.is_file():
        return candidate

    found = shutil.which("sovereign-dispatcher")
    if found:
        return pathlib.Path(found)

    return None


def _get_or_write_wasm_cache(wasm_hash: str, binary: bytes):
    """Write WASM binary to /tmp/rufus_wasm_cache/<hash>.wasm and return path."""
    import pathlib
    cache_dir = pathlib.Path("/tmp/rufus_wasm_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    wasm_path = cache_dir / f"{wasm_hash}.wasm"
    if not wasm_path.exists():
        wasm_path.write_bytes(binary)
    return wasm_path


def _run_sovereign_dispatcher(dispatcher_path, binary: bytes, states_json: list, step_name: str) -> list:
    """Invoke the Rust sovereign-dispatcher subprocess for batch WASM execution."""
    import hashlib
    import json
    import subprocess

    wasm_hash = hashlib.sha256(binary).hexdigest()
    wasm_path = _get_or_write_wasm_cache(wasm_hash, binary)

    payload = json.dumps({
        "wasm_path": str(wasm_path),
        "step_name": step_name,
        "sagas": [{"id": str(i), "payload": s} for i, s in enumerate(states_json)],
    })

    proc = subprocess.run(
        [str(dispatcher_path)],
        input=payload.encode(),
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"sovereign-dispatcher exited {proc.returncode}: {proc.stderr[:200]!r}"
        )
    result = json.loads(proc.stdout)
    if result.get("error"):
        raise RuntimeError(f"sovereign-dispatcher error: {result['error']}")
    return result["results"]


# ---------------------------------------------------------------------------
# Pyodide / Browser implementation
# ---------------------------------------------------------------------------

class PyodideWasmBridge:
    """Browser bridge: calls globalThis.rufusWasmExecute via Pyodide JS FFI.

    The host page must define window.rufusWasmExecute(wasm_bytes, state_json,
    step_name) → string (synchronous JS function) before starting the Python
    runtime.

    Component Model binaries (magic bytes \\x00asm\\x0e\\x00) are not supported
    in the browser path because the Pyodide WASM runtime cannot nest WASM
    instantiation.  Clear NotImplementedError is raised so callers can apply
    the fallback_on_error policy.
    """

    _CM_MAGIC = b"\x00asm\x0e\x00"

    def execute_component(
        self,
        binary: bytes,
        state_json: str,
        step_name: str,
    ) -> str:
        if binary[:6] == self._CM_MAGIC:
            raise NotImplementedError(
                "Component Model binaries (WASI 0.3) cannot be executed inside "
                "the Pyodide browser runtime.  Use a core WASM module compiled "
                "for wasm32-wasi, or run on a native edge device."
            )
        try:
            from js import rufusWasmExecute  # type: ignore[import]
            from pyodide.ffi import run_sync  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "PyodideWasmBridge requires Pyodide and a host page that exposes "
                "globalThis.rufusWasmExecute."
            ) from exc

        # run_sync wraps a JS Promise returned by the async JS function
        result = run_sync(rufusWasmExecute(binary, state_json, step_name))
        return str(result)


# ---------------------------------------------------------------------------
# WASI 0.3 compiled agent implementation
# ---------------------------------------------------------------------------

class WasiWasmBridge:
    """WASI bridge: delegates to WasmRuntime._execute_wasi (stdin/stdout).

    Used when the Rufus agent itself is compiled to wasm32 (WASI deployment).
    Nested Component Model instantiation raises NotImplementedError; callers
    should apply fallback_on_error='skip' or 'default' for WASI deployments.
    """

    _CM_MAGIC = b"\x00asm\x0e\x00"

    def execute_component(
        self,
        binary: bytes,
        state_json: str,
        step_name: str,
    ) -> str:
        if sys.platform == "wasm32" and binary[:6] == self._CM_MAGIC:
            raise NotImplementedError(
                "Component Model binary execution is not supported when the "
                "Rufus agent is running as a WASI module (sys.platform='wasm32'). "
                "The host environment must handle nested WASM instantiation."
            )
        from rufus.implementations.execution.wasm_runtime import WasmRuntime
        result_bytes = WasmRuntime._execute_wasi(
            binary,
            state_json.encode("utf-8"),
            step_name,
        )
        return result_bytes.decode("utf-8")


# ---------------------------------------------------------------------------
# Auto-detect factory
# ---------------------------------------------------------------------------

def detect_wasm_bridge() -> WasmBridgeProtocol:
    """Return the most appropriate WasmBridge for the current environment.

    Detection order:
    1. ``sys.platform == 'wasm32'``  → WasiWasmBridge
    2. ``js`` module importable      → PyodideWasmBridge
    3. Everything else               → NativeWasmBridge
    """
    if sys.platform == "wasm32":
        return WasiWasmBridge()

    try:
        import js  # noqa: F401 — only present in Pyodide
        return PyodideWasmBridge()
    except ImportError:
        pass

    return NativeWasmBridge()
