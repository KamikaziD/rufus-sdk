"""
Verification tests for:
  1. LOOP step (ITERATE mode)
  2. LOOP step (WHILE mode)
  3. LOOP max_iterations cap
  4. Dynamic PARALLEL fan-out (iterate_over + task_function)
  5. Static PARALLEL backward-compatibility (regression)

Fixtures are sync to avoid pytest-asyncio 0.21/pytest 9.x incompatibility
(see tests/conftest.py for details).
"""
import asyncio
import concurrent.futures
import pytest
from unittest.mock import AsyncMock, MagicMock
from pydantic import BaseModel
from typing import List

from ruvon.workflow import Workflow
from ruvon.models import (
    WorkflowStep, LoopStep, ParallelWorkflowStep, ParallelExecutionTask,
    StepContext, MergeStrategy, MergeConflictBehavior,
)
from ruvon.implementations.execution.sync import SyncExecutor
from ruvon.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from ruvon.implementations.templating.jinja2 import Jinja2TemplateEngine


# ---------------------------------------------------------------------------
# State models
# ---------------------------------------------------------------------------

class LoopState(BaseModel):
    items: List[str] = []
    collected: List[str] = []
    collected_indices: List[int] = []
    keep_monitoring: bool = True
    iteration_count: int = 0


class ParallelState(BaseModel):
    devices: List[str] = ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Step functions — importable by dotted string path
# ---------------------------------------------------------------------------

def iterate_body(state: LoopState, context: StepContext, **_) -> dict:
    """Body step for ITERATE tests — accumulates loop_item and loop_index."""
    return {
        "collected": list(state.collected) + [context.loop_item],
        "collected_indices": list(state.collected_indices) + [context.loop_index],
    }


def while_body(state: LoopState, context: StepContext, **_) -> dict:
    """Body step for WHILE test — increments counter and stops the loop."""
    return {
        "iteration_count": state.iteration_count + 1,
        "keep_monitoring": False,
    }


def noop_step(state, context: StepContext, **_) -> dict:
    """Terminal sentinel step — does nothing, just completes."""
    return {}


def parallel_task(state: dict, context: StepContext, device_id: str = "", **_) -> dict:
    """Per-item task for dynamic PARALLEL fan-out."""
    return {"pushed": device_id}


def static_task_a(state: dict, context: StepContext, **_) -> dict:
    return {"from_a": True}


def static_task_b(state: dict, context: StepContext, **_) -> dict:
    return {"from_b": True}


# ---------------------------------------------------------------------------
# Sync fixture helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def sync_executor():
    """SyncExecutor wired synchronously — no async initialize needed."""
    exec_ = SyncExecutor()
    exec_._thread_pool_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    return exec_


@pytest.fixture
def mock_persistence():
    p = AsyncMock()
    p.save_workflow = AsyncMock()
    p.log_execution = AsyncMock()
    return p


@pytest.fixture
def mock_observer():
    return AsyncMock()


def _make_workflow(steps, state, executor, persistence, observer):
    return Workflow(
        workflow_steps=steps,
        initial_state_model=state,
        workflow_type="TestWorkflow",
        persistence_provider=persistence,
        execution_provider=executor,
        workflow_builder=MagicMock(),
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=observer,
    )


def _import(dotted_path: str):
    from ruvon.builder import WorkflowBuilder
    return WorkflowBuilder._import_from_string(dotted_path)


def _noop():
    return WorkflowStep(name="Sentinel", func=_import("tests.sdk.test_loop_and_parallel.noop_step"))


# ---------------------------------------------------------------------------
# 1. LOOP ITERATE — body called N times with correct item and index
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_loop_iterate_calls_body_for_each_item(sync_executor, mock_persistence, mock_observer):
    """Body step is called once per item with correct loop_item and loop_index."""
    sync_executor._loop = asyncio.get_event_loop()
    state = LoopState(items=["x", "y", "z"])

    body = WorkflowStep(name="Collect", func=_import("tests.sdk.test_loop_and_parallel.iterate_body"))
    loop = LoopStep(
        name="Iterate_Items", mode="ITERATE", iterate_over="items",
        max_iterations=100, loop_body=[body], automate_next=False,
    )
    # Add sentinel so the loop isn't the last step — allows result inspection
    wf = _make_workflow([loop, _noop()], state, sync_executor, mock_persistence, mock_observer)
    result, next_step = await wf.next_step(user_input={})

    assert next_step == "Sentinel"
    assert result["loop_iterations"] == 3
    assert len(result["loop_results"]) == 3
    # Body merges each iteration into state — final state accumulates all items
    assert wf.state.collected == ["x", "y", "z"]
    assert wf.state.collected_indices == [0, 1, 2]


