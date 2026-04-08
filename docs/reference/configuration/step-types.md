# Step Types Reference

## Overview

Ruvon supports 11 step execution types. Each type controls how the step executes and what configuration options are available.

## STANDARD

Synchronous step execution.

### Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"STANDARD"` | Yes | Step type identifier |
| `function` | `string` | Yes | Python import path to step function |
| `compensate_function` | `string` | No | Compensation function for Saga pattern |
| `automate_next` | `boolean` | No | Auto-execute next step |

### Example

```yaml
- name: "Validate_Order"
  type: "STANDARD"
  function: "my_app.steps.validate_order"
  automate_next: true
```

### Behavior

- Executes synchronously in workflow process
- Blocks until function returns
- Return value merged into workflow state
- Suitable for fast operations (< 1 second)

---

## ASYNC

Asynchronous step execution via task queue.

### Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"ASYNC"` | Yes | Step type identifier |
| `function` | `string` | Yes | Python import path to async task function |
| `compensate_function` | `string` | No | Compensation function |
| `automate_next` | `boolean` | No | Auto-execute next step |

### Example

```yaml
- name: "Process_Payment"
  type: "ASYNC"
  function: "my_app.tasks.process_payment"
  automate_next: true
```

### Behavior

- Dispatched to `ExecutionProvider` (e.g., Celery)
- Workflow status → `PENDING_ASYNC`
- Worker executes task asynchronously
- Workflow resumes when task completes
- Suitable for long-running operations

---

## DECISION

Conditional branching with declarative routes.

### Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"DECISION"` | Yes | Step type identifier |
| `function` | `string` | Yes | Python import path to decision function |
| `routes` | `list[dict]` | No | Declarative routing rules |

### Routes Schema

```yaml
routes:
  - condition: string   # Python expression
    target: string      # Target step name
  - default: string     # Fallback (optional)
```

### Example

```yaml
- name: "Check_Amount"
  type: "DECISION"
  function: "my_app.steps.check_amount"
  routes:
    - condition: "state.amount > 10000"
      target: "High_Value_Review"
    - condition: "state.amount > 1000"
      target: "Standard_Processing"
    - default: "Auto_Approve"
```

### Behavior

- Function executes and returns result
- Routes evaluated in order
- First matching condition wins
- Workflow jumps to target step
- If no routes, function must raise `WorkflowJumpDirective`

---

## PARALLEL

Execute multiple tasks concurrently.

### Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"PARALLEL"` | Yes | Step type identifier |
| `tasks` | `list[dict]` | Yes | List of parallel tasks |
| `merge_strategy` | `"SHALLOW"` or `"DEEP"` | No | Result merge strategy (default: SHALLOW) |
| `merge_conflict_behavior` | `string` | No | Conflict resolution (default: PREFER_NEW) |
| `allow_partial_success` | `boolean` | No | Continue if some tasks fail (default: false) |
| `timeout_seconds` | `int` | No | Maximum execution time |

### Tasks Schema

```yaml
tasks:
  - name: string              # Required
    function_path: string     # Required
```

### Merge Strategies

- `SHALLOW`: Merge top-level keys only
- `DEEP`: Recursively merge nested dictionaries

### Merge Conflict Behaviors

- `PREFER_NEW`: New values overwrite old
- `PREFER_EXISTING`: Keep existing values
- `RAISE_ERROR`: Fail on conflicts

### Example

```yaml
- name: "Check_Services"
  type: "PARALLEL"
  tasks:
    - name: "check_inventory"
      function_path: "my_app.services.check_inventory"
    - name: "validate_address"
      function_path: "my_app.services.validate_address"
    - name: "calculate_shipping"
      function_path: "my_app.services.calculate_shipping"
  merge_strategy: "DEEP"
  allow_partial_success: false
  timeout_seconds: 60
```

### Behavior

- All tasks dispatched simultaneously
- Execution via `ExecutionProvider.dispatch_parallel_tasks()`
- Results merged based on strategy
- Conflicts handled per merge_conflict_behavior
- Workflow continues when all tasks complete (or timeout)

---

## HTTP

Call external HTTP/REST APIs.

### Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"HTTP"` | Yes | Step type identifier |
| `http_config` | `dict` | Yes | HTTP request configuration |
| `output_key` | `string` | Yes | Key to store response in state |
| `includes` | `list[string]` | No | Response fields to include |

