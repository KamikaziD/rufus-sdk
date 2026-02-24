# Parallel Execution

Parallel execution allows a workflow to execute multiple tasks concurrently, significantly reducing total execution time for independent operations.

## Why Parallel Execution?

Consider a workflow that needs to:
1. Validate customer credit (300ms API call)
2. Check inventory availability (200ms database query)
3. Calculate shipping cost (150ms external service)

**Sequential execution**: 300ms + 200ms + 150ms = **650ms total**

**Parallel execution**: max(300ms, 200ms, 150ms) = **300ms total** (2.17x faster!)

When tasks don't depend on each other, running them in parallel is a significant performance optimization.

## How Parallel Steps Work

### YAML Configuration

```yaml
- name: "Gather_Order_Data"
  type: "PARALLEL"
  tasks:
    - name: "validate_credit"
      function_path: "steps.validate_customer_credit"

    - name: "check_inventory"
      function_path: "steps.check_inventory_availability"

    - name: "calculate_shipping"
      function_path: "steps.calculate_shipping_cost"

  merge_strategy: "SHALLOW"  # How to combine results
  merge_conflict_behavior: "PREFER_NEW"  # What to do on key collision
  allow_partial_success: true  # Continue if some tasks fail
  timeout_seconds: 300  # Max time to wait for all tasks
```

### Execution Flow

```
1. Workflow reaches "Gather_Order_Data" step
2. ExecutionProvider dispatches 3 tasks concurrently:
   - Task 1: validate_credit (to worker A)
   - Task 2: check_inventory (to worker B)
   - Task 3: calculate_shipping (to worker C)
3. Workflow transitions to PENDING_ASYNC
4. Workers execute tasks in parallel
5. Each worker reports result back:
   - validate_credit → {"credit_approved": True, "credit_limit": 10000}
   - check_inventory → {"in_stock": True, "warehouse_id": "WH-1"}
   - calculate_shipping → {"shipping_cost": 15.99, "estimated_days": 3}
6. Rufus merges results using merge_strategy
7. Merged result saved to workflow state
8. Workflow transitions to ACTIVE (ready for next step)
```

## Task Function Signature

Parallel task functions are identical to standard step functions:

```python
def validate_customer_credit(state: OrderState, context: StepContext) -> dict:
    """Parallel task: Validate customer credit."""
    customer_id = state.customer_id

    # Call external API
    credit_info = credit_api.check(customer_id)

    # Return result
    return {
        "credit_approved": credit_info.approved,
        "credit_limit": credit_info.limit
    }
```

**Key Points**:
- Receives same `state` and `context` as sequential steps
- Returns dict that will be merged
- Can read state, cannot reliably write state (race conditions)
- Should be stateless and idempotent

## Merge Strategies

When parallel tasks complete, Rufus must merge their results into a single dict. There are two strategies:

### SHALLOW Merge (Default)

Top-level keys are merged, nested dicts replace entirely:

```python
# Task 1 returns:
{"customer": {"name": "Alice", "tier": "gold"}, "approved": True}

# Task 2 returns:
{"customer": {"id": "C123"}, "inventory": {"qty": 5}}

# Merged result (SHALLOW):
{
    "customer": {"id": "C123"},  # Task 2 replaces Task 1
    "approved": True,             # From Task 1
    "inventory": {"qty": 5}       # From Task 2
}
```

**When to use**: Default behavior, simpler logic, each task owns distinct top-level keys.

### DEEP Merge

Nested dicts are recursively merged:

```python
# Task 1 returns:
{"customer": {"name": "Alice", "tier": "gold"}, "approved": True}

# Task 2 returns:
{"customer": {"id": "C123"}, "inventory": {"qty": 5}}

# Merged result (DEEP):
{
    "customer": {
        "name": "Alice",  # From Task 1
        "tier": "gold",   # From Task 1
        "id": "C123"      # From Task 2
    },
    "approved": True,
    "inventory": {"qty": 5}
}
```

**When to use**: Tasks contribute to the same nested object.

