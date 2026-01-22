import sys
import os
import pytest
import yaml
from pydantic import BaseModel, Field
from typing import List, Dict, Any

# --- Test Setup ---
# Set TESTING env var to true BEFORE importing celery app
os.environ["TESTING"] = "true"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from confucius.workflow import Workflow
from confucius.workflow_loader import _build_steps_from_config
from confucius.models import StepContext
from fastapi.testclient import TestClient
from confucius.routers import get_workflow_router
from confucius.workflow_loader import WorkflowBuilder
from confucius.persistence import save_workflow_state

# --- Mocks and Fixtures ---

class InputSchema(BaseModel):
    name: str
    age: int = Field(..., ge=18)

def dummy_func(state: BaseModel, context: StepContext):
    if context.validated_input:
        state.name = context.validated_input.name
        state.age = context.validated_input.age
    elif context.previous_step_result: # For legacy required_input tests
        state.name = context.previous_step_result.get("name")
        state.age = context.previous_step_result.get("age")
    return {"name": state.name, "age": state.age}

class SimpleState(BaseModel):
    name: str = ""
    age: int = 0

@pytest.fixture
def workflow_with_schema():
    steps_config = [{
        "name": "SchemaStep",
        "type": "STANDARD",
        "function": "tests.test_input_model.dummy_func",
        "input_model": "tests.test_input_model.InputSchema"
    }]
    steps = _build_steps_from_config(steps_config)
    return Workflow(
        workflow_steps=steps,
        initial_state_model=SimpleState(),
        steps_config=steps_config,
        state_model_path="tests.test_input_model.SimpleState"
    )

@pytest.fixture
def workflow_with_legacy_input():
    steps_config = [{
        "name": "LegacyStep",
        "type": "STANDARD",
        "function": "tests.test_input_model.dummy_func",
        "required_input": ["name", "age"]
    }]
    steps = _build_steps_from_config(steps_config)
    return Workflow(
        workflow_steps=steps,
        initial_state_model=SimpleState(),
        steps_config=steps_config,
        state_model_path="tests.test_input_model.SimpleState"
    )

# --- Unit Tests for Validation Logic ---

def test_step_creation_with_input_model():
    steps_config = [{"name": "s1", "function": "tests.test_input_model.dummy_func", "input_model": "tests.test_input_model.InputSchema"}]
    steps = _build_steps_from_config(steps_config)
    assert len(steps) == 1
    assert steps[0].input_schema is not None
    assert issubclass(steps[0].input_schema, BaseModel)
    assert steps[0].input_schema.__name__ == "InputSchema"
    assert steps[0].required_input == []

def test_validation_with_schema_success(workflow_with_schema: Workflow):
    valid_input = {"name": "John", "age": 30}
    result, _ = workflow_with_schema.next_step(valid_input)
    assert workflow_with_schema.state.name == "John"
    assert workflow_with_schema.state.age == 30
    assert result["age"] == 30

def test_validation_with_schema_coercion(workflow_with_schema: Workflow):
    """Test if Pydantic correctly coerces types e.g., str to int."""
    valid_input = {"name": "Jane", "age": "40"}
    result, _ = workflow_with_schema.next_step(valid_input)
    assert workflow_with_schema.state.name == "Jane"
    assert workflow_with_schema.state.age == 40 # Should be coerced to int
    assert isinstance(result["age"], int)

def test_validation_with_schema_missing_field(workflow_with_schema: Workflow):
    invalid_input = {"name": "John"}
    with pytest.raises(ValueError, match="Invalid input for step 'SchemaStep'"):
        workflow_with_schema.next_step(invalid_input)

def test_validation_with_schema_invalid_type(workflow_with_schema: Workflow):
    invalid_input = {"name": "John", "age": "eighteen"}
    with pytest.raises(ValueError, match="Invalid input for step 'SchemaStep'"):
        workflow_with_schema.next_step(invalid_input)
        
