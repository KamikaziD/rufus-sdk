"""
WASM Runtime Helper for Rufus Workflow Engine.

Executes pre-compiled WebAssembly binaries as workflow steps using the WASI
stdin/stdout interface via the wasmtime Python package.

Architecture:
  - WasmBinaryResolver (Protocol) — abstracts binary lookup (disk or SQLite)
  - DiskWasmBinaryResolver       — cloud: reads .wasm from local disk path
  - SqliteWasmBinaryResolver     — edge: reads .wasm BLOB from device_wasm_cache
  - WasmRuntime                  — instantiates modules and runs them via WASI

WASI contract for WASM modules:
  - Read JSON input from stdin (either mapped state keys or full state dict)
  - Write JSON result to stdout
  - Exit with code 0 on success; any other exit code is treated as failure

Usage:
    resolver = DiskWasmBinaryResolver(db_conn)
    runtime = WasmRuntime(resolver)
    result = await runtime.execute(wasm_config, state_data)

.. deprecated::
    ``WasmRuntime`` uses the legacy stdin/stdout interface.  New modules should
    be compiled as WASI 0.3 Component Model binaries and will be handled
    automatically by ``ComponentStepRuntime`` (same ``execute`` signature).
    ``WasmRuntime`` is retained for backward compatibility; it will not be
    removed in the 0.x series.
"""

import asyncio
import hashlib
import io
import json
import logging
from typing import Any, Dict, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class WasmBinaryResolver(Protocol):
    """Abstracts .wasm binary lookup for cloud (disk) and edge (SQLite)."""

    async def resolve(self, binary_hash: str) -> bytes:
        """Return the raw .wasm bytes for the given SHA-256 hash.

        Raises:
            FileNotFoundError: if the binary is not found.
        """
        ...


class DiskWasmBinaryResolver:
    """Resolves WASM binaries from local disk via the wasm_components DB table.

    Used on the cloud control plane. Looks up blob_storage_path from the DB
    and reads the file from disk.

    Args:
        db_pool: asyncpg connection pool (PostgreSQL) or aiosqlite connection.
    """

    def __init__(self, db_pool):
        self._pool = db_pool

    async def resolve(self, binary_hash: str) -> bytes:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT blob_storage_path FROM wasm_components WHERE binary_hash = $1",
                binary_hash,
            )
        if row is None:
            raise FileNotFoundError(
                f"WASM binary not found in wasm_components: hash={binary_hash}"
            )
        path = row["blob_storage_path"]
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError as exc:
            raise FileNotFoundError(
                f"WASM binary file missing from disk: {path}"
            ) from exc


