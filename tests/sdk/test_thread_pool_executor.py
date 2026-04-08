"""
Tests for ThreadPoolExecutorProvider.

Verifies:
1. execute_sync_step_function calls the function with correct args.
2. dispatch_async_task raises RuntimeError when not initialized.
3. dispatch_parallel_tasks raises RuntimeError when not initialized.
4. register_scheduled_workflow is callable without raising (logs-only).
5. Multiple parallel tasks complete correctly via SyncExecutor
   (ThreadPoolExecutorProvider's full integration requires a DB; we verify
   the simpler SyncExecutor handles concurrent results for compatibility).
"""
import asyncio
import concurrent.futures
import pytest
from unittest.mock import MagicMock, AsyncMock
from pydantic import BaseModel

from ruvon.implementations.execution.thread_pool import ThreadPoolExecutorProvider
from ruvon.implementations.execution.sync import SyncExecutor
from ruvon.models import (
    StepContext, ParallelWorkflowStep, ParallelExecutionTask,
    WorkflowStep,
)
from ruvon.workflow import Workflow
from ruvon.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from ruvon.implementations.templating.jinja2 import Jinja2TemplateEngine


# ---------------------------------------------------------------------------
# State model
# ---------------------------------------------------------------------------

class SimpleState(BaseModel):
    value: int = 0
    a_done: bool = False
    b_done: bool = False


# ---------------------------------------------------------------------------
# Step functions
# ---------------------------------------------------------------------------

def add_one(state: SimpleState, context: StepContext, **_) -> dict:
    return {"value": state.value + 1}


def multiply_two(state: SimpleState, context: StepContext, **_) -> dict:
    return {"value": state.value * 2}


# Module-level functions for dotted-path import in parallel task tests
def task_a(state: dict, context: StepContext, **_) -> dict:
    return {"a_done": True}


def task_b(state: dict, context: StepContext, **_) -> dict:
    return {"b_done": True}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def provider():
    p = ThreadPoolExecutorProvider(max_workers=4)
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_execute_sync_step_function_calls_function(provider):
    """execute_sync_step_function passes (state, context) to the function."""
    state = SimpleState(value=5)
    context = StepContext(workflow_id="wf-1", step_name="AddOne")
    result = provider.execute_sync_step_function(add_one, state, context)
    assert result == {"value": 6}


def test_execute_sync_step_function_multiply(provider):
    """execute_sync_step_function works with a multiply function."""
    state = SimpleState(value=7)
    context = StepContext(workflow_id="wf-1", step_name="Multiply")
    result = provider.execute_sync_step_function(multiply_two, state, context)
    assert result == {"value": 14}


def test_dispatch_async_task_raises_when_not_initialized(provider):
    """dispatch_async_task raises RuntimeError if initialize() was never called."""
    with pytest.raises(RuntimeError, match="not initialized"):
        provider.dispatch_async_task(
            func_path="tests.sdk.test_thread_pool_executor.add_one",
            state_data={"value": 1},
            workflow_id="wf-1",
            current_step_index=0,
            data_region=None,
            merge_strategy="shallow",
            merge_conflict_behavior="prefer_new",
        )


def test_dispatch_parallel_tasks_raises_when_not_initialized(provider):
    """dispatch_parallel_tasks raises RuntimeError if not initialized."""
    task = ParallelExecutionTask(
        name="task1",
        func_path="tests.sdk.test_thread_pool_executor.add_one",
    )
    with pytest.raises(RuntimeError, match="not initialized"):
        provider.dispatch_parallel_tasks(
            tasks=[task],
            state_data={"value": 0},
            workflow_id="wf-1",
            current_step_index=0,
            merge_function_path=None,
            data_region=None,
            merge_strategy="shallow",
            merge_conflict_behavior="prefer_new",
        )


def test_register_scheduled_workflow_does_not_raise(provider, capsys):
    """register_scheduled_workflow is callable and logs without raising."""
    provider.register_scheduled_workflow(
        schedule_name="test_schedule",
        workflow_type="TestWorkflow",
        cron_expression="0 * * * *",
        initial_data={"key": "value"},
    )
    captured = capsys.readouterr()
    assert "test_schedule" in captured.out


@pytest.mark.asyncio
async def test_parallel_tasks_via_sync_executor_all_complete():
    """
    SyncExecutor (portable, no thread pool) executes all parallel tasks
    and merges results correctly.
    """
    import concurrent.futures as cf
    executor = SyncExecutor()
    executor._thread_pool_executor = cf.ThreadPoolExecutor(max_workers=2)

    mock_persistence = AsyncMock()
    mock_persistence.save_workflow = AsyncMock()
    mock_persistence.log_execution = AsyncMock()
    mock_observer = AsyncMock()

    step = ParallelWorkflowStep(
        name="ParallelCheck",
        tasks=[
            ParallelExecutionTask(
                name="TaskA",
                func_path="tests.sdk.test_thread_pool_executor.task_a"
            ),
            ParallelExecutionTask(
                name="TaskB",
                func_path="tests.sdk.test_thread_pool_executor.task_b"
            ),
        ],
    )
    sentinel = WorkflowStep(name="Done", func=lambda s, c, **_: {})

    wf = Workflow(
        workflow_steps=[step, sentinel],
        initial_state_model=SimpleState(value=0),
        workflow_type="TestWorkflow",
        persistence_provider=mock_persistence,
        execution_provider=executor,
        workflow_builder=MagicMock(),
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=mock_observer,
    )
    wf.status = "ACTIVE"
    executor._loop = asyncio.get_event_loop()

    await wf.next_step(user_input={})

    # Both tasks ran: their results were merged into workflow state
    state_dict = wf.state.model_dump()
    assert state_dict.get("a_done") is True, f"task_a result should be in state: {state_dict}"
    assert state_dict.get("b_done") is True, f"task_b result should be in state: {state_dict}"
