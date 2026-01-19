# Confucius YAML Configuration Reference

This document provides a complete reference for defining and configuring workflows using the Confucius workflow engine's YAML-based system. It covers all configuration options, step types, and advanced features.

## 1. The Registry: `workflow_registry.yaml`

All workflows must be registered in a central registry file. This file tells the `WorkflowBuilder` what workflows are available, where their definitions are, and what data structure they use.

Each entry in the `workflows` list requires three keys:

*   `type`: A unique string identifier for the workflow (e.g., `LoanApplication`).
*   `config_file`: The path to the YAML file containing the workflow's step definitions. This path is relative to the location of the registry file.
*   `initial_state_model`: The full Python import path to the Pydantic `BaseModel` that defines the state for this workflow (e.g., `"state_models.LoanApplicationState"`).

**Example:**
```yaml
# config/workflow_registry.yaml
workflows:
  - type: "LoanApplication"
    description: "A complex workflow for processing a loan application."
    config_file: "loan_workflow.yaml"
    initial_state_model: "state_models.LoanApplicationState"
  
  - type: "CustomerOnboarding"
    description: "A simple workflow for onboarding a new customer."
    config_file: "onboarding_workflow.yaml"
    initial_state_model: "state_models.OnboardingState"
```

---

## 2. Anatomy of a Workflow Definition File

Each workflow has its own YAML file that defines its steps. The file contains top-level keys and a list of `steps`.

### 2.1. Anatomy of a Step

Each item in the `steps` list is a dictionary that defines a single unit of work.

*   `name`: A unique string name for the step within the workflow (e.g., `"Collect_Application_Data"`).
*   `type`: Defines how the step is executed. This is one of the most important keys. See **Section 3** for details.
*   `function`: The full Python import path to the function that contains the business logic for this step (e.g., `"workflow_utils.collect_application_data"`).
*   `input_model` (Recommended): The import path to a Pydantic model defining the inputs for this step. See **Section 4** for details.
*   `required_input` (Legacy): A simple list of required input keys. Use `input_model` for new development.
*   `automate_next` (Optional): A boolean (`true`/`false`) flag. If set to `true`, the engine will immediately execute the next step in the workflow using the output of the current step as its input.
*   `dependencies`: (For future use/documentation purposes) A list of step names that should complete before this one. Currently, the engine executes steps in the order they appear in the `steps` list unless a directive alters the flow.

---

## 3. Step Execution Types

The `type` key controls the execution behavior of a step.

| Type | Description |
| :--- | :--- |
| **`STANDARD`** | The default type. Executes the specified `function` synchronously. The workflow waits for the function to complete before moving to the next step. |
| **`DECISION`** | Functionally the same as `STANDARD`, but used to signify that the step's primary purpose is to evaluate the state and potentially alter the workflow's path using a `WorkflowJumpDirective`. |
| **`ASYNC`** | For long-running tasks. The step's `function` (which must be a Celery task) is dispatched to a background worker. The workflow's status becomes `PENDING_ASYNC` and execution pauses. A callback resumes the workflow once the task is complete. |
| **`PARALLEL`** | For executing multiple `ASYNC` tasks concurrently. This step does not have a `function` key, but instead a `tasks` list. The workflow waits for all tasks to complete, merges their results, and then resumes. |
| **`HUMAN_IN_LOOP`** | Pauses the workflow indefinitely for external input. The step's function should raise a `WorkflowPauseDirective`. The workflow status becomes `WAITING_HUMAN` until it is resumed via the `/resume` API endpoint. |

---

## 4. Input Validation

You can define the inputs required for a step in two ways.

### `input_model` (Recommended)
This is the modern, preferred method. You provide the import path to a Pydantic model.

**Benefits:**
*   **Automatic Type Coercion:** Input `{"age": "30"}` will be automatically converted to the integer `30`.
*   **Rich Validation:** You can use all of Pydantic's validators (`ge`, `le`, `pattern`, etc.) on the model fields.
*   **API Schema Generation:** The engine uses this model to generate a JSON Schema for the API, enabling richer UIs and better documentation.