**Configuration**:
```yaml
merge_strategy: "DEEP"
```

## Conflict Handling

What happens when two tasks return the same key?

```python
# Task 1 returns:
{"price": 99.99, "currency": "USD"}

# Task 2 returns:
{"price": 89.99, "currency": "USD"}  # Conflict on "price"!
```

Rufus offers three conflict behaviors:

### PREFER_NEW (Default)

Later task overwrites earlier task:

```python
# Merged result:
{"price": 89.99, "currency": "USD"}  # Task 2's price wins
```

**When to use**: Tasks have priority order, later tasks are more authoritative.

### PREFER_OLD

Earlier task wins:

```python
# Merged result:
{"price": 99.99, "currency": "USD"}  # Task 1's price wins
```

**When to use**: First result is canonical, subsequent results are fallbacks.

### RAISE_ERROR

Throw error on conflict:

```python
# Raises: MergeConflictError("Key 'price' exists in multiple task results")
```

**When to use**: Conflicts indicate a bug, tasks should own distinct keys.

**Configuration**:
```yaml
merge_conflict_behavior: "RAISE_ERROR"
```

## Partial Success

What if one task fails but others succeed?

```python
# Task 1: validate_credit → {"credit_approved": True} (SUCCESS)
# Task 2: check_inventory → {"in_stock": True} (SUCCESS)
# Task 3: calculate_shipping → Exception! (FAILURE)
```

### allow_partial_success: true

Workflow continues with partial results:

```python
# Merged result (Tasks 1 and 2 only):
{
    "credit_approved": True,
    "in_stock": True,
    "shipping_cost_failed": True  # Rufus adds failure metadata
}

# Workflow status: ACTIVE (continues to next step)
```

**When to use**: Optional tasks, graceful degradation.

### allow_partial_success: false (Default)

Workflow fails if any task fails:

```python
# Workflow status: FAILED
# Error: "Parallel task 'calculate_shipping' failed: ..."
```

**When to use**: All tasks are required, failure is not acceptable.

**Configuration**:
```yaml
allow_partial_success: true
```

## Timeout Handling

Parallel steps have a maximum execution time:

```yaml
timeout_seconds: 300  # Max 5 minutes for all tasks
```

**Behavior**:
1. Workflow waits up to 300 seconds for all tasks to complete
2. If timeout expires:
   - With `allow_partial_success: true`: Use results from completed tasks
   - With `allow_partial_success: false`: Workflow fails

**Example**:
```python
# Task 1: Completes in 10s
# Task 2: Completes in 20s
# Task 3: Hangs (never completes)

# After 300s:
# - With partial success: Use results from Tasks 1 and 2
# - Without partial success: Workflow fails
```

## Execution Providers

How tasks execute depends on the `ExecutionProvider`:

### SyncExecutionProvider (Development)

Executes tasks **sequentially** in the main process:

```python
# Despite YAML saying "parallel", SyncExecutionProvider runs sequentially
for task in parallel_step.tasks:
    result = task.function(state, context)
    results.append(result)
```

**Why**: Simplifies debugging, deterministic execution, no worker infrastructure needed.

### CeleryExecutionProvider (Production)

Dispatches tasks to Celery workers in parallel:

```python
# Dispatch all tasks to Celery
celery_tasks = [
    execute_async_task.apply_async(kwargs={"task": task, ...})
    for task in parallel_step.tasks
]

# Wait for all to complete (or timeout)
results = [task.get(timeout=timeout_seconds) for task in celery_tasks]
```

**Characteristics**:
- True parallelism (different processes/machines)
- Fault tolerance (worker retries)
- Scalability (add more workers)

### ThreadPoolExecutionProvider

Executes tasks in Python threads:

```python
with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
    futures = [
        executor.submit(task.function, state, context)
        for task in parallel_step.tasks
    ]
    results = [future.result(timeout=timeout_seconds) for future in futures]
```

**Characteristics**:
- True parallelism for I/O-bound tasks (API calls, database queries)
- Limited by GIL for CPU-bound tasks
- No external dependencies (no Celery/Redis)

