# Rufus Workflow Engine - Usage Guide

This comprehensive guide will walk you through all aspects of using the Rufus workflow SDK,
from basic concepts to advanced patterns.

## Table of Contents

1. Getting Started
2. Core Concepts
3. Providers and Implementations
4. Defining Workflows in YAML
5. Implementing Step Functions
6. Running Workflows with the SDK
7. Using the CLI Tool
8. Step Types Reference
9. Advanced Features
10. Best Practices
11. Testing Workflows

## 1. Getting Started

### Prerequisites

```
Python 3.10+
pip for package installation
```
### Installation

Install the core Rufus SDK:

```
pip install rufus
```
For specific functionalities like a FastAPI server or Celery integration, install optional
dependencies:

```
# For the optional FastAPI server components (installs uvicorn, fastap
pip install rufus[server]
```
```
# If you plan to use Celery for async execution
pip install rufus[celery]
```
```
# For development and testing tools (installs pytest, typer, etc.)
pip install rufus[dev]
```

## 2. Core Concepts

### Workflows

A **workflow** is a series of steps that execute to accomplish a business process. Each
workflow has:

```
A unique type (e.g., "LoanApplication", "UserOnboarding").
A state - data that persists throughout execution (a Pydantic model).
A list of steps - units of work to be executed.
A status - indicates the current execution state.
```
### Workflow States

```
Status Description
ACTIVE Workflow is running and ready for the next step
PENDING_ASYNC Waiting for an async task to complete
```
```
PENDING_SUB_WORKFLOW
Waiting for a child workflow to complete or report a
non-blocking status
FAILED_CHILD_WORKFLOW A child workflow failed during execution
WAITING_CHILD_HUMAN_INPUT A child workflow is paused awaiting human input
WAITING_HUMAN Paused, awaiting human input (e.g., via a UI)
```
```
COMPLETED All steps finished successfully
FAILED An error occurred during execution
```
```
FAILED_ROLLED_BACK
Failed and saga compensation successfully rolled
back changes
```
### Steps

A **step** is a single unit of work in a workflow. Steps can:

```
Execute synchronous Python functions.
Dispatch async tasks to an ExecutionProvider.
Run multiple tasks in parallel.
Pause for human review.
Launch sub-workflows (nested execution).
Make decisions and branch the workflow.
```
### State Management

Each workflow has a **state** , which is a Pydantic model that holds all the data for that workflow
execution. The state:


```
Is validated on every update.
Persists between step executions (managed by a PersistenceProvider).
Can be accessed and modified by any step.
Is serialized to JSON for storage.
```
## 3. Providers and Implementations

Rufus is built with a pluggable architecture, meaning its core logic is independent of how
persistence, execution, and observability are handled. This is achieved through **Provider
Interfaces** (defined in rufus.providers.*) and their **Implementations** (found in
rufus.implementations.*).

You inject specific provider implementations into the WorkflowEngine to configure its
behavior.

```
PersistenceProvider : Handles saving and loading workflow states.
InMemoryPersistence (for testing/dev)
PostgresProvider (for production durability)
ExecutionProvider : Manages how workflow steps are executed (synchronously,
asynchronously, in parallel).
SyncExecutor (for testing/dev)
CeleryExecutor (for distributed, scalable execution)
WorkflowObserver : Provides hooks for reacting to workflow events (logging, metrics,
real-time updates).
LoggingObserver (for basic console logging)
ExpressionEvaluator : Used for evaluating conditions in DECISION steps or
dynamic injection.
SimpleExpressionEvaluator
TemplateEngine : Used for rendering dynamic content, like HTTP step bodies or
FireAndForget initial data.
Jinja2TemplateEngine
```
## 4. Defining Workflows in YAML

Rufus uses YAML for defining workflows. This provides a human-readable, Git-friendly, and
declarative way to describe your business processes.

### Example: Simple Welcome Workflow (config/welcome_flow.yaml)

```
# config/welcome_flow.yaml
workflow_type: "WelcomeFlow"
initial_state_model: "pydantic.BaseModel" # A simple Pydantic model fo
description: "A simple workflow to welcome new users."
```
```
steps:
```
- name: "Log_Start"
type: "STANDARD"


```
function: "my_app.workflow_steps.log_message"
automate_next: true # Automatically proceed to the next step
```
- name: "Greet_User"
type: "STANDARD"
function: "my_app.workflow_steps.greet_user"
input_model: "my_app.workflow_steps.UserNameInput" _# Expects speci_

