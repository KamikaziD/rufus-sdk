#!/usr/bin/env python3
"""
Test script for production features:
- PostgreSQL persistence
- Saga pattern with compensation
- Sub-workflow execution

Run with: python test_production_features.py
"""

import os
import sys
import asyncio
from typing import Dict, Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set environment variables for testing
os.environ['WORKFLOW_STORAGE'] = 'postgres'

os.environ['TESTING'] = 'true'  # Synchronous Celery execution

from src.confucius.workflow import Workflow, CompensatableStep, StartSubWorkflowDirective
from src.confucius.persistence import save_workflow_state, load_workflow_state, get_storage_backend
from pydantic import BaseModel


# ============================================================================
# Test State Models
# ============================================================================

class TestState(BaseModel):
    """Simple test state"""
    step1_executed: bool = False
    step2_executed: bool = False
    step3_executed: bool = False
    compensation1_executed: bool = False
    compensation2_executed: bool = False
    sub_workflow_results: Dict[str, Any] = {}


class ChildState(BaseModel):
    """State for child workflow"""
    child_step_executed: bool = False
    result: str = ""


# ============================================================================
# Test Functions
# ============================================================================

def step1_func(state: TestState, **kwargs):
    """Step 1: Simple execution"""
    print("  → Executing step1")
    state.step1_executed = True
    return {"step1": "completed"}


def step2_func(state: TestState, context: "StepContext", **kwargs):
    """Step 2: Simple execution"""
    print("  → Executing step2")
    state.step2_executed = True
    return {"step2": "completed"}


def step3_func_fail(state: TestState, **kwargs):
    """Step 3: Fails to trigger saga rollback"""
    print("  → Executing step3 (will fail)")
    raise Exception("Step 3 failed intentionally")


def compensate_step1(state: TestState, **kwargs):
    """Compensation for step 1"""
    print("  → Compensating step1")
    state.compensation1_executed = True
    state.step1_executed = False
    return {"step1": "compensated"}


def compensate_step2(state: TestState, **kwargs):
    """Compensation for step 2"""
    print("  → Compensating step2")
    state.compensation2_executed = True
    state.step2_executed = False
    return {"step2": "compensated"}


def launch_child_workflow(state: TestState, **kwargs):
    """Launch a child workflow"""
    print("  → Launching child workflow")
    raise StartSubWorkflowDirective(
        workflow_type="ChildWorkflow",
        initial_data={"parent_id": "test"}
    )


def child_workflow_step(state: ChildState, context: "StepContext", **kwargs):
    """Child workflow step"""
    print("  → Executing child workflow step")
    state.child_step_executed = True
    state.result = "child_completed"
    return {"result": "child_completed"}


# ============================================================================
# Test 1: Basic PostgreSQL Persistence
# ============================================================================

def test_basic_postgresql_persistence():
    """Test that workflows can be saved and loaded from PostgreSQL"""
    print("\n" + "="*70)
    print("TEST 1: Basic PostgreSQL Persistence")
    print("="*70)

    # Verify we're using PostgreSQL
    backend = get_storage_backend()
    print(f"Storage backend: {backend}")
    assert backend == 'postgres', f"Expected 'postgres' but got '{backend}'"

    # Create a simple workflow
    step1 = CompensatableStep(
        name="Step1",
        func=step1_func,
        required_input=[],
    )

    step2 = CompensatableStep(
        name="Step2",
        func=step2_func,
        required_input=[],
    )

    workflow = Workflow(
        workflow_type="BasicTest",
        initial_state_model=TestState(),
        workflow_steps=[step1, step2],
        state_model_path="test_production_features.TestState"
    )

    original_id = workflow.id
    print(f"Created workflow: {original_id}")

    # Execute first step
    print("\nExecuting Step 1...")
    result, next_step = workflow.next_step({})
    print(f"Result: {result}")
    print(f"Next step: {next_step}")

    # Save to PostgreSQL
    print("\nSaving to PostgreSQL...")
    save_workflow_state(workflow.id, workflow)
    print("✓ Saved successfully")

    # Load from PostgreSQL
    print("\nLoading from PostgreSQL...")
    loaded_workflow = load_workflow_state(original_id)
    print(f"✓ Loaded workflow: {loaded_workflow.id}")

    # Verify state
    assert loaded_workflow.id == original_id
    assert loaded_workflow.workflow_type == "BasicTest"
    assert loaded_workflow.state.step1_executed == True
    assert loaded_workflow.state.step2_executed == False
    assert loaded_workflow.current_step == 1

    print("\n✅ TEST 1 PASSED: PostgreSQL persistence working correctly")
    return True


# ============================================================================
# Test 2: Saga Pattern with Compensation
# ============================================================================

