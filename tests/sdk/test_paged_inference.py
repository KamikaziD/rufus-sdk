"""
Tests for PagedInferenceRuntime — shard-level LLM paging for edge + browser.

Covers:
    1. paging_strategy="none" → no OPFS/paged calls, base inference path unchanged
    2. PagedBrowserInferenceProvider FFI → mock js.runPagedInference, verify shape
    3. LlamaCppPagedProvider subprocess → verify --mmap flag in cmd
    4. AIInferenceConfig Pydantic validation for shard fields
"""

import asyncio
import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub heavy optional deps before any rufus.implementations.inference import.
# tflite.py imports numpy at module level; paged_browser imports js (Pyodide).
# ---------------------------------------------------------------------------
if "numpy" not in sys.modules:
    _np = types.ModuleType("numpy")
    _np.ndarray = list
    _np.float32 = float
    _np.int32 = int
    _np.int64 = int
    _np.dtype = type
    _np.array = MagicMock(return_value=[])
    _np.zeros = MagicMock(return_value=[])
    _np.expand_dims = MagicMock(return_value=[])
    _np.isscalar = lambda x: isinstance(x, (int, float, complex, bool))
    _np.bool_ = bool
    sys.modules["numpy"] = _np

# Stub tflite_runtime so TFLiteInferenceProvider doesn't crash at import
for _tflite_mod in ("tflite_runtime", "tflite_runtime.interpreter"):
    if _tflite_mod not in sys.modules:
        _stub = types.ModuleType(_tflite_mod)
        _stub.Interpreter = MagicMock
        sys.modules[_tflite_mod] = _stub

from rufus.models import AIInferenceConfig


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_ai_config(**overrides) -> AIInferenceConfig:
    defaults = dict(
        model_name="test-model",
        input_source="state.prompt",
        runtime="custom",
    )
    defaults.update(overrides)
    return AIInferenceConfig(**defaults)


# ── 1. paging_strategy="none" leaves inference path untouched ─────────────────

def test_aiconfig_paging_strategy_defaults_to_none():
    cfg = _make_ai_config()
    assert cfg.paging_strategy == "none"
    assert cfg.max_resident_shards == 2
    assert cfg.prefetch_shards == 1
    assert cfg.shard_urls is None
    assert cfg.logic_gate_threshold == 0.0
    assert cfg.max_tokens is None


def test_aiconfig_paging_strategy_none_has_no_shard_urls():
    """When paging is disabled, shard_urls may remain None — no validation error."""
    cfg = _make_ai_config(paging_strategy="none", shard_urls=None)
    assert cfg.paging_strategy == "none"
    assert cfg.shard_urls is None


# ── 2. PagedBrowserInferenceProvider FFI ──────────────────────────────────────

@pytest.mark.asyncio
async def test_paged_browser_provider_ffi_called():
    """Mock js.runPagedInference; verify args forwarded and InferenceResult shape."""
    from rufus.implementations.inference.paged_browser import PagedBrowserInferenceProvider

    # Build a mock JS result object matching what Pyodide would return
    mock_js_result = MagicMock()
    mock_js_result.text = "Relay fault on CB-42 caused by worn contacts."
    mock_js_result.tokens_generated = 8
    mock_js_result.shards_loaded = 2
    mock_js_result.latency_ms = 1234.5
    mock_js_result.complexity_score = 0.82

    # Inject a fake `js` module so the import succeeds outside Pyodide
    fake_js = types.ModuleType("js")
    fake_js.runPagedInference = AsyncMock(return_value=mock_js_result)
    sys.modules["js"] = fake_js

    try:
        provider = PagedBrowserInferenceProvider(model_id="bitnet-2b")
        await provider.load_model("models/bitnet.gguf", "bitnet-2b")
        assert provider.is_model_loaded("bitnet-2b")

        cfg = _make_ai_config(paging_strategy="shard", max_tokens=64, logic_gate_threshold=0.5)
        result = await provider.run_inference(
            model_name="bitnet-2b",
            inputs={"prompt": "diagnose relay fault"},
            config=cfg,
        )

        # Verify FFI was called with correct args
        fake_js.runPagedInference.assert_called_once()
        call_args = fake_js.runPagedInference.call_args
        payload = json.loads(call_args[0][0])
        assert payload["prompt"] == "diagnose relay fault"
        assert payload["threshold"] == 0.5
        assert call_args[0][1] == 64  # max_tokens

        # Verify result shape
        assert result.success is True
        assert result.outputs["text"] == "Relay fault on CB-42 caused by worn contacts."
        assert result.outputs["tokens_generated"] == 8
        assert result.outputs["shards_loaded"] == 2
        assert result.outputs["path_taken"] == "full_inference"  # shards_loaded > 1
        assert result.model_name == "bitnet-2b"
    finally:
        sys.modules.pop("js", None)


