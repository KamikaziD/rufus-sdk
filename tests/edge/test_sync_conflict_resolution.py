"""
Sync conflict resolution tests — Sprint 2.

Verifies that cloud-rejected transactions transition to FAILED status
instead of being re-queued on every sync cycle.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus_edge.sync_manager import SyncManager


@pytest_asyncio.fixture
async def sync_manager_with_pending(tmp_path):
    import uuid
    persistence = SQLitePersistenceProvider(db_path=str(tmp_path / "conflict_test.db"))
    await persistence.initialize()

    # Insert directly into saf_pending_transactions (the table sync_manager uses)
    await persistence.conn.execute(
        """
        INSERT INTO saf_pending_transactions
            (id, transaction_id, idempotency_key, workflow_id,
             amount_cents, currency, card_token, card_last_four,
             encrypted_payload, encryption_key_id,
             status, created_at, queued_at, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_sync', datetime('now'), datetime('now'), ?)
        """,
        (
            str(uuid.uuid4()), "txn-001", "key-001", None,
            999, "USD", "tok_test", "4242",
            "", "default", "{}",
        ),
    )
    await persistence.conn.commit()

    mgr = SyncManager(
        persistence=persistence,
        sync_url="http://localhost",
        device_id="test-device",
        api_key="test-key",
    )
    # Provide a mock adapter so network calls don't fire
    mock_adapter = MagicMock()
    mock_adapter.http_post = AsyncMock()
    mgr._adapter = mock_adapter
    yield mgr, persistence
    await persistence.close()


@pytest.mark.asyncio
async def test_rejected_transaction_becomes_failed(sync_manager_with_pending):
    """
    When the cloud rejects a transaction, mark_rejected() must set its status to FAILED.
    """
    mgr, persistence = sync_manager_with_pending

    # Simulate cloud rejecting "txn-001"
    await mgr.mark_rejected(["txn-001"])

    # Verify the row is now failed in saf_pending_transactions
    async with persistence.conn.execute(
        "SELECT status FROM saf_pending_transactions WHERE transaction_id = 'txn-001'"
    ) as cursor:
        row = await cursor.fetchone()

    assert row is not None
    assert row[0] == "failed"


@pytest.mark.asyncio
async def test_rejected_transactions_not_re_queued(sync_manager_with_pending):
    """
    After mark_rejected(), the transaction should not appear in _get_pending_transactions().
    """
    mgr, persistence = sync_manager_with_pending

    # Initially pending
    pending_before = await mgr._get_pending_transactions()
    assert len(pending_before) == 1

    # Reject it
    await mgr.mark_rejected(["txn-001"])

    # Now it should not appear in pending
    pending_after = await mgr._get_pending_transactions()
    assert len(pending_after) == 0
