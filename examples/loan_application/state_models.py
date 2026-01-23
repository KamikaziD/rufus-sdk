from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

# --- Step-specific Input Models ---
class CollectApplicationDataInput(BaseModel):
    user_id: str
    name: str
    email: str
    country: str
    age: int = Field(..., ge=18, description="Applicant's age, must be 18 or older.")
    requested_amount: float = Field(..., gt=0, description="The requested loan amount, must be positive.")
    id_document_url: str

class CreateUserProfileInput(BaseModel):
    name: str
    email: str

class ComplianceReviewFetchClientDataInput(BaseModel):
    client_id: str

class ImageComplianceCollectComplianceAssetsInput(BaseModel):
    image_url: Optional[str] = None
    compliance_text: Optional[str] = None

class ProcessHumanDecisionInput(BaseModel):
    decision: str
    reviewer_id: str
    comments: Optional[str] = None

# --- Child Workflow States ---
class KYCState(BaseModel):
    user_name: str
    id_document_url: str
    id_verified: Optional[bool] = None
    sanctions_screen_passed: Optional[bool] = None
    kyc_report_summary: Optional[str] = None
    kyc_overall_status: Optional[str] = None # E.g., "APPROVED", "PENDING", "REJECTED"

# --- Main Workflow States ---
class UserProfileState(BaseModel):
    user_id: str
    name: str
    email: str
    country: str
    age: int = Field(..., ge=18)
    id_document_url: str # Added for KYC

class CreditCheckResult(BaseModel):
    score: int
    report_id: str
    risk_level: str

class FraudCheckResult(BaseModel):
    status: str
    score: float
    reason: Optional[str] = None

class UnderwritingResult(BaseModel):
    risk_score: float
    recommendation: str
    detailed_report_url: Optional[str] = None

class HumanReviewDecision(BaseModel):
    decision: str # "APPROVED", "REJECTED", "MORE_INFO"
    reviewer_id: str
    comments: Optional[str] = None
    timestamp: str # Using str for simplicity here, datetime in real app

class LoanApplicationState(BaseModel):
    application_id: Optional[str] = None
    requested_amount: float
    applicant_profile: UserProfileState
    credit_check: Optional[CreditCheckResult] = None
    fraud_check: Optional[FraudCheckResult] = None

    # Nested Workflow results
    kyc_results: Optional[KYCState] = None

    # Sub-workflow results (generic dict for any child workflow)
    sub_workflow_results: Optional[Dict[str, Any]] = None
    
    # Fire-and-forget spawned workflows tracking
    spawned_workflows: Optional[List[Dict[str, Any]]] = None

    pre_approval_status: Optional[str] = None # E.g., "FAST_TRACK_APPROVED", "PENDING_DETAILED_REVIEW", "REJECTED_AUTOMATIC"
    underwriting_type: Optional[str] = None
    underwriting_result: Optional[UnderwritingResult] = None

    human_review: Optional[HumanReviewDecision] = None

    final_loan_status: Optional[str] = None # E.g., "APPROVED", "REJECTED", "PENDING_MANUAL_REVIEW"

    # Async task tracking
    async_task_id: Optional[str] = None

class OnboardingState(BaseModel):
    user_id: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    email_domain: Optional[str] = None
    email_verified: Optional[bool] = None
    email_sent: Optional[bool] = None
    database_updated: Optional[bool] = None

class ComplianceState(BaseModel):
    client_id: Optional[str] = None
    client_data: Optional[Dict[str, Any]] = None
    compliance_status: Optional[str] = None
    report_url: Optional[str] = None

class ImageComplianceState(BaseModel):
    image_url: Optional[str] = None
    compliance_text: Optional[str] = None
    analysis_result: Optional[str] = None
    agent_id: Optional[str] = "OCR-Agent"
    email_sent: Optional[bool] = False
    database_updated: Optional[bool] = False

class SuperWorkflowState(BaseModel):

    name: str

    greeting: Optional[str] = None

    greeting_length: Optional[int] = None

    analysis_decision: Optional[str] = None

    final_message: Optional[str] = None



class GearsTestState(BaseModel):

    test_id: str

    items: List[str] = Field(default_factory=list)

    processed_count: int = 0

    loop_item: Optional[str] = None

    spawned_workflows: Optional[List[Dict[str, Any]]] = None

    schedule_registered: bool = False

    stop_loop: bool = False

class NotificationState(BaseModel):
    recipient: str
    message: str
    status: str = "pending"


# --- Test-specific Models ---
# These are used by the test suite and are included here to facilitate
# the workflow loader being able to find them during test runs.

class TestParentState(BaseModel):
    parent_id: str
    sub_workflow_results: Optional[Dict[str, Any]] = None
    p_step_4_executed: bool = False

class TestChildState(BaseModel):
    child_id: str
    step_1_executed: bool = False
    step_2_executed: bool = False
    final_message: Optional[str] = None