**Example:**
```yaml
# my_workflow.yaml
steps:
  - name: "Create_User"
    type: "STANDARD"
    function: "my_funcs.create_user"
    input_model: "my_models.CreateUserInput" # Points to a Pydantic model
```
```python
# my_models.py
from pydantic import BaseModel, Field

class CreateUserInput(BaseModel):
    name: str
    age: int = Field(..., ge=18)
    email: str
```

### `required_input` (Legacy)
This is a simple list of string keys that must be present in the input data. It does not perform any type checking or validation. It is maintained for backward compatibility.

**Example:**
```yaml
steps:
  - name: "Create_User"
    type: "STANDARD"
    function: "my_funcs.create_user"
    required_input: ["name", "age", "email"]
```

---

## 5. Walkthrough: The Loan Application Workflow

Let's examine `config/loan_workflow.yaml` to see how these concepts fit together.

### Step 1: Input Validation with `input_model`
The first step, `Collect_Application_Data`, uses the `input_model` to validate its input.
```yaml
  - name: "Collect_Application_Data"
    type: "STANDARD"
    function: "workflow_utils.collect_application_data"
    input_model: "state_models.CollectApplicationDataInput"
```
The engine will now ensure that any data submitted to this step conforms to the `CollectApplicationDataInput` model defined in `state_models.py`, checking for required fields, types, and validation rules (e.g., `age >= 18`).

### Step 2: Parallel Execution
The `Run_Concurrent_Checks` step executes credit and fraud checks at the same time.
```yaml
  - name: "Run_Concurrent_Checks"
    type: "PARALLEL"
    tasks:
      - name: "Credit_Check"
        function: "workflow_utils.run_credit_check_agent"
      - name: "Fraud_Detection"
        function: "workflow_utils.run_fraud_detection_agent"
```
The engine dispatches both functions (which must be Celery tasks) to background workers. Once both are complete, their results are merged, and the workflow proceeds to the next step.

### Step 3: Decision & Branching
The `Evaluate_Pre_Approval` step inspects the results from the parallel checks and decides where to go next.
```python
# workflow_utils.py
def evaluate_pre_approval(state: LoanApplicationState):
    if state.credit_check.score < 600:
        # This directive tells the engine to skip to "Generate_Final_Decision"
        raise WorkflowJumpDirective(target_step_name="Generate_Final_Decision")
    # ...
```
If the credit score is too low, the function raises `WorkflowJumpDirective`. The engine catches this and immediately changes the current step to `Generate_Final_Decision`, skipping all the underwriting steps.

### Step 4: Dynamic Step Injection
The `Inject_Underwriting_Branch` step demonstrates how to dynamically alter the workflow's path.
```yaml
  - name: "Inject_Underwriting_Branch"
    type: "STANDARD"
    function: "workflow_utils.noop" # This function does nothing
    dynamic_injection:
      rules:
        - condition_key: "underwriting_type"
          value_match: "full"
          action: "INSERT_AFTER_CURRENT"
          steps_to_insert:
            - name: "Run_Full_Underwriting"
              type: "ASYNC"
              function: "workflow_utils.run_full_underwriting_agent"
            - name: "Request_Human_Review"
              type: "HUMAN_IN_LOOP"
              # ... more steps
```
After the preceding `Route_Underwriting` step sets the `underwriting_type` in the state, this step's `dynamic_injection` rule is evaluated. If `state.underwriting_type` is `"full"`, the engine inserts the `Run_Full_Underwriting` and `Request_Human_Review` steps into the plan right after the current step. If it were `"simple"`, a different rule would inject the `Simplified_Underwriting` step instead.

