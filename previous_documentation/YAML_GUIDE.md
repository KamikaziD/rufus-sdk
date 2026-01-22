# Rufus SDK - YAML Configuration Reference

This document provides a complete reference for defining and configuring workflows using the Rufus SDK's YAML-based system.
It covers all configuration options, step types, and advanced features.

## 1. The Registry: workflow_registry.yaml

All Rufus workflows must be registered in a central registry file. This file tells the WorkflowBuilder what workflows are available,
where their definitions are, and what data structure they use.

Each entry in the workflows list requires three keys:

```
type: A unique string identifier for the workflow (e.g., LoanApplication).
config_file: The path to the YAML file containing the workflow's step definitions. This path is relative to the location of
the registry file.
initial_state_model: The full Python import path to the Pydantic BaseModel that defines the state for this workflow
(e.g., "my_app.state_models.LoanApplicationState").
```
Additionally, the workflow_registry.yaml can declare external package dependencies using the requires key. These
packages will be scanned by Rufus for additional workflow steps and definitions.

**Example:**

```
# config/workflow_registry.yaml
workflows:
```
- type: "LoanApplication"
description: "A complex workflow for processing a loan application."
config_file: "loan_workflow.yaml"
initial_state_model: "my_app.state_models.LoanApplicationState"
- type: "CustomerOnboarding"
description: "A simple workflow for onboarding a new customer."
config_file: "my_app.onboarding_workflow.yaml"
initial_state_model: "my_app.state_models.OnboardingState"

```
requires: # Optional: list of packages to auto-discover steps/workflows from
```
- rufus-my-custom-package _# Rufus will look for entry points and modules in 'rufus_my_custom_pac_
- another-workflow-extension _# Can be any installed package_

## 2. Anatomy of a Workflow Definition File

Each workflow has its own YAML file that defines its steps. The file contains top-level keys and a list of steps.

### Top-Level Keys

```
workflow_type: (Required) Must match the type in the registry.
workflow_version: (Optional) Version of this specific workflow definition.
initial_state_model: (Required) Python import path to the Pydantic model for the workflow's state.
description: (Optional) Human-readable description.
steps: (Required) A list of step definitions.
```
### Anatomy of a Step

Each item in the steps list is a dictionary that defines a single unit of work. The specific properties available depend on the type
of the step. Refer to **Section 3: Step Execution Types Reference** for details on each type and its configuration.

```
name: (Required) A unique string name for the step within the workflow (e.g., "Collect_Application_Data").
type: (Required) Defines how the step is executed. See Section 3 for details on available types and their specific
configuration.
function: (Conditional) The full Python import path to the function that contains the business logic for this step (e.g.,
"my_app.workflow_steps.collect_application_data"). Required for STANDARD, DECISION, HUMAN_IN_LOOP
types. For ASYNC and HTTP types, this points to the task implementation if any.
```

```
compensate_function: (Optional) The full Python import path to the function that contains the compensation logic for
this step, used in Saga patterns. Applicable for STANDARD steps that are designed to be compensatable.
input_model: (Optional, Recommended) The import path to a Pydantic model defining the expected inputs for this step.
This enables automatic validation and API schema generation.
required_input: (Optional, Legacy) A simple list of required input keys. Use input_model for new development.
automate_next: (Optional) A boolean (true/false) flag. If true, the WorkflowEngine will immediately execute the next
step using the output of the current step as input, without waiting for another next_step call. Defaults to false.
dependencies: (Optional, for documentation/visualization) A list of step names that should complete before this one. The
engine executes steps in order unless altered by directives.
dynamic_injection: (Optional) Configuration for dynamically injecting new steps at runtime. See Section 7 for details.
routes: (Optional) For DECISION type steps, defines declarative routing rules.
```
## 3. Step Execution Types Reference

The type key controls the execution behavior of a step and dictates its available configuration properties.

```
Type Description
```
```
function
key
required?
```
```
Example YAML Configuration
```
#### STANDARD

```
The default type. Executes
the specified function
synchronously.
```
```
Yes
yaml<br>name: "Process_Data"<br>type: "STANDARD"
<br>function: "my_app.data_processor.process"
```
#### DECISION

```
Functionally similar to
STANDARD, but signifies its
primary purpose is to
evaluate state and alter flow.
```
```
Yes
```
```
yaml<br>name: "Evaluate_Risk"<br>type: "DECISION"
<br>function: "my_app.risk_engine.evaluate"
<br>routes:<br> - condition: "state.risk_score >
700"<br> next_step: "Approve_Loan"
```
#### ASYNC