@pytest.mark.asyncio
async def test_paged_browser_provider_fast_path_label():
    """shards_loaded=1 → path_taken should be 'fast_path'."""
    from rufus.implementations.inference.paged_browser import PagedBrowserInferenceProvider

    mock_js_result = MagicMock()
    mock_js_result.text = "Error E42 = low voltage"
    mock_js_result.tokens_generated = 4
    mock_js_result.shards_loaded = 1   # fast path — only shard-0 loaded
    mock_js_result.latency_ms = 320.0
    mock_js_result.complexity_score = 0.18

    fake_js = types.ModuleType("js")
    fake_js.runPagedInference = AsyncMock(return_value=mock_js_result)
    sys.modules["js"] = fake_js

    try:
        provider = PagedBrowserInferenceProvider()
        await provider.load_model("", "bitnet-2b")
        cfg = _make_ai_config(logic_gate_threshold=0.4)
        result = await provider.run_inference("bitnet-2b", {"prompt": "what is E42?"}, config=cfg)
        assert result.outputs["path_taken"] == "fast_path"
    finally:
        sys.modules.pop("js", None)


# ── 3. LlamaCppPagedProvider subprocess uses --mmap ───────────────────────────

@pytest.mark.asyncio
async def test_llamacpp_paged_uses_mmap_flag():
    """Mock asyncio.create_subprocess_exec; verify --mmap appears in the command."""
    from rufus.implementations.inference.llamacpp_paged import LlamaCppPagedProvider

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"Contacts worn, replace relay.", b""))

    captured_cmd = []

    async def fake_exec(*args, **kwargs):
        captured_cmd.extend(args)
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        provider = LlamaCppPagedProvider(
            binary_path="llama-cli",
            model_path="/opt/models/bitnet-2b.gguf",
        )
        await provider.load_model("/opt/models/bitnet-2b.gguf", "bitnet-2b")

        cfg = _make_ai_config(paging_strategy="shard", max_tokens=32)
        result = await provider.run_inference(
            model_name="bitnet-2b",
            inputs={"prompt": "diagnose CB-42"},
            config=cfg,
        )

    assert "--mmap" in captured_cmd, "llama.cpp must be invoked with --mmap for native paging"
    assert "-m" in captured_cmd
    assert "/opt/models/bitnet-2b.gguf" in captured_cmd
    assert "-n" in captured_cmd
    assert "32" in captured_cmd
    assert result.success is True
    assert "Contacts worn" in result.outputs["text"]
    assert result.outputs["path_taken"] == "native_mmap"


@pytest.mark.asyncio
async def test_llamacpp_paged_binary_not_found():
    """FileNotFoundError → success=False with helpful error_message."""
    from rufus.implementations.inference.llamacpp_paged import LlamaCppPagedProvider

    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("no binary")):
        provider = LlamaCppPagedProvider(binary_path="nonexistent-llama-cli",
                                         model_path="/tmp/model.gguf")
        provider._loaded = True
        provider._model_name = "bitnet-2b"
        result = await provider.run_inference("bitnet-2b", {"prompt": "test"})

    assert result.success is False
    assert "not found" in result.error_message.lower()


# ── 4. AIInferenceConfig Pydantic validation ──────────────────────────────────

def test_aiconfig_shard_validation_max_resident_shards_ge_1():
    with pytest.raises(Exception):  # ValidationError
        _make_ai_config(max_resident_shards=0)


def test_aiconfig_shard_validation_accepts_explicit_shard_urls():
    cfg = _make_ai_config(
        paging_strategy="shard",
        shard_urls=["https://cdn.example.com/shard-0.gguf",
                    "https://cdn.example.com/shard-1.gguf"],
        max_resident_shards=2,
        max_tokens=128,
    )
    assert cfg.paging_strategy == "shard"
    assert len(cfg.shard_urls) == 2
    assert cfg.max_tokens == 128


def test_aiconfig_logic_gate_threshold_bounds():
    cfg_zero = _make_ai_config(logic_gate_threshold=0.0)
    assert cfg_zero.logic_gate_threshold == 0.0

    cfg_one = _make_ai_config(logic_gate_threshold=1.0)
    assert cfg_one.logic_gate_threshold == 1.0

    with pytest.raises(Exception):  # ValidationError
        _make_ai_config(logic_gate_threshold=1.1)


def test_aiconfig_shard_size_mb_ge_10():
    with pytest.raises(Exception):  # ValidationError
        _make_ai_config(shard_size_mb=5)

    cfg = _make_ai_config(shard_size_mb=120)
    assert cfg.shard_size_mb == 120
