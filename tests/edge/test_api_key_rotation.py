"""
API key rotation tests — Sprint 4.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_rotate_api_key_succeeds_with_correct_key():
    """rotate_api_key returns a new key dict when current key is valid."""
    service = MagicMock()
    service.authenticate_device = AsyncMock(return_value=True)

    import secrets
    import hashlib

    new_key = secrets.token_urlsafe(32)

    async def _fake_execute(query, *args):
        return "UPDATE 1"

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value="UPDATE 1")

    mock_pool = AsyncMock()
    mock_pool.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.__aexit__ = AsyncMock(return_value=False)

    from ruvon_server.device_service import DeviceService

    mock_persistence = MagicMock()
    mock_persistence.pool = MagicMock()
    mock_persistence.pool.acquire = MagicMock(return_value=mock_pool)

    svc = DeviceService(mock_persistence)
    svc.authenticate_device = AsyncMock(return_value=True)

    result = await svc.rotate_api_key("device-001", "current-valid-key")
    assert result is not None
    assert "new_api_key" in result
    assert result["device_id"] == "device-001"
    assert "rotated_at" in result


@pytest.mark.asyncio
async def test_rotate_api_key_fails_with_wrong_key():
    """rotate_api_key returns None when current key is invalid."""
    from ruvon_server.device_service import DeviceService

    mock_persistence = MagicMock()
    svc = DeviceService(mock_persistence)
    svc.authenticate_device = AsyncMock(return_value=False)

    result = await svc.rotate_api_key("device-001", "wrong-key")
    assert result is None
