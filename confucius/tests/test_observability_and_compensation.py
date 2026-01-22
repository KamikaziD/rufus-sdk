import asyncio
import json
import pytest

from confucius.observability import monitor
from confucius.workflow import Workflow, CompensatableStep
from pydantic import BaseModel
import types

# Simple Pydantic state model for tests


class DummyState(BaseModel):
    value: int = 0
    saga_log: list = []


@pytest.mark.asyncio
async def test_monitor_handles_notification_and_forwards_to_registered_client():
    # Prepare a fake websocket that collects sent messages
    class FakeWebSocket:
        def __init__(self):
            self.messages = []

        async def send_json(self, data):
            self.messages.append(("json", data))

        async def send_text(self, text):
            self.messages.append(("text", text))

    execution_id = "exec-123"
    ws = FakeWebSocket()

    # Ensure no clients for this execution initially
    assert execution_id not in monitor.active_connections

    # Register client
    await monitor.register_client(execution_id, ws)
    assert execution_id in monitor.active_connections

    # Simulate a payload from Postgres LISTEN/NOTIFY
    payload = json.dumps({
        "execution_id": execution_id,
        "status": "ACTIVE",
        "current_step": 1,
        "workflow_type": "TestWorkflow"
    })

    # Call the internal handler directly
    await monitor._handle_notification(connection=None, pid=0, channel="workflow_update", payload=payload)

    # Validate the websocket received the payload
    assert ws.messages, "Expected monitor to forward notification to websocket"
    kind, data = ws.messages[-1]
    assert kind == "json"
    assert data["execution_id"] == execution_id or data.get(
        "id") == execution_id or data.get("workflow_id") == execution_id

    # Cleanup
    await monitor.unregister_client(execution_id, ws)


@pytest.mark.asyncio
async def test_saga_rollback_persists_compensation_log(monkeypatch):
    """
    Verify that when _execute_saga_rollback runs it attempts to persist compensation logs
    via persistence_postgres.get_postgres_store(). We monkeypatch the Postgres store to
    capture calls to log_compensation().
    """

    # Create a fake Postgres store with an async log_compensation method
    class FakePostgresStore:
        def __init__(self):
            self.logged = []

        async def log_compensation(self, execution_id, step_name, step_index, action_type, action_result, error_message=None, state_before=None, state_after=None, executed_by=None):
            # Store the call for assertions
            self.logged.append({
                "execution_id": execution_id,
                "step_name": step_name,
                "step_index": step_index,
                "action_type": action_type,
                "action_result": action_result,
                "error_message": error_message,
                "state_before": state_before,
                "state_after": state_after,
                "executed_by": executed_by
            })
            return True

        async def save_workflow(self, workflow_id, workflow_instance):
            # Mock save
            pass


    fake_store = FakePostgresStore()

    async def fake_get_postgres_store():
        return fake_store

    # Patch the getter used by the persistence module
    monkeypatch.setattr(
        "confucius.persistence.get_postgres_store", fake_get_postgres_store)

    # Build a workflow with one compensatable step that will be considered completed
    def forward_action(state: DummyState, **kwargs):
        # Simulate forward action that altered state
        state.value = 42
        return {"transaction_id": "TX123"}

    def compensate_action(state: DummyState, **kwargs):
        # Compensation resets the value
        state.value = 0
        return {"refunded": "TX123"}

    step = CompensatableStep(
        name="Charge_Card",
        func=forward_action,
        compensate_func=compensate_action,
        required_input=[]
    )

    # Create workflow instance manually
    wf = Workflow(
        workflow_steps=[step],
        initial_state_model=DummyState(),
        workflow_type="Payment",
        steps_config=[{"name": "Charge_Card"}],
        state_model_path="tests.test_observability_and_compensation.DummyState"
    )

    # Simulate that the step was completed and pushed onto completed_steps_stack
    wf.saga_mode = True
    wf.completed_steps_stack = [{
        "step_index": 0,
        "step_name": "Charge_Card",
        "state_snapshot": {"value": 42}
    }]

    # The state should reflect that forward action had been run previously
    wf.state.value = 42

    # Call rollback; this is synchronous method that will schedule async persistence when running under an event loop
    wf._execute_saga_rollback()

    # Allow scheduled tasks to run (the workflow implementation schedules async tasks when event loop is running)
    await asyncio.sleep(0.1)

    # Validate that the fake Postgres store received at least one compensation log entry
    assert fake_store.logged, "Expected compensation log to be persisted via Postgres store"
    entry = fake_store.logged[-1]
    assert entry["execution_id"] == wf.id
    assert entry["step_name"] == "Charge_Card"
    assert entry["action_type"] in ("COMPENSATE", "COMPENSATE_FAILED")
