# Loan Application Workflow Example

This example demonstrates a complex, production-ready loan application workflow using the Ruvon SDK. It showcases advanced features including parallel execution, conditional branching, dynamic step injection, saga compensation patterns, and human-in-the-loop processes.

## Overview

The loan application workflow evaluates loan applications through multiple stages:

1. **Application Initialization** - Collects and validates applicant data
2. **Parallel Risk Assessment** - Runs credit check and fraud detection simultaneously
3. **Pre-Approval Evaluation** - Makes decision based on risk assessment:
   - **Fast-Track** (high credit, clean fraud) → Skip to final approval
   - **Auto-Reject** (low credit or high fraud risk) → Skip to rejection
   - **Detailed Review** (medium risk) → Continue to underwriting
4. **KYC Verification** - Know Your Customer sub-workflow (currently requires SDK fixes)
5. **Dynamic Underwriting Routing** - Chooses path based on loan amount:
   - **Simplified** (< $20,000) → Quick automated underwriting
   - **Full** (≥ $20,000) → Complex underwriting with human review
6. **Final Decision** - Generates loan approval or rejection

## Features Demonstrated

### 1. Parallel Execution
```yaml
- name: "Run_Concurrent_Checks"
  type: "PARALLEL"
  tasks:
    - name: "Credit_Check"
      function: "loan.run_credit_check_agent"
    - name: "Fraud_Detection"
      function: "loan.run_fraud_detection_agent"
```

Parallel tasks run simultaneously in separate threads, with results merged back into the workflow state.

### 2. Conditional Branching with Directives
```python
def evaluate_pre_approval(state: LoanApplicationState, context: StepContext):
    if credit_score > 700 and fraud_status == "CLEAN":
        state.pre_approval_status = "FAST_TRACK_APPROVED"
        raise WorkflowJumpDirective(target_step_name="Generate_Final_Decision")
    elif credit_score < 600 or fraud_status == "HIGH_RISK":
        state.pre_approval_status = "REJECTED_AUTOMATIC"
        raise WorkflowJumpDirective(target_step_name="Generate_Final_Decision")
```

Use `WorkflowJumpDirective` to skip steps based on business logic.

### 3. Dynamic Step Injection
```yaml
- name: "Inject_Underwriting_Branch"
  type: "STANDARD"
  function: "general.noop"
  dynamic_injection:
    rules:
      - condition_key: "underwriting_type"
        value_match: "full"
        action: "INSERT_AFTER_CURRENT"
        steps_to_insert:
          - name: "Run_Full_Underwriting"
            type: "ASYNC"
            function: "loan.run_full_underwriting_agent"
```

Steps are dynamically added to the workflow based on runtime state values.

### 4. Human-in-the-Loop
```python
def request_human_review(state: LoanApplicationState, context: StepContext):
    state.final_loan_status = "PENDING_MANUAL_REVIEW"
    raise WorkflowPauseDirective(result={"message": "Waiting for human review."})

def process_human_decision(state: LoanApplicationState, context: StepContext):
    input_data = context.validated_input
    state.human_review = HumanReviewDecision(
        decision=input_data.decision,
        reviewer_id=input_data.reviewer_id,
        comments=input_data.comments
    )
```

Workflows can pause for human input and resume with validated data.

### 5. Saga Compensation Patterns
```yaml
- name: "Generate_Final_Decision"
  type: "STANDARD"
  function: "loan.generate_final_decision"
  compensate_function: "loan.compensate_generate_final_decision"
```

Each step can define a compensation function for distributed transaction rollback.

## File Structure

```
examples/loan_application/
├── README.md                  # This file
├── workflow_registry.yaml     # Registry of available workflows
├── loan_workflow.yaml         # Main loan application workflow definition
├── kyc_workflow.yaml          # KYC sub-workflow definition
├── state_models.py            # Pydantic models for workflow state
├── loan.py                    # Step implementation functions
├── kyc.py                     # KYC step implementation functions
├── general.py                 # Utility functions (noop, etc.)
└── run_loan_sync.py          # Test script with 3 scenarios
```

## State Models

