import sys
import os
import pytest
import yaml
from pydantic import BaseModel
from typing import List, Dict, Any

# --- Test Setup ---

# Set TESTING env var to true BEFORE importing celery app
os.environ["TESTING"] = "true"

# Add src to path to allow importing confucius
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
# Add root to path to allow importing workflow_utils, state_models etc.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from confucius.workflow_loader import WorkflowBuilder
from confucius.workflow import Workflow
from confucius.persistence import save_workflow_state, load_workflow_state
from state_models import OnboardingState # Using a real state model

# This fixture sets up a temporary directory with all necessary config files for integration tests.
@pytest.fixture
def temp_integration_config(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    
    # 1. Dummy workflow YAML with real task paths
    workflow_yaml = {
        "workflow_type": "IntegrationTestWorkflow",
        "steps": [
            {"name": "CreateProfile", "type": "STANDARD", "function": "workflow_utils.create_user_profile", "required_input": ["name", "email"]},
            {"name": "VerifyEmail", "type": "ASYNC", "function": "workflow_utils.verify_email_address"},
            {
                "name": "SendAndSetDB", 
                "type": "PARALLEL",
                "tasks": [
                    {"name": "SendEmail", "function": "workflow_utils.send_welcome_email"},
                    {"name": "SetDB", "function": "workflow_utils.set_compliance_alert_db"}
                ]
            },
            {"name": "FinalStep", "type": "STANDARD", "function": "workflow_utils.noop"}
        ]
    }
    workflow_file = config_dir / "integration_workflow.yaml"
    with open(workflow_file, "w") as f:
        yaml.dump(workflow_yaml, f)

    # 2. Dummy registry YAML pointing to the workflow
    registry_yaml = {
        "workflows": [
            {
                "type": "IntegrationTestWorkflow",
                "description": "An integration test workflow.",
                "config_file": str(workflow_file),
                "initial_state_model": "state_models.OnboardingState"
            }
        ]
    }
    registry_file = config_dir / "integration_registry.yaml"
    with open(registry_file, "w") as f:
        yaml.dump(registry_yaml, f)
        
    return registry_file


# --- Integration Tests ---

def test_async_step_integration(temp_integration_config):
    """
    Tests that an ASYNC step completes and correctly updates the state
    when running in Celery's eager mode.
    """
    # 1. Setup
    builder = WorkflowBuilder(registry_path=str(temp_integration_config))
    initial_data = {"name": "Test User", "email": "test@example.com"}
    workflow = builder.create_workflow(
        workflow_type="IntegrationTestWorkflow",
        initial_data=initial_data
    )
    save_workflow_state(workflow.id, workflow)
    
    # 2. Run the first STANDARD step
    result, next_step_name = workflow.next_step(initial_data)
    save_workflow_state(workflow.id, workflow)
    
    assert workflow.current_step_name == "VerifyEmail"
    assert workflow.state.user_id is not None
    assert workflow.state.email_verified is None # Not yet verified
    
    # 3. Run the ASYNC step
    # Because TESTING=true, this will execute synchronously, including the resume callback.
    # The `next_step` method internally reloads the workflow state.
    result, next_step_name = workflow.next_step({})
    
    # 4. Assertions
    # The workflow object in memory is stale; we must reload it to see the callback's effects.
    # In TESTING mode, the next_step method itself should handle reloading the state.
    reloaded_workflow = load_workflow_state(workflow.id)
    
    assert "_async_dispatch" in result
    assert reloaded_workflow.status == "ACTIVE"
    assert reloaded_workflow.current_step_name == "SendAndSetDB" # Should have advanced
    assert reloaded_workflow.state.email_verified is True # The async task should have set this

def test_parallel_step_integration(temp_integration_config):
    """
    Tests that a PARALLEL step completes and correctly updates the state
    when running in Celery's eager mode.
    """
    # 1. Setup - get the workflow to the parallel step
    builder = WorkflowBuilder(registry_path=str(temp_integration_config))
    initial_data = {"name": "Test User", "email": "test@example.com"}
    workflow = builder.create_workflow(
        workflow_type="IntegrationTestWorkflow",
        initial_data=initial_data
    )
    save_workflow_state(workflow.id, workflow)

    # Run standard step and save
    workflow.next_step(initial_data) 
    save_workflow_state(workflow.id, workflow)

    # Run async step and save
    workflow.next_step({}) 
    save_workflow_state(workflow.id, workflow)
    
    reloaded_workflow = load_workflow_state(workflow.id)
    assert reloaded_workflow.current_step_name == "SendAndSetDB"
    assert reloaded_workflow.state.email_sent is None
    assert reloaded_workflow.state.database_updated is None

    # 2. Run the PARALLEL step
    result, next_step_name = reloaded_workflow.next_step({})
    
    # 3. Assertions
    # In TESTING mode, the result contains the merged results synchronously.
    assert "_sync_parallel_result" in result
    
    # The `next_step` method should have processed this result and advanced the workflow.
    assert reloaded_workflow.status == "ACTIVE"
    assert reloaded_workflow.current_step_name == "FinalStep"
    assert reloaded_workflow.state.email_sent is True # From the first parallel task
    assert reloaded_workflow.state.database_updated is True # From the second parallel task
