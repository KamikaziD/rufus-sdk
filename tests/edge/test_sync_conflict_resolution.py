"""
Sync conflict resolution tests — Sprint 2.

Verifies that cloud-rejected transactions transition to FAILED status
instead of being re-queued on every sync cycle.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus_edge.sync_manager import SyncManager
from rufus_edge.models import SyncStatus


@pytest_asyncio.fixture
async def sync_manager_with_pending(tmp_path):
    persistence = SQLitePersistenceProvider(db_path=str(tmp_path / "conflict_test.db"))
    await persistence.initialize()

    # Insert a parent workflow record (required by FK constraint on tasks table)
    await persistence.save_workflow(
        "wf-reject-test",
        {
            "workflow_id": "wf-reject-test",
            "workflow_type": "SAFTest",
            "status": "ACTIVE",
            "current_step_index": 0,
            "current_step_name": "SAF_Sync",
            "current_state": {},
            "workflow_definition": {},
            "state_model_path": "tests.edge.test_sync_conflict_resolution",
            "created_at": "2026-03-14T00:00:00",
            "updated_at": "2026-03-14T00:00:00",
        },
    )

    # Insert a pending SAF task with all required SAFTransaction fields
    await persistence.create_task_record(
        execution_id="wf-reject-test",
        step_name="SAF_Sync",
        step_index=0,
        task_data={
            "transaction": {
                "transaction_id": "txn-001",
                "idempotency_key": "key-001",
                "device_id": "test-device",
                "merchant_id": "merch-001",
                "amount": "9.99",
                "currency": "USD",
                "card_token": "tok_test",
                "card_last_four": "4242",
                "encrypted_payload": None,
                "encryption_key_id": "default",
            },
        },
        idempotency_key="key-001",
    )

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

    # Verify the task is now FAILED
    async with persistence.conn.execute(
        "SELECT status FROM tasks WHERE step_name = 'SAF_Sync' AND idempotency_key = 'key-001'"
    ) as cursor:
        row = await cursor.fetchone()

    assert row is not None
    assert row[0] == "FAILED"


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
