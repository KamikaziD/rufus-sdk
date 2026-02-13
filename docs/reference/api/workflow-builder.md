# WorkflowBuilder API Reference

## Overview

`WorkflowBuilder` loads workflow definitions from YAML files and creates workflow instances with proper dependency injection.

**Module:** `rufus.builder`

## Constructor

### `WorkflowBuilder.__init__`

```python
def __init__(
    self,
    config_dir: str,
    persistence_provider: PersistenceProvider,
    execution_provider: ExecutionProvider,
    observer: Optional[WorkflowObserver] = None,
    expression_evaluator: Optional[ExpressionEvaluator] = None,
    template_engine: Optional[TemplateEngine] = None,
    registry_path: Optional[str] = None
)
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `config_dir` | `str` | Yes | Path to directory containing workflow YAML files |
| `persistence_provider` | `PersistenceProvider` | Yes | Persistence implementation (SQLite, PostgreSQL, etc.) |
| `execution_provider` | `ExecutionProvider` | Yes | Execution implementation (sync, thread_pool, celery) |
| `observer` | `WorkflowObserver` | No | Observability hook implementation |
| `expression_evaluator` | `ExpressionEvaluator` | No | Expression evaluation implementation (default: simple) |
| `template_engine` | `TemplateEngine` | No | Template rendering implementation (default: Jinja2) |
| `registry_path` | `str` | No | Custom path to workflow_registry.yaml |

**Example:**

```python
from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.execution.sync import SyncExecutionProvider

persistence = SQLitePersistenceProvider(db_path="workflows.db")
execution = SyncExecutionProvider()

builder = WorkflowBuilder(
    config_dir="config/",
    persistence_provider=persistence,
    execution_provider=execution
)
```

## Methods

### `create_workflow`

Create and initialize a new workflow instance.

```python
async def create_workflow(
    self,
    workflow_type: str,
    initial_data: dict,
    owner_id: Optional[str] = None,
    data_region: Optional[str] = None
) -> Workflow
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workflow_type` | `str` | Yes | Workflow type from registry |
| `initial_data` | `dict` | Yes | Initial state data |
| `owner_id` | `str` | No | Owner identifier for multi-tenancy |
| `data_region` | `str` | No | Data region for compliance/routing |

**Returns:** `Workflow` instance

**Raises:**
- `ValueError` - If workflow_type not found in registry
- `ValidationError` - If initial_data fails state model validation

**Example:**

```python
workflow = await builder.create_workflow(
    workflow_type="OrderProcessing",
    initial_data={"customer_id": "123", "amount": 99.99},
    owner_id="tenant-abc"
)
```

### `load_workflow`

Load existing workflow from persistence.

```python
async def load_workflow(
    self,
    workflow_id: UUID
) -> Workflow
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workflow_id` | `UUID` | Yes | Workflow identifier |

**Returns:** `Workflow` instance

**Raises:**
- `ValueError` - If workflow not found

**Example:**

```python
from uuid import UUID

workflow = await builder.load_workflow(
    workflow_id=UUID("550e8400-e29b-41d4-a716-446655440000")
)
```

### `get_workflow_config`

Get workflow configuration from registry.

```python
def get_workflow_config(
    self,
    workflow_type: str
) -> dict
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workflow_type` | `str` | Yes | Workflow type identifier |

**Returns:** `dict` - Workflow configuration dictionary

**Raises:**
- `ValueError` - If workflow_type not in registry

**Example:**

```python
config = builder.get_workflow_config("OrderProcessing")
print(config['workflow_version'])  # "1.0.0"
```

### `list_available_workflows`

List all registered workflow types.

```python
def list_available_workflows(self) -> list[str]
```

**Returns:** `list[str]` - List of workflow type names

**Example:**

```python
workflows = builder.list_available_workflows()
# ["OrderProcessing", "UserOnboarding", "DataPipeline"]
```

## Class Attributes

### `_import_cache`

Class-level cache for imported functions and models.

**Type:** `dict[str, Any]`

**Description:** Caches imported Python objects to avoid repeated `importlib` calls. Provides 162x speedup for repeated step function imports.

**Note:** Cache is shared across all `WorkflowBuilder` instances for performance.

## Import Resolution

### `_import_from_string`

Import Python object from string path (class method).

```python
@classmethod
def _import_from_string(cls, import_path: str) -> Any
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `import_path` | `str` | Yes | Python import path (e.g., "my_app.steps.process") |

**Returns:** `Any` - Imported Python object

**Raises:**
- `ImportError` - If module or attribute not found

**Example:**

```python
func = WorkflowBuilder._import_from_string("my_app.steps.process_order")
result = func(state, context)
```

## Related Types

- [Workflow](workflow.md)
- [PersistenceProvider](providers.md#persistenceprovider)
- [ExecutionProvider](providers.md#executionprovider)
- [WorkflowObserver](providers.md#workflowobserver)

## See Also

- [Workflow Configuration](../configuration/yaml-schema.md)
- [Step Types](../configuration/step-types.md)