```
For long-running tasks. The
specified function (which
must be an importable task)
is dispatched to an
ExecutionProvider (e.g.,
Celery). Parent workflow
waits.
```
```
Yes
```
```
yaml<br>name: "Send_Email"<br>type: "ASYNC"
<br>function:
"my_app.email_tasks.send_welcome_email"
```
```
PARALLEL Executes multiple ASYNC
tasks concurrently. Parent
workflow waits for all tasks
to complete and merges
results.
```
```
No yaml<br>name: "Process_Multi_API"<br>type:
"PARALLEL"<br>tasks:<br> - name: "Call_API_A"<br>
function: "my_app.api_client.call_a"<br> - name:
"Call_API_B"<br> function:
"my_app.api_client.call_b"
<br>merge_function_path:
"my_app.utils.merge_api_results"
<br>timeout_seconds: 60 # Optional: Max duration
for all parallel tasks to
complete<br>allow_partial_success: false #
Optional: If true, workflow proceeds even if some
tasks fail<br>
```
```
### PARALLEL Step Behavior Notes:
```
```
⚠ Non-Determinism Warning: When using async executors
(e.g., CeleryExecutor), the order in which results are
returned by parallel tasks and merged is non-deterministic. Do
not rely on a specific order of task completion or result
processing for the default merge.
```
```
Best Practices for Parallel Tasks:
```
1. **Non-Overlapping Keys:** Design parallel tasks to return
results with non-overlapping keys to avoid silent data loss
during the default shallow merge.
2. **Custom Merge Functions:** For complex merging logic or
deterministic conflict resolution, use a merge_function_path


```
to specify a custom Python callable.
```
3. **Order Agnostic:** Do not rely on the execution or completion
order of individual parallel tasks.

```
Default Merge Behavior:
When merge_function_path is not specified, Rufus performs
a shallow merge (dict.update()) of all task results into the
workflow state. In case of key collisions, the last-write-wins.
Rufus will log a WARNING message when a key collision occurs
during a default merge, indicating which key was overwritten.
```
```
Task Mutation Guidelines:
Individual tasks executed in parallel receive a copy of the
workflow state (as a dictionary). They cannot directly mutate
the original WorkflowEngine's state object. Any changes a
task intends to make to the workflow state must be returned as
part of its result, which is then processed by the merge logic.
```
```
Merge Function Error Handling:
If a custom merge_function (specified by
merge_function_path) raises an exception during execution,
the workflow will transition to a FAILED status. The results from
the individual parallel tasks are preserved in the execution logs
for debugging. Compensation functions for prior steps are not
triggered, as the individual tasks themselves are considered to
have completed successfully before the merge failure.
```
```
Custom Merge Function Signature:
A custom merge function should have the following signature:
python<br>def custom_merge_logic(<br>
task_results: Dict[str, Any], # Dictionary
mapping task name to its return value<br>
current_state: Dict[str, Any] # The current
workflow state (as a dict) before merging<br>) ->
Dict[str, Any]:<br> """<br> Args:<br>
task_results: A dictionary where keys are the
names of the parallel tasks<br> and values are
their respective return values.<br>
current_state: The workflow's state as it was
*before* the parallel step results were merged.
<br><br> Returns:<br> A dictionary of updates to
be applied to the workflow's state. These
updates<br> will be merged into the workflow's
state after the function completes.<br> """<br> #
Example: Summing numeric results<br> total_score
= sum(res.get('score', 0) for res in
task_results.values() if isinstance(res, dict))
<br> return {"total_score": total_score}<br>
```
#### HUMAN_IN_LOOP

```
Pauses the workflow
indefinitely for external input.
The function should raise a
WorkflowPauseDirective.
```
```
Yes
```
```
yaml<br>name: "Request_Approval"<br>type:
"HUMAN_IN_LOOP"<br>function:
"my_app.human_tasks.request_manager_approval"
```
#### HTTP

```
Makes an HTTP request to
an external API. Uses the
ExecutionProvider to
dispatch. Parent workflow
waits.
```
```
No
```
```
yaml<br>name: "Fetch_User_Profile"<br>type:
"HTTP"<br>method: "GET"<br>url:
"https://api.example.com/users/{{state.user_id}}"
<br>output_key: "user_profile_data"
```
**FIRE_AND_FORGET** Spawns a new independent
workflow that runs in the

