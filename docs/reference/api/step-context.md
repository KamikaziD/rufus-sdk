# StepContext Reference

## Overview

`StepContext` provides contextual information to step functions during execution.

**Module:** `ruvon.models`

## Class Definition

```python
class StepContext(BaseModel):
    workflow_id: str
    step_name: str
    validated_input: Optional[Any] = None
    previous_step_result: Optional[Dict[str, Any]] = None
    loop_item: Optional[Any] = None    # Current item in a LOOP ITERATE step
    loop_index: Optional[int] = None   # Current index in a LOOP ITERATE step
```

`StepContext` is a **Pydantic `BaseModel`** (not a dataclass). All fields are read-only from
within step functions; do not mutate the context.

## Fields

### `workflow_id`

**Type:** `str`

Unique identifier (UUID as string) of the workflow instance.

**Example:**

```python
def my_step(state: MyState, context: StepContext, **_):
    print(f"Workflow ID: {context.workflow_id}")
    return {}
```

---

### `step_name`

**Type:** `str`

Name of the current step being executed (matches the `name:` field in YAML).

**Example:**

```python
def my_step(state: MyState, context: StepContext, **_):
    print(f"Current step: {context.step_name}")
    return {}
```

---

### `validated_input`

**Type:** `Optional[Any]`
**Default:** `None`

The validated user input for this step (resolved from the step's `input_schema`). Present
only when the step defines `input_model:` in YAML and the caller provides matching data.

**Example:**

```python
class ApprovalInput(BaseModel):
    approved: bool
    reason: str

def approval_step(state: OrderState, context: StepContext, **user_input):
    # context.validated_input is an ApprovalInput instance when input_model is set
    if context.validated_input:
        print(f"Approved: {context.validated_input.approved}")
    return {"approved": context.validated_input.approved}
```

---

### `previous_step_result`

**Type:** `Optional[Dict[str, Any]]`
**Default:** `None`

Result dictionary returned by the immediately preceding step. `None` for the first step.

**Example:**

```python
def process_order(state: OrderState, context: StepContext, **_):
    if context.previous_step_result:
        validated = context.previous_step_result.get("validated")
        if not validated:
            raise ValueError("Order not validated")
    return {"processed": True}
```

---

### `loop_item`

**Type:** `Optional[Any]`
**Default:** `None`

The current item from the list being iterated in a `LOOP` step with `mode: ITERATE`.
`None` outside of LOOP steps or in `mode: WHILE` loops.

**Example:**

```python
def process_device(state: RolloutState, context: StepContext, **_):
    device_id = context.loop_item        # e.g. "device-001"
    index = context.loop_index           # e.g. 0, 1, 2, ...
    print(f"Processing device {index}: {device_id}")
    return {"last_processed": device_id}
```

---

### `loop_index`

**Type:** `Optional[int]`
**Default:** `None`

Zero-based index of the current iteration in a `LOOP ITERATE` step.
`None` outside of LOOP steps.

**Example:**

```python
def summarise_item(state: BatchState, context: StepContext, **_):
    # context.loop_index == 0 → first item
    if context.loop_index == 0:
        state.results = []          # Reset accumulator on first pass
    return {"current_index": context.loop_index}
```

---

## Usage in Step Functions

### Function Signature

All step functions must accept `state`, `context`, and `**user_input`:

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
        **user_input: Additional validated inputs from the caller

    Returns:
        dict: Keys merged into workflow state
    """
    ...
```

### Common Patterns

#### Using Previous Step Results

```python
def enrich_order(state: OrderState, context: StepContext, **_):
    prev = context.previous_step_result or {}
    score = prev.get("fraud_score", 0)
    return {"enriched": True, "risk_level": "high" if score > 0.8 else "low"}
```

#### Processing LOOP Items

```python
def send_config(state: RolloutState, context: StepContext, **_):
    device_id = context.loop_item
    idx = context.loop_index
    total = len(state.devices)
    print(f"[{idx + 1}/{total}] Sending config to {device_id}")
    # ... push config ...
    return {"configured": device_id}
```

#### Logging with Context

```python
import logging
logger = logging.getLogger(__name__)

def logged_step(state: MyState, context: StepContext, **_):
    logger.info(
        "Executing step=%s workflow=%s", context.step_name, context.workflow_id
    )
    result = perform_operation(state)
    return result
```

## Related Types

- [Workflow](workflow.md)
- [Step Types](../configuration/step-types.md)
- [Directives](directives.md)

## See Also

- [Writing Step Functions](../../how-to-guides/write-step-functions.md)
- [Loop Steps](../configuration/step-types.md#loop)
