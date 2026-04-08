import time
import datetime
from typing import Optional, Any
from ruvon.models import WorkflowJumpDirective, WorkflowPauseDirective, StartSubWorkflowDirective, StepContext
from state_models import LoanApplicationState, UserProfileState, HumanReviewDecision, KYCState

# NOTE: Celery task decorators commented out for sync execution
# For Celery execution, uncomment @celery_app.task decorators and import celery_app
# from celery import Celery
# celery_app = Celery('loan_workflow')

# --- Loan Application Steps ---

def initialize_application(state: LoanApplicationState, context: StepContext):
    """Initial step: Generates an application ID and confirms data is loaded."""
    if not state.applicant_profile or not state.requested_amount:
        raise ValueError("Applicant profile and requested amount must be provided in initial_data.")
    state.application_id = f"LOAN-{int(time.time())}" # Generate a simple ID
    print(f"Application {state.application_id} initialized for {state.applicant_profile.name}.")
    return {"message": "Application initialized."}

# @celery_app.task  # Commented out for sync execution
def run_credit_check_agent(state: dict, context: StepContext):
    """AI Agent: Simulates calling a Credit Score microservice."""
    print(f"Running credit check for {state['applicant_profile']['name']}...")
    time.sleep(0.5) # Reduced for sync testing (was 3)
    score = 780 if state['applicant_profile']['age'] >= 25 else 620
    risk = "low" if score > 700 else "medium"
    return {"credit_check": {"score": score, "report_id": "CR" + str(score), "risk_level": risk}}

# @celery_app.task  # Commented out for sync execution
def run_fraud_detection_agent(state: dict, context: StepContext):
    """AI Agent: Simulates calling a Fraud Detection microservice."""

    print(f"Running fraud detection for {state['applicant_profile']['name']}...")
    time.sleep(0.5) # Reduced for sync testing (was 2)
    status = "CLEAN" if state['applicant_profile']['country'] != "ZA" else "HIGH_RISK"
    score = 0.1 if status == "CLEAN" else 0.9
    return {"fraud_check": {"status": status, "score": score, "reason": "High IP risk" if status == "HIGH_RISK" else None}}

def evaluate_pre_approval(state: LoanApplicationState, context: StepContext):
    """Conditional Branching: Evaluates pre-approval based on async agent results."""
    print(f"Evaluating pre-approval for {state.application_id}...")
    if not state.credit_check or not state.fraud_check:
        raise ValueError("Missing credit or fraud check results for pre-approval.")

    # Handle both dict and Pydantic model for credit_check
    if isinstance(state.credit_check, dict):
        credit_score = state.credit_check.get('score', 0)
    else:
        credit_score = state.credit_check.score

    # Handle both dict and Pydantic model for fraud_check
    if isinstance(state.fraud_check, dict):
        fraud_status = state.fraud_check.get('status', 'UNKNOWN')
    else:
        fraud_status = state.fraud_check.status

    if credit_score > 700 and fraud_status == "CLEAN":
        state.pre_approval_status = "FAST_TRACK_APPROVED"
        print(f"Application {state.application_id}: Fast-track approved. Bypassing detailed review.")
        raise WorkflowJumpDirective(target_step_name="Generate_Final_Decision")
    elif credit_score < 600 or fraud_status == "HIGH_RISK":
        state.pre_approval_status = "REJECTED_AUTOMATIC"
        print(f"Application {state.application_id}: Rejected automatically.")
        raise WorkflowJumpDirective(target_step_name="Generate_Final_Decision")
    else:
        state.pre_approval_status = "PENDING_DETAILED_REVIEW"
        print(f"Application {state.application_id}: Needs detailed review.")
        return {"pre_approval_decision": state.pre_approval_status}

def route_underwriting(state: LoanApplicationState, context: StepContext):
    """Sets the underwriting type based on the requested loan amount."""
    if state.requested_amount < 20000:
        state.underwriting_type = "simple"
        print(f"Application {state.application_id}: Routing to SIMPLIFIED underwriting.")
    else:
        state.underwriting_type = "full"
        print(f"Application {state.application_id}: Routing to FULL underwriting.")
    return {"underwriting_type": state.underwriting_type}

