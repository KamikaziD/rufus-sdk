# YAML Schema Reference

## Overview

Complete specification for workflow definition YAML files.

## Workflow Registry Schema

**File:** `workflow_registry.yaml`

### Top-Level Structure

```yaml
workflows:
  - type: string              # Required
    description: string       # Optional
    config_file: string       # Required
    initial_state_model: string  # Required
    requires: list[string]    # Optional

requires: list[string]        # Optional
```

### Fields

#### `workflows`

**Type:** `list[dict]`

**Required:** Yes

List of workflow definitions.

#### `workflows[].type`

**Type:** `string`

**Required:** Yes

Unique workflow type identifier (e.g., "OrderProcessing").

#### `workflows[].description`

**Type:** `string`

**Required:** No

Human-readable workflow description.

#### `workflows[].config_file`

**Type:** `string`

**Required:** Yes

Path to workflow YAML file (relative to registry file).

#### `workflows[].initial_state_model`

**Type:** `string`

**Required:** Yes

Python import path to Pydantic state model (e.g., "my_app.models.OrderState").

#### `workflows[].requires`

**Type:** `list[string]`

**Required:** No

List of required Python packages for this workflow.

#### `requires`

**Type:** `list[string]`

**Required:** No

Global list of required packages for all workflows.

### Example

```yaml
workflows:
  - type: "OrderProcessing"
    description: "E-commerce order processing workflow"
    config_file: "order_processing.yaml"
    initial_state_model_path: "my_app.models.OrderState"
    requires:
      - ruvon-payment-gateway
      - ruvon-inventory

  - type: "UserOnboarding"
    description: "New user onboarding workflow"
    config_file: "user_onboarding.yaml"
    initial_state_model: "my_app.models.UserState"

requires:
  - ruvon-notifications
```

---

## Workflow Definition Schema

**File:** `<workflow_name>.yaml`

### Top-Level Structure

```yaml
workflow_type: string              # Required
workflow_version: string           # Optional
initial_state_model_path: string   # Required
description: string                # Optional
saga_enabled: bool                 # Optional (default: false)
steps: list[dict]                  # Required
```

### Fields

#### `workflow_type`

**Type:** `string`

**Required:** Yes

Must match registry entry.

#### `workflow_version`

**Type:** `string`

**Required:** No

Semantic version (e.g., "1.0.0").

#### `saga_enabled`

**Type:** `bool`

**Required:** No

**Default:** `false`

When `true`, enables Saga compensation mode. On step failure, compensation functions
(`compensate_function` in each step) are executed in reverse order and the workflow
status becomes `FAILED_ROLLED_BACK`. Requires `CompensatableStep` entries.

```yaml
saga_enabled: true
```

#### `initial_state_model_path`

**Type:** `string`

**Required:** Yes

Python import path to Pydantic state model.

#### `description`

**Type:** `string`

**Required:** No

Human-readable description.

#### `steps`

**Type:** `list[dict]`

**Required:** Yes

List of workflow steps.

### Example

```yaml
workflow_type: "OrderProcessing"
workflow_version: "1.5.0"
initial_state_model_path: "my_app.models.OrderState"
description: "Process customer orders with payment and fulfillment"

steps:
  - name: "Validate_Order"
    type: "STANDARD"
    function: "my_app.steps.validate_order"
    automate_next: true
```

---

## Step Schema

### Common Step Fields

All step types support these fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | Yes | Unique step identifier |
| `type` | `string` | Yes | Step type (see [Step Types](step-types.md)) |
| `description` | `string` | No | Human-readable step description (informational only) |
| `function` | `string` | Conditional | Python import path to step function |
| `compensate_function` | `string` | No | Python import path to compensation function |
| `input_model` | `string` | No | Python import path to input Pydantic model. **Note:** In YAML this key is `input_model`; at runtime the builder resolves the class and stores it on the step as `step.input_schema`. |
| `required_input` | `list[string]` | No | List of required input keys (legacy) |
| `automate_next` | `boolean` | No | Auto-execute next step (default: false) |
| `dependencies` | `list[string]` | No | List of prerequisite step names |
| `dynamic_injection` | `dict` | No | Dynamic step injection rules |
| `routes` | `list[dict]` | No | Declarative routing (DECISION steps) |

### Step Type-Specific Fields

Different step types require additional fields. See [Step Types Reference](step-types.md) for details.

---

## Dynamic Injection Schema

### Structure

```yaml
dynamic_injection:
  rules:
    - condition_key: string         # Required
      value_match: any              # Conditional
      value_is_not: list[any]       # Conditional
      action: string                # Required
      steps_to_insert: list[dict]   # Required
```

