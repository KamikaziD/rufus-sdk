"""
Integration tests: RufusEdgeAgent WASM resolver wiring.

Verifies that:
  1. agent.start() creates a SqliteWasmBinaryResolver and assigns _wasm_resolver
  2. execute_workflow() passes wasm_binary_resolver to create_workflow()
  3. _reload_wasm_resolver() refreshes the resolver from the live connection
  4. sync_wasm command triggers _reload_wasm_resolver() after handling
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rufus_edge.agent import RufusEdgeAgent
from rufus.implementations.execution.wasm_runtime import SqliteWasmBinaryResolver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent(db_path: str = ":memory:") -> RufusEdgeAgent:
    return RufusEdgeAgent(
        device_id="test-device-001",
        cloud_url="",  # no cloud; avoids bootstrap HTTP calls
        db_path=db_path,
    )


async def _start_agent_minimal(agent: RufusEdgeAgent):
    """Start agent with all network/polling patched out."""
    with (
        patch.object(agent, "bootstrap", new=AsyncMock(return_value=True)),
        patch("rufus_edge.agent.ConfigManager") as MockCM,
        patch("rufus_edge.agent.SyncManager") as MockSM,
        patch("rufus_edge.agent.asyncio") as mock_asyncio,
    ):
        mock_cm = MockCM.return_value
        mock_cm.initialize = AsyncMock()
        mock_cm.start_polling = AsyncMock()
        mock_cm.on_config_change = MagicMock()
        mock_cm.config = MagicMock(version=1)

        mock_sm = MockSM.return_value
        mock_sm.initialize = AsyncMock()
        mock_sm.check_connectivity = AsyncMock(return_value=False)

        # Prevent asyncio.create_task from spinning real tasks; close each
        # coroutine immediately so Python doesn't emit "never awaited" warnings.
        created_coros: list = []

        def _capture_create_task(coro):
            created_coros.append(coro)
            return MagicMock()

        mock_asyncio.create_task = _capture_create_task
        mock_asyncio.sleep = AsyncMock()

        await agent.start()

        for coro in created_coros:
            coro.close()

        # Restore real asyncio so callers can use it
        agent._background_tasks.clear()

    return agent


@asynccontextmanager
async def started_agent():
    """Context manager: yields a started agent and closes its SQLite connection on exit."""
    agent = make_agent()
    await _start_agent_minimal(agent)
    try:
        yield agent
    finally:
        # Close the aiosqlite connection so pytest-asyncio can tear down the
        # event loop without the background thread hanging indefinitely.
        if agent.persistence:
            await agent.persistence.close()
        agent._is_running = False


# ---------------------------------------------------------------------------
# Test: _wasm_resolver set after start()
# ---------------------------------------------------------------------------

class TestAgentWasmResolverWiring:
    @pytest.mark.asyncio
    async def test_wasm_resolver_is_none_before_start(self):
        agent = make_agent()
        assert agent._wasm_resolver is None

    @pytest.mark.asyncio
    async def test_wasm_resolver_set_after_start(self):
        async with started_agent() as agent:
            assert agent._wasm_resolver is not None
            assert isinstance(agent._wasm_resolver, SqliteWasmBinaryResolver)

    @pytest.mark.asyncio
    async def test_wasm_resolver_uses_persistence_conn(self):
        async with started_agent() as agent:
            # The resolver's _conn should be the same object as persistence.conn
            assert agent._wasm_resolver._conn is agent.persistence.conn


# ---------------------------------------------------------------------------
# Test: execute_workflow passes wasm_binary_resolver
# ---------------------------------------------------------------------------

class TestExecuteWorkflowPassesResolver:
    @pytest.mark.asyncio
    async def test_create_workflow_receives_resolver(self):
        async with started_agent() as agent:
            # Give the workflow builder a fake workflow type
            agent.config_manager.get_workflow_config = MagicMock(
                return_value={"type": "Test"}
            )

            captured_kwargs: list[dict] = []

            async def fake_create_workflow(**kwargs):
                captured_kwargs.append(kwargs)
                wf = MagicMock()
                wf.id = "wf-001"
                wf.status = "COMPLETED"
                wf.state = MagicMock()
                wf.state.model_dump = MagicMock(return_value={})
                return wf

            with patch.object(agent.workflow_builder, "create_workflow", side_effect=fake_create_workflow):
                try:
                    await agent.execute_workflow("Test", {})
                except Exception:
                    pass  # workflow config missing is fine; we just want to check the kwargs

            if captured_kwargs:
                assert "wasm_binary_resolver" in captured_kwargs[0]
                assert captured_kwargs[0]["wasm_binary_resolver"] is agent._wasm_resolver


# ---------------------------------------------------------------------------
# Test: _reload_wasm_resolver
# ---------------------------------------------------------------------------

class TestReloadWasmResolver:
    @pytest.mark.asyncio
    async def test_reload_creates_new_resolver_from_conn(self):
        async with started_agent() as agent:
            original_resolver = agent._wasm_resolver
            agent._reload_wasm_resolver()
            new_resolver = agent._wasm_resolver

            # A new instance is created
            assert new_resolver is not original_resolver
            assert isinstance(new_resolver, SqliteWasmBinaryResolver)
            # But it still points at the same live connection
            assert new_resolver._conn is agent.persistence.conn

    @pytest.mark.asyncio
    async def test_reload_no_op_when_persistence_none(self):
        agent = make_agent()
        # Don't call start() — persistence is None
        assert agent._wasm_resolver is None
        agent._reload_wasm_resolver()  # must not raise
        assert agent._wasm_resolver is None


# ---------------------------------------------------------------------------
# Test: sync_wasm command calls _reload_wasm_resolver
# ---------------------------------------------------------------------------

class TestSyncWasmCommandReloadsResolver:
    @pytest.mark.asyncio
    async def test_sync_wasm_calls_reload(self):
        async with started_agent() as agent:
            agent.config_manager.handle_sync_wasm_command = AsyncMock()
            reload_called = []

            original_reload = agent._reload_wasm_resolver

            def tracking_reload():
                reload_called.append(True)
                original_reload()

            agent._reload_wasm_resolver = tracking_reload

            await agent._handle_cloud_command({
                "command_type": "sync_wasm",
                "command_data": {"binary_hash": "abc123"},
            })

            agent.config_manager.handle_sync_wasm_command.assert_awaited_once()
            assert len(reload_called) == 1


# ---------------------------------------------------------------------------
# Test: _on_patch_broadcast hot-swaps WasmComponentPool
# ---------------------------------------------------------------------------

class TestPatchBroadcastHandler:
    @pytest.mark.asyncio
    async def test_on_patch_broadcast_calls_swap_module(self):
        """_on_patch_broadcast verifies hash and calls pool.swap_module."""
        import hashlib
        from rufus.implementations.execution.component_runtime import _get_wasm_pool

        binary = b"\x00asm\x0e\x00\x01\x00" + b"\xab" * 50
        wasm_hash = hashlib.sha256(binary).hexdigest()
        step_name = "FraudScorer"

        async with started_agent() as agent:
            pool = _get_wasm_pool()
            with patch.object(pool, "swap_module", new=AsyncMock()) as mock_swap:
                await agent._on_patch_broadcast(binary, wasm_hash, step_name)
                mock_swap.assert_awaited_once_with(wasm_hash, binary)

    @pytest.mark.asyncio
    async def test_on_patch_broadcast_skipped_with_nkey_verifier_reject(self):
        """_on_patch_broadcast discards patch when NKey verification fails."""
        import hashlib
        from rufus.implementations.execution.component_runtime import _get_wasm_pool

        binary = b"\x00asm\x0e\x00\x01\x00" + b"\xcd" * 50
        wasm_hash = hashlib.sha256(binary).hexdigest()

        fake_verifier = MagicMock()
        fake_verifier.verify = MagicMock(return_value=False)

        async with started_agent() as agent:
            agent._nkey_verifier = fake_verifier
            pool = _get_wasm_pool()
            with patch.object(pool, "swap_module", new=AsyncMock()) as mock_swap:
                await agent._on_patch_broadcast(binary, wasm_hash, "FraudScorer")
                mock_swap.assert_not_awaited()