### Step 5: Human-in-the-Loop
The dynamically injected `Request_Human_Review` step is designed to pause the workflow.
```yaml
            - name: "Request_Human_Review"
              type: "HUMAN_IN_LOOP"
              function: "workflow_utils.request_human_review"
```
The `request_human_review` function simply raises a `WorkflowPauseDirective`. The engine catches this and sets the workflow status to `WAITING_HUMAN`. The workflow will not proceed until an external user submits a decision via the `/api/v1/workflow/{id}/resume` endpoint. When resumed, the engine advances to the next step, `Process_Human_Decision`, which is designed to handle the submitted review data.

---

## 6. Advanced Feature: Automated Step Chaining

For workflows where a sequence of steps should run automatically without human intervention, you can use the `automate_next: true` flag.

When a step with this flag completes, the engine immediately triggers the next step in the sequence. The crucial part is that the **entire dictionary returned by the completed step is used as the input for the next step**. This allows you to create powerful, self-driving chains of logic.

### Example: The SuperWorkflow

Let's look at `config/super_workflow.yaml`, which is designed to showcase this feature.

```yaml
# config/super_workflow.yaml
workflow_type: "SuperWorkflow"
steps:
  - name: "Record_User_Name"
    type: "STANDARD"
    function: "workflow_utils.record_name"
    required_input: ["name"]
    automate_next: true # <-- Automation starts here

  - name: "Generate_Greeting"
    type: "STANDARD"
    function: "workflow_utils.generate_greeting"
    automate_next: true # <-- Automation continues

  - name: "Analyze_Greeting"
    type: "STANDARD"
    function: "workflow_utils.analyze_greeting"
    automate_next: false # <-- Automation stops here

  - name: "Finalize"
    type: "STANDARD"
    function: "workflow_utils.finalize_workflow"
```

**How it works:**

1.  The user starts the workflow by calling `/next` on the `Record_User_Name` step, providing a `name`.
2.  `record_name` executes and returns a dictionary, e.g., `{"greeting": "Hello, World!"}`.
3.  Because `automate_next` is `true`, the engine does not stop. It immediately calls the `Generate_Greeting` step, providing `{"greeting": "Hello, World!"}` as its input.
4.  `generate_greeting` runs and returns `{"greeting_length": 13}`.
5.  `automate_next` is also `true` on this step, so the engine continues and calls `Analyze_Greeting`, providing `{"greeting_length": 13}` as its input.
6.  `Analyze_Greeting` runs. Its `automate_next` flag is `false`.
7.  The automated chain stops. The workflow's `current_step` is now pointing to `Finalize`, waiting for the user to make the next call to the `/api/v1/workflow/{id}/next` endpoint.

---

## 7. Complete Step Configuration Reference

### All Step Properties

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `name` | string | Yes | Unique identifier for the step |
| `type` | string | Yes | Step execution type (STANDARD, ASYNC, PARALLEL, DECISION, HUMAN_IN_LOOP) |
| `function` | string | Conditional | Python import path to step function (not used for PARALLEL) |
| `compensate_function` | string | No | Python import path to saga compensation function |
| `input_model` | string | No | Python import path to Pydantic input validation model |
| `required_input` | list | No | Legacy: List of required input keys |
| `automate_next` | boolean | No | If true, automatically execute next step (default: false) |
| `dependencies` | list | No | Documentation: List of step names this depends on |
| `dynamic_injection` | object | No | Rules for injecting steps at runtime |
| `tasks` | list | Conditional | List of parallel tasks (only for PARALLEL type) |
| `merge_function_path` | string | No | Custom merge function for PARALLEL results |

---

## 8. Saga Pattern Configuration

The saga pattern provides automatic rollback through compensation functions.

### Basic Saga Configuration

```yaml
workflow_type: "OrderProcessing"
initial_state_model: "state_models.OrderState"

steps:
  - name: "Reserve_Inventory"
    type: "STANDARD"
    function: "inventory.reserve_items"
    compensate_function: "inventory.release_items"

  - name: "Charge_Payment"
    type: "STANDARD"
    function: "payment.charge_customer"
    compensate_function: "payment.refund_customer"

  - name: "Create_Shipment"
    type: "STANDARD"
    function: "shipping.create_shipment"
    compensate_function: "shipping.cancel_shipment"
```

