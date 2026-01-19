# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Confucius is a configuration-driven workflow engine library for Python that enables complex, multi-step processes to be defined in YAML files. The project consists of:

1. **Core library** (`src/confucius/`) - A reusable, installable package containing the workflow engine
2. **Example application** (root directory) - Demonstrates how to use the library with sample workflows

The architecture decouples business logic from process orchestration by having workflow steps reference functions in the application layer while the engine handles state management, execution flow, and task orchestration.

## Development Commands

### Setup
```bash
# Install dependencies and the core package in editable mode
pip install -r requirements.txt
pip install -e .

# Start Redis (required for state persistence and Celery)
docker run -d --name redis-server -p 6379:6379 redis
```

### Running the Application
```bash
# Start Celery worker (required for async/parallel tasks)
celery -A celery_setup worker --loglevel=info

# Start FastAPI development server
uvicorn main:app --reload
```

### Testing
```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_workflow.py

# Run with verbose output
pytest -v

# Run specific test
pytest tests/test_workflow.py::test_automate_next_chain
```

## Architecture

### Core Components

**Workflow Engine (`src/confucius/workflow.py`)**
- `Workflow`: Main class that manages workflow state, steps, and execution
- `WorkflowStep`: Standard synchronous step execution
- `AsyncWorkflowStep`: Long-running tasks executed by Celery workers
- `ParallelWorkflowStep`: Executes multiple tasks concurrently using Celery groups
- `WorkflowJumpDirective`: Exception-based control flow for conditional branching
- `WorkflowPauseDirective`: Exception that pauses workflow for human input

**Workflow Loader (`src/confucius/workflow_loader.py`)**
- `WorkflowBuilder`: Loads workflow definitions from YAML files
- Resolves function paths to callables using `importlib`
- Manages workflow registry for discovering available workflows
- Handles Pydantic model imports for state and input validation

**Persistence (`src/confucius/persistence.py`)**
- Redis-based state storage with automatic serialization/deserialization
- Pub/Sub pattern for real-time workflow state updates via WebSockets
- All workflow state is saved after each step execution

**Celery Tasks (`src/confucius/tasks.py`)**
- `resume_from_async_task`: Resumes workflow after async step completes
- `merge_and_resume_parallel_tasks`: Merges results from parallel tasks and continues workflow
- Task chaining: async tasks automatically trigger workflow resumption

**API Router (`src/confucius/routers.py`)**
- `get_workflow_router()`: Factory function that returns pre-built FastAPI router
- Endpoints: start workflow, get status, next step, resume (for human input), retry failed
- WebSocket endpoint for real-time state updates

### Application Layer

**Workflow Functions (`workflow_utils.py`)**
- Business logic functions that do the actual work
- Functions decorated with `@celery_app.task` are async-capable
- Must accept `state` as first parameter (Pydantic model for sync, dict for async)
- Can raise `WorkflowJumpDirective` for conditional branching
- Can raise `WorkflowPauseDirective` for human-in-the-loop steps

**State Models (`state_models.py`)**
- Pydantic models define the schema for each workflow's state
- Separate input models for step-level validation (e.g., `CollectApplicationDataInput`)
- State is automatically validated and serialized by the engine

**Celery Configuration (`celery_setup.py`)**
- `configure_celery_app()`: Sets up Celery broker, backend, and task discovery
- Must be called by both the worker entrypoint and the FastAPI app
- Discovers tasks from both `confucius.tasks` (core) and `workflow_utils` (application)

### Workflow Configuration

**Registry (`config/workflow_registry.yaml`)**
- Master list of all available workflows
- Maps workflow type to config file and initial state model

**Workflow YAML Structure**
- `workflow_type`: Unique identifier
- `initial_state_model`: Python path to Pydantic state model
- `steps`: List of workflow steps with configuration

**Step Types**
- `STANDARD`: Synchronous function execution
- `ASYNC`: Long-running task executed by Celery worker
- `PARALLEL`: Multiple tasks executed concurrently, results merged
- `DECISION`: Can raise `WorkflowJumpDirective` to change flow
- `HUMAN_IN_LOOP`: Pauses workflow, raises `WorkflowPauseDirective`

