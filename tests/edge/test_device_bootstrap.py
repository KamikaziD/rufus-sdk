"""
Device bootstrap tests — Sprint 4.

Verifies that bootstrap() auto-registers a factory-fresh device and stores
the returned API key, so subsequent calls to start() skip registration.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider
from ruvon_edge.agent import RufusEdgeAgent


@pytest_asyncio.fixture
async def fresh_agent(tmp_path):
    agent = RufusEdgeAgent(
        device_id="fresh-device-001",
        cloud_url="http://localhost:8000",
        api_key="",  # Factory-fresh: no key
        db_path=str(tmp_path / "bootstrap.db"),
    )
    agent.persistence = SQLitePersistenceProvider(db_path=str(tmp_path / "bootstrap.db"))
    await agent.persistence.initialize()
    yield agent
    await agent.persistence.close()


@pytest.mark.asyncio
async def test_bootstrap_registers_and_stores_key(fresh_agent):
    """A fresh device with no API key calls register and stores the key."""
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"api_key": "new-key-abc123"}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await fresh_agent.bootstrap(device_type="pos", merchant_id="merch-1")

    assert result is True
    assert fresh_agent.api_key == "new-key-abc123"


@pytest.mark.asyncio
async def test_bootstrap_loads_stored_key(fresh_agent):
    """If a key is already stored in SQLite, bootstrap uses it without calling register."""
    # Pre-store a key
    await fresh_agent.persistence.set_edge_sync_state("api_key", "stored-key-xyz")

    with patch("httpx.AsyncClient") as mock_client_cls:
        result = await fresh_agent.bootstrap()
        # Should NOT have made any HTTP calls
        mock_client_cls.assert_not_called()

    assert result is True
    assert fresh_agent.api_key == "stored-key-xyz"


@pytest.mark.asyncio
async def test_bootstrap_returns_false_on_failed_registration(fresh_agent):
    """Failed registration returns False without crashing."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.json.return_value = {}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await fresh_agent.bootstrap()

    assert result is False
    assert fresh_agent.api_key == ""  # Unchanged