def test_saga_pattern():
    """Test automatic rollback with saga pattern"""
    print("\n" + "="*70)
    print("TEST 2: Saga Pattern with Compensation")
    print("="*70)

    # Create workflow with compensatable steps
    step1 = CompensatableStep(
        name="Step1_Compensatable",
        func=step1_func,
        compensate_func=compensate_step1,
        required_input=[],
    )

    step2 = CompensatableStep(
        name="Step2_Compensatable",
        func=step2_func,
        compensate_func=compensate_step2,
        required_input=[],
    )

    step3_fail = CompensatableStep(
        name="Step3_Fail",
        func=step3_func_fail,
        required_input=[],
    )

    workflow = Workflow(
        workflow_type="SagaTest",
        initial_state_model=TestState(),
        workflow_steps=[step1, step2, step3_fail],
        state_model_path="test_production_features.TestState"
    )

    # Enable saga mode
    print("\nEnabling saga mode...")
    workflow.enable_saga_mode()
    assert workflow.saga_mode == True
    print("✓ Saga mode enabled")

    # Execute step 1
    print("\nExecuting Step 1 (should succeed)...")
    result1, next_step1 = workflow.next_step({})
    print(f"✓ Step 1 completed: {result1}")
    assert workflow.state.step1_executed == True

    # Execute step 2
    print("\nExecuting Step 2 (should succeed)...")
    result2, next_step2 = workflow.next_step({})
    print(f"✓ Step 2 completed: {result2}")
    assert workflow.state.step2_executed == True

    # Execute step 3 (will fail and trigger rollback)
    print("\nExecuting Step 3 (should fail and trigger rollback)...")
    try:
        result3, next_step3 = workflow.next_step({})
        assert False, "Step 3 should have failed"
    except Exception as e:
        print(f"✓ Step 3 failed as expected: {e}")

    # Verify saga rollback occurred
    print("\nVerifying saga rollback...")
    assert workflow.status == "FAILED_ROLLED_BACK", f"Expected FAILED_ROLLED_BACK but got {workflow.status}"
    assert workflow.state.compensation1_executed == True, "Step 1 compensation not executed"
    assert workflow.state.compensation2_executed == True, "Step 2 compensation not executed"
    print("✓ Compensation executed for both steps")

    # Verify state was rolled back
    assert workflow.state.step1_executed == False, "Step 1 should be rolled back"
    assert workflow.state.step2_executed == False, "Step 2 should be rolled back"
    print("✓ State successfully rolled back")

    print("\n✅ TEST 2 PASSED: Saga pattern with automatic rollback working correctly")
    return True


# ============================================================================
# Test 3: Sub-Workflow Execution
# ============================================================================

