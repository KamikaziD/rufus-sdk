"""
Base compliance test class for ExecutionProvider implementations.

Only tests the synchronous execute_sync_step_function since async dispatch
requires a running broker.
"""

import pytest
from rufus.models import StepContext
from pydantic import BaseModel


class _State(BaseModel):
    value: int = 0


class BaseExecutionCompliance:
    """
    Inherit and implement the ``provider`` fixture in subclasses.
    The fixture must return an ExecutionProvider.
    """

    def test_execute_sync_step_function_returns_dict(self, provider):
        def my_step(state, context, **kwargs):
            return {"done": True}

        ctx = StepContext(workflow_id="wf-1", step_name="S1")
        result = provider.execute_sync_step_function(my_step, _State(), ctx)
        assert isinstance(result, dict)
        assert result.get("done") is True

    def test_execute_sync_step_function_none_result(self, provider):
        """Steps that return None should not crash the caller."""
        def noop_step(state, context, **kwargs):
            return None

        ctx = StepContext(workflow_id="wf-1", step_name="S1")
        result = provider.execute_sync_step_function(noop_step, _State(), ctx)
        # SyncExecutor returns None for None-returning steps — callers must handle
        assert result is None or isinstance(result, dict)