### HTTP Config Schema

```yaml
http_config:
  method: string              # Required: GET, POST, PUT, DELETE, PATCH
  url: string                 # Required (supports templates)
  headers: dict               # Optional (supports templates)
  query_params: dict          # Optional (supports templates)
  body: dict                  # Optional (supports templates)
  timeout: int                # Optional (default: 30)
  retry_policy: dict          # Optional
```

### Retry Policy Schema

```yaml
retry_policy:
  max_attempts: int           # Default: 1
  delay_seconds: int          # Default: 5
```

### Example

```yaml
- name: "Call_Payment_Gateway"
  type: "HTTP"
  http_config:
    method: "POST"
    url: "https://api.gateway.com/charge"
    headers:
      Authorization: "Bearer {{secrets.GATEWAY_TOKEN}}"
      Content-Type: "application/json"
    body:
      amount: "{{state.amount}}"
      currency: "USD"
      customer_id: "{{state.customer_id}}"
    timeout: 30
    retry_policy:
      max_attempts: 3
      delay_seconds: 5
  output_key: "payment_response"
  includes: ["body", "status_code"]
```

### Behavior

- Templates rendered with Jinja2 (`{{variable}}`)
- Request executed via HTTP client
- Response stored in `state[output_key]`
- Supports all HTTP methods
- Automatic JSON parsing for JSON responses

---

## LOOP

Iterate over collections or execute until condition.

### Configuration (ITERATE Mode)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"LOOP"` | Yes | Step type identifier |
| `mode` | `"ITERATE"` | Yes | Loop mode |
| `iterate_over` | `string` | Yes | Dot-notation path to list in state |
| `item_var_name` | `string` | Yes | Variable name for current item |
| `max_iterations` | `int` | Yes | Safety limit |
| `loop_body` | `list[dict]` | Yes | Steps to execute per iteration |

### Configuration (WHILE Mode)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"LOOP"` | Yes | Step type identifier |
| `mode` | `"WHILE"` | Yes | Loop mode |
| `while_condition` | `string` | Yes | Python expression for continuation |
| `max_iterations` | `int` | Yes | Safety limit |
| `loop_body` | `list[dict]` | Yes | Steps to execute per iteration |

### Example (ITERATE)

```yaml
- name: "Process_Order_Items"
  type: "LOOP"
  mode: "ITERATE"
  iterate_over: "state.order_items"
  item_var_name: "current_item"
  max_iterations: 100
  loop_body:
    - name: "Update_Inventory"
      type: "STANDARD"
      function: "my_app.inventory.update_stock"
    - name: "Calculate_Tax"
      type: "STANDARD"
      function: "my_app.tax.calculate_item_tax"
```

### Example (WHILE)

```yaml
- name: "Poll_Until_Ready"
  type: "LOOP"
  mode: "WHILE"
  while_condition: "state.api_status != 'READY'"
  max_iterations: 10
  loop_body:
    - name: "Check_Status"
      type: "HTTP"
      http_config:
        method: "GET"
        url: "https://api.example.com/status"
      output_key: "api_status"
```

### Behavior

- **ITERATE**: Execute loop_body for each item in list
- **WHILE**: Execute loop_body while condition is true
- Current item available as `context.loop_item`; index as `context.loop_index`
- Stops at max_iterations (safety limit)
- Loop body steps execute in order per iteration

---

## FIRE_AND_FORGET

Launch independent background workflow.

### Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"FIRE_AND_FORGET"` | Yes | Step type identifier |
| `target_workflow_type` | `string` | Yes | Workflow type to spawn |
| `initial_data_template` | `dict` | Yes | Initial data for spawned workflow |

### Example

```yaml
- name: "Send_Email"
  type: "FIRE_AND_FORGET"
  target_workflow_type: "EmailDelivery"
  initial_data_template:
    recipient: "{{state.customer_email}}"
    subject: "Order Confirmation"
    order_id: "{{state.order_id}}"
```

### Behavior

- Spawns independent workflow (not a sub-workflow)
- Parent does NOT wait for completion
- Parent only stores spawned workflow ID
- No status bubbling to parent
- Use for notifications, logging, background processing

---

## CRON_SCHEDULE

Register recurring workflow schedule.

### Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"CRON_SCHEDULE"` | Yes | Step type identifier |
| `schedule_name` | `string` | Yes | Unique schedule identifier |
| `cron_expression` | `string` | Yes | Standard cron expression |
| `target_workflow_type` | `string` | Yes | Workflow to trigger |
| `initial_data_template` | `dict` | Yes | Initial data for triggered workflow |

### Example

```yaml
- name: "Schedule_Weekly_Report"
  type: "CRON_SCHEDULE"
  schedule_name: "weekly_report_{{state.user_id}}"
  cron_expression: "0 9 * * MON"
  target_workflow_type: "GenerateReport"
  initial_data_template:
    user_id: "{{state.user_id}}"
    report_type: "weekly_summary"
```

### Behavior

- Registers schedule with execution provider (e.g., Celery Beat)
- Workflow triggered at cron intervals
- Schedule persists until explicitly removed
- Requires execution provider with scheduling support

---

## HUMAN_IN_LOOP

Pause for human input or approval.

### Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"HUMAN_IN_LOOP"` | Yes | Step type identifier |
| `function` | `string` | Yes | Python import path to step function |
| `automate_next` | `boolean` | No | Auto-execute next step after resume |

### Example

```yaml
- name: "Manager_Approval"
  type: "HUMAN_IN_LOOP"
  function: "my_app.approvals.request_manager_approval"
  automate_next: true
```

### Behavior

- Function typically raises `WorkflowPauseDirective`
- Workflow status → `WAITING_HUMAN_INPUT`
- Execution pauses until manual resume
- Resume with user input continues to next step

---

## AI_INFERENCE

Run AI/ML model inference as a workflow step. Supports TensorFlow Lite, ONNX Runtime,
and custom inference providers.

### Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"AI_INFERENCE"` | Yes | Step type identifier |
| `ai_config` | `dict` | Yes | Inference configuration (see below) |
| `automate_next` | `boolean` | No | Auto-execute next step |

### `ai_config` Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | `string` | Yes | Unique name matching a loaded model |
| `runtime` | `string` | Yes | `"tflite"`, `"onnx"`, or `"custom"` |
| `input_source` | `string` | Yes | State path to input data (e.g., `"state.sensor_data"`) |
| `output_key` | `string` | No | State key for inference result (default: `"inference_result"`) |
| `preprocessing` | `string` | No | `"normalize"`, `"resize"`, `"none"` |
| `postprocessing` | `string` | No | `"softmax"`, `"threshold"`, `"argmax"`, `"none"` |
| `threshold` | `float` | No | Threshold for binary classification decisions |
| `timeout_ms` | `int` | No | Max inference time in ms (default: 5000) |
| `fallback_on_error` | `string` | No | `"skip"`, `"fail"`, `"default"` |

### Example

```yaml
- name: "Detect_Anomaly"
  type: "AI_INFERENCE"
  ai_config:
    model_name: "anomaly_detector"
    model_path: "models/anomaly_detector.tflite"
    runtime: "tflite"
    input_source: "state.sensor_readings"
    preprocessing: "normalize"
    output_key: "anomaly_result"
    postprocessing: "threshold"
    postprocessing_params:
      threshold: 0.7
    threshold: 0.7
  automate_next: true
```

### Use Cases

- Edge device anomaly detection (TFLite on POS terminals, IoT sensors)
- Fraud scoring inline with payment workflow
- Document classification before routing decisions

---

## Step Type Comparison

| Type | Execution | Pauses Workflow | Supports Compensation | Use Case |
|------|-----------|-----------------|----------------------|----------|
| `STANDARD` | Sync | No | Yes | Fast operations |
| `ASYNC` | Async queue | Yes | Yes | Long-running tasks |
| `DECISION` | Sync | No | No | Conditional branching |
| `PARALLEL` | Concurrent | Yes | No | Scatter-gather |
| `HTTP` | Sync/Async | Optional | No | External API calls |
| `LOOP` | Iterative | No | No | Batch processing |
| `FIRE_AND_FORGET` | Async | No | No | Background jobs |
| `CRON_SCHEDULE` | Scheduled | No | No | Recurring workflows |
| `HUMAN_IN_LOOP` | Manual | Yes | No | Approvals |
| `AI_INFERENCE` | Sync | No | No | On-device ML inference |
| `WASM` | Sync (sandboxed) | No | No | Polyglot edge logic |

---

## WASM

