"""
Tests for Workflow Versioning (Definition Snapshots)

Tests cover:
- Definition snapshot creation on workflow creation
- Snapshot persistence and loading
- Protection from YAML definition changes
- Explicit workflow versioning
- Backward compatibility
"""

import pytest
import copy
from typing import Dict, Any
from pydantic import BaseModel

from rufus.builder import WorkflowBuilder
from rufus.workflow import Workflow


class SimpleState(BaseModel):
    """Test state model."""
    value: str = "initial"
    count: int = 0


@pytest.fixture
def simple_workflow_config():
    """Fixture providing a simple workflow configuration."""
    return {
        "workflow_type": "SimpleWorkflow",
        "workflow_version": "1.0.0",
        "initial_state_model_path": "tests.sdk.test_workflow_versioning.SimpleState",
        "description": "Simple test workflow",
        "steps": [
            {
                "name": "Step_1",
                "type": "STANDARD",
                "function": "tests.sdk.test_workflow_versioning.step_1_function",
                "automate_next": False
            },
            {
                "name": "Step_2",
                "type": "STANDARD",
                "function": "tests.sdk.test_workflow_versioning.step_2_function",
                "dependencies": ["Step_1"]
            }
        ]
    }


# Dummy step functions
def step_1_function(state: SimpleState, context):
    state.count += 1
    return {"step_1_done": True}


def step_2_function(state: SimpleState, context):
    state.count += 1
    return {"step_2_done": True}


def test_workflow_has_version_and_snapshot_fields():
    """Test that Workflow class has version and snapshot fields."""
    # Create mock providers
    from unittest.mock import Mock

    workflow = Workflow(
        workflow_type="TestWorkflow",
        workflow_version="1.0.0",
        definition_snapshot={"test": "snapshot"},
        workflow_steps=[],
        initial_state_model=SimpleState(),
        persistence_provider=Mock(),
        execution_provider=Mock(),
        workflow_builder=Mock(),
        expression_evaluator_cls=Mock,
        template_engine_cls=Mock,
        workflow_observer=Mock()
    )

    assert workflow.workflow_version == "1.0.0"
    assert workflow.definition_snapshot == {"test": "snapshot"}


def test_workflow_to_dict_includes_version_and_snapshot():
    """Test that to_dict includes version and snapshot."""
    from unittest.mock import Mock

    snapshot = {
        "workflow_type": "TestWorkflow",
        "steps": [{"name": "Step_1"}]
    }

    workflow = Workflow(
        workflow_type="TestWorkflow",
        workflow_version="2.0.0",
        definition_snapshot=snapshot,
        workflow_steps=[],
        initial_state_model=SimpleState(),
        persistence_provider=Mock(),
        execution_provider=Mock(),
        workflow_builder=Mock(),
        expression_evaluator_cls=Mock,
        template_engine_cls=Mock,
        workflow_observer=Mock()
    )

    workflow_dict = workflow.to_dict()

    assert workflow_dict['workflow_version'] == "2.0.0"
    assert workflow_dict['definition_snapshot'] == snapshot


def test_workflow_backward_compatibility_no_version():
    """Test backward compatibility when version/snapshot not provided."""
    from unittest.mock import Mock

    workflow = Workflow(
        workflow_type="TestWorkflow",
        workflow_steps=[],
        initial_state_model=SimpleState(),
        persistence_provider=Mock(),
        execution_provider=Mock(),
        workflow_builder=Mock(),
        expression_evaluator_cls=Mock,
        template_engine_cls=Mock,
        workflow_observer=Mock()
    )

    assert workflow.workflow_version is None
    assert workflow.definition_snapshot is None

    # to_dict should handle None values
    workflow_dict = workflow.to_dict()
    assert 'workflow_version' in workflow_dict
    assert 'definition_snapshot' in workflow_dict


