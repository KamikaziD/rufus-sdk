"""
Tests for the HUMAN_IN_LOOP step type.

Verifies that:
1. HUMAN_IN_LOOP can be loaded from YAML config without error.
2. First call with no user_input auto-pauses (WAITING_HUMAN, current_step unchanged).
3. Resume calls the step function with user_input and advances the step.
4. input_schema validates user_input on resume; invalid input raises ValueError.
5. HUMAN_IN_LOOP without a function merges user_input directly into state.
6. WorkflowJumpDirective raised inside the func routes to the correct step.
7. Legacy 2-step pattern (generic WorkflowStep raising WorkflowPauseDirective) still increments
   current_step on resume (backward compatibility).
"""
import pytest
from unittest.mock import AsyncMock
from pydantic import BaseModel
from typing import Optional

from ruvon.workflow import Workflow
from ruvon.models import (
    WorkflowStep, HumanWorkflowStep, StepContext,
    WorkflowPauseDirective, WorkflowJumpDirective,
)
from ruvon.builder import WorkflowBuilder
from ruvon.implementations.execution.sync import SyncExecutor
from ruvon.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from ruvon.implementations.templating.jinja2 import Jinja2TemplateEngine


# ---------------------------------------------------------------------------
# State model
# ---------------------------------------------------------------------------

class ApprovalState(BaseModel):
    order_id: str = "ORD-001"
    approved: Optional[bool] = None
    approved_by: Optional[str] = None
    customer_name: Optional[str] = None
    rejection_reason: Optional[str] = None


class ApprovalInput(BaseModel):
    approved: bool
    reviewer: str


# ---------------------------------------------------------------------------
# Module-level step functions (must be at module level for dotted-path imports)
# ---------------------------------------------------------------------------

def approval_step(state: ApprovalState, context: StepContext, **user_input) -> dict:
    """Process approval decision."""
    return {
        "approved": user_input.get("approved"),
        "approved_by": user_input.get("reviewer"),
    }


def decision_routing_step(state: ApprovalState, context: StepContext, **user_input) -> dict:
    """Route based on approval decision."""
    if not user_input.get("approved"):
        raise WorkflowJumpDirective("Rejected_Step")
    return {"approved": True, "approved_by": user_input.get("reviewer")}


def terminal_step(state: ApprovalState, context: StepContext, **_) -> dict:
    return {"finished": True}


def legacy_pause_step(state: ApprovalState, context: StepContext, **_) -> dict:
    """Old-style HITL: raises WorkflowPauseDirective."""
    raise WorkflowPauseDirective(result={"awaiting": True})


def legacy_process_step(state: ApprovalState, context: StepContext, **user_input) -> dict:
    """Old-style HITL: receives user_input on resume."""
    return {"approved": user_input.get("approved")}


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