Executes a pre-compiled WebAssembly binary in a WASI sandbox. State is passed as JSON on stdin; the module writes its result as JSON to stdout. Works with any language that compiles to WASM (Rust, C, Go, AssemblyScript, etc.).

Requires the `wasmtime` Python package: `pip install wasmtime`

### Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"WASM"` | Yes | Step type identifier |
| `wasm_config.wasm_hash` | `string` | Yes | SHA-256 hex digest of the `.wasm` binary |
| `wasm_config.entrypoint` | `string` | No | Exported function to call (default: `"execute"`) |
| `wasm_config.state_mapping` | `dict` | No | Workflow state keys → WASM input keys. Omit to pass the full state |
| `wasm_config.timeout_ms` | `int` | No | Max execution time in ms (default: `5000`, range: 100–60000) |
| `wasm_config.fallback_on_error` | `string` | No | `"fail"` (default) / `"skip"` / `"default"` |
| `wasm_config.default_result` | `dict` | No | Returned when `fallback_on_error: "default"` |
| `merge_strategy` | `string` | No | How to merge result into state (default: `"SHALLOW"`) |
| `merge_conflict_behavior` | `string` | No | Conflict resolution (default: `"PREFER_NEW"`) |
| `automate_next` | `boolean` | No | Auto-execute next step |

### Example — Risk Scoring

```yaml
- name: "Score_Transaction_Risk"
  type: "WASM"
  wasm_config:
    wasm_hash: "a3f5c2d1e4b6f8901234567890abcdef1234567890abcdef1234567890abcdef12"
    entrypoint: "execute"
    state_mapping:
      transaction_amount: "amount"
      card_country: "country"
      merchant_category: "mcc"
    timeout_ms: 2000
    fallback_on_error: "default"
    default_result:
      risk_score: 0.5
      risk_label: "UNKNOWN"
  merge_strategy: "SHALLOW"
  automate_next: true
```

### WASM Module Contract

Your WebAssembly module must:

1. Read JSON from **stdin** — the input is either the full workflow state dict or the mapped keys from `state_mapping`
2. Write a JSON **object** to **stdout** — the keys are merged into workflow state
3. Exit with code **0** on success; any other exit code is treated as an error

**Minimal Rust example:**

```rust
use std::io::{self, Read};
use serde_json::{json, Value};

fn main() {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).unwrap();
    let state: Value = serde_json::from_str(&input).unwrap();

    let amount = state["amount"].as_f64().unwrap_or(0.0);
    let risk_score = if amount > 10_000.0 { 0.9 } else { 0.1 };

    let result = json!({
        "risk_score": risk_score,
        "risk_label": if risk_score > 0.7 { "HIGH" } else { "LOW" }
    });
    print!("{}", result);
}
```

Compile to WASM:

```bash
rustup target add wasm32-wasi
cargo build --target wasm32-wasi --release
# Binary: target/wasm32-wasi/release/risk_scorer.wasm
```

### Behavior

- Executes synchronously in the workflow process via `asyncio.run_in_executor` (non-blocking)
- WASI sandbox — the module cannot access the filesystem, network, or environment variables unless explicitly granted
- SHA-256 of the binary is verified before every execution
- Binary resolved from:
  - **Cloud**: local disk via `wasm_components.blob_storage_path`
  - **Edge**: SQLite `device_wasm_cache.binary_data`
- `fallback_on_error: "skip"` → returns `{}` and continues; `"default"` → returns `default_result`

### Edge Distribution

WASM binaries are pushed to edge devices via the `sync_wasm` command broadcast. When the cloud sends a `sync_wasm` command with a `binary_hash`, the edge agent:

1. Checks `device_wasm_cache` (idempotent — skips if already cached)
2. Downloads from `GET /api/v1/wasm-components/{hash}/download`
3. Verifies SHA-256
4. Stores the binary blob in SQLite

On device startup, `load_local_workflow_definitions()` scans all cached workflow YAMLs for `type: WASM` steps and prefetches any missing binaries in the background.

### Use Cases

- **Fraud scoring** — sub-2ms Rust risk model running offline on a POS terminal
- **Validation logic** — complex business rules compiled from a strongly-typed language
- **Data transformation** — format conversion or normalization without Python overhead
- **Cryptographic operations** — WASM-safe implementations of hashing or encoding

---

## See Also

- [YAML Schema](yaml-schema.md)
- [Directives](../api/directives.md)
- [StepContext](../api/step-context.md)