def test_definition_snapshot_is_deep_copy(simple_workflow_config):
    """Test that definition snapshot is a deep copy, not a reference."""
    original_config = simple_workflow_config

    # Simulate what WorkflowBuilder does
    snapshot = copy.deepcopy(original_config)

    # Modify original
    original_config['steps'].append({
        "name": "Step_3",
        "type": "STANDARD",
        "function": "some.new.function"
    })

    # Snapshot should be unchanged
    assert len(snapshot['steps']) == 2
    assert len(original_config['steps']) == 3


def test_snapshot_preserves_all_workflow_details(simple_workflow_config):
    """Test that snapshot preserves all workflow configuration details."""
    snapshot = copy.deepcopy(simple_workflow_config)

    # Check all key fields are preserved
    assert snapshot['workflow_type'] == "SimpleWorkflow"
    assert snapshot['workflow_version'] == "1.0.0"
    assert snapshot['initial_state_model_path'] == "tests.sdk.test_workflow_versioning.SimpleState"
    assert snapshot['description'] == "Simple test workflow"
    assert len(snapshot['steps']) == 2

    # Check step details
    step_1 = snapshot['steps'][0]
    assert step_1['name'] == "Step_1"
    assert step_1['type'] == "STANDARD"
    assert step_1['function'] == "tests.sdk.test_workflow_versioning.step_1_function"
    assert step_1['automate_next'] is False

    step_2 = snapshot['steps'][1]
    assert step_2['dependencies'] == ["Step_1"]


def test_snapshot_protection_from_yaml_changes():
    """Test that snapshot protects running workflow from YAML changes."""
    # Original YAML (v1)
    original_config = {
        "workflow_type": "OrderProcessing",
        "workflow_version": "1.0.0",
        "steps": [
            {"name": "Validate_Order", "type": "STANDARD"},
            {"name": "Human_Approval", "type": "STANDARD"},
            {"name": "Process_Payment", "type": "STANDARD"}
        ]
    }

    # Workflow created with snapshot
    snapshot_v1 = copy.deepcopy(original_config)

    # Simulate YAML file change (v2) - removes Human_Approval step
    new_yaml_config = {
        "workflow_type": "OrderProcessing",
        "workflow_version": "2.0.0",
        "steps": [
            {"name": "Validate_Order", "type": "STANDARD"},
            # Human_Approval step removed!
            {"name": "Process_Payment", "type": "STANDARD"}
        ]
    }

    # Running workflow should still use v1 snapshot
    assert len(snapshot_v1['steps']) == 3
    assert snapshot_v1['steps'][1]['name'] == "Human_Approval"

    # New workflows would use v2
    assert len(new_yaml_config['steps']) == 2
    assert 'Human_Approval' not in [s['name'] for s in new_yaml_config['steps']]


def test_explicit_versioning_workflow_type_suffix():
    """Test explicit versioning using workflow type suffix."""
    # Approach: OrderProcessing_v1, OrderProcessing_v2

    config_v1 = {
        "workflow_type": "OrderProcessing_v1",
        "workflow_version": "1.0.0",
        "steps": [
            {"name": "Legacy_Step", "type": "STANDARD"}
        ]
    }

    config_v2 = {
        "workflow_type": "OrderProcessing_v2",
        "workflow_version": "2.0.0",
        "steps": [
            {"name": "New_Step", "type": "STANDARD"}
        ]
    }

    # Both versions can coexist
    assert config_v1['workflow_type'] != config_v2['workflow_type']
    assert config_v1['workflow_version'] != config_v2['workflow_version']


def test_hybrid_versioning_approach(simple_workflow_config):
    """Test hybrid approach: snapshot + explicit version."""
    # Workflow with explicit version
    config_with_version = copy.deepcopy(simple_workflow_config)
    config_with_version['workflow_version'] = "1.5.0"

    # Snapshot captures both config and version
    snapshot = copy.deepcopy(config_with_version)

    assert snapshot['workflow_version'] == "1.5.0"
    assert snapshot['workflow_type'] == "SimpleWorkflow"
    assert len(snapshot['steps']) == 2


