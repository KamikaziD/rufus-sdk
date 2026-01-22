import asyncio
import json
from types import SimpleNamespace

import pytest

import src.confucius.tasks as tasks_module


class DummyConn:
    def __init__(self, executed):
        self._select_called = 0
        self.executed = executed  # list to record execute calls

    async def fetchrow(self, query, *args):
        q = query.strip().lower()
        if q.startswith("select status from tasks"):
            # First SELECT -> PENDING
            self._select_called += 1
            return {"status": "PENDING"}
        if q.strip().startswith("update tasks") and "returning" in q:
            # claiming update returns a row if it succeeds
            return {"task_id": "t-claimed", "status": "RUNNING"}
        # Fallback
        return None

    async def execute(self, query, *args):
        # record roughly which idempotency_key was updated
        self.executed.append((query, args))
        return None


class DummyPoolAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DummyPool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return DummyPoolAcquire(self.conn)


class DummyStore:
    def __init__(self, conn):
        self.pool = DummyPool(conn)


@pytest.mark.asyncio
async def test_merge_and_resume_parallel_tasks_marks_tasks_and_resumes(monkeypatch):
    # Prepare input results with idempotency keys in different shapes
    results = [
        {"_confucius": {"idempotency_key": "k1"}, "val1": 1},
        {"idempotency_key": "k2", "val2": 2},
        {"no_key": "x"},
    ]

    # Setup dummy PG store/conn that records execute calls
    executed = []
    conn = DummyConn(executed)
    dummy_store = DummyStore(conn)

    async def fake_get_postgres_store():
        return dummy_store

    # Patch the tasks module's sync helper so tests can inject a DummyStore
    monkeypatch.setattr(tasks_module, "_get_postgres_store_sync",
                        lambda: dummy_store, raising=False)

    # Capture resume_workflow_from_celery calls
    called = {}

    def fake_resume_workflow_from_celery(workflow_id, step_result, next_step_index_or_name, completed_step_index=None):
        called['args'] = (workflow_id, step_result,
                          next_step_index_or_name, completed_step_index)

    monkeypatch.setattr(tasks_module, "resume_workflow_from_celery",
                        fake_resume_workflow_from_celery, raising=False)

    # Run the merge function in a thread so the sync function can call asyncio.run safely
    merged = await asyncio.to_thread(
        tasks_module.merge_and_resume_parallel_tasks,
        results,
        "wf-1",
        3,
        None
    )

    # The function returns merged_results synchronously
    assert isinstance(merged, dict)
    # Expect merged to contain val1 and val2
    assert merged.get("val1") == 1
    assert merged.get("val2") == 2

    # The dummy conn should have recorded UPDATEs for both k1 and k2
    assert any("k1" in str(args) or "k2" in str(args)
               for (_q, args) in executed)

    # Ensure resume was called (it calls resume_workflow_from_celery)
    assert 'args' in called
    wf_id, arg_res, next_idx, completed_idx = called['args']
    assert wf_id == "wf-1"
    # merged results passed into resume should match our merged dict
    assert isinstance(arg_res, dict)
    assert arg_res.get("val1") == 1 and arg_res.get("val2") == 2
    assert completed_idx == 3


def test_resume_from_async_task_claims_and_marks_complete(monkeypatch):
    # Simulate an async task result with idempotency key
    result = {"_confucius": {"idempotency_key": "k-123"}, "out": "ok"}

    # Dummy conn logic: SELECT returns PENDING, UPDATE returning row succeeds,
    # and final execute for marking complete will be recorded.
    executed = []

    class Conn2:
        def __init__(self):
            self._select_seen = False

        async def fetchrow(self, query, *args):
            q = query.strip().lower()
            if q.startswith("select status from tasks"):
                # return pending on first check
                return {"status": "PENDING"}
            if q.strip().startswith("update tasks") and "returning" in q:
                return {"task_id": "t1", "status": "RUNNING"}
            return None

        async def execute(self, query, *args):
            executed.append((query, args))
            return None

    conn = Conn2()
    dummy_store = DummyStore(conn)

    async def fake_get_postgres_store():
        return dummy_store

    # Patch the tasks module's sync helper to return the dummy store for this test
    monkeypatch.setattr(tasks_module, "_get_postgres_store_sync",
                        lambda: dummy_store, raising=False)

    # Patch resume_workflow_from_celery so we don't try to execute workflow logic
    called = {}

    def fake_resume_workflow_from_celery(workflow_id, step_result, next_step_index_or_name, completed_step_index=None):
        called['args'] = (workflow_id, step_result,
                          next_step_index_or_name, completed_step_index)

    monkeypatch.setattr(tasks_module, "resume_workflow_from_celery",
                        fake_resume_workflow_from_celery, raising=False)

    # Call the function under test
    out = tasks_module.resume_from_async_task(
        result, workflow_id="wf-xyz", current_step_index=2)

    # It should return the same result object
    assert out == result

    # resume_workflow_from_celery should have been invoked
    assert 'args' in called
    wf_id, step_res, next_idx, completed_idx = called['args']
    assert wf_id == "wf-xyz"
    assert completed_idx == 2

    # The dummy conn should have had an execute to mark completion
    assert any("COMPLETED" in q or "completed_at" in q for (
        q, _args) in executed)
