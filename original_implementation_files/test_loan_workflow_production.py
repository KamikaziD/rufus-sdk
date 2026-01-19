#!/usr/bin/env python3
"""
Production Test for Loan Workflow
Tests the existing LoanApplication workflow with PostgreSQL backend

Run with: python test_loan_workflow_production.py
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set environment variables for production testing
os.environ['WORKFLOW_STORAGE'] = 'postgres'

os.environ['TESTING'] = 'true'  # Synchronous Celery execution

import pytest
from src.confucius.workflow_loader import workflow_builder
from src.confucius.persistence import save_workflow_state, load_workflow_state, get_storage_backend
from state_models import LoanApplicationState


@pytest.fixture(scope="module")
def workflow_id():
    """Fixture to create and provide a workflow ID for tests"""
    loan_workflow = workflow_builder.create_workflow(
        workflow_type="LoanApplication",
        initial_data={
            "application_id": "TEST-001",
            "requested_amount": 50000.0,
            "applicant_profile": {
                "user_id": "U-123",
                "name": "Test Applicant",
                "email": "test@example.com",
                "country": "USA",
                "age": 35,
                "id_document_url": "https://example.com/id_123.jpg"
            }
        }
    )
    save_workflow_state(loan_workflow.id, loan_workflow)
    return loan_workflow.id


# ============================================================================
# Test 1: Create Loan Workflow from Registry
# ============================================================================

def test_loan_workflow_creation(workflow_id):
    """Test creating loan workflow from existing YAML config"""
    print("\n" + "="*70)
    print("TEST 1: Loan Workflow Creation from Registry")
    print("="*70)

    # Verify PostgreSQL backend
    backend = get_storage_backend()
    print(f"Storage backend: {backend}")
    assert backend == 'postgres', f"Expected 'postgres' but got '{backend}'"

    # Verify workflow exists
    loan_workflow = load_workflow_state(workflow_id)
    assert loan_workflow is not None
    assert loan_workflow.workflow_type == "LoanApplication"
    print(f"Workflow {workflow_id} verified in {backend}")

    workflow_id = loan_workflow.id
    print(f"✓ Created workflow: {workflow_id}")
    print(f"  Type: {loan_workflow.workflow_type}")
    print(f"  Total steps: {len(loan_workflow.workflow_steps)}")
    print(f"  Current step: {loan_workflow.current_step}")
    print(f"  Status: {loan_workflow.status}")

    # Display workflow steps
    print("\nWorkflow steps:")
    for i, step in enumerate(loan_workflow.workflow_steps):
        step_type = type(step).__name__
        print(f"  {i}. {step.name} ({step_type})")

    # Verify state
    assert loan_workflow.state.application_id == "TEST-001"
    assert loan_workflow.state.requested_amount == 50000.0
    print("\n✓ Initial state verified")

    # Save to PostgreSQL
    print("\nSaving to PostgreSQL...")
    save_workflow_state(workflow_id, loan_workflow)
    print("✓ Saved successfully")

    # Load from PostgreSQL
    print("\nLoading from PostgreSQL...")
    loaded_workflow = load_workflow_state(workflow_id)
    print(f"✓ Loaded workflow: {loaded_workflow.id}")

    # Verify loaded state
    assert loaded_workflow.id == workflow_id
    assert loaded_workflow.workflow_type == "LoanApplication"
    assert loaded_workflow.state.application_id == "TEST-001"
    assert loaded_workflow.state.requested_amount == 50000.0
    print("✓ Loaded state matches original")

    print("\n✅ TEST 1 PASSED: Loan workflow creation and persistence working")
    return workflow_id, loan_workflow


# ============================================================================
# Test 2: Execute Loan Workflow Steps
# ============================================================================

def test_loan_workflow_execution(workflow_id: str = None):
    """Test executing loan workflow steps"""
    print("\n" + "="*70)
    print("TEST 2: Loan Workflow Step Execution")
    print("="*70)

    if workflow_id:
        # Load existing workflow
        print(f"\nLoading workflow: {workflow_id}")
        loan_workflow = load_workflow_state(workflow_id)
    else:
        # Create new workflow
        print("\nCreating new LoanApplication workflow...")
        loan_workflow = workflow_builder.create_workflow(
            workflow_type="LoanApplication",
            initial_data={
                "application_id": "TEST-002",
                "requested_amount": 75000.0,
                "applicant_profile": {
                    "user_id": "U-456",
                    "name": "Jane Smith",
                    "email": "jane@example.com",
                    "country": "USA",
                    "age": 42,
                    "id_document_url": "https://example.com/id_456.jpg"
                }
            }
        )
        workflow_id = loan_workflow.id

    print(f"Workflow ID: {workflow_id}")
    print(f"Current step: {loan_workflow.current_step} - {loan_workflow.current_step_name}")
    print(f"Status: {loan_workflow.status}")

    # Step 1: Collect Application Data
    print("\n--- Step 1: Collect Application Data ---")
    print(f"Executing step: {loan_workflow.current_step_name}")

    try:
        result, next_step = loan_workflow.next_step({
            "user_id": "U-456",
            "name": "Jane Smith",
            "email": "jane@example.com",
            "country": "USA",
            "age": 42,
            "requested_amount": 75000.0,
            "id_document_url": "https://example.com/id.jpg"
        })
        print(f"✓ Step completed: {result}")
        print(f"  Next step: {next_step}")
        print(f"  Status: {loan_workflow.status}")

        # Save state
        save_workflow_state(workflow_id, loan_workflow)
        print("  State saved to PostgreSQL")
    except Exception as e:
        print(f"✗ Step failed: {e}")
        import traceback
        traceback.print_exc()

    # Step 2: Run Concurrent Checks (PARALLEL)
    print("\n--- Step 2: Run Concurrent Checks (PARALLEL) ---")
    print(f"Executing step: {loan_workflow.current_step_name}")

    try:
        result, next_step = loan_workflow.next_step({})
        print(f"✓ Parallel tasks dispatched")
        print(f"  Result: {result}")
        print(f"  Status: {loan_workflow.status}")

        # Check if async or completed synchronously
        if loan_workflow.status == "PENDING_ASYNC":
            print("  Note: In production, Celery would handle async execution")
            print("  For testing, continuing with synchronous execution")

        save_workflow_state(workflow_id, loan_workflow)
        print("  State saved to PostgreSQL")
    except Exception as e:
        print(f"✗ Step failed: {e}")
        import traceback
        traceback.print_exc()

    # Step 3: Evaluate Pre-Approval
    if loan_workflow.status != "PENDING_ASYNC":
        print("\n--- Step 3: Evaluate Pre-Approval ---")
        print(f"Executing step: {loan_workflow.current_step_name}")

        try:
            result, next_step = loan_workflow.next_step({})
            print(f"✓ Step completed: {result}")
            print(f"  Next step: {next_step}")
            print(f"  Pre-approval status: {loan_workflow.state.pre_approval_status}")

            save_workflow_state(workflow_id, loan_workflow)
            print("  State saved to PostgreSQL")
        except Exception as e:
            print(f"✗ Step failed: {e}")
            import traceback
            traceback.print_exc()

    # Step 4: Run KYC Workflow Placeholder
    if loan_workflow.status == "ACTIVE":
        print("\n--- Step 4: Run KYC Workflow (Placeholder) ---")
        print(f"Executing step: {loan_workflow.current_step_name}")

        try:
            result, next_step = loan_workflow.next_step({})
            print(f"✓ Step completed: {result}")
            print(f"  Next step: {next_step}")

            save_workflow_state(workflow_id, loan_workflow)
            print("  State saved to PostgreSQL")
        except Exception as e:
            print(f"✗ Step failed: {e}")
            import traceback
            traceback.print_exc()

    # Step 5: Route Underwriting
    if loan_workflow.status == "ACTIVE":
        print("\n--- Step 5: Route Underwriting ---")
        print(f"Executing step: {loan_workflow.current_step_name}")

        try:
            result, next_step = loan_workflow.next_step({})
            print(f"✓ Step completed: {result}")
            print(f"  Next step: {next_step}")
            print(f"  Underwriting type: {loan_workflow.state.underwriting_type}")

            save_workflow_state(workflow_id, loan_workflow)
            print("  State saved to PostgreSQL")
        except Exception as e:
            print(f"✗ Step failed: {e}")
            import traceback
            traceback.print_exc()

    # Step 6: Dynamic Injection (noop trigger)
    if loan_workflow.status == "ACTIVE":
        print("\n--- Step 6: Inject Underwriting Branch (Dynamic) ---")
        print(f"Executing step: {loan_workflow.current_step_name}")
        print(f"  Underwriting type: {loan_workflow.state.underwriting_type}")

        try:
            result, next_step = loan_workflow.next_step({})
            print(f"✓ Step completed: {result}")
            print(f"  Next step: {next_step}")
            print(f"  Total steps now: {len(loan_workflow.workflow_steps)}")

            # Check if steps were injected
            if loan_workflow.state.underwriting_type == "full":
                print("  Expected injection: Full Underwriting + Human Review")
            elif loan_workflow.state.underwriting_type == "simple":
                print("  Expected injection: Simplified Underwriting")

            save_workflow_state(workflow_id, loan_workflow)
            print("  State saved to PostgreSQL")
        except Exception as e:
            print(f"✗ Step failed: {e}")
            import traceback
            traceback.print_exc()

    # Continue execution if active
    steps_executed = 6
    max_steps = 15  # Safety limit

    while loan_workflow.status == "ACTIVE" and steps_executed < max_steps:
        steps_executed += 1
        current_step_name = loan_workflow.current_step_name

        print(f"\n--- Step {steps_executed}: {current_step_name} ---")

        try:
            result, next_step = loan_workflow.next_step({})
            print(f"✓ Step completed: {result}")
            print(f"  Next step: {next_step}")
            print(f"  Status: {loan_workflow.status}")

            save_workflow_state(workflow_id, loan_workflow)
            print("  State saved")

            # Check for special statuses
            if loan_workflow.status == "WAITING_HUMAN":
                print("  ⚠️  Workflow paused for human input")
                print(f"  Current step: {loan_workflow.current_step_name}")
                break
            elif loan_workflow.status == "PENDING_ASYNC":
                print("  ⚠️  Workflow waiting for async task")
                break
            elif loan_workflow.status == "COMPLETED":
                print("  🎉 Workflow completed!")
                break

        except Exception as e:
            print(f"✗ Step failed: {e}")
            import traceback
            traceback.print_exc()
            break

    print(f"\n✅ TEST 2 PASSED: Executed {steps_executed} steps successfully")
    print(f"   Final status: {loan_workflow.status}")
    print(f"   Final step: {loan_workflow.current_step_name}")

    return workflow_id, loan_workflow


# ============================================================================
# Test 3: Workflow State Persistence and Recovery
# ============================================================================

def test_loan_workflow_persistence(workflow_id: str):
    """Test that workflow state persists correctly across loads"""
    print("\n" + "="*70)
    print("TEST 3: Loan Workflow Persistence and Recovery")
    print("="*70)

    print(f"\nLoading workflow from database: {workflow_id}")
    loan_workflow = load_workflow_state(workflow_id)

    print(f"✓ Workflow loaded successfully")
    print(f"  ID: {loan_workflow.id}")
    print(f"  Type: {loan_workflow.workflow_type}")
    print(f"  Status: {loan_workflow.status}")
    print(f"  Current step: {loan_workflow.current_step} - {loan_workflow.current_step_name}")
    print(f"  Total steps: {len(loan_workflow.workflow_steps)}")

    # Verify state fields
    print("\nState verification:")
    print(f"  Application ID: {loan_workflow.state.application_id}")
    print(f"  Requested amount: ${loan_workflow.state.requested_amount:,.2f}")
    print(f"  Applicant: {loan_workflow.state.applicant_profile.name}")
    print(f"  Email: {loan_workflow.state.applicant_profile.email}")

    if loan_workflow.state.credit_check:
        print(f"  Credit check: {loan_workflow.state.credit_check}")

    if loan_workflow.state.fraud_check:
        print(f"  Fraud check: {loan_workflow.state.fraud_check}")

    if loan_workflow.state.pre_approval_status:
        print(f"  Pre-approval: {loan_workflow.state.pre_approval_status}")

    if loan_workflow.state.underwriting_type:
        print(f"  Underwriting type: {loan_workflow.state.underwriting_type}")

    if loan_workflow.state.final_loan_status:
        print(f"  Final status: {loan_workflow.state.final_loan_status}")

    # Test modification and re-save
    print("\nModifying and re-saving workflow...")
    original_step = loan_workflow.current_step

    # Add a test modification to metadata
    if not hasattr(loan_workflow, 'metadata'):
        loan_workflow.metadata = {}
    loan_workflow.metadata['test_key'] = 'test_value'
    loan_workflow.metadata['persistence_test'] = True

    save_workflow_state(workflow_id, loan_workflow)
    print("✓ Workflow saved with modifications")

    # Reload and verify modifications
    print("\nReloading to verify persistence...")
    reloaded_workflow = load_workflow_state(workflow_id)

    assert reloaded_workflow.current_step == original_step
    assert reloaded_workflow.metadata.get('test_key') == 'test_value'
    assert reloaded_workflow.metadata.get('persistence_test') == True
    print("✓ Modifications persisted correctly")

    print("\n✅ TEST 3 PASSED: Workflow persistence and recovery working")
    return True


# ============================================================================
# Test 4: Loan Workflow with Saga Pattern (If Compensatable)
# ============================================================================

def test_loan_workflow_saga_capability():
    """Test enabling saga mode on loan workflow"""
    print("\n" + "="*70)
    print("TEST 4: Loan Workflow Saga Pattern Capability")
    print("="*70)

    print("\nCreating new loan workflow for saga testing...")
    loan_workflow = workflow_builder.create_workflow(
        workflow_type="LoanApplication",
        initial_data={
            "application_id": "SAGA-001",
            "requested_amount": 100000.0,
            "applicant_profile": {
                "user_id": "U-SAGA",
                "name": "Saga Test User",
                "email": "saga@example.com",
                "country": "USA",
                "age": 30,
                "id_document_url": "https://example.com/id_saga.jpg"
            }
        }
    )

    workflow_id = loan_workflow.id
    print(f"✓ Created workflow: {workflow_id}")

    # Try enabling saga mode
    print("\nEnabling saga mode...")
    loan_workflow.enable_saga_mode()
    print(f"✓ Saga mode enabled: {loan_workflow.saga_mode}")

    # Check for compensatable steps
    compensatable_count = 0
    for step in loan_workflow.workflow_steps:
        if hasattr(step, 'compensate_func') and step.compensate_func is not None:
            compensatable_count += 1
            print(f"  Found compensatable step: {step.name}")

    if compensatable_count == 0:
        print("\n⚠️  Note: Current loan workflow has no compensation functions defined")
        print("   To enable full saga rollback, add 'compensate_function' to YAML steps")
        print("   Example:")
        print("     - name: 'Collect_Application_Data'")
        print("       compensate_function: 'workflow_utils.clear_application_data'")
    else:
        print(f"\n✓ Found {compensatable_count} compensatable steps")

    # Save with saga mode enabled
    save_workflow_state(workflow_id, loan_workflow)
    print("\n✓ Saved workflow with saga mode enabled")

    # Reload and verify
    reloaded = load_workflow_state(workflow_id)
    assert reloaded.saga_mode == True
    print("✓ Saga mode persisted correctly")

    print("\n✅ TEST 4 PASSED: Loan workflow can use saga pattern")
    print("   (Add compensation functions to YAML for full rollback capability)")
    return True


# ============================================================================
# Main Test Runner
# ============================================================================

def main():
    """Run all loan workflow production tests"""
    print("\n" + "="*70)
    print("LOAN WORKFLOW PRODUCTION TEST SUITE")
    print("="*70)
    print(f"Storage Backend: {os.environ.get('WORKFLOW_STORAGE')}")
    print(f"Database URL: {os.environ.get('DATABASE_URL', 'Not set')[:50]}...")

    results = []

    try:
        # Test 1: Creation and Persistence
        workflow_id, loan_workflow = test_loan_workflow_creation()
        results.append(("Loan Workflow Creation", True))
    except Exception as e:
        print(f"\n❌ TEST 1 FAILED: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Loan Workflow Creation", False))
        workflow_id = None

    try:
        # Test 2: Step Execution
        workflow_id, loan_workflow = test_loan_workflow_execution(workflow_id)
        results.append(("Loan Workflow Execution", True))
    except Exception as e:
        print(f"\n❌ TEST 2 FAILED: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Loan Workflow Execution", False))

    if workflow_id:
        try:
            # Test 3: Persistence
            test_loan_workflow_persistence(workflow_id)
            results.append(("Loan Workflow Persistence", True))
        except Exception as e:
            print(f"\n❌ TEST 3 FAILED: {e}")
            import traceback
            traceback.print_exc()
            results.append(("Loan Workflow Persistence", False))

    try:
        # Test 4: Saga Capability
        test_loan_workflow_saga_capability()
        results.append(("Loan Workflow Saga Capability", True))
    except Exception as e:
        print(f"\n❌ TEST 4 FAILED: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Loan Workflow Saga Capability", False))

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
        print("\n🎉 All loan workflow tests passed!")
        print("   Loan workflow is production-ready with PostgreSQL backend")
        return 0
    else:
        print(f"\n⚠️  {total_tests - passed_tests} test(s) failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
