import time
from typing import Any
from rufus.models import StepContext
from state_models import KYCState

# NOTE: Celery task decorators commented out for sync execution
# For Celery execution, uncomment @celery_app.task decorators

# --- KYC Process Steps ---

# @celery_app.task  # Commented out for sync execution
def verify_id_agent(state: dict, context: StepContext):
    """Child AI Agent: Verifies ID document."""
    # state is a dict here because it comes from Celery task payload
    user_name = state.get('user_name', 'Unknown')
    doc_url = state.get('id_document_url', 'Unknown')
    print(f"  KYC: Verifying ID for {user_name} from {doc_url}...")
    time.sleep(0.5)  # Reduced for sync testing (was 2)
    verified = True if "valid" in doc_url else False
    # Return dict update
    return {"id_verified": verified, "kyc_message": "ID verification completed."}

# @celery_app.task  # Commented out for sync execution
def sanctions_screen_agent(state: dict, context: StepContext):
    """Child AI Agent: Runs sanctions screening."""
    user_name = state.get('user_name', 'Unknown')
    print(f"  KYC: Running sanctions screen for {user_name}...")
    time.sleep(0.5)  # Reduced for sync testing (was 1.5)
    passed = True if "suspect" not in user_name else False
    return {"sanctions_screen_passed": passed, "kyc_message": "Sanctions screen completed."}

def generate_kyc_report(state: KYCState, context: StepContext):
    """Child Step: Generates final KYC report."""
    print(f"  KYC: Generating report for {state.user_name}...")
    kyc_status = "APPROVED" if state.id_verified and state.sanctions_screen_passed else "REJECTED"
    state.kyc_overall_status = kyc_status
    state.kyc_report_summary = f"ID: {state.id_verified}, Sanctions: {state.sanctions_screen_passed}, Overall: {kyc_status}"
    return {"kyc_overall_status": kyc_status, "kyc_report_summary": state.kyc_report_summary}