```
No yaml<br>name: "Log_Audit_Event"<br>type:
"FIRE_AND_FORGET"<br>target_workflow_type:
```

```
background without blocking
the parent.
```
```
"AuditEventLogging"<br>initial_data_template:<br>
event_type: "UserLogin"
```
#### LOOP

```
Executes a body of steps
repeatedly based on a list or
a condition.
```
```
No
```
```
yaml<br>name: "Process_Items"<br>type: "LOOP"
<br>mode: "ITERATE"<br>iterate_over:
"state.items_to_process"<br>loop_body:<br> -
name: "Item_Step"<br> type: "STANDARD"<br>
function: "my_app.item_processor.process_single"
```
#### CRON_SCHEDULER

```
Registers a new recurring
workflow schedule. No
```
```
yaml<br>name: "Schedule_Report"<br>type:
"CRON_SCHEDULER"<br>schedule_name:
"monthly_summary"<br>cron_expression: "0 0 1 * *"
# 1st of every month<br>target_workflow_type:
"GenerateMonthlyReport"
```
## 4. Input Validation

You can define the inputs required for a step using a Pydantic model. This is the recommended method.

### input_model (Recommended)

You provide the full Python import path to a Pydantic BaseModel. Rufus uses this model to validate user_input automatically.

**Benefits:**

```
Automatic Type Coercion: Input {"age": "30"} will be converted to the integer 30 if age is int.
Rich Validation: You can use all of Pydantic's validators (ge, le, pattern, etc.).
API Schema Generation: If using rufus-server, this model generates JSON Schema for API documentation and dynamic
UI forms.
```
**Example (my_workflow.yaml):**

```
steps:
```
- name: "Create_User"
type: "STANDARD"
function: "my_app.funcs.create_user"
input_model: "my_app.models.CreateUserInput" _# Points to a Pydantic model_

**Python (my_app/models.py):**

```
from pydantic import BaseModel, Field
```
```
class CreateUserInput(BaseModel):
name: str
age: int = Field(..., ge= 18 )
email: str
```
### required_input (Legacy)

This is a simple list of string keys that must be present in the input data. It does not perform any type checking or rich validation. It
is maintained for backward compatibility.

```
steps:
```
- name: "Create_User"
type: "STANDARD"
function: "my_app.funcs.create_user"
required_input: ["name", "age", "email"]

## 5. Saga Pattern Configuration

The Saga pattern provides automatic rollback through compensation functions.


### Basic Saga Configuration

Add a compensate_function to any STANDARD step in your workflow YAML that requires compensation logic. These steps
should be designed as CompensatableSteps.

```
steps:
```
- name: "Reserve_Inventory"
type: "STANDARD"
function: "my_app.inventory.reserve_items"
compensate_function: "my_app.inventory.release_items" _# Function to call on rollback_
- name: "Charge_Payment"
type: "STANDARD"
function: "my_app.payment.charge_customer"
compensate_function: "my_app.payment.refund_customer"

**Compensation Function Signature:**

Compensation functions are standard Python callables that receive the state and context objects:

```
# my_app/payment.py
from rufus.models import BaseModel, StepContext
from typing import Dict, Any
```
```
def refund_customer(state: BaseModel, context: StepContext) -> Dict[str, Any]:
"""
Compensation function that undoes the 'charge_customer' action.
"""
# Logic to refund the customer, e.g., calling an external payment API.
# Access state to get transaction_id, customer_id, etc.
print(f"Refunding transaction {state.transaction_id} for {state.customer_id}")
return {"refunded": True, "transaction_id": state.transaction_id}
```
### Enabling Saga Mode

Saga mode must be explicitly enabled on a WorkflowEngine instance:

```
# In your Python application code
workflow_instance.enable_saga_mode()
```
## 6. Sub-Workflow Configuration

Sub-workflows allow you to compose complex workflows from smaller, reusable workflows. Rufus provides robust mechanisms for
managing the lifecycle and status of child workflows.

### Parent Workflow Step Function

In a step function of the parent workflow, raise a StartSubWorkflowDirective:

```
# my_app/loan_steps.py
from rufus.models import StartSubWorkflowDirective, BaseModel, StepContext
from my_app.state_models import LoanApplicationState
```
```
def launch_kyc_workflow(state: LoanApplicationState, context: StepContext):
"""Launches KYC verification as a child workflow."""
raise StartSubWorkflowDirective(
workflow_type="KYC_Process", # Type defined in registry
initial_data={
"user_id": state.applicant_profile.user_id,
"document_url": state.applicant_profile.id_document_url
```

