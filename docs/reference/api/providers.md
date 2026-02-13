# Provider Interfaces Reference

## Overview

Provider interfaces abstract external dependencies for persistence, execution, and observability. All providers use Python Protocol for duck typing.

**Module:** `rufus.providers`

## PersistenceProvider

Persistence abstraction for workflow state, audit logs, and task records.

**Module:** `rufus.providers.persistence`

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

### Implementations

| Provider | Module | Description |
|----------|--------|-------------|
| `PostgresPersistenceProvider` | `rufus.implementations.persistence.postgres` | PostgreSQL with JSONB |
| `SQLitePersistenceProvider` | `rufus.implementations.persistence.sqlite` | SQLite with WAL mode |
| `MemoryPersistenceProvider` | `rufus.implementations.persistence.memory` | In-memory (testing) |
| `RedisPersistenceProvider` | `rufus.implementations.persistence.redis` | Redis-based |

---

## ExecutionProvider

Execution abstraction for sync, async, and parallel step execution.

**Module:** `rufus.providers.execution`

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

### Implementations

| Provider | Module | Description |
|----------|--------|-------------|
| `SyncExecutionProvider` | `rufus.implementations.execution.sync` | Synchronous execution |
| `ThreadPoolExecutionProvider` | `rufus.implementations.execution.thread_pool` | Thread-based parallel |
| `CeleryExecutor` | `rufus.implementations.execution.celery` | Distributed Celery |
| `PostgresExecutor` | `rufus.implementations.execution.postgres_executor` | PostgreSQL task queue |

---

## WorkflowObserver

Observability hooks for workflow lifecycle events.

**Module:** `rufus.providers.observer`

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
    result: dict
) -> None
```

Called after step execution.

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

### Implementations

| Provider | Module | Description |
|----------|--------|-------------|
| `LoggingObserver` | `rufus.implementations.observability.logging` | Console logging |
| `NoopObserver` | `rufus.providers.observer` | No-op (default) |

---

## ExpressionEvaluator

Expression evaluation for DECISION steps and dynamic injection.

**Module:** `rufus.providers.expression_evaluator`

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
| `SimpleExpressionEvaluator` | `rufus.implementations.expression.simple` | Basic Python eval |

---

## TemplateEngine

Template rendering for HTTP steps and dynamic content.

**Module:** `rufus.providers.template_engine`

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
| `Jinja2TemplateEngine` | `rufus.implementations.templating.jinja2` | Jinja2 renderer |

---

## See Also

- [Workflow](workflow.md)
- [WorkflowBuilder](workflow-builder.md)
- [Database Schema](../configuration/database-schema.md)
