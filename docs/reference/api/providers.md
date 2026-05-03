# Provider Interfaces Reference

## Overview

Provider interfaces abstract external dependencies for persistence, execution, and observability. `WorkflowObserver` uses ABC (abstract base class, v1.0+). All other providers use Python ABC with `@abstractmethod` declarations.

**Module:** `ruvon.providers`

## PersistenceProvider

Persistence abstraction for workflow state, audit logs, and task records.

**Module:** `ruvon.providers.persistence`

### Methods

#### `initialize`

```python
async def initialize(self) -> None
```

Initialize persistence backend (create connections, apply migrations).

**Example:**

```python
await persistence.initialize()
```

#### `save_workflow`

```python
async def save_workflow(
    self,
    workflow_id: UUID,
    workflow_data: dict
) -> None
```

Persist workflow state.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `workflow_id` | `UUID` | Workflow identifier |
| `workflow_data` | `dict` | Complete workflow state dictionary |

#### `load_workflow`

```python
async def load_workflow(
    self,
    workflow_id: UUID
) -> dict
```

Load workflow state from persistence.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `workflow_id` | `UUID` | Workflow identifier |

**Returns:** `dict` - Workflow state dictionary

**Raises:**
- `ValueError` - If workflow not found

#### `list_workflows`

```python
async def list_workflows(
    self,
    status: Optional[str] = None,
    workflow_type: Optional[str] = None,
    limit: int = 20,
    offset: int = 0
) -> list[dict]
```

List workflows with optional filtering.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | `str` | `None` | Filter by workflow status |
| `workflow_type` | `str` | `None` | Filter by workflow type |
| `limit` | `int` | `20` | Maximum results |
| `offset` | `int` | `0` | Pagination offset |

**Returns:** `list[dict]` - List of workflow summaries

#### `log_execution`

```python
async def log_execution(
    self,
    workflow_id: UUID,
    step_name: str,
    level: str,
    message: str,
    metadata: Optional[dict] = None
) -> None
```

Log workflow execution event.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `workflow_id` | `UUID` | Workflow identifier |
| `step_name` | `str` | Step name |
| `level` | `str` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `message` | `str` | Log message |
| `metadata` | `dict` | Additional metadata |

#### `record_metric`

```python
async def record_metric(
    self,
    workflow_id: UUID,
    step_name: str,
    metric_name: str,
    metric_value: float,
    metadata: Optional[dict] = None
) -> None
```

Record workflow performance metric.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `workflow_id` | `UUID` | Workflow identifier |
| `step_name` | `str` | Step name |
| `metric_name` | `str` | Metric name (e.g., "duration_ms") |
| `metric_value` | `float` | Metric value |
| `metadata` | `dict` | Additional metadata |

#### `claim_next_task`

```python
async def claim_next_task(
    self,
    worker_id: str
) -> Optional[dict]
```

Claim next task from distributed queue (for async execution).

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `worker_id` | `str` | Worker identifier |

**Returns:** `Optional[dict]` - Task data or None if queue empty

#### `heartbeat_update`

```python
async def heartbeat_update(
    self,
    workflow_id: UUID,
    worker_id: str,
    current_step: str,
    metadata: Optional[dict] = None
) -> None
```

Update heartbeat for zombie detection.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `workflow_id` | `UUID` | Workflow identifier |
| `worker_id` | `str` | Worker identifier |
| `current_step` | `str` | Current step name |
| `metadata` | `dict` | Additional metadata |

#### `scan_stale_heartbeats`

```python
async def scan_stale_heartbeats(
    self,
    stale_threshold_seconds: int
) -> list[dict]
```

Scan for stale heartbeats (zombie workflows).

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `stale_threshold_seconds` | `int` | Heartbeat age threshold |

**Returns:** `list[dict]` - List of zombie workflow records

#### `close`

```python
async def close(self) -> None
```

Close persistence connections.

### Edge-only methods

The following methods are declared in the base class but raise `NotImplementedError` unless the implementation supports them (currently: `SQLitePersistenceProvider` only).

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_pending_sync_workflows` | `(limit: int) -> List[WorkflowRecord]` | Workflows not yet synced to cloud |
| `get_audit_logs_for_workflows` | `(ids: List[str], limit_per_workflow: int = 50) -> List[AuditLogRecord]` | Audit logs for given workflow IDs |
| `delete_synced_workflows` | `(ids: List[str]) -> int` | Delete workflows after successful sync |
| `get_edge_sync_state` | `(key: str) -> Optional[str]` | Read a plain string sync state value |
| `set_edge_sync_state` | `(key: str, value: str) -> None` | Write a plain string sync state value |

### Typed exceptions

```python
class PersistenceError(RuntimeError): ...
class WorkflowNotFoundError(PersistenceError): ...
class DuplicateIdempotencyKeyError(PersistenceError): ...
class TaskNotFoundError(PersistenceError): ...
```

### Implementations

| Provider | Module | Description |
|----------|--------|-------------|
| `PostgresPersistenceProvider` | `ruvon.implementations.persistence.postgres` | PostgreSQL with JSONB |
| `SQLitePersistenceProvider` | `ruvon.implementations.persistence.sqlite` | SQLite with WAL mode; includes all edge-only methods |
| `MemoryPersistenceProvider` | `ruvon.implementations.persistence.memory` | In-memory (testing) |
| `RedisPersistenceProvider` | `ruvon.implementations.persistence.redis` | Redis-based |

---

## ExecutionProvider

Execution abstraction for sync, async, and parallel step execution.

**Module:** `ruvon.providers.execution`

### `ExecutionContext` dataclass *(v1.0)*

Carries cross-cutting context through task dispatch calls.

```python
@dataclass
class ExecutionContext:
    trace_id: Optional[str]
    actor_id: Optional[str]
    workflow_id: str
    step_name: str
    attempt: int = 1
