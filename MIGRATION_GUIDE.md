# Migration Guide: Confucius → Rufus SDK

This guide helps you migrate workflows from the original Confucius server-based architecture to the Rufus SDK-first architecture.

## Overview

### What Changed?

**Confucius** was a monolithic workflow server with:
- Central FastAPI server handling all requests
- Server-side workflow execution
- Tightly coupled components
- Client-server architecture

**Rufus** is an SDK-first workflow engine with:
- Embedded directly in your Python application
- Pluggable provider architecture
- No server required for basic operation
- Full control over execution environment

### Migration Benefits

- **Simpler Deployment**: No separate workflow server to manage
- **Better Integration**: Embed workflows directly in your app logic
- **More Control**: Choose your own persistence, execution, observability
- **Lower Latency**: No network calls for local workflows
- **Cost Savings**: Fewer infrastructure components

## Migration Checklist

- [ ] Update package imports
- [ ] Migrate state models
- [ ] Update step function signatures
- [ ] Convert workflow YAML files
- [ ] Update workflow initialization code
- [ ] Replace server-specific features
- [ ] Test workflow execution
- [ ] Update deployment configuration

## Step-by-Step Migration

### 1. Package Installation

**Before (Confucius):**
```bash
pip install confucius-workflows
```

**After (Rufus):**
```bash
# Clone repository (until PyPI release)
git clone https://github.com/your-org/rufus.git
cd rufus
pip install -e .
```

### 2. Import Statements

**Before (Confucius):**
```python
from confucius.workflow import (
    WorkflowJumpDirective,
    WorkflowPauseDirective,
    StartSubWorkflowDirective
)
from confucius.models import StepContext
from confucius.celery_app import celery_app
from confucius.semantic_firewall import WorkflowInput
```

**After (Rufus):**
```python
from rufus.models import (
    WorkflowJumpDirective,
    WorkflowPauseDirective,
    StartSubWorkflowDirective,
    StepContext
)
# Celery import moved to your application
from your_app.celery import celery_app
# WorkflowInput replaced with BaseModel
from pydantic import BaseModel
```

### 3. State Models

**Before (Confucius):**
```python
from confucius.semantic_firewall import WorkflowInput
from pydantic import BaseModel

class MyInputModel(WorkflowInput):
    name: str
    email: str

class MyState(BaseModel):
    user_id: str
    status: Optional[str] = None
```

**After (Rufus):**
```python
from pydantic import BaseModel
from typing import Optional

# All input models now inherit from BaseModel
class MyInputModel(BaseModel):
    name: str
    email: str

class MyState(BaseModel):
    user_id: str
    status: Optional[str] = None
```

**Key Changes:**
- `WorkflowInput` → `BaseModel` (semantic firewall removed from SDK)
- No other changes to state model structure

### 4. Step Function Signatures

All step functions must now include `context: StepContext` parameter.

**Before (Confucius):**
```python
def my_step(state: MyState):
    """Step function without context."""
    state.processed = True
    return {"result": "success"}

@celery_app.task
def async_step(state: dict):
    """Async step without context."""
    return {"data": state['input']}
```

**After (Rufus):**
```python
from rufus.models import StepContext

def my_step(state: MyState, context: StepContext):
    """Step function with context parameter."""
    print(f"[{context.step_name}] Processing...")
    state.processed = True
    return {"result": "success"}

@celery_app.task
def async_step(state: dict, context: StepContext):
    """Async step with context parameter."""
    print(f"Task: {context.step_name}")
    return {"data": state['input']}
```

**Key Changes:**
- **Add `context: StepContext`** parameter to ALL step functions
- Context provides: `workflow_id`, `step_name`, `validated_input`, `previous_step_result`

### 5. Workflow YAML Files

#### Function Paths

**Before (Confucius):**
```yaml
steps:
  - name: "My_Step"
    type: "STANDARD"
    function: "steps.loan.my_function"  # Module path with dots
    compensate_function: "steps.loan.compensate_my_function"
```

**After (Rufus):**
```yaml
steps:
  - name: "My_Step"
    type: "STANDARD"
    function: "loan.my_function"  # Direct module.function
    compensate_function: "loan.compensate_my_function"
```

