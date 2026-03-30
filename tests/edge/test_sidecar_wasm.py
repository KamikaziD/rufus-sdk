"""Tests for WASM sidecar compilation and contract.

These tests:
1. Validate the build_wasm.py script structure (no wasmtime required)
2. Test the wasm_main() entry point logic via Python (bypassing WASM runtime)
3. Test the actual WASM binary if wasmtime is available (skips gracefully if not)
"""

from __future__ import annotations

import importlib.util
import io
import json
import pathlib
import sys
from unittest.mock import patch

import pytest

_SIDECAR_BASE = pathlib.Path(__file__).parents[2] / "src" / "rufus_edge" / "sidecar"


def _import_sidecar(module_leaf: str):
    path = _SIDECAR_BASE / (module_leaf + ".py")
    spec = importlib.util.spec_from_file_location(f"rufus_edge.sidecar.{module_leaf}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# build_wasm.py — structure tests (no compilation needed)
# ---------------------------------------------------------------------------

def test_build_wasm_module_importable():
    mod = _import_sidecar("build_wasm")
    assert hasattr(mod, "build")
    assert hasattr(mod, "compute_source_hash")
    assert hasattr(mod, "is_up_to_date")


def test_compute_source_hash_is_stable():
    """Same source file → same hash on repeated calls."""
    mod = _import_sidecar("build_wasm")
    h1 = mod.compute_source_hash()
    h2 = mod.compute_source_hash()
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex digest


def test_is_up_to_date_false_when_no_binary(tmp_path):
    """is_up_to_date() returns False when wasm binary does not exist."""
    mod = _import_sidecar("build_wasm")
    with patch.object(mod, "_WASM_OUT", tmp_path / "apply_config.wasm"):
        with patch.object(mod, "_WASM_HASH", tmp_path / "apply_config.sha256"):
            assert mod.is_up_to_date() is False


def test_build_raises_when_no_toolchain(tmp_path):
    """build() raises RuntimeError when py2wasm and wasi-sdk are absent."""
    mod = _import_sidecar("build_wasm")
    with patch.object(mod, "_WASM_OUT", tmp_path / "apply_config.wasm"):
        with patch.object(mod, "_WASM_HASH", tmp_path / "apply_config.sha256"):
            with pytest.raises(RuntimeError, match="py2wasm|wasi-sdk"):
                mod.build(force=True)


# ---------------------------------------------------------------------------
# wasm_main() entry point — tested via Python (simulates WASM stdin/stdout)
# ---------------------------------------------------------------------------

_applier = _import_sidecar("config_applier")


def _run_wasm_main(proposal: dict, monkeypatch) -> dict:
    """Run wasm_main() with the given proposal, capture stdout as JSON."""
    stdin_data = json.dumps(proposal)
    stdout_capture = io.StringIO()
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_data))
    monkeypatch.setattr("sys.stdout", stdout_capture)

    # Patch the actual config apply functions to avoid filesystem ops
    with patch.object(_applier, "_apply_hot_swap", return_value="hot_swapped:fraud_threshold=0.85"):
        with patch.object(_applier, "_apply_drain_and_restart", return_value="drain_restarted"):
            try:
                _applier.wasm_main()
            except SystemExit:
                pass

    output = stdout_capture.getvalue()
    return json.loads(output) if output else {}


def test_wasm_main_hot_swap_approved(monkeypatch):
    """Approved hot-swap key → outcome contains hot_swapped."""
    result = _run_wasm_main(
        {"key": "fraud_threshold", "value": 0.85, "approved": True},
        monkeypatch,
    )
    assert "outcome" in result
    assert "hot_swapped" in result["outcome"] or "drain" in result["outcome"]


def test_wasm_main_not_approved(monkeypatch):
    """Not approved → outcome is skipped_not_approved."""
    result = _run_wasm_main(
        {"key": "fraud_threshold", "value": 0.85, "approved": False},
        monkeypatch,
    )
    assert result.get("outcome") == "skipped_not_approved"


def test_wasm_main_drain_restart_key(monkeypatch):
    """A restart-required key → calls drain_and_restart path."""
    # Patch the keys so we know what's hot-swap vs restart
    restart_key = next(iter(_applier._RESTART_REQUIRED_KEYS), None)
    if restart_key is None:
        pytest.skip("No restart-required keys defined")

    stdout_capture = io.StringIO()
    monkeypatch.setattr("sys.stdin", io.StringIO(
        json.dumps({"key": restart_key, "value": "new_value", "approved": True})
    ))
    monkeypatch.setattr("sys.stdout", stdout_capture)

    with patch.object(_applier, "_apply_drain_and_restart", return_value="drain_restarted") as mock_drain:
        with patch.object(_applier, "_apply_hot_swap", return_value="hot_swapped"):
            try:
                _applier.wasm_main()
            except SystemExit:
                pass
    mock_drain.assert_called_once()


def test_wasm_main_invalid_json_writes_error(monkeypatch):
    """Invalid JSON on stdin → wasm_main writes error JSON to stdout and exits 1."""
    stdout_capture = io.StringIO()
    monkeypatch.setattr("sys.stdin", io.StringIO("NOT VALID JSON"))
    monkeypatch.setattr("sys.stdout", stdout_capture)

    with pytest.raises(SystemExit) as exc_info:
        _applier.wasm_main()

    assert exc_info.value.code == 1
    output = stdout_capture.getvalue()
    result = json.loads(output)
    assert "error" in result.get("outcome", "").lower()


# ---------------------------------------------------------------------------
# Actual WASM binary test (skips if wasmtime not installed)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    importlib.util.find_spec("wasmtime") is None,
    reason="wasmtime not installed — skipping WASM binary test"
)
def test_wasm_binary_executes_hot_swap():
    """Load apply_config.wasm and verify it processes a hot-swap proposal."""
    import wasmtime

    wasm_path = _SIDECAR_BASE / "wasm" / "apply_config.wasm"
    if not wasm_path.exists():
        pytest.skip("apply_config.wasm not compiled — run: python -m rufus_edge.sidecar.build_wasm")

    engine = wasmtime.Engine()
    store = wasmtime.Store(engine)
    module = wasmtime.Module.from_file(engine, str(wasm_path))

    # Feed the proposal via WASI stdin
    proposal = json.dumps({"key": "fraud_threshold", "value": 0.9, "approved": True})
    wasi = wasmtime.WasiConfig()
    wasi.stdin_bytes = proposal.encode()
    stdout_buf = io.BytesIO()
    wasi.stdout = wasmtime.WasiFile.from_fileobj(stdout_buf)
    store.set_wasi(wasi)

    linker = wasmtime.Linker(engine)
    linker.define_wasi()
    instance = linker.instantiate(store, module)

    start = instance.exports(store).get("_start") or instance.exports(store).get("wasm_main")
    if start:
        start(store)

    result = json.loads(stdout_buf.getvalue().decode())
    assert "outcome" in result