```

Pass via `execution_context=` parameter on `dispatch_async_task()` and `dispatch_parallel_tasks()`.

### Methods

#### `dispatch_async_task`

```python
async def dispatch_async_task(
    self,
    workflow_id: UUID,
    step_name: str,
    function_path: str,
    state: BaseModel,
    context: StepContext
) -> str
```

Dispatch async task for background execution.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `workflow_id` | `UUID` | Workflow identifier |
| `step_name` | `str` | Step name |
| `function_path` | `str` | Python import path to task function |
| `state` | `BaseModel` | Workflow state |
| `context` | `StepContext` | Step context |

**Returns:** `str` - Task identifier

#### `dispatch_parallel_tasks`

```python
async def dispatch_parallel_tasks(
    self,
    workflow_id: UUID,
    tasks: list[dict],
    state: BaseModel
) -> list[dict]
```

Execute multiple tasks in parallel.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `workflow_id` | `UUID` | Workflow identifier |
| `tasks` | `list[dict]` | List of task configurations |
| `state` | `BaseModel` | Workflow state |

**Returns:** `list[dict]` - List of task results

#### `dispatch_sub_workflow`

```python
async def dispatch_sub_workflow(
    self,
    parent_workflow_id: UUID,
    workflow_type: str,
    initial_data: dict,
    owner_id: Optional[str] = None,
    data_region: Optional[str] = None
) -> UUID
```

Launch sub-workflow.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `parent_workflow_id` | `UUID` | Parent workflow identifier |
| `workflow_type` | `str` | Sub-workflow type |
| `initial_data` | `dict` | Initial state data |
| `owner_id` | `str` | Owner identifier |
| `data_region` | `str` | Data region |

**Returns:** `UUID` - Sub-workflow identifier

#### `report_child_status_to_parent`

```python
async def report_child_status_to_parent(
    self,
    child_workflow_id: UUID,
    parent_workflow_id: UUID,
    child_status: str
) -> None
```

Report child workflow status to parent.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `child_workflow_id` | `UUID` | Child workflow identifier |
| `parent_workflow_id` | `UUID` | Parent workflow identifier |
| `child_status` | `str` | Child workflow status |

#### `execute_sync_step_function`

```python
async def execute_sync_step_function(
    self,
    function: Callable,
    state: BaseModel,
    context: StepContext,
    **user_input
) -> dict
```

Execute step function synchronously.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `function` | `Callable` | Step function to execute |
| `state` | `BaseModel` | Workflow state |
| `context` | `StepContext` | Step context |
| `**user_input` | `dict` | Additional user inputs |

**Returns:** `dict` - Step execution result

#### `get_task_status` *(v1.0)*

```python
async def get_task_status(self, task_id: str) -> str
```

Returns the current status string of a dispatched task.

#### `cancel_task` *(v1.0)*

```python
async def cancel_task(self, task_id: str) -> bool
```

Request cancellation of a dispatched task. Returns `True` if cancellation was accepted.

### Implementations

| Provider | Module | Description |
|----------|--------|-------------|
| `SyncExecutionProvider` | `ruvon.implementations.execution.sync` | Synchronous execution |
| `ThreadPoolExecutionProvider` | `ruvon.implementations.execution.thread_pool` | Thread-based parallel |
| `CeleryExecutor` | `ruvon.implementations.execution.celery` | Distributed Celery |
| `PostgresExecutor` | `ruvon.implementations.execution.postgres_executor` | PostgreSQL task queue |

---

## WorkflowObserver

Observability hooks for workflow lifecycle events.

**Module:** `ruvon.providers.observer`

**Type:** ABC (abstract base class, v1.0+). All methods have default async no-op implementations — subclasses only need to override the methods they care about. Existing subclasses continue to work without modification.

**Migration note:** If you previously subclassed `WorkflowObserver` as a Protocol, change to `class MyObserver(WorkflowObserver):` — existing method implementations require no changes.

### Methods

#### `on_workflow_started`

```python
async def on_workflow_started(
    self,
    workflow_id: UUID,
    workflow_type: str
) -> None
```

Called when workflow starts.

#### `on_step_executed`

```python
async def on_step_executed(
    self,
    workflow_id: UUID,
    step_name: str,
    result: dict,
    duration_ms: Optional[float] = None,
) -> None
```

Called after step execution. `duration_ms` is the wall-clock time for `STANDARD` steps; `None` for async/parallel dispatch (timing measured by the worker).

#### `on_workflow_completed`

```python
async def on_workflow_completed(
    self,
    workflow_id: UUID
) -> None
```

Called when workflow completes successfully.

#### `on_workflow_failed`

```python
async def on_workflow_failed(
    self,
    workflow_id: UUID,
    error: Exception
) -> None
```

Called when workflow fails.

#### `on_workflow_status_changed`

```python
async def on_workflow_status_changed(
    self,
    workflow_id: UUID,
    old_status: str,
    new_status: str
) -> None
```

Called when workflow status changes.

#### `on_workflow_paused` *(v1.0)*

```python
async def on_workflow_paused(
    self,
    workflow_id: UUID,
    step_name: str,
    reason: str
) -> None
```

Called when workflow is paused (e.g. `HUMAN_IN_LOOP` step raises `WorkflowPauseDirective`).

#### `on_workflow_resumed` *(v1.0)*

```python
async def on_workflow_resumed(
    self,
    workflow_id: UUID,
    step_name: str,
    resume_data: dict
) -> None
```

Called when a paused workflow is resumed with user input.

#### `on_compensation_started` *(v1.0)*

```python
async def on_compensation_started(
    self,
    workflow_id: UUID,
    step_name: str,
    step_index: int
) -> None
```

Called when Saga compensation begins for a step (triggered on workflow failure).

#### `on_compensation_completed` *(v1.0)*

```python
async def on_compensation_completed(
    self,
    workflow_id: UUID,
    step_name: str,
    success: bool,
    error: Optional[Exception] = None
) -> None
```

Called after each Saga compensation function completes (success or failure).

#### `on_child_workflow_started` *(v1.0)*

```python
async def on_child_workflow_started(
    self,
    parent_id: UUID,
    child_id: UUID,
    child_type: str
) -> None
```

Called when a sub-workflow is launched from a parent workflow.

### OtelObserver *(v1.0)*

OpenTelemetry observer that creates parent spans per workflow and child spans per step.

**Installation:**

```bash
pip install 'ruvon-sdk[otel]'
```

**Usage:**

```python
from ruvon.implementations.observability.otel import OtelObserver