### Fields

#### `rules`

**Type:** `list[dict]`

**Required:** Yes

List of injection rules.

#### `rules[].condition_key`

**Type:** `string`

**Required:** Yes

Dot-notation path in workflow state (e.g., "user.profile.age").

#### `rules[].value_match`

**Type:** `any`

**Required:** Conditional (one of value_match or value_is_not)

Inject if condition_key equals this value.

#### `rules[].value_is_not`

**Type:** `list[any]`

**Required:** Conditional (one of value_match or value_is_not)

Inject if condition_key NOT in this list.

#### `rules[].action`

**Type:** `string`

**Required:** Yes

**Allowed values:** `"INSERT_AFTER_CURRENT"`

#### `rules[].steps_to_insert`

**Type:** `list[dict]`

**Required:** Yes

List of step configurations to inject (same schema as regular steps).

### Example

```yaml
steps:
  - name: "Evaluate_Risk"
    type: "STANDARD"
    function: "my_app.risk.evaluate"
    dynamic_injection:
      rules:
        - condition_key: "risk_level"
          value_match: "high"
          action: "INSERT_AFTER_CURRENT"
          steps_to_insert:
            - name: "Manual_Review"
              type: "HUMAN_IN_LOOP"
              function: "my_app.approvals.request_review"
```

---

## Routes Schema (DECISION Steps)

### Structure

```yaml
routes:
  - condition: string       # Required
    target: string          # Required
  - default: string         # Optional (fallback route)
```

### Fields

#### `routes[].condition`

**Type:** `string`

**Required:** Yes (except for default route)

Python expression evaluated against workflow state.

#### `routes[].target`

**Type:** `string`

**Required:** Yes

Target step name to jump to.

#### `routes[].default`

**Type:** `string`

**Required:** No

Fallback target if no conditions match.

### Example

```yaml
steps:
  - name: "Check_Order_Value"
    type: "DECISION"
    function: "my_app.steps.check_order_value"
    routes:
      - condition: "state.amount > 10000"
        target: "High_Value_Review"
      - condition: "state.amount > 1000"
        target: "Standard_Processing"
      - default: "Auto_Approve"
```

---

## HTTP Step Schema

### Structure

```yaml
type: "HTTP"
http_config:
  method: string              # Required
  url: string                 # Required
  headers: dict[string, string]  # Optional
  query_params: dict[string, string]  # Optional
  body: dict                  # Optional
  timeout: int                # Optional
  retry_policy: dict          # Optional
output_key: string            # Required
includes: list[string]        # Optional
```

### Fields

#### `http_config.method`

**Type:** `string`

**Required:** Yes

**Allowed values:** `GET`, `POST`, `PUT`, `DELETE`, `PATCH`

#### `http_config.url`

**Type:** `string`

**Required:** Yes

URL template (supports Jinja2 syntax: `{{state.field}}`).

#### `http_config.headers`

**Type:** `dict[string, string]`

**Required:** No

HTTP headers (supports templating).

#### `http_config.query_params`

**Type:** `dict[string, string]`

**Required:** No

Query parameters (supports templating).

#### `http_config.body`

**Type:** `dict`

**Required:** No

Request body (JSON, supports templating).

#### `http_config.timeout`

**Type:** `int`

**Required:** No

Request timeout in seconds (default: 30).

#### `http_config.retry_policy`

**Type:** `dict`

**Required:** No

Retry configuration (max_attempts, delay_seconds).

#### `output_key`

**Type:** `string`

**Required:** Yes

Key to store response in workflow state.

#### `includes`

**Type:** `list[string]`

**Required:** No

Response fields to include (default: all).

**Allowed values:** `body`, `status_code`, `headers`

### Example

```yaml
steps:
  - name: "Fetch_Product"
    type: "HTTP"
    http_config:
      method: "GET"
      url: "https://api.example.com/products/{{state.product_id}}"
      headers:
        Authorization: "Bearer {{secrets.API_TOKEN}}"
      timeout: 10
      retry_policy:
        max_attempts: 3
        delay_seconds: 5
    output_key: "product_data"
    includes: ["body", "status_code"]
```

---

## PARALLEL Step Schema

### Structure

Two modes are supported: **static task list** (tasks enumerated in YAML) and **dynamic fan-out** (one function called once per item in a state list at runtime).