# ---------------------------------------------------------------------------
# 2. LOOP WHILE — exits after body sets condition to False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_loop_while_exits_when_condition_false(sync_executor, mock_persistence, mock_observer):
    """WHILE loop runs body once; body sets keep_monitoring=False, loop exits."""
    sync_executor._loop = asyncio.get_event_loop()
    state = LoopState(keep_monitoring=True)

    body = WorkflowStep(name="Poll", func=_import("tests.sdk.test_loop_and_parallel.while_body"))
    loop = LoopStep(
        name="Monitor", mode="WHILE", while_condition="keep_monitoring",
        max_iterations=50, loop_body=[body], automate_next=False,
    )
    wf = _make_workflow([loop, _noop()], state, sync_executor, mock_persistence, mock_observer)
    result, next_step = await wf.next_step(user_input={})

    assert next_step == "Sentinel"
    assert result["loop_iterations"] == 1
    assert wf.state.keep_monitoring is False
    assert wf.state.iteration_count == 1


# ---------------------------------------------------------------------------
# 3. LOOP max_iterations cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_loop_iterate_respects_max_iterations(sync_executor, mock_persistence, mock_observer):
    """With max_iterations=2 over 5 items, only 2 iterations run."""
    sync_executor._loop = asyncio.get_event_loop()
    state = LoopState(items=["a", "b", "c", "d", "e"])

    body = WorkflowStep(name="Collect", func=_import("tests.sdk.test_loop_and_parallel.iterate_body"))
    loop = LoopStep(
        name="Capped_Loop", mode="ITERATE", iterate_over="items",
        max_iterations=2, loop_body=[body], automate_next=False,
    )
    wf = _make_workflow([loop, _noop()], state, sync_executor, mock_persistence, mock_observer)
    result, _ = await wf.next_step(user_input={})

    assert result["loop_iterations"] == 2
    assert len(result["loop_results"]) == 2
    assert wf.state.collected == ["a", "b"]


# ---------------------------------------------------------------------------
# 4. Dynamic PARALLEL fan-out (iterate_over + task_function)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dynamic_parallel_calls_task_per_item(sync_executor, mock_persistence, mock_observer):
    """
    PARALLEL with iterate_over='devices' dispatches one task per item,
    passing each as `device_id` kwarg.
    """
    sync_executor._loop = asyncio.get_event_loop()
    state = ParallelState(devices=["a", "b", "c"])

    step = ParallelWorkflowStep(
        name="Push_Devices",
        iterate_over="devices",
        task_function="tests.sdk.test_loop_and_parallel.parallel_task",
        item_var_name="device_id",
        tasks=[],
        merge_strategy=MergeStrategy.SHALLOW,
        merge_conflict_behavior=MergeConflictBehavior.PREFER_NEW,
        automate_next=False,
    )
    wf = _make_workflow([step, _noop()], state, sync_executor, mock_persistence, mock_observer)
    result, next_step = await wf.next_step(user_input={})

    assert next_step == "Sentinel"
    assert "task_results" in result
    assert len(result["task_results"]) == 3
    assert set(result["task_results"].keys()) == {"Push_Devices_0", "Push_Devices_1", "Push_Devices_2"}
    assert result["task_results"]["Push_Devices_0"] == {"pushed": "a"}
    assert result["task_results"]["Push_Devices_1"] == {"pushed": "b"}
    assert result["task_results"]["Push_Devices_2"] == {"pushed": "c"}


# ---------------------------------------------------------------------------
# 5. Static PARALLEL backward-compatibility regression
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_static_parallel_still_works(sync_executor, mock_persistence, mock_observer):
    """Existing static task list PARALLEL steps continue to work unchanged."""
    sync_executor._loop = asyncio.get_event_loop()

    class SimpleState(BaseModel):
        from_a: bool = False
        from_b: bool = False

    state = SimpleState()
    step = ParallelWorkflowStep(
        name="Static_Parallel",
        tasks=[
            ParallelExecutionTask(
                name="task_a",
                func_path="tests.sdk.test_loop_and_parallel.static_task_a",
            ),
            ParallelExecutionTask(
                name="task_b",
                func_path="tests.sdk.test_loop_and_parallel.static_task_b",
            ),
        ],
        merge_strategy=MergeStrategy.SHALLOW,
        merge_conflict_behavior=MergeConflictBehavior.PREFER_NEW,
        automate_next=False,
    )
    wf = _make_workflow([step, _noop()], state, sync_executor, mock_persistence, mock_observer)
    result, next_step = await wf.next_step(user_input={})

    assert next_step == "Sentinel"
    assert "task_results" in result
    assert result["task_results"]["task_a"] == {"from_a": True}
    assert result["task_results"]["task_b"] == {"from_b": True}
