import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from rufus.engine import WorkflowEngine
from rufus.workflow import Workflow
from rufus.models import WorkflowStep
from pydantic import BaseModel
from typing import Dict, Any, Optional, List, Callable, Type
import importlib
import os




@pytest.fixture
def mock_providers():
    """Provides mocked provider instances and classes for the WorkflowEngine."""
    mock_persistence_provider = AsyncMock()
    mock_execution_provider = AsyncMock()
    mock_workflow_observer = AsyncMock()
    mock_expression_evaluator_cls = MagicMock()
    mock_template_engine_cls = MagicMock()

    # Configure mocks to return themselves when instantiated for cls parameters
    mock_expression_evaluator_cls.return_value = MagicMock()
    mock_template_engine_cls.return_value = MagicMock()

    return {
        "persistence": mock_persistence_provider,
        "executor": mock_execution_provider,
        "observer": mock_workflow_observer,
        "expression_evaluator_cls": mock_expression_evaluator_cls,
        "template_engine_cls": mock_template_engine_cls,
        "workflow_registry": {
            "test_workflow": {
                "initial_state_model_path": "tests.sdk.temp_test_module.MyStateModel",
                "steps": [
                    {"name": "step1", "function": "some_func"}
                ]
            }
        }
    }

class MyStateModel(BaseModel):
    value: str = "initial"
    sub_workflow_results: Dict[str, Any] = {}


@pytest.mark.asyncio
async def test_workflow_engine_initialization(mock_providers):
    """
    Tests that the WorkflowEngine can be initialized correctly.
    """
    engine = WorkflowEngine(**mock_providers)
    assert engine.persistence == mock_providers["persistence"]
    assert engine.executor == mock_providers["executor"]
    assert engine.observer == mock_providers["observer"]
    assert engine.workflow_registry == mock_providers["workflow_registry"]
    assert engine.expression_evaluator_cls == mock_providers["expression_evaluator_cls"]
    assert engine.template_engine_cls == mock_providers["template_engine_cls"]
    assert engine.workflow_builder is not None

@pytest.mark.asyncio
async def test_workflow_engine_initialize_method(mock_providers):
    """
    Tests the initialize method of the WorkflowEngine.
    """
    engine = WorkflowEngine(**mock_providers)
    await engine.initialize()
    mock_providers["executor"].initialize.assert_called_once_with(engine)

@pytest.mark.asyncio
async def test_start_workflow_success(mock_providers):
    """
    Tests successful workflow initiation using start_workflow.
    """
    engine = WorkflowEngine(**mock_providers)
    await engine.initialize()

    # Mock the builder's create_workflow to return a mock Workflow instance
    mock_workflow_instance = MagicMock(spec=Workflow)
    mock_workflow_instance.id = "workflow-123"
    mock_workflow_instance.workflow_type = "test_workflow"
    mock_workflow_instance.state = MyStateModel()
    mock_workflow_instance.to_dict.return_value = {"id": "workflow-123", "workflow_type": "test_workflow", "state": {}}

    engine.workflow_builder.create_workflow = AsyncMock(return_value=mock_workflow_instance)

    workflow = await engine.start_workflow("test_workflow", {"value": "start"})

    engine.workflow_builder.create_workflow.assert_called_once()
    mock_providers["persistence"].save_workflow.assert_called_once_with("workflow-123", mock_workflow_instance.to_dict.return_value)
    mock_providers["observer"].on_workflow_started.assert_called_once_with("workflow-123", "test_workflow", mock_workflow_instance.state)
    assert workflow.id == "workflow-123"

