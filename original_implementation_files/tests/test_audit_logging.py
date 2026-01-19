import asyncio
import pytest
from confucius.workflow import Workflow, WorkflowStep
from pydantic import BaseModel
from typing import Dict, Any, Optional

class TestState(BaseModel):
    data: str = ""

@pytest.mark.asyncio
async def test_audit_log_persisted_on_step_completion(monkeypatch):
    """
    Verify that Workflow.next_step triggers log_audit_event_sync.
    """
    
    # Fake Store
    class FakePostgresStore:
        def __init__(self):
            self.audit_logs = []
            self.metrics = []

        async def log_audit_event(self, workflow_id, event_type, step_name=None, user_id=None, worker_id=None, old_state=None, new_state=None, decision_rationale=None, metadata=None):
            self.audit_logs.append({
                "workflow_id": workflow_id,
                "event_type": event_type,
                "step_name": step_name,
                "metadata": metadata
            })
            return True

        async def record_metric(self, workflow_id, workflow_type, metric_name, metric_value, unit=None, step_name=None, tags=None):
            self.metrics.append({
                "workflow_id": workflow_id,
                "metric_name": metric_name,
                "step_name": step_name
            })
            return True

        async def save_workflow(self, workflow_id, workflow_instance):
            pass

        async def log_execution(self, workflow_id: str, execution_id: str, step_name: str, event_type: str, message: str, metadata: Optional[Dict[str, Any]] = None):
            pass

    fake_store = FakePostgresStore()

    async def fake_get_postgres_store():
        return fake_store

    # Patch confucius.persistence.get_postgres_store
    monkeypatch.setattr("confucius.persistence.get_postgres_store", fake_get_postgres_store)

    # Define Workflow
    def step_func(state: TestState, **kwargs):
        state.data = "processed"
        return {"result": "success"}

    step = WorkflowStep(name="Step1", func=step_func, automate_next=False)
    
    wf = Workflow(
        workflow_steps=[step],
        initial_state_model=TestState(),
        workflow_type="AuditTest",
        steps_config=[{"name": "Step1"}],
        state_model_path="tests.test_audit_logging.TestState"
    )

    # Execute step
    result, next_step = wf.next_step({})

    # Wait for async tasks (since log_audit_event_sync uses pg_executor which uses run_in_executor/loop)
    # Actually, run_coroutine_sync blocks until done, so we don't need to wait if we are mocking correctly?
    # Wait, pg_executor.run_coroutine_sync uses run_coroutine_threadsafe.result().
    # So it blocks the calling thread (this test thread).
    # Since we mocked get_postgres_store which returns a fake store with async methods,
    # and pg_executor runs those async methods in a separate loop/thread.
    # It should work.

    assert len(fake_store.audit_logs) == 1
    assert fake_store.audit_logs[0]["event_type"] == "STEP_COMPLETED"
    assert fake_store.audit_logs[0]["step_name"] == "Step1"
    
    assert len(fake_store.metrics) >= 1
    assert fake_store.metrics[0]["metric_name"] == "step_completed_count"
