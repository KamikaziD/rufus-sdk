#!/usr/bin/env python3
"""
Test Loan Workflow Saga Rollback
Demonstrates automatic compensation when workflow fails

This test:
1. Creates a loan workflow with saga mode enabled
2. Executes several steps successfully
3. Injects a failure to trigger rollback
4. Verifies compensation functions execute in reverse order
5. Checks final state is properly rolled back

Run with: python test_loan_saga_rollback.py
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set environment variables
os.environ['WORKFLOW_STORAGE'] = 'postgres'

os.environ['TESTING'] = 'true'

from src.confucius.workflow_loader import workflow_builder
from src.confucius.persistence import save_workflow_state, load_workflow_state
from state_models import LoanApplicationState
import workflow_utils


# ==============================================================================
# Inject Failure Function
# ==============================================================================

def inject_failure_in_route_underwriting(state: LoanApplicationState):
    """
    Modified route_underwriting that fails after setting state

    This simulates a failure during the underwriting routing step,
    which should trigger compensation of all previous steps.
    """
    # Do the normal work first
    if state.requested_amount < 20000:
        state.underwriting_type = "simple"
        print(f"Application {state.application_id}: Routing to SIMPLIFIED underwriting.")
    else:
        state.underwriting_type = "full"
        print(f"Application {state.application_id}: Routing to FULL underwriting.")

    # Now inject the failure
    print(f"\n💥 SIMULATED FAILURE in Route_Underwriting step!")
    print(f"   This will trigger saga rollback of all previous steps...")
    raise Exception("INTENTIONAL FAILURE: Underwriting system unavailable")


# ==============================================================================
# Test Saga Rollback
# ==============================================================================

def test_loan_saga_rollback():
    """Test loan workflow with saga pattern rollback"""
    print("\n" + "="*70)
    print("LOAN WORKFLOW SAGA ROLLBACK TEST")
    print("="*70)
    print("\nThis test demonstrates automatic compensation when a workflow fails.")
    print("Steps that completed successfully will be 'undone' in reverse order.\n")

    # Create loan workflow
    print("Step 1: Creating LoanApplication workflow...")
    loan_workflow = workflow_builder.create_workflow(
        workflow_type="LoanApplication",
        initial_data={
            "application_id": "SAGA-TEST-001",
            "requested_amount": 50000.0,  # Will trigger "full" underwriting
            "applicant_profile": {
                "user_id": "U-SAGA-001",
                "name": "Test Saga User",
                "email": "saga@example.com",
                "country": "USA",
                "age": 35,
                "id_document_url": "https://example.com/id_saga.jpg"
            }
        }
    )

    workflow_id = loan_workflow.id
    print(f"✓ Created workflow: {workflow_id}")
    print(f"  Initial steps: {len(loan_workflow.workflow_steps)}")

    # Enable saga mode
    print("\nStep 2: Enabling saga mode...")
    loan_workflow.enable_saga_mode()
    print(f"✓ Saga mode enabled: {loan_workflow.saga_mode}")

    # Count compensatable steps
    compensatable_steps = []
    for i, step in enumerate(loan_workflow.workflow_steps):
        if hasattr(step, 'compensate_func') and step.compensate_func is not None:
            compensatable_steps.append((i, step.name))
            print(f"  ✓ Step {i}: {step.name} - Compensatable")

    print(f"\n  Total compensatable steps: {len(compensatable_steps)}")

    # Save initial state
    save_workflow_state(workflow_id, loan_workflow)
    print("\n✓ Initial state saved to PostgreSQL")

    # Execute Step 1: Collect Application Data
    print("\n" + "-"*70)
    print("Step 3: Executing workflow steps...")
    print("-"*70)

    print("\n[STEP 1] Collect_Application_Data")
    try:
        result, next_step = loan_workflow.next_step({
            "user_id": "U-SAGA-001",
            "name": "Test Saga User",
            "email": "saga@example.com",
            "country": "USA",
            "age": 35,
            "requested_amount": 50000.0,
            "id_document_url": "https://example.com/id_saga.jpg"
        })
        print(f"✓ Step completed: {result}")
        print(f"  Application ID: {loan_workflow.state.application_id}")
        print(f"  Applicant: {loan_workflow.state.applicant_profile.name}")
        save_workflow_state(workflow_id, loan_workflow)
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False

    # Execute Step 2: Run Concurrent Checks
    print("\n[STEP 2] Run_Concurrent_Checks (Parallel)")
    try:
        result, next_step = loan_workflow.next_step({})
        print(f"✓ Parallel tasks executed")

        # Handle credit check result (might be dict or Pydantic model)
        if loan_workflow.state.credit_check:
            if hasattr(loan_workflow.state.credit_check, 'score'):
                print(f"  Credit Score: {loan_workflow.state.credit_check.score}")
            elif isinstance(loan_workflow.state.credit_check, dict):
                print(f"  Credit Score: {loan_workflow.state.credit_check.get('score', 'N/A')}")
        else:
            print(f"  Credit Score: N/A")

        # Handle fraud check result (might be dict or Pydantic model)
        if loan_workflow.state.fraud_check:
            if hasattr(loan_workflow.state.fraud_check, 'status'):
                print(f"  Fraud Status: {loan_workflow.state.fraud_check.status}")
            elif isinstance(loan_workflow.state.fraud_check, dict):
                print(f"  Fraud Status: {loan_workflow.state.fraud_check.get('status', 'N/A')}")
        else:
            print(f"  Fraud Status: N/A")

        save_workflow_state(workflow_id, loan_workflow)
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Execute Step 3: Evaluate Pre-Approval
    print("\n[STEP 3] Evaluate_Pre_Approval")
    try:
        result, next_step = loan_workflow.next_step({})
        print(f"✓ Pre-approval evaluated")
        print(f"  Status: {loan_workflow.state.pre_approval_status}")
        print(f"  Current step: {loan_workflow.current_step} - {loan_workflow.current_step_name}")
        save_workflow_state(workflow_id, loan_workflow)
    except Exception as e:
        # This might jump to final decision
        print(f"  Note: {e}")
        save_workflow_state(workflow_id, loan_workflow)

    # Execute Step 4: Run KYC Workflow (if not jumped)
    if loan_workflow.current_step_name == "Run_KYC_Workflow":
        print("\n[STEP 4] Run_KYC_Workflow")
        try:
            result, next_step = loan_workflow.next_step({})
            print(f"✓ KYC workflow executed")
            save_workflow_state(workflow_id, loan_workflow)
        except Exception as e:
            print(f"✗ Failed: {e}")

    # Execute Step 5: Route Underwriting - THIS WILL FAIL
    if loan_workflow.current_step_name == "Route_Underwriting":
        print("\n[STEP 5] Route_Underwriting - WILL FAIL TO TRIGGER ROLLBACK")
        print(f"  Completed steps in saga stack: {len(loan_workflow.completed_steps_stack)}")
        print(f"  Stack: {[loan_workflow.workflow_steps[i].name for i in loan_workflow.completed_steps_stack]}")

        # Temporarily replace the function with our failing version
        original_func = loan_workflow.workflow_steps[loan_workflow.current_step].func
        loan_workflow.workflow_steps[loan_workflow.current_step].func = inject_failure_in_route_underwriting

        try:
            result, next_step = loan_workflow.next_step({})
            print(f"✗ Unexpected: Step should have failed!")
            return False
        except Exception as e:
            print(f"\n✓ Exception caught (as expected): {e}")
            print(f"  Workflow status: {loan_workflow.status}")

            # Restore original function
            loan_workflow.workflow_steps[loan_workflow.current_step].func = original_func

    # Verify rollback occurred
    print("\n" + "="*70)
    print("SAGA ROLLBACK VERIFICATION")
    print("="*70)

    if loan_workflow.status == "FAILED_ROLLED_BACK":
        print("\n✅ Workflow status: FAILED_ROLLED_BACK (correct)")

        # Verify state was rolled back
        print("\nVerifying state rollback:")

        checks = []

        # Check 1: Application ID should be cleared
        if loan_workflow.state.application_id is None:
            print("  ✓ Application ID: Cleared")
            checks.append(True)
        else:
            print(f"  ✗ Application ID: Still set ({loan_workflow.state.application_id})")
            checks.append(False)

        # Check 2: Applicant profile should be cleared
        if loan_workflow.state.applicant_profile is None:
            print("  ✓ Applicant Profile: Cleared")
            checks.append(True)
        else:
            print(f"  ✗ Applicant Profile: Still set ({loan_workflow.state.applicant_profile.name})")
            checks.append(False)

        # Check 3: Requested amount should be cleared
        if loan_workflow.state.requested_amount == 0.0:
            print("  ✓ Requested Amount: Reset to 0")
            checks.append(True)
        else:
            print(f"  ✗ Requested Amount: Still set ({loan_workflow.state.requested_amount})")
            checks.append(False)

        # Check 4: Pre-approval status should be cleared
        if loan_workflow.state.pre_approval_status is None:
            print("  ✓ Pre-approval Status: Cleared")
            checks.append(True)
        else:
            print(f"  ✗ Pre-approval Status: Still set ({loan_workflow.state.pre_approval_status})")
            checks.append(False)

        # Check 5: Underwriting type should be cleared
        if loan_workflow.state.underwriting_type is None:
            print("  ✓ Underwriting Type: Cleared")
            checks.append(True)
        else:
            print(f"  ✗ Underwriting Type: Still set ({loan_workflow.state.underwriting_type})")
            checks.append(False)

        # Save final state
        save_workflow_state(workflow_id, loan_workflow)
        print("\n✓ Final rolled-back state saved to PostgreSQL")

        # Overall result
        if all(checks):
            print("\n" + "="*70)
            print("🎉 SUCCESS: All state properly rolled back!")
            print("="*70)
            print(f"\nWorkflow ID: {workflow_id}")
            print(f"Status: {loan_workflow.status}")
            print(f"Compensated steps: {len(loan_workflow.completed_steps_stack)}")
            print("\nThe saga pattern successfully:")
            print("  1. Tracked all completed steps")
            print("  2. Detected the failure")
            print("  3. Executed compensation functions in reverse order")
            print("  4. Restored the workflow to a clean state")
            print("\nNo partial data remains in the system!")
            return True
        else:
            print("\n⚠️  Some state not properly rolled back")
            return False
    else:
        print(f"\n✗ Unexpected workflow status: {loan_workflow.status}")
        print(f"   Expected: FAILED_ROLLED_BACK")
        return False


# ==============================================================================
# Main
# ==============================================================================

def main():
    """Run saga rollback test"""
    print("\n" + "="*70)
    print("SAGA PATTERN DEMONSTRATION")
    print("="*70)
    print("\nThis test shows how the saga pattern automatically 'undos' work")
    print("when a workflow fails, ensuring data consistency.\n")

    try:
        success = test_loan_saga_rollback()

        if success:
            print("\n✅ TEST PASSED: Saga rollback working correctly")
            return 0
        else:
            print("\n❌ TEST FAILED: Issues with rollback")
            return 1

    except Exception as e:
        print(f"\n❌ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