observer = OtelObserver(
    tracer_provider=None,   # Optional: pass your TracerProvider; uses global if None
    service_name="ruvon",   # Span service.name attribute
)
```

Auto no-ops when `opentelemetry-sdk` is not installed (safe to instantiate unconditionally).

### Implementations

| Provider | Module | Description |
|----------|--------|-------------|
| `LoggingObserver` | `ruvon.implementations.observability.logging` | Structured console logging |
| `OtelObserver` | `ruvon.implementations.observability.otel` | OpenTelemetry spans (requires `[otel]` extra) |
| `EventPublisherObserver` | `ruvon.implementations.observability.events` | Redis Streams event publishing |
| `NoopObserver` | `ruvon.providers.observer` | No-op (default) |

---

## ExpressionEvaluator

Expression evaluation for DECISION steps and dynamic injection.

**Module:** `ruvon.providers.expression_evaluator`

### Methods

#### `evaluate`

```python
def evaluate(
    self,
    expression: str,
    context: dict
) -> bool
```

Evaluate boolean expression.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `expression` | `str` | Python expression string |
| `context` | `dict` | Variable context for evaluation |

**Returns:** `bool` - Evaluation result

**Example:**

```python
result = evaluator.evaluate(
    "state.amount > 10000",
    {"state": workflow.state}
)
```

### Implementations

| Provider | Module | Description |
|----------|--------|-------------|
| `SimpleExpressionEvaluator` | `ruvon.implementations.expression_evaluator.simple` | Basic Python eval |

---

## TemplateEngine

Template rendering for HTTP steps and dynamic content.

**Module:** `ruvon.providers.template_engine`

### Methods

#### `render`

```python
def render(
    self,
    template: str,
    context: dict
) -> str
```

Render template string with context.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `template` | `str` | Template string |
| `context` | `dict` | Variable context |

**Returns:** `str` - Rendered output

**Example:**

```python
output = engine.render(
    "Hello {{state.user_name}}!",
    {"state": {"user_name": "Alice"}}
)
# "Hello Alice!"
```

### Implementations

| Provider | Module | Description |
|----------|--------|-------------|
| `Jinja2TemplateEngine` | `ruvon.implementations.templating.jinja2` | Jinja2 renderer |

---

## See Also

- [Workflow](workflow.md)
- [WorkflowBuilder](workflow-builder.md)
- [Database Schema](../configuration/database-schema.md)
