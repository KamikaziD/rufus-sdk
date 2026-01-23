# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Rufus is a Python-native, SDK-first workflow engine designed for orchestrating complex business processes and AI pipelines. It emphasizes a declarative, developer-friendly approach where workflows are defined in YAML and executed via an embedded SDK. The project consists of:

1. **Core SDK** (`src/rufus/`) - The reusable workflow engine library
2. **CLI Tool** (`src/rufus_cli/`) - Command-line interface for validation and local testing
3. **Server** (`src/rufus_server/`) - Optional FastAPI wrapper for REST API access

The architecture separates workflow definition (YAML) from implementation (Python functions) and decouples core engine logic from external dependencies through pluggable provider interfaces.

## Development Commands

### Setup
```bash
# Install in development mode with all dependencies
pip install -r requirements.txt

# For PostgreSQL support
pip install asyncpg

# Start Redis (required for Celery executor)
docker run -d --name redis-server -p 6379:6379 redis
```

### Testing
```bash
# Run all tests with coverage
pytest

# Run specific test module
pytest tests/sdk/test_engine.py

# Run with verbose output
pytest -v

# Run single test
pytest tests/sdk/test_workflow.py::test_workflow_initialization

# Tests automatically exclude confucius/ and original_implementation_files/ directories
```

### Running the CLI
```bash
# Validate a workflow YAML file
rufus validate config/my_workflow.yaml

# Run a workflow locally (in-memory, synchronous)
rufus run config/my_workflow.yaml -d '{"field": "value"}'

# Specify custom registry
rufus run config/my_workflow.yaml --registry config/workflow_registry.yaml
```

### Running the Server (Optional)
```bash
# Start FastAPI development server
uvicorn rufus_server.main:app --reload

# Start Celery worker (for async execution)
celery -A rufus.implementations.execution.celery worker --loglevel=info
```

## Architecture

### Core Components

**Workflow Class (`src/rufus/workflow.py`)**
- Main class managing workflow lifecycle, state, and execution
- Delegates to providers for persistence, execution, and observability
- Handles all step types, directives, and control flow

**WorkflowEngine (Legacy, being phased out)**
- Located in `src/rufus/engine.py`
- Being migrated to unified `Workflow` class in `workflow.py`
- Contains orchestration logic including Saga pattern and dynamic injection

**WorkflowBuilder (`src/rufus/builder.py`)**
- Loads workflow definitions from YAML files
- Resolves function/model paths using `importlib`
- Manages workflow registry and auto-discovers `rufus-*` packages
- Creates `Workflow` instances with proper dependency injection

**Models (`src/rufus/models.py`)**
- Pydantic-based data structures for all workflow components
- `StepContext`: Provides context to step functions (workflow_id, step_name, previous results, loop state)
- `WorkflowStep` and subclasses: `CompensatableStep`, `AsyncWorkflowStep`, `HttpWorkflowStep`, `ParallelWorkflowStep`, `FireAndForgetWorkflowStep`, `LoopStep`, `CronScheduleWorkflowStep`
- Workflow directives (as exceptions): `WorkflowJumpDirective`, `WorkflowPauseDirective`, `StartSubWorkflowDirective`, `SagaWorkflowException`

### Provider Interfaces (`src/rufus/providers/`)

All external integrations are abstracted via Python Protocol interfaces:

**PersistenceProvider (`persistence.py`)**
- Defines how workflow state, audit logs, and task records are stored
- Methods: `save_workflow`, `get_workflow`, `claim_next_task`, etc.

**ExecutionProvider (`execution.py`)**
- Abstracts task execution environment
- Methods: `dispatch_async_task`, `dispatch_parallel_tasks`, `dispatch_sub_workflow`, `report_child_status_to_parent`, `execute_sync_step_function`

**WorkflowObserver (`observer.py`)**
- Hooks for workflow event observation
- Methods: `on_workflow_started`, `on_step_executed`, `on_workflow_completed`, `on_workflow_failed`, `on_workflow_status_changed`

**ExpressionEvaluator (`expression_evaluator.py`)**
- Evaluates conditions for decision steps and dynamic injection
- Default: simple Python expression evaluation