### Compensation Function Signature

```python
def compensate_function_name(state: StateModel) -> Dict[str, Any]:
    """
    Compensation function that undoes the forward action

    Args:
        state: Current workflow state (includes all data from forward execution)

    Returns:
        Dictionary with compensation results
    """
    # Undo the operation
    undo_operation(state.resource_id)

    return {
        "compensated": True,
        "compensation_details": "Resource released"
    }
```

### Saga Execution Flow

1. **Forward Phase**: Steps execute normally
2. **Failure Detected**: If any step fails
3. **Rollback Phase**: Compensation functions execute in reverse order
4. **Final State**: Workflow status becomes `FAILED_ROLLED_BACK`

### Enabling Saga Mode

Saga mode must be enabled programmatically:

```python
# In workflow initialization
workflow = workflow_builder.create_workflow("OrderProcessing", initial_data)
workflow.enable_saga_mode()
```

---

## 9. Sub-Workflow Configuration

Sub-workflows allow you to compose complex workflows from smaller, reusable workflows.

### Parent Workflow Configuration

```yaml
workflow_type: "LoanApplication"
initial_state_model: "state_models.LoanApplicationState"

steps:
  - name: "Collect_Application"
    type: "STANDARD"
    function: "loan.collect_application"

  - name: "Run_KYC_Workflow"
    type: "STANDARD"
    function: "loan.launch_kyc_workflow"
    # This function raises StartSubWorkflowDirective

  - name: "Process_KYC_Results"
    type: "STANDARD"
    function: "loan.process_kyc_results"
    # Can access sub_workflow_results from state
```

### Launching a Sub-Workflow

```python
from confucius.workflow import StartSubWorkflowDirective

def launch_kyc_workflow(state):
    """Launch KYC verification as a child workflow"""
    raise StartSubWorkflowDirective(
        workflow_type="KYC",  # Must match registry entry
        initial_data={
            "user_name": state.applicant_name,
            "id_document_url": state.id_document_url,
            "email": state.email
        },
        data_region="us-east-1"  # Optional: specify data region
    )
```

### Child Workflow (KYC)

```yaml
workflow_type: "KYC"
initial_state_model: "state_models.KYCState"

steps:
  - name: "Verify_Identity_Document"
    type: "ASYNC"
    function: "kyc.verify_document"

  - name: "Check_Watchlists"
    type: "PARALLEL"
    tasks:
      - name: "OFAC_Check"
        function: "kyc.check_ofac"
      - name: "PEP_Check"
        function: "kyc.check_pep"

  - name: "Generate_KYC_Result"
    type: "STANDARD"
    function: "kyc.generate_result"
```

### Accessing Sub-Workflow Results

After the child completes, the parent can access results:

```python
def process_kyc_results(state: LoanApplicationState):
    """Process results from KYC sub-workflow"""
    # Child results are in state.sub_workflow_results
    kyc_data = state.sub_workflow_results.get('KYC', {})

    if kyc_data.get('kyc_passed'):
        return {
            "kyc_status": "verified",
            "kyc_completion_date": kyc_data.get('completion_date')
        }
    else:
        return {
            "kyc_status": "failed",
            "kyc_failure_reason": kyc_data.get('failure_reason')
        }
```

### State Model Requirements

Parent state must have `sub_workflow_results` field:

```python
from pydantic import BaseModel
from typing import Dict, Any, Optional

class LoanApplicationState(BaseModel):
    applicant_name: str
    # ... other fields ...

    # Required for sub-workflow support
    sub_workflow_results: Optional[Dict[str, Any]] = {}
```

---

## 10. Dynamic Injection Rules

Dynamic injection allows you to modify the workflow structure at runtime based on state values.

### Basic Injection Rule