#### },

```
data_region="eu-west-1" # Optional: route child to specific region
)
```
The parent workflow will automatically transition to PENDING_SUB_WORKFLOW status. The child workflow's status changes are
then reported back to the parent, causing the parent's status to dynamically update to reflect the child's state.

**Parent Workflow Statuses during Sub-Workflow Execution:**

```
PENDING_SUB_WORKFLOW : The child workflow has been dispatched and is currently active or processing.
FAILED_CHILD_WORKFLOW : The child workflow encountered an error and failed. The parent's metadata will contain
failed_child_id and failed_child_status.
WAITING_CHILD_HUMAN_INPUT : The child workflow has paused, waiting for human input. The parent's metadata will
contain waiting_child_id and waiting_child_step.
```
**Accessing Sub-Workflow Results:**

When a child workflow successfully completes, its final state (and any explicit result returned by its last step) will be merged into
the parent's state within parent.state.sub_workflow_results. This dictionary is keyed by the child workflow's ID.

```
def process_kyc_results(state: LoanApplicationState, context: StepContext):
"""Processes results from the completed KYC sub-workflow."""
# Access the child's full final state
kyc_final_state = state.sub_workflow_results.get('<child_workflow_id>', {}).get('state', {})
```
```
# Or, if the child returned an explicit final result from its last step:
kyc_final_result = state.sub_workflow_results.get('<child_workflow_id>', {}).get('final_result
```
```
if kyc_final_state.get('kyc_status') == "APPROVED":
state.kyc_approved = True
return {"message": "KYC approved."}
else:
state.kyc_approved = False
return {"message": "KYC review required."}
```
## 7. Dynamic Step Injection

Dynamic step injection allows you to modify the workflow's sequence of steps at runtime based on current state or business rules.

**YAML Example:**

```
steps:
```
- name: "Evaluate_Risk_Score"
type: "STANDARD"
function: "my_app.risk.evaluate"
dynamic_injection:
rules:
- condition_key: "risk_level" _# Path in workflow state_
value_match: "high"
action: "INSERT_AFTER_CURRENT"
steps_to_insert: _# Steps to be injected_
- name: "Manual_Review"
type: "HUMAN_IN_LOOP"
function: "my_app.human.request_review"
- name: "Notify_Fraud_Team"
type: "FIRE_AND_FORGET"
target_workflow_type: "FraudNotification"

**Rule Properties:**

```
condition_key: (Required) A dot-notation path within the workflow state (e.g., "user.profile.age").
value_match: (Conditional) Inject if condition_key equals this value.
```

```
value_is_not: (Conditional) Inject if condition_key does NOT equal any of these values.
action: (Required) Currently only "INSERT_AFTER_CURRENT" is supported.
steps_to_insert: (Required) A list of step configurations to insert.
```
## 8. HTTP Step Configuration

The HTTP step type allows your workflow to interact with any external service without writing custom Python wrappers.

```
steps:
```
- name: "Fetch_Product_Details"
type: "HTTP"
method: "GET"
url: "https://api.ecommerce.com/products/{{state.product_id}}" _# Templating with Jinja2 syntax_
headers:
Authorization: "Bearer {{secrets.ECOMMERCE_API_TOKEN}}" _# Access secrets_
Content-Type: "application/json"
query_params: _# Optional: query parameters_
locale: "en-US"
body: _# Optional: request body (will be JSON for json/application-json content types)_
some_field: "some_value"
output_key: "product_api_response" _# Key to store the response in workflow state_
includes: ["body", "status_code"] _# Optional: Filter response fields to save_
retry_policy: _# Optional: specific retry policy for this step_
max_attempts: 3
delay_seconds: 5
timeout_seconds: 30 _# Optional: timeout for the HTTP request_

**Templating:**

```
Uses Jinja2-like syntax ({{variable}}) for dynamic values in url, headers, body, and query_params.
Context for templating is the entire workflow state and available secrets.
```
## 9. Advanced Node Types (The "Gears")

These nodes provide high-level control flow and orchestration capabilities.

### FIRE_AND_FORGET

Spawns an independent workflow that runs in the background without pausing the current workflow. The parent workflow only
retains a reference (ID) to the spawned workflow.

