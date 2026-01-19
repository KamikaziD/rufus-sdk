# Confucius Workflow Engine - Technical Documentation

This document provides a deep technical reference for the Confucius workflow orchestration engine, covering architecture, implementation details, and advanced technical considerations.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Core Components](#core-components)
3. [Persistence Layer](#persistence-layer)
4. [Async Execution Model](#async-execution-model)
5. [Sub-Workflow Execution](#sub-workflow-execution)
6. [Saga Pattern Implementation](#saga-pattern-implementation)
7. [WebSocket Real-Time Updates](#websocket-real-time-updates)
8. [Error Handling and Recovery](#error-handling-and-recovery)
9. [Scalability Considerations](#scalability-considerations)
10. [Security Considerations](#security-considerations)
11. [Performance Optimization](#performance-optimization)
12. [Monitoring and Observability](#monitoring-and-observability)

---

## Architecture Overview

### System Layers

The Confucius workflow engine is organized into four primary layers:

```
┌───────────────────────────────────────────────────────────┐
│                   Application Layer                        │
│  ┌──────────┐  ┌─────────────┐  ┌──────────────┐         │
│  │ FastAPI  │  │  WebSocket  │  │   Debug UI   │         │
│  │  Router  │  │   Handler   │  │   (contrib)  │         │
│  └────┬─────┘  └──────┬──────┘  └──────────────┘         │
└───────┼────────────────┼───────────────────────────────────┘
        │                │
┌───────┼────────────────┼───────────────────────────────────┐
│       ▼                ▼        Engine Layer               │
│  ┌──────────────────────────────────────┐                 │
│  │       Workflow Engine Core           │                 │
│  │  ┌────────────┐    ┌──────────────┐ │                 │
│  │  │ Workflow   │───▶│ Step Types   │ │                 │
│  │  │ Execution  │    │ - Standard   │ │                 │
│  │  │ - State    │    │ - Async      │ │                 │
│  │  │ - Steps    │    │ - Parallel   │ │                 │
│  │  │ - Saga     │    │ - Decision   │ │                 │
│  │  │ - Sub-wf   │    │ - HITL       │ │                 │
│  │  │            │    │ - HTTP       │ │                 │
│  │  └────────────┘    └──────────────┘ │                 │
│  │                                      │                 │
│  │  ┌────────────────────────────────┐ │                 │
│  │  │   WorkflowLoader & Builder     │ │                 │
│  │  │   - YAML parsing              │ │                 │
│  │  │   - Step instantiation        │ │                 │
│  │  │   - Registry management       │ │                 │
│  │  └────────────────────────────────┘ │                 │
│  └──────────────────────────────────────┘                 │
└────────┬───────────────────────────────────────────────────┘
         │
┌────────┼───────────────────────────────────────────────────┐
│        ▼            Persistence Layer                      │
│  ┌─────────────────────────────────────────────┐          │
│  │  Persistence Factory (persistence.py)       │          │
│  │  ┌──────────────┐      ┌─────────────────┐ │          │
│  │  │ Redis Store  │      │ PostgreSQL Store│ │          │
│  │  │ - Dev/Fast   │      │ - Prod/ACID     │ │          │
│  │  │ - Pub/Sub    │      │ - Audit logs    │ │          │
│  │  │ - Simple     │      │ - Task claiming │ │          │
│  │  └──────────────┘      └─────────────────┘ │          │
│  └─────────────────────────────────────────────┘          │
└────────┬───────────────────────────────────────────────────┘
         │
┌────────┼───────────────────────────────────────────────────┐
│        ▼           Async Execution Layer                   │
│  ┌─────────────────────────────────────────────┐          │
│  │         Celery Workers (tasks.py)            │          │
│  │  ┌─────────────────────────────────────┐   │          │
│  │  │ - Async step execution              │   │          │
│  │  │ - Parallel task coordination        │   │          │
│  │  │ - Sub-workflow execution            │   │          │
│  │  │ - Workflow resumption               │   │          │
│  │  └─────────────────────────────────────┘   │          │
│  └─────────────────────────────────────────────┘          │
└───────────────────────────────────────────────────────────┘
```

### Request Flow

#### Standard Step Execution

```
1. Client → POST /api/v1/workflow/{id}/next
2. Router loads workflow from persistence
3. Workflow.next_step() executes current step function
4. Function returns dict to update state
5. State merged, workflow saved
6. Response returned to client
```

#### Async Step Execution

```
1. Client → POST /api/v1/workflow/{id}/next
2. Router loads workflow from persistence
3. Workflow.next_step() detects AsyncWorkflowStep
4. Step dispatches Celery task with state data
5. Workflow status → PENDING_ASYNC, saved
6. Response 202 returned to client
   │
   └─→ [Async]
       7. Celery worker executes task
       8. Task result passed to resume_from_async_task
       9. Workflow reloaded, state updated
       10. Workflow advanced to next step
       11. Workflow saved with ACTIVE status
```

#### Sub-Workflow Execution

```
1. Client → POST /api/v1/workflow/{id}/next
2. Step raises StartSubWorkflowDirective
3. Engine creates child workflow
4. Parent status → PENDING_SUB_WORKFLOW
5. Child workflow dispatched to Celery
   │
   └─→ [Async]
       6. Celery executes child workflow steps
       7. Child completes
       8. resume_parent_from_child task triggered
       9. Child results merged into parent.state.sub_workflow_results
       10. Parent advanced to next step
```

---

## Core Components

### workflow.py

The heart of the engine. Contains all workflow and step classes.

#### Key Classes

**Workflow**
```python
class Workflow:
    def __init__(self, id, workflow_steps, initial_state_model, ...):
        self.id = id or str(uuid.uuid4())
        self.workflow_steps = workflow_steps or []
        self.current_step = 0
        self.state = initial_state_model
        self.status = "ACTIVE"

        # Saga support
        self.saga_mode = False
        self.completed_steps_stack = []

        # Sub-workflow support
        self.parent_execution_id = None
        self.blocked_on_child_id = None

        # Additional features
        self.data_region = None
        self.priority = 5
        self.idempotency_key = None
        self.metadata = {}
```

**Key Methods:**
- `next_step(user_input)`: Execute the current step
- `enable_saga_mode()`: Activate compensation tracking
- `_execute_saga_rollback()`: Run compensations in reverse order
- `_handle_sub_workflow(directive)`: Create and launch child workflow
- `_process_dynamic_injection()`: Evaluate and inject steps at runtime

#### Step Types

**WorkflowStep** (Base)
```python
class WorkflowStep:
    def __init__(self, name, func, required_input, input_schema, automate_next):
        self.name = name
        self.func = func  # Callable function
        self.required_input = required_input or []
        self.input_schema = input_schema  # Pydantic model
        self.automate_next = automate_next
```

**CompensatableStep**
```python
class CompensatableStep(WorkflowStep):
    def __init__(self, ..., compensate_func):
        super().__init__(...)
        self.compensate_func = compensate_func
        self.compensation_executed = False

    def compensate(self, state):
        """Execute compensation logic"""
        if not self.compensate_func or self.compensation_executed:
            return {"message": "..."}

        result = self.compensate_func(state=state)
        self.compensation_executed = True
        return result
```

**AsyncWorkflowStep**
```python
class AsyncWorkflowStep(WorkflowStep):
    def __init__(self, name, func_path, ...):
        super().__init__(name, None, ...)  # No immediate func
        self.func_path = func_path  # Import path string

    def dispatch_async_task(self, state, workflow_id, current_step_index):
        """Dispatch task to Celery"""
        # Import the task function dynamically
        module_path, func_name = self.func_path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        task_func = getattr(module, func_name)

        # Create Celery chain: task → resume callback
        task_chain = chain(
            task_func.s(state.model_dump()),
            resume_from_async_task.s(workflow_id, current_step_index)
        )

        async_result = task_chain.apply_async()
        return {"_async_dispatch": True, "task_id": async_result.id}
```

**ParallelWorkflowStep**
```python
class ParallelWorkflowStep(WorkflowStep):
    def __init__(self, name, tasks, merge_function_path, automate_next):
        super().__init__(name=name, func=self.dispatch_parallel_tasks, ...)
        self.tasks = tasks  # List of ParallelExecutionTask
        self.merge_function_path = merge_function_path

    def dispatch_parallel_tasks(self, state, workflow_id, current_step_index):
        """Dispatch multiple tasks in parallel"""
        celery_tasks = []
        for task_def in self.tasks:
            # Import and instantiate each task
            module_path, func_name = task_def.func_path.rsplit('.', 1)
            module = importlib.import_module(module_path)
            task_func = getattr(module, func_name)
            celery_tasks.append(task_func.s(state.model_dump()))

        # Create group → merge callback
        task_group = group(celery_tasks)
        callback = merge_and_resume_parallel_tasks.s(
            workflow_id=workflow_id,
            current_step_index=current_step_index,
            merge_function_path=self.merge_function_path
        )
        chain(task_group, callback).apply_async()

        return {"_async_dispatch": True}

**HttpWorkflowStep**
```python
class HttpWorkflowStep(AsyncWorkflowStep):
    def __init__(self, name, http_config, ...):
        super().__init__(
            name=name,
            func_path="confucius.tasks.execute_http_request",
            ...
        )
        self.http_config = http_config # method, url, headers, body, includes

    def dispatch_async_task(self, state, workflow_id, current_step_index, **kwargs):
        # Merge static config into dynamic execution context
        kwargs.update(self.http_config)
        return super().dispatch_async_task(state, workflow_id, current_step_index, **kwargs)
```

**FireAndForgetWorkflowStep**
```python
class FireAndForgetWorkflowStep(WorkflowStep):
    def __init__(self, name, target_workflow_type, initial_data_template, ...):
        super().__init__(name=name, func=self._spawn_workflow, ...)
        self.target_workflow_type = target_workflow_type
        self.initial_data_template = initial_data_template # {{state.field}} templating

    def _spawn_workflow(self, state, workflow_id):
        """Creates and dispatches an independent workflow"""
        # 1. Resolve templates in initial_data
        # 2. Instantiate target workflow via workflow_builder
        # 3. Save child and dispatch via execute_independent_workflow.delay()
        # 4. Return immediately without pausing parent
        # 5. Adds record to state.spawned_workflows
```

**LoopStep**
```python
class LoopStep(WorkflowStep):
    def __init__(self, name, loop_body, mode, iterate_over, while_condition, ...):
        super().__init__(name=name, func=self._execute_loop, ...)
        self.loop_body = loop_body # List of WorkflowStep
        self.mode = mode # "ITERATE" or "WHILE"
        self.iterate_over = iterate_over
        self.while_condition = while_condition

    def _execute_loop(self, state, workflow_id, **kwargs):
        """Executes the loop body repeatedly"""
        # 1. Evaluate termination condition
        # 2. Synchronously execute steps in loop_body
        # 3. Handle state updates per iteration (item_var_name)
        # Note: Step functions in loop body MUST accept **kwargs
        # Note: 'iterate_over' paths starting with 'state.' are automatically resolved.
```

**CronScheduleWorkflowStep**
```python
class CronScheduleWorkflowStep(WorkflowStep):
    def __init__(self, name, target_workflow_type, cron_expression, initial_data_template, ...):
        super().__init__(name=name, func=self._register_schedule, ...)
        self.target_workflow_type = target_workflow_type
        self.cron_expression = cron_expression
        self.initial_data_template = initial_data_template

    def _register_schedule(self, state, workflow_id, **kwargs):
        """Registers a new dynamic schedule in the database"""
        # 1. Resolve data templates
        # 2. Insert into 'scheduled_workflows' table
        # 3. Polled by 'poll_scheduled_workflows' Celery task
```

### Important: Step Function Signatures

All step functions must now accept `**kwargs` to handle metadata injected by the engine (such as `workflow_id` or loop variables).

```python
def my_step_function(state: MyState, **kwargs):
    workflow_id = kwargs.get('workflow_id')
    # ... logic ...
```

**Key Features:**
- **Templating:** Supports `{variable.path}` substitution in URL, headers, and body.
- **Filtering:** Use `includes: ["body", "status_code"]` to prune large API responses before saving to state.
- **Polyglot:** Allows orchestration of non-Python microservices via standard REST/HTTP.

#### Directives (Exceptions for Flow Control)

**WorkflowJumpDirective**
```python
class WorkflowJumpDirective(Exception):
    """Jump to a specific step"""
    def __init__(self, target_step_name):
        self.target_step_name = target_step_name
```

**WorkflowPauseDirective**
```python
class WorkflowPauseDirective(Exception):
    """Pause workflow for human input"""
    def __init__(self, result):
        self.result = result  # Data to return
```

**StartSubWorkflowDirective**
```python
class StartSubWorkflowDirective(Exception):
    """Launch a child workflow"""
    def __init__(self, workflow_type, initial_data, data_region=None):
        self.workflow_type = workflow_type
        self.initial_data = initial_data
        self.data_region = data_region
```

**SagaWorkflowException**
```python
class SagaWorkflowException(Exception):
    """Indicates saga failure and rollback"""
    def __init__(self, failed_step, original_error):
        self.failed_step = failed_step
        self.original_error = original_error
```

### workflow_loader.py

Parses YAML configurations and builds workflow instances.

**WorkflowBuilder**
```python
class WorkflowBuilder:
    def __init__(self, registry_path="config/workflow_registry.yaml"):
        self.registry_path = registry_path
        self._registry = None  # Loaded on first access
        self._workflow_configs = {}  # Cached configs

    def create_workflow(self, workflow_type, initial_data):
        """Main entry point: create a new workflow instance"""
        # 1. Get state model class from registry
        state_model_class = self._registry[workflow_type]["initial_state_model"]

        # 2. Initialize state with provided data
        initial_state = state_model_class(**initial_data)

        # 3. Load and build steps from YAML
        workflow_config = self.get_workflow_config(workflow_type)
        steps_config = workflow_config.get("steps", [])
        workflow_steps = _build_steps_from_config(steps_config)

        # 4. Create Workflow instance
        return Workflow(
            workflow_type=workflow_type,
            workflow_steps=workflow_steps,
            initial_state_model=initial_state,
            steps_config=steps_config,
            state_model_path=state_model_path
        )
```

**_build_steps_from_config**
```python
def _build_steps_from_config(steps_config):
    """Convert YAML step configs to Step objects"""
    steps = []
    for config in steps_config:
        step_type = config.get("type", "STANDARD")

        if step_type == "PARALLEL":
            # Build ParallelWorkflowStep with tasks
            tasks = [ParallelExecutionTask(...) for task in config["tasks"]]
            step = ParallelWorkflowStep(name=config["name"], tasks=tasks, ...)

        elif step_type == "ASYNC":
            # Build AsyncWorkflowStep with function path
            step = AsyncWorkflowStep(
                name=config["name"],
                func_path=config["function"],
                ...
            )

        else:
            # Build standard or compensatable step
            func = _import_from_string(config["function"])
            compensate_func = _import_from_string(config.get("compensate_function"))

            if compensate_func:
                step = CompensatableStep(name, func, compensate_func, ...)
            else:
                step = WorkflowStep(name, func, ...)

        steps.append(step)

    return steps
```

### routers.py

FastAPI router factory providing REST API endpoints.

**Key Endpoints:**

```python
@router.post("/workflow/start")
async def start_workflow(request: WorkflowStartRequest):
    """Create and initialize a new workflow"""
    workflow = workflow_builder.create_workflow(
        request.workflow_type,
        request.initial_data
    )
    await save_workflow_state(workflow.id, workflow)
    return WorkflowStartResponse(workflow_id=workflow.id, ...)

@router.post("/workflow/{workflow_id}/next")
async def next_workflow_step(workflow_id, request: WorkflowStepRequest):
    """Execute the next step in the workflow"""
    workflow = await load_workflow_state(workflow_id)

    try:
        result, next_step = workflow.next_step(request.input_data)
        await save_workflow_state(workflow_id, workflow)

        if workflow.status == "PENDING_ASYNC":
            return JSONResponse(status_code=202, content={...})

        return WorkflowStepResponse(workflow_id, result, ...)
    except Exception as e:
        workflow.status = "FAILED"
        await save_workflow_state(workflow_id, workflow)
        raise HTTPException(500, str(e))

@router.post("/workflow/{workflow_id}/resume")
async def resume_workflow(workflow_id, request: ResumeWorkflowRequest):
    """Resume a workflow paused for human input"""
    workflow = await load_workflow_state(workflow_id)

    if workflow.status != "WAITING_HUMAN":
        raise HTTPException(400, "Not awaiting human input")

    # Advance to next step and execute with resume data
    workflow.current_step += 1
    next_step_obj = workflow.workflow_steps[workflow.current_step]
    result = next_step_obj.func(state=workflow.state, **request.dict())

    workflow.status = "ACTIVE"
    await save_workflow_state(workflow_id, workflow)

    # Continue execution
    workflow.next_step({})
    await save_workflow_state(workflow_id, workflow)

    return WorkflowStepResponse(...)
```

---

## Persistence Layer

### Architecture

The persistence layer uses a **factory pattern** to support multiple backends.

**persistence.py** (Factory)
```python
def save_workflow_state(workflow_id, workflow_instance):
    """Save workflow to configured backend"""
    backend = os.getenv('WORKFLOW_STORAGE', 'redis').lower()

    if backend in ['postgres', 'postgresql']:
        # PostgreSQL: async operation
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return asyncio.create_task(_async_save_postgres(...))
        else:
            loop.run_until_complete(_async_save_postgres(...))
    else:
        # Redis: sync operation
        _save_to_redis(workflow_id, workflow_instance)

def load_workflow_state(workflow_id):
    """Load workflow from configured backend"""
    backend = os.getenv('WORKFLOW_STORAGE', 'redis').lower()

    if backend in ['postgres', 'postgresql']:
        return _load_from_postgres(workflow_id)
    else:
        return _load_from_redis(workflow_id)
```

### Redis Backend

**Use Case**: Development, testing, simple deployments

**Implementation**:
```python
def _save_to_redis(workflow_id, workflow):
    """Save to Redis with pub/sub notification"""
    workflow_dict = workflow.to_dict()
    serialized = json.dumps(workflow_dict)

    # Save workflow state
    redis_client.set(f"workflow:{workflow_id}", serialized)

    # Publish update for WebSocket subscribers
    channel = f"workflow_events:{workflow_id}"
    redis_client.publish(channel, serialized)

def _load_from_redis(workflow_id):
    """Load workflow from Redis"""
    data = redis_client.get(f"workflow:{workflow_id}")
    if not data:
        return None

    workflow_dict = json.loads(data)
    return Workflow.from_dict(workflow_dict)
```

**Pros**:
- Fast in-memory operations
- Simple setup
- Built-in pub/sub for WebSocket

**Cons**:
- No persistence guarantees
- No ACID transactions
- Limited query capabilities

### PostgreSQL Backend

**Use Case**: Production deployments, compliance requirements

**Schema** (from migrations/001_init_postgresql_schema.sql):
```sql
CREATE TABLE workflow_executions (
    id UUID PRIMARY KEY,
    workflow_type VARCHAR(255) NOT NULL,
    current_step INTEGER NOT NULL,
    status VARCHAR(50) NOT NULL,
    state JSONB NOT NULL,
    steps_config JSONB NOT NULL,
    state_model_path TEXT NOT NULL,
    saga_mode BOOLEAN DEFAULT FALSE,
    completed_steps_stack JSONB DEFAULT '[]',
    parent_execution_id UUID REFERENCES workflow_executions(id),
    blocked_on_child_id UUID,
    data_region VARCHAR(50) DEFAULT 'us-east-1',
    priority INTEGER DEFAULT 5,
    idempotency_key VARCHAR(255) UNIQUE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_workflow_status ON workflow_executions(status);
CREATE INDEX idx_workflow_type ON workflow_executions(workflow_type);
CREATE INDEX idx_parent_execution ON workflow_executions(parent_execution_id);
CREATE INDEX idx_idempotency ON workflow_executions(idempotency_key);

-- Audit logging
CREATE TABLE workflow_audit_log (
    id SERIAL PRIMARY KEY,
    workflow_id UUID NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    step_name VARCHAR(255),
    user_id VARCHAR(255),
    worker_id VARCHAR(255),
    old_state JSONB,
    new_state JSONB,
    decision_rationale TEXT,
    metadata JSONB,
    recorded_at TIMESTAMP DEFAULT NOW()
);

-- Saga compensation tracking
CREATE TABLE compensation_log (
    id SERIAL PRIMARY KEY,
    execution_id UUID NOT NULL,
    step_name VARCHAR(255) NOT NULL,
    step_index INTEGER NOT NULL,
    action_type VARCHAR(50) NOT NULL,  -- FORWARD, COMPENSATE, COMPENSATE_FAILED
    action_result JSONB,
    error_message TEXT,
    state_before JSONB,
    state_after JSONB,
    executed_by VARCHAR(255),
    executed_at TIMESTAMP DEFAULT NOW()
);

-- Metrics
CREATE TABLE workflow_metrics (
    id SERIAL PRIMARY KEY,
    workflow_id UUID NOT NULL,
    workflow_type VARCHAR(255),
    step_name VARCHAR(255),
    metric_name VARCHAR(255) NOT NULL,
    metric_value FLOAT NOT NULL,
    unit VARCHAR(50),
    tags JSONB,
    recorded_at TIMESTAMP DEFAULT NOW()
);
```

**Implementation**:
```python
class PostgresWorkflowStore:
    def __init__(self, db_url):
        self.db_url = db_url
        self.pool = None

    async def initialize(self):
        """Create connection pool"""
        self.pool = await asyncpg.create_pool(
            self.db_url,
            min_size=5,
            max_size=20,
            command_timeout=60
        )

    async def save_workflow(self, workflow_id, workflow):
        """Atomic upsert with JSONB support"""
        workflow_dict = workflow.to_dict()

        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO workflow_executions (
                    id, workflow_type, current_step, status,
                    state, steps_config, state_model_path, ...
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, ...)
                ON CONFLICT (id) DO UPDATE SET
                    current_step = EXCLUDED.current_step,
                    status = EXCLUDED.status,
                    state = EXCLUDED.state,
                    updated_at = NOW()
            """,
                workflow_id,
                workflow_dict['workflow_type'],
                workflow_dict['current_step'],
                workflow_dict['status'],
                json.dumps(workflow_dict['state']),  # JSONB
                ...
            )

    async def load_workflow(self, workflow_id):
        """Load with JSONB deserialization"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM workflow_executions WHERE id = $1
            """, workflow_id)

            if not row:
                return None

            workflow_dict = {
                'id': str(row['id']),
                'workflow_type': row['workflow_type'],
                'state': json.loads(row['state']),  # Deserialize JSONB
                ...
            }

            return Workflow.from_dict(workflow_dict)
```

### Database Concurrency (The PostgresExecutor Bridge)

A critical challenge in Python workflow engines is managing database connections when mixing synchronous code (Celery tasks) with asynchronous drivers (`asyncpg`).

**The Problem:**
Standard `asyncpg` connection pools are bound to a specific `asyncio` event loop. Celery workers, being inherently synchronous or using their own event loop management, often create new loops for execution or run in threads where the main loop is inaccessible. This leads to `InterfaceError: another operation is in progress` or `ConnectionDoesNotExistError`.

**The Solution: `PostgresExecutor`**
Confucius solves this with a dedicated, thread-safe executor bridge (`src/confucius/postgres_executor.py`).

1.  **Dedicated Thread:** On startup, a singleton `_PostgresExecutor` spins up a daemon thread running a permanent `asyncio` event loop.
2.  **Thread-Safe Submission:** Synchronous code submits coroutines to this loop using `run_coroutine_sync(coro)`.
3.  **Result Marshaling:** The executor waits for the future to complete and returns the result to the caller thread, handling timeouts and exceptions.

**Implementation:**
```python
# src/confucius/postgres_executor.py
class _PostgresExecutor:
    def __init__(self):
        self._thread = threading.Thread(target=self._run_loop, ...)
        self._loop = None # The dedicated loop

    def run_coroutine_sync(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

# Usage in Persistence Layer
def save_workflow_state(workflow_id, workflow, sync=False):
    if sync:
        # Force execution on the safe executor thread
        return pg_executor.run_coroutine_sync(
            _async_save_postgres(workflow_id, workflow)
        )
    # ...
```

This architecture ensures that all database operations—whether from an async FastAPI route or a synchronous Celery task—are serialized through a stable, healthy event loop with a persistent connection pool.

**Advanced Features**:

1. **Atomic Task Claiming** (FOR UPDATE SKIP LOCKED):
```python
async def claim_pending_task(self, worker_id):
    """Atomically claim a task for distributed workers"""
    async with self.pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE tasks
            SET status = 'RUNNING',
                worker_id = $1,
                claimed_at = NOW()
            WHERE task_id = (
                SELECT task_id FROM tasks
                WHERE status = 'PENDING'
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
        """, worker_id)

        return row
```

2. **Audit Logging**:
```python
async def log_audit_event(self, workflow_id, event_type, **kwargs):
    """Log compliance event"""
    await conn.execute("""
        INSERT INTO workflow_audit_log (
            workflow_id, event_type, step_name,
            user_id, old_state, new_state, ...
        ) VALUES ($1, $2, $3, $4, $5, $6, ...)
    """, workflow_id, event_type, ...)
```

3. **Performance Metrics**:
```python
async def record_metric(self, workflow_id, metric_name, value, **kwargs):
    """Record performance metric"""
    await conn.execute("""
        INSERT INTO workflow_metrics (
            workflow_id, metric_name, metric_value, unit, tags
        ) VALUES ($1, $2, $3, $4, $5)
    """, workflow_id, metric_name, value, ...)
```

---

## Async Execution Model

### Celery Integration

**Celery Configuration** (celery_app.py):
```python
from celery import Celery
from src.confucius.workflow_loader import workflow_builder

# Automatically discover task modules from registered workflows
discovered_task_modules = workflow_builder.get_all_task_modules()

celery_app = Celery('confucius')

celery_app.conf.update(
    include=['src.confucius.tasks'] + discovered_task_modules,
    # ... other settings
)
```

### Dynamic Task Discovery

The engine implements an automatic discovery mechanism for Celery tasks to minimize configuration overhead.

1.  **Scanning**: On startup, `WorkflowBuilder` iterates through all registered workflows in `workflow_registry.yaml`.
2.  **Extraction**: It parses every step configuration, looking for:
    *   `ASYNC` steps (`function` path)
    *   `PARALLEL` steps (`tasks` list paths and `merge_function_path`)
    *   `dynamic_injection` rules (`steps_to_insert`)
    *   `compensate_function` paths
3.  **Collection**: It extracts the module path (e.g., `my_app.integrations.stripe`) from each function reference.
4.  **Registration**: The set of unique module paths is passed to Celery's `include` configuration.

This ensures that any Python module containing a task referenced in YAML is automatically loaded by the Celery worker.

### Task Definitions (tasks.py)

**resume_from_async_task**
```python
@celery_app.task
def resume_from_async_task(result, workflow_id, current_step_index):
    """Resume workflow after async step completes"""
    resume_workflow_from_celery(
        workflow_id,
        result,  # Task result to merge into state
        current_step_index + 1,  # Advance to next step
        completed_step_index=current_step_index
    )
```

**merge_and_resume_parallel_tasks**
```python
@celery_app.task
def merge_and_resume_parallel_tasks(
    results, workflow_id, current_step_index, merge_function_path
):
    """Merge parallel task results and resume workflow"""
    if merge_function_path:
        # Use custom merge function
        merge_func = _import_from_string(merge_function_path)
        merged = merge_func(results)
    else:
        # Default: merge all dicts
        merged = {}
        for res in results:
            if isinstance(res, dict):
                merged.update(res)

    resume_workflow_from_celery(
        workflow_id,
        merged,
        current_step_index + 1,
        completed_step_index=current_step_index
    )
```

**execute_sub_workflow**
```python
@celery_app.task
def execute_sub_workflow(child_id, parent_id):
    """Execute child workflow to completion"""
    child = load_workflow_state(child_id)

    max_iterations = 1000
    iterations = 0

    # Run child until blocked or complete
    while child.status == "ACTIVE" and iterations < max_iterations:
        try:
            result, next_step = child.next_step(user_input={})
            save_workflow_state(child_id, child)

            # Child hit async or human step - pause
            if child.status in ["PENDING_ASYNC", "WAITING_HUMAN"]:
                return

            iterations += 1
        except Exception as e:
            child.status = "FAILED"
            save_workflow_state(child_id, child)
            # Propagate failure to parent
            parent = load_workflow_state(parent_id)
            parent.status = "FAILED"
            save_workflow_state(parent_id, parent)
            return

    # Child completed - resume parent
    if child.status == "COMPLETED":
        resume_parent_from_child.delay(parent_id, child_id)
```

**resume_parent_from_child**
```python
@celery_app.task
def resume_parent_from_child(parent_id, child_id):
    """Merge child results and resume parent"""
    parent = load_workflow_state(parent_id)
    child = load_workflow_state(child_id)

    # Merge child state into parent
    if not parent.state.sub_workflow_results:
        parent.state.sub_workflow_results = {}
    parent.state.sub_workflow_results[child.workflow_type] = child.state.model_dump()

    # Resume parent
    parent.current_step += 1
    parent.status = "ACTIVE"
    parent.blocked_on_child_id = None
    save_workflow_state(parent_id, parent)

    # Continue parent execution
    parent.next_step(user_input={})
    save_workflow_state(parent_id, parent)
```

### Execution Patterns

**Pattern 1: Simple Async Step**
```
1. Workflow dispatches task
2. Status → PENDING_ASYNC
3. Task executes independently
4. Task result → resume_from_async_task
5. Workflow reloaded, state updated, advanced
6. Status → ACTIVE
```

**Pattern 2: Parallel Execution**
```
1. Workflow dispatches group of tasks
2. Status → PENDING_ASYNC
3. All tasks execute concurrently
4. Results collected by Celery
5. Results → merge_and_resume_parallel_tasks
6. Custom merge function applied
7. Workflow reloaded, state updated, advanced
8. Status → ACTIVE
```

**Pattern 3: Nested Sub-Workflows**
```
Parent Workflow
  ├─ Step 1
  ├─ Step 2 → Launch Child A
  │   Child A Workflow
  │     ├─ Child Step 1
  │     ├─ Child Step 2 → Launch Child B
  │     │   Child B Workflow
  │     │     ├─ Grand-child Step 1
  │     │     └─ Grand-child Step 2 → Complete
  │     ├─ Child Step 3 (resumes after B)
  │     └─ Child Step 4 → Complete
  ├─ Step 3 (resumes after A)
  └─ Step 4
```

---

## Sub-Workflow Execution

### Implementation Details

**Creating Child Workflow**:
```python
def _handle_sub_workflow(self, directive):
    """Create and launch child workflow"""
    # 1. Load child workflow config from registry
    registry_data = yaml.safe_load(open('config/workflow_registry.yaml'))
    workflow_config = find_config(directive.workflow_type)

    # 2. Build child workflow
    state_model_class = _import_from_string(workflow_config['initial_state_model'])
    initial_state = state_model_class(**directive.initial_data)
    workflow_steps = _build_steps_from_config(workflow_yaml['steps'])

    child = Workflow(
        workflow_steps=workflow_steps,
        initial_state_model=initial_state,
        workflow_type=directive.workflow_type,
        ...
    )

    # 3. Set parent relationship
    child.parent_execution_id = self.id
    child.data_region = directive.data_region or self.data_region

    # 4. Pause parent
    self.status = "PENDING_SUB_WORKFLOW"
    self.blocked_on_child_id = child.id

    # 5. Save both
    save_workflow_state(self.id, self)
    save_workflow_state(child.id, child)

    # 6. Dispatch child execution
    execute_sub_workflow.delay(child.id, self.id)

    return {"child_workflow_id": child.id}, None
```

### State Merging

Child results are stored in parent's `sub_workflow_results`:

```python
# Parent state model
class ParentState(BaseModel):
    # ... fields ...
    sub_workflow_results: Optional[Dict[str, Any]] = {}

# After child completes
parent.state.sub_workflow_results = {
    "KYC": {
        "kyc_passed": True,
        "verification_level": "full",
        "document_verified": True
    },
    "CreditCheck": {
        "score": 750,
        "report_id": "CR-12345"
    }
}
```

Access in subsequent steps:

```python
def process_results(state: ParentState):
    kyc_data = state.sub_workflow_results.get('KYC', {})
    if kyc_data.get('kyc_passed'):
        return {"kyc_status": "verified"}
```

---

## Saga Pattern Implementation

### Compensation Tracking

When saga mode is enabled, the engine tracks completed compensatable steps:

```python
def next_step(self, user_input):
    step = self.workflow_steps[self.current_step]

    # Snapshot state BEFORE execution
    if self.saga_mode and isinstance(step, CompensatableStep):
        state_snapshot = self.state.model_dump()

    # Execute step
    try:
        result = step.func(state=self.state)

        # Track successful compensation
        if self.saga_mode and isinstance(step, CompensatableStep):
            self.completed_steps_stack.append({
                'step_index': self.current_step,
                'step_name': step.name,
                'state_snapshot': state_snapshot
            })

        # Continue...

    except Exception as e:
        # Saga rollback on failure
        if self.saga_mode and self.completed_steps_stack:
            self._execute_saga_rollback()
            self.status = "FAILED_ROLLED_BACK"
            raise SagaWorkflowException(step.name, e)
        else:
            self.status = "FAILED"
            raise
```

### Rollback Execution

```python
def _execute_saga_rollback(self):
    """Compensate in reverse order"""
    for entry in reversed(self.completed_steps_stack):
        step_index = entry['step_index']
        step = self.workflow_steps[step_index]

        if isinstance(step, CompensatableStep):
            try:
                result = step.compensate(self.state)

                # Log compensation
                if hasattr(self.state, 'saga_log'):
                    self.state.saga_log.append({
                        'step': step.name,
                        'action': 'COMPENSATE',
                        'result': result
                    })

            except Exception as e:
                # Log failure but continue rollback
                if hasattr(self.state, 'saga_log'):
                    self.state.saga_log.append({
                        'step': step.name,
                        'action': 'COMPENSATE_FAILED',
                        'error': str(e)
                    })

    save_workflow_state(self.id, self)
```

### Example Saga Flow

```yaml
steps:
  - name: "Reserve_Inventory"
    function: "inventory.reserve"
    compensate_function: "inventory.release"

  - name: "Charge_Payment"
    function: "payment.charge"
    compensate_function: "payment.refund"

  - name: "Create_Shipment"
    function: "shipping.create"
    compensate_function: "shipping.cancel"
```

Execution:
```
1. Reserve_Inventory → SUCCESS (tracked)
2. Charge_Payment → SUCCESS (tracked)
3. Create_Shipment → FAILURE

Rollback:
3. shipping.cancel(state) → Undo shipment
2. payment.refund(state) → Refund charge
1. inventory.release(state) → Release reservation

Final status: FAILED_ROLLED_BACK
```

---

## WebSocket Real-Time Updates

### Redis Pub/Sub Implementation

**Subscription Endpoint**:
```python
@router.websocket("/workflow/{workflow_id}/subscribe")
async def workflow_subscribe(websocket, workflow_id):
    await websocket.accept()

    redis_client = aredis.Redis(...)
    pubsub = redis_client.pubsub()
    channel = f"workflow_events:{workflow_id}"

    try:
        # Send initial state
        initial_state = await redis_client.get(f"workflow:{workflow_id}")
        if initial_state:
            await websocket.send_text(initial_state)

        # Subscribe to updates
        await pubsub.subscribe(channel)

        # Event loop
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1.0
            )
            if message:
                await websocket.send_text(message['data'])

            await asyncio.sleep(0.01)

    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await redis_client.close()
```

**Publishing Updates**:

Every workflow state save triggers a Redis publish:
```python
def _save_to_redis(workflow_id, workflow):
    serialized = json.dumps(workflow.to_dict())

    # Save state
    redis_client.set(f"workflow:{workflow_id}", serialized)

    # Notify subscribers
    redis_client.publish(f"workflow_events:{workflow_id}", serialized)
```

### Client-Side Implementation

```javascript
// Connect to WebSocket
const ws = new WebSocket(`ws://localhost:8000/api/v1/workflow/${workflowId}/subscribe`);

ws.onmessage = (event) => {
    const workflow = JSON.parse(event.data);

    // Update UI
    updateStatus(workflow.status);
    updateCurrentStep(workflow.current_step);
    updateState(workflow.state);

    // Highlight completed steps
    workflow.workflow_steps.slice(0, workflow.current_step).forEach(step => {
        markComplete(step.name);
    });
};

ws.onerror = (error) => {
    console.error('WebSocket error:', error);
    // Implement reconnection logic
};
```

---

## Error Handling and Recovery

### Error Categories

1. **Validation Errors**: Input doesn't match Pydantic schema
2. **Step Execution Errors**: Exception in step function
3. **Async Task Failures**: Celery task fails
4. **Sub-Workflow Failures**: Child workflow fails
5. **Saga Compensation Failures**: Compensation function fails

### Error Handling Strategies

**1. Input Validation**:
```python
try:
    if step.input_schema:
        validated = step.input_schema(**user_input)
        kwargs = validated.model_dump()
except ValidationError as e:
    raise ValueError(f"Invalid input: {e}")
```

**2. Step Execution**:
```python
try:
    result = step.func(state=self.state, **kwargs)
except Exception as e:
    if self.saga_mode:
        self._execute_saga_rollback()
        self.status = "FAILED_ROLLED_BACK"
        raise SagaWorkflowException(step.name, e)
    else:
        self.status = "FAILED"
        raise
```

**3. Retry Mechanism**:
```python
@router.post("/workflow/{workflow_id}/retry")
async def retry_workflow(workflow_id):
    workflow = await load_workflow_state(workflow_id)

    if workflow.status != "FAILED":
        raise HTTPException(400, "Workflow not failed")

    # Reset to ACTIVE and retry current step
    workflow.status = "ACTIVE"
    await save_workflow_state(workflow_id, workflow)

    return {"status": "ACTIVE", "current_step": workflow.current_step_name}
```

### Recovery Patterns

**Pattern 1: Exponential Backoff (Celery Task)**:
```python
from celery import shared_task
from celery.exceptions import Retry

@shared_task(bind=True, max_retries=3)
def unreliable_task(self, state_dict):
    try:
        result = external_api_call(state_dict)
        return {"result": result}
    except ExternalAPIError as e:
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=2 ** self.request.retries)
```

**Pattern 2: Circuit Breaker**:
```python
from pybreaker import CircuitBreaker

circuit_breaker = CircuitBreaker(fail_max=5, timeout_duration=60)

@circuit_breaker
def call_external_service(data):
    return requests.post('https://external.api/endpoint', json=data)
```

---

## Scalability Considerations

### Horizontal Scaling

**Celery Workers**:
```bash
# Run multiple workers
celery -A src.confucius.celery_app worker -n worker1@%h -Q default,high_priority
celery -A src.confucius.celery_app worker -n worker2@%h -Q default
celery -A src.confucius.celery_app worker -n worker3@%h -Q low_priority
```

**PostgreSQL Connection Pooling**:
```python
# Configured in persistence_postgres.py
self.pool = await asyncpg.create_pool(
    self.db_url,
    min_size=5,   # Minimum connections
    max_size=20,  # Maximum connections per instance
    command_timeout=60
)
```

### Load Balancing

**FastAPI Instances**:
```bash
# Use gunicorn with multiple workers
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

**NGINX Configuration**:
```nginx
upstream confucius_backend {
    least_conn;
    server api1:8000;
    server api2:8000;
    server api3:8000;
}

server {
    listen 80;

    location /api/ {
        proxy_pass http://confucius_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /api/v1/workflow/ {
        proxy_pass http://confucius_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";  # WebSocket support
    }
}
```

### Database Optimization

**Indexes**:
```sql
CREATE INDEX CONCURRENTLY idx_workflow_status ON workflow_executions(status);
CREATE INDEX CONCURRENTLY idx_workflow_type_created ON workflow_executions(workflow_type, created_at);
CREATE INDEX CONCURRENTLY idx_parent_child ON workflow_executions(parent_execution_id) WHERE parent_execution_id IS NOT NULL;
```

**Partitioning** (for high volume):
```sql
CREATE TABLE workflow_executions (
    id UUID NOT NULL,
    created_at TIMESTAMP NOT NULL,
    ...
) PARTITION BY RANGE (created_at);

CREATE TABLE workflow_executions_2025_01 PARTITION OF workflow_executions
    FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');

CREATE TABLE workflow_executions_2025_02 PARTITION OF workflow_executions
    FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');
```

---

## Worker Registry

To support auditable, hybrid-cloud deployments and provide enhanced operational visibility, Confucius implements a passive Worker Registry. This system tracks all active Celery worker nodes, their locations, and their capabilities.

### Architecture

The registry consists of three main components:
1.  **`worker_nodes` Table**: A table in PostgreSQL that serves as the central directory of all known workers.
2.  **Worker-Side Registration**: Logic within the Celery worker process to register itself on startup and send periodic heartbeats.
3.  **API Endpoint**: An endpoint to expose the current list of active workers for administrative or monitoring purposes.

### Database Schema (`worker_nodes`)
The `worker_nodes` table stores vital information about each worker instance.

```sql
CREATE TABLE IF NOT EXISTS worker_nodes (
    worker_id VARCHAR(255) PRIMARY KEY,
    hostname VARCHAR(255),
    region VARCHAR(50) NOT NULL,
    zone VARCHAR(50),
    capabilities JSONB DEFAULT '{}',
    status VARCHAR(50) DEFAULT 'online', -- 'online', 'offline', 'draining'
    last_heartbeat TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```
- **`worker_id`**: A unique, static ID for the worker container, provided via the `WORKER_ID` environment variable. This ensures a stable identity across restarts.
- **`hostname`**: The network hostname of the worker instance.
- **`region` / `zone`**: Geographic or logical location of the worker (e.g., `eu-west-1`, `on-premise-datacenter`). Provided by `WORKER_REGION` and `WORKER_ZONE` environment variables.
- **`capabilities`**: A JSONB field for storing arbitrary metadata, such as `{ "gpu": true, "pii_access": true }`. Provided by the `WORKER_CAPABILITIES` environment variable.
- **`status`**: The worker's current state. `online` on registration, `offline` on graceful shutdown.
- **`last_heartbeat`**: Timestamp that is periodically updated by the worker to show it is still alive.

### Registration and Heartbeat Process

The registration logic is handled by the `WorkerRegistry` class (`src/confucius/worker_registry.py`) and is hooked into the Celery worker's lifecycle.

1.  **Startup (`worker_ready` signal)**: When a Celery worker is ready, the `on_worker_ready` signal handler is invoked.
    - It instantiates a `WorkerRegistry` object.
    - The `register()` method is called, which performs an `INSERT ... ON CONFLICT DO UPDATE` into the `worker_nodes` table, setting the worker's status to `online`.
    - A new background thread is started to handle heartbeats.

2.  **Heartbeat (Background Thread)**:
    - The thread runs a loop that wakes up every 30 seconds.
    - It executes a simple `UPDATE` statement on the `worker_nodes` table, setting `last_heartbeat = NOW()` for its `worker_id`.
    - This is a lightweight way to signal liveness without high overhead.

3.  **Shutdown (`worker_shutdown` signal)**:
    - On graceful shutdown, the `on_worker_shutdown` handler is invoked.
    - It calls the `deregister()` method, which sets the worker's `status` to `offline` in the database.
    - The heartbeat thread is cleanly stopped.

This passive registration model is robust and provides a near real-time view of the worker pool's health and capacity. It is a critical feature for regulated industries where proving data remained within a specific boundary (e.g., on an on-premise worker) is a compliance requirement.

---

## Security Considerations

### Secrets Management

Confucius provides a centralized secrets management system via the `SecretsProvider` protocol. This allows workflows to reference sensitive data (like API keys) using `{{secrets.KEY}}` syntax in YAML files.

*   **Runtime Resolution:** Secrets are resolved at the last possible moment (just before task execution or HTTP call).
*   **Security:** Secrets are never persisted in the workflow state or audit logs in plaintext.
*   **Providers:**
    *   `EnvSecretsProvider`: Fetches secrets from environment variables (Default).
    *   Future support for HashiCorp Vault and AWS Secrets Manager.

### Role-Based Access Control (RBAC)

Multi-tenant support is enforced at the API level.

*   **Ownership:** Every workflow can have an `owner_id` and `org_id`.
*   **Identification:** The API identifies users via `X-User-ID` and `X-Org-ID` headers.
*   **Enforcement:** Users can only access workflows they own or that belong to their organization. Workflows without an owner are considered public/legacy and are accessible to all.

### Regional Data Sovereignty

To comply with data residency laws (e.g., GDPR), Confucius supports regional task routing.

*   **Configuration:** Set `data_region: "region-name"` when starting a workflow or in a step directive.
*   **Routing:** The engine automatically routes all Celery tasks for that workflow to a queue named after the region.
*   **Enforcement:** By starting workers that only listen to specific regional queues, you can guarantee that data never leaves a specific geographical boundary.

### Semantic Firewall (Input Sanitization)

Confucius implements a "Semantic Firewall" at the application edge to prevent injection attacks and enforce data sovereignty. This is enforced via the `WorkflowInput` base class (`src/confucius/semantic_firewall.py`).

**Core Protection:**
All Pydantic input models inherit from `WorkflowInput`, which automatically applies strict validators:

1.  **Anti-Injection:** Scans string inputs for patterns matching XSS (Cross-Site Scripting), SQL Injection, and Python Code Injection (e.g., `eval()`, `__import__`).
2.  **Context Bounds:** Enforces a maximum character limit (default 50KB) on string fields to prevent Denial of Service (DoS) via memory exhaustion.
3.  **Data Sovereignty:** `SovereignWorkerInput` subclass validates `data_region` against an allowlist, ensuring sensitive payloads are processed only in authorized geographic regions.

**Implementation:**
```python
# src/confucius/semantic_firewall.py
class WorkflowInput(BaseModel):
    @validator('*', pre=True)
    def sanitize_strings(cls, v):
        dangerous_patterns = [
            r'<script.*?>.*?</script>',
            r'javascript:',
            r'eval\(',
            r';\s*DROP\s+TABLE'
        ]
        # ... validation logic ...
        return v

# Usage in State Models
class LoanInput(WorkflowInput):
    applicant_name: str  # Automatically sanitized
    amount: float
```

### Encryption at Rest

Sensitive workflow state can be encrypted in the database using the `Fernet` symmetric encryption scheme (AES-128).

*   **Implementation:** `src/confucius/crypto_utils.py` handles the encryption logic.
*   **Storage:** When `ENABLE_ENCRYPTION_AT_REST=true`, the engine serializes the state to JSON, encrypts it, and stores the resulting bytes in the `encrypted_state` column. The standard `state` JSONB column is cleared.
*   **Transparency:** Decryption happens automatically in the persistence layer during `load_workflow`.

### API Rate Limiting

To protect the platform from abuse and ensure stability, rate limiting is enforced on critical endpoints.

*   **Integration:** Uses the `slowapi` library.
*   **Default Limit:** `POST /api/v1/workflow/start` is limited to **10 requests per minute per IP**.
*   **Error Response:** Returns `429 Too Many Requests` with a JSON body detailing the limit.

### SQL Injection Prevention

Use parameterized queries:
```python
# Safe
await conn.execute(
    "SELECT * FROM workflows WHERE id = $1",
    workflow_id
)

# NEVER do this
await conn.execute(
    f"SELECT * FROM workflows WHERE id = '{workflow_id}'"  # Vulnerable!
)
```

### Idempotency

Prevent duplicate operations:
```python
workflow.idempotency_key = f"order-{order_id}"

# In PostgreSQL
CREATE UNIQUE INDEX idx_idempotency ON workflow_executions(idempotency_key);
```

### Access Control

Implement middleware for authentication:
```python
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer

security = HTTPBearer()

async def verify_token(credentials = Depends(security)):
    token = credentials.credentials
    # Verify JWT token
    if not is_valid_token(token):
        raise HTTPException(401, "Invalid token")
    return get_user_from_token(token)

@router.post("/workflow/start")
async def start_workflow(request, user = Depends(verify_token)):
    # Only authenticated users can start workflows
    workflow = workflow_builder.create_workflow(...)
    workflow.metadata['created_by'] = user.id
    ...
```

### Data Encryption

Encrypt sensitive state data:
```python
from cryptography.fernet import Fernet

def encrypt_sensitive_data(data: str, key: bytes) -> str:
    f = Fernet(key)
    return f.encrypt(data.encode()).decode()

def decrypt_sensitive_data(encrypted: str, key: bytes) -> str:
    f = Fernet(key)
    return f.decrypt(encrypted.encode()).decode()

# In state model
class SecureState(BaseModel):
    user_id: str
    encrypted_ssn: str  # Store encrypted

    def set_ssn(self, ssn: str):
        key = os.getenv('ENCRYPTION_KEY').encode()
        self.encrypted_ssn = encrypt_sensitive_data(ssn, key)

    def get_ssn(self) -> str:
        key = os.getenv('ENCRYPTION_KEY').encode()
        return decrypt_sensitive_data(self.encrypted_ssn, key)
```

---

## Performance Optimization

### Caching

**Workflow Configuration Caching**:
```python
class WorkflowBuilder:
    def __init__(self, registry_path):
        self._registry = None  # Cached
        self._workflow_configs = {}  # Cached

    def get_workflow_config(self, workflow_type):
        """Load and cache workflow YAML"""
        if workflow_type not in self._workflow_configs:
            # Load from file
            self._workflow_configs[workflow_type] = yaml.safe_load(...)
        return self._workflow_configs[workflow_type]
```

**Redis Caching for Frequently Accessed Data**:
```python
def get_user_profile(user_id):
    # Try cache first
    cached = redis_client.get(f"user_profile:{user_id}")
    if cached:
        return json.loads(cached)

    # Fetch from database
    profile = database.get_user(user_id)

    # Cache for 5 minutes
    redis_client.setex(
        f"user_profile:{user_id}",
        300,
        json.dumps(profile)
    )

    return profile
```

### Async I/O

Use async operations throughout:
```python
# Good: Concurrent database operations
results = await asyncio.gather(
    load_workflow_state(workflow_id_1),
    load_workflow_state(workflow_id_2),
    load_workflow_state(workflow_id_3)
)

# Bad: Sequential operations
result1 = await load_workflow_state(workflow_id_1)
result2 = await load_workflow_state(workflow_id_2)
result3 = await load_workflow_state(workflow_id_3)
```

### Database Query Optimization

**EXPLAIN ANALYZE** queries:
```sql
EXPLAIN ANALYZE
SELECT * FROM workflow_executions
WHERE status = 'ACTIVE' AND workflow_type = 'LoanApplication'
ORDER BY created_at DESC
LIMIT 100;
```

**Use covering indexes**:
```sql
-- Query needs: status, workflow_type, created_at, id
CREATE INDEX idx_workflow_covering ON workflow_executions(status, workflow_type, created_at)
INCLUDE (id);
```

---

## Monitoring and Observability

### Logging

**Structured Logging**:
```python
import logging
import json

logger = logging.getLogger(__name__)

def log_workflow_event(workflow_id, event, **kwargs):
    logger.info(json.dumps({
        'workflow_id': workflow_id,
        'event': event,
        'timestamp': datetime.now().isoformat(),
        **kwargs
    }))

# Usage
log_workflow_event(
    workflow.id,
    'step_completed',
    step_name='Credit_Check',
    duration_ms=1234,
    status='success'
)
```

### Metrics

**Prometheus Integration**:
```python
from prometheus_client import Counter, Histogram, Gauge

workflow_started = Counter('workflow_started_total', 'Workflows started', ['workflow_type'])
workflow_completed = Counter('workflow_completed_total', 'Workflows completed', ['workflow_type', 'status'])
step_duration = Histogram('workflow_step_duration_seconds', 'Step execution time', ['workflow_type', 'step_name'])
active_workflows = Gauge('workflow_active_count', 'Active workflows', ['workflow_type'])

# Usage
workflow_started.labels(workflow_type='LoanApplication').inc()

with step_duration.labels(workflow_type='LoanApplication', step_name='Credit_Check').time():
    result = execute_step(...)

active_workflows.labels(workflow_type='LoanApplication').set(count_active())
```

### Health Checks

```python
@router.get("/health")
async def health_check():
    checks = {
        "postgres": await check_postgres(),
        "redis": check_redis(),
        "celery": check_celery_workers()
    }

    if all(checks.values()):
        return {"status": "healthy", "checks": checks}
    else:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "checks": checks}
        )

async def check_postgres():
    try:
        store = await get_postgres_store()
        await store.pool.fetchval("SELECT 1")
        return True
    except:
        return False

def check_redis():
    try:
        redis_client.ping()
        return True
    except:
        return False
```

### Distributed Tracing

**OpenTelemetry Integration**:
```python
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.celery import CeleryInstrumentor

# Instrument FastAPI
FastAPIInstrumentor.instrument_app(app)

# Instrument Celery
CeleryInstrumentor().instrument()

# Manual tracing
tracer = trace.get_tracer(__name__)

def execute_step(step, state):
    with tracer.start_as_current_span("execute_step") as span:
        span.set_attribute("step.name", step.name)
        span.set_attribute("step.type", type(step).__name__)

        result = step.func(state=state)

        span.set_attribute("step.status", "success")
        return result
```

---

For usage examples and API details, see:
- [Usage Guide](USAGE_GUIDE.md)
- [YAML Configuration Reference](YAML_GUIDE.md)
- [API Reference](API_REFERENCE.md)