**TemplateEngine (`template_engine.py`)**
- Renders dynamic content from workflow state
- Default: Jinja2 implementation

### Default Implementations (`src/rufus/implementations/`)

**Persistence**
- `postgres.py`: PostgreSQL with JSONB, FOR UPDATE SKIP LOCKED, audit logging
- `memory.py`: In-memory storage for testing
- `redis.py`: Redis-based persistence

**Execution**
- `sync.py`: Synchronous executor for simple scenarios and testing
- `celery.py`: Distributed async/parallel execution via Celery
- `thread_pool.py`: Thread-based parallel execution
- `postgres_executor.py`: PostgreSQL-backed task queue

**Observability**
- `logging.py`: Console-based workflow event logging

**Templating**
- `jinja2.py`: Jinja2 template rendering

**Expression Evaluation**
- `simple.py`: Basic Python expression evaluator

### Workflow Configuration

**Registry (`config/workflow_registry.yaml`)**
- Master list of all available workflows
- Each entry defines: `type`, `config_file`, `initial_state_model`
- Optional `requires` key lists external `rufus-*` packages

**Workflow YAML Structure**
- `workflow_type`: Unique identifier
- `workflow_version`: Optional version string
- `initial_state_model`: Python path to Pydantic state model
- `steps`: List of step definitions

**Step Configuration Keys**
- `name`: Unique step identifier within workflow
- `type`: Execution type (STANDARD, ASYNC, DECISION, PARALLEL, etc.)
- `function`: Python path to step function
- `compensate_function`: Optional compensation logic for Saga pattern
- `input_model`: Pydantic model for input validation
- `automate_next`: Boolean flag to auto-execute next step
- `dependencies`: List of prerequisite step names
- `dynamic_injection`: Rules for runtime step insertion
- `routes`: Declarative routing for DECISION steps

## Key Patterns

### Adding a New Workflow

1. **Define State Model** (create new file or add to existing):
   ```python
   # my_app/state_models.py
   from pydantic import BaseModel
   from typing import Optional

   class MyWorkflowState(BaseModel):
       user_id: str
       status: Optional[str] = None
       result_data: Optional[dict] = None
   ```

2. **Implement Step Functions**:
   ```python
   # my_app/workflow_steps.py
   from rufus.models import StepContext
   from my_app.state_models import MyWorkflowState

   def process_data(state: MyWorkflowState, context: StepContext) -> dict:
       """Synchronous step function"""
       state.status = "processing"
       return {"processed": True}

   def async_operation(state: MyWorkflowState, context: StepContext) -> dict:
       """Async step (dispatched to executor)"""
       # Long-running operation
       return {"async_result": "completed"}
   ```

3. **Create Workflow YAML** (`config/my_workflow.yaml`):
   ```yaml
   workflow_type: "MyWorkflow"
   workflow_version: "1.0.0"
   initial_state_model: "my_app.state_models.MyWorkflowState"
   description: "My custom workflow"

   steps:
     - name: "Process_Data"
       type: "STANDARD"
       function: "my_app.workflow_steps.process_data"
       automate_next: true

     - name: "Async_Operation"
       type: "ASYNC"
       function: "my_app.workflow_steps.async_operation"
       dependencies: ["Process_Data"]
   ```

4. **Register in `config/workflow_registry.yaml`**:
   ```yaml
   workflows:
     - type: "MyWorkflow"
       description: "My custom workflow"
       config_file: "my_workflow.yaml"
       initial_state_model: "my_app.state_models.MyWorkflowState"
   ```

### Step Function Signature

All step functions must accept:
```python
def step_function(state: BaseModel, context: StepContext, **user_input) -> dict:
    """
    Args:
        state: The workflow's state (Pydantic model)
        context: StepContext with workflow_id, step_name, previous_step_result, etc.
        **user_input: Additional validated inputs passed to this step

    Returns:
        dict: Result data merged into workflow state
    """
    pass
```

### Control Flow Mechanisms

**Automated Step Chaining (`automate_next`)**
- Set `automate_next: true` in step config
- Return value becomes input for next step
- No additional API call needed