**Key Step Configuration**
- `function`: Python path to function (e.g., `workflow_utils.collect_application_data`)
- `input_model`: Python path to Pydantic model for input validation (optional)
- `automate_next`: If true, automatically executes next step using current step's return value
- `dependencies`: List of step names that must complete before this step
- `dynamic_injection`: Rules for inserting steps at runtime based on state

### Control Flow Mechanisms

**Automated Step Chaining (`automate_next`)**
- When `automate_next: true`, the return value of a step becomes input for the next step
- Chain multiple steps by returning dict that matches next step's input schema
- See `config/super_workflow.yaml` for example

**Conditional Branching**
- Raise `WorkflowJumpDirective(target_step_name="Step_Name")` to skip to a specific step
- Used in decision steps (e.g., `evaluate_pre_approval` in loan workflow)

**Dynamic Step Injection**
- Define injection rules in YAML with `condition_key`, `value_match`, and `steps_to_insert`
- Engine evaluates rules after step execution and injects steps if conditions match
- Used for runtime workflow customization (e.g., routing to different underwriting paths)

**Human-in-the-Loop**
- Raise `WorkflowPauseDirective(result={...})` to pause workflow
- Workflow enters `WAITING_HUMAN` status
- Resume via `/api/v1/workflow/{workflow_id}/resume` endpoint with input data

## Key Patterns

### Adding a New Workflow

1. **Define State Model** in `state_models.py`:
   ```python
   class MyWorkflowState(BaseModel):
       field1: str
       field2: Optional[int] = None
   ```

2. **Implement Step Functions** in `workflow_utils.py`:
   ```python
   def my_step(state: MyWorkflowState, param: str):
       state.field1 = param
       return {"result": "success"}

   @celery_app.task
   def my_async_step(state: dict):
       time.sleep(5)  # Long operation
       return {"async_result": "done"}
   ```

3. **Create Workflow YAML** in `config/`:
   ```yaml
   workflow_type: "MyWorkflow"
   initial_state_model: "state_models.MyWorkflowState"
   steps:
     - name: "My_Step"
       type: "STANDARD"
       function: "workflow_utils.my_step"
     - name: "My_Async_Step"
       type: "ASYNC"
       function: "workflow_utils.my_async_step"
       dependencies: ["My_Step"]
   ```

4. **Register in `config/workflow_registry.yaml`**:
   ```yaml
   - type: "MyWorkflow"
     description: "Description of my workflow"
     config_file: "config/my_workflow.yaml"
     initial_state_model: "state_models.MyWorkflowState"
   ```

### Async vs Sync Steps

- **Sync steps**: Execute in the request thread, return immediately
- **Async steps**: Dispatched to Celery, workflow enters `ACTIVE_ASYNC` status
  - Function must be decorated with `@celery_app.task`
  - Receives state as `dict` (not Pydantic model)
  - Use `task.s(state_dict)` syntax for Celery signature

### State Management

- State is a Pydantic model, automatically validated on updates
- For sync steps: receive state as model instance, modify directly
- For async steps: receive state as dict, return dict to merge into state
- All state changes are persisted to Redis after step execution
- State includes special fields like `async_task_id` for task tracking

### Testing Considerations

- Set `TESTING=true` environment variable to run parallel tasks synchronously
- Tests use pytest with fixtures for workflow instances
- Integration tests (`test_integration.py`) require Redis
- Mock Celery tasks for unit tests or use synchronous execution

## Important Notes

- **Path Resolution**: All function/model paths in YAML are resolved using `importlib`
- **Celery Discovery**: `celery_setup.py` must include all modules with `@celery_app.task` decorators
- **State Serialization**: State must be JSON-serializable; complex objects need custom serialization
- **Error Handling**: Failed steps set workflow status to `FAILED`; use retry endpoint to re-attempt
- **WebSocket Updates**: Real-time updates use Redis Pub/Sub (Redis) or LISTEN/NOTIFY (PostgreSQL)
- **Dynamic Injection**: Injected steps are inserted after the current step in execution order
- **Input Validation**: Use `input_model` in YAML to validate step inputs with Pydantic schemas

## Production Upgrades (NEW!)

### PostgreSQL Persistence

**Setup**:
```bash
# Install dependencies
pip install -r requirements.txt  # Includes asyncpg

# Initialize database
export DATABASE_URL="postgresql://user:pass@localhost:5432/confucius"
python scripts/init_database.py

# Switch backend
export WORKFLOW_STORAGE=postgres
```