```yaml
- name: "Risk_Router"
  type: "STANDARD"
  function: "risk.calculate_risk"
  dynamic_injection:
    rules:
      - condition_key: "risk_level"
        value_match: "high"
        action: "INSERT_AFTER_CURRENT"
        steps_to_insert:
          - name: "Enhanced_Due_Diligence"
            type: "ASYNC"
            function: "compliance.enhanced_diligence"
```

### Injection Rule Properties

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `condition_key` | string | Yes | Dot-notation path to state field (e.g., "user.profile.age") |
| `value_match` | any | No | Exact value to match (use this OR value_is_not) |
| `value_is_not` | list | No | List of values to exclude (inject if NOT in list) |
| `action` | string | Yes | Currently only "INSERT_AFTER_CURRENT" supported |
| `steps_to_insert` | list | Yes | List of step configurations to inject |

### Multiple Rules

You can have multiple rules that inject different steps:

```yaml
dynamic_injection:
  rules:
    # Rule 1: High risk
    - condition_key: "risk_score"
      value_match: "high"
      action: "INSERT_AFTER_CURRENT"
      steps_to_insert:
        - name: "Enhanced_Review"
          type: "HUMAN_IN_LOOP"
          function: "review.request_enhanced"

    # Rule 2: International customer
    - condition_key: "country"
      value_is_not: ["US", "CA"]
      action: "INSERT_AFTER_CURRENT"
      steps_to_insert:
        - name: "International_Compliance"
          type: "ASYNC"
          function: "compliance.international_check"

    # Rule 3: Large amount
    - condition_key: "amount"
      value_match: "large"
      action: "INSERT_AFTER_CURRENT"
      steps_to_insert:
        - name: "Executive_Approval"
          type: "HUMAN_IN_LOOP"
          function: "approval.request_executive"
```

### Nested State Access

Use dot notation to access nested fields:

```yaml
dynamic_injection:
  rules:
    - condition_key: "applicant_profile.credit_score"
      value_match: "excellent"
      action: "INSERT_AFTER_CURRENT"
      steps_to_insert:
        - name: "Fast_Track_Approval"
          type: "STANDARD"
          function: "approval.fast_track"
```

---

## 11. Complete Example: Multi-Stage Loan Workflow

This example demonstrates all features together.