**Key Changes:**
- Remove `steps.` prefix from function paths
- Use direct `module.function` format

#### Step Types

**Before (Confucius):**
```yaml
steps:
  - name: "Make_Decision"
    type: "DECISION"  # Special decision step type
    function: "steps.evaluate"

  - name: "Request_Approval"
    type: "HUMAN_IN_LOOP"  # Special human step type
    function: "steps.request_approval"
```

**After (Rufus):**
```yaml
steps:
  - name: "Make_Decision"
    type: "STANDARD"  # Use STANDARD with directives
    function: "evaluate"

  - name: "Request_Approval"
    type: "STANDARD"  # Use STANDARD with directives
    function: "request_approval"
```

**Supported Step Types in Rufus:**
- `STANDARD` - Synchronous step
- `ASYNC` - Asynchronous step (requires ExecutionProvider)
- `PARALLEL` - Parallel task execution
- `HTTP` - HTTP request step
- `FIRE_AND_FORGET` - Spawn independent workflow
- `LOOP` - Iterative processing
- `CRON_SCHEDULER` - Scheduled execution

**Key Changes:**
- `DECISION` → `STANDARD` (use `WorkflowJumpDirective` in function)
- `HUMAN_IN_LOOP` → `STANDARD` (use `WorkflowPauseDirective` in function)

#### Parallel Tasks

**Before (Confucius):**
```yaml
- name: "Run_Parallel"
  type: "PARALLEL"
  tasks:
    - name: "Task_A"
      function: "steps.task_a"  # Old format
```

**After (Rufus):**
```yaml
- name: "Run_Parallel"
  type: "PARALLEL"
  tasks:
    - name: "Task_A"
      function: "task_a"  # New format (same key name)
```

**Key Changes:**
- Parallel tasks use `function` key (not `function_path`)
- Remove `steps.` prefix from function paths

### 6. Workflow Initialization

**Before (Confucius - Server-Based):**
```python
import requests

# Start workflow via HTTP API
response = requests.post(
    "http://confucius-server:8000/workflows/start",
    json={
        "workflow_type": "MyWorkflow",
        "initial_data": {...},
        "workflow_id": "custom-id",
        "data_region": "us-east-1"
    }
)
workflow_id = response.json()["workflow_id"]

# Poll for status
status_response = requests.get(
    f"http://confucius-server:8000/workflows/{workflow_id}/status"
)
```

**After (Rufus - SDK Embedded):**
```python
import asyncio
import yaml
from rufus.engine import WorkflowEngine
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

async def main():
    # Load registry
    with open("workflow_registry.yaml") as f:
        registry_config = yaml.safe_load(f)

    workflow_registry = {}
    for wf in registry_config["workflows"]:
        with open(wf["config_file"]) as f:
            wf_config = yaml.safe_load(f)
        workflow_registry[wf["type"]] = {
            "initial_state_model_path": wf["initial_state_model"],
            "steps": wf_config["steps"],
            "workflow_version": wf_config.get("workflow_version", "1.0"),
        }

    # Initialize engine
    engine = WorkflowEngine(
        persistence=InMemoryPersistence(),
        executor=SyncExecutor(),
        observer=LoggingObserver(),
        workflow_registry=workflow_registry,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )
    await engine.initialize()

    # Start workflow (no HTTP calls!)
    workflow = await engine.start_workflow(
        workflow_type="MyWorkflow",
        initial_data={...}
    )

    # Execute steps directly
    while workflow.status == "ACTIVE":
        result = await workflow.next_step(user_input={})
        print(f"Step result: {result}")

asyncio.run(main())
```

**Key Changes:**
- No HTTP server required
- Direct SDK calls instead of REST API
- Choose your own providers (persistence, execution, observability)
- Explicit control over workflow execution

### 7. Celery Task Decorators

**Before (Confucius):**
```python
from confucius.celery_app import celery_app

@celery_app.task
def my_async_task(state: dict):
    # Task implementation
    return {"result": "done"}
```