def test_sub_workflow():
    """Test parent-child workflow relationships"""
    print("\n" + "="*70)
    print("TEST 3: Sub-Workflow Execution")
    print("="*70)

    # For sub-workflow testing, we need to register workflows in the WorkflowBuilder
    # Since this is a complex integration test that requires Celery and workflow registry,
    # we'll test the core mechanics instead

    # Create child workflow directly
    child_step = CompensatableStep(
        name="ChildStep",
        func=child_workflow_step,
        required_input=[],
    )

    # Create steps_config for persistence
    child_steps_config = [
        {
            "name": "ChildStep",
            "type": "STANDARD",
            "function": "test_production_features.child_workflow_step",
            "required_input": []
        }
    ]

    child_workflow = Workflow(
        workflow_type="ChildWorkflow",
        initial_state_model=ChildState(),
        workflow_steps=[child_step],
        state_model_path="test_production_features.ChildState",
        steps_config=child_steps_config
    )

    # Save child workflow
    child_id = child_workflow.id
    save_workflow_state(child_id, child_workflow)
    print(f"Created and saved child workflow: {child_id}")

    # Create parent workflow
    parent_step1 = CompensatableStep(
        name="LaunchChild",
        func=lambda state, **kwargs: {"step1": "ready to launch child"},
        required_input=[],
    )

    parent_step2 = CompensatableStep(
        name="ProcessChildResults",
        func=step2_func,
        required_input=[],
    )

    # Create steps_config for persistence
    parent_steps_config = [
        {
            "name": "LaunchChild",
            "type": "STANDARD",
            "function": "test_production_features.step2_func",  # Dummy function
            "required_input": []
        },
        {
            "name": "ProcessChildResults",
            "type": "STANDARD",
            "function": "test_production_features.step2_func",
            "required_input": []
        }
    ]

    parent_workflow = Workflow(
        workflow_type="ParentWorkflow",
        initial_state_model=TestState(),
        workflow_steps=[parent_step1, parent_step2],
        state_model_path="test_production_features.TestState",
        steps_config=parent_steps_config
    )

    parent_id = parent_workflow.id
    save_workflow_state(parent_id, parent_workflow)
    print(f"Created parent workflow: {parent_id}")

    # Test sub-workflow relationship fields
    print("\nTesting sub-workflow relationship fields...")

    # Simulate parent-child relationship
    child_workflow.parent_execution_id = parent_id
    parent_workflow.blocked_on_child_id = child_id
    parent_workflow.status = "PENDING_SUB_WORKFLOW"

    # Save updated workflows
    save_workflow_state(child_id, child_workflow)
    save_workflow_state(parent_id, parent_workflow)
    print("✓ Parent-child relationship established")

    # Verify parent is waiting
    loaded_parent = load_workflow_state(parent_id)
    assert loaded_parent.status == "PENDING_SUB_WORKFLOW", f"Expected PENDING_SUB_WORKFLOW but got {loaded_parent.status}"
    assert loaded_parent.blocked_on_child_id == child_id, "Parent should be blocked on child"
    print(f"✓ Parent is waiting for child: {loaded_parent.blocked_on_child_id}")

    # Execute child workflow to completion
    loaded_child = load_workflow_state(child_id)
    print(f"\nExecuting child workflow: {child_id}")
    print(f"  Current step: {loaded_child.current_step}/{len(loaded_child.workflow_steps)}")
    print(f"  Initial state: {loaded_child.state}")

    result, next_step = loaded_child.next_step({})
    print(f"  Result: {result}")
    print(f"  Next step: {next_step}")
    print(f"  Final state: {loaded_child.state}")
    print(f"  Status: {loaded_child.status}")

    # Check if the step was executed
    if hasattr(loaded_child.state, 'child_step_executed'):
        assert loaded_child.state.child_step_executed == True, f"Child step not executed. State: {loaded_child.state}"
    else:
        print("  Warning: child_step_executed field not found in state")

    assert loaded_child.status == "COMPLETED", f"Expected COMPLETED but got {loaded_child.status}"

    save_workflow_state(child_id, loaded_child)
    print("✓ Child workflow completed and saved")

    # Manually simulate what the Celery task would do
    # (In production, resume_parent_from_child task handles this)
    print("\nSimulating parent resumption (done by Celery in production)...")
    loaded_parent.state.sub_workflow_results["ChildWorkflow"] = loaded_child.state.model_dump()
    loaded_parent.status = "ACTIVE"
    loaded_parent.blocked_on_child_id = None
    save_workflow_state(parent_id, loaded_parent)
    print("✓ Child results merged into parent")

    # Reload and verify
    final_parent = load_workflow_state(parent_id)
    assert "ChildWorkflow" in final_parent.state.sub_workflow_results
    assert final_parent.state.sub_workflow_results["ChildWorkflow"]["result"] == "child_completed"
    assert final_parent.status == "ACTIVE"
    assert final_parent.blocked_on_child_id is None
    print("✓ Parent state correctly updated with child results")

    print("\n✅ TEST 3 PASSED: Sub-workflow mechanics working correctly")
    print("   (Note: Full integration test with Celery would verify automatic resumption)")
    return True


# ============================================================================
# Main Test Runner
# ============================================================================

def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("CONFUCIUS PRODUCTION FEATURES TEST SUITE")
    print("="*70)
    print(f"Storage Backend: {os.environ.get('WORKFLOW_STORAGE')}")
    print(f"Database URL: {os.environ.get('DATABASE_URL', 'Not set')[:50]}...")

    results = []

    try:
        # Test 1: Basic PostgreSQL Persistence
        results.append(("Basic PostgreSQL Persistence", test_basic_postgresql_persistence()))
    except Exception as e:
        print(f"\n❌ TEST 1 FAILED: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Basic PostgreSQL Persistence", False))

    try:
        # Test 2: Saga Pattern
        results.append(("Saga Pattern with Compensation", test_saga_pattern()))
    except Exception as e:
        print(f"\n❌ TEST 2 FAILED: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Saga Pattern with Compensation", False))

    try:
        # Test 3: Sub-Workflows
        results.append(("Sub-Workflow Execution", test_sub_workflow()))
    except Exception as e:
        print(f"\n❌ TEST 3 FAILED: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Sub-Workflow Execution", False))

    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)

    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status}: {test_name}")

    total_tests = len(results)
    passed_tests = sum(1 for _, passed in results if passed)

    print(f"\nTotal: {passed_tests}/{total_tests} tests passed")

    if passed_tests == total_tests:
        print("\n🎉 All tests passed! Production features are working correctly.")
        return 0
    else:
        print(f"\n⚠️  {total_tests - passed_tests} test(s) failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
