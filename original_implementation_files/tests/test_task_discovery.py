import sys
import os
import pytest
import yaml
from pydantic import BaseModel

# Add src to path to allow importing confucius
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from confucius.workflow_loader import WorkflowBuilder

@pytest.fixture
def temp_config_dir(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    
    # 1. Dummy state model file
    (config_dir / "test_state_models.py").write_text("from pydantic import BaseModel\n\nclass TestState(BaseModel):\n    data: str = 'initial'")

    # 2. Dummy workflow YAML with various references
    workflow_yaml = {
        "workflow_type": "DiscoveryTestWorkflow",
        "steps": [
            {"name": "Step1", "type": "ASYNC", "function": "module_a.task_one"},
            {
                "name": "Step2", 
                "type": "PARALLEL",
                "merge_function_path": "module_b.merge_func",
                "tasks": [
                    {"name": "TaskA", "function": "module_c.task_two"},
                    {"name": "TaskB", "function": "module_a.task_three"}
                ]
            },
            {
                "name": "Step3",
                "type": "STANDARD",
                "function": "module_d.noop",
                "dynamic_injection": {
                    "rules": [
                        {
                            "condition_key": "data",
                            "value_match": "inject",
                            "action": "INSERT_AFTER_CURRENT",
                            "steps_to_insert": [
                                {"name": "InjectedAsync", "type": "ASYNC", "function": "module_e.injected_task"}
                            ]
                        }
                    ]
                }
            }
        ]
    }
    with open(config_dir / "test_workflow.yaml", "w") as f:
        yaml.dump(workflow_yaml, f)

    # 3. Dummy registry YAML
    registry_yaml = {
        "workflows": [
            {
                "type": "DiscoveryTestWorkflow",
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

def test_get_all_task_modules(temp_config_dir):
    registry_path = temp_config_dir / "config" / "test_registry.yaml"
    
    # Initialize builder with the temp registry
    builder = WorkflowBuilder(registry_path=str(registry_path))
    
    modules = builder.get_all_task_modules()
    
    # Check if all modules are discovered
    assert "module_a" in modules
    assert "module_b" in modules
    assert "module_c" in modules
    assert "module_d" in modules # STANDARD steps also have function paths
    assert "module_e" in modules # Injected steps
    
    assert len(modules) == 5