**After (Rufus):**
```python
# Create your own Celery app
from celery import Celery

celery_app = Celery(
    'my_workflows',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/1'
)

# Use your Celery app
@celery_app.task
def my_async_task(state: dict, context: StepContext):
    # Task implementation (note: context parameter added)
    return {"result": "done"}

# Or for sync testing, comment out decorators
# @celery_app.task  # Commented for sync execution
def my_async_task(state: dict, context: StepContext):
    return {"result": "done"}
```

**Key Changes:**
- **Bring your own Celery app** (not provided by SDK)
- Add `context: StepContext` parameter
- Can disable Celery for local/sync testing

### 8. Execution Providers

**Before (Confucius):**
```python
# Server handles all execution automatically
# No choice of execution provider
```

**After (Rufus):**
```python
# Choose your execution provider

# Option 1: Synchronous (for development/testing)
from rufus.implementations.execution.sync import SyncExecutor
executor = SyncExecutor()

# Option 2: Celery (for production async/distributed)
from rufus.implementations.execution.celery import CeleryExecutor
executor = CeleryExecutor(celery_app=your_celery_app)

# Option 3: Custom (implement ExecutionProvider protocol)
class MyCustomExecutor:
    async def dispatch_async_task(self, ...):
        # Your implementation
        pass
```

**Key Changes:**
- **Pluggable execution** - choose sync, Celery, or custom
- Full control over task routing and execution

### 9. Persistence Providers

**Before (Confucius):**
```python
# Server uses configured database
# No choice from client side
```

**After (Rufus):**
```python
# Choose your persistence provider

# Option 1: In-Memory (for development/testing)
from rufus.implementations.persistence.memory import InMemoryPersistence
persistence = InMemoryPersistence()

# Option 2: PostgreSQL (for production)
from rufus.implementations.persistence.postgres import PostgresPersistence
persistence = PostgresPersistence(
    db_url="postgresql://user:pass@localhost/rufus_db"
)

# Option 3: Custom (implement PersistenceProvider protocol)
class MyCustomPersistence:
    async def save_workflow(self, workflow):
        # Your implementation
        pass
```

**Key Changes:**
- **Pluggable persistence** - choose in-memory, PostgreSQL, or custom
- Direct control over database connections and transactions

### 10. Sub-Workflows

**Before (Confucius):**
```python
from confucius.workflow import StartSubWorkflowDirective

def launch_sub_workflow(state: MyState):
    raise StartSubWorkflowDirective(
        workflow_type="ChildWorkflow",
        initial_data={"user_id": state.user_id}
    )
```

**After (Rufus):**
```python
from rufus.models import StartSubWorkflowDirective, StepContext

def launch_sub_workflow(state: MyState, context: StepContext):
    raise StartSubWorkflowDirective(
        workflow_type="ChildWorkflow",
        initial_data={"user_id": state.user_id},
        data_region="us-east-1"  # Optional
    )
```

**Known Limitations:**
- Sub-workflow feature currently has SDK bugs (missing `initial_state_model` attribute)
- Workaround: Use separate workflow execution instead of sub-workflows temporarily

## Complete Migration Example

### Original Confucius Workflow

**confucius/steps/loan.py:**
```python
from confucius.workflow import WorkflowJumpDirective
from confucius.celery_app import celery_app

def evaluate_application(state: LoanState):
    if state.credit_score > 700:
        raise WorkflowJumpDirective(target_step_name="Approve")
    else:
        raise WorkflowJumpDirective(target_step_name="Reject")

@celery_app.task
def run_credit_check(state: dict):
    # Async task without context
    return {"credit_score": 750}
```

**confucius/config/loan_workflow.yaml:**
```yaml
workflow_type: "LoanApplication"
initial_state_model: "confucius.models.LoanState"

steps:
  - name: "Check_Credit"
    type: "ASYNC"
    function: "steps.loan.run_credit_check"

  - name: "Evaluate"
    type: "DECISION"
    function: "steps.loan.evaluate_application"
    dependencies: ["Check_Credit"]
```

### Migrated Rufus Workflow

