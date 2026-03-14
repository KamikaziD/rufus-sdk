"""
Base compliance test class for WorkflowObserver implementations.

Verifies that all required methods exist, accept the correct signatures,
and do not raise exceptions (for no-op implementations).
"""

import pytest
from unittest.mock import MagicMock
from pydantic import BaseModel


class _DummyState(BaseModel):
    value: int = 0


class BaseObserverCompliance:
    """
    Inherit and implement the ``observer`` fixture in subclasses.
    The fixture must yield an initialized WorkflowObserver.
    """

    @pytest.mark.asyncio
    async def test_on_workflow_started(self, observer):
        await observer.on_workflow_started("wf-1", "TestWF", _DummyState())

    @pytest.mark.asyncio
    async def test_on_step_executed_without_duration(self, observer):
        await observer.on_step_executed(
            "wf-1", "StepA", 0, "COMPLETED", {"result": 1}, _DummyState()
        )

    @pytest.mark.asyncio
    async def test_on_step_executed_with_duration(self, observer):
        await observer.on_step_executed(
            "wf-1", "StepA", 0, "COMPLETED", None, _DummyState(), duration_ms=12.5
        )

    @pytest.mark.asyncio
    async def test_on_workflow_completed(self, observer):
        await observer.on_workflow_completed("wf-1", "TestWF", _DummyState())

    @pytest.mark.asyncio
    async def test_on_workflow_failed(self, observer):
        await observer.on_workflow_failed("wf-1", "TestWF", "some error", _DummyState())

    @pytest.mark.asyncio
    async def test_on_workflow_status_changed(self, observer):
        await observer.on_workflow_status_changed("wf-1", "ACTIVE", "COMPLETED", "StepA")

    @pytest.mark.asyncio
    async def test_on_workflow_rolled_back(self, observer):
        await observer.on_workflow_rolled_back("wf-1", "TestWF", "rolled back", _DummyState(), [])

    @pytest.mark.asyncio
    async def test_on_step_failed(self, observer):
        await observer.on_step_failed("wf-1", "StepA", 0, "step error", _DummyState())

    @pytest.mark.asyncio
    async def test_on_workflow_paused(self, observer):
        await observer.on_workflow_paused("wf-1", "StepA", "HUMAN_IN_LOOP")

    @pytest.mark.asyncio
    async def test_on_workflow_resumed(self, observer):
        await observer.on_workflow_resumed("wf-1", "StepA", {"approved": True})

    @pytest.mark.asyncio
    async def test_on_compensation_started(self, observer):
        await observer.on_compensation_started("wf-1", "StepA", 0)

    @pytest.mark.asyncio
    async def test_on_compensation_completed_success(self, observer):
        await observer.on_compensation_completed("wf-1", "StepA", success=True)

    @pytest.mark.asyncio
    async def test_on_compensation_completed_failure(self, observer):
        await observer.on_compensation_completed("wf-1", "StepA", success=False, error="db down")

    @pytest.mark.asyncio
    async def test_on_child_workflow_started(self, observer):
        await observer.on_child_workflow_started("parent-1", "child-1", "ChildWF")
