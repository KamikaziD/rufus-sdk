"""
Tests for FireAndForget step type.

Verifies that:
1. FireAndForget dispatches an independent workflow via dispatch_independent_workflow.
2. The parent workflow advances immediately without waiting for the child.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel
from typing import Optional, List

from ruvon.workflow import Workflow
from ruvon.models import (
    WorkflowStep, FireAndForgetWorkflowStep, StepContext,
)
from ruvon.implementations.execution.sync import SyncExecutor
from ruvon.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from ruvon.implementations.templating.jinja2 import Jinja2TemplateEngine


# ---------------------------------------------------------------------------
# State model
# ---------------------------------------------------------------------------

class FaFState(BaseModel):
    amount: float = 99.0
    recipient: str = "user_42"
    spawned_workflows: Optional[List[dict]] = None


def terminal_step(state: FaFState, context: StepContext, **_) -> dict:
    return {"finished": True}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_persistence():
    p = AsyncMock()
    p.save_workflow = AsyncMock()
    p.log_execution = AsyncMock()
    return p


@pytest.fixture
def mock_observer():
    return AsyncMock()


def _make_child_workflow():
    """Minimal mock that looks like a Workflow to workflow.py."""
    child = MagicMock()
    child.id = "child-workflow-uuid"
    child.status = "ACTIVE"
    child.parent_execution_id = None
    child.data_region = None
    child.metadata = {}
    return child


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fire_and_forget_calls_dispatch_independent_workflow(mock_persistence, mock_observer):
    """dispatch_independent_workflow is called with the spawned workflow's ID."""
    child_wf = _make_child_workflow()

    mock_builder = AsyncMock()
    mock_builder.create_workflow = AsyncMock(return_value=child_wf)

    dispatch_called_with = []

    class TrackingExecutor(SyncExecutor):
        async def dispatch_independent_workflow(self, workflow_id):
            dispatch_called_with.append(workflow_id)

    executor = TrackingExecutor()

    faf_step = FireAndForgetWorkflowStep(
        name="SendAuditLog",
        target_workflow_type="AuditLogWorkflow",
        initial_data_template={"amount": "{{ state.amount }}", "recipient": "{{ state.recipient }}"},
    )
    sentinel = WorkflowStep(
        name="Done",
        func=lambda state, context, **_: {},
    )

    wf = Workflow(
        workflow_steps=[faf_step, sentinel],
        initial_state_model=FaFState(),
        workflow_type="ParentWorkflow",
        persistence_provider=mock_persistence,
        execution_provider=executor,
        workflow_builder=mock_builder,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=mock_observer,
    )
    wf.status = "ACTIVE"

    await wf.next_step(user_input={})

    assert dispatch_called_with == [child_wf.id], (
        f"dispatch_independent_workflow should be called with the child ID, got {dispatch_called_with}"
    )


@pytest.mark.asyncio
async def test_fire_and_forget_does_not_block_next_step(mock_persistence, mock_observer):
    """Parent workflow advances past FireAndForget to the next step without blocking."""
    child_wf = _make_child_workflow()

    mock_builder = AsyncMock()
    mock_builder.create_workflow = AsyncMock(return_value=child_wf)

    class ImmediateExecutor(SyncExecutor):
        async def dispatch_independent_workflow(self, workflow_id):
            pass  # Non-blocking

    executor = ImmediateExecutor()

    steps_executed = []

    def sentinel_func(state, context, **_):
        steps_executed.append("Done")
        return {}

    faf_step = FireAndForgetWorkflowStep(
        name="FireLog",
        target_workflow_type="LogWorkflow",
        initial_data_template={},
    )
    sentinel = WorkflowStep(name="Done", func=sentinel_func)

    wf = Workflow(
        workflow_steps=[faf_step, sentinel],
        initial_state_model=FaFState(),
        workflow_type="ParentWorkflow",
        persistence_provider=mock_persistence,
        execution_provider=executor,
        workflow_builder=mock_builder,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=mock_observer,
    )
    wf.status = "ACTIVE"

    # First next_step executes FireAndForget
    await wf.next_step(user_input={})
    assert wf.current_step == 1, f"After FaF step, current_step should be 1 but is {wf.current_step}"
    assert wf.status == "ACTIVE", "Workflow should still be ACTIVE after FaF step"

    # Second next_step executes the sentinel
    await wf.next_step(user_input={})
    assert "Done" in steps_executed, "Sentinel step should have executed"


@pytest.mark.asyncio
async def test_fire_and_forget_template_renders_state_fields(mock_persistence, mock_observer):
    """initial_data_template is rendered with the current workflow state values."""
    received_initial_data = {}

    async def capture_create(workflow_type, initial_data, **kwargs):
        received_initial_data.update(initial_data)
        return _make_child_workflow()

    mock_builder = AsyncMock()
    mock_builder.create_workflow = AsyncMock(side_effect=capture_create)

    class SilentExecutor(SyncExecutor):
        async def dispatch_independent_workflow(self, workflow_id):
            pass

    executor = SilentExecutor()

    # Note: template context is state.model_dump() so keys are top-level (no "state." prefix)
    faf_step = FireAndForgetWorkflowStep(
        name="NotifyUser",
        target_workflow_type="NotificationWorkflow",
        initial_data_template={"to": "{{ recipient }}", "total": "{{ amount }}"},
    )

    wf = Workflow(
        workflow_steps=[faf_step],
        initial_state_model=FaFState(amount=250.0, recipient="alice"),
        workflow_type="ParentWorkflow",
        persistence_provider=mock_persistence,
        execution_provider=executor,
        workflow_builder=mock_builder,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=mock_observer,
    )
    wf.status = "ACTIVE"

    await wf.next_step(user_input={})

    assert received_initial_data.get("to") == "alice"
    assert received_initial_data.get("total") == "250.0"
