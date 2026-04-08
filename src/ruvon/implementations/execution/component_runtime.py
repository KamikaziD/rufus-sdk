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
The component must export ``ruvon:step/runner#execute`` as defined in
``src/ruvon/wasm_component/step.wit``::

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
            thread_name_prefix="ruvon-wasm-batch",
        )
    return _BATCH_EXECUTOR


# ---------------------------------------------------------------------------
# WasmComponentPool — singleton cache of pre-compiled wasmtime Components.
#
# Rationale: compiling a Component (Cranelift codegen) takes ~50 ms.  Caching
# the compiled Component objects eliminates that overhead on every call.
#
# Hot-swap: swap_module() replaces a cached Component under asyncio.Lock.
# Python's GIL makes the dict assignment atomic, but the lock ensures the
# resolve → compile → assign sequence is a single coherent operation with no
# torn state visible to concurrent callers.
#
# Thread-safety note: get_or_compile() and swap_module() must be called from
# the event loop (async context).  The resolved Component object is then
# passed as a plain argument into run_in_executor — never await inside the
# thread-pool worker.
# ---------------------------------------------------------------------------
_WASM_COMPONENT_POOL: Optional["WasmComponentPool"] = None


def _get_wasm_pool() -> "WasmComponentPool":
    global _WASM_COMPONENT_POOL
    if _WASM_COMPONENT_POOL is None:
        _WASM_COMPONENT_POOL = WasmComponentPool()
    return _WASM_COMPONENT_POOL