@pytest.mark.asyncio
async def test_get_workflow_success(mock_providers):
    """
    Tests successful retrieval of a workflow using get_workflow.
    """
    engine = WorkflowEngine(**mock_providers)
    await engine.initialize()

    workflow_id = "existing-workflow-456"
    mock_workflow_data = {
        "id": workflow_id,
        "workflow_type": "test_workflow",
        "current_step": 0,
        "status": "ACTIVE",
        "state": {"value": "retrieved"},
        "steps_config": [],
        "state_model_path": "tests.sdk.temp_test_module.MyStateModel"
    }
    mock_providers["persistence"].load_workflow.return_value = mock_workflow_data

    # Mock Workflow.from_dict directly as it's a class method
    with patch('rufus.workflow.Workflow.from_dict') as mock_from_dict:
        mock_workflow_instance = MagicMock(spec=Workflow)
        mock_from_dict.return_value = mock_workflow_instance
        
        workflow = await engine.get_workflow(workflow_id)

        mock_providers["persistence"].load_workflow.assert_called_once_with(workflow_id)
        mock_from_dict.assert_called_once()
        assert workflow == mock_workflow_instance

@pytest.mark.asyncio
async def test_get_workflow_not_found(mock_providers):
    """
    Tests that get_workflow raises an error if the workflow is not found.
    """
    engine = WorkflowEngine(**mock_providers)
    await engine.initialize()

    workflow_id = "non-existent-workflow"
    mock_providers["persistence"].load_workflow.return_value = None

    with pytest.raises(ValueError, match=f"Workflow with ID {workflow_id} not found."):
        await engine.get_workflow(workflow_id)

@pytest.mark.asyncio
async def test_report_child_status_completed(mock_providers):
    """
    Tests report_child_status when a child workflow completes successfully.
    """
    engine = WorkflowEngine(**mock_providers)
    await engine.initialize()

    parent_id = "parent-wf-1"
    child_id = "child-wf-1"

    mock_parent_workflow = MagicMock(spec=Workflow)
    mock_parent_workflow.id = parent_id
    mock_parent_workflow.status = "PENDING_SUB_WORKFLOW"
    mock_parent_workflow.blocked_on_child_id = child_id
    mock_parent_workflow.current_step = 0
    mock_parent_workflow.current_step_name = "sub_workflow_step"
    mock_parent_workflow.metadata = {}
    mock_parent_workflow.state = MagicMock(spec=BaseModel) # No sub_workflow_results here initially
    mock_parent_workflow.to_dict.return_value = {} # Simplified for this test
    mock_parent_workflow._notify_status_change = AsyncMock()
    mock_parent_workflow.next_step = AsyncMock() # Mock next_step call

    mock_child_workflow = MagicMock(spec=Workflow)
    mock_child_workflow.id = child_id
    mock_child_workflow.workflow_type = "ChildWorkflowType"
    mock_child_workflow.state = MagicMock(spec=BaseModel)
    mock_child_workflow.state.model_dump.return_value = {"value": "child_completed"} # Child's final state
    mock_child_workflow.to_dict.return_value = {} # Simplified for this test

    engine.persistence.load_workflow.side_effect = [
        mock_parent_workflow.to_dict.return_value, # First load for parent
        mock_child_workflow.to_dict.return_value # Second load for child (in get_workflow_type)
    ]
    # For get_workflow: parent, child, child
    engine.get_workflow = AsyncMock(side_effect=[mock_parent_workflow, mock_child_workflow, mock_child_workflow])
    engine.get_workflow_type = AsyncMock(return_value="ChildWorkflowType")


    await engine.report_child_status(
        child_id=child_id,
        parent_id=parent_id,
        child_new_status="COMPLETED",
        child_result={"output": "success"}
    )

    mock_providers["persistence"].save_workflow.assert_called_with(parent_id, mock_parent_workflow.to_dict.return_value)
    assert mock_parent_workflow.status == "ACTIVE"
    assert mock_parent_workflow.blocked_on_child_id is None
    assert mock_parent_workflow.current_step == 1  # Should increment from 0 to 1
    # Now check that sub_workflow_results was set
    assert hasattr(mock_parent_workflow.state, "sub_workflow_results")
    assert mock_parent_workflow.state.sub_workflow_results[child_id]["status"] == "COMPLETED"
    assert mock_parent_workflow.state.sub_workflow_results[child_id]["final_result"] == {"output": "success"}
    mock_parent_workflow._notify_status_change.assert_called_once()
    # Note: next_step is not called automatically - auto-resume not yet implemented (see TODO in engine.py:142-144)