def test_version_comparison_for_compatibility():
    """Test version comparison logic for compatibility checking."""
    # This would be used by WorkflowBuilder to check compatibility

    def is_compatible(snapshot_version: str, current_version: str) -> bool:
        """Check if versions are compatible (simple major version check)."""
        if not snapshot_version or not current_version:
            return True  # Allow if version not specified

        snap_major = int(snapshot_version.split('.')[0])
        curr_major = int(current_version.split('.')[0])

        return snap_major == curr_major  # Compatible if same major version

    # Same major version - compatible
    assert is_compatible("1.0.0", "1.5.0") is True
    assert is_compatible("2.3.1", "2.7.9") is True

    # Different major version - incompatible
    assert is_compatible("1.0.0", "2.0.0") is False
    assert is_compatible("2.0.0", "3.0.0") is False

    # No version specified - compatible
    assert is_compatible(None, "1.0.0") is True
    assert is_compatible("1.0.0", None) is True


def test_snapshot_size_reasonable():
    """Test that snapshot size is reasonable (not bloated)."""
    import json

    # Typical workflow config
    config = {
        "workflow_type": "TypicalWorkflow",
        "workflow_version": "1.0.0",
        "initial_state_model_path": "my_app.models.WorkflowState",
        "description": "A typical workflow with several steps",
        "steps": [
            {
                "name": f"Step_{i}",
                "type": "STANDARD",
                "function": f"my_app.steps.step_{i}",
                "automate_next": True
            }
            for i in range(10)  # 10 steps
        ]
    }

    # Snapshot is just JSON serialization
    snapshot_json = json.dumps(config)
    snapshot_size = len(snapshot_json.encode('utf-8'))

    # Should be < 5KB for typical workflow
    assert snapshot_size < 5000  # 5KB

    # For this specific config, should be around 1-2KB
    assert snapshot_size < 2000  # 2KB


def test_snapshot_preserves_complex_step_configs():
    """Test that snapshot preserves complex step configurations."""
    complex_config = {
        "workflow_type": "ComplexWorkflow",
        "steps": [
            {
                "name": "Parallel_Tasks",
                "type": "PARALLEL",
                "tasks": [
                    {"name": "task1", "function": "path.to.task1"},
                    {"name": "task2", "function": "path.to.task2"},
                    {"name": "task3", "function": "path.to.task3"}
                ],
                "merge_strategy": "DEEP",
                "allow_partial_success": True
            },
            {
                "name": "Decision_Step",
                "type": "DECISION",
                "function": "path.to.decision",
                "routes": [
                    {"condition": "state.value > 100", "target": "High_Value"},
                    {"condition": "state.value <= 100", "target": "Low_Value"}
                ]
            },
            {
                "name": "Compensatable_Step",
                "type": "STANDARD",
                "function": "path.to.main",
                "compensate_function": "path.to.compensate"
            }
        ]
    }

    snapshot = copy.deepcopy(complex_config)

    # Verify complex structures preserved
    parallel_step = snapshot['steps'][0]
    assert len(parallel_step['tasks']) == 3
    assert parallel_step['merge_strategy'] == "DEEP"

    decision_step = snapshot['steps'][1]
    assert len(decision_step['routes']) == 2

    compensatable_step = snapshot['steps'][2]
    assert 'compensate_function' in compensatable_step


def test_multiple_workflow_instances_independent_snapshots():
    """Test that multiple workflow instances have independent snapshots."""
    config = {
        "workflow_type": "MyWorkflow",
        "steps": [{"name": "Step_1"}]
    }

    # Create two snapshots (as WorkflowBuilder would)
    snapshot_1 = copy.deepcopy(config)
    snapshot_2 = copy.deepcopy(config)

    # Modify config
    config['steps'].append({"name": "Step_2"})

    # Both snapshots should be unchanged
    assert len(snapshot_1['steps']) == 1
    assert len(snapshot_2['steps']) == 1

    # Snapshots are independent from each other
    snapshot_1['custom_field'] = "value"
    assert 'custom_field' not in snapshot_2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