```yaml
workflow_type: "ComprehensiveLoanApplication"
workflow_version: "2.0"
initial_state_model: "state_models.ComprehensiveLoanState"

steps:
  # Stage 1: Initial Collection
  - name: "Collect_Application_Data"
    type: "STANDARD"
    function: "loan.collect_application"
    input_model: "state_models.ApplicationInput"
    compensate_function: "loan.cancel_application"
    automate_next: true

  # Stage 2: Parallel Background Checks
  - name: "Run_Background_Checks"
    type: "PARALLEL"
    tasks:
      - name: "Credit_Bureau_Check"
        function: "credit.check_credit_score"
      - name: "Fraud_Detection"
        function: "fraud.detect_fraud_patterns"
      - name: "Employment_Verification"
        function: "employment.verify_employer"
    merge_function_path: "loan.merge_background_checks"

  # Stage 3: Risk Evaluation & Branching
  - name: "Evaluate_Initial_Risk"
    type: "DECISION"
    function: "risk.evaluate_initial_risk"
    dynamic_injection:
      rules:
        # Reject low credit scores immediately
        - condition_key: "credit_score"
          value_is_not: ["excellent", "good", "fair"]
          action: "INSERT_AFTER_CURRENT"
          steps_to_insert:
            - name: "Auto_Reject"
              type: "STANDARD"
              function: "loan.auto_reject"

        # High-value loans need extra steps
        - condition_key: "loan_amount_category"
          value_match: "high"
          action: "INSERT_AFTER_CURRENT"
          steps_to_insert:
            - name: "Executive_Pre_Approval"
              type: "HUMAN_IN_LOOP"
              function: "approval.request_executive_preapproval"

  # Stage 4: Sub-Workflow for KYC
  - name: "Run_KYC_Verification"
    type: "STANDARD"
    function: "kyc.launch_kyc_workflow"
    compensate_function: "kyc.cancel_kyc"

  # Stage 5: Process KYC Results
  - name: "Process_KYC_Results"
    type: "STANDARD"
    function: "kyc.process_results"
    automate_next: true

  # Stage 6: Underwriting Router
  - name: "Route_Underwriting"
    type: "DECISION"
    function: "underwriting.determine_path"

  # Stage 7: Dynamic Underwriting (injected based on route)
  - name: "Underwriting_Injection_Point"
    type: "STANDARD"
    function: "loan.noop"
    dynamic_injection:
      rules:
        # Full underwriting for complex cases
        - condition_key: "underwriting_type"
          value_match: "full"
          action: "INSERT_AFTER_CURRENT"
          steps_to_insert:
            - name: "Full_Underwriting_Analysis"
              type: "ASYNC"
              function: "underwriting.full_analysis"
              compensate_function: "underwriting.cancel_analysis"

            - name: "Underwriter_Review"
              type: "HUMAN_IN_LOOP"
              function: "underwriting.request_review"

            - name: "Process_Underwriter_Decision"
              type: "STANDARD"
              function: "underwriting.process_decision"
              compensate_function: "underwriting.reverse_decision"

        # Simplified underwriting for standard cases
        - condition_key: "underwriting_type"
          value_match: "simplified"
          action: "INSERT_AFTER_CURRENT"
          steps_to_insert:
            - name: "Automated_Underwriting"
              type: "ASYNC"
              function: "underwriting.automated_analysis"

  # Stage 8: Final Decision
  - name: "Generate_Final_Decision"
    type: "STANDARD"
    function: "loan.generate_final_decision"
    compensate_function: "loan.reverse_final_decision"
    automate_next: true

  # Stage 9: Notification
  - name: "Send_Decision_Notification"
    type: "STANDARD"
    function: "notifications.send_decision"
```

### Supporting State Model

```python
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Dict, Any, List
from datetime import datetime

class ComprehensiveLoanState(BaseModel):
    # Initial application data
    application_id: str
    applicant_name: str
    email: EmailStr
    loan_amount: float = Field(..., gt=0)

    # Background check results
    credit_score: Optional[int] = None
    fraud_risk_score: Optional[float] = None
    employment_verified: Optional[bool] = None

    # Risk assessment
    loan_amount_category: Optional[str] = None  # low, medium, high
    risk_level: Optional[str] = None  # low, medium, high

    # KYC results
    kyc_passed: Optional[bool] = None
    kyc_completion_date: Optional[datetime] = None

    # Underwriting
    underwriting_type: Optional[str] = None  # full, simplified
    underwriting_result: Optional[str] = None

    # Final decision
    final_decision: Optional[str] = None  # approved, rejected, pending
    approval_amount: Optional[float] = None
    interest_rate: Optional[float] = None

    # Sub-workflow results
    sub_workflow_results: Dict[str, Any] = {}

    # Saga compensation log
    saga_log: Optional[List[Dict[str, Any]]] = []

condition: "applicant.age >= 21 AND applicant.income > 50000"
```

---

## 12. HTTP Integration (Polyglot Support)

The `HTTP` step type allows your workflow to interact with any external service (Node.js, Go, 3rd party APIs) without writing custom Python code.

### Basic Configuration

```yaml
- name: "Call_External_API"
  type: "HTTP"
  method: "POST"
  url: "https://api.example.com/users"
  headers:
    Content-Type: "application/json"
    Authorization: "Bearer {api_token}"  # Template substitution
  body:
    name: "{user.name}"
    email: "{user.email}"
  timeout: 10  # Seconds (default: 30)
  output_key: "api_response" # Where to store result in state
  includes: ["body", "status_code"] # Optional: Filter response fields (body, status_code, headers)
```

