"""
Test utilities for CLI testing.
"""
from pathlib import Path
from typing import Any, Dict, Optional
from pydantic import BaseModel
import yaml

from ruvon.models import StepContext


# Test state model for sample workflows
class TestState(BaseModel):
    """Test state model for CLI testing."""
    user_id: Optional[str] = None
    status: Optional[str] = None
    result: Optional[str] = None
    step_1_output: Optional[str] = None
    step_2_output: Optional[str] = None


# Test step functions
def step_1(state: TestState, context: StepContext) -> Dict[str, Any]:
    """Test step 1."""
    state.step_1_output = "Step 1 executed"
    return {"step_1_output": "Step 1 executed"}


def step_2(state: TestState, context: StepContext) -> Dict[str, Any]:
    """Test step 2."""
    state.step_2_output = "Step 2 executed"
    return {"step_2_output": "Step 2 executed"}


def assert_output_contains(output: str, expected: str) -> None:
    """
    Assert that output contains expected string.

    Args:
        output: The output to check
        expected: The expected substring

    Raises:
        AssertionError: If expected not found in output
    """
    assert expected in output, f"Expected '{expected}' not found in output:\n{output}"


def assert_output_not_contains(output: str, unexpected: str) -> None:
    """
    Assert that output does not contain unexpected string.

    Args:
        output: The output to check
        unexpected: The unexpected substring

    Raises:
        AssertionError: If unexpected found in output
    """
    assert unexpected not in output, f"Unexpected '{unexpected}' found in output:\n{output}"


def create_test_workflow_yaml(
    output_path: Path,
    workflow_type: str = "TestWorkflow",
    steps: Optional[list] = None
) -> Path:
    """
    Create a test workflow YAML file.

    Args:
        output_path: Path to write the YAML file
        workflow_type: The workflow type name
        steps: List of step definitions (optional)

    Returns:
        Path to the created YAML file
    """
    if steps is None:
        steps = [
            {
                "name": "Step_1",
                "type": "STANDARD",
                "function": "tests.cli.utils.step_1"
            }
        ]

    workflow_content = {
        "workflow_type": workflow_type,
        "workflow_version": "1.0.0",
        "initial_state_model": "tests.cli.utils.TestState",
        "description": f"Test workflow: {workflow_type}",
        "steps": steps
    }

    with open(output_path, 'w') as f:
        yaml.dump(workflow_content, f)

    return output_path


def create_test_config(
    output_path: Path,
    persistence_provider: str = "memory",
    execution_provider: str = "sync",
    **kwargs
) -> Path:
    """
    Create a test config file.

    Args:
        output_path: Path to write the config file
        persistence_provider: Persistence provider type
        execution_provider: Execution provider type
        **kwargs: Additional config options

    Returns:
        Path to the created config file
    """
    config_content = {
        "persistence": {
            "provider": persistence_provider,
            **kwargs.get("persistence_options", {})
        },
        "execution": {
            "provider": execution_provider,
            **kwargs.get("execution_options", {})
        },
        "defaults": kwargs.get("defaults", {})
    }

    with open(output_path, 'w') as f:
        yaml.dump(config_content, f)

    return output_path
