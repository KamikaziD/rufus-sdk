"""
Tests for PARALLEL step batch_size field.

Verifies:
  1. batch_size splits large iterate_over lists into correct chunk sizes
  2. batch_size=0 (default) dispatches all tasks at once (regression guard)
  3. batch_size larger than the list dispatches all items in a single call
  4. Results from all batches are merged into workflow state correctly

Fixtures are sync to avoid pytest-asyncio 0.21/pytest 9.x incompatibility.
"""
import asyncio
import concurrent.futures
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from pydantic import BaseModel, ConfigDict
from typing import List

from ruvon.workflow import Workflow
from ruvon.models import (
    WorkflowStep, ParallelWorkflowStep,
    StepContext, MergeStrategy, MergeConflictBehavior,
)
from ruvon.implementations.execution.sync import SyncExecutor
from ruvon.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from ruvon.implementations.templating.jinja2 import Jinja2TemplateEngine


# ---------------------------------------------------------------------------
# State models
# ---------------------------------------------------------------------------

class BatchState(BaseModel):
    """State for batch tests. Allows extra fields so per-item keys can be set."""
    model_config = ConfigDict(extra="allow")
    items: List[str] = []


# ---------------------------------------------------------------------------
# Step functions
# ---------------------------------------------------------------------------

def noop_step(state, context: StepContext, **_) -> dict:
    return {}


def unique_key_task(state: dict, context: StepContext, item: str = "", **_) -> dict:
    """Returns a unique key per item so all results survive shallow merge."""
    return {f"done_{item}": True}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sync_executor():
    exec_ = SyncExecutor()
    exec_._thread_pool_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)
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
        workflow_type="BatchTestWorkflow",
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
    return WorkflowStep(name="Sentinel", func=_import("tests.sdk.test_parallel_batching.noop_step"))


def _make_parallel_step(items_field: str, task_fn: str, batch_size: int) -> ParallelWorkflowStep:
    return ParallelWorkflowStep(
        name="Batch_Step",
        iterate_over=items_field,
        task_function=task_fn,
        item_var_name="item",
        batch_size=batch_size,
        tasks=[],
        merge_strategy=MergeStrategy.SHALLOW,
        merge_conflict_behavior=MergeConflictBehavior.PREFER_NEW,
        automate_next=False,
    )


def _minimal_sync_result() -> dict:
    """Minimal valid return value from dispatch_parallel_tasks for the batch path."""
    return {"_async_dispatch": False, "_sync_parallel_result": {}, "task_results": {}, "errors": {}}


# ---------------------------------------------------------------------------
# 1. Correct chunk count: 10 items, batch_size=3 → 4 dispatch calls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_size_splits_into_correct_chunks(sync_executor, mock_persistence, mock_observer):
    """10 items with batch_size=3 should trigger 4 separate dispatch calls (3+3+3+1)."""
    sync_executor._loop = asyncio.get_event_loop()
    items = [f"item_{i}" for i in range(10)]
    state = BatchState(items=items)

    step = _make_parallel_step("items", "tests.sdk.test_parallel_batching.unique_key_task", batch_size=3)
    wf = _make_workflow([step, _noop()], state, sync_executor, mock_persistence, mock_observer)

    call_chunk_sizes = []

    original_dispatch = sync_executor.dispatch_parallel_tasks

    async def tracking_dispatch(tasks, **kwargs):
        call_chunk_sizes.append(len(tasks))
        return _minimal_sync_result()

    with patch.object(sync_executor, "dispatch_parallel_tasks", side_effect=tracking_dispatch):
        await wf.next_step(user_input={})

    assert call_chunk_sizes == [3, 3, 3, 1], (
        f"Expected 4 calls with sizes [3,3,3,1], got {call_chunk_sizes}"
    )


# ---------------------------------------------------------------------------
# 2. batch_size=0 (default) dispatches all items in a single call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_size_zero_dispatches_all_at_once(sync_executor, mock_persistence, mock_observer):
    """batch_size=0 (default) must NOT batch — all 10 items dispatched in one call."""
    sync_executor._loop = asyncio.get_event_loop()
    items = [f"item_{i}" for i in range(10)]
    state = BatchState(items=items)

    step = _make_parallel_step("items", "tests.sdk.test_parallel_batching.unique_key_task", batch_size=0)
    wf = _make_workflow([step, _noop()], state, sync_executor, mock_persistence, mock_observer)

    dispatch_calls = []

    async def tracking_dispatch(tasks, **kwargs):
        dispatch_calls.append(len(tasks))
        return _minimal_sync_result()

    with patch.object(sync_executor, "dispatch_parallel_tasks", side_effect=tracking_dispatch):
        await wf.next_step(user_input={})

    assert len(dispatch_calls) == 1, f"Expected 1 dispatch call, got {len(dispatch_calls)}"
    assert dispatch_calls[0] == 10, f"Expected all 10 items in single call, got {dispatch_calls[0]}"


# ---------------------------------------------------------------------------
# 3. batch_size larger than list → single dispatch with all items
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_size_larger_than_list(sync_executor, mock_persistence, mock_observer):
    """When batch_size exceeds list length, all items are dispatched in one call."""
    sync_executor._loop = asyncio.get_event_loop()
    items = [f"item_{i}" for i in range(10)]
    state = BatchState(items=items)

    step = _make_parallel_step("items", "tests.sdk.test_parallel_batching.unique_key_task", batch_size=100)
    wf = _make_workflow([step, _noop()], state, sync_executor, mock_persistence, mock_observer)

    dispatch_calls = []

    async def tracking_dispatch(tasks, **kwargs):
        dispatch_calls.append(len(tasks))
        return _minimal_sync_result()

    with patch.object(sync_executor, "dispatch_parallel_tasks", side_effect=tracking_dispatch):
        await wf.next_step(user_input={})

    assert len(dispatch_calls) == 1, f"Expected 1 dispatch call, got {len(dispatch_calls)}"
    assert dispatch_calls[0] == 10


# ---------------------------------------------------------------------------
# 4. Results from all batches are merged into state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_results_merged_into_state(sync_executor, mock_persistence, mock_observer):
    """
    Each batch's _sync_parallel_result is applied to state before the next batch runs.
    With unique keys per item, all 10 items' results must appear in final state.
    """
    sync_executor._loop = asyncio.get_event_loop()
    items = [f"item_{i}" for i in range(10)]
    state = BatchState(items=items)

    # batch_size=5 → 2 batches of 5
    step = _make_parallel_step("items", "tests.sdk.test_parallel_batching.unique_key_task", batch_size=5)
    wf = _make_workflow([step, _noop()], state, sync_executor, mock_persistence, mock_observer)

    await wf.next_step(user_input={})

    # unique_key_task returns {"done_<item>": True} for each item.
    # With unique keys, SyncExecutor shallow-merges them all into _sync_parallel_result.
    # After 2 batches, all 10 keys must be set in workflow state.
    state_dict = wf.state.model_dump()
    for i in range(10):
        key = f"done_item_{i}"
        assert state_dict.get(key) is True, (
            f"Expected state.{key} = True after batching, but it was missing or False"
        )