@pytest.mark.asyncio
async def test_report_child_status_auto_resume_async_executor(mock_providers):
    """
    Tests that auto-resume is triggered for async executors when child completes.
    """
    # Create a non-SyncExecutor mock (simulates Celery/ThreadPool)
    from rufus.implementations.execution.sync import SyncExecutor

    # Ensure the executor is NOT a SyncExecutor
    async_executor = MagicMock()
    async_executor.initialize = AsyncMock()  # Make initialize async
    async_executor.dispatch_independent_workflow = MagicMock()
    mock_providers["executor"] = async_executor

    engine = WorkflowEngine(**mock_providers)
    await engine.initialize()

    parent_id = "parent-async-123"
    child_id = "child-async-456"

    mock_parent_workflow = MagicMock(spec=Workflow)
    mock_parent_workflow.id = parent_id
    mock_parent_workflow.status = "PENDING_SUB_WORKFLOW"
    mock_parent_workflow.blocked_on_child_id = child_id
    mock_parent_workflow.current_step = 0
    mock_parent_workflow.current_step_name = "SubWorkflow"
    mock_parent_workflow.metadata = {}
    mock_parent_workflow.state = MagicMock(spec=BaseModel)
    mock_parent_workflow.to_dict.return_value = {}
    mock_parent_workflow._notify_status_change = AsyncMock()

    mock_child_workflow = MagicMock(spec=Workflow)
    mock_child_workflow.id = child_id
    mock_child_workflow.workflow_type = "ChildWorkflow"
    mock_child_workflow.state = MagicMock(spec=BaseModel)
    mock_child_workflow.state.model_dump.return_value = {"completed": True}

    engine.get_workflow = AsyncMock(side_effect=[mock_parent_workflow, mock_child_workflow])

    await engine.report_child_status(
        child_id=child_id,
        parent_id=parent_id,
        child_new_status="COMPLETED",
        child_result={"output": "success"}
    )

    # Verify auto-resume was triggered for async executor
    async_executor.dispatch_independent_workflow.assert_called_once_with(parent_id)


@pytest.mark.asyncio
async def test_report_child_status_failed(mock_providers):
    """
    Tests report_child_status when a child workflow fails.
    """
    engine = WorkflowEngine(**mock_providers)
    await engine.initialize()

    parent_id = "parent-wf-2"
    child_id = "child-wf-2"

    mock_parent_workflow = MagicMock(spec=Workflow)
    mock_parent_workflow.id = parent_id
    mock_parent_workflow.status = "PENDING_SUB_WORKFLOW"
    mock_parent_workflow.blocked_on_child_id = child_id
    mock_parent_workflow.current_step_name = "sub_workflow_step"
    mock_parent_workflow.metadata = {}
    mock_parent_workflow.to_dict.return_value = {}
    mock_parent_workflow._notify_status_change = AsyncMock()

    engine.get_workflow = AsyncMock(return_value=mock_parent_workflow)

    await engine.report_child_status(
        child_id=child_id,
        parent_id=parent_id,
        child_new_status="FAILED",
        child_result={"error": "child failed"}
    )

    mock_providers["persistence"].save_workflow.assert_called_with(parent_id, mock_parent_workflow.to_dict.return_value)
    assert mock_parent_workflow.status == "FAILED_CHILD_WORKFLOW"
    assert mock_parent_workflow.blocked_on_child_id is None
    assert mock_parent_workflow.metadata["failed_child_id"] == child_id
    assert mock_parent_workflow.metadata["failed_child_status"] == "FAILED"
    mock_parent_workflow._notify_status_change.assert_called_once()