### Workflow Registry (config/workflow_registry.yaml)

All your workflow YAML files must be registered in a central workflow_registry.yaml file.
This file also declares any package dependencies for auto-discovery of steps and workflows.

```
# config/workflow_registry.yaml
workflows:
```
- type: "WelcomeFlow"
description: "A simple welcome workflow."
config_file: "welcome_flow.yaml" _# Relative path to the workflow Y_
initial_state_model: "my_app.workflow_steps.WelcomeState" _# Full i_

```
requires: # Optional: list of packages to auto-discover steps/workflow
```
- rufus-example-package

## 5. Implementing Step Functions

Step functions are standard Python callables that implement the actual business logic for
each step. They receive the current workflow state (a Pydantic model) and a context
object (containing metadata).

### Example: (my_app/workflow_steps.py)

```
# my_app/workflow_steps.py
from pydantic import BaseModel, Field
from rufus.models import StepContext
from typing import Optional
```
```
class WelcomeState(BaseModel):
message: str = "Default Welcome Message"
user_name: Optional[str] = None
greeting_sent: bool = False
```
```
class UserNameInput(BaseModel):
name: str = Field(..., description="The user's name.")
```

```
def log_message(state: WelcomeState, context: StepContext):
"""Logs the initial message from the state."""
print(f"[{context.workflow_id}] Log Start: {state.message}")
# You can return a dict to update the state, or modify 'state' dir
return {"log_entry": f"Workflow started at {context.workflow_id}"}
```
```
def greet_user(state: WelcomeState, context: StepContext):
"""Greets the user based on input and updates state."""
user_name = "Guest"
if context.validated_input and isinstance(context.validated_input,
user_name = context.validated_input.name
```
```
state.user_name = user_name
state.greeting_sent = True
print(f"[{context.workflow_id}] Hello, {user_name}!")
return {"greeting_message": f"Hello, {user_name}!"}
```
## 6. Running Workflows with the SDK

The Rufus SDK allows you to embed workflow execution directly into your Python application.

```
# main.py or your application entry point
import os
import sys
import shutil
from pathlib import Path
from rufus.engine import WorkflowEngine
from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.memory import InMemoryPersisten
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserve
from rufus.implementations.expression_evaluator import SimpleExpressio
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngi
```
```
# --- 1. Set up your workflow registry (for this example, we create it
# In a real app, you would have your config/ directory and provide its
config_path = Path("./config") # Assuming a 'config' directory exists
config_path.mkdir(exist_ok=True)
Path("./my_app").mkdir(exist_ok=True) # Ensure 'my_app' directory for
```
```
# Write welcome_flow.yaml
(config_path / "welcome_flow.yaml").write_text("""
workflow_type: \"WelcomeFlow\"
initial_state_model: \"my_app.workflow_steps.WelcomeState\"
description: \"A simple workflow to welcome new users.\"
```

steps:

- name: \"Log_Start\"
type: \"STANDARD\"
function: \"my_app.workflow_steps.log_message\"
automate_next: true
- name: \"Greet_User\"
type: \"STANDARD\"
function: \"my_app.workflow_steps.greet_user\"
input_model: \"my_app.workflow_steps.UserNameInput\"
""")

_# Write workflow_registry.yaml_
(config_path / "workflow_registry.yaml").write_text("""
workflows:

- type: \"WelcomeFlow\"
description: \"A simple welcome workflow.\"
config_file: \"welcome_flow.yaml\" # Relative path to the workflow
initial_state_model: \"my_app.workflow_steps.WelcomeState\" # Full
""")

_# Write my_app/workflow_steps.py_
(Path("./my_app") / "workflow_steps.py").write_text("""
from pydantic import BaseModel, Field
from rufus.models import StepContext
from typing import Optional

class WelcomeState(BaseModel):
message: str = "Default Welcome Message"
user_name: Optional[str] = None
greeting_sent: bool = False

class UserNameInput(BaseModel):
name: str = Field(..., description="The user's name.")

def log_message(state: WelcomeState, context: StepContext):
print(f"[SDK] ({context.workflow_id}) Log Start: {state.message}")
return {"log_entry": f"Workflow started at {context.workflow_id}"}

