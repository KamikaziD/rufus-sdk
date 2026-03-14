"""
Observer ordering and signature tests.

Verifies that:
- on_workflow_started fires before on_step_executed (enforced by workflow.py call order)
- on_step_executed accepts duration_ms kwarg
- LoggingObserver and NoopWorkflowObserver implement all v1.0 methods
"""

import pytest
from pydantic import BaseModel

from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.observability.noop import NoopWorkflowObserver


class _State(BaseModel):
    x: int = 0


@pytest.fixture
def logging_observer():
    return LoggingObserver()


@pytest.fixture
def noop_observer():
    return NoopWorkflowObserver()


class TestObserverOrdering:
    """
    Ordering is enforced by workflow.py — here we verify the interface is consistent.
    """

    @pytest.mark.asyncio
    async def test_logging_observer_all_methods(self, logging_observer):
        obs = logging_observer
        s = _State()
        await obs.on_workflow_started("wf-1", "T", s)
        await obs.on_step_executed("wf-1", "S", 0, "COMPLETED", None, s, duration_ms=10.0)
        await obs.on_workflow_completed("wf-1", "T", s)
        await obs.on_workflow_failed("wf-1", "T", "err", s)
        await obs.on_workflow_status_changed("wf-1", "ACTIVE", "COMPLETED", "S")
        await obs.on_workflow_rolled_back("wf-1", "T", "msg", s, [])
        await obs.on_step_failed("wf-1", "S", 0, "err", s)
        await obs.on_workflow_paused("wf-1", "S", "reason")
        await obs.on_workflow_resumed("wf-1", "S", {"approved": True})
        await obs.on_compensation_started("wf-1", "S", 0)
        await obs.on_compensation_completed("wf-1", "S", success=True)
        await obs.on_compensation_completed("wf-1", "S", success=False, error="oops")
        await obs.on_child_workflow_started("p-1", "c-1", "ChildWF")

    @pytest.mark.asyncio
    async def test_noop_observer_all_methods(self, noop_observer):
        obs = noop_observer
        s = _State()
        await obs.on_workflow_started("wf-1", "T", s)
        await obs.on_step_executed("wf-1", "S", 0, "COMPLETED", None, s)
        await obs.on_step_executed("wf-1", "S", 0, "COMPLETED", None, s, duration_ms=5.0)
        await obs.on_workflow_completed("wf-1", "T", s)
        await obs.on_workflow_failed("wf-1", "T", "err", s)
        await obs.on_workflow_status_changed("wf-1", "ACTIVE", "FAILED", "S")
        await obs.on_workflow_rolled_back("wf-1", "T", "msg", s, [])
        await obs.on_step_failed("wf-1", "S", 0, "err", s)
        await obs.on_workflow_paused("wf-1", "S", "reason")
        await obs.on_workflow_resumed("wf-1", "S", None)
        await obs.on_compensation_started("wf-1", "S", 0)
        await obs.on_compensation_completed("wf-1", "S", success=True)
        await obs.on_child_workflow_started("p", "c", "T")

    def test_duration_ms_defaults_to_none(self):
        """on_step_executed duration_ms is optional — must not be required."""
        import inspect
        sig = inspect.signature(LoggingObserver.on_step_executed)
        params = sig.parameters
        assert "duration_ms" in params
        assert params["duration_ms"].default is None