### LoanApplicationState
```python
class LoanApplicationState(BaseModel):
    application_id: Optional[str]
    requested_amount: float
    applicant_profile: UserProfileState
    credit_check: Optional[CreditCheckResult]
    fraud_check: Optional[FraudCheckResult]
    pre_approval_status: Optional[str]
    underwriting_type: Optional[str]
    underwriting_result: Optional[UnderwritingResult]
    human_review: Optional[HumanReviewDecision]
    final_loan_status: Optional[str]
```

### UserProfileState
```python
class UserProfileState(BaseModel):
    user_id: str
    name: str
    email: str
    country: str
    age: int
    id_document_url: str
```

## Running the Example

### Prerequisites

1. Install Ruvon SDK:
```bash
cd /path/to/rufus
pip install -e .
```

2. Navigate to the example directory:
```bash
cd examples/loan_application
```

### Execute All Test Scenarios

```bash
python run_loan_sync.py
```

This runs three scenarios:
- **Scenario 1**: Fast-track approval (high credit, low risk)
- **Scenario 2**: SKIPPED (requires sub-workflow SDK fixes)
- **Scenario 3**: Automatic rejection (high fraud risk)

### Expected Output

```
================================================================================
LOAN APPLICATION WORKFLOW - SYNCHRONOUS EXECUTION
================================================================================

✓ Loaded workflow registry
[SyncExecutor] Initialized.
✓ Workflow engine initialized

================================================================================
SCENARIO 1: Fast-Track Approval
================================================================================

✓ Started workflow: xxxx-xxxx-xxxx
  Status: ACTIVE

--- Step 1: Initialize_Application ---
Application LOAN-xxx initialized for Alice Johnson.
Running credit check for Alice Johnson...
Running fraud detection for Alice Johnson...
Evaluating pre-approval for LOAN-xxx...
Application LOAN-xxx: Fast-track approved. Bypassing detailed review.

--- Step 2: Generate_Final_Decision ---
Application LOAN-xxx finalized as APPROVED.

✓ Workflow completed with status: COMPLETED
  Final state: APPROVED
  Total steps executed: 2

================================================================================
EXECUTION SUMMARY
================================================================================
Scenario 1 (Fast-Track):       APPROVED
Scenario 2 (Human Review):     SKIPPED (requires SDK fixes)
Scenario 3 (Auto-Reject):      REJECTED

✓ Executed scenarios completed successfully!
```

## Step Functions

All step functions follow the signature:
```python
def step_name(state: StateModel, context: StepContext) -> Dict[str, Any]:
    # Function implementation
    return {"key": "value"}
```

### Parallel Task Functions

Parallel task functions receive state as a dict:
```python
def run_credit_check_agent(state: dict, context: StepContext) -> Dict[str, Any]:
    # Access state as dictionary
    name = state['applicant_profile']['name']
    return {"credit_check": {...}}
```

### Async Task Functions

Functions decorated with `@celery_app.task` (commented out for sync execution):
```python
# @celery_app.task
def run_full_underwriting_agent(state: dict, context: StepContext):
    # Simulates async execution
    return {"underwriting_result": {...}}
```

## Business Logic

### Credit Scoring
- Age ≥ 25: Score 780 (low risk)
- Age < 25: Score 620 (medium risk)

### Fraud Detection
- Country != "ZA": CLEAN (0.1 fraud score)
- Country == "ZA": HIGH_RISK (0.9 fraud score)

### Pre-Approval Rules
- Credit > 700 AND Fraud = CLEAN → **Fast-Track Approved**
- Credit < 600 OR Fraud = HIGH_RISK → **Rejected Automatically**
- Otherwise → **Detailed Review Required**

### Underwriting Routing
- Loan Amount < $20,000 → **Simplified Underwriting**
- Loan Amount ≥ $20,000 → **Full Underwriting with Human Review**

## Compensation Functions

Each critical step has a compensation function for saga pattern rollback:

```python
def compensate_generate_final_decision(state: LoanApplicationState, context: StepContext):
    print(f"[COMPENSATION] Revoking final decision for {state.application_id}")
    previous_status = state.final_loan_status
    state.final_loan_status = None
    return {
        "compensation_action": "revoke_final_decision",
        "previous_status": previous_status,
        "critical": True
    }
```

## Known Limitations

### 1. Sub-Workflow Feature
The KYC sub-workflow step is currently disabled because the SDK has a bug where `Workflow.initial_state_model` attribute doesn't exist. Once this is fixed in the SDK, you can enable it by testing Scenario 2.

### 2. Step Types
The original workflow used `DECISION` and `HUMAN_IN_LOOP` step types, but the SDK only supports:
- `STANDARD`
- `ASYNC`
- `PARALLEL`
- `HTTP`
- `FIRE_AND_FORGET`
- `LOOP`
- `CRON_SCHEDULER`

Use `STANDARD` steps with directives (`WorkflowJumpDirective`, `WorkflowPauseDirective`) to implement decision and human-in-the-loop logic.

### 3. Celery Decorators
Celery task decorators are commented out for synchronous execution. To enable true async execution with Celery:

1. Uncomment `@celery_app.task` decorators
2. Configure Celery broker (Redis/RabbitMQ)
3. Use `CeleryExecutor` instead of `SyncExecutor`

## Customization

### Add New Steps

1. Define the step function in `loan.py`:
```python
def my_custom_step(state: LoanApplicationState, context: StepContext):
    # Your logic here
    return {"custom_result": "value"}
```

2. Add to `loan_workflow.yaml`:
```yaml
- name: "My_Custom_Step"
  type: "STANDARD"
  function: "loan.my_custom_step"
  dependencies: ["Previous_Step"]
  automate_next: true
```

### Modify Business Rules

Edit the logic in `loan.py`:
```python
def evaluate_pre_approval(state: LoanApplicationState, context: StepContext):
    # Update thresholds
    if credit_score > 750 and fraud_status == "CLEAN":  # Changed from 700
        # ...
```

### Add New State Fields

Update `state_models.py`:
```python
class LoanApplicationState(BaseModel):
    # ... existing fields ...
    my_new_field: Optional[str] = None
```

## Testing Scenarios

### Scenario 1: Fast-Track Approval
```python
applicant = UserProfileState(
    user_id="user_001",
    name="Alice Johnson",
    email="alice@example.com",
    country="US",      # Clean country
    age=30,            # High credit score (780)
    id_document_url="https://docs.example.com/valid_id.pdf"
)
initial_data = LoanApplicationState(
    requested_amount=15000.0,  # Simplified underwriting
    applicant_profile=applicant
)
```
**Result**: Fast-track approved, skips to final decision

### Scenario 3: Automatic Rejection
```python
applicant = UserProfileState(
    user_id="user_003",
    name="Charlie Wilson",
    email="charlie@example.com",
    country="ZA",      # High-risk country
    age=22,            # Lower credit score (620)
    id_document_url="https://docs.example.com/valid_id.pdf"
)
initial_data = LoanApplicationState(
    requested_amount=25000.0,
    applicant_profile=applicant
)
```
**Result**: Automatically rejected due to high fraud risk

## Next Steps

1. **Enable Celery** for true async execution
2. **Implement Persistence** using PostgresPersistence instead of InMemoryPersistence
3. **Add Human Review UI** for processing manual decisions
4. **Integrate Real Services** for credit checks, fraud detection, KYC
5. **Add Observability** with custom observers for monitoring and metrics
6. **Test Compensation** by forcing failures and verifying saga rollback

## Resources

- [Ruvon SDK Documentation](../../README.md)
- [Quickstart Example](../quickstart/)
- [Technical Documentation](../../TECHNICAL_DOCUMENTATION.md)
- [SDK Development Plan](../../updated_sdk_plan.md)

## Contributing

This example demonstrates the Ruvon SDK's capabilities for complex workflow orchestration. If you encounter bugs or have suggestions for improvements, please open an issue or submit a pull request.

---

**Note**: This workflow is migrated from the original Confucius implementation to demonstrate SDK-first architecture. Some advanced features (sub-workflows) require SDK enhancements currently in development.