**loan.py:**
```python
from rufus.models import WorkflowJumpDirective, StepContext
# Bring your own Celery app
from my_app.celery import celery_app

def evaluate_application(state: LoanState, context: StepContext):
    """Added context parameter."""
    print(f"[{context.step_name}] Evaluating application...")
    if state.credit_score > 700:
        raise WorkflowJumpDirective(target_step_name="Approve")
    else:
        raise WorkflowJumpDirective(target_step_name="Reject")

@celery_app.task
def run_credit_check(state: dict, context: StepContext):
    """Added context parameter."""
    print(f"[{context.step_name}] Running credit check...")
    return {"credit_score": 750}
```

**state_models.py:**
```python
from pydantic import BaseModel  # Changed from WorkflowInput
from typing import Optional

class LoanState(BaseModel):  # Changed: removed confucius prefix
    applicant_id: str
    credit_score: Optional[int] = None
    status: Optional[str] = None
```

**loan_workflow.yaml:**
```yaml
workflow_type: "LoanApplication"
initial_state_model: "state_models.LoanState"  # Changed path

steps:
  - name: "Check_Credit"
    type: "ASYNC"
    function: "loan.run_credit_check"  # Changed: removed steps. prefix

  - name: "Evaluate"
    type: "STANDARD"  # Changed: DECISION → STANDARD
    function: "loan.evaluate_application"  # Changed: removed steps. prefix
    dependencies: ["Check_Credit"]
```

**run_loan.py:**
```python
import asyncio
import yaml
from rufus.engine import WorkflowEngine
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

async def main():
    # Load registry
    with open("workflow_registry.yaml") as f:
        registry_config = yaml.safe_load(f)

    workflow_registry = {}
    for wf in registry_config["workflows"]:
        with open(wf["config_file"]) as f:
            wf_config = yaml.safe_load(f)
        workflow_registry[wf["type"]] = {
            "initial_state_model_path": wf["initial_state_model"],
            "steps": wf_config["steps"],
            "workflow_version": wf_config.get("workflow_version", "1.0"),
        }

    # Initialize engine with providers
    engine = WorkflowEngine(
        persistence=InMemoryPersistence(),
        executor=SyncExecutor(),
        observer=LoggingObserver(),
        workflow_registry=workflow_registry,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )
    await engine.initialize()

    # Start and execute workflow
    workflow = await engine.start_workflow(
        workflow_type="LoanApplication",
        initial_data={"applicant_id": "user_123"}
    )

    while workflow.status == "ACTIVE":
        result = await workflow.next_step(user_input={})
        print(f"Step result: {result}")

    print(f"Final status: {workflow.state.status}")

asyncio.run(main())
```

## Migration Patterns

### Pattern 1: Server API → SDK Calls

**Before:**
```python
# Client making HTTP requests
response = requests.post("http://server/workflows/abc-123/next")
```

**After:**
```python
# Direct SDK calls
result = await workflow.next_step(user_input={})
```

### Pattern 2: Global Celery App → Your Celery App

**Before:**
```python
from confucius.celery_app import celery_app
```

**After:**
```python
# In your_app/celery.py
from celery import Celery

celery_app = Celery(
    'my_workflows',
    broker='redis://localhost:6379/0'
)

# In your steps
from your_app.celery import celery_app
```

### Pattern 3: Implicit Providers → Explicit Providers

**Before:**
```python
# Server configuration determines providers
```

**After:**
```python
# You choose providers explicitly
engine = WorkflowEngine(
    persistence=PostgresPersistence(...),
    executor=CeleryExecutor(...),
    observer=CustomObserver(...),
    ...
)
```

## Testing After Migration

### 1. Unit Test Step Functions

```python
import pytest
from rufus.models import StepContext
from state_models import MyState
from steps import my_step

def test_my_step():
    # Arrange
    state = MyState(field="value")
    context = StepContext(
        workflow_id="test-123",
        step_name="My_Step",
        validated_input=None,
        previous_step_result=None
    )

    # Act
    result = my_step(state, context)

    # Assert
    assert state.processed == True
    assert result["status"] == "success"
```

### 2. Integration Test Workflows