### Templating

You can inject values from the workflow state into the `url`, `headers`, and `body` using `{variable}` syntax. Nested values are supported via dot notation (e.g., `{user.profile.id}`).

### Output Format

The response is stored in the state under the key specified by `output_key` (default: `http_response`).

```json
"api_response": {
  "status_code": 201,
  "body": { "id": "123", "created": true },
  "headers": { "content-type": "application/json" }
}
```

---

## 13. Complete Example: Multi-Stage Loan Workflow

### Naming Conventions

- Use PascalCase for workflow types: `LoanApplication`, `CustomerOnboarding`
- Use Snake_Case_With_Capitals for step names: `Collect_Application_Data`, `Run_Credit_Check`
- Use descriptive names that indicate the action: `Validate_Input`, `Send_Notification`

### Step Organization

- Group related steps logically
- Use comments to mark stages
- Keep steps focused on a single responsibility

```yaml
steps:
  # === STAGE 1: Data Collection ===
  - name: "Collect_User_Data"
    type: "STANDARD"
    function: "data.collect"

  # === STAGE 2: Validation ===
  - name: "Validate_Input"
    type: "STANDARD"
    function: "validation.validate"

  # === STAGE 3: Processing ===
  - name: "Process_Application"
    type: "ASYNC"
    function: "processing.process"
```

### Compensation Functions

- Always provide compensation for steps that modify external state
- Test compensation functions independently
- Log compensation actions for audit trails

### Dynamic Injection

- Use sparingly - excessive injection makes workflows hard to understand
- Document injection rules clearly
- Prefer explicit steps over complex injection logic when possible

### Testing YAML Configuration

Validate your YAML files:

```bash
# Check YAML syntax
python -c "import yaml; yaml.safe_load(open('config/my_workflow.yaml'))"

# Test workflow creation
python -c "
from confucius.workflow_loader import workflow_builder
wf = workflow_builder.create_workflow('MyWorkflow', {})
print(f'Created workflow with {len(wf.workflow_steps)} steps')
"
```

---

## 13. Common Patterns

### Pattern 1: Approval Chain

```yaml
steps:
  - name: "Request_Manager_Approval"
    type: "HUMAN_IN_LOOP"
    function: "approval.request_manager"

  - name: "Check_Manager_Decision"
    type: "DECISION"
    function: "approval.check_manager_decision"
    # Jumps to director approval if manager approved

  - name: "Request_Director_Approval"
    type: "HUMAN_IN_LOOP"
    function: "approval.request_director"

  - name: "Process_Final_Approval"
    type: "STANDARD"
    function: "approval.process_final"
```

### Pattern 2: Retry with Backoff

```yaml
steps:
  - name: "Call_External_API"
    type: "ASYNC"
    function: "api.call_with_retry"
    # Implement retry logic in the Celery task
```

```python
from celery import shared_task
from tenacity import retry, stop_after_attempt, wait_exponential

@shared_task
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def call_with_retry(state_dict):
    response = external_api.call(state_dict['request_data'])
    return {"api_response": response}
```

### Pattern 3: Scatter-Gather

```yaml
steps:
  # Scatter: Send work to multiple services
  - name: "Dispatch_To_Services"
    type: "PARALLEL"
    tasks:
      - name: "Service_A"
        function: "services.call_service_a"
      - name: "Service_B"
        function: "services.call_service_b"
      - name: "Service_C"
        function: "services.call_service_c"
    merge_function_path: "services.gather_results"

  # Gather: Process combined results
  - name: "Process_Combined_Results"
    type: "STANDARD"
    function: "services.process_combined"
```

### Pattern 4: Conditional Pipeline