**Conditional Branching**
```python
from rufus.models import WorkflowJumpDirective

def decision_step(state: MyState, context: StepContext):
    if state.amount > 10000:
        raise WorkflowJumpDirective(target_step_name="High_Value_Process")
    else:
        raise WorkflowJumpDirective(target_step_name="Standard_Process")
```

**Human-in-the-Loop**
```python
from rufus.models import WorkflowPauseDirective

def approval_step(state: MyState, context: StepContext):
    raise WorkflowPauseDirective(result={"awaiting_approval": True})
```

**Sub-Workflows**
```python
from rufus.models import StartSubWorkflowDirective

def trigger_child(state: MyState, context: StepContext):
    raise StartSubWorkflowDirective(
        workflow_type="ChildWorkflow",
        initial_data={"user_id": state.user_id},
        owner_id=state.owner_id,
        data_region="us-east-1"
    )
```

**Parallel Execution**
```yaml
- name: "Parallel_Tasks"
  type: "PARALLEL"
  tasks:
    - name: "task1"
      function_path: "my_app.tasks.task1"
    - name: "task2"
      function_path: "my_app.tasks.task2"
  merge_strategy: "SHALLOW"  # or DEEP
  merge_conflict_behavior: "PREFER_NEW"  # or PREFER_OLD, RAISE_ERROR
  allow_partial_success: true
  timeout_seconds: 300
```

### Saga Pattern (Compensation)

**Enable Saga Mode**:
```python
# In application code
workflow = workflow_builder.create_workflow("OrderProcessing", initial_data)
workflow.enable_saga_mode()
```

**Define Compensatable Steps**:
```python
def charge_payment(state: OrderState, context: StepContext):
    tx_id = payment_service.charge(state.amount)
    state.transaction_id = tx_id
    return {"transaction_id": tx_id}

def refund_payment(state: OrderState, context: StepContext):
    """Compensation function - reverses charge_payment"""
    if state.transaction_id:
        payment_service.refund(state.transaction_id)
    return {"refunded": True}
```

**Link in YAML**:
```yaml
- name: "Charge_Payment"
  type: "STANDARD"
  function: "my_app.steps.charge_payment"
  compensate_function: "my_app.steps.refund_payment"
```

**Behavior**:
- On failure, compensation functions execute in reverse order
- Workflow status becomes `FAILED_ROLLED_BACK`
- Compensation logged to audit table (PostgreSQL backend)

### Sub-Workflow Status Bubbling

Child workflows report status changes to parents:
- `PENDING_SUB_WORKFLOW`: Child is running
- `WAITING_CHILD_HUMAN_INPUT`: Child paused for input
- `FAILED_CHILD_WORKFLOW`: Child failed
- Parent resumes when child completes
- Child results available in `state.sub_workflow_results[workflow_type]`

## Testing

### Using TestHarness
```python
from rufus.testing.harness import TestHarness

# Create test harness with in-memory providers
harness = TestHarness()

# Start workflow
workflow = harness.start_workflow(
    workflow_type="MyWorkflow",
    initial_data={"user_id": "123"}
)

# Execute next step
result = harness.next_step(workflow.id, user_input={"param": "value"})

# Check state
assert workflow.state.status == "completed"
```

### Testing Patterns
- Use in-memory persistence for unit tests
- Set `TESTING=true` to run parallel tasks synchronously
- Mock external services in step functions
- Use `pytest` fixtures for common setup

## Performance Optimizations (Phase 1)

Rufus SDK includes production-grade performance optimizations enabled by default:

### Optimizations Implemented

1. **uvloop Event Loop**
   - 2-4x faster async I/O operations
   - Configured automatically in `src/rufus/__init__.py`
   - Control via `RUFUS_USE_UVLOOP` environment variable
   ```python
   # Automatically enabled on import
   import rufus  # uvloop configured here
   ```

2. **orjson Serialization**
   - 3-5x faster JSON serialization/deserialization
   - Utility module: `src/rufus/utils/serialization.py`
   - Used in: postgres.py, redis.py, celery.py
   ```python
   from rufus.utils.serialization import serialize, deserialize

   # Fast serialization
   json_str = serialize({"key": "value"})
   data = deserialize(json_str)
   ```

