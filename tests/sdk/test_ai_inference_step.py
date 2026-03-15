"""Tests for AI_INFERENCE step execution in workflow.py."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel

from rufus.models import AIInferenceWorkflowStep, AIInferenceConfig, WorkflowStep, StepContext
from rufus.workflow import Workflow


class SimpleState(BaseModel):
    sensor_data: str = "temperature:42.5"
    result: dict = {}
    analysis_result: dict = {}


def _make_workflow(inference_provider=None):
    """Create a minimal Workflow instance for testing AI_INFERENCE dispatch."""
    from rufus.implementations.persistence.memory import InMemoryPersistence
    from rufus.implementations.execution.sync import SyncExecutor
    from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
    from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
    from rufus.builder import WorkflowBuilder

    state = SimpleState()
    step = AIInferenceWorkflowStep(
        name="Analyse",
        ai_config=AIInferenceConfig(
            model_name="test_model",
            model_path="models/test.onnx",
            runtime="onnx",
            input_source="state.sensor_data",
            output_key="analysis_result",
            fallback_on_error="skip",
        ),
        automate_next=False,
    )
    persistence = InMemoryPersistence()
    executor = SyncExecutor()
    observer = MagicMock()
    observer.on_workflow_started = AsyncMock()
    observer.on_step_executed = AsyncMock()
    observer.on_workflow_completed = AsyncMock()
    observer.on_workflow_failed = AsyncMock()
    observer.on_workflow_status_changed = AsyncMock()
    observer.on_workflow_rolled_back = AsyncMock()
    observer.on_step_failed = AsyncMock()
    observer.initialize = AsyncMock()
    observer.close = AsyncMock()
    builder = WorkflowBuilder({}, SimpleExpressionEvaluator, Jinja2TemplateEngine)

    return Workflow(
        workflow_type="TestInference",
        workflow_steps=[step],
        initial_state_model=state,
        state_model_path="tests.sdk.test_ai_inference_step.SimpleState",
        persistence_provider=persistence,
        execution_provider=executor,
        workflow_builder=builder,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=observer,
        inference_provider=inference_provider,
    )


@pytest.mark.asyncio
async def test_ai_inference_no_provider_fallback_skip():
    """When no inference_provider and fallback_on_error='skip', step returns {} and workflow completes."""
    import asyncio
    wf = _make_workflow(inference_provider=None)
    await wf.persistence.initialize()
    await wf.execution.initialize(None)
    await wf.persistence.save_workflow(wf.id, wf.to_dict())

    result, _ = await wf.next_step(user_input={})
    # fallback_on_error='skip' — workflow should complete without error
    assert wf.status == "COMPLETED"


@pytest.mark.asyncio
async def test_ai_inference_no_provider_fallback_fail():
    """When no inference_provider and fallback_on_error='fail', step raises RuntimeError."""
    from rufus.implementations.persistence.memory import InMemoryPersistence
    from rufus.implementations.execution.sync import SyncExecutor
    from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
    from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
    from rufus.builder import WorkflowBuilder
    from unittest.mock import AsyncMock, MagicMock

    state = SimpleState()
    step = AIInferenceWorkflowStep(
        name="Analyse",
        ai_config=AIInferenceConfig(
            model_name="test_model",
            runtime="onnx",
            input_source="state.sensor_data",
            output_key="result",
            fallback_on_error="fail",
        ),
        automate_next=False,
    )
    persistence = InMemoryPersistence()
    executor = SyncExecutor()
    observer = MagicMock()
    for m in ["on_workflow_started", "on_step_executed", "on_workflow_completed",
              "on_workflow_failed", "on_workflow_status_changed", "on_workflow_rolled_back",
              "on_step_failed", "initialize", "close"]:
        setattr(observer, m, AsyncMock())
    builder = WorkflowBuilder({}, SimpleExpressionEvaluator, Jinja2TemplateEngine)

    wf = Workflow(
        workflow_type="TestInferenceFail",
        workflow_steps=[step],
        initial_state_model=state,
        state_model_path="tests.sdk.test_ai_inference_step.SimpleState",
        persistence_provider=persistence,
        execution_provider=executor,
        workflow_builder=builder,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=observer,
        inference_provider=None,
    )
    await persistence.initialize()
    await executor.initialize(None)
    await persistence.save_workflow(wf.id, wf.to_dict())

    from rufus.models import WorkflowFailedException
    with pytest.raises(WorkflowFailedException):
        await wf.next_step(user_input={})
    assert wf.status == "FAILED"


@pytest.mark.asyncio
async def test_ai_inference_with_provider():
    """With a mock provider, result is merged into workflow state."""
    mock_provider = MagicMock()
    mock_provider.is_model_loaded = MagicMock(return_value=True)
    mock_provider.load_model = AsyncMock()

    # run_inference returns an object with .outputs
    mock_result = MagicMock()
    mock_result.outputs = {"label": "CRITICAL", "score": 0.97}
    mock_provider.run_inference = AsyncMock(return_value=mock_result)

    wf = _make_workflow(inference_provider=mock_provider)
    await wf.persistence.initialize()
    await wf.execution.initialize(None)
    await wf.persistence.save_workflow(wf.id, wf.to_dict())

    await wf.next_step(user_input={})

    assert wf.status == "COMPLETED"
    assert wf.state.result == {}  # result key is "analysis_result", not "result"
    # The analysis_result is set dynamically — check via model_dump
    state_dict = wf.state.model_dump()
    assert "analysis_result" in state_dict
    assert state_dict["analysis_result"] == {"label": "CRITICAL", "score": 0.97}


@pytest.mark.asyncio
async def test_ai_inference_default_fallback():
    """fallback_on_error='default' returns the default_result when no provider."""
    from rufus.implementations.persistence.memory import InMemoryPersistence
    from rufus.implementations.execution.sync import SyncExecutor
    from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
    from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
    from rufus.builder import WorkflowBuilder
    from pydantic import BaseModel

    class StateWithInference(BaseModel):
        sensor_data: str = "test"
        analysis_result: dict = {}

    step = AIInferenceWorkflowStep(
        name="Analyse",
        ai_config=AIInferenceConfig(
            model_name="test_model",
            runtime="onnx",
            input_source="state.sensor_data",
            output_key="analysis_result",
            fallback_on_error="default",
            default_result={"label": "UNKNOWN", "score": 0.0},
        ),
        automate_next=False,
    )
    persistence = InMemoryPersistence()
    executor = SyncExecutor()
    observer = MagicMock()
    for m in ["on_workflow_started", "on_step_executed", "on_workflow_completed",
              "on_workflow_failed", "on_workflow_status_changed", "on_workflow_rolled_back",
              "on_step_failed", "initialize", "close"]:
        setattr(observer, m, AsyncMock())
    builder = WorkflowBuilder({}, SimpleExpressionEvaluator, Jinja2TemplateEngine)
    state = StateWithInference()

    wf = Workflow(
        workflow_type="TestDefault",
        workflow_steps=[step],
        initial_state_model=state,
        state_model_path="tests.sdk.test_ai_inference_step.StateWithInference",
        persistence_provider=persistence,
        execution_provider=executor,
        workflow_builder=builder,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=observer,
        inference_provider=None,
    )
    await persistence.initialize()
    await executor.initialize(None)
    await persistence.save_workflow(wf.id, wf.to_dict())

    await wf.next_step(user_input={})
    assert wf.status == "COMPLETED"
    assert wf.state.analysis_result == {"label": "UNKNOWN", "score": 0.0}