# @celery_app.task  # Commented out for sync execution
def run_full_underwriting_agent(state: dict, context: StepContext):
    """AI Agent: Simulates a complex, long-running underwriting microservice."""
    print(f"Running full underwriting for {state['application_id']}...")
    time.sleep(1) # Reduced for sync testing (was 7)
    risk_score = state['requested_amount'] / (state['applicant_profile']['age'] * state['credit_check']['score']) if state.get('credit_check') else 0.5
    recommendation = "APPROVE" if risk_score < 0.005 else "REJECT"
    return {"underwriting_result": {"risk_score": risk_score, "recommendation": recommendation, "detailed_report_url": f"/reports/{state['application_id']}.pdf"}}

# @celery_app.task  # Commented out for sync execution
def run_simplified_underwriting_agent(state: dict, context: StepContext):
    """AI Agent: Simulates a simplified, faster underwriting microservice."""
    print(f"Running simplified underwriting for {state['application_id']}...")
    time.sleep(0.5) # Reduced for sync testing (was 2)
    risk_score = state['requested_amount'] / (state['applicant_profile']['age'] * state['credit_check']['score'] * 2) if state.get('credit_check') else 0.25
    recommendation = "APPROVE" if risk_score < 0.003 else "REJECT"
    return {"underwriting_result": {"risk_score": risk_score, "recommendation": recommendation, "detailed_report_url": f"/reports/{state['application_id']}_simple.pdf"}}

def request_human_review(state: LoanApplicationState, context: StepContext):
    """Human-in-the-Loop: Pauses workflow for human decision by raising a directive."""
    state.final_loan_status = "PENDING_MANUAL_REVIEW"
    print(f"Application {state.application_id}: Paused for Human Underwriter Review.")
    # The engine will catch this directive and set the status to WAITING_HUMAN
    raise WorkflowPauseDirective(result={"message": "Waiting for human review."})

def process_human_decision(state: LoanApplicationState, context: StepContext):
    """Processes the decision from the Human-in-the-Loop step."""
    input_data = context.validated_input
    if not input_data:
        raise ValueError("Human decision input is missing from the context.")

    if state.human_review is None:
        state.human_review = HumanReviewDecision(
            decision=input_data.decision,
            reviewer_id=input_data.reviewer_id,
            comments=input_data.comments,
            timestamp=str(datetime.datetime.now())
        )
    
    if state.human_review.decision == "APPROVED":
        state.final_loan_status = "APPROVED"
        print(f"Application {state.application_id}: Manually Approved by {input_data.reviewer_id}.")
    else:
        state.final_loan_status = "REJECTED"
        print(f"Application {state.application_id}: Manually Rejected by {input_data.reviewer_id}. Reason: {input_data.comments or 'No comments'}")
        
    return {"human_review_status": "processed"}

def generate_final_decision(state: LoanApplicationState, context: StepContext):
    """Final step: Consolidates all results and sets final status."""
    if state.final_loan_status == "APPROVED" or (state.pre_approval_status == "FAST_TRACK_APPROVED"):
        state.final_loan_status = "APPROVED"
        print(f"Application {state.application_id} finalized as APPROVED.")
        return {"final_outcome": "LOAN APPROVED"}
    else:
        state.final_loan_status = "REJECTED"
        print(f"Application {state.application_id} finalized as REJECTED.")
        return {"final_outcome": "LOAN REJECTED"}

def run_kyc_workflow_placeholder(state: LoanApplicationState, context: StepContext):
    """
    DEPRECATED: Legacy placeholder function - use run_kyc_workflow instead
    """
    print("WARNING: Using deprecated KYC placeholder. Use run_kyc_workflow() instead.")
    return {"message": "KYC workflow placeholder executed (deprecated)."}


def run_kyc_workflow(state: LoanApplicationState, context: StepContext):
    """
    Launch KYC (Know Your Customer) verification as a sub-workflow
    """
    print(f"[KYC SUB-WORKFLOW] Launching KYC verification for {state.applicant_profile.name}")
    print(f"[KYC SUB-WORKFLOW] User ID: {state.applicant_profile.user_id}")
    print(f"[KYC SUB-WORKFLOW] ID Document: {state.applicant_profile.id_document_url}")

    raise StartSubWorkflowDirective(
        workflow_type="KYC",
        initial_data={
            "user_name": state.applicant_profile.name,
            "id_document_url": state.applicant_profile.id_document_url
        },
        data_region="onsite-london"
    )

# --- Compensation Functions ---