```yaml
type: "PARALLEL"

# ── Static task list ──────────────────────────────────────────────────────────
tasks:
  - name: string              # Required (static mode)
    function_path: string     # Required (static mode)

# ── Dynamic fan-out (alternative to tasks list) ───────────────────────────────
iterate_over: string          # Optional: dot-notation path to a state list
task_function: string         # Optional: function called once per item
item_var_name: string         # Optional: kwarg name for each item (default: "item")
batch_size: int               # Optional: chunk size for iterate_over lists (0 = all at once)

# ── Shared options ────────────────────────────────────────────────────────────
merge_strategy: string        # Optional
merge_conflict_behavior: string  # Optional
allow_partial_success: boolean   # Optional
timeout_seconds: int          # Optional
```

When both `iterate_over` and `task_function` are set, the static `tasks` list is ignored and tasks are generated at runtime — one per item in the resolved list.

### Fields

#### `tasks`

**Type:** `list[dict]`

**Required:** Yes (static mode) / ignored (dynamic fan-out mode)

List of parallel tasks. Used when the task set is fixed at workflow design time.

#### `tasks[].name`

**Type:** `string`

**Required:** Yes

Unique task name.

#### `tasks[].function_path`

**Type:** `string`

**Required:** Yes

Python import path to task function.

#### `iterate_over`

**Type:** `string`

**Required:** No

Dot-notation path into workflow state pointing to a list (e.g. `"device_ids"` or `"order.line_items"`). When set alongside `task_function`, enables dynamic fan-out: one task per item in the list.

#### `task_function`

**Type:** `string`

**Required:** No (required when `iterate_over` is set)

Python import path to the function called for each item. The function receives the item as a kwarg named by `item_var_name`.

#### `item_var_name`

**Type:** `string`

**Required:** No

**Default:** `"item"`

Name of the kwarg passed to `task_function` for each item. For example, `item_var_name: "device_id"` means the function is called as `task_function(state, context, device_id=item)`.

#### `batch_size`

**Type:** `int`

**Required:** No

**Default:** `0` (all at once)

When set to a positive integer, the `iterate_over` list is split into chunks of this size and each chunk is dispatched sequentially. Useful when dispatching hundreds or thousands of items would overwhelm the target system.

```yaml
- name: "Push_To_Fleet"
  type: "PARALLEL"
  iterate_over: "device_ids"       # list of 1000 items in state
  task_function: "steps.push_to_device"
  item_var_name: "device_id"
  batch_size: 50                   # 20 sequential batches of 50
  merge_strategy: "SHALLOW"
  allow_partial_success: true
```

> **Executor compatibility:** `batch_size` is only supported with `SyncExecutor` and `ThreadPoolExecutor`. When using `CeleryExecutionProvider`, `batch_size` is ignored with a warning logged — Celery's async dispatch model cannot iterate batches synchronously. For Celery-based batching, pre-chunk the list in a STANDARD step and use a sub-workflow per chunk.

#### `merge_strategy`

**Type:** `string`

**Required:** No

**Allowed values:** `SHALLOW`, `DEEP`

**Default:** `SHALLOW`

#### `merge_conflict_behavior`

**Type:** `string`

**Required:** No

**Allowed values:** `PREFER_NEW`, `PREFER_OLD`, `RAISE_ERROR`

**Default:** `PREFER_NEW`

#### `allow_partial_success`

**Type:** `boolean`

**Required:** No

**Default:** `false`

If true, workflow continues even if some tasks fail.

#### `timeout_seconds`

**Type:** `int`

**Required:** No

Maximum time for all tasks to complete.

### Examples

**Static task list:**

```yaml
steps:
  - name: "Parallel_Services"
    type: "PARALLEL"
    tasks:
      - name: "check_inventory"
        function_path: "my_app.services.check_inventory"
      - name: "validate_address"
        function_path: "my_app.services.validate_address"
    merge_strategy: "DEEP"
    allow_partial_success: false
    timeout_seconds: 60
```

**Dynamic fan-out** — push config to every device in `state.device_ids`:

```yaml
steps:
  - name: "Push_To_Fleet"
    type: "PARALLEL"
    iterate_over: "device_ids"      # list of device IDs in workflow state
    task_function: "steps.push_to_device"
    item_var_name: "device_id"
    batch_size: 50                  # optional: process 50 at a time
    merge_strategy: "SHALLOW"
    allow_partial_success: true
```

```python
def push_to_device(state: dict, context: StepContext, device_id: str = "", **_) -> dict:
    """Called once per item — device_id is the current list element."""
    push_config_update(device_id, state["config_data"])
    return {"pushed": device_id}
```

---

## LOOP Step Schema

### Structure