class WasmComponentPool:
    """Singleton cache of pre-compiled wasmtime Component objects.

    Usage::

        pool = _get_wasm_pool()
        component = await pool.get_or_compile(binary, wasm_hash)
        # pass component to thread-pool executor ...

        # Hot-swap (called by NATS patch handler):
        await pool.swap_module(wasm_hash, new_binary)
    """

    def __init__(self) -> None:
        # wasm_hash -> compiled Component object (opaque, engine-specific)
        self._cache: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
        # Shared Engine — compiled once, thread-safe for reads.
        # Created lazily on first use so tests without wasmtime don't fail at
        # import time.
        self._engine: Optional[Any] = None

    def _get_engine(self) -> Any:
        """Return (or lazily create) the shared wasmtime Engine."""
        if self._engine is None:
            try:
                from wasmtime import Engine, Config  # type: ignore[import]
                config = Config()
                config.async_support = False
                self._engine = Engine(config)
            except ImportError as exc:
                raise ImportError(
                    "wasmtime ≥ 20 with Component Model support is required. "
                    "Install it with: pip install wasmtime"
                ) from exc
        return self._engine

    async def get_or_compile(self, binary: bytes, wasm_hash: str) -> Any:
        """Return cached Component for *wasm_hash*, compiling it if needed.

        Thread-safe: the lock prevents two callers from compiling the same
        binary concurrently — the second caller waits and receives the cached
        result.
        """
        if wasm_hash in self._cache:
            return self._cache[wasm_hash]

        async with self._lock:
            # Double-checked locking: re-check after acquiring lock.
            if wasm_hash in self._cache:
                return self._cache[wasm_hash]

            loop = asyncio.get_event_loop()
            engine = self._get_engine()
            try:
                from wasmtime.component import Component  # type: ignore[import]
            except ImportError as exc:
                raise ImportError("wasmtime Component Model support required") from exc

            component = await loop.run_in_executor(
                _get_batch_executor(),
                lambda: Component(engine, binary),
            )
            self._cache[wasm_hash] = component
            logger.debug("WasmComponentPool: compiled and cached %s…", wasm_hash[:16])
            return component

    async def swap_module(self, wasm_hash: str, new_binary: bytes) -> None:
        """Atomically replace the compiled Component for *wasm_hash*.

        Designed for zero-downtime hot-swap: in-flight calls that already
        retrieved the old Component will finish normally.  The next call to
        get_or_compile() for this hash returns the new Component.
        """
        loop = asyncio.get_event_loop()
        engine = self._get_engine()
        try:
            from wasmtime.component import Component  # type: ignore[import]
        except ImportError as exc:
            raise ImportError("wasmtime Component Model support required") from exc

        new_component = await loop.run_in_executor(
            _get_batch_executor(),
            lambda: Component(engine, new_binary),
        )

        async with self._lock:
            self._cache[wasm_hash] = new_component
            logger.info(
                "WasmComponentPool: hot-swapped component for hash %s…", wasm_hash[:16]
            )

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
                # Cloud path — use pool-cached Component to avoid re-compilation.
                pool = _get_wasm_pool()
                component = await pool.get_or_compile(binary, wasm_config.wasm_hash)
                engine = pool._get_engine()
                results_json = await loop.run_in_executor(
                    _get_batch_executor(),
                    lambda: [
                        self._call_component_cached(component, engine, s, step_name)
                        for s in states_json
                    ],
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
                # Default cloud/native path — wasmtime direct call.
                # Use WasmComponentPool to avoid recompiling on every call.
                # Falls back to _call_component(binary, ...) if pool compilation
                # fails (e.g. wasmtime not installed), which preserves the legacy
                # behaviour and keeps unit tests that patch _call_component working.
                try:
                    pool = _get_wasm_pool()
                    component = await pool.get_or_compile(binary, wasm_config.wasm_hash)
                    engine = pool._get_engine()
                    result_json = await loop.run_in_executor(
                        _get_batch_executor(),
                        lambda: self._call_component_cached(component, engine, state_json, step_name),
                    )
                except ImportError:
                    # wasmtime not installed — try the un-pooled path which may
                    # have been patched in tests, or fall through to WASI host mode.
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
        """Synchronous Component Model call — runs in thread-pool executor.

        Prefer _call_component_cached() when a pre-compiled Component is
        available from WasmComponentPool to avoid repeated Cranelift codegen.
        """
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

        # Resolve the exported function: ruvon:step/runner#execute
        try:
            # Try canonical interface path first
            runner = instance.exports(store).get("ruvon:step/runner")
            if runner is not None:
                execute_fn = runner.get("execute")
            else:
                # Fallback: flat export named "execute"
                execute_fn = instance.exports(store).get("execute")
        except Exception:
            execute_fn = instance.exports(store).get("execute")

        if execute_fn is None:
            raise RuntimeError(
                "Component does not export 'ruvon:step/runner#execute' or 'execute'. "
                "Ensure the component implements the ruvon:step/runner interface."
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

    @staticmethod
    def _call_component_cached(component: Any, engine: Any, state_json: str, step_name: str) -> str:
        """Synchronous Component Model call using a pre-compiled Component.

        Skips Cranelift codegen (~50 ms) by reusing the engine and Component
        from WasmComponentPool.  Each call creates a fresh Store + Instance.
        Runs in the thread-pool executor.
        """
        try:
            from wasmtime import Store  # type: ignore[import]
            from wasmtime.component import Linker  # type: ignore[import]
        except ImportError as exc:
            raise ImportError("wasmtime ≥ 20 with Component Model support is required") from exc

        store = Store(engine)
        linker = Linker(engine)

        try:
            from wasmtime.component import add_to_linker as add_wasi  # type: ignore[import]
            add_wasi(linker)
        except Exception:
            pass

        instance = linker.instantiate(store, component)

        try:
            runner = instance.exports(store).get("ruvon:step/runner")
            if runner is not None:
                execute_fn = runner.get("execute")
            else:
                execute_fn = instance.exports(store).get("execute")
        except Exception:
            execute_fn = instance.exports(store).get("execute")

        if execute_fn is None:
            raise RuntimeError(
                "Component does not export 'ruvon:step/runner#execute' or 'execute'."
            )

        outcome = execute_fn(store, state_json, step_name)

        if hasattr(outcome, "value"):
            if outcome.tag == 0:
                return outcome.value
            else:
                err = outcome.value
                code = getattr(err, "code", "UNKNOWN")
                message = getattr(err, "message", str(err))
                raise RuntimeError(f"Component step error [{code}]: {message}")
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
        from ruvon.implementations.execution.wasm_runtime import WasmRuntime
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
