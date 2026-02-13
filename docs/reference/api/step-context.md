# StepContext Reference

## Overview

`StepContext` provides contextual information to step functions during execution.

**Module:** `rufus.models`

## Class Definition

```python
@dataclass
class StepContext:
    workflow_id: UUID
    step_name: str
    previous_step_result: Optional[dict] = None
    loop_state: Optional[LoopState] = None
    parent_workflow_id: Optional[UUID] = None
    metadata: dict = field(default_factory=dict)
```

## Fields

### `workflow_id`

**Type:** `UUID`

Unique identifier of the workflow instance.

**Example:**

```python
def my_step(state: MyState, context: StepContext):
    print(f"Workflow ID: {context.workflow_id}")
```

### `step_name`

**Type:** `str`

Name of the current step being executed.

**Example:**

```python
def my_step(state: MyState, context: StepContext):
    print(f"Current step: {context.step_name}")
```

### `previous_step_result`

**Type:** `Optional[dict]`

Result dictionary from the previous step execution.

**Default:** `None`

**Example:**

```python
def process_order(state: OrderState, context: StepContext):
    # Access previous step's result
    if context.previous_step_result:
        validation_status = context.previous_step_result.get("validated")
        if not validation_status:
            raise ValueError("Order not validated")

    return {"processed": True}
```

### `loop_state`

**Type:** `Optional[LoopState]`

Loop iteration state for LOOP step types.

**Default:** `None`

**Fields:**
- `current_iteration` (int) - Current iteration number (0-indexed)
- `current_item` (Any) - Current item in ITERATE mode
- `total_iterations` (int) - Total iterations

**Example:**

```python
def process_item(state: MyState, context: StepContext):
    if context.loop_state:
        item = context.loop_state.current_item
        iteration = context.loop_state.current_iteration
        total = context.loop_state.total_iterations

        print(f"Processing item {iteration + 1}/{total}: {item}")

        return {"item_id": item["id"], "processed": True}
```

### `parent_workflow_id`

**Type:** `Optional[UUID]`

Identifier of parent workflow (if this is a sub-workflow).

**Default:** `None`

**Example:**

```python
def child_step(state: ChildState, context: StepContext):
    if context.parent_workflow_id:
        print(f"Running as child of {context.parent_workflow_id}")

    return {"child_result": "completed"}
```

### `metadata`

**Type:** `dict`

Additional metadata dictionary for custom extensions.

**Default:** `{}`

**Example:**

```python
def custom_step(state: MyState, context: StepContext):
    # Store custom metadata
    context.metadata["custom_flag"] = True
    context.metadata["tenant_id"] = state.tenant_id

    return {"status": "processed"}
```

## Usage in Step Functions

### Function Signature

All step functions receive `state` and `context`:

```python
def step_function(
    state: BaseModel,
    context: StepContext,
    **user_input
) -> dict:
    """
    Args:
        state: Workflow state (Pydantic model)
        context: Step execution context
        **user_input: Additional validated inputs

    Returns:
        dict: Result data merged into workflow state
    """
    pass
```

### Common Patterns

#### Accessing Previous Results

```python
def sequential_step(state: MyState, context: StepContext):
    # Chain step results
    previous_output = context.previous_step_result.get("output_key")

    new_result = process(previous_output)

    return {"next_output": new_result}
```

#### Loop Processing

```python
def loop_body_step(state: MyState, context: StepContext):
    # Process current loop item
    item = context.loop_state.current_item

    # Track progress
    progress = (context.loop_state.current_iteration + 1) / context.loop_state.total_iterations
    print(f"Progress: {progress:.1%}")

    return {"item_result": process_item(item)}
```

#### Sub-Workflow Context

```python
def parent_aware_step(state: ChildState, context: StepContext):
    # Different behavior for top-level vs child workflows
    if context.parent_workflow_id:
        # Running as child
        return {"mode": "child", "parent": str(context.parent_workflow_id)}
    else:
        # Running as top-level workflow
        return {"mode": "standalone"}
```

#### Logging with Context

```python
def logged_step(state: MyState, context: StepContext):
    logger.info(
        f"Executing {context.step_name} in workflow {context.workflow_id}"
    )

    result = perform_operation(state)

    logger.info(f"Completed {context.step_name}")

    return result
```

## LoopState Details

### Class Definition

```python
@dataclass
class LoopState:
    current_iteration: int
    current_item: Any
    total_iterations: int
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `current_iteration` | `int` | Current iteration number (0-indexed) |
| `current_item` | `Any` | Current item being processed (ITERATE mode) |
| `total_iterations` | `int` | Total number of iterations |

### Example

```python
def process_batch(state: BatchState, context: StepContext):
    if not context.loop_state:
        raise ValueError("Expected loop_state but none provided")

    item = context.loop_state.current_item
    iteration = context.loop_state.current_iteration

    # First iteration setup
    if iteration == 0:
        state.batch_results = []

    # Process item
    result = process_single_item(item)
    state.batch_results.append(result)

    # Last iteration cleanup
    if iteration == context.loop_state.total_iterations - 1:
        return {"batch_complete": True, "total_processed": len(state.batch_results)}

    return {"item_processed": True}
```

## Related Types

- [Workflow](workflow.md)
- [Step Types](../configuration/step-types.md)
- [Directives](directives.md)

## See Also

- [Writing Step Functions](../../how-to-guides/write-step-functions.md)
- [Loop Steps](../configuration/step-types.md#loop)