```yaml
steps:
  - name: "Classify_Request"
    type: "DECISION"
    function: "classifier.classify"
    # Sets request_type: simple, moderate, complex

  - name: "Route_By_Type"
    type: "STANDARD"
    function: "router.noop"
    dynamic_injection:
      rules:
        - condition_key: "request_type"
          value_match: "simple"
          action: "INSERT_AFTER_CURRENT"
          steps_to_insert:
            - name: "Simple_Processing"
              type: "STANDARD"
              function: "processing.simple"

        - condition_key: "request_type"
          value_match: "moderate"
          action: "INSERT_AFTER_CURRENT"
          steps_to_insert:
            - name: "Moderate_Processing"
              type: "ASYNC"
              function: "processing.moderate"

        - condition_key: "request_type"
          value_match: "complex"
          action: "INSERT_AFTER_CURRENT"
          steps_to_insert:
            - name: "Complex_Processing"
              type: "PARALLEL"
              tasks:
                - name: "Analyze"
                  function: "processing.analyze"
                - name: "Validate"
                  function: "processing.validate"
```

---

## 14. Advanced Node Types (The "Gears")

These nodes provide high-level control flow and orchestration capabilities.

### FIRE_AND_FORGET: Independent Workflows
Spawns another workflow that runs independently without pausing the current one.

```yaml
- name: "Send_Confirmation"
  type: "FIRE_AND_FORGET"
  target_workflow_type: "EmailDelivery"
  initial_data_template:
    user_id: "{{state.user_id}}"
    subject: "Order {{state.order_id}} confirmed"
```

### LOOP: Iterative Logic
Executes a sequence of steps repeatedly.

#### Iterate Mode (Lists)
```yaml
- name: "Process_Batch"
  type: "LOOP"
  mode: "ITERATE"
  iterate_over: "state.items"
  item_var_name: "loop_item" # Available in loop body as state.loop_item
  loop_body:
    - name: "Validate_Item"
      function: "utils.validate"
    - name: "Process_Item"
      function: "utils.process"
```

#### While Mode (Conditions)
```yaml
- name: "Wait_For_Completion"
  type: "LOOP"
  mode: "WHILE"
  while_condition: "state.status != 'READY'"
  max_iterations: 10
  loop_body:
    - name: "Poll_Status"
      function: "utils.poll"
```

### CRON_SCHEDULER: Dynamic Scheduling
Registers a new recurring workflow schedule from within a step.

```yaml
- name: "Schedule_Weekly_Report"
  type: "CRON_SCHEDULER"
  schedule: "0 0 * * MON" # Standard cron expression
  target_workflow_type: "ReportGenerator"
  schedule_name: "report_{{state.user_id}}"
  initial_data_template:
    user_id: "{{state.user_id}}"
```

---

## 15. Troubleshooting YAML Configuration

### Common Errors

**Error**: `ValueError: Workflow type 'MyWorkflow' not found in registry`

**Solution**: Add your workflow to `workflow_registry.yaml`:
```yaml
workflows:
  - type: "MyWorkflow"
    config_file: "config/my_workflow.yaml"
    initial_state_model: "state_models.MyWorkflowState"
```

**Error**: `ImportError: cannot import name 'my_function'`

**Solution**: Verify the function path in your YAML matches the actual Python module structure:
```yaml
function: "workflow_utils.my_function"  # Must exist in workflow_utils.py
```

**Error**: `KeyError: 'steps'`

**Solution**: Ensure your workflow YAML has a `steps` list:
```yaml
workflow_type: "MyWorkflow"
initial_state_model: "state_models.MyState"
steps:  # Required
  - name: "First_Step"
    type: "STANDARD"
    function: "utils.first_step"
```

**Error**: `Dynamic injection condition not triggering`

**Solution**: Check the exact value match:
```yaml
# State value: "high_risk" (with underscore)
# Config: value_match: "high-risk"  # Wrong!
# Config: value_match: "high_risk"  # Correct
```

---

For implementation details and architecture information, see:
- [Usage Guide](USAGE_GUIDE.md)
- [Technical Documentation](TECHNICAL_DOCUMENTATION.md)
- [API Reference](API_REFERENCE.md)