class SqliteWasmBinaryResolver:
    """Resolves WASM binaries from the edge device_wasm_cache SQLite table.

    Used on edge devices. Reads the binary_data BLOB stored at sync time.

    Args:
        conn: aiosqlite connection (or any async connection supporting execute/fetchone).
    """

    def __init__(self, conn):
        self._conn = conn

    async def resolve(self, binary_hash: str) -> bytes:
        cursor = await self._conn.execute(
            "SELECT binary_data FROM device_wasm_cache WHERE binary_hash = ?",
            (binary_hash,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise FileNotFoundError(
                f"WASM binary not found in device_wasm_cache: hash={binary_hash}"
            )
        return bytes(row[0])


class WasmRuntime:
    """Executes pre-compiled WASM binaries via the WASI stdin/stdout interface.

    Requires the `wasmtime` package: pip install wasmtime

    .. deprecated::
        Use ``ComponentStepRuntime`` for new modules.  Component Model binaries
        are dispatched automatically; this class handles legacy core modules.

    Args:
        resolver: A WasmBinaryResolver that provides raw .wasm bytes.
    """

    def __init__(self, resolver: WasmBinaryResolver):
        self._resolver = resolver
        # Lazily-created ComponentStepRuntime for CM binary detection
        self._component_runtime = None

    async def execute(
        self,
        wasm_config,  # WasmConfig — imported at call site to avoid circular imports
        state_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a WASM module and return its JSON output as a dict.

        The WASM module must:
          1. Read JSON from stdin (mapped state or full state depending on state_mapping)
          2. Write a JSON object to stdout
          3. Exit 0 on success

        Args:
            wasm_config: WasmConfig instance with hash, entrypoint, mapping, timeout.
            state_data: Current workflow state as a plain dict.

        Returns:
            Dict to be merged into workflow state via the configured merge strategy.

        Raises:
            RuntimeError: On WASM execution error when fallback_on_error='fail'.
            FileNotFoundError: If the binary cannot be resolved.
        """
        # Peek at the binary to decide whether to use the Component Model path
        try:
            binary = await self._resolver.resolve(wasm_config.wasm_hash)
        except Exception as exc:
            return self._handle_error(wasm_config, exc)

        from rufus.implementations.execution.component_runtime import is_component
        if is_component(binary):
            # Delegate to ComponentStepRuntime; avoid resolving the binary twice
            # by wrapping it in a trivial resolver
            if self._component_runtime is None:
                from rufus.implementations.execution.component_runtime import (
                    ComponentStepRuntime,
                )
                self._component_runtime = ComponentStepRuntime(self._resolver)
            return await self._component_runtime.execute(wasm_config, state_data)

        try:
            return await asyncio.wait_for(
                self._run_with_binary(binary, wasm_config, state_data),
                timeout=wasm_config.timeout_ms / 1000,
            )
        except asyncio.TimeoutError:
            msg = (
                f"WASM step timed out after {wasm_config.timeout_ms}ms "
                f"(hash={wasm_config.wasm_hash}, entrypoint={wasm_config.entrypoint})"
            )
            return self._handle_error(wasm_config, RuntimeError(msg))

    async def _run(self, wasm_config, state_data: Dict[str, Any]) -> Dict[str, Any]:
        binary = await self._resolver.resolve(wasm_config.wasm_hash)
        return await self._run_with_binary(binary, wasm_config, state_data)

    async def _run_with_binary(
        self, binary: bytes, wasm_config, state_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            from wasmtime import Engine, Linker, Module, Store, WasiConfig
        except ImportError as exc:
            raise ImportError(
                "wasmtime is required for WASM steps. Install it with: pip install wasmtime"
            ) from exc


        # Verify hash integrity
        actual_hash = hashlib.sha256(binary).hexdigest()
        if actual_hash != wasm_config.wasm_hash:
            raise RuntimeError(
                f"WASM binary hash mismatch: expected {wasm_config.wasm_hash}, "
                f"got {actual_hash}"
            )

        # Build input from state_mapping or pass full state
        if wasm_config.state_mapping:
            input_data = {
                wasm_key: state_data.get(state_key)
                for state_key, wasm_key in wasm_config.state_mapping.items()
            }
        else:
            input_data = state_data

        stdin_bytes = json.dumps(input_data).encode("utf-8")

        # Run in a thread pool to avoid blocking the event loop (wasmtime is sync)
        loop = asyncio.get_event_loop()
        try:
            result_bytes = await loop.run_in_executor(
                None,
                lambda: self._execute_wasi(binary, stdin_bytes, wasm_config.entrypoint),
            )
        except Exception as exc:
            return self._handle_error(wasm_config, exc)

        try:
            result = json.loads(result_bytes)
        except json.JSONDecodeError as exc:
            return self._handle_error(
                wasm_config,
                RuntimeError(
                    f"WASM stdout is not valid JSON: {result_bytes[:200]!r}"
                ),
            )

        if not isinstance(result, dict):
            return self._handle_error(
                wasm_config,
                RuntimeError(
                    f"WASM result must be a JSON object, got {type(result).__name__}"
                ),
            )

        return result

    @staticmethod
    def _execute_wasi(binary: bytes, stdin_bytes: bytes, entrypoint: str) -> bytes:
        """Synchronous WASI execution — called in a thread pool executor."""
        import os
        import tempfile
        from wasmtime import Engine, Linker, Module, Store, WasiConfig

        engine = Engine()
        module = Module(engine, binary)
        linker = Linker(engine)
        linker.define_wasi()

        # Write stdin to a temp file (wasmtime v25+ dropped stdin_bytes())
        stdin_fd, stdin_path = tempfile.mkstemp(suffix=".wasm_stdin")
        stdout_fd, stdout_path = tempfile.mkstemp(suffix=".wasm_stdout")
        try:
            os.write(stdin_fd, stdin_bytes)
            os.close(stdin_fd)
            stdin_fd = -1
            os.close(stdout_fd)
            stdout_fd = -1

            wasi_config = WasiConfig()
            wasi_config.stdin_file = stdin_path
            wasi_config.stdout_file = stdout_path

            store = Store(engine)
            store.set_wasi(wasi_config)

            instance = linker.instantiate(store, module)
            exports = instance.exports(store)

            if entrypoint not in exports:
                raise RuntimeError(
                    f"WASM module does not export function '{entrypoint}'. "
                    f"Available exports: {list(exports)}"
                )

            fn = exports[entrypoint]
            fn(store)

            with open(stdout_path, "rb") as f:
                return f.read()
        finally:
            if stdin_fd >= 0:
                os.close(stdin_fd)
            if stdout_fd >= 0:
                os.close(stdout_fd)
            try:
                os.unlink(stdin_path)
            except OSError:
                pass
            try:
                os.unlink(stdout_path)
            except OSError:
                pass

    def _handle_error(self, wasm_config, exc: Exception) -> Dict[str, Any]:
        """Apply fallback_on_error policy."""
        mode = wasm_config.fallback_on_error
        if mode == "skip":
            logger.warning(f"WASM step error (skip): {exc}")
            return {}
        if mode == "default":
            logger.warning(f"WASM step error (default): {exc}")
            return wasm_config.default_result or {}
        # mode == "fail" (default)
        raise RuntimeError(str(exc)) from exc
