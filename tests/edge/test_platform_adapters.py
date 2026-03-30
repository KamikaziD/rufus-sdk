"""
Unit tests for rufus_edge.platform adapters.

Tests all three adapters (native, wasi, pyodide) using mock HTTP to avoid
real network calls.
"""

import asyncio
import json
import pytest

from rufus_edge.platform import detect_platform, get_adapter
from rufus_edge.platform.base import NullSystemMetrics
from rufus.wasm_component import is_component as _is_component


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

class _MockHttpResponse:
    def __init__(self, status: int, body: dict, hdrs: dict = None):
        self.status_code = status
        self._body = body
        self.headers = hdrs or {}
        self.content = json.dumps(body).encode()

    def json(self):
        return self._body

    def text(self):
        return json.dumps(self._body)


# ─────────────────────────────────────────────────────────────────────────────
# NullSystemMetrics
# ─────────────────────────────────────────────────────────────────────────────

def test_null_system_metrics_returns_empty_dict():
    metrics = NullSystemMetrics()
    result = metrics.collect()
    assert isinstance(result, dict)
    assert result == {}


# ─────────────────────────────────────────────────────────────────────────────
# wasm_component.is_component
# ─────────────────────────────────────────────────────────────────────────────

def test_is_component_detects_component_magic():
    component_binary = b"\x00asm\x0d\x00\x01\x00" + b"\x00" * 100
    assert _is_component(component_binary) is True


def test_is_component_rejects_core_module():
    core_binary = b"\x00asm\x01\x00\x00\x00" + b"\x00" * 100
    assert _is_component(core_binary) is False


def test_is_component_rejects_short_binary():
    assert _is_component(b"\x00asm") is False
    assert _is_component(b"") is False


def test_is_component_rejects_non_wasm():
    assert _is_component(b"PK\x03\x04") is False  # ZIP magic
    assert _is_component(b"\x7fELF") is False      # ELF magic


# ─────────────────────────────────────────────────────────────────────────────
# detect_platform
# ─────────────────────────────────────────────────────────────────────────────

def test_detect_platform_returns_native_on_cpython():
    """On native CPython, detect_platform() must return NativePlatformAdapter."""
    import sys
    # Guard: only run if not inside a WASI or Pyodide environment
    if sys.platform == "wasm32" or "pyodide" in sys.modules:
        pytest.skip("Not running on native CPython")

    from rufus_edge.platform.native import NativePlatformAdapter
    adapter = detect_platform()
    assert isinstance(adapter, NativePlatformAdapter)


# ─────────────────────────────────────────────────────────────────────────────
# NativePlatformAdapter (using monkey-patched httpx)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_native_http_get_success(monkeypatch):
    from rufus_edge.platform.native import NativePlatformAdapter

    expected = {"status": "ok"}

    class _FakeClient:
        async def get(self, url, **kwargs):
            return type("R", (), {
                "status_code": 200,
                "json": lambda self: expected,
                "text": "ok",
                "headers": {},
                "content": json.dumps(expected).encode(),
            })()

        async def aclose(self):
            pass

    adapter = NativePlatformAdapter()
    adapter._client = _FakeClient()

    resp = await adapter.http_get("http://test/health", headers={})
    assert resp.status_code == 200
    assert resp.json() == expected


@pytest.mark.asyncio
async def test_native_http_post_success(monkeypatch):
    from rufus_edge.platform.native import NativePlatformAdapter

    captured = {}
    expected = {"accepted": []}

    class _FakeClient:
        async def post(self, url, json=None, **kwargs):
            captured["url"] = url
            captured["json"] = json
            return type("R", (), {
                "status_code": 200,
                "json": lambda self: expected,
                "text": "{}",
                "headers": {},
                "content": b"{}",
            })()

        async def aclose(self):
            pass

    adapter = NativePlatformAdapter()
    adapter._client = _FakeClient()

    payload = {"transactions": []}
    resp = await adapter.http_post("http://test/sync", json=payload, headers={})
    assert resp.status_code == 200
    assert captured["json"] == payload


def test_native_system_metrics_returns_dict():
    from rufus_edge.platform.native import NativePlatformAdapter

    adapter = NativePlatformAdapter()
    metrics = adapter.system_metrics()
    assert isinstance(metrics, dict)
    # Either has psutil keys or is empty — both are valid
    for key in metrics:
        assert key in ("cpu_percent", "mem_percent", "disk_percent")


