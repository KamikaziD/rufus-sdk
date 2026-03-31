"""
Unit tests for ComponentStepRuntime and the is_component() detection helper.

All tests use mock binary data and a mock resolver — no wasmtime installation
required.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rufus.implementations.execution.wasm_runtime import WasmRuntime  # noqa: F401 (legacy compat)
from rufus.implementations.execution.component_runtime import (
    ComponentStepRuntime,
    WasmComponentPool,
    is_component,
)

# ---------------------------------------------------------------------------
# Magic-byte helpers
# ---------------------------------------------------------------------------

# A valid Component Model header (first 8 bytes)
CM_MAGIC_8 = b"\x00asm\x0e\x00\x01\x00" + b"\x00" * 100

# A valid core-module header
CORE_MAGIC_8 = b"\x00asm\x01\x00\x00\x00" + b"\x00" * 100


# ---------------------------------------------------------------------------
# is_component()
# ---------------------------------------------------------------------------

class TestIsComponent:
    def test_detects_component_magic(self):
        assert is_component(CM_MAGIC_8) is True

    def test_rejects_core_module(self):
        assert is_component(CORE_MAGIC_8) is False

    def test_rejects_empty(self):
        assert is_component(b"") is False

    def test_rejects_short(self):
        assert is_component(b"\x00asm\x0e") is False


# ---------------------------------------------------------------------------
# Fake WasmConfig
# ---------------------------------------------------------------------------

def make_config(
    wasm_hash: str = "a" * 64,
    entrypoint: str = "execute",
    state_mapping: dict = None,
    timeout_ms: int = 5000,
    fallback_on_error: str = "fail",
    default_result: dict = None,
):
    cfg = MagicMock()
    cfg.wasm_hash = wasm_hash
    cfg.entrypoint = entrypoint
    cfg.state_mapping = state_mapping
    cfg.timeout_ms = timeout_ms
    cfg.fallback_on_error = fallback_on_error
    cfg.default_result = default_result
    return cfg


# ---------------------------------------------------------------------------
# ComponentStepRuntime — Component Model path
# ---------------------------------------------------------------------------

class TestComponentStepRuntimeComponentPath:
    def _make_runtime(self, binary: bytes, result_json: str = '{"score": 99}'):
        """Build a ComponentStepRuntime with a mock resolver returning *binary*."""
        import hashlib

        wasm_hash = hashlib.sha256(binary).hexdigest()
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=binary)

        runtime = ComponentStepRuntime(resolver)
        # Patch _call_component so we don't need a real wasmtime build
        runtime._call_component = MagicMock(return_value=result_json)
        return runtime, wasm_hash

    @pytest.mark.asyncio
    async def test_component_binary_returns_merged_dict(self):
        import hashlib
        binary = CM_MAGIC_8
        wasm_hash = hashlib.sha256(binary).hexdigest()
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=binary)

        runtime = ComponentStepRuntime(resolver)

        # Patch the synchronous _call_component
        with patch.object(
            ComponentStepRuntime,
            "_call_component",
            return_value='{"risk_score": 42}',
        ):
            config = make_config(wasm_hash=wasm_hash)
            result = await runtime.execute(config, {"amount": 100})

        assert result == {"risk_score": 42}

    @pytest.mark.asyncio
    async def test_state_mapping_filters_input(self):
        import hashlib
        binary = CM_MAGIC_8
        wasm_hash = hashlib.sha256(binary).hexdigest()
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=binary)

        runtime = ComponentStepRuntime(resolver)

        captured_state_json: list[str] = []

        def fake_call(binary_arg, state_json, step_name):
            captured_state_json.append(state_json)
            return '{"ok": true}'

        with patch.object(ComponentStepRuntime, "_call_component", side_effect=fake_call):
            config = make_config(
                wasm_hash=wasm_hash,
                state_mapping={"amount": "txn_amount"},  # state_key → wasm_key
            )
            await runtime.execute(config, {"amount": 50, "card": "tok_xxx"})

        sent = json.loads(captured_state_json[0])
        assert "txn_amount" in sent
        assert "card" not in sent

    @pytest.mark.asyncio
    async def test_fallback_skip_on_error(self):
        import hashlib
        binary = CM_MAGIC_8
        wasm_hash = hashlib.sha256(binary).hexdigest()
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=binary)

        runtime = ComponentStepRuntime(resolver)

        def fake_call(*a, **k):
            raise RuntimeError("simulated error")

        with patch.object(ComponentStepRuntime, "_call_component", side_effect=fake_call):
            config = make_config(wasm_hash=wasm_hash, fallback_on_error="skip")
            result = await runtime.execute(config, {})

        assert result == {}

    @pytest.mark.asyncio
    async def test_fallback_default_on_error(self):
        import hashlib
        binary = CM_MAGIC_8
        wasm_hash = hashlib.sha256(binary).hexdigest()
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=binary)

        runtime = ComponentStepRuntime(resolver)

        def fake_call(*a, **k):
            raise RuntimeError("simulated error")

        with patch.object(ComponentStepRuntime, "_call_component", side_effect=fake_call):
            config = make_config(
                wasm_hash=wasm_hash,
                fallback_on_error="default",
                default_result={"risk_score": 0},
            )
            result = await runtime.execute(config, {})

        assert result == {"risk_score": 0}

    @pytest.mark.asyncio
    async def test_hash_mismatch_raises(self):
        import hashlib
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=CM_MAGIC_8)

        runtime = ComponentStepRuntime(resolver)
        config = make_config(wasm_hash="wrong_hash" * 4)  # won't match sha256(CM_MAGIC_8)
        config.fallback_on_error = "fail"

        with pytest.raises(RuntimeError, match="hash mismatch"):
            await runtime.execute(config, {})


# ---------------------------------------------------------------------------
# ComponentStepRuntime — legacy stdin/stdout path
# ---------------------------------------------------------------------------

class TestComponentStepRuntimeLegacyPath:
    @pytest.mark.asyncio
    async def test_core_module_uses_wasm_runtime(self):
        import hashlib
        binary = CORE_MAGIC_8
        wasm_hash = hashlib.sha256(binary).hexdigest()
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=binary)

        runtime = ComponentStepRuntime(resolver)

        with patch(
            "rufus.implementations.execution.wasm_runtime.WasmRuntime._execute_wasi",
            return_value=b'{"legacy": true}',
        ):
            config = make_config(wasm_hash=wasm_hash)
            result = await runtime.execute(config, {})

        assert result == {"legacy": True}


# ---------------------------------------------------------------------------
# WasmRuntime CM delegation (backward-compat)
# ---------------------------------------------------------------------------

class TestWasmRuntimeCMDelegation:
    @pytest.mark.asyncio
    async def test_wasm_runtime_delegates_component_to_component_runtime(self):
        import hashlib
        binary = CM_MAGIC_8
        wasm_hash = hashlib.sha256(binary).hexdigest()
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=binary)

        runtime = WasmRuntime(resolver)

        with patch.object(
            ComponentStepRuntime,
            "_call_component",
            return_value='{"delegated": true}',
        ):
            config = make_config(wasm_hash=wasm_hash)
            result = await runtime.execute(config, {})

        assert result == {"delegated": True}

    @pytest.mark.asyncio
    async def test_wasm_runtime_uses_legacy_for_core_module(self):
        import hashlib
        binary = CORE_MAGIC_8
        wasm_hash = hashlib.sha256(binary).hexdigest()
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=binary)

        runtime = WasmRuntime(resolver)

        # Patch both the wasmtime import guard and _execute_wasi so wasmtime
        # doesn't need to be installed in the test environment
        with patch(
            "rufus.implementations.execution.wasm_runtime.WasmRuntime._run_with_binary",
            new=AsyncMock(return_value={"legacy": True}),
        ):
            config = make_config(wasm_hash=wasm_hash)
            result = await runtime.execute(config, {})

        assert result == {"legacy": True}


# ---------------------------------------------------------------------------
# ComponentStepRuntime — bridge integration
# ---------------------------------------------------------------------------

class TestComponentStepRuntimeBridgeIntegration:
    """Verify that the optional bridge param routes correctly."""

    @pytest.mark.asyncio
    async def test_bridge_used_when_set_call_component_skipped(self):
        """When bridge is provided, _call_component must NOT be called."""
        import hashlib
        binary = CM_MAGIC_8
        wasm_hash = hashlib.sha256(binary).hexdigest()
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=binary)

        fake_bridge = MagicMock()
        fake_bridge.execute_component = MagicMock(return_value='{"bridge_result": true}')

        runtime = ComponentStepRuntime(resolver, bridge=fake_bridge)

        with patch.object(ComponentStepRuntime, "_call_component") as mock_native:
            config = make_config(wasm_hash=wasm_hash)
            result = await runtime.execute(config, {"x": 1})

        # Bridge was called; native path was not
        fake_bridge.execute_component.assert_called_once()
        mock_native.assert_not_called()
        assert result == {"bridge_result": True}

    @pytest.mark.asyncio
    async def test_cloud_path_unchanged_when_bridge_is_none(self):
        """Without a bridge, the default _call_component (wasmtime) path runs."""
        import hashlib
        binary = CM_MAGIC_8
        wasm_hash = hashlib.sha256(binary).hexdigest()
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=binary)

        runtime = ComponentStepRuntime(resolver, bridge=None)

        with patch.object(
            ComponentStepRuntime,
            "_call_component",
            return_value='{"cloud": true}',
        ) as mock_native:
            config = make_config(wasm_hash=wasm_hash)
            result = await runtime.execute(config, {})

        mock_native.assert_called_once()
        assert result == {"cloud": True}

    @pytest.mark.asyncio
    async def test_bridge_error_respects_fallback_on_error_skip(self):
        """Bridge RuntimeError must be caught and handled by _handle_error policy."""
        import hashlib
        binary = CM_MAGIC_8
        wasm_hash = hashlib.sha256(binary).hexdigest()
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=binary)

        fake_bridge = MagicMock()
        fake_bridge.execute_component = MagicMock(
            side_effect=RuntimeError("bridge execution failed")
        )

        runtime = ComponentStepRuntime(resolver, bridge=fake_bridge)
        config = make_config(wasm_hash=wasm_hash, fallback_on_error="skip")

        result = await runtime.execute(config, {})
        assert result == {}


# ---------------------------------------------------------------------------
# ComponentStepRuntime — slow resolver triggers timeout (EBu8w)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_component_runtime_timeout_triggers_skip():
    """A slow resolver that exceeds timeout_ms is treated as an error."""
    import asyncio
    import hashlib
    binary = CORE_MAGIC_8
    actual_hash = hashlib.sha256(binary).hexdigest()

    class _SlowResolver:
        async def resolve(self, binary_hash: str) -> bytes:
            await asyncio.sleep(10)  # cancelled by timeout
            return binary

    runtime = ComponentStepRuntime(_SlowResolver())
    config = make_config(
        wasm_hash=actual_hash,
        timeout_ms=50,
        fallback_on_error="skip",
    )

    result = await runtime.execute(config, {})
    assert result == {}


# ---------------------------------------------------------------------------
# WasmComponentPool — hot-swap and caching
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wasm_component_pool_caches_compiled_component():
    """get_or_compile returns the same object on repeated calls (no recompile)."""
    import sys
    import hashlib

    binary = CM_MAGIC_8
    wasm_hash = hashlib.sha256(binary).hexdigest()

    # Create a fake wasmtime.component module so the import inside get_or_compile succeeds.
    fake_component_cls = MagicMock()
    fake_component_instance = object()
    fake_component_cls.return_value = fake_component_instance

    fake_wt_component = MagicMock()
    fake_wt_component.Component = fake_component_cls

    pool = WasmComponentPool()
    pool._engine = MagicMock()  # skip real Engine creation

    with patch.dict(sys.modules, {"wasmtime.component": fake_wt_component}):
        result1 = await pool.get_or_compile(binary, wasm_hash)
        result2 = await pool.get_or_compile(binary, wasm_hash)

    assert result1 is fake_component_instance
    assert result2 is fake_component_instance  # second call returns cached — no recompile
    # Component() was only called once (cache hit on second call)
    assert fake_component_cls.call_count == 1


@pytest.mark.asyncio
async def test_wasm_component_pool_swap_module_replaces_cache():
    """swap_module atomically replaces the cached component for a given hash."""
    import sys
    import hashlib

    binary_v1 = CM_MAGIC_8
    binary_v2 = b"\x00asm\x0e\x00\x01\x00" + b"\xff" * 100
    wasm_hash = hashlib.sha256(binary_v1).hexdigest()

    fake_v1 = object()
    fake_v2 = object()

    call_count = 0

    def _fake_component_cls(engine, binary):
        nonlocal call_count
        call_count += 1
        return fake_v1 if call_count == 1 else fake_v2

    fake_wt_component = MagicMock()
    fake_wt_component.Component = _fake_component_cls

    pool = WasmComponentPool()
    pool._engine = MagicMock()  # skip real Engine creation

    with patch.dict(sys.modules, {"wasmtime.component": fake_wt_component}):
        # Prime the cache with v1
        first = await pool.get_or_compile(binary_v1, wasm_hash)
        assert first is fake_v1

        # Hot-swap to v2
        await pool.swap_module(wasm_hash, binary_v2)

    # After swap, cache holds v2
    assert pool._cache[wasm_hash] is fake_v2
