"""
Sequence counter tests — Sprint 2.

Verifies that _next_sequence() returns strictly increasing values across
multiple calls, even when interleaved across conceptual sync calls.
"""

import pytest
import pytest_asyncio

from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus_edge.sync_manager import SyncManager


@pytest_asyncio.fixture
async def sync_manager(tmp_path):
    persistence = SQLitePersistenceProvider(db_path=str(tmp_path / "seq_test.db"))
    await persistence.initialize()
    mgr = SyncManager(
        persistence=persistence,
        sync_url="http://localhost",
        device_id="test-device-001",
        api_key="test-key",
    )
    await mgr.initialize()
    yield mgr
    await persistence.close()


@pytest.mark.asyncio
async def test_sequence_starts_at_one(sync_manager):
    seq = await sync_manager._next_sequence()
    assert seq == 1


@pytest.mark.asyncio
async def test_sequence_is_monotonic(sync_manager):
    values = [await sync_manager._next_sequence() for _ in range(10)]
    assert values == list(range(1, 11))


@pytest.mark.asyncio
async def test_sequence_across_three_sync_calls(sync_manager):
    """Simulates 10 transactions across 3 sync batches — sequences must be strictly increasing."""
    seq1 = await sync_manager._next_sequence()  # batch 1
    seq2 = await sync_manager._next_sequence()  # batch 2
    seq3 = await sync_manager._next_sequence()  # batch 3
    assert seq1 < seq2 < seq3
    assert seq1 == 1
    assert seq2 == 2
    assert seq3 == 3


@pytest.mark.asyncio
async def test_sequence_persists_across_manager_instances(tmp_path):
    """Sequence state survives manager restart (persisted in SQLite)."""
    persistence = SQLitePersistenceProvider(db_path=str(tmp_path / "persist_seq.db"))
    await persistence.initialize()

    mgr1 = SyncManager(
        persistence=persistence,
        sync_url="http://localhost",
        device_id="dev-restart",
        api_key="key",
    )
    await mgr1.initialize()
    seq1 = await mgr1._next_sequence()
    seq2 = await mgr1._next_sequence()
    assert seq2 == 2

    # Simulate restart: new SyncManager, same persistence
    mgr2 = SyncManager(
        persistence=persistence,
        sync_url="http://localhost",
        device_id="dev-restart",
        api_key="key",
    )
    await mgr2.initialize()
    seq3 = await mgr2._next_sequence()
    assert seq3 == 3  # Continues from where mgr1 left off

    await persistence.close()