```python
import pytest
import asyncio
from rufus.engine import WorkflowEngine
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor

@pytest.mark.asyncio
async def test_loan_workflow():
    # Setup engine
    engine = WorkflowEngine(
        persistence=InMemoryPersistence(),
        executor=SyncExecutor(),
        ...
    )
    await engine.initialize()

    # Start workflow
    workflow = await engine.start_workflow(
        workflow_type="LoanApplication",
        initial_data={"applicant_id": "test-123"}
    )

    # Execute all steps
    while workflow.status == "ACTIVE":
        await workflow.next_step(user_input={})

    # Assert final state
    assert workflow.status == "COMPLETED"
    assert workflow.state.status == "APPROVED"
```

## Common Migration Issues

### Issue 1: Missing Context Parameter

**Error:**
```
TypeError: my_step() takes 1 positional argument but 2 were given
```

**Solution:**
Add `context: StepContext` parameter to all step functions.

### Issue 2: Wrong Function Path

**Error:**
```
ImportError: cannot import name 'my_function' from 'steps.loan'
```

**Solution:**
Update YAML to use direct module paths (remove `steps.` prefix):
```yaml
function: "loan.my_function"  # Not "steps.loan.my_function"
```

### Issue 3: Unknown Step Type

**Error:**
```
ValueError: Unknown step type: 'DECISION'
```

**Solution:**
Change `DECISION` and `HUMAN_IN_LOOP` to `STANDARD`:
```yaml
type: "STANDARD"  # Not "DECISION" or "HUMAN_IN_LOOP"
```

### Issue 4: Workflow Not Advancing

**Symptom:**
Workflow stays at `ACTIVE` status but doesn't progress.

**Solution:**
Ensure `automate_next: true` is set on steps:
```yaml
- name: "My_Step"
  type: "STANDARD"
  function: "my_step"
  automate_next: true  # ← Required
```

### Issue 5: Parallel Tasks Fail

**Error:**
```
RuntimeError: Parallel tasks failed: Task X failed: 'dict' object has no attribute 'field'
```

**Solution:**
Parallel task functions receive `state: dict`, not Pydantic models:
```python
# Correct for parallel tasks
def parallel_task(state: dict, context: StepContext):
    name = state['user']['name']  # Access as dict
    return {"result": "done"}
```

## Deployment Changes

### Before (Confucius)

```yaml
# docker-compose.yml
services:
  confucius-server:
    image: confucius-workflows:latest
    environment:
      - DATABASE_URL=postgresql://...
      - CELERY_BROKER=redis://...
    ports:
      - "8000:8000"

  celery-worker:
    image: confucius-workflows:latest
    command: celery worker
```

### After (Rufus)

```yaml
# docker-compose.yml
services:
  my-app:
    build: .
    environment:
      - DATABASE_URL=postgresql://...
      - CELERY_BROKER=redis://...
    # No workflow server needed!

  celery-worker:
    build: .
    command: celery -A my_app.celery worker
```

**Key Changes:**
- No separate workflow server
- Workflows embedded in your application
- Simpler deployment architecture

## Performance Considerations

### Latency

**Confucius:** Server round-trip for each operation (~10-50ms network overhead)

**Rufus:** Direct SDK calls (no network overhead for local execution)

### Resource Usage

**Confucius:** Separate server process + workers

**Rufus:** Workflows run in your application process

### Scalability

**Confucius:** Scale workflow server and workers separately

**Rufus:** Scale your application (workflows scale with it)

## Getting Help

If you encounter issues during migration:

1. **Check Examples**: See `examples/loan_application/` for a complete migrated workflow
2. **Review Docs**: Read [TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md)
3. **Open Issue**: [GitHub Issues](https://github.com/your-org/rufus/issues)
4. **Ask Community**: [GitHub Discussions](https://github.com/your-org/rufus/discussions)

## Next Steps

After migration:

1. **Test Thoroughly**: Run all workflow scenarios
2. **Update Docs**: Document your migrated workflows
3. **Monitor Performance**: Compare with previous Confucius performance
4. **Optimize Providers**: Choose production-ready persistence and execution providers
5. **Deploy**: Update deployment configuration for SDK-embedded architecture

---

**Congratulations on migrating to Rufus!** You now have a more flexible, embeddable workflow engine with full control over your execution environment. 🎉
