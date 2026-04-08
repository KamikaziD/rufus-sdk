# Workflow API Reference

## Overview

`Workflow` manages workflow lifecycle, state, and execution. Main class for orchestrating step execution and control flow.

**Module:** `ruvon.workflow`

## Constructor

### `Workflow.__init__`

```python
def __init__(
    self,
    id: UUID,
    workflow_type: str,
    state: BaseModel,
    steps: list[WorkflowStep],
    persistence: PersistenceProvider,
    execution: ExecutionProvider,
    observer: Optional[WorkflowObserver] = None,
    current_step_index: int = 0,
    status: str = "ACTIVE",
    workflow_version: Optional[str] = None,
    definition_snapshot: Optional[dict] = None,
    owner_id: Optional[str] = None,
    data_region: Optional[str] = None
)
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | `UUID` | Yes | Unique workflow identifier |
| `workflow_type` | `str` | Yes | Workflow type from registry |
| `state` | `BaseModel` | Yes | Pydantic state model instance |
| `steps` | `list[WorkflowStep]` | Yes | List of workflow steps |
| `persistence` | `PersistenceProvider` | Yes | Persistence implementation |
| `execution` | `ExecutionProvider` | Yes | Execution implementation |
| `observer` | `WorkflowObserver` | No | Observability hook |
| `current_step_index` | `int` | No | Current step index (default: 0) |
| `status` | `str` | No | Workflow status (default: "ACTIVE") |
| `workflow_version` | `str` | No | Workflow definition version |
| `definition_snapshot` | `dict` | No | Snapshot of workflow YAML |
| `owner_id` | `str` | No | Owner identifier |
| `data_region` | `str` | No | Data region |

**Note:** Direct instantiation requires all 6 providers injected (`persistence_provider`, `execution_provider`, `workflow_observer`, `workflow_builder`, `expression_evaluator_cls`, `template_engine_cls`) — all raise `ValueError` if `None`. Use `WorkflowBuilder.create_workflow()` for normal usage; pass `MagicMock()` for providers you don't need in tests.

## Properties

### `id`

**Type:** `UUID`

Unique workflow identifier.

### `workflow_type`

**Type:** `str`

Workflow type identifier from registry.

### `state`

**Type:** `BaseModel`

Current workflow state (Pydantic model).

### `status`

**Type:** `str`

Current workflow status.

**Possible Values:**
- `ACTIVE` - Currently running
- `PENDING_ASYNC` - Waiting for async task
- `PENDING_SUB_WORKFLOW` - Waiting for sub-workflow
- `PAUSED` - Paused for input
- `WAITING_HUMAN` - Waiting for human input
- `WAITING_HUMAN_INPUT` - Waiting for user input
- `WAITING_CHILD_HUMAN_INPUT` - Child workflow waiting
- `COMPLETED` - Successfully finished
- `FAILED` - Failed with error
- `FAILED_ROLLED_BACK` - Failed and rolled back (Saga)
- `FAILED_CHILD_WORKFLOW` - Child workflow failed
- `FAILED_WORKER_CRASH` - Worker crashed (zombie)
- `CANCELLED` - Manually cancelled

### `current_step`

**Type:** `Optional[WorkflowStep]`

Currently executing step.

**Returns:** `None` if workflow completed.

### `current_step_index`

**Type:** `int`

Index of current step in steps list.

### `workflow_version`

**Type:** `Optional[str]`

Workflow definition version (from YAML `workflow_version`).

### `definition_snapshot`

**Type:** `Optional[dict]`

Complete workflow YAML configuration snapshot.

## Methods

### `next_step`

Execute the next workflow step.

```python
async def next_step(
    self,
    user_input: dict = {}
) -> Tuple[Dict[str, Any], Optional[str]]
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_input` | `dict` | Yes | Input data for step execution (pass `{}` when no input needed) |

**Returns:** `Tuple[Dict[str, Any], Optional[str]]`
- First element: step result dict (merged into workflow state)
- Second element: jump directive string (target step name) or `None` for normal sequential flow

**Step timing:** For `STANDARD` steps, execution duration is measured and passed as `duration_ms` to `WorkflowObserver.on_step_executed()`. `duration_ms` is `None` for async/parallel dispatch steps (timing measured by the worker).

**Raises:**
- `ValueError` - If workflow already completed/failed

**Example:**

```python
result, directive = await workflow.next_step(user_input={"approved": True})

