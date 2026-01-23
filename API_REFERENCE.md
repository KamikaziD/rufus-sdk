# Rufus SDK - API Reference

Complete API documentation for the Rufus SDK. This reference covers all core classes, provider interfaces, models, and directives.

## Table of Contents

- [Core Classes](#core-classes)
  - [WorkflowEngine](#workflowengine)
  - [Workflow](#workflow)
  - [WorkflowBuilder](#workflowbuilder)
- [Provider Interfaces](#provider-interfaces)
  - [PersistenceProvider](#persistenceprovider)
  - [ExecutionProvider](#executionprovider)
  - [WorkflowObserver](#workflowobserver)
  - [ExpressionEvaluator](#expressionevaluator)
  - [TemplateEngine](#templateengine)
- [Models](#models)
  - [StepContext](#stepcontext)
  - [WorkflowStep](#workflowstep)
  - [State Models](#state-models)
- [Directives](#directives)
  - [WorkflowJumpDirective](#workflowjumpdirective)
  - [WorkflowPauseDirective](#workflowpausedirective)
  - [StartSubWorkflowDirective](#startsubworkflowdirective)
  - [SagaWorkflowException](#sagaworkflowexception)
- [Default Implementations](#default-implementations)

---

## Core Classes

### WorkflowEngine

The central orchestrator responsible for managing workflow lifecycle, state transitions, and step execution.

**Location:** `rufus.engine.WorkflowEngine`

#### Constructor

```python
def __init__(
    self,
    persistence: PersistenceProvider,
    executor: ExecutionProvider,
    observer: WorkflowObserver,
    workflow_registry: Dict[str, Any],
    expression_evaluator_cls: Type[ExpressionEvaluator],
    template_engine_cls: Type[TemplateEngine]
)
```

**Parameters:**

- **persistence** (`PersistenceProvider`) - Provider for saving/loading workflow state
- **executor** (`ExecutionProvider`) - Provider for executing workflow steps
- **observer** (`WorkflowObserver`) - Provider for observing workflow events
- **workflow_registry** (`Dict[str, Any]`) - Dictionary mapping workflow types to configurations
- **expression_evaluator_cls** (`Type[ExpressionEvaluator]`) - Class for evaluating expressions
- **template_engine_cls** (`Type[TemplateEngine]`) - Class for rendering templates

**Example:**

```python
from rufus.engine import WorkflowEngine
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

engine = WorkflowEngine(
    persistence=InMemoryPersistence(),
    executor=SyncExecutor(),
    observer=LoggingObserver(),
    workflow_registry=workflow_registry,
    expression_evaluator_cls=SimpleExpressionEvaluator,
    template_engine_cls=Jinja2TemplateEngine
)
```

#### Methods

##### initialize()

Initialize the engine and all providers.

```python
async def initialize() -> None
```

**Example:**

```python
await engine.initialize()
```

##### start_workflow()

Start a new workflow instance.

```python
async def start_workflow(
    self,
    workflow_type: str,
    initial_data: Dict[str, Any],
    owner_id: Optional[str] = None,
    org_id: Optional[str] = None,
    data_region: Optional[str] = None
) -> Workflow
```

**Parameters:**

- **workflow_type** (`str`) - The type of workflow to start (must exist in registry)
- **initial_data** (`Dict[str, Any]`) - Initial state data for the workflow
- **owner_id** (`Optional[str]`) - Optional owner identifier
- **org_id** (`Optional[str]`) - Optional organization identifier
- **data_region** (`Optional[str]`) - Optional data region for compliance

**Returns:** `Workflow` instance

**Example:**

```python
workflow = await engine.start_workflow(
    workflow_type="LoanApplication",
    initial_data={"applicant_id": "user_123", "amount": 50000},
    owner_id="user_123",
    data_region="us-east-1"
)
```

##### get_workflow()

Retrieve an existing workflow by ID.

```python
async def get_workflow(
    self,
    workflow_id: str
) -> Workflow
```

**Parameters:**

- **workflow_id** (`str`) - Unique workflow identifier

**Returns:** `Workflow` instance

**Example:**

```python
workflow = await engine.get_workflow("abc-123-def")
```

##### close()

Cleanup and close all providers.

```python
async def close() -> None
```

**Example:**

```python
await engine.close()
```

---

### Workflow

Represents a single workflow instance with its current state and execution context.

**Location:** `rufus.workflow.Workflow`

#### Properties

- **id** (`str`) - Unique workflow identifier
- **workflow_type** (`str`) - Type of workflow
- **status** (`str`) - Current status (`ACTIVE`, `COMPLETED`, `FAILED`, `WAITING_HUMAN`, etc.)
- **state** (`BaseModel`) - Current workflow state (Pydantic model)
- **current_step** (`int`) - Index of current step
- **workflow_steps** (`List[WorkflowStep]`) - List of all workflow steps

#### Methods

##### next_step()

Execute the next step in the workflow.

```python
async def next_step(
    self,
    user_input: Dict[str, Any]
) -> Tuple[Dict[str, Any], Optional[str]]
```

**Parameters:**

- **user_input** (`Dict[str, Any]`) - Input data for the step (required for human-in-the-loop steps)

**Returns:** Tuple of `(result_dict, next_step_name)`

**Example:**

```python
# Execute next step
result, next_step = await workflow.next_step(user_input={})

# For human-in-the-loop steps
result, next_step = await workflow.next_step(
    user_input={
        "decision": "APPROVED",
        "reviewer_id": "reviewer_123",
        "comments": "Looks good"
    }
)
```

##### enable_saga_mode()

Enable Saga pattern for distributed transaction rollback.

```python
def enable_saga_mode(self) -> None
```

**Example:**

```python
workflow.enable_saga_mode()
```

---

### WorkflowBuilder

Responsible for loading workflow configurations and assembling executable workflows.

**Location:** `rufus.builder.WorkflowBuilder`

#### Constructor

```python
def __init__(
    self,
    workflow_registry: Dict[str, Any],
    expression_evaluator_cls: Type[ExpressionEvaluator],
    template_engine_cls: Type[TemplateEngine]
)
```

**Note:** Typically created internally by `WorkflowEngine`.

#### Methods

##### create_workflow()

Create a new workflow instance from registry configuration.

```python
async def create_workflow(
    self,
    workflow_type: str,
    initial_data: Dict[str, Any],
    workflow_id: Optional[str] = None,
    owner_id: Optional[str] = None,
    org_id: Optional[str] = None,
    data_region: Optional[str] = None
) -> Workflow
```

**Returns:** `Workflow` instance

---

## Provider Interfaces

All provider interfaces use Python's `Protocol` typing for maximum flexibility.

### PersistenceProvider

Interface for saving and loading workflow state.

**Location:** `rufus.providers.persistence.PersistenceProvider`

#### Methods

##### initialize()

```python
async def initialize(self) -> None
```

Initialize the persistence layer (e.g., database connections).

##### close()

```python
async def close() -> None
```

Cleanup and close connections.

##### save_workflow()

```python
async def save_workflow(
    self,
    workflow: Workflow
) -> None
```

Persist workflow state to storage.

##### load_workflow()

```python
async def load_workflow(
    self,
    workflow_id: str
) -> Optional[Workflow]
```

Load workflow state from storage.

**Returns:** `Workflow` instance or `None` if not found

##### create_audit_log()

```python
async def create_audit_log(
    self,
    workflow_id: str,
    step_name: str,
    action: str,
    details: Optional[Dict[str, Any]] = None
) -> None
```

Create an audit log entry for workflow events.

**Example Implementation:**

```python
from rufus.providers.persistence import PersistenceProvider

class MyPersistence:
    async def initialize(self):
        self.workflows = {}

    async def save_workflow(self, workflow):
        self.workflows[workflow.id] = workflow

    async def load_workflow(self, workflow_id):
        return self.workflows.get(workflow_id)

    async def create_audit_log(self, workflow_id, step_name, action, details):
        print(f"[AUDIT] {workflow_id} - {step_name}: {action}")
```

---

### ExecutionProvider

Interface for executing workflow steps (sync, async, parallel).

**Location:** `rufus.providers.execution.ExecutionProvider`

#### Methods

##### initialize()

```python
async def initialize(
    self,
    engine: Any
) -> None
```

Initialize the executor with a reference to the engine.

##### close()

```python
async def close() -> None
```

Cleanup resources.

##### execute_sync_step_function()

```python
async def execute_sync_step_function(
    self,
    func: Callable,
    state: BaseModel,
    context: StepContext
) -> Dict[str, Any]
```

Execute a synchronous step function.

**Parameters:**

- **func** (`Callable`) - The step function to execute
- **state** (`BaseModel`) - Current workflow state
- **context** (`StepContext`) - Step execution context

**Returns:** Result dictionary

##### dispatch_async_task()

```python
async def dispatch_async_task(
    self,
    workflow_id: str,
    func_path: str,
    state_data: Dict[str, Any],
    context_data: Dict[str, Any],
    data_region: Optional[str] = None
) -> Dict[str, Any]
```

Dispatch an asynchronous task (e.g., to Celery).

**Parameters:**

- **workflow_id** (`str`) - Workflow identifier
- **func_path** (`str`) - Module path to function (e.g., "steps.my_function")
- **state_data** (`Dict[str, Any]`) - Serialized state data
- **context_data** (`Dict[str, Any]`) - Serialized context data
- **data_region** (`Optional[str]`) - Data region for routing

**Returns:** Task result or task ID

##### dispatch_parallel_tasks()

```python
async def dispatch_parallel_tasks(
    self,
    tasks: List[ParallelExecutionTask],
    state_data: Dict[str, Any],
    workflow_id: str,
    current_step_index: int,
    merge_function_path: Optional[str] = None,
    data_region: Optional[str] = None,
    merge_strategy: str = "SHALLOW",
    merge_conflict_behavior: str = "PREFER_NEW",
    timeout_seconds: Optional[int] = None,
    allow_partial_success: bool = False
) -> Dict[str, Any]
```

Dispatch multiple tasks to run in parallel.

**Parameters:**

- **tasks** (`List[ParallelExecutionTask]`) - List of tasks to execute
- **state_data** (`Dict[str, Any]`) - Serialized state data
- **workflow_id** (`str`) - Workflow identifier
- **current_step_index** (`int`) - Index of parallel step
- **merge_function_path** (`Optional[str]`) - Optional custom merge function
- **merge_strategy** (`str`) - How to merge results (`SHALLOW`, `DEEP`)
- **merge_conflict_behavior** (`str`) - Conflict resolution (`PREFER_NEW`, `PREFER_OLD`, `FAIL`)
- **timeout_seconds** (`Optional[int]`) - Maximum execution time
- **allow_partial_success** (`bool`) - Whether to proceed if some tasks fail

**Returns:** Merged results dictionary

---

### WorkflowObserver

Interface for observing and reacting to workflow events.

**Location:** `rufus.providers.observer.WorkflowObserver`

#### Methods

##### on_workflow_started()

```python
async def on_workflow_started(
    self,
    workflow_id: str,
    workflow_type: str,
    initial_data: Dict[str, Any]
) -> None
```

Called when a workflow starts.

##### on_step_started()

```python
async def on_step_started(
    self,
    workflow_id: str,
    step_name: str,
    step_type: str
) -> None
```

Called when a step begins execution.

##### on_step_completed()

```python
async def on_step_completed(
    self,
    workflow_id: str,
    step_name: str,
    result: Dict[str, Any]
) -> None
```

Called when a step completes successfully.

##### on_step_failed()

```python
async def on_step_failed(
    self,
    workflow_id: str,
    step_name: str,
    error: str,
    state: Any
) -> None
```

Called when a step fails.

##### on_workflow_completed()

```python
async def on_workflow_completed(
    self,
    workflow_id: str,
    final_state: Any
) -> None
```

Called when a workflow completes.

##### on_workflow_failed()

```python
async def on_workflow_failed(
    self,
    workflow_id: str,
    error: str,
    state: Any
) -> None
```

Called when a workflow fails.

**Example Implementation:**

```python
from rufus.providers.observer import WorkflowObserver

class MetricsObserver:
    async def on_workflow_started(self, workflow_id, workflow_type, initial_data):
        self.metrics.increment(f"workflow.{workflow_type}.started")

    async def on_step_completed(self, workflow_id, step_name, result):
        self.metrics.timing(f"step.{step_name}.duration", result.get('duration'))

    async def on_workflow_failed(self, workflow_id, error, state):
        self.metrics.increment("workflow.failed")
        self.alert_service.send(f"Workflow {workflow_id} failed: {error}")
```

---

### ExpressionEvaluator

Interface for evaluating conditional expressions in workflows.

**Location:** `rufus.providers.expression_evaluator.ExpressionEvaluator`

#### Methods

##### evaluate()

```python
def evaluate(
    self,
    expression: str,
    context: Dict[str, Any]
) -> bool
```

Evaluate an expression against a context.

**Parameters:**

- **expression** (`str`) - Expression to evaluate (e.g., `"state.score > 80"`)
- **context** (`Dict[str, Any]`) - Context data including state

**Returns:** `bool` - Result of evaluation

**Example:**

```python
result = evaluator.evaluate(
    expression="state.credit_score > 700 and state.fraud_risk < 0.3",
    context={"state": workflow.state}
)
```

---

### TemplateEngine

Interface for rendering templates with dynamic data.

**Location:** `rufus.providers.template_engine.TemplateEngine`

#### Methods

##### render_template()

```python
def render_template(
    self,
    template_path: str,
    context: Dict[str, Any]
) -> str
```

Render a template file with context data.

##### render_string_template()

```python
def render_string_template(
    self,
    template: str,
    context: Dict[str, Any]
) -> str
```

Render a template string with context data.

**Example:**

```python
output = template_engine.render_string_template(
    template="Hello {{ user.name }}, your score is {{ state.score }}",
    context={"user": user, "state": workflow.state}
)
```

---

## Models

### StepContext

Provides contextual information to step functions during execution.

**Location:** `rufus.models.StepContext`

#### Fields

```python
class StepContext(BaseModel):
    workflow_id: str
    step_name: str
    validated_input: Optional[BaseModel] = None
    previous_step_result: Optional[Dict[str, Any]] = None
    loop_item: Optional[Any] = None
    loop_index: Optional[int] = None
```

**Field Descriptions:**

- **workflow_id** - Unique identifier for the workflow instance
- **step_name** - Name of the current step
- **validated_input** - Validated user input (for human-in-the-loop steps)
- **previous_step_result** - Result from the previous step
- **loop_item** - Current item in a loop step
- **loop_index** - Current index in a loop step

**Usage in Step Functions:**

```python
from rufus.models import StepContext

def my_step(state: MyState, context: StepContext):
    print(f"Executing {context.step_name} in workflow {context.workflow_id}")

    # Access previous result
    if context.previous_step_result:
        score = context.previous_step_result.get('score')

    # Access user input (for human-in-the-loop)
    if context.validated_input:
        decision = context.validated_input.decision

    return {"status": "completed"}
```

---

### WorkflowStep

Base class for all workflow step types.

**Location:** `rufus.models.WorkflowStep`

#### Base Fields

```python
class WorkflowStep(BaseModel):
    name: str
    func_path: Optional[str] = None
    automate_next: bool = False
    required_input: List[str] = []
    input_schema: Optional[Type[BaseModel]] = None
    dependencies: List[str] = []
    merge_strategy: MergeStrategy = MergeStrategy.SHALLOW
    merge_conflict_behavior: MergeConflictBehavior = MergeConflictBehavior.PREFER_NEW
```

#### Subclasses

##### CompensatableStep

Step with compensation function for Saga pattern.

```python
class CompensatableStep(WorkflowStep):
    compensate_func: Optional[Callable] = None
```

##### AsyncWorkflowStep

Step executed asynchronously (e.g., via Celery).

```python
class AsyncWorkflowStep(WorkflowStep):
    # Inherits all base fields
    pass
```

##### ParallelWorkflowStep

Step that executes multiple tasks in parallel.

```python
class ParallelWorkflowStep(WorkflowStep):
    tasks: List[ParallelExecutionTask]
    merge_function_path: Optional[str] = None
    timeout_seconds: Optional[int] = None
    allow_partial_success: bool = False
```

##### HttpWorkflowStep

Step that makes HTTP requests.

```python
class HttpWorkflowStep(WorkflowStep):
    url_template: str
    method: str = "GET"
    headers_template: Optional[Dict[str, str]] = None
    body_template: Optional[str] = None
```

---

### State Models

User-defined Pydantic models representing workflow state.

**Example:**

```python
from pydantic import BaseModel, Field
from typing import Optional

class LoanApplicationState(BaseModel):
    """State for loan application workflow."""
    application_id: Optional[str] = None
    applicant_name: str
    requested_amount: float = Field(gt=0)
    credit_score: Optional[int] = None
    fraud_score: Optional[float] = None
    status: Optional[str] = None
    approved: bool = False
```

**Best Practices:**

- Use `Optional[]` for fields populated during workflow execution
- Use `Field()` for validation constraints
- Keep state models focused and single-purpose
- Document fields with docstrings

---

## Directives

Directives are special exceptions that alter workflow control flow.

### WorkflowJumpDirective

Jump to a specific step, skipping intermediate steps.

**Location:** `rufus.models.WorkflowJumpDirective`

#### Constructor

```python
WorkflowJumpDirective(
    target_step_name: str,
    result: Optional[Dict[str, Any]] = None
)
```

**Parameters:**

- **target_step_name** (`str`) - Name of step to jump to
- **result** (`Optional[Dict[str, Any]]`) - Optional result data

**Example:**

```python
from rufus.models import WorkflowJumpDirective

def evaluate_credit(state: LoanState, context: StepContext):
    if state.credit_score > 750:
        # Skip detailed review, jump to approval
        raise WorkflowJumpDirective(
            target_step_name="Auto_Approve",
            result={"reason": "Excellent credit"}
        )
    elif state.credit_score < 600:
        # Skip to rejection
        raise WorkflowJumpDirective(
            target_step_name="Auto_Reject",
            result={"reason": "Poor credit"}
        )
    # Otherwise continue to next step normally
    return {"status": "needs_review"}
```

---

### WorkflowPauseDirective

Pause workflow execution for external input (human-in-the-loop).

**Location:** `rufus.models.WorkflowPauseDirective`

#### Constructor

```python
WorkflowPauseDirective(
    result: Optional[Dict[str, Any]] = None
)
```

**Parameters:**

- **result** (`Optional[Dict[str, Any]]`) - Optional result data

**Example:**

```python
from rufus.models import WorkflowPauseDirective

def request_manager_approval(state: LoanState, context: StepContext):
    """Pause workflow and wait for manager decision."""
    state.status = "PENDING_APPROVAL"
    state.pending_since = datetime.now().isoformat()

    raise WorkflowPauseDirective(
        result={
            "message": "Waiting for manager approval",
            "required_role": "loan_manager"
        }
    )

def process_manager_decision(state: LoanState, context: StepContext):
    """Process the manager's decision when workflow resumes."""
    decision = context.validated_input.decision
    manager_id = context.validated_input.manager_id

    state.status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    state.approved_by = manager_id

    return {"decision": decision, "approved_by": manager_id}
```

**Resume Workflow:**

```python
# Later, when human provides input
result = await workflow.next_step(
    user_input={
        "decision": "APPROVE",
        "manager_id": "mgr_123",
        "comments": "Verified employment history"
    }
)
```

---

### StartSubWorkflowDirective

Launch a child workflow and wait for its completion.

**Location:** `rufus.models.StartSubWorkflowDirective`

#### Constructor

```python
StartSubWorkflowDirective(
    workflow_type: str,
    initial_data: Dict[str, Any],
    data_region: Optional[str] = None
)
```

**Parameters:**

- **workflow_type** (`str`) - Type of child workflow to start
- **initial_data** (`Dict[str, Any]`) - Initial state for child workflow
- **data_region** (`Optional[str]`) - Data region for compliance

**Example:**

```python
from rufus.models import StartSubWorkflowDirective

def run_kyc_verification(state: LoanState, context: StepContext):
    """Launch KYC sub-workflow."""
    print(f"Launching KYC verification for {state.applicant_name}")

    raise StartSubWorkflowDirective(
        workflow_type="KYC_Verification",
        initial_data={
            "user_id": state.applicant_id,
            "name": state.applicant_name,
            "document_url": state.id_document_url
        },
        data_region="us-east-1"
    )

def process_kyc_results(state: LoanState, context: StepContext):
    """Process results from KYC sub-workflow."""
    kyc_result = context.previous_step_result

    state.kyc_status = kyc_result.get('status')
    state.kyc_verified = kyc_result.get('verified', False)

    return {"kyc_completed": True}
```

**Note:** Sub-workflow feature currently has SDK limitations (missing `initial_state_model` attribute).

---

### SagaWorkflowException

Trigger Saga pattern rollback by executing compensation functions.

**Location:** `rufus.models.SagaWorkflowException`

#### Constructor

```python
SagaWorkflowException(
    message: str,
    failed_step: str
)
```

**Parameters:**

- **message** (`str`) - Error message
- **failed_step** (`str`) - Name of step that failed

**Example:**

```python
from rufus.models import SagaWorkflowException

def charge_credit_card(state: OrderState, context: StepContext):
    """Charge customer's credit card."""
    try:
        payment_result = payment_gateway.charge(
            card_token=state.payment_token,
            amount=state.total_amount
        )
        state.payment_id = payment_result['transaction_id']
        state.charged = True
        return {"payment_id": payment_result['transaction_id']}
    except PaymentError as e:
        # Trigger Saga rollback
        raise SagaWorkflowException(
            message=f"Payment failed: {str(e)}",
            failed_step="charge_credit_card"
        )

def compensate_charge_credit_card(state: OrderState, context: StepContext):
    """Compensation: Refund the charge."""
    if state.payment_id:
        payment_gateway.refund(state.payment_id)
        print(f"[COMPENSATION] Refunded payment {state.payment_id}")
        state.charged = False
        return {"refunded": True}
```

**Enable Saga Mode:**

```python
workflow.enable_saga_mode()
```

---

## Default Implementations

### InMemoryPersistence

Simple in-memory persistence for development and testing.

**Location:** `rufus.implementations.persistence.memory.InMemoryPersistence`

**Usage:**

```python
from rufus.implementations.persistence.memory import InMemoryPersistence

persistence = InMemoryPersistence()
```

**Characteristics:**

- No external dependencies
- Data lost on process restart
- Fast and simple
- Ideal for development and testing

---

### PostgresPersistence

Production-ready PostgreSQL persistence.

**Location:** `rufus.implementations.persistence.postgres.PostgresPersistence`

**Usage:**

```python
from rufus.implementations.persistence.postgres import PostgresPersistence

persistence = PostgresPersistence(
    db_url="postgresql://user:password@localhost:5432/rufus_db"
)
```

**Characteristics:**

- ACID-compliant transactions
- JSONB for efficient state storage
- `FOR UPDATE SKIP LOCKED` for atomic task claiming
- Full audit trail
- Production-ready

---

### SyncExecutor

Synchronous executor for local development.

**Location:** `rufus.implementations.execution.sync.SyncExecutor`

**Usage:**

```python
from rufus.implementations.execution.sync import SyncExecutor

executor = SyncExecutor()
```

**Characteristics:**

- Executes steps in current process
- Uses ThreadPoolExecutor for parallel tasks
- No external dependencies
- Ideal for development and testing

---

### CeleryExecutor

Distributed async executor using Celery.

**Location:** `rufus.implementations.execution.celery.CeleryExecutor`

**Usage:**

```python
from celery import Celery
from rufus.implementations.execution.celery import CeleryExecutor

celery_app = Celery('workflows', broker='redis://localhost:6379')
executor = CeleryExecutor(celery_app=celery_app)
```

**Characteristics:**

- Distributed task execution
- Scalable worker pools
- Async and parallel task support
- Production-ready
- Requires Redis or RabbitMQ

---

### LoggingObserver

Simple console logging observer.

**Location:** `rufus.implementations.observability.logging.LoggingObserver`

**Usage:**

```python
from rufus.implementations.observability.logging import LoggingObserver

observer = LoggingObserver()
```

**Characteristics:**

- Logs to console
- No external dependencies
- Good for development
- Can be extended for custom logging

---

### SimpleExpressionEvaluator

Basic Python expression evaluator.

**Location:** `rufus.implementations.expression_evaluator.simple.SimpleExpressionEvaluator`

**Usage:**

```python
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator

evaluator = SimpleExpressionEvaluator()
result = evaluator.evaluate("state.score > 80", {"state": state})
```

**Characteristics:**

- Uses Python's `eval()` with restricted globals
- Supports basic comparisons and logic
- Simple and lightweight

---

### Jinja2TemplateEngine

Jinja2-based template rendering.

**Location:** `rufus.implementations.templating.jinja2.Jinja2TemplateEngine`

**Usage:**

```python
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

engine = Jinja2TemplateEngine()
output = engine.render_string_template(
    "Hello {{ name }}!",
    {"name": "World"}
)
```

**Characteristics:**

- Full Jinja2 syntax support
- Template inheritance
- Filters and macros
- Production-ready

---

## Additional Resources

- **[QUICKSTART.md](QUICKSTART.md)** - Get started in 5 minutes
- **[TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md)** - Architecture deep dive
- **[MIGRATION_GUIDE.md](MIGRATION_GUIDE.md)** - Migrating from Confucius
- **[examples/](examples/)** - Working code examples

## Support

For questions and issues:

- **GitHub Issues**: [github.com/your-org/rufus/issues](https://github.com/your-org/rufus/issues)
- **Discussions**: [github.com/your-org/rufus/discussions](https://github.com/your-org/rufus/discussions)