def test_validation_with_schema_field_validator(workflow_with_schema: Workflow):
    """Test a validator on the Pydantic model (age >= 18)."""
    invalid_input = {"name": "Timmy", "age": 10}
    with pytest.raises(ValueError, match="Invalid input for step 'SchemaStep'"):
        workflow_with_schema.next_step(invalid_input)

def test_backward_compatibility_with_required_input(workflow_with_legacy_input: Workflow):
    valid_input = {"name": "LegacyUser", "age": 50}
    workflow_with_legacy_input.next_step(valid_input)
    assert workflow_with_legacy_input.state.name == "LegacyUser"
    assert workflow_with_legacy_input.state.age == 50

def test_backward_compatibility_missing_input(workflow_with_legacy_input: Workflow):
    invalid_input = {"name": "LegacyUser"}
    with pytest.raises(ValueError, match="Missing required input for step 'LegacyStep': age"):
        workflow_with_legacy_input.next_step(invalid_input)

# --- API Tests ---
@pytest.fixture
def test_app_client(tmp_path):
    # Create a dummy registry and workflow file for the test client
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    
    workflow_yaml = {
        "steps": [
            {"name": "SchemaStep", "type": "STANDARD", "function": "tests.test_input_model.dummy_func", "input_model": "tests.test_input_model.InputSchema"},
            {"name": "LegacyStep", "type": "STANDARD", "function": "tests.test_input_model.dummy_func", "required_input": ["name", "age"]},
        ]
    }
    with open(config_dir / "api_test_workflow.yaml", "w") as f:
        yaml.dump(workflow_yaml, f)

    registry_yaml = {
        "workflows": [{
            "type": "ApiTestWorkflow",
            "description": "An API test workflow.",
            "config_file": "api_test_workflow.yaml",
            "initial_state_model": "tests.test_input_model.SimpleState"
        }]
    }
    registry_file = config_dir / "test_registry.yaml"
    with open(registry_file, "w") as f:
        yaml.dump(registry_yaml, f)

    builder = WorkflowBuilder(registry_path=str(registry_file))
    router = get_workflow_router(builder)
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)

def test_get_current_step_info_with_schema(test_app_client):
    # Start a workflow
    start_payload = {"workflow_type": "ApiTestWorkflow", "initial_data": {}}
    start_response = test_app_client.post("/api/v1/workflow/start", json=start_payload)
    assert start_response.status_code == 200
    workflow_id = start_response.json()["workflow_id"]

    # Get info for the first step, which has a schema
    info_response = test_app_client.get(f"/api/v1/workflow/{workflow_id}/current_step_info")
    assert info_response.status_code == 200
    data = info_response.json()

    assert data["name"] == "SchemaStep"
    assert data["input_schema"] is not None
    assert data["input_schema"]["title"] == "InputSchema"
    assert "name" in data["input_schema"]["properties"]
    assert "age" in data["input_schema"]["properties"]
    assert data["input_schema"]["properties"]["age"]["minimum"] == 18 # Pydantic v2 uses minimum/maximum for ge/le

def test_get_current_step_info_with_legacy(test_app_client):
    # Start a workflow and advance to the legacy step
    start_payload = {"workflow_type": "ApiTestWorkflow", "initial_data": {}}
    start_response = test_app_client.post("/api/v1/workflow/start", json=start_payload)
    workflow_id = start_response.json()["workflow_id"]
    
    # Advance past the first step
    next_payload = {"input_data": {"name": "test", "age": 20}}
    test_app_client.post(f"/api/v1/workflow/{workflow_id}/next", json=next_payload)

    # Get info for the second step
    info_response = test_app_client.get(f"/api/v1/workflow/{workflow_id}/current_step_info")
    assert info_response.status_code == 200
    data = info_response.json()
    
    assert data["name"] == "LegacyStep"
    assert data["input_schema"] is None
    assert data["required_input"] == ["name", "age"]

