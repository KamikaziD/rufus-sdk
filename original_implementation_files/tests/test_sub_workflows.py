import pytest
from uuid import uuid4
import os
import celery
from pydantic import BaseModel
from typing import Optional, Dict, Any

# Import the global celery app instance
from src.confucius.celery_app import celery_app as confucius_celery_app
# Import persistence functions
from src.confucius.persistence import load_workflow_state, save_workflow_state
from src.confucius.tasks import execute_sub_workflow
from src.confucius.workflow import WorkflowJumpDirective
from src.confucius.workflow_loader import WorkflowBuilder

import src.confucius.workflow_loader as workflow_loader_module

# Define test-specific state models locally
class TestParentState(BaseModel):
    parent_id: str
    sub_workflow_results: Optional[Dict[str, Any]] = None
    p_step_4_executed: bool = False

class TestChildState(BaseModel):
    child_id: str
    step_1_executed: bool = False
    step_2_executed: bool = False
    final_message: Optional[str] = None

# Configure pytest-celery to use our factory-created app
@pytest.fixture(scope="session")
def celery_app():
    """
    Overrides the celery_app fixture from pytest-celery to use our
    global app instance but with a test-specific configuration.
    """
    app = confucius_celery_app
    app.conf.update(
        broker_url="memory://",
        result_backend="cache+memory://",
        task_always_eager=True  # Ensure tasks run synchronously in tests
    )
    # The autodiscovery is already done in the global app, so no need to repeat
    celery.current_app = app  # Explicitly set the current app
    return app

# The celery_worker fixture will now automatically pick up the app from the celery_app fixture
# and configure itself according to the returned app.

# Use an absolute path for the test-specific registry to avoid CWD issues.
test_registry_path = os.path.abspath("tests/config/testing_workflow_registry.yaml")


@pytest.fixture(autouse=True)
def patch_global_workflow_builder(monkeypatch):
    """
    Monkey-patches the global workflow_builder instance in the workflow_loader
    module to use our test-specific registry.
    """
    test_builder = WorkflowBuilder(registry_path=test_registry_path)
    monkeypatch.setattr(workflow_loader_module, "workflow_builder", test_builder)
    return test_builder


@pytest.fixture
def parent_workflow(patch_global_workflow_builder, celery_app, celery_worker):
    """
    Fixture to create a new parent workflow instance for each test.
    This now depends on the pytest-celery fixtures to ensure the app
    is correctly initialized before the workflow is created.
    """
    parent_id = f"parent-{uuid4()}"
    workflow = patch_global_workflow_builder.create_workflow(
        workflow_type="TestParentWorkflow",
        initial_data={"parent_id": parent_id}
    )
    save_workflow_state(workflow.id, workflow)
    return workflow


