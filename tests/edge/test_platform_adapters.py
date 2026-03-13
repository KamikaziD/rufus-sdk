"""
Unit tests for rufus_edge.platform adapters.

All three adapters (Native, Pyodide, WASI) are tested with mocked HTTP so
the tests run on native CPython without a browser or WASI runtime.
"""

from __future__ import annotations

import asyncio
import json
from typing import Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rufus_edge.platform.base import HttpResponse, PlatformAdapter, SystemMetrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_response(status: int, body: dict | bytes | str, headers: dict = None) -> HttpResponse:
    if isinstance(body, dict):
        raw = json.dumps(body).encode()
    elif isinstance(body, str):
        raw = body.encode()
    else:
        raw = body
    return HttpResponse(status_code=status, body=raw, headers=headers or {})


# ---------------------------------------------------------------------------
# NativePlatformAdapter
# ---------------------------------------------------------------------------

class TestNativePlatformAdapter:
    def _make_adapter(self):
        from rufus_edge.platform.native import NativePlatformAdapter
        return NativePlatformAdapter(default_headers={"X-App": "test"})

    @pytest.mark.asyncio
    async def test_http_get_success(self):
        adapter = self._make_adapter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = json.dumps({"ok": True}).encode()
        mock_resp.headers = {"content-type": "application/json"}

        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_resp)):
            resp = await adapter.http_get("http://example.com/health")

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    @pytest.mark.asyncio
    async def test_http_post_success(self):
        adapter = self._make_adapter()
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.content = json.dumps({"id": "abc"}).encode()
        mock_resp.headers = {}

        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)):
            resp = await adapter.http_post(
                "http://example.com/sync",
                body=json.dumps({"txn": 1}).encode(),
            )

        assert resp.status_code == 201
        assert resp.json()["id"] == "abc"

    def test_get_system_metrics_returns_metrics_object(self):
        adapter = self._make_adapter()
        # psutil may or may not be installed in CI — either way we get a SystemMetrics
        metrics = adapter.get_system_metrics()
        assert isinstance(metrics, SystemMetrics)
        assert metrics.cpu_percent >= 0.0

    @pytest.mark.asyncio
    async def test_default_headers_merged(self):
        """default_headers must be merged into every outgoing request."""
        from rufus_edge.platform.native import NativePlatformAdapter
        adapter = NativePlatformAdapter(default_headers={"Authorization": "Bearer tok"})

        captured: Dict = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"{}"
        mock_resp.headers = {}

        async def fake_client_get(url, headers=None, timeout=30.0):
            captured.update(headers or {})
            return mock_resp

        # Patch the underlying httpx client .get method
        client = await adapter._get_client()
        with patch.object(client, "get", side_effect=fake_client_get):
            await adapter.http_get("http://example.com")

        assert captured.get("Authorization") == "Bearer tok"

    @pytest.mark.asyncio
    async def test_aclose_is_idempotent(self):
        from rufus_edge.platform.native import NativePlatformAdapter
        adapter = NativePlatformAdapter()
        # Should not raise even if client was never created
        await adapter.aclose()
        await adapter.aclose()


# ---------------------------------------------------------------------------
# WasiPlatformAdapter (native fallback path)
# ---------------------------------------------------------------------------

class TestWasiPlatformAdapter:
    def _make_adapter(self):
        from rufus_edge.platform.wasi import WasiPlatformAdapter
        adapter = WasiPlatformAdapter()
        # Force native (httpx) path regardless of sys.platform
        adapter._in_wasi = False
        return adapter

    @pytest.mark.asyncio
    async def test_http_get_uses_httpx_fallback(self):
        adapter = self._make_adapter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"status":"ok"}'
        mock_resp.headers = {}

        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_resp)):
            resp = await adapter.http_get("http://example.com/health")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_http_post_uses_httpx_fallback(self):
        adapter = self._make_adapter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"accepted":[]}'
        mock_resp.headers = {}

        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)):
            resp = await adapter.http_post("http://example.com/sync", body=b"{}")

        assert resp.status_code == 200

    def test_system_metrics_are_zeros_in_wasi(self):
        from rufus_edge.platform.wasi import WasiPlatformAdapter
        adapter = WasiPlatformAdapter()
        adapter._in_wasi = True
        m = adapter.get_system_metrics()
        assert m.cpu_percent == 0.0
        assert m.memory_used_mb == 0.0


# ---------------------------------------------------------------------------
# PyodidePlatformAdapter (mocked js.fetch)
# ---------------------------------------------------------------------------

class TestPyodidePlatformAdapter:
    """
    PyodidePlatformAdapter requires ``js`` and ``pyodide`` modules which only
    exist inside Pyodide.  We stub them out here.
    """

    def _make_adapter(self):
        # Stub the pyodide modules before importing the adapter
        import sys
        import types

        # Create fake js module
        js_mod = types.ModuleType("js")
        pyodide_mod = types.ModuleType("pyodide")
        pyodide_ffi = types.ModuleType("pyodide.ffi")
        pyodide_ffi.to_js = lambda x, **kw: x  # identity
        pyodide_mod.ffi = pyodide_ffi

        sys.modules.setdefault("js", js_mod)
        sys.modules.setdefault("pyodide", pyodide_mod)
        sys.modules.setdefault("pyodide.ffi", pyodide_ffi)

        from rufus_edge.platform.pyodide import PyodidePlatformAdapter
        return PyodidePlatformAdapter(default_headers={"X-Test": "1"})

    def test_system_metrics_are_zeros(self):
        adapter = self._make_adapter()
        m = adapter.get_system_metrics()
        assert m.cpu_percent == 0.0

    def test_conforms_to_protocol(self):
        adapter = self._make_adapter()
        assert isinstance(adapter, PlatformAdapter)


# ---------------------------------------------------------------------------
# detect_platform() auto-selector
# ---------------------------------------------------------------------------

class TestDetectPlatform:
    def test_returns_native_on_cpython(self, monkeypatch):
        import sys
        import importlib
        from rufus_edge.platform.native import NativePlatformAdapter

        if sys.platform == "wasm32":
            pytest.skip("Running inside WASM")

        # Remove any stub 'js' module that earlier tests may have injected
        monkeypatch.delitem(sys.modules, "js", raising=False)

        # Reload the platform package so detect_platform() re-evaluates
        import rufus_edge.platform as platform_pkg
        importlib.reload(platform_pkg)

        adapter = platform_pkg.detect_platform()
        assert isinstance(adapter, NativePlatformAdapter)

    def test_returns_wasi_on_wasm32(self, monkeypatch):
        import sys
        from rufus_edge.platform.wasi import WasiPlatformAdapter

        monkeypatch.setattr(sys, "platform", "wasm32")
        from importlib import reload
        import rufus_edge.platform as platform_pkg
        reload(platform_pkg)
        adapter = platform_pkg.detect_platform()
        assert isinstance(adapter, WasiPlatformAdapter)

    def test_http_response_json(self):
        resp = HttpResponse(status_code=200, body=b'{"key": "value"}')
        assert resp.json() == {"key": "value"}
        assert resp.text == '{"key": "value"}'
        assert resp.content == b'{"key": "value"}'