# Check if we jumped to a different step
if directive:
    print(f"Jumped to: {directive}")
```

### `enable_saga_mode`

Enable Saga pattern for automatic compensation.

```python
async def enable_saga_mode(self) -> None
```

**Example:**

```python
await workflow.enable_saga_mode()
```

**Effects:**
- Sets `saga_mode_enabled` flag
- On failure, compensation functions execute in reverse order
- Status becomes `FAILED_ROLLED_BACK` after rollback

### `cancel`

Cancel workflow execution.

```python
async def cancel(
    self,
    reason: Optional[str] = None
) -> None
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `reason` | `str` | No | Cancellation reason for audit log |

**Example:**

```python
await workflow.cancel(reason="Duplicate order detected")
```

**Effects:**
- Sets status to `CANCELLED`
- Logs cancellation to audit log
- Does not trigger compensation (use Saga mode for rollback)

### `save`

Persist workflow state to database.

```python
async def save(self) -> None
```

**Example:**

```python
await workflow.save()
```

**Note:** Automatically called by `next_step()`. Manual saves rarely needed.

### `jump_to_step`

Jump to specific step by name.

```python
async def jump_to_step(
    self,
    target_step_name: str
) -> None
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `target_step_name` | `str` | Yes | Name of target step |

**Raises:**
- `ValueError` - If step name not found

**Example:**

```python
await workflow.jump_to_step("High_Value_Review")
```

**Note:** Typically invoked via `WorkflowJumpDirective`, not directly.

## Saga Mode

### Compensation Flow

When Saga mode enabled and workflow fails:

1. Compensation functions execute in reverse step order
2. Each compensation receives original step's state
3. Compensation failures logged but don't halt rollback
4. Workflow status becomes `FAILED_ROLLED_BACK`

**Example:**

```python
# Enable Saga mode
await workflow.enable_saga_mode()

# Execute steps
result, _ = await workflow.next_step(user_input={})  # Reserve_Inventory
result, _ = await workflow.next_step(user_input={})  # Charge_Payment (fails)

# Automatic compensation:
# 1. refund_payment() called
# 2. release_inventory() called
# 3. Status: FAILED_ROLLED_BACK
```

## Sub-Workflow Integration

### Parent Status Updates

When sub-workflow launched:

1. Parent status → `PENDING_SUB_WORKFLOW`
2. Child paused → Parent status → `WAITING_CHILD_HUMAN_INPUT`
3. Child failed → Parent status → `FAILED_CHILD_WORKFLOW`
4. Child completed → Parent resumes execution

### Accessing Sub-Workflow Results

```python
# In parent workflow step function
def process_results(state: MyState, context: StepContext):
    child_id = state.sub_workflow_results.keys()[0]
    child_data = state.sub_workflow_results[child_id]

    # Access child's final state
    kyc_status = child_data['state']['kyc_status']

    return {"kyc_approved": kyc_status == "APPROVED"}
```

## Workflow Versioning

### Definition Snapshots

Workflows snapshot their YAML configuration at creation:

```python
workflow = await builder.create_workflow("OrderProcessing", initial_data)

# Snapshot stored automatically
snapshot = workflow.definition_snapshot
print(snapshot['workflow_version'])  # "1.0.0"
print(snapshot['steps'][0]['name'])  # "Validate_Order"
```

**Benefits:**
- Running workflows immune to YAML changes
- Deploy new workflow versions without breaking existing instances
- Full audit trail of workflow definition used

## Related Types

- [WorkflowBuilder](workflow-builder.md)
- [StepContext](step-context.md)
- [Directives](directives.md)
- [Providers](providers.md)

## See Also

- [Step Types](../configuration/step-types.md)
- [Control Flow](../../how-to-guides/control-flow.md)