def test_sub_workflow_creation_and_resumption(parent_workflow):
    """
    Tests the full lifecycle of a sub-workflow using the eager celery worker.
    """
    # 1. Start the parent workflow. Because the first step has automate_next=true,
    # this single call will execute Step 1, then immediately execute Step 2,
    # which triggers the sub-workflow and pauses the parent.
    parent_workflow.next_step({})
    save_workflow_state(parent_workflow.id, parent_workflow)

    # 2. Verify parent is paused and waiting for the child
    reloaded_parent = load_workflow_state(parent_workflow.id)
    assert reloaded_parent is not None, "Parent workflow should be found in the database"
    assert reloaded_parent.status == "PENDING_SUB_WORKFLOW"
    assert reloaded_parent.blocked_on_child_id is not None
    assert reloaded_parent.current_step_name == "P_Step_2_Trigger_Child"
    child_workflow_id = reloaded_parent.blocked_on_child_id

    # 3. Verify the child workflow was created correctly
    child_workflow = load_workflow_state(child_workflow_id)
    assert child_workflow is not None, "Child workflow should have been saved and be loadable"
    assert child_workflow.workflow_type == "TestChildWorkflow"
    assert child_workflow.parent_execution_id == parent_workflow.id
    assert child_workflow.status == "ACTIVE"
    assert isinstance(child_workflow.state, TestChildState)

    # 4. Execute the child workflow's Celery task. Since tasks are eager,
    # this runs synchronously and should trigger the parent resumption task.
    execute_sub_workflow(child_id=child_workflow.id, parent_id=parent_workflow.id, blocked_on_child_meta=reloaded_parent.blocked_on_child_meta)

    # 5. Verify the child workflow is complete
    reloaded_child = load_workflow_state(child_workflow_id)
    assert reloaded_child.status == "COMPLETED"
    assert reloaded_child.state.step_1_executed is True
    assert reloaded_child.state.step_2_executed is True
    assert "finished successfully" in reloaded_child.state.final_message

    # 6. Verify the parent has been resumed and advanced
    final_parent = load_workflow_state(parent_workflow.id)
    assert final_parent.status == "COMPLETED"
    assert final_parent.blocked_on_child_id is None
    # The parent completes after the merge, at the step that triggered the sub-workflow.
    # The current_step will be incremented past that step.
    # So if P_Step_2_Trigger_Child (index 1) triggered it, current_step becomes 2.
    assert final_parent.current_step_name == "P_Step_3_Trigger_Child_And_Automate"

    # 7. Check that the child's state was correctly merged
    assert hasattr(final_parent.state, 'sub_workflow_results')
    assert final_parent.state.sub_workflow_results is not None
    child_results = final_parent.state.sub_workflow_results.get("TestChildWorkflow")
    assert child_results is not None
    assert child_results["final_message"] == reloaded_child.state.final_message

    # 8. The parent workflow should be completed at this point due to the merge function
    assert final_parent.state.p_step_4_executed is True
    assert final_parent.status == "COMPLETED"
    print("Sub-workflow lifecycle test completed successfully.")


def test_sub_workflow_with_automate_next(parent_workflow):
    """
    Tests that the parent workflow automatically continues if the sub-workflow
    step has `automate_next: true`.
    """
    # Jump the parent workflow directly to the step that has automate_next enabled
    try:
        raise WorkflowJumpDirective("P_Step_3_Trigger_Child_And_Automate")
    except WorkflowJumpDirective as e:
        target_index = next(i for i, s in enumerate(parent_workflow.workflow_steps) if s.name == e.target_step_name)
        parent_workflow.current_step = target_index
    save_workflow_state(parent_workflow.id, parent_workflow)

    # Execute the step that triggers the sub-workflow. This will pause the parent.
    parent_workflow.next_step({})
    save_workflow_state(parent_workflow.id, parent_workflow)

    # Verify parent is paused
    reloaded_parent = load_workflow_state(parent_workflow.id)
    assert reloaded_parent.status == "PENDING_SUB_WORKFLOW"
    child_workflow_id = reloaded_parent.blocked_on_child_id

    # Load child workflow for execution
    child_workflow = load_workflow_state(child_workflow_id) # NEW: Load child workflow here

    # Execute the child workflow to completion
    execute_sub_workflow(child_id=child_workflow.id, parent_id=parent_workflow.id, blocked_on_child_meta=reloaded_parent.blocked_on_child_meta)

    # The `resume_parent_from_child` task should have run and, because `automate_next`
    # was true, it should have immediately called `next_step` on the parent, completing the workflow.
    final_parent = load_workflow_state(parent_workflow.id)

    assert final_parent.status == "COMPLETED"
    assert final_parent.state.p_step_4_executed is True
    assert hasattr(final_parent.state, 'sub_workflow_results')
    assert final_parent.state.sub_workflow_results is not None
    child_results = final_parent.state.sub_workflow_results.get("TestChildWorkflow")
    assert "finished successfully" in child_results["final_message"]
    print("Sub-workflow with automate_next test completed successfully.")
