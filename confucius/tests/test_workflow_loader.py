import sys
import os
import pytest
import yaml
from pydantic import BaseModel

# Add src to path to allow importing confucius
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from confucius.workflow_loader import WorkflowBuilder, _build_steps_from_config
from confucius.workflow import Workflow, WorkflowStep, AsyncWorkflowStep, ParallelWorkflowStep

# --- Test Setup ---

class TestState(BaseModel):
    data: str = "initial"

# We create a fixture that sets up a temporary directory with all necessary config files.
@pytest.fixture
def temp_config_dir(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    
    # 1. Dummy state model file
    (config_dir / "test_state_models.py").write_text("from pydantic import BaseModel\n\nclass TestState(BaseModel):\n    data: str = 'initial'")

    # 2. Dummy functions file
    (config_dir / "test_workflow_funcs.py").write_text("def standard_func(state, context): pass\n\ndef merge_func(results): pass")

    # 3. Dummy workflow YAML
    workflow_yaml = {
        "workflow_type": "LoaderTestWorkflow",
        "steps": [
            {"name": "StandardStep", "type": "STANDARD", "function": "config.test_workflow_funcs.standard_func"},
            {"name": "AsyncStep", "type": "ASYNC", "function": "workflow_utils.run_credit_check_agent"},
            {
                "name": "ParallelStep", 
                "type": "PARALLEL",
                "merge_function_path": "config.test_workflow_funcs.merge_func",
                "tasks": [
                    {"name": "TaskA", "function": "workflow_utils.run_credit_check_agent"},
                    {"name": "TaskB", "function": "workflow_utils.run_fraud_detection_agent"}
                ]
            }
        ]
    }
    with open(config_dir / "test_workflow.yaml", "w") as f:
        yaml.dump(workflow_yaml, f)

    # 4. Dummy registry YAML
    registry_yaml = {
        "workflows": [
            {
                "type": "LoaderTestWorkflow",
                "description": "A test workflow.",
                "config_file": "test_workflow.yaml",
                "initial_state_model": "config.test_state_models.TestState"
            }
        ]
    }
    with open(config_dir / "test_registry.yaml", "w") as f:
        yaml.dump(registry_yaml, f)
        
    # Add the temp config dir to the path to allow imports
    sys.path.insert(0, str(tmp_path))
    yield tmp_path
    sys.path.pop(0)


# --- Tests ---

def test_build_steps_from_config(temp_config_dir):
    config_path = temp_config_dir / "config" / "test_workflow.yaml"
    with open(config_path, "r") as f:
        workflow_config = yaml.safe_load(f)
    
    steps_config = workflow_config["steps"]
    
    # Run the builder function
    steps = _build_steps_from_config(steps_config)
    
    assert len(steps) == 3
    
    # Test Standard Step
    standard_step = steps[0]
    assert isinstance(standard_step, WorkflowStep)
    assert not isinstance(standard_step, (AsyncWorkflowStep, ParallelWorkflowStep))
    assert standard_step.name == "StandardStep"
    assert callable(standard_step.func) # Should be a resolved callable
    
    # Test Async Step
    async_step = steps[1]
    assert isinstance(async_step, AsyncWorkflowStep)
    assert async_step.name == "AsyncStep"
    assert async_step.func is None # The callable is None
    assert async_step.func_path == "workflow_utils.run_credit_check_agent" # The path is a string

    # Test Parallel Step
    parallel_step = steps[2]
    assert isinstance(parallel_step, ParallelWorkflowStep)
    assert parallel_step.name == "ParallelStep"
    assert parallel_step.merge_function_path == "config.test_workflow_funcs.merge_func"
    assert len(parallel_step.tasks) == 2
    assert parallel_step.tasks[0].name == "TaskA"
    assert parallel_step.tasks[0].func_path == "workflow_utils.run_credit_check_agent" # Path is a string
    assert parallel_step.tasks[1].name == "TaskB"
    assert parallel_step.tasks[1].func_path == "workflow_utils.run_fraud_detection_agent"

def test_workflow_builder_creation(temp_config_dir):
    registry_path = temp_config_dir / "config" / "test_registry.yaml"
    
    # Initialize builder with the temp registry
    builder = WorkflowBuilder(registry_path=str(registry_path))
    
    # Test state model loading
    state_model = builder.get_state_model_class("LoaderTestWorkflow")
    assert state_model.__name__ == "TestState"
    
    # Test workflow creation
    workflow = builder.create_workflow(
        workflow_type="LoaderTestWorkflow",
        initial_data={"data": "test"}
    )
    
    assert isinstance(workflow, Workflow)
    assert workflow.workflow_type == "LoaderTestWorkflow"
    assert isinstance(workflow.state, state_model)
    assert workflow.state.data == "test"
    assert len(workflow.workflow_steps) == 3
    assert workflow.workflow_steps[1].name == "AsyncStep"

def test_workflow_builder_file_not_found():
    with pytest.raises(FileNotFoundError):
        WorkflowBuilder(registry_path="non/existent/path.yaml")