def compensate_collect_application_data(state: LoanApplicationState, context: StepContext):
    print(f"[COMPENSATION] Clearing application data for {state.application_id}")
    app_id = state.application_id
    applicant_name = state.applicant_profile.name if state.applicant_profile else "Unknown"

    state.application_id = None
    state.applicant_profile = None
    state.requested_amount = 0.0

    print(f"[COMPENSATION] Application {app_id} for {applicant_name} cleared successfully")
    return {
        "compensation_action": "clear_application",
        "cleared_application_id": app_id,
        "cleared_applicant": applicant_name
    }

def compensate_evaluate_pre_approval(state: LoanApplicationState, context: StepContext):
    print(f"[COMPENSATION] Revoking pre-approval for {state.application_id}")
    previous_status = state.pre_approval_status
    state.pre_approval_status = None
    print(f"[COMPENSATION] Pre-approval status '{previous_status}' revoked for {state.application_id}")
    return {
        "compensation_action": "revoke_pre_approval",
        "previous_status": previous_status,
        "application_id": state.application_id
    }

def compensate_route_underwriting(state: LoanApplicationState, context: StepContext):
    print(f"[COMPENSATION] Clearing underwriting routing for {state.application_id}")
    previous_type = state.underwriting_type
    state.underwriting_type = None
    print(f"[COMPENSATION] Underwriting type '{previous_type}' cleared for {state.application_id}")
    return {
        "compensation_action": "clear_underwriting_routing",
        "previous_underwriting_type": previous_type
    }

def compensate_request_human_review(state: LoanApplicationState, context: StepContext):
    print(f"[COMPENSATION] Cancelling human review for {state.application_id}")
    if state.human_review:
        reviewer_id = state.human_review.reviewer_id
        state.human_review = None
        print(f"[COMPENSATION] Cleared review assignment for reviewer {reviewer_id}")

    if state.final_loan_status == "PENDING_MANUAL_REVIEW":
        state.final_loan_status = None

    return {
        "compensation_action": "cancel_human_review",
        "application_id": state.application_id,
        "message": "Human review request cancelled"
    }

def compensate_process_human_decision(state: LoanApplicationState, context: StepContext):
    print(f"[COMPENSATION] Reverting human decision for {state.application_id}")
    if state.human_review:
        previous_decision = state.human_review.decision
        reviewer_id = state.human_review.reviewer_id
        state.human_review = None
        state.final_loan_status = None
        print(f"[COMPENSATION] Decision '{previous_decision}' by {reviewer_id} reverted")
        return {
            "compensation_action": "revert_human_decision",
            "reverted_decision": previous_decision,
            "reviewer_id": reviewer_id
        }
    return {"compensation_action": "revert_human_decision", "message": "No decision to revert"}

def compensate_generate_final_decision(state: LoanApplicationState, context: StepContext):
    print(f"[COMPENSATION] Revoking final decision for {state.application_id}")
    previous_status = state.final_loan_status
    state.final_loan_status = None
    print(f"[COMPENSATION] CRITICAL: Final status '{previous_status}' revoked for {state.application_id}")
    return {
        "compensation_action": "revoke_final_decision",
        "previous_status": previous_status,
        "application_id": state.application_id,
        "critical": True,
        "message": f"Loan {previous_status} status revoked - no disbursement"
    }

def compensate_run_credit_check(state: LoanApplicationState, context: StepContext):
    print(f"[COMPENSATION] Clearing credit check results for {state.application_id}")
    if state.credit_check:
        previous_score = state.credit_check.score
        state.credit_check = None
        print(f"[COMPENSATION] Cleared credit score {previous_score}")
        return {
            "compensation_action": "clear_credit_check",
            "previous_score": previous_score
        }
    return {"compensation_action": "clear_credit_check", "message": "No credit check to clear"}

def compensate_run_fraud_check(state: LoanApplicationState, context: StepContext):
    print(f"[COMPENSATION] Clearing fraud check results for {state.application_id}")
    if state.fraud_check:
        previous_status = state.fraud_check.status
        state.fraud_check = None
        print(f"[COMPENSATION] Cleared fraud status {previous_status}")
        return {
            "compensation_action": "clear_fraud_check",
            "previous_status": previous_status
        }
    return {"compensation_action": "clear_fraud_check", "message": "No fraud check to clear"}

def compensate_run_kyc_workflow(state: LoanApplicationState, context: StepContext):
    print(f"[COMPENSATION] Rolling back KYC workflow for {state.application_id}")
    if state.kyc_results:
        state.kyc_results = None
        print(f"[COMPENSATION] KYC results cleared")
    return {
        "compensation_action": "rollback_kyc",
        "message": "KYC workflow rolled back"
    }
