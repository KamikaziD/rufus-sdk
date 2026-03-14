# WorkflowBuilder API Reference

## Overview

`WorkflowBuilder` loads workflow definitions from YAML files and creates workflow instances with proper dependency injection.

**Module:** `rufus.builder`

## Constructor

### `WorkflowBuilder.__init__`

```python
def __init__(
    self,
    workflow_registry: Dict[str, Any],
    expression_evaluator_cls: Type[ExpressionEvaluator],
    template_engine_cls: Type[TemplateEngine],
    config_dir: Optional[str] = None,
)
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workflow_registry` | `Dict[str, Any]` | Yes | Registry mapping workflow types to config. See format below. |
| `expression_evaluator_cls` | `Type[ExpressionEvaluator]` | Yes | Expression evaluator class (e.g. `SimpleExpressionEvaluator`) |
| `template_engine_cls` | `Type[TemplateEngine]` | Yes | Template engine class (e.g. `Jinja2TemplateEngine`) |
| `config_dir` | `str` | No | Directory containing workflow YAML files (defaults to `os.getcwd()`) |

**`workflow_registry` format:**

```python
{
    "WorkflowType": {
        "config_file": "my_workflow.yaml",           # YAML filename relative to config_dir
        "initial_state_model_path": "my_app.state.MyState",  # Python import path to Pydantic model
    },
    ...
}
```

**Note:** Providers (`persistence_provider`, `execution_provider`, `workflow_observer`) are **not** constructor parameters — they are passed per-workflow to `create_workflow()`. This allows a single builder to create workflows with different providers.

**Example:**

```python
from rufus.builder import WorkflowBuilder
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

workflow_registry = {
    "OrderProcessing": {
        "config_file": "order_processing.yaml",
        "initial_state_model_path": "my_app.state_models.OrderState",
    }
}

builder = WorkflowBuilder(
    workflow_registry=workflow_registry,
    expression_evaluator_cls=SimpleExpressionEvaluator,
    template_engine_cls=Jinja2TemplateEngine,
    config_dir="config/",
)
```

## Methods

### `create_workflow`

Create and initialize a new workflow instance.

```python
async def create_workflow(
    self,
    workflow_type: str,
    persistence_provider: PersistenceProvider,
    execution_provider: ExecutionProvider,
    workflow_builder: WorkflowBuilder,
    expression_evaluator_cls: Type[ExpressionEvaluator],
    template_engine_cls: Type[TemplateEngine],
    workflow_observer: WorkflowObserver,
    initial_data: Optional[dict] = None,
    owner_id: Optional[str] = None,
    org_id: Optional[str] = None,
    data_region: Optional[str] = None,
    priority: Optional[int] = None,
    idempotency_key: Optional[str] = None,
    metadata: Optional[dict] = None,
    wasm_binary_resolver: Optional[Callable] = None,
) -> Workflow
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workflow_type` | `str` | Yes | Workflow type from registry |
| `persistence_provider` | `PersistenceProvider` | Yes | Persistence implementation for this workflow |
| `execution_provider` | `ExecutionProvider` | Yes | Execution implementation for this workflow |
| `workflow_builder` | `WorkflowBuilder` | Yes | Pass `builder` itself — stored for sub-workflow spawning |
| `expression_evaluator_cls` | `Type[ExpressionEvaluator]` | Yes | Expression evaluator class |
| `template_engine_cls` | `Type[TemplateEngine]` | Yes | Template engine class |
| `workflow_observer` | `WorkflowObserver` | Yes | Observer for lifecycle events |
| `initial_data` | `dict` | No | Initial state data (defaults to `None`) |
| `owner_id` | `str` | No | Owner identifier for multi-tenancy |
| `org_id` | `str` | No | Organisation identifier |
| `data_region` | `str` | No | Data region for compliance/routing |
| `priority` | `int` | No | Workflow priority |
| `idempotency_key` | `str` | No | Idempotency key to prevent duplicate creation |
| `metadata` | `dict` | No | Arbitrary metadata attached to this workflow |
| `wasm_binary_resolver` | `Callable` | No | Resolver for WASM binaries (Component Model steps) |

**Returns:** `Workflow` instance

**Raises:**
- `ValueError` - If workflow_type not found in registry
- `ValidationError` - If initial_data fails state model validation

**Example:**

```python
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver

persistence = SQLitePersistenceProvider(db_path=":memory:")
await persistence.initialize()
execution = SyncExecutor()
observer = LoggingObserver()

workflow = await builder.create_workflow(
    workflow_type="OrderProcessing",
    persistence_provider=persistence,
    execution_provider=execution,
    workflow_builder=builder,
    expression_evaluator_cls=SimpleExpressionEvaluator,
    template_engine_cls=Jinja2TemplateEngine,
    workflow_observer=observer,
    initial_data={"customer_id": "123", "amount": 99.99},
    owner_id="tenant-abc",
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
