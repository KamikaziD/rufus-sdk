import importlib
import types
import uuid

from pydantic import BaseModel
from src.confucius.workflow import AsyncWorkflowStep


def test_async_step_generates_idempotency_key_and_returns_task_info(monkeypatch):
    """
    Verify that AsyncWorkflowStep.dispatch_async_task constructs an idempotency key
    and returns a dict containing that key and the dispatched async task id.
    This test mocks:
      - persistence_postgres.create_task_record (async)
      - celery.chain to provide an object with apply_async() that returns an object with .id
      - importlib.import_module to return a fake module with the task function
    """

    # Simple Pydantic-like state with model_dump()
    class DummyState(BaseModel):
        name: str = "tester"

        def model_dump(self):
            return {"name": self.name}

    state = DummyState()

    # Prepare an AsyncWorkflowStep with a fake function path
    step = AsyncWorkflowStep(
        name="Fake_Async",
        func_path="fake.module.fake_task",
    )

    # Mock create_task_record (async) to return a predictable idempotency_key
    async def fake_create_task_record(execution_id, step_name, step_index, task_data=None, idempotency_key=None, metadata=None, max_retries=3):
        return {"task_id": "dbtask-123", "idempotency_key": idempotency_key or f"{execution_id}:{step_index}:{'deadbeef'}"}

    monkeypatch.setattr("src.confucius.workflow.create_task_record",
                        fake_create_task_record, raising=False)
    # Also patch the persistence_postgres module reference just in case
    try:
        import src.confucius.persistence_postgres as pp
        monkeypatch.setattr(pp, "create_task_record",
                            fake_create_task_record, raising=False)
    except Exception:
        # if module path differs in environment, ignore
        pass

    # Fake task function object returned by importlib.import_module(...); it must expose .s()
    class FakeTask:
        def __init__(self, *args, **kwargs):
            pass

        @staticmethod
        def s(payload):
            # Return a mock signature object that has a .set() method
            signature = types.SimpleNamespace()
            signature.set = lambda queue: signature
            return signature

    fake_module = types.SimpleNamespace(fake_task=FakeTask)

    # Patch importlib.import_module to return our fake module when requested
    original_import_module = importlib.import_module

    def fake_import_module(name, package=None):
        if name == "fake.module":
            return fake_module
        return original_import_module(name, package)
    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    # Patch celery.chain to return an object with apply_async() that returns an object with id attr
    class FakeAsyncResult:
        def __init__(self, _id):
            self.id = _id

    class FakeChain:
        def __init__(self, *args, **kwargs):
            pass

        def apply_async(self):
            return FakeAsyncResult("async-456")

    # IMPORTANT: dispatch_async_task does a local import `from celery import chain`
    # at runtime, so patch the real celery.chain symbol (not the workflow module attribute).
    import celery
    monkeypatch.setattr(celery, "chain", lambda *a, **
                        k: FakeChain(), raising=False)

    # Now call dispatch_async_task and assert expected shape
    workflow_id = "workflow-1"
    step_index = 0

    result = step.dispatch_async_task(
        state=state, workflow_id=workflow_id, current_step_index=step_index)

    assert isinstance(result, dict)
    assert result.get("idempotency_key") is not None
    assert result.get("task_id") is not None
    assert result["_async_dispatch"] is True
    # idempotency key should contain the workflow id and step index
    assert str(workflow_id) in result["idempotency_key"]
    assert str(step_index) in result["idempotency_key"]
