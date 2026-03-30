"""
ComponentStepRuntime — WASM Component Model executor for Rufus workflow steps.

Replaces the stdin/stdout-based WasmRuntime for binaries that implement the
rufus:step@0.1.0 WIT interface.  Maintains full backward compatibility: if the
binary is a legacy core WASM module it delegates to WasmRuntime._execute_wasi().

Detection logic (per spec §8):
  - binary[:8] == b'\\x00asm\\x0d\\x00\\x01\\x00'  → Component Model → _run_component()
  - binary[:8] == b'\\x00asm\\x01\\x00\\x00\\x00'  → Core module   → _run_legacy_wasi()

Platform dispatch:
  - Native CPython: wasmtime.component Python bindings
  - Browser (Pyodide): js.WebAssembly + Component Model polyfill (cm-js)
  - WASI host: component is executed by the surrounding host runtime
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any, Dict

from rufus.wasm_component import is_component
from rufus.implementations.execution.wasm_runtime import WasmBinaryResolver, WasmRuntime

logger = logging.getLogger(__name__)


class ComponentStepRuntime:
    """
    Executes WASM Component Model steps (rufus:step@0.1.0 world).

    Falls back to the legacy WasmRuntime for core WASM modules so that
    existing binaries continue to work without recompilation.

    Args:
        resolver: WasmBinaryResolver that supplies raw .wasm bytes.
    """

    def __init__(self, resolver: WasmBinaryResolver) -> None:
        self._resolver = resolver
        self._legacy_runtime = WasmRuntime(resolver)

    async def execute(
        self,
        wasm_config,  # WasmConfig — imported at call site to avoid circular imports
        state_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a WASM step, auto-detecting Component Model vs legacy core module.

        Args:
            wasm_config: WasmConfig instance (hash, entrypoint, mapping, timeout).
            state_data:  Current workflow state as a plain dict.

        Returns:
            Dict to be merged into workflow state.

        Raises:
            RuntimeError: On execution error (when fallback_on_error='fail').
            FileNotFoundError: If the binary cannot be resolved.
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
        except Exception as exc:
            return self._handle_error(wasm_config, exc)

    async def _dispatch(
        self,
        wasm_config,
        state_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        binary = await self._resolver.resolve(wasm_config.wasm_hash)

        # Integrity check
        actual_hash = hashlib.sha256(binary).hexdigest()
        if actual_hash != wasm_config.wasm_hash:
            raise RuntimeError(
                f"WASM binary hash mismatch: expected {wasm_config.wasm_hash}, "
                f"got {actual_hash}"
            )

        if is_component(binary):
            return await self._run_component(binary, wasm_config, state_data)
        else:
            return await self._run_legacy_wasi(wasm_config, state_data)

    # ------------------------------------------------------------------
    # Component Model path
    # ------------------------------------------------------------------

    async def _run_component(
        self,
        binary: bytes,
        wasm_config,
        state_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a Component Model binary via wasmtime.component (native)
        or js.WebAssembly (browser/Pyodide)."""
        try:
            import js  # noqa: F401  — Pyodide environment
            return await self._run_component_browser(binary, wasm_config, state_data)
        except ImportError:
            pass

        # Native CPython — try wasmtime.component
        try:
            return await self._run_component_native(binary, wasm_config, state_data)
        except ImportError:
            raise ImportError(
                "wasmtime is required for Component Model WASM steps on native CPython. "
                "Install it with: pip install wasmtime  (or use the 'native' extra)"
            )

    @staticmethod
    async def _run_component_native(
        binary: bytes,
        wasm_config,
        state_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Invoke the rufus:step execute() export via wasmtime.component."""
        from wasmtime import Engine, Store
        from wasmtime.component import Component, Linker

        # Build state JSON input
        if wasm_config.state_mapping:
            input_state = {
                wasm_key: state_data.get(state_key)
                for state_key, wasm_key in wasm_config.state_mapping.items()
            }
        else:
            input_state = state_data

        state_json = json.dumps(input_state)

        loop = asyncio.get_event_loop()

        def _sync_execute():
            engine = Engine()
            store = Store(engine)
            component = Component(engine, binary)
            linker = Linker(engine)
            # Basic WASI imports needed by many components
            try:
                linker.define_wasi()
            except Exception:
                pass  # Component may not import WASI

            instance = linker.instantiate(store, component)
            # Call the exported execute function
            # Interface: execute(state: string, step-name: string) -> result<string, step-error>
            execute_fn = instance.exports(store).get("execute")
            if execute_fn is None:
                # Try kebab-case export name
                execute_fn = instance.exports(store).get("rufus:step/step-component#execute")
            if execute_fn is None:
                raise RuntimeError(
                    "Component does not export 'execute'. "
                    "Ensure it implements the rufus:step@0.1.0 world."
                )
            result = execute_fn(store, state_json, wasm_config.entrypoint)
            # wasmtime.component returns a Python tuple/variant for result<T, E>
            # Convention: (True, value) = ok, (False, error) = err
            if isinstance(result, tuple) and len(result) == 2:
                ok, payload = result
                if ok:
                    return payload
                else:
                    raise RuntimeError(
                        f"Component step error (code={getattr(payload, 'code', '?')}): "
                        f"{getattr(payload, 'message', str(payload))}"
                    )
            # Flat string return (simplified binding)
            return result

        result_json = await loop.run_in_executor(None, _sync_execute)

        try:
            result = json.loads(result_json)
        except (json.JSONDecodeError, TypeError):
            raise RuntimeError(
                f"Component execute() did not return valid JSON: {result_json!r}"
            )

        if not isinstance(result, dict):
            raise RuntimeError(
                f"Component execute() result must be a JSON object, got {type(result).__name__}"
            )

        return result

    @staticmethod
    async def _run_component_browser(
        binary: bytes,
        wasm_config,
        state_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Invoke the component via js.WebAssembly (Pyodide / browser)."""
        import js
        from pyodide.ffi import to_js

        if wasm_config.state_mapping:
            input_state = {
                wasm_key: state_data.get(state_key)
                for state_key, wasm_key in wasm_config.state_mapping.items()
            }
        else:
            input_state = state_data

        state_json = json.dumps(input_state)

        # Compile and instantiate via js.WebAssembly
        bytes_js = to_js(binary)
        module = await js.WebAssembly.compile(bytes_js)
        instance = await js.WebAssembly.instantiate(module, to_js({}))
        exports = instance.exports

        execute_fn = getattr(exports, "execute", None)
        if execute_fn is None:
            raise RuntimeError(
                "Component does not export 'execute'. "
                "Ensure it implements the rufus:step@0.1.0 world."
            )

        result_json = execute_fn(state_json, wasm_config.entrypoint)

        try:
            result = json.loads(str(result_json))
        except (json.JSONDecodeError, TypeError):
            raise RuntimeError(
                f"Component execute() did not return valid JSON: {result_json!r}"
            )

        if not isinstance(result, dict):
            raise RuntimeError(
                f"Component execute() result must be a JSON object, got {type(result).__name__}"
            )

        return result

    # ------------------------------------------------------------------
    # Legacy WASI path
    # ------------------------------------------------------------------

    async def _run_legacy_wasi(
        self,
        wasm_config,
        state_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Delegate to the original WasmRuntime for core WASM modules."""
        logger.debug(
            f"WASM step '{wasm_config.entrypoint}': legacy core module detected, "
            "falling back to stdin/stdout interface"
        )
        return await self._legacy_runtime.execute(wasm_config, state_data)

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def _handle_error(self, wasm_config, exc: Exception) -> Dict[str, Any]:
        mode = wasm_config.fallback_on_error
        if mode == "skip":
            logger.warning(f"WASM component step error (skip): {exc}")
            return {}
        if mode == "default":
            logger.warning(f"WASM component step error (default): {exc}")
            return wasm_config.default_result or {}
        raise RuntimeError(str(exc)) from exc
