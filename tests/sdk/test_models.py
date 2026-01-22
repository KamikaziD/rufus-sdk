import pytest
from rufus.models import (
    WorkflowJumpDirective, WorkflowPauseDirective, StartSubWorkflowDirective,
    SagaWorkflowException, WorkflowFailedException
)

def test_workflow_jump_directive_initialization():
    """
    Tests that WorkflowJumpDirective initializes correctly.
    """
    target_step = "TargetStep"
    exception = WorkflowJumpDirective(target_step)
    assert exception.target_step_name == target_step

def test_workflow_pause_directive_initialization():
    """
    Tests that WorkflowPauseDirective initializes correctly.
    """
    result = {"status": "paused", "reason": "human_input_needed"}
    exception = WorkflowPauseDirective(result)
    assert exception.result == result

def test_start_sub_workflow_directive_initialization():
    """
    Tests that StartSubWorkflowDirective initializes correctly.
    """
    workflow_type = "ChildWorkflow"
    initial_data = {"key": "value"}
    data_region = "US-East"
    exception = StartSubWorkflowDirective(workflow_type, initial_data, data_region)
    assert exception.workflow_type == workflow_type
    assert exception.initial_data == initial_data
    assert exception.data_region == data_region

def test_saga_workflow_exception_initialization():
    """
    Tests that SagaWorkflowException initializes correctly.
    """
    step_name = "FailedStep"
    original_exception = ValueError("Something went wrong")
    exception = SagaWorkflowException(step_name, original_exception)
    assert exception.step_name == step_name
    assert exception.original_exception == original_exception
    assert f"Saga step '{step_name}' failed: {original_exception}" in str(exception)

def test_workflow_failed_exception_initialization():
    """
    Tests that WorkflowFailedException initializes correctly.
    """
    workflow_id = "wf-123"
    step_name = "CriticalStep"
    original_exception = RuntimeError("Service unavailable")
    exception = WorkflowFailedException(workflow_id, step_name, original_exception)
    assert exception.workflow_id == workflow_id
    assert exception.step_name == step_name
    assert exception.original_exception == original_exception
    assert f"Workflow {workflow_id} failed at step '{step_name}': {original_exception}" in str(exception)