@pytest.mark.asyncio
async def test_report_child_status_not_blocked(mock_providers):
    """
    Tests report_child_status when the parent is not blocked on the reporting child.
    """
    engine = WorkflowEngine(**mock_providers)
    await engine.initialize()

    parent_id = "parent-wf-3"
    child_id = "child-wf-3"
    other_child_id = "other-child-wf"

    mock_parent_workflow = MagicMock(spec=Workflow)
    mock_parent_workflow.id = parent_id
    mock_parent_workflow.status = "ACTIVE" # Not blocked
    mock_parent_workflow.blocked_on_child_id = other_child_id # Blocked on another child
    mock_parent_workflow.current_step_name = "some_step"
    mock_parent_workflow.to_dict.return_value = {}
    mock_parent_workflow._notify_status_change = AsyncMock()
    mock_parent_workflow.next_step = AsyncMock()

    engine.get_workflow = AsyncMock(return_value=mock_parent_workflow)

    await engine.report_child_status(
        child_id=child_id,
        parent_id=parent_id,
        child_new_status="COMPLETED",
        child_result={"output": "irrelevant"}
    )

    mock_providers["persistence"].save_workflow.assert_not_called()

    # Assert that parent status and blocked_on_child_id did not change
    assert mock_parent_workflow.status == "ACTIVE"
    assert mock_parent_workflow.blocked_on_child_id == other_child_id
    # Assert that next_step was not called
    mock_parent_workflow.next_step.assert_not_called()
    # Notify status change should not be called
    mock_parent_workflow._notify_status_change.assert_not_called()

@pytest.mark.asyncio
async def test_report_child_status_waiting_human(mock_providers):
    """
    Tests report_child_status when a child workflow enters WAITING_HUMAN status.
    """
    engine = WorkflowEngine(**mock_providers)
    await engine.initialize()

    parent_id = "parent-wf-4"
    child_id = "child-wf-4"

    mock_parent_workflow = MagicMock(spec=Workflow)
    mock_parent_workflow.id = parent_id
    mock_parent_workflow.status = "PENDING_SUB_WORKFLOW"
    mock_parent_workflow.blocked_on_child_id = child_id
    mock_parent_workflow.current_step_name = "sub_workflow_step"
    mock_parent_workflow.metadata = {}
    mock_parent_workflow.to_dict.return_value = {}
    mock_parent_workflow._notify_status_change = AsyncMock()

    engine.get_workflow = AsyncMock(return_value=mock_parent_workflow)

    await engine.report_child_status(
        child_id=child_id,
        parent_id=parent_id,
        child_new_status="WAITING_HUMAN",
        child_current_step_name="human_approval_step"
    )

    mock_providers["persistence"].save_workflow.assert_called_with(parent_id, mock_parent_workflow.to_dict.return_value)
    assert mock_parent_workflow.status == "WAITING_CHILD_HUMAN_INPUT"
    assert mock_parent_workflow.metadata["waiting_child_id"] == child_id
    assert mock_parent_workflow.metadata["waiting_child_step"] == "human_approval_step"
    mock_parent_workflow._notify_status_change.assert_called_once()


@pytest.mark.asyncio
async def test_get_workflow_type_not_found(mock_providers):
    """
    Tests that get_workflow_type raises an error if the workflow is not found.
    """
    engine = WorkflowEngine(**mock_providers)
    await engine.initialize()

    workflow_id = "non-existent-workflow-type"
    mock_providers["persistence"].load_workflow.return_value = None # Simulate workflow not found

    with pytest.raises(ValueError, match=f"Workflow with ID {workflow_id} not found."):
        await engine.get_workflow_type(workflow_id)

@pytest.mark.asyncio
async def test_get_workflow_type_success(mock_providers):
    """
    Tests that get_workflow_type successfully retrieves the workflow type.
    """
    engine = WorkflowEngine(**mock_providers)
    await engine.initialize()

    workflow_id = "existing-workflow-type"
    expected_workflow_type = "MyWorkflowType"
    mock_providers["persistence"].load_workflow.return_value = {
        "id": workflow_id,
        "workflow_type": expected_workflow_type,
        "state": {},
        "steps_config": [],
        "state_model_path": ""
    }

    workflow_type = await engine.get_workflow_type(workflow_id)
    assert workflow_type == expected_workflow_type
    mock_providers["persistence"].load_workflow.assert_called_once_with(workflow_id)