def test_native_is_wasm_capable_returns_bool():
    from rufus_edge.platform.native import NativePlatformAdapter

    adapter = NativePlatformAdapter()
    result = adapter.is_wasm_capable()
    assert isinstance(result, bool)


# ─────────────────────────────────────────────────────────────────────────────
# WasiPlatformAdapter (urllib fallback, no actual WASI host needed)
# ─────────────────────────────────────────────────────────────────────────────

def test_wasi_system_metrics_returns_empty():
    from rufus_edge.platform.wasi import WasiPlatformAdapter

    adapter = WasiPlatformAdapter()
    assert adapter.system_metrics() == {}


def test_wasi_is_wasm_capable():
    from rufus_edge.platform.wasi import WasiPlatformAdapter

    adapter = WasiPlatformAdapter()
    assert adapter.is_wasm_capable() is True


@pytest.mark.asyncio
async def test_wasi_http_get_via_urllib(monkeypatch):
    """WasiPlatformAdapter._urllib_request works when mocked."""
    from rufus_edge.platform.wasi import WasiPlatformAdapter, _WasiHttpResponse

    async def _fake_request(method, url, headers, body):
        return _WasiHttpResponse(200, b'{"status":"ok"}', {})

    adapter = WasiPlatformAdapter()
    monkeypatch.setattr(adapter, "_urllib_request", _fake_request)

    resp = await adapter.http_get("http://fake/health", headers={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ─────────────────────────────────────────────────────────────────────────────
# PyodidePlatformAdapter (urllib fallback when js module absent)
# ─────────────────────────────────────────────────────────────────────────────

def test_pyodide_system_metrics_returns_empty():
    from rufus_edge.platform.pyodide import PyodidePlatformAdapter

    adapter = PyodidePlatformAdapter()
    assert adapter.system_metrics() == {}


def test_pyodide_is_wasm_capable_false_outside_browser():
    from rufus_edge.platform.pyodide import PyodidePlatformAdapter

    adapter = PyodidePlatformAdapter()
    # Outside Pyodide, js module not importable → False
    assert adapter.is_wasm_capable() is False


@pytest.mark.asyncio
async def test_pyodide_http_get_via_urllib(monkeypatch):
    """PyodidePlatformAdapter falls back to urllib when js is absent."""
    from rufus_edge.platform.pyodide import PyodidePlatformAdapter, _PyodideHttpResponse

    async def _fake_fetch(method, url, headers, body):
        return _PyodideHttpResponse(200, b'{"pong":true}', {})

    adapter = PyodidePlatformAdapter()
    monkeypatch.setattr(adapter, "_urllib_fetch", _fake_fetch)
    # Also prevent js import path from being tried
    monkeypatch.setattr(adapter, "_js_fetch", _fake_fetch)

    resp = await adapter.http_get("http://fake/ping", headers={})
    assert resp.status_code == 200
    assert resp.json()["pong"] is True


# ─────────────────────────────────────────────────────────────────────────────
# SyncManager adapter wiring
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_manager_uses_injected_adapter():
    """SyncManager.check_connectivity() uses the injected adapter."""
    from rufus_edge.sync_manager import SyncManager
    from unittest.mock import AsyncMock, MagicMock

    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_adapter = MagicMock()
    mock_adapter.http_get = AsyncMock(return_value=mock_response)

    mock_persistence = MagicMock()

    sm = SyncManager(
        persistence=mock_persistence,
        sync_url="http://fake",
        device_id="dev-001",
        api_key="key",
        platform_adapter=mock_adapter,
    )
    sm._adapter = mock_adapter  # skip initialize()

    result = await sm.check_connectivity()
    assert result is True
    mock_adapter.http_get.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# ConfigManager adapter wiring
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_config_manager_uses_injected_adapter():
    """ConfigManager.pull_config() uses the injected adapter."""
    from rufus_edge.config_manager import ConfigManager
    from unittest.mock import AsyncMock, MagicMock

    mock_config = {
        "device_id": "dev-001",
        "version": "1.0",
        "floor_limit": "25.00",
        "fraud_rules": [],
        "features": {},
        "workflows": {},
        "models": {},
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_config
    mock_response.headers = {}

    mock_adapter = MagicMock()
    mock_adapter.http_get = AsyncMock(return_value=mock_response)

    cm = ConfigManager(
        config_url="http://fake",
        device_id="dev-001",
        api_key="key",
        platform_adapter=mock_adapter,
    )
    cm._adapter = mock_adapter  # skip auto-detect in initialize()

    updated = await cm.pull_config()
    assert updated is True
    assert cm.config is not None
    mock_adapter.http_get.assert_called_once()
