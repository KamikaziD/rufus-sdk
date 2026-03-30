"""
Unit tests for ComponentStepRuntime.

All tests use mock binary resolvers — no real WASM execution required.
"""

import asyncio
import json
import struct
import pytest

from rufus.wasm_component import is_component, COMPONENT_MAGIC


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_core_binary() -> bytes:
    """Minimal valid-looking WASM core module header."""
    return b"\x00asm\x01\x00\x00\x00" + b"\x00" * 8


def _make_component_binary() -> bytes:
    """Minimal WASM Component Model header."""
    return b"\x00asm\x0d\x00\x01\x00" + b"\x00" * 8


class _MockResolver:
    """Returns a pre-baked binary regardless of the hash."""

    def __init__(self, binary: bytes):
        self._binary = binary

    async def resolve(self, binary_hash: str) -> bytes:
        return self._binary


class _MockWasmConfig:
    """Minimal WasmConfig lookalike for tests."""

    def __init__(
        self,
        wasm_hash: str = "a" * 64,
        entrypoint: str = "execute",
        timeout_ms: int = 5000,
        fallback_on_error: str = "fail",
        state_mapping: dict = None,
        default_result: dict = None,
    ):
        self.wasm_hash = wasm_hash
        self.entrypoint = entrypoint
        self.timeout_ms = timeout_ms
        self.fallback_on_error = fallback_on_error
        self.state_mapping = state_mapping
        self.default_result = default_result


# ─────────────────────────────────────────────────────────────────────────────
# is_component
# ─────────────────────────────────────────────────────────────────────────────

def test_is_component_true_for_component_magic():
    assert is_component(_make_component_binary()) is True


def test_is_component_false_for_core_magic():
    assert is_component(_make_core_binary()) is False


def test_is_component_false_for_garbage():
    assert is_component(b"garbage") is False


def test_is_component_false_for_empty():
    assert is_component(b"") is False


# ─────────────────────────────────────────────────────────────────────────────
# COMPONENT_MAGIC constant
# ─────────────────────────────────────────────────────────────────────────────

def test_component_magic_length():
    assert len(COMPONENT_MAGIC) == 8


def test_component_magic_is_detected():
    binary = COMPONENT_MAGIC + b"\x00" * 10
    assert is_component(binary) is True


# ─────────────────────────────────────────────────────────────────────────────
# ComponentStepRuntime — hash mismatch
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_component_runtime_hash_mismatch_raises():
    import hashlib
    from rufus.implementations.execution.component_runtime import ComponentStepRuntime

    binary = _make_core_binary()
    resolver = _MockResolver(binary)
    runtime = ComponentStepRuntime(resolver)

    config = _MockWasmConfig(wasm_hash="0" * 64)  # wrong hash
    with pytest.raises(RuntimeError, match="hash mismatch"):
        await runtime.execute(config, {})


# ─────────────────────────────────────────────────────────────────────────────
# ComponentStepRuntime — fallback_on_error='skip'
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_component_runtime_skip_on_error():
    import hashlib
    from rufus.implementations.execution.component_runtime import ComponentStepRuntime

    binary = _make_core_binary()
    actual_hash = hashlib.sha256(binary).hexdigest()

    resolver = _MockResolver(binary)
    runtime = ComponentStepRuntime(resolver)

    config = _MockWasmConfig(wasm_hash=actual_hash, fallback_on_error="skip")

    # Core binary without wasmtime installed will raise ImportError → skip → {}
    # Or with wasmtime, it will fail at instantiation → skip → {}
    result = await runtime.execute(config, {"amount": 100})
    assert result == {}


# ─────────────────────────────────────────────────────────────────────────────
# ComponentStepRuntime — fallback_on_error='default'
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_component_runtime_default_on_error():
    import hashlib
    from rufus.implementations.execution.component_runtime import ComponentStepRuntime

    binary = _make_core_binary()
    actual_hash = hashlib.sha256(binary).hexdigest()

    resolver = _MockResolver(binary)
    runtime = ComponentStepRuntime(resolver)

    default_result = {"status": "fallback"}
    config = _MockWasmConfig(
        wasm_hash=actual_hash,
        fallback_on_error="default",
        default_result=default_result,
    )

    result = await runtime.execute(config, {})
    assert result == default_result


# ─────────────────────────────────────────────────────────────────────────────
# ComponentStepRuntime — timeout
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_component_runtime_timeout_triggers_skip():
    import hashlib
    from rufus.implementations.execution.component_runtime import ComponentStepRuntime

    binary = _make_core_binary()
    actual_hash = hashlib.sha256(binary).hexdigest()

    class _SlowResolver:
        async def resolve(self, binary_hash: str) -> bytes:
            await asyncio.sleep(10)  # will be cancelled by timeout
            return binary

    runtime = ComponentStepRuntime(_SlowResolver())
    config = _MockWasmConfig(
        wasm_hash=actual_hash,
        timeout_ms=50,  # 50 ms timeout
        fallback_on_error="skip",
    )

    result = await runtime.execute(config, {})
    assert result == {}


# ─────────────────────────────────────────────────────────────────────────────
# ComponentStepRuntime — delegates to WasmRuntime for core modules
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_component_runtime_delegates_core_to_legacy(monkeypatch):
    """When binary is a core module, _run_legacy_wasi is called."""
    import hashlib
    from rufus.implementations.execution.component_runtime import ComponentStepRuntime

    binary = _make_core_binary()
    actual_hash = hashlib.sha256(binary).hexdigest()
    resolver = _MockResolver(binary)

    called = {}

    async def _mock_legacy(self_inner, wasm_config, state_data):
        called["invoked"] = True
        return {"legacy": True}

    monkeypatch.setattr(
        ComponentStepRuntime,
        "_run_legacy_wasi",
        _mock_legacy,
    )

    runtime = ComponentStepRuntime(resolver)
    config = _MockWasmConfig(wasm_hash=actual_hash, fallback_on_error="fail")
    result = await runtime.execute(config, {})

    assert called.get("invoked") is True
    assert result == {"legacy": True}


# ─────────────────────────────────────────────────────────────────────────────
# ComponentStepRuntime — component path is dispatched (not legacy)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_component_runtime_dispatches_component_path(monkeypatch):
    """When binary is a Component Model binary, _run_component is called."""
    import hashlib
    from rufus.implementations.execution.component_runtime import ComponentStepRuntime

    binary = _make_component_binary()
    actual_hash = hashlib.sha256(binary).hexdigest()
    resolver = _MockResolver(binary)

    called = {}

    async def _mock_component(self_inner, bin_bytes, wasm_config, state_data):
        called["invoked"] = True
        return {"component": True}

    monkeypatch.setattr(
        ComponentStepRuntime,
        "_run_component",
        _mock_component,
    )

    runtime = ComponentStepRuntime(resolver)
    config = _MockWasmConfig(wasm_hash=actual_hash, fallback_on_error="fail")
    result = await runtime.execute(config, {})

    assert called.get("invoked") is True
    assert result == {"component": True}