## Common Patterns

### Pattern 1: Gather Data from Multiple Sources

```yaml
- name: "Gather_Customer_Data"
  type: "PARALLEL"
  tasks:
    - name: "get_customer_profile"
      function_path: "steps.get_customer_from_crm"

    - name: "get_order_history"
      function_path: "steps.get_orders_from_db"

    - name: "get_loyalty_points"
      function_path: "steps.get_points_from_loyalty_api"

  merge_strategy: "DEEP"
  merge_conflict_behavior: "PREFER_NEW"
```

**Result**:
```python
{
    "customer_profile": {"name": "Alice", "email": "alice@example.com"},
    "order_history": [{"order_id": "O1"}, {"order_id": "O2"}],
    "loyalty_points": 5000
}
```

### Pattern 2: Validation Checks

```yaml
- name: "Validate_Order"
  type: "PARALLEL"
  tasks:
    - name: "validate_address"
      function_path: "validators.validate_shipping_address"

    - name: "validate_payment_method"
      function_path: "validators.validate_payment_info"

    - name: "validate_inventory"
      function_path: "validators.check_item_availability"

  allow_partial_success: false  # All validations must pass
```

**Behavior**: If any validation fails, workflow fails immediately.

### Pattern 3: Fan-Out Processing

```yaml
- name: "Send_Notifications"
  type: "PARALLEL"
  tasks:
    - name: "send_email"
      function_path: "notifiers.send_email_notification"

    - name: "send_sms"
      function_path: "notifiers.send_sms_notification"

    - name: "send_push"
      function_path: "notifiers.send_push_notification"

  allow_partial_success: true  # OK if some notifications fail
```

**Behavior**: Best-effort notifications, workflow continues even if some fail.

### Pattern 4: Dynamic Fan-Out (Runtime-Generated Tasks)

The patterns above have a fixed task list defined in YAML at design time. **Dynamic fan-out** generates tasks at runtime from a list in workflow state — useful when you don't know the target set until the workflow is running.

```yaml
- name: "Push_Config_To_Fleet"
  type: "PARALLEL"
  iterate_over: "device_ids"       # dot-notation path to a list in state
  task_function: "steps.push_to_device"  # called once per item
  item_var_name: "device_id"       # kwarg name for each item (default: "item")
  merge_strategy: "SHALLOW"
  allow_partial_success: true
```

```python
def push_to_device(state: FleetState, context: StepContext, device_id: str = "", **_) -> dict:
    """Called once per device in state.device_ids."""
    push_config_update(device_id, state.config_data)
    return {"pushed": device_id}
```

**How it works**: When the PARALLEL step executes, Rufus reads `state.device_ids`, creates one task per element, and dispatches them all concurrently. If `state.device_ids` has 500 items, 500 tasks run in parallel.

**When to use dynamic fan-out vs. static tasks:**

| | Static tasks | Dynamic fan-out |
|---|---|---|
| **Task set** | Fixed at design time in YAML | Determined at runtime from state |
| **Use case** | Calling 2–5 known services | Processing N items from a list |
| **Examples** | Validate credit + inventory + address | Push config to fleet, process order items, notify user list |

**State requirement**: The `iterate_over` list must be populated in state before the PARALLEL step runs. Set it in an earlier STANDARD step:

```python
async def load_target_devices(state: FleetState, context: StepContext, **_) -> dict:
    devices = await fetch_online_devices()
    return {"device_ids": [d.id for d in devices]}
```

## Race Conditions and State Mutations

**WARNING**: Parallel tasks share the same workflow state. Modifying state in parallel tasks creates race conditions:

```python
# ❌ Bad: Race condition
def task_a(state: OrderState, context: StepContext):
    state.items.append({"sku": "ITEM-A"})  # Mutates shared state
    return {}

def task_b(state: OrderState, context: StepContext):
    state.items.append({"sku": "ITEM-B"})  # Mutates shared state
    return {}

# Result: One mutation may be lost (race condition)
```

**Best Practice**: Only **read** state in parallel tasks, **return** mutations:

