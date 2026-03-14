"""
Process-safe sync lock tests — Sprint 2.

Verifies that concurrent calls to sync_all_pending() result in the second
call being skipped (not run concurrently) via the SQLite advisory lock.
"""

import pytest
import pytest_asyncio
import asyncio
from unittest.mock import AsyncMock, MagicMock

from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus_edge.sync_manager import SyncManager
from rufus_edge.models import SyncStatus


@pytest_asyncio.fixture
async def sync_manager(tmp_path):
    persistence = SQLitePersistenceProvider(db_path=str(tmp_path / "lock_test.db"))
    await persistence.initialize()

    mgr = SyncManager(
        persistence=persistence,
        sync_url="http://localhost",
        device_id="lock-device",
        api_key="lock-key",
    )
    mock_adapter = MagicMock()
    mock_adapter.http_post = AsyncMock()
    mgr._adapter = mock_adapter
    yield mgr, persistence
    await persistence.close()


@pytest.mark.asyncio
async def test_acquire_and_release_lock(sync_manager):
    """Basic acquire → release cycle."""
    mgr, _ = sync_manager
    acquired = await mgr._acquire_sync_lock()
    assert acquired is True
    # Attempting to acquire again should fail
    second = await mgr._acquire_sync_lock()
    assert second is False
    # After release, acquire should succeed again
    await mgr._release_sync_lock()
    third = await mgr._acquire_sync_lock()
    assert third is True
    await mgr._release_sync_lock()


@pytest.mark.asyncio
async def test_concurrent_sync_second_is_skipped(sync_manager):
    """
    When no pending transactions exist, sync_all_pending() returns COMPLETED
    immediately. Test that holding the lock causes the second call to return
    a FAILED report with 'already in progress'.
    """
    mgr, _ = sync_manager

    # Manually acquire the lock to simulate a running sync
    await mgr._acquire_sync_lock()

    # Second call should be skipped
    report = await mgr.sync_all_pending()
    assert report.status == SyncStatus.FAILED
    assert any("in progress" in (e.get("message") or "") for e in report.errors)

    # Cleanup
    await mgr._release_sync_lock()


@pytest.mark.asyncio
async def test_stale_lock_is_taken(sync_manager):
    """A lock older than _lock_stale_seconds should be forcibly taken."""
    mgr, persistence = sync_manager

    # Insert a stale lock (timestamp in the past)
    old_ts = "2020-01-01T00:00:00"
    await persistence.conn.execute(
        "INSERT INTO sync_lock (lock_key, holder_id, acquired_at) VALUES ('saf_sync', 'old-holder', ?)",
        (old_ts,),
    )
    await persistence.conn.commit()

    # Should succeed because the lock is stale
    acquired = await mgr._acquire_sync_lock()
    assert acquired is True
    await mgr._release_sync_lock()