**Features**:
- ACID-compliant transactions with SERIALIZABLE isolation
- Audit logging in `workflow_audit_log` table
- Performance metrics in `workflow_metrics` table
- Real-time updates via PostgreSQL LISTEN/NOTIFY
- Atomic task claiming with `FOR UPDATE SKIP LOCKED`

**Persistence Layer**: `src/confucius/persistence_postgres.py`

### Saga Pattern (Compensation/Rollback)

**Purpose**: Automatically undo completed steps when workflow fails

**Step 1 - Define Compensation** in `workflow_utils.py`:
```python
def charge_card(state: OrderState, amount: float, **kwargs):
    """Forward action"""
    tx_id = payment_api.charge(state.card_token, amount)
    state.transaction_id = tx_id
    return {"transaction_id": tx_id}

def refund_card(state: OrderState, **kwargs):
    """Compensation - reverses charge_card"""
    if state.transaction_id:
        payment_api.refund(state.transaction_id)
    return {"refunded": state.transaction_id}
```

**Step 2 - Link in YAML**:
```yaml
- name: "Charge_Card"
  type: "STANDARD"
  function: "workflow_utils.charge_card"
  compensate_function: "workflow_utils.refund_card"  # Links compensation
```

**Step 3 - Enable Saga Mode**:
```python
workflow = workflow_builder.create_workflow("OrderProcessing", {})
workflow.enable_saga_mode()  # Activates automatic rollback
```

**Behavior**:
- Tracks completed CompensatableStep instances in `completed_steps_stack`
- On failure, calls compensation functions in reverse order
- Workflow status becomes `FAILED_ROLLED_BACK`
- Compensation logged to `compensation_log` table (PostgreSQL backend)

**Auto-enabled** for: Payment, BankTransfer, OrderProcessing, LoanApplication workflows

### Sub-Workflows (Hierarchical Composition)

**Purpose**: Break complex workflows into reusable, composable units

**Parent Workflow** (`config/loan_workflow.yaml`):
```yaml
steps:
  - name: "Run_KYC"
    type: "STANDARD"
    function: "workflow_utils.trigger_kyc_workflow"
```

**Child Workflow** (`config/kyc_workflow.yaml`):
```yaml
workflow_type: "KYC"
steps:
  - name: "Verify_ID"
    type: "ASYNC"
    function: "workflow_utils.verify_id"
```

**Implementation** in `workflow_utils.py`:
```python
from confucius.workflow import StartSubWorkflowDirective

def trigger_kyc_workflow(state: LoanState, **kwargs):
    """Launches KYC as child workflow"""
    raise StartSubWorkflowDirective(
        workflow_type="KYC",
        initial_data={
            "user_id": state.user_id,
            "document_url": state.id_document_url
        },
        data_region="eu-central-1"  # Optional: override region
    )

def process_kyc_results(state: LoanState, **kwargs):
    """Executes after KYC child completes"""
    kyc_data = state.sub_workflow_results.get("KYC", {})

    if kyc_data.get("approved"):
        return {"kyc_status": "approved"}
    else:
        raise WorkflowPauseDirective(result={"requires_review": True})
```

**Execution Flow**:
1. Parent hits `trigger_kyc_workflow` → raises `StartSubWorkflowDirective`
2. Engine creates child workflow, sets `parent.status = "PENDING_SUB_WORKFLOW"`
3. Celery task `execute_sub_workflow` runs child to completion
4. Child results merged into `parent.state.sub_workflow_results[workflow_type]`
5. Parent status → "ACTIVE", resumes at next step

**Key Fields**:
- `parent_execution_id`: Links child to parent
- `blocked_on_child_id`: Parent tracks which child is running
- `sub_workflow_results`: Dict on parent state containing all child results

**Limitations**: Max nesting depth = 2 (configurable via `MAX_NESTING_DEPTH` env var)

### Migration from Redis to PostgreSQL

**Option 1**: Fresh start (recommended for new projects)
```bash
export WORKFLOW_STORAGE=postgres
python scripts/init_database.py
```

**Option 2**: Migrate existing workflows
```python
from confucius.persistence import migrate_redis_to_postgres

# One-time migration
migrate_redis_to_postgres()
```

**Dual-backend support**: Can run both simultaneously during migration