def greet_user(state: WelcomeState, context: StepContext):
user_name = "Guest"
if context.validated_input and isinstance(context.validated_input,
user_name = context.validated_input.name

state.user_name = user_name
state.greeting_sent = True


print(f"[SDK] ({context.workflow_id}) Hello, {user_name}!")
return {"greeting_message": f"Hello, {user_name}!"}
""")

_# Ensure 'my_app' is in Python path for dynamic imports_
sys.path.insert( 0 , str(Path(".")))

_# --- 2. Initialize SDK Providers ---
# Choose your desired implementations for persistence, execution, and_
persistence_provider = InMemoryPersistence() _# For development and tes
# persistence_provider = PostgresProvider(db_url="postgresql://user:pa_
execution_provider = SyncExecutor() _# For synchronous executi
# execution_provider = CeleryExecutor(celery_app=my_celery_app_instanc_
workflow_observer = LoggingObserver() _# Logs events to console_
expression_evaluator_cls = SimpleExpressionEvaluator
template_engine_cls = Jinja2TemplateEngine

_# --- 3. Instantiate WorkflowBuilder ---_
workflow_builder = WorkflowBuilder(registry_path=str(config_path / "wo

_# --- 4. Create and Run a Workflow ---_
initial_state_data = {"message": "Hello from Rufus SDK!"}
workflow_instance = workflow_builder.create_workflow(
workflow_type="WelcomeFlow",
initial_data=initial_state_data,
persistence_provider=persistence_provider,
execution_provider=execution_provider,
workflow_builder=workflow_builder,
expression_evaluator_cls=expression_evaluator_cls,
template_engine_cls=template_engine_cls,
workflow_observer=workflow_observer
)

print(f"\n--- Starting Workflow: {workflow_instance.id} ---")
print(f"Current Status: {workflow_instance.status}")
print(f"Current Step: {workflow_instance.current_step_name}")

_# Execute steps until completion_
while workflow_instance.status not in ["COMPLETED", "FAILED", "FAILED_
current_step_name = workflow_instance.current_step_name
print(f"\nExecuting step: {current_step_name}")

user_input = {}
if current_step_name == "Greet_User":
user_input = {"name": "Alice"} _# Provide input for this step_


```
# next_step handles state transitions and auto-advancement
workflow_instance.next_step(user_input=user_input)
```
```
print(f"Status after step: {workflow_instance.status}")
if workflow_instance.status != "COMPLETED":
print(f"Next step: {workflow_instance.current_step_name}")
```
```
print(f"\n--- Workflow Finished ({workflow_instance.status}) ---")
print(f"Final state: {workflow_instance.state.model_dump_json(indent= 2
```
```
# --- Cleanup temporary config files ---
shutil.rmtree(config_path)
shutil.rmtree(Path("./my_app"))
print("\nCleaned up temporary example files.")
```
## 7. Using the CLI Tool

The Rufus CLI provides convenient commands for validating and running workflows.

### Validate Workflow YAML

Check your workflow definition for syntax errors and basic structural integrity:

```
rufus validate config/my_workflow.yaml
```
### Run Workflow Locally

Execute a workflow from your terminal using in-memory persistence and synchronous
execution:

```
rufus run config/my_workflow.yaml -d '{"user_id": "U123", "amount": 10
```
This is ideal for rapid prototyping and testing during development.

## 8. Step Types Reference

Rufus supports a rich set of step types to cover diverse orchestration needs. For detailed
configuration options of each step type, please refer to the YAML Guide.

```
Type Description Usage (YAML)
```
```
STANDARD
Executes a Python function
synchronously.
```
```
function:
"my_app.steps.process_data"
```

#### ASYNC

```
Dispatches a Python
function to an
ExecutionProvider (e.g.,
Celery) for background
processing. Parent workflow
waits.
```
```
function:
"my_app.tasks.perform_long_op"
```
#### PARALLEL

```
Executes multiple ASYNC
tasks concurrently with
timeouts, partial success
handling, and conflict
detection during merge.
```
```
tasks: [...]
merge_function_path:
"my_app.utils.merge_results"
```
#### DECISION

```
A STANDARD step whose
function raises a
WorkflowJumpDirective
to alter flow.
```
```
function:
"my_app.steps.evaluate_risk"
```
#### HUMAN_IN_LOOP

```
Pauses the workflow,
requiring external input to
resume. Function raises
WorkflowPauseDirective.
```
```
function:
"my_app.steps.request_approval"
```
#### HTTP

```
Makes an HTTP request to
an external API. Ideal for
polyglot integration.
```
```
method: "POST" url:
"https://api.example.com/data"
```
#### FIRE_AND_FORGET

```
Spawns a new independent
workflow without blocking
the parent.
```
```
target_workflow_type:
"NotificationFlow"
```
#### LOOP

```
Executes a body of steps
repeatedly based on a list or
a condition.
```
```
mode: "ITERATE" iterate_over:
"state.items" loop_body: [...]
```
#### CRON_SCHEDULER

```
Dynamically registers a new
recurring workflow schedule.
```
```
schedule: "0 9 * * MON"
target_workflow_type:
"DailyReport"
```
## 9. Advanced Features

### Saga Pattern (Distributed Transactions)

Rufus implements the Saga pattern to ensure data consistency across distributed systems. If
a workflow fails after several steps, Rufus automatically executes "compensation" functions
in reverse order to undo changes.

**How to use:**

1. **Define a compensate_function** in your step YAML for CompensatableSteps:


```
steps:
```
- name: "Charge_Payment"
type: "STANDARD"
function: "my_app.steps.charge_customer"
compensate_function: "my_app.steps.refund_customer" _# Functio_
2. **Enable saga mode** on your workflow instance:

```
workflow_instance.enable_saga_mode()
```
### Sub-Workflows (Hierarchical Composition)

Break down complex processes into smaller, reusable child workflows. The parent workflow
pauses while the child executes, with the parent's status dynamically updating to reflect the
child's state (e.g., PENDING_SUB_WORKFLOW, WAITING_CHILD_HUMAN_INPUT,
FAILED_CHILD_WORKFLOW). The parent resumes after the child completes, merging the
child's results into its own state.

**How to use:**

In a step function, raise a StartSubWorkflowDirective:

```
from rufus.models import StartSubWorkflowDirective
```
```
def initiate_kyc(state: BaseModel, context: StepContext):
raise StartSubWorkflowDirective(
workflow_type="KYC_Process",
initial_data={"user_id": state.user_id},
data_region="eu-west-1" # Optional: route child to specific re
)
```
The child workflow's final state and any explicit final result will be accessible in the parent's
state.sub_workflow_results dictionary, keyed by the child workflow's ID. This allows for
detailed inspection of the child's outcome.

## 10. Best Practices

```
Idempotent Steps : Design your step functions to be idempotent, meaning they can be
called multiple times without changing the result beyond the initial call. This is crucial
for retries and recovery.
Small, Focused Steps : Each step should do one thing well. This improves readability,
testability, and reusability.
Clear State Models : Define your Pydantic state models clearly, ensuring they
represent the evolving data of your workflow accurately.
```

```
Version Control YAML : Treat your workflow YAML files as code. Store them in Git, use
pull requests for changes, and ensure they are part of your CI/CD pipeline.
Logging and Observability : Integrate with the WorkflowObserver to gain insights
into your workflow's execution, debug issues, and monitor performance.
Leverage Package Auto-Discovery : When creating reusable step functions or
workflows, package them as rufus-* extensions. The SDK's auto-discovery
mechanism (builder.py) will automatically load them, making your logic available for
use in YAML definitions.
```
## 11. Testing Workflows

Rufus provides a WorkflowTestHarness for comprehensive local testing of your workflows.

```
# tests/test_my_workflow.py
from rufus.testing.harness import WorkflowTestHarness
```
```
def test_onboarding_process():
harness = WorkflowTestHarness(
workflow_type="WelcomeFlow",
initial_data={"message": "Test onboarding!"},
registry_path="config/workflow_registry.yaml" # Your actual re
)
```
```
# Mock an async step if needed (e.g., sending an email)
# harness.mock_step("Send_Welcome_Email", returns={"email_status":
```
```
# Run all steps automatically
final_workflow = harness.run_all_steps(
input_data_per_step={
"Greet_User": {"name": "Test User"} # Provide input for sp
}
)
```
```
assert final_workflow.status == "COMPLETED"
assert final_workflow.current_state.user_name == "Test User"
assert final_workflow.current_state.greeting_sent is True
```
```
def test_saga_rollback_scenario():
harness = WorkflowTestHarness(
workflow_type="OrderProcessing",
initial_data={"order_id": "ORD-123", "amount": 100.0},
registry_path="config/workflow_registry.yaml"
)
harness.workflow.enable_saga_mode() # Enable saga mode for this te
```

_# Mock a step to fail_
harness.mock_step("Charge_Payment", raises=ValueError("Payment fai

final_workflow = harness.run_all_steps()

assert final_workflow.status == "FAILED_ROLLED_BACK"
_# Assert that compensation for previous steps was called_
assert any(log["action"] == "mocked_compensate" for log in harness
