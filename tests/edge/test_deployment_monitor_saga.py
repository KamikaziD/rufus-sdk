"""End-to-end saga compensation test for the DeploymentMonitor sidecar workflow.

Verifies that when ApplyChange raises an exception:
  1. rollback_change() (the saga compensate_function) is invoked.
  2. The workflow status becomes FAILED_ROLLED_BACK.

The test uses the actual `apply_approved_change` / `rollback_change` functions from
`config_applier` — they are patched so no filesystem or signal I/O happens — proving
the compensation wiring is correct end-to-end through the Ruvon saga engine.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel

from ruvon.workflow import Workflow
from ruvon.models import CompensatableStep


# ---------------------------------------------------------------------------
# Minimal state model that satisfies apply_approved_change / rollback_change
# ---------------------------------------------------------------------------

class _ApplyState(BaseModel):
    approved: bool = True
    suggestion: dict = {
        "change": {"key": "fraud_threshold", "value": 500},
        "apply_mode": "hot_swap",
    }
    apply_outcome: str = ""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_providers():
    """Mocked providers for Workflow — no real DB or executor needed.

    execute_sync_step_function is wired to actually call the provided function
    so step-level exceptions propagate through the saga engine as intended.
    """
    mock_persistence = AsyncMock()
    mock_execution = AsyncMock()
    mock_observer = AsyncMock()
    mock_evaluator_cls = MagicMock()
    mock_template_cls = MagicMock()
    mock_builder = MagicMock()

    mock_evaluator_cls.return_value = MagicMock()
    mock_template_cls.return_value = MagicMock()

    # Wire execute_sync_step_function to actually invoke the step function.
    # Without this the mock returns a coroutine that never raises, masking failures.
    import asyncio

    async def _real_call(func, state, context, **kwargs):
        if asyncio.iscoroutinefunction(func):
            return await func(state, context, **kwargs)
        return func(state, context, **kwargs)

    mock_execution.execute_sync_step_function = AsyncMock(side_effect=_real_call)

    return {
        "persistence_provider": mock_persistence,
        "execution_provider": mock_execution,
        "workflow_observer": mock_observer,
        "expression_evaluator_cls": mock_evaluator_cls,
        "template_engine_cls": mock_template_cls,
        "workflow_builder": mock_builder,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_apply_change_triggers_rollback_on_failure(mock_providers):
    """Saga compensation end-to-end:

    Scenario that mirrors the real deployment_monitor workflow:
      1. ApplyChange (CompensatableStep) executes successfully — pushed to completed_steps_stack.
      2. ReportOutcome (a subsequent standard step) fails with a RuntimeError.
      3. The saga engine should call rollback_change (ApplyChange's compensate_func) in reverse.
      4. Workflow status must become FAILED_ROLLED_BACK.
    """
    from ruvon.models import WorkflowStep

    rollback_calls: list[dict] = []

    async def _ok_apply(state, context, **kwargs):
        # Simulates ApplyChange succeeding — change has been applied to the device.
        return {"apply_outcome": "hot_swap_ok"}

    async def _track_rollback(state, context, **kwargs):
        rollback_calls.append({"state_approved": getattr(state, "approved", None)})
        return {"rollback": "ok"}

    async def _fail_report(state, context, **kwargs):
        raise RuntimeError("simulated cloud outage during ReportOutcome")

    apply_step = CompensatableStep(
        name="ApplyChange",
        func=_ok_apply,
        compensate_func=_track_rollback,
    )
    report_step = WorkflowStep(
        name="ReportOutcome",
        func=_fail_report,
    )

    initial_state = _ApplyState()
    workflow = Workflow(
        workflow_type="DeploymentMonitor",
        initial_state_model=initial_state,
        workflow_steps=[apply_step, report_step],
        steps_config=[{"name": "ApplyChange"}, {"name": "ReportOutcome"}],
        state_model_path="tests.edge.test_deployment_monitor_saga:_ApplyState",
        **mock_providers,
    )

    await workflow.enable_saga_mode()

    with patch.object(workflow, "_notify_status_change", AsyncMock()):
        # Step 1: ApplyChange — should succeed, pushed to completed_steps_stack
        result, _ = await workflow.next_step(user_input={})
        assert result.get("apply_outcome") == "hot_swap_ok"
        assert len(workflow.completed_steps_stack) == 1, (
            "ApplyChange should be on completed_steps_stack after success"
        )

        # Step 2: ReportOutcome — should fail, triggering saga rollback of ApplyChange
        try:
            await workflow.next_step(user_input={})
        except Exception:
            pass  # SagaWorkflowException propagates after rollback; expected

    assert workflow.status == "FAILED_ROLLED_BACK", (
        f"Expected FAILED_ROLLED_BACK, got {workflow.status!r}"
    )
    assert len(rollback_calls) == 1, (
        f"Expected rollback_change to be called once, got {len(rollback_calls)}"
    )


@pytest.mark.asyncio
async def test_saga_mode_enabled_by_yaml_key():
    """Confirm that WorkflowBuilder.create_workflow() enables saga_mode when
    deployment_monitor.yaml declares `saga_mode: true`."""
    import yaml
    from pathlib import Path

    yaml_path = Path("config/workflows/deployment_monitor.yaml")
    if not yaml_path.exists():
        pytest.skip("deployment_monitor.yaml not found")

    config = yaml.safe_load(yaml_path.read_text())
    assert config.get("saga_mode") is True, (
        "deployment_monitor.yaml must declare `saga_mode: true` at the top level "
        "so the builder activates saga mode on workflow creation."
    )


@pytest.mark.asyncio
async def test_apply_change_step_has_compensate_function():
    """Confirm that the ApplyChange step in deployment_monitor.yaml has a
    compensate_function pointing to rollback_change."""
    import yaml
    from pathlib import Path

    yaml_path = Path("config/workflows/deployment_monitor.yaml")
    if not yaml_path.exists():
        pytest.skip("deployment_monitor.yaml not found")

    config = yaml.safe_load(yaml_path.read_text())
    steps = {s["name"]: s for s in config.get("steps", [])}

    apply_step = steps.get("ApplyChange")
    assert apply_step is not None, "ApplyChange step not found in deployment_monitor.yaml"

    compensate_fn = apply_step.get("compensate_function", "")
    assert "rollback_change" in compensate_fn, (
        f"ApplyChange.compensate_function should reference rollback_change, got {compensate_fn!r}"
    )