```
steps:
```
- name: "Send_Confirmation_Email"
type: "FIRE_AND_FORGET"
target_workflow_type: "EmailDelivery" _# Workflow to spawn_
initial_data_template: _# Initial data for the spawned workflow_
user_id: "{{state.user.id}}"
email_type: "order_confirmation"
recipient: "{{state.user.email}}"

### LOOP

Executes a sequence of steps repeatedly.

**Iterate Mode (Lists)**

```
steps:
```
- name: "Process_Order_Items"
type: "LOOP"
mode: "ITERATE"
iterate_over: "state.order_details.items" _# Path to a list in the workflow state_
item_var_name: "current_item" _# Variable name for each item within loop_body context_


```
max_iterations: 100 # Safety limit
loop_body: # Steps to execute for each item
```
- name: "Update_Inventory"
type: "STANDARD"
function: "my_app.inventory.update_stock"
- name: "Apply_Discount"
type: "STANDARD"
function: "my_app.pricing.apply_item_discount"

**While Mode (Conditions)**

```
steps:
```
- name: "Poll_API_Until_Ready"
type: "LOOP"
mode: "WHILE"
while_condition: "state.api_status != 'READY'" _# Condition to continue loop_
max_iterations: 10 _# Safety limit_
loop_body:
- name: "Call_Status_Endpoint"
type: "HTTP"
method: "GET"
url: "https://api.example.com/status"
output_key: "api_status_response"
- name: "Extract_Status"
type: "STANDARD"
function: "my_app.utils.extract_api_status"

### CRON_SCHEDULER

Registers a new recurring workflow schedule. Requires an ExecutionProvider that supports scheduling (e.g.,
CeleryExecutor integrated with Celery Beat).

```
steps:
```
- name: "Schedule_Weekly_Report"
type: "CRON_SCHEDULER"
schedule_name: "weekly_report_for_user_{{state.user_id}}" _# Unique name for the schedule_
target_workflow_type: "GenerateReport" _# Workflow to be triggered_
cron_expression: "0 9 * * MON" _# Standard cron expression (e.g., "0 9 * * MON" for 9 AM every M_
initial_data_template: _# Initial data for the triggered workflow_
user_id: "{{state.user_id}}"
report_period: "last_week"

## 10. Common Patterns

### Pattern 1: Approval Chain

```
steps:
```
- name: "Request_Manager_Approval"
type: "HUMAN_IN_LOOP"
function: "my_app.approvals.request_manager_approval"
- name: "Check_Manager_Decision"
type: "DECISION"
function: "my_app.approvals.check_manager_decision"
routes:
- condition: "state.manager_decision == 'APPROVED'"
next_step: "Process_Director_Approval"
- default: "Notify_Rejection"


### Pattern 2: Retry with Exponential Backoff (in Async Steps)

Retry logic is typically handled within the ExecutionProvider or within the Celery task itself using libraries like tenacity.

```
# my_app/tasks.py
from celery import shared_task
from tenacity import retry, stop_after_attempt, wait_exponential
```
```
@shared_task(bind=True)
@retry(stop=stop_after_attempt( 5 ), wait=wait_exponential(multiplier= 1 , min= 2 , max= 10 ))
def call_external_api_with_retry(self, state_data: Dict[str, Any]):
# ... logic to call API ...
response = requests.post("https://api.example.com/unreliable", json=state_data)
response.raise_for_status()
return response.json()
```
### Pattern 3: Scatter-Gather

```
steps:
```
- name: "Dispatch_To_Services"
type: "PARALLEL"
tasks:
- name: "Call_Service_A"
function: "my_app.services.call_service_a"
- name: "Call_Service_B"
function: "my_app.services.call_service_b"
merge_function_path: "my_app.utils.merge_service_results" _# Custom function to combine results_

## 11. Troubleshooting YAML Configuration

### Common Errors

```
Error: Workflow type 'MyWorkflow' not found in registry : Ensure your workflow is listed in
workflow_registry.yaml and the type matches exactly.
ImportError: cannot import name 'my_function' : Verify the function or input_model paths in your YAML
match the actual Python module structure and are importable from your application's Python path.
Missing 'steps' section : Ensure your workflow YAML file has a steps key with a list of step definitions.
Dynamic injection condition not triggering : Double-check condition_key and value_match (or
value_is_not) for exact values and correct paths in state.
```
### Validation

Use the Rufus CLI to validate your YAML files:

```
rufus validate config/my_workflow.yaml
```
