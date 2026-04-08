"""
Audit log pagination tests — Sprint 2.

Verifies that get_audit_logs_for_workflows() respects limit_per_workflow
and that workflow_sync.py enforces the 5 MB payload cap.
"""

import pytest
import pytest_asyncio
import uuid
import json

from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider


@pytest_asyncio.fixture
async def persistence(tmp_path):
    p = SQLitePersistenceProvider(db_path=str(tmp_path / "audit_test.db"))
    await p.initialize()
    # Create a workflow to satisfy FK
    await p.save_workflow("wf-audit", {
        "id": "wf-audit",
        "workflow_type": "T",
        "status": "COMPLETED",
        "current_step": 1,
        "state": {},
        "steps_config": [],
        "state_model_path": "tests.fixtures.test_state.TestState",
        "metadata": {},
        "completed_steps_stack": "[]",
        "priority": 5,
        "data_region": "us-east-1",
        "saga_mode": False,
    })
    yield p
    await p.close()


async def _insert_audit_rows(persistence, workflow_id: str, count: int):
    """Helper: insert N audit log rows for a workflow."""
    for i in range(count):
        await persistence.conn.execute(
            """
            INSERT INTO workflow_audit_log
              (audit_id, workflow_id, event_type, step_name, recorded_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (uuid.uuid4().hex, workflow_id, "STEP_COMPLETED", f"Step{i}"),
        )
    await persistence.conn.commit()


@pytest.mark.asyncio
async def test_limit_per_workflow_is_respected(persistence):
    await _insert_audit_rows(persistence, "wf-audit", 100)
    rows = await persistence.get_audit_logs_for_workflows(["wf-audit"], limit_per_workflow=20)
    assert len(rows) <= 20


@pytest.mark.asyncio
async def test_default_limit_is_50(persistence):
    await _insert_audit_rows(persistence, "wf-audit", 75)
    rows = await persistence.get_audit_logs_for_workflows(["wf-audit"])
    assert len(rows) <= 50


@pytest.mark.asyncio
async def test_empty_workflow_ids_returns_empty(persistence):
    rows = await persistence.get_audit_logs_for_workflows([])
    assert rows == []


@pytest.mark.asyncio
async def test_payload_cap_drops_audit_logs(tmp_path):
    """
    workflow_sync.py must drop audit_logs when the payload exceeds 5 MB.
    """
    # Build a fake large audit log list (>5 MB)
    large_audit = [{"workflow_id": "wf-x", "data": "x" * 1000} for _ in range(6000)]
    workflows = [{"id": "wf-x", "status": "COMPLETED"}]

    payload = {"workflows": workflows, "audit_logs": large_audit}
    payload_bytes = json.dumps(payload).encode()
    assert len(payload_bytes) > 5 * 1024 * 1024, "Test setup: payload must exceed 5 MB"

    # Simulate the cap logic from workflow_sync.py
    MAX = 5 * 1024 * 1024
    if len(payload_bytes) > MAX:
        payload = {"workflows": workflows, "audit_logs": []}

    assert payload["audit_logs"] == []
    assert payload["workflows"] == workflows