```yaml
type: "LOOP"
mode: string                  # Required
iterate_over: string          # Conditional (ITERATE mode)
item_var_name: string         # Conditional (ITERATE mode)
while_condition: string       # Conditional (WHILE mode)
max_iterations: int           # Required
loop_body: list[dict]         # Required
```

### Fields

#### `mode`

**Type:** `string`

**Required:** Yes

**Allowed values:** `ITERATE`, `WHILE`

#### `iterate_over`

**Type:** `string`

**Required:** Yes (ITERATE mode)

Dot-notation path to list in workflow state.

#### `item_var_name`

**Type:** `string`

**Required:** Yes (ITERATE mode)

Variable name for current item.

#### `while_condition`

**Type:** `string`

**Required:** Yes (WHILE mode)

Python expression for loop continuation.

#### `max_iterations`

**Type:** `int`

**Required:** Yes

Safety limit for maximum iterations.

#### `loop_body`

**Type:** `list[dict]`

**Required:** Yes

Steps to execute in each iteration.

### Example (ITERATE)

```yaml
steps:
  - name: "Process_Items"
    type: "LOOP"
    mode: "ITERATE"
    iterate_over: "state.order_items"
    item_var_name: "current_item"
    max_iterations: 100
    loop_body:
      - name: "Update_Inventory"
        type: "STANDARD"
        function: "my_app.inventory.update_stock"
```

### Example (WHILE)

```yaml
steps:
  - name: "Poll_Status"
    type: "LOOP"
    mode: "WHILE"
    while_condition: "state.status != 'READY'"
    max_iterations: 10
    loop_body:
      - name: "Check_API"
        type: "HTTP"
        http_config:
          method: "GET"
          url: "https://api.example.com/status"
        output_key: "api_status"
```

---

## WASM Step Schema

### Structure

```yaml
type: "WASM"
wasm_config:
  wasm_hash: string         # Required — SHA-256 hex digest
  entrypoint: string        # Optional — default "execute"
  state_mapping: dict       # Optional — workflow key → WASM input key
  timeout_ms: int           # Optional — default 5000 (range 100–60000)
  fallback_on_error: string # Optional — "fail" | "skip" | "default"
  default_result: dict      # Optional — used when fallback_on_error: "default"
merge_strategy: string      # Optional — default "SHALLOW"
merge_conflict_behavior: string  # Optional — default "PREFER_NEW"
automate_next: bool         # Optional
```

### Fields

#### `wasm_config.wasm_hash`

**Type:** `string`

**Required:** Yes

SHA-256 hex digest (64 lowercase hex chars) of the `.wasm` binary. Used for both binary resolution and integrity verification at execution time.

#### `wasm_config.entrypoint`

**Type:** `string`

**Default:** `"execute"`

The name of the exported function in the WASM module to call. The function receives no arguments; it reads state from stdin and writes results to stdout.

#### `wasm_config.state_mapping`

**Type:** `dict[string, string]`

**Default:** `{}` (full state passed)

Maps workflow state keys to WASM input keys. If provided, only the specified keys are sent to the module. If omitted, the entire workflow state dict is passed as-is.

```yaml
state_mapping:
  transaction_amount: "amount"   # state.transaction_amount → input["amount"]
  card_country: "country"        # state.card_country → input["country"]
```

#### `wasm_config.timeout_ms`

**Type:** `int`

**Default:** `5000` | **Range:** `100` – `60000`

Maximum execution time. If the module does not complete within this duration, an `asyncio.TimeoutError` is raised and `fallback_on_error` is applied.

#### `wasm_config.fallback_on_error`

**Type:** `string` — `"fail"` | `"skip"` | `"default"`

**Default:** `"fail"`

| Value | Behavior |
|-------|----------|
| `"fail"` | Raises `RuntimeError`, workflow transitions to `FAILED` |
| `"skip"` | Returns `{}`, workflow continues unchanged |
| `"default"` | Returns `default_result`, workflow continues |

#### `wasm_config.default_result`

**Type:** `dict`

Returned when `fallback_on_error: "default"`. Must be a valid dict that can merge into workflow state.

### Example

```yaml
- name: "Validate_Card_BIN"
  type: "WASM"
  wasm_config:
    wasm_hash: "c9a1b2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1"
    entrypoint: "execute"
    state_mapping:
      card_bin: "bin"
    timeout_ms: 500
    fallback_on_error: "default"
    default_result:
      bin_valid: false
      bin_country: "UNKNOWN"
  automate_next: true
```

---

## See Also

- [Step Types Reference](step-types.md)
- [CLI Commands](cli-commands.md)
- [Database Schema](database-schema.md)