def _make_workflow(steps, state=None, persistence=None, observer=None):
    """Build a minimal Workflow instance for testing."""
    if persistence is None:
        p = AsyncMock()
        p.save_workflow = AsyncMock()
        p.log_execution = AsyncMock()
        persistence = p
    if observer is None:
        observer = AsyncMock()

    return Workflow(
        workflow_steps=steps,
        initial_state_model=state or ApprovalState(),
        workflow_type="ApprovalWorkflow",
        persistence_provider=persistence,
        execution_provider=SyncExecutor(),
        workflow_builder=AsyncMock(),
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=observer,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_hitl_yaml_loads_without_error():
    """WorkflowBuilder._build_steps_from_config with HUMAN_IN_LOOP returns HumanWorkflowStep."""
    steps = WorkflowBuilder._build_steps_from_config([
        {"name": "Await_Approval", "type": "HUMAN_IN_LOOP"}
    ])
    assert len(steps) == 1
    assert isinstance(steps[0], HumanWorkflowStep), (
        f"Expected HumanWorkflowStep, got {type(steps[0])}"
    )
    assert steps[0].name == "Await_Approval"
    assert steps[0].func is None  # func is optional


@pytest.mark.asyncio
async def test_hitl_auto_pause_on_first_call(mock_persistence, mock_observer):
    """Empty user_input on a HumanWorkflowStep triggers auto-pause: WAITING_HUMAN, current_step unchanged."""
    hitl_step = HumanWorkflowStep(name="Await_Approval", func=approval_step)
    sentinel = WorkflowStep(name="Done", func=terminal_step)

    wf = _make_workflow([hitl_step, sentinel], persistence=mock_persistence, observer=mock_observer)
    wf.status = "ACTIVE"

    with pytest.raises(WorkflowPauseDirective):
        await wf.next_step(user_input={})

    assert wf.status == "WAITING_HUMAN", f"Expected WAITING_HUMAN, got {wf.status}"
    assert wf.current_step == 0, f"current_step should stay at 0, got {wf.current_step}"
    mock_persistence.save_workflow.assert_called()


@pytest.mark.asyncio
async def test_hitl_resume_calls_func_with_user_input(mock_persistence, mock_observer):
    """Resume calls the step function with provided user_input and advances to the next step."""
    hitl_step = HumanWorkflowStep(name="Await_Approval", func=approval_step)
    sentinel = WorkflowStep(name="Done", func=terminal_step)

    wf = _make_workflow([hitl_step, sentinel], persistence=mock_persistence, observer=mock_observer)
    wf.status = "WAITING_HUMAN"

    result, next_step_name = await wf.next_step(user_input={"approved": True, "reviewer": "mgr@co.com"})

    assert wf.status == "ACTIVE", f"Expected ACTIVE after resume, got {wf.status}"
    assert wf.current_step == 1, f"Expected current_step=1 after advance, got {wf.current_step}"
    assert wf.state.approved is True
    assert wf.state.approved_by == "mgr@co.com"
    assert next_step_name == "Done"


@pytest.mark.asyncio
async def test_hitl_input_schema_validates_user_input(mock_persistence, mock_observer):
    """Invalid user_input raises ValueError when input_schema is set."""
    hitl_step = HumanWorkflowStep(
        name="Await_Approval",
        func=approval_step,
        input_schema=ApprovalInput,
    )
    sentinel = WorkflowStep(name="Done", func=terminal_step)

    wf = _make_workflow([hitl_step, sentinel], persistence=mock_persistence, observer=mock_observer)
    wf.status = "WAITING_HUMAN"

    # Missing required field "approved" and "reviewer"
    with pytest.raises(ValueError, match="Invalid input"):
        await wf.next_step(user_input={"wrong_field": "oops"})


@pytest.mark.asyncio
async def test_hitl_no_func_merges_user_input_into_state(mock_persistence, mock_observer):
    """HumanWorkflowStep without func merges user_input directly into workflow state."""
    hitl_step = HumanWorkflowStep(name="Collect_Info")  # No func
    sentinel = WorkflowStep(name="Done", func=terminal_step)

    wf = _make_workflow([hitl_step, sentinel], persistence=mock_persistence, observer=mock_observer)
    wf.status = "WAITING_HUMAN"

    await wf.next_step(user_input={"customer_name": "Alice", "approved": True})

    assert wf.state.customer_name == "Alice"
    assert wf.state.approved is True
    assert wf.current_step == 1


@pytest.mark.asyncio
async def test_hitl_decision_routing_via_jump_directive(mock_persistence, mock_observer):
    """WorkflowJumpDirective raised inside the HITL func routes to the correct step."""
    hitl_step = HumanWorkflowStep(name="Await_Approval", func=decision_routing_step)
    approved_step = WorkflowStep(name="Approved_Step", func=terminal_step)
    rejected_step = WorkflowStep(name="Rejected_Step", func=terminal_step)

    wf = _make_workflow(
        [hitl_step, approved_step, rejected_step],
        persistence=mock_persistence,
        observer=mock_observer,
    )
    wf.status = "WAITING_HUMAN"

    result, next_step_name = await wf.next_step(user_input={"approved": False, "reviewer": "mgr@co.com"})

    assert next_step_name == "Rejected_Step", (
        f"Expected jump to Rejected_Step, got {next_step_name}"
    )
    assert wf.current_step == 2  # Index of Rejected_Step


@pytest.mark.asyncio
async def test_hitl_backward_compat_legacy_pattern(mock_persistence, mock_observer):
    """Old generic WorkflowStep raising WorkflowPauseDirective still increments current_step on resume.

    Note: the legacy executor (execute_sync_step_function) does NOT forward user_input to
    the step function — that is pre-existing behaviour, unchanged by this fix. The key
    assertion is that the workflow advances past the pause step on resume.
    """
    pause_step = WorkflowStep(name="Pause_Step", func=legacy_pause_step)
    process_step = WorkflowStep(name="Process_Step", func=legacy_process_step)

    wf = _make_workflow([pause_step, process_step], persistence=mock_persistence, observer=mock_observer)
    wf.status = "ACTIVE"

    # First call: step function raises WorkflowPauseDirective
    with pytest.raises(WorkflowPauseDirective):
        await wf.next_step(user_input={})

    assert wf.status == "WAITING_HUMAN"
    assert wf.current_step == 0, "current_step should stay at pause step while WAITING_HUMAN"

    # Resume: legacy path increments past pause step, then executes process_step
    result, next_step_name = await wf.next_step(user_input={"approved": True})

    # Workflow has advanced past process_step (now at end — both steps consumed)
    assert wf.current_step == 2, f"Expected current_step=2 (end), got {wf.current_step}"
    assert wf.status == "COMPLETED"