3. **Optimized PostgreSQL Connection Pool**
   - Default: min=10, max=50 connections (tuned for high concurrency)
   - Configurable via constructor or environment variables
   ```python
   persistence = PostgresPersistenceProvider(
       db_url=db_url,
       pool_min_size=10,
       pool_max_size=50
   )
   ```
   - Environment variables:
     - `POSTGRES_POOL_MIN_SIZE` (default: 10)
     - `POSTGRES_POOL_MAX_SIZE` (default: 50)
     - `POSTGRES_POOL_COMMAND_TIMEOUT` (default: 10)
     - `POSTGRES_POOL_MAX_QUERIES` (default: 50000)
     - `POSTGRES_POOL_MAX_INACTIVE_LIFETIME` (default: 300)

4. **Import Caching**
   - Class-level cache in `WorkflowBuilder._import_cache`
   - 162x speedup for repeated step function imports
   - Reduces 5-10ms overhead per step execution
   ```python
   # Cached automatically - no code changes needed
   func = WorkflowBuilder._import_from_string("my_app.steps.process_data")
   ```

### Benchmark Results

Run benchmarks: `python tests/benchmarks/workflow_performance.py`

```
Serialization: 2,453,971 ops/sec (orjson)
Import Caching: 162x speedup
Async Latency: 5.5µs p50, 12.7µs p99 (uvloop)
Workflow Throughput: 703,633 workflows/sec (simplified)
```

### Performance Guidelines

**When writing new code:**
- Use `from rufus.utils.serialization import serialize, deserialize` for JSON operations
- Import caching is automatic - no code changes needed
- PostgreSQL pool settings can be tuned per deployment

**Configuration for different workloads:**
- **Low concurrency** (< 10 concurrent workflows):
  - `POSTGRES_POOL_MIN_SIZE=5`
  - `POSTGRES_POOL_MAX_SIZE=20`
- **Medium concurrency** (10-100 concurrent workflows):
  - `POSTGRES_POOL_MIN_SIZE=10` (default)
  - `POSTGRES_POOL_MAX_SIZE=50` (default)
- **High concurrency** (> 100 concurrent workflows):
  - `POSTGRES_POOL_MIN_SIZE=20`
  - `POSTGRES_POOL_MAX_SIZE=100`

**Disabling optimizations** (for debugging):
```bash
export RUFUS_USE_UVLOOP=false  # Use stdlib asyncio
export RUFUS_USE_ORJSON=false  # Use stdlib json
```

### Expected Gains

- **+50-100% throughput** for I/O-bound workflows
- **-30-40% latency** for async operations
- **-80% serialization time** for state persistence
- **-90% import overhead** for repeated step function calls

## Important Notes

- **Path Resolution**: All YAML paths resolved via `importlib.import_module`
- **State Serialization**: State must be JSON-serializable (Pydantic handles this)
- **Provider Injection**: All providers injected via `Workflow.__init__` or `WorkflowBuilder`
- **Async Execution**: Async steps dispatched to `ExecutionProvider`, not executed inline
- **Error Handling**: Uncaught exceptions set workflow status to `FAILED`
- **Dynamic Injection**: Evaluated after each step, can insert new steps at runtime
- **Parallel Merge Conflicts**: Logged as warnings when tasks return overlapping keys
- **Sub-Workflow Nesting**: Supports hierarchical composition with status propagation

## Recent Migration (SDK Extraction)

This codebase was recently refactored from "Confucius" to "Rufus" with a focus on:
- Extracting core SDK from monolithic application
- Unified `Workflow` class (consolidating `WorkflowEngine`)
- Improved provider interfaces and dependency injection
- Better separation of concerns (SDK vs Server vs CLI)
- Enhanced sub-workflow status propagation
- Improved parallel execution with conflict detection

When making changes, be aware that:
- Some legacy `confucius/` code still exists in the repo
- Documentation may reference old patterns
- Tests in `tests/sdk/` cover the new architecture