```python
# ✅ Good: No race condition
def task_a(state: OrderState, context: StepContext):
    # Read state
    user_id = state.user_id

    # Compute result
    item_a = fetch_item("ITEM-A", user_id)

    # Return (Rufus merges after all tasks complete)
    return {"item_a": item_a}

def task_b(state: OrderState, context: StepContext):
    user_id = state.user_id
    item_b = fetch_item("ITEM-B", user_id)
    return {"item_b": item_b}

# Result: Deterministic merge, no race condition
```

## Performance Considerations

### Task Granularity

**Too fine-grained** (many tiny tasks):
- High coordination overhead
- Context switching cost
- Diminishing returns

```yaml
# ❌ Bad: Too many small tasks
tasks:
  - name: "add_1"
  - name: "add_2"
  - name: "add_3"
  # 100 tasks, each takes 1ms
  # Overhead > actual work
```

**Too coarse-grained** (few large tasks):
- Limited parallelism
- Long-pole problem (slowest task determines total time)

```yaml
# ❌ Bad: One task does everything
tasks:
  - name: "do_everything"  # 10-second task, no parallelism
```

**Sweet spot** (3-10 tasks of similar duration):
```yaml
# ✅ Good: Balanced parallelism
tasks:
  - name: "fetch_customer"     # ~300ms
  - name: "fetch_inventory"    # ~250ms
  - name: "fetch_pricing"      # ~200ms
  - name: "calculate_shipping" # ~150ms
# Total: ~300ms (vs 900ms sequential)
```

### Network vs CPU Bound

**I/O-bound tasks** (API calls, database queries):
- Excellent candidates for parallelization
- ThreadPoolExecutor or Celery both work well
- High speedup potential

**CPU-bound tasks** (image processing, data analysis):
- Limited by GIL with ThreadPoolExecutor
- Use CeleryExecutionProvider with process pool
- Or use multiprocessing explicitly

## Debugging Parallel Steps

### Logging

Parallel tasks log independently:

```python
def task_a(state, context):
    logger.info(f"[{context.workflow_id}] Task A started")
    result = do_work()
    logger.info(f"[{context.workflow_id}] Task A completed")
    return result
```

**Tip**: Include `workflow_id` in logs to correlate parallel tasks.

### Audit Trail

Audit log shows parallel task execution:

```sql
SELECT step_name, event_type, event_data, created_at
FROM workflow_audit_log
WHERE workflow_id = '550e8400-...'
  AND step_name = 'Gather_Order_Data'
ORDER BY created_at ASC;
```

Example output:
```
event_type              | event_data                        | created_at
------------------------|-----------------------------------|-------------------
PARALLEL_TASKS_STARTED  | {"task_count": 3}                 | 10:15:00.000
PARALLEL_TASK_COMPLETED | {"task_name": "check_inventory"}  | 10:15:00.200
PARALLEL_TASK_COMPLETED | {"task_name": "calculate_ship..."}| 10:15:00.150
PARALLEL_TASK_COMPLETED | {"task_name": "validate_credit"}  | 10:15:00.300
PARALLEL_TASKS_MERGED   | {"merge_strategy": "SHALLOW"}     | 10:15:00.305
```

### Testing Parallel Steps

Use `SyncExecutionProvider` for deterministic tests:

```python
def test_parallel_step():
    # Use sync executor (no actual parallelism)
    execution = SyncExecutionProvider()

    builder = WorkflowBuilder(
        config_dir="config/",
        execution_provider=execution,
        ...
    )

    workflow = builder.create_workflow("MyWorkflow", data)
    workflow.execute_next_step()  # Parallel step runs sequentially

    # Assertions on merged result
    assert workflow.state.credit_approved is True
```

**Benefit**: No race conditions, deterministic order, easier debugging.

## What's Next

Now that you understand parallel execution:
- [State Management](state-management.md) - How parallel results merge into state
- [Workflow Lifecycle](workflow-lifecycle.md) - PENDING_ASYNC state transitions
- [Performance](performance.md) - Optimizing parallel task performance
