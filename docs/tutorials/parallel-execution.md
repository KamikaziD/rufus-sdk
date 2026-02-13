# Tutorial: Add Parallel Execution to Your Workflow

**Learning Objectives:**
- Understand when to use parallel execution
- Add PARALLEL step type to workflows
- Configure merge strategies for parallel results
- Handle partial failures
- Test parallel execution with different executors

**Prerequisites:**
- Completed [Build a Task Manager](./build-task-manager.md)
- Understanding of async/await in Python

**Time:** 20 minutes

---

## What is Parallel Execution?

In real workflows, some tasks can run concurrently instead of sequentially. For example:

**Sequential (Slow)**:
```
Validate Order → Check Inventory → Verify Payment → Calculate Shipping
Total Time: 4 seconds
```

**Parallel (Fast)**:
```
Validate Order →  Check Inventory  ↓
                  Verify Payment    → Calculate Shipping
                  Fraud Check       ↑
Total Time: 2 seconds
```

Rufus provides the `PARALLEL` step type to run tasks concurrently.

---

## When to Use Parallel Execution

Use parallel steps when:
- ✅ Tasks are **independent** (no shared dependencies)
- ✅ Tasks can **fail independently** (one failure doesn't block others)
- ✅ You want **faster throughput** (I/O-bound operations)

Don't use parallel steps when:
- ❌ Tasks **depend on each other** (use sequential steps instead)
- ❌ Tasks **modify shared state** (race conditions)
- ❌ Order matters for business logic

---

## Step 1: Create a Parallel Workflow

Let's build an order processing workflow with parallel validation checks.

Create a new directory:

```bash
mkdir rufus-parallel-demo
cd rufus-parallel-demo
mkdir -p order_processor config
touch order_processor/__init__.py
```

### Define the State Model

Create `order_processor/models.py`:

```python
from pydantic import BaseModel
from typing import Optional, List, Dict


class OrderState(BaseModel):
    """State for order processing workflow"""

    # Order details
    order_id: str
    customer_id: str
    items: List[Dict[str, any]]
    total_amount: float

    # Validation results (from parallel checks)
    inventory_valid: Optional[bool] = None
    payment_valid: Optional[bool] = None
    fraud_check_passed: Optional[bool] = None

    # Validation details
    inventory_status: Optional[str] = None
    payment_status: Optional[str] = None
    fraud_score: Optional[float] = None

    # Shipping
    shipping_cost: Optional[float] = None
    estimated_delivery: Optional[str] = None

    # Overall status
    validation_complete: bool = False
    ready_to_ship: bool = False
```

---

## Step 2: Implement Parallel Task Functions

Create `order_processor/tasks.py`:

```python
"""
Parallel tasks for order validation
"""

import asyncio
from order_processor.models import OrderState
from rufus.models import StepContext


def check_inventory(state: OrderState, context: StepContext, **kwargs) -> dict:
    """
    Check if all items are in stock
    """
    print(f"📦 Checking inventory for order {state.order_id}")

    # Simulate inventory lookup (1 second)
    import time
    time.sleep(1)

    # Check each item
    all_in_stock = True
    for item in state.items:
        sku = item.get('sku')
        quantity = item.get('quantity', 1)
        print(f"   {sku}: {quantity} units")

        # Simulate: items starting with 'OUT' are out of stock
        if sku.startswith('OUT'):
            all_in_stock = False

    status = "in_stock" if all_in_stock else "out_of_stock"
    print(f"   Status: {status}")

    return {
        "inventory_valid": all_in_stock,
        "inventory_status": status
    }


def verify_payment(state: OrderState, context: StepContext, **kwargs) -> dict:
    """
    Verify payment method is valid
    """
    print(f"💳 Verifying payment for order {state.order_id}")

    # Simulate payment verification (1.5 seconds)
    import time
    time.sleep(1.5)

    # Simulate: amounts over $10,000 require manual review
    valid = state.total_amount < 10000

    status = "approved" if valid else "requires_review"
    print(f"   Amount: ${state.total_amount:.2f}")
    print(f"   Status: {status}")

    return {
        "payment_valid": valid,
        "payment_status": status
    }


def fraud_check(state: OrderState, context: StepContext, **kwargs) -> dict:
    """
    Run fraud detection on order
    """
    print(f"🔍 Running fraud check for order {state.order_id}")

    # Simulate fraud detection (2 seconds)
    import time
    time.sleep(2)

    # Simulate fraud score calculation
    fraud_score = hash(state.customer_id) % 100 / 100.0  # 0.0 to 1.0

    passed = fraud_score < 0.8  # Threshold: 0.8

    print(f"   Customer: {state.customer_id}")
    print(f"   Fraud Score: {fraud_score:.2f}")
    print(f"   Status: {'PASS' if passed else 'FAIL'}")

    return {
        "fraud_check_passed": passed,
        "fraud_score": fraud_score
    }
```

**Key Points:**
- Each task is **independent** - no shared state modifications
- Each task **returns a dict** - merged into workflow state
- Each task has **simulated delay** - shows parallel benefit
- Each task can **fail independently** - won't block others

---

## Step 3: Add Non-Parallel Steps

Create `order_processor/steps.py`:

```python
"""
Sequential steps for order processing
"""

from order_processor.models import OrderState
from rufus.models import StepContext


def validate_order(state: OrderState, context: StepContext, **kwargs) -> dict:
    """
    Initial order validation
    """
    print(f"\n📝 Validating order: {state.order_id}")
    print(f"   Customer: {state.customer_id}")
    print(f"   Items: {len(state.items)}")
    print(f"   Total: ${state.total_amount:.2f}\n")

    return {
        "step": "validate_order"
    }


def check_validation_results(state: OrderState, context: StepContext, **kwargs) -> dict:
    """
    Check if all parallel validations passed
    """
    print(f"\n✅ Checking validation results...")

    # Check results from parallel tasks
    inventory_ok = state.inventory_valid == True
    payment_ok = state.payment_valid == True
    fraud_ok = state.fraud_check_passed == True

    print(f"   Inventory: {'✓' if inventory_ok else '✗'} ({state.inventory_status})")
    print(f"   Payment: {'✓' if payment_ok else '✗'} ({state.payment_status})")
    print(f"   Fraud Check: {'✓' if fraud_ok else '✗'} (score: {state.fraud_score:.2f})")

    all_valid = inventory_ok and payment_ok and fraud_ok

    state.validation_complete = True
    state.ready_to_ship = all_valid

    print(f"\n   Overall: {'PASS' if all_valid else 'FAIL'}")

    return {
        "validation_complete": True,
        "ready_to_ship": all_valid
    }


def calculate_shipping(state: OrderState, context: StepContext, **kwargs) -> dict:
    """
    Calculate shipping cost
    """
    if not state.ready_to_ship:
        print("\n❌ Order not ready to ship - skipping shipping calculation")
        return {}

    print(f"\n📮 Calculating shipping for order {state.order_id}")

    # Simple shipping calculation
    shipping_cost = 5.00 + (len(state.items) * 2.00)

    print(f"   Items: {len(state.items)}")
    print(f"   Shipping Cost: ${shipping_cost:.2f}")
    print(f"   Estimated Delivery: 3-5 business days")

    return {
        "shipping_cost": shipping_cost,
        "estimated_delivery": "3-5 business days"
    }
```

---

## Step 4: Define the Workflow with PARALLEL Step

Create `config/workflow.yaml`:

```yaml
workflow_type: "OrderProcessing"
workflow_version: "1.0.0"
initial_state_model: "order_processor.models.OrderState"
description: "Order processing with parallel validation"

steps:
  - name: "Validate_Order"
    type: "STANDARD"
    function: "order_processor.steps.validate_order"
    automate_next: true
    description: "Initial order validation"

  - name: "Parallel_Validation"
    type: "PARALLEL"
    description: "Run validation checks concurrently"
    tasks:
      - name: "check_inventory"
        function_path: "order_processor.tasks.check_inventory"
      - name: "verify_payment"
        function_path: "order_processor.tasks.verify_payment"
      - name: "fraud_check"
        function_path: "order_processor.tasks.fraud_check"
    merge_strategy: "SHALLOW"
    merge_conflict_behavior: "PREFER_NEW"
    allow_partial_success: true
    timeout_seconds: 300
    automate_next: true

  - name: "Check_Results"
    type: "STANDARD"
    function: "order_processor.steps.check_validation_results"
    automate_next: true
    description: "Aggregate validation results"

  - name: "Calculate_Shipping"
    type: "STANDARD"
    function: "order_processor.steps.calculate_shipping"
    description: "Calculate shipping cost if order is valid"
```

**PARALLEL Step Configuration:**

- `tasks`: List of tasks to run in parallel
  - `name`: Task identifier
  - `function_path`: Python path to task function
- `merge_strategy`: How to merge results
  - `SHALLOW`: Merge top-level keys only
  - `DEEP`: Recursively merge nested dicts
- `merge_conflict_behavior`: What to do if tasks return same key
  - `PREFER_NEW`: Last task wins
  - `PREFER_OLD`: First task wins
  - `RAISE_ERROR`: Fail on conflict
- `allow_partial_success`: Continue if some tasks fail
- `timeout_seconds`: Maximum time for all tasks

---

## Step 5: Build and Run the Application

Create `main.py`:

```python
"""
Order Processing with Parallel Validation
"""

import asyncio
import time
from pathlib import Path

from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.memory import InMemoryPersistenceProvider
from rufus.implementations.execution.thread_pool import ThreadPoolExecutionProvider
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine


async def main():
    print("="*70)
    print("  RUFUS PARALLEL EXECUTION DEMO")
    print("="*70)

    # Create workflow builder with thread pool executor
    print("\n⚙️  Initializing with ThreadPoolExecutor (parallel execution)...")
    builder = WorkflowBuilder(
        registry_path=None,
        persistence_provider=InMemoryPersistenceProvider(),
        execution_provider=ThreadPoolExecutionProvider(max_workers=5),
        observer=LoggingObserver(),
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )

    # Load workflow
    workflow_path = Path(__file__).parent / "config" / "workflow.yaml"
    builder.load_workflow_config("OrderProcessing", str(workflow_path))
    print("✓ Workflow loaded\n")

    # Create order
    print("="*70)
    print("  PROCESSING ORDER")
    print("="*70)

    initial_data = {
        "order_id": "ORD-12345",
        "customer_id": "CUST-999",
        "items": [
            {"sku": "WIDGET-001", "quantity": 2, "price": 29.99},
            {"sku": "GADGET-042", "quantity": 1, "price": 149.99},
        ],
        "total_amount": 209.97
    }

    workflow = builder.create_workflow(
        "OrderProcessing",
        initial_data=initial_data
    )

    # Measure execution time
    start_time = time.time()

    # Execute workflow
    while workflow.status == "ACTIVE":
        result = await workflow.next_step()

        if workflow.status == "COMPLETED":
            break

    elapsed_time = time.time() - start_time

    # Show results
    print("\n" + "="*70)
    print("  WORKFLOW COMPLETED")
    print("="*70 + "\n")

    print(f"Order ID: {workflow.state.order_id}")
    print(f"Total Amount: ${workflow.state.total_amount:.2f}")
    print(f"\nValidation Results:")
    print(f"  Inventory: {'✓' if workflow.state.inventory_valid else '✗'}")
    print(f"  Payment: {'✓' if workflow.state.payment_valid else '✗'}")
    print(f"  Fraud Check: {'✓' if workflow.state.fraud_check_passed else '✗'}")
    print(f"\nReady to Ship: {'Yes' if workflow.state.ready_to_ship else 'No'}")

    if workflow.state.ready_to_ship:
        print(f"Shipping Cost: ${workflow.state.shipping_cost:.2f}")
        print(f"Estimated Delivery: {workflow.state.estimated_delivery}")

    print(f"\n⏱️  Execution Time: {elapsed_time:.2f} seconds")
    print(f"   (Sequential would take ~4.5 seconds)")
    print(f"   Speedup: {4.5/elapsed_time:.1f}x faster!")


if __name__ == '__main__':
    asyncio.run(main())
```

Run it:

```bash
python main.py
```

Output:

```
======================================================================
  RUFUS PARALLEL EXECUTION DEMO
======================================================================

⚙️  Initializing with ThreadPoolExecutor (parallel execution)...
✓ Workflow loaded

======================================================================
  PROCESSING ORDER
======================================================================

📝 Validating order: ORD-12345
   Customer: CUST-999
   Items: 2
   Total: $209.97

📦 Checking inventory for order ORD-12345
💳 Verifying payment for order ORD-12345
🔍 Running fraud check for order ORD-12345
   WIDGET-001: 2 units
   GADGET-042: 1 units
   Status: in_stock
   Amount: $209.97
   Status: approved
   Customer: CUST-999
   Fraud Score: 0.25
   Status: PASS

✅ Checking validation results...
   Inventory: ✓ (in_stock)
   Payment: ✓ (approved)
   Fraud Check: ✓ (score: 0.25)

   Overall: PASS

📮 Calculating shipping for order ORD-12345
   Items: 2
   Shipping Cost: $9.00
   Estimated Delivery: 3-5 business days

======================================================================
  WORKFLOW COMPLETED
======================================================================

Order ID: ORD-12345
Total Amount: $209.97

Validation Results:
  Inventory: ✓
  Payment: ✓
  Fraud Check: ✓

Ready to Ship: Yes
Shipping Cost: $9.00
Estimated Delivery: 3-5 business days

⏱️  Execution Time: 2.15 seconds
   (Sequential would take ~4.5 seconds)
   Speedup: 2.1x faster!
```

---

## Step 6: Test with Different Executors

### Compare Sequential vs Parallel

Let's compare execution times with different executors.

**Sequential Executor**:

```python
from rufus.implementations.execution.sync import SyncExecutor

# In main():
execution_provider=SyncExecutor(),  # Sequential execution
```

Run it:
```
⏱️  Execution Time: 4.58 seconds
   (Sequential would take ~4.5 seconds)
   Speedup: 1.0x faster!
```

**Thread Pool Executor** (current):
```
⏱️  Execution Time: 2.15 seconds
   Speedup: 2.1x faster!
```

**The parallel executor is 2x faster!**

---

## Understanding Merge Strategies

### SHALLOW Merge

```yaml
merge_strategy: "SHALLOW"
```

Results merged at top level only:

```python
# Task 1 returns:
{"inventory_valid": True, "details": {"sku": "A"}}

# Task 2 returns:
{"payment_valid": True, "details": {"amount": 100}}

# Merged result (SHALLOW):
{
    "inventory_valid": True,
    "payment_valid": True,
    "details": {"amount": 100}  # Task 2's details overwrites Task 1's
}
```

### DEEP Merge

```yaml
merge_strategy: "DEEP"
```

Results merged recursively:

```python
# Merged result (DEEP):
{
    "inventory_valid": True,
    "payment_valid": True,
    "details": {
        "sku": "A",      # From Task 1
        "amount": 100     # From Task 2
    }
}
```

---

## Handling Partial Failures

### Allow Partial Success

```yaml
allow_partial_success: true
```

Workflow continues even if some tasks fail:

```python
# Task 1: Success
# Task 2: Failure
# Task 3: Success

# Result: Workflow completes with tasks 1 and 3 results
# Failed task logged but doesn't block workflow
```

### Require All Success

```yaml
allow_partial_success: false
```

Workflow fails if any task fails:

```python
# Task 1: Success
# Task 2: Failure
# Task 3: Success

# Result: Workflow status = FAILED
```

---

## Best Practices

**✅ Do:**
- Use parallel execution for **independent I/O operations**
- Set **reasonable timeouts** (avoid infinite wait)
- Return **non-overlapping keys** from tasks (avoid conflicts)
- Test with **ThreadPoolExecutor** before deploying to Celery
- Use `allow_partial_success: true` for **optional checks**

**❌ Don't:**
- Use parallel execution for **CPU-bound tasks** (use Celery with separate workers)
- Modify **shared state** in parallel tasks (race conditions!)
- Return **same keys** from multiple tasks (creates merge conflicts)
- Use parallel execution when **order matters**
- Forget to set **timeouts** (tasks can hang forever)

---

## Performance Tips

1. **Thread Pool Size**: Match your I/O concurrency
   ```python
   ThreadPoolExecutionProvider(max_workers=10)  # 10 concurrent tasks
   ```

2. **Timeout Configuration**: Set per your slowest task
   ```yaml
   timeout_seconds: 300  # 5 minutes max
   ```

3. **Celery for Distributed**: Use for heavy workloads
   ```python
   from rufus.implementations.execution.celery import CeleryExecutor
   execution_provider=CeleryExecutor()
   ```

---

## What You've Learned

1. **PARALLEL Step Type**: Run tasks concurrently
2. **Merge Strategies**: SHALLOW vs DEEP merging
3. **Conflict Resolution**: PREFER_NEW, PREFER_OLD, RAISE_ERROR
4. **Partial Success**: Continue on partial failures
5. **Performance**: Measure and compare executor performance
6. **Executor Portability**: Test with ThreadPool before Celery

---

## Next Steps

**Try these enhancements:**
1. Add more parallel tasks (e.g., address validation, tax calculation)
2. Test with `CeleryExecutor` for distributed execution
3. Add error handling for failed tasks
4. Implement retry logic for transient failures
5. Add metrics tracking for task execution time

**Recommended Next Tutorial:**
- [Saga Pattern](./saga-pattern.md) - Add compensation for failures

---

## Troubleshooting

**Tasks run sequentially, not in parallel:**
- Check you're using `ThreadPoolExecutionProvider` or `CeleryExecutor`
- `SyncExecutor` runs tasks sequentially by design

**Merge conflicts:**
- Check task return values for overlapping keys
- Use `merge_conflict_behavior: "PREFER_NEW"` or make keys unique

**Timeout errors:**
- Increase `timeout_seconds` in workflow YAML
- Check task functions aren't hanging

**State not updated after parallel step:**
- Ensure tasks **return a dict**
- Check `merge_strategy` configuration
