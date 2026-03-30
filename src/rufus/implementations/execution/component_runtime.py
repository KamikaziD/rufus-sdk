"""
ComponentStepRuntime — Component Model WASM executor for Rufus.

Supersedes the stdin/stdout WasmRuntime for modules compiled with the
WASI 0.3 / Component Model toolchain.

Detection logic
---------------
* Component Model magic: ``\\x00asm`` at offset 0 **and** version bytes ``\\x0e\\x00``
  at offset 4 (core modules use ``\\x01\\x00\\x00\\x00``).
* Anything else is treated as a core WASM module and routed to the legacy
  ``WasmRuntime`` stdin/stdout path (full backward compat).

Component contract
------------------
The component must export ``rufus:step/runner#execute`` as defined in
``src/rufus/wasm_component/step.wit``::

    execute: func(state-json: string, step-name: string) -> result<string, step-error>

Native execution uses ``wasmtime.component`` (``pip install wasmtime``).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared thread-pool executor for batch WASM dispatch.
#
# A singleton is intentional: 50,000 devices each with a private
# ThreadPoolExecutor(max_workers=14) would create 700,000 threads.
# The singleton keeps the total thread count at cpu_count.
# ---------------------------------------------------------------------------
_BATCH_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None


def _get_batch_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _BATCH_EXECUTOR
    if _BATCH_EXECUTOR is None:
        _BATCH_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
            max_workers=os.cpu_count() or 4,
            thread_name_prefix="rufus-wasm-batch",
        )
    return _BATCH_EXECUTOR

# Component Model magic: first 8 bytes of a .wasm Component
# Core module:  \x00asm\x01\x00\x00\x00
# Component:    \x00asm\x0e\x00\x01\x00
_CM_MAGIC = b"\x00asm\x0e\x00"


def is_component(binary: bytes) -> bool:
    """Return True if *binary* looks like a Component Model module."""
    return len(binary) >= 6 and binary[:6] == _CM_MAGIC


class ComponentStepRuntime:
    """
    Execute WASM step components via the Component Model typed interface.

    Falls back transparently to the legacy stdin/stdout ``WasmRuntime`` for
    old core-module binaries so that existing deployments keep working.

    Args:
        resolver: A ``WasmBinaryResolver`` that provides raw ``.wasm`` bytes.
        bridge:   Optional ``WasmBridgeProtocol`` for platform-specific execution.
                  When set, Component Model binaries are dispatched through the
                  bridge instead of the default ``_call_component`` (wasmtime) path.
                  The cloud path (bridge=None) is completely unchanged.
    """

    def __init__(self, resolver, bridge=None):
        self._resolver = resolver
        self._bridge = bridge
        # Cached legacy runtime — created on first core-module execution
        self._legacy_runtime = None

    async def execute(
        self,
        wasm_config,  # WasmConfig
        state_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a WASM step and return a dict to merge into workflow state.

        Routing:
        - Component Model binary → ``_run_component``
        - Core module binary    → legacy ``WasmRuntime._execute_wasi`` path
        """
        try:
            return await asyncio.wait_for(
                self._dispatch(wasm_config, state_data),
                timeout=wasm_config.timeout_ms / 1000,
            )
        except asyncio.TimeoutError:
            msg = (
                f"WASM step timed out after {wasm_config.timeout_ms}ms "
                f"(hash={wasm_config.wasm_hash})"
            )
            return self._handle_error(wasm_config, RuntimeError(msg))

    async def execute_batch(
        self,
        wasm_config,
        states: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Execute N states through the same WASM component in one event-loop round-trip.

        Resolves and hash-verifies the binary once, then dispatches all states
        to the batch executor (one run_in_executor call instead of N).

        Returns a list of result dicts in the same order as *states*.
        Falls back to legacy path for core-module (non-Component) binaries.
        """
        if not states:
            return []

        binary = await self._resolver.resolve(wasm_config.wasm_hash)
        actual_hash = hashlib.sha256(binary).hexdigest()
        if actual_hash != wasm_config.wasm_hash:
            raise RuntimeError(
                f"WASM binary hash mismatch: expected {wasm_config.wasm_hash}, "
                f"got {actual_hash}"
            )

        if not is_component(binary):
            # Legacy path: run sequentially (core modules have stdin/stdout overhead anyway)
            return [await self._run_legacy(binary, wasm_config, s) for s in states]

        # Apply state_mapping once per call (same mapping for all states)
        if wasm_config.state_mapping:
            mapped_states = [
                {
                    wasm_key: s.get(state_key)
                    for state_key, wasm_key in wasm_config.state_mapping.items()
                }
                for s in states
            ]
        else:
            mapped_states = states

        step_name = getattr(wasm_config, "entrypoint", "execute")
        states_json = [json.dumps(s) for s in mapped_states]

        loop = asyncio.get_event_loop()
        _bridge = self._bridge

        try:
            if _bridge is not None:
                results_json = await loop.run_in_executor(
                    _get_batch_executor(),
                    lambda: (
                        _bridge.execute_batch(binary, states_json, step_name)
                        if hasattr(_bridge, "execute_batch")
                        else [_bridge.execute_component(binary, s, step_name) for s in states_json]
                    ),
                )
            else:
                # Cloud path — wasmtime direct, parallelised in the batch executor
                results_json = await loop.run_in_executor(
                    _get_batch_executor(),
                    lambda: [self._call_component(binary, s, step_name) for s in states_json],
                )
        except Exception as exc:
            return [self._handle_error(wasm_config, exc)] * len(states)

        output: List[Dict[str, Any]] = []
        for rj in results_json:
            try:
                r = json.loads(rj)
                if isinstance(r, dict):
                    output.append(r)
                else:
                    output.append(self._handle_error(
                        wasm_config,
                        RuntimeError(f"Non-dict result: {type(r).__name__}"),
                    ))
            except json.JSONDecodeError:
                output.append(self._handle_error(
                    wasm_config,
                    RuntimeError(f"Non-JSON: {rj[:200]!r}"),
                ))
        return output

    async def _dispatch(self, wasm_config, state_data: Dict[str, Any]) -> Dict[str, Any]:
        binary = await self._resolver.resolve(wasm_config.wasm_hash)

        # Verify integrity
        actual_hash = hashlib.sha256(binary).hexdigest()
        if actual_hash != wasm_config.wasm_hash:
            raise RuntimeError(
                f"WASM binary hash mismatch: expected {wasm_config.wasm_hash}, "
                f"got {actual_hash}"
            )

        if is_component(binary):
            return await self._run_component(binary, wasm_config, state_data)
        else:
            return await self._run_legacy(binary, wasm_config, state_data)

    # ------------------------------------------------------------------
    # Component Model path (wasmtime.component)
    # ------------------------------------------------------------------

    async def _run_component(
        self,
        binary: bytes,
        wasm_config,
        state_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a Component Model binary via wasmtime.component."""
        if wasm_config.state_mapping:
            input_data = {
                wasm_key: state_data.get(state_key)
                for state_key, wasm_key in wasm_config.state_mapping.items()
            }
        else:
            input_data = state_data

        state_json = json.dumps(input_data)
        step_name = getattr(wasm_config, "entrypoint", "execute")

        loop = asyncio.get_event_loop()
        try:
            if self._bridge is not None:
                # Platform-specific bridge (edge / browser / WASI path)
                _bridge = self._bridge
                result_json = await loop.run_in_executor(
                    None,
                    lambda: _bridge.execute_component(binary, state_json, step_name),
                )
            elif "js" in __import__("sys").modules or "pyodide" in __import__("sys").modules:
                # Browser / Pyodide — dispatch through js.WebAssembly
                try:
                    result_json = await self._run_component_browser(binary, state_json, step_name)
                except Exception as _browser_exc:
                    return self._handle_error(wasm_config, _browser_exc)
            else:
                # Default cloud/native path — wasmtime direct call
                try:
                    result_json = await loop.run_in_executor(
                        None,
                        lambda: self._call_component(binary, state_json, step_name),
                    )
                except ImportError:
                    # WASI host: the surrounding runtime executes the component;
                    # we just return empty dict and let the host handle state passing
                    logger.warning(
                        "wasmtime not available and no bridge set — running in WASI host mode "
                        "(state passing is managed by the host runtime)"
                    )
                    result_json = "{}"
        except Exception as exc:
            return self._handle_error(wasm_config, exc)

        try:
            result = json.loads(result_json)
        except json.JSONDecodeError as exc:
            return self._handle_error(
                wasm_config,
                RuntimeError(f"Component returned non-JSON: {result_json[:200]!r}"),
            )

        if not isinstance(result, dict):
            return self._handle_error(
                wasm_config,
                RuntimeError(
                    f"Component result must be a JSON object, got {type(result).__name__}"
                ),
            )
        return result

    @staticmethod
    def _call_component(binary: bytes, state_json: str, step_name: str) -> str:
        """Synchronous Component Model call — runs in thread-pool executor."""
        try:
            from wasmtime import Engine, Store, Config  # type: ignore[import]
            from wasmtime.component import Component, Linker  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "wasmtime ≥ 20 with Component Model support is required. "
                "Install it with: pip install wasmtime"
            ) from exc

        config = Config()
        config.async_support = False
        engine = Engine(config)
        store = Store(engine)
        component = Component(engine, binary)
        linker = Linker(engine)

        # Add WASI preview2 to the linker (needed by most components)
        try:
            from wasmtime.component import add_to_linker as add_wasi  # type: ignore[import]
            add_wasi(linker)
        except Exception:
            pass  # Component may not need WASI

        instance = linker.instantiate(store, component)

        # Resolve the exported function: rufus:step/runner#execute
        try:
            # Try canonical interface path first
            runner = instance.exports(store).get("rufus:step/runner")
            if runner is not None:
                execute_fn = runner.get("execute")
            else:
                # Fallback: flat export named "execute"
                execute_fn = instance.exports(store).get("execute")
        except Exception:
            execute_fn = instance.exports(store).get("execute")

        if execute_fn is None:
            raise RuntimeError(
                "Component does not export 'rufus:step/runner#execute' or 'execute'. "
                "Ensure the component implements the rufus:step/runner interface."
            )

        # Call: execute(state_json: string, step_name: string) -> result<string, step-error>
        outcome = execute_fn(store, state_json, step_name)

        # wasmtime returns a Python Result-like value (ok/err variant)
        if hasattr(outcome, "value"):
            # Variant: outcome.tag == 0 (ok) or 1 (err)
            if outcome.tag == 0:
                return outcome.value
            else:
                err = outcome.value
                code = getattr(err, "code", "UNKNOWN")
                message = getattr(err, "message", str(err))
                raise RuntimeError(f"Component step error [{code}]: {message}")
        # Some bindings return the value directly on ok, raise on err
        return str(outcome)

    async def _run_component_browser(
        self,
        binary: bytes,
        state_json: str,
        step_name: str,
    ) -> str:
        """Execute a Component Model binary via js.WebAssembly (Pyodide/browser)."""
        try:
            import js  # noqa: F401 — only present in Pyodide
            import pyodide  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "Browser execution requires Pyodide runtime."
            ) from exc

        # cm-js polyfill: window.ComponentModel.run(wasmBytes, stateJson, stepName)
        # This is a thin JS shim that wraps the Component Model Polyfill.
        # See docs/browser-component-polyfill.md for setup instructions.
        import js as _js
        wasm_bytes = _js.Uint8Array.new(list(binary))
        result = await _js.ComponentModel.run(wasm_bytes, state_json, step_name)
        return str(result)

    # ------------------------------------------------------------------
    # Legacy stdin/stdout path
    # ------------------------------------------------------------------

    async def _run_legacy(
        self,
        binary: bytes,
        wasm_config,
        state_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Delegate to the legacy WasmRuntime stdin/stdout path."""
        # Import here to avoid circular dependency
        from rufus.implementations.execution.wasm_runtime import WasmRuntime
        if self._legacy_runtime is None:
            self._legacy_runtime = WasmRuntime(self._resolver)

        logger.debug(
            f"WASM binary {wasm_config.wasm_hash[:16]}… is a core module; "
            "using legacy stdin/stdout path"
        )

        if wasm_config.state_mapping:
            input_data = {
                wasm_key: state_data.get(state_key)
                for state_key, wasm_key in wasm_config.state_mapping.items()
            }
        else:
            input_data = state_data

        stdin_bytes = json.dumps(input_data).encode("utf-8")

        loop = asyncio.get_event_loop()
        try:
            _lr = self._legacy_runtime
            result_bytes = await loop.run_in_executor(
                None,
                lambda: WasmRuntime._execute_wasi(
                    binary, stdin_bytes, wasm_config.entrypoint
                ) if _lr is None else _lr._execute_wasi(binary, stdin_bytes, wasm_config.entrypoint),
            )
        except Exception as exc:
            return self._handle_error(wasm_config, exc)

        try:
            result = json.loads(result_bytes)
        except json.JSONDecodeError:
            return self._handle_error(
                wasm_config,
                RuntimeError(f"WASM stdout is not valid JSON: {result_bytes[:200]!r}"),
            )

        if not isinstance(result, dict):
            return self._handle_error(
                wasm_config,
                RuntimeError(
                    f"WASM result must be a JSON object, got {type(result).__name__}"
                ),
            )
        return result

    # ------------------------------------------------------------------
    # Error policy
    # ------------------------------------------------------------------

    def _handle_error(self, wasm_config, exc: Exception) -> Dict[str, Any]:
        mode = wasm_config.fallback_on_error
        if mode == "skip":
            logger.warning(f"WASM/Component step error (skip): {exc}")
            return {}
        if mode == "default":
            logger.warning(f"WASM/Component step error (default): {exc}")
            return wasm_config.default_result or {}
        raise RuntimeError(str(exc)) from exc
