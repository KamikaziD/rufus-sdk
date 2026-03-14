# Tutorial: Implement the Saga Pattern for Compensation

**Learning Objectives:**
- Understand the Saga pattern for distributed transactions
- Implement compensation functions for rollback
- Enable Saga mode in workflows
- Test failure scenarios and rollback
- Handle partial failures gracefully

**Prerequisites:**
- Completed [Build a Task Manager](./build-task-manager.md)
- Understanding of database transactions

**Time:** 25 minutes

---

## What is the Saga Pattern?

The Saga pattern manages **distributed transactions** by breaking them into steps with **compensation** logic.

**Traditional Transaction (Single Database)**:
```sql
BEGIN TRANSACTION;
  INSERT INTO orders ...;
  UPDATE inventory ...;
  INSERT INTO payments ...;
COMMIT;  -- All or nothing
```

**Saga Pattern (Distributed Systems)**:
```
Step 1: Create Order     → Compensation: Cancel Order
Step 2: Charge Payment   → Compensation: Refund Payment
Step 3: Ship Order       → Compensation: Cancel Shipment

If Step 3 fails:
  1. Run compensation for Step 2 (refund)
  2. Run compensation for Step 1 (cancel order)
  3. Workflow status = FAILED_ROLLED_BACK
```

---

## When to Use Saga Pattern

Use Saga pattern when:
- ✅ **Multiple external systems** (payment gateway, shipping API, inventory)
- ✅ **Distributed transactions** (no single database ACID guarantees)
- ✅ **Reversible operations** (refunds, cancellations)
- ✅ **Long-running workflows** (manual approvals, async operations)

Don't use Saga when:
- ❌ **Single database** (use database transactions instead)
- ❌ **Operations can't be reversed** (sending emails, logging)
- ❌ **Simple sequential workflows** (unnecessary complexity)

---

## Step 1: Create a Payment Workflow

Let's build an e-commerce payment workflow with compensation.

Create a new directory:

```bash
mkdir rufus-saga-demo
cd rufus-saga-demo
mkdir -p payment_processor config
touch payment_processor/__init__.py
```

### Define the State Model

Create `payment_processor/models.py`:

```python
from pydantic import BaseModel
from typing import Optional


class PaymentState(BaseModel):
    """State for payment processing workflow"""

    # Order details
    order_id: str
    customer_id: str
    amount: float
    currency: str = "USD"

    # Step results
    order_created: bool = False
    order_reference: Optional[str] = None

    payment_charged: bool = False
    transaction_id: Optional[str] = None
    payment_method: Optional[str] = None

    inventory_reserved: bool = False
    reservation_id: Optional[str] = None

    shipment_created: bool = False
    tracking_number: Optional[str] = None

    # Compensation tracking
    compensations_run: list = []

    # Final status
    workflow_status: str = "pending"
```

---

## Step 2: Implement Step Functions with Compensation

Create `payment_processor/steps.py`:

```python
"""
Payment workflow steps with compensation functions
"""

import uuid
from payment_processor.models import PaymentState
from rufus.models import StepContext


# ============================================================================
# STEP 1: Create Order
# ============================================================================

def create_order(state: PaymentState, context: StepContext, **kwargs) -> dict:
    """
    Create order in order management system
    """
    print(f"\n📝 Creating order for customer {state.customer_id}")
    print(f"   Amount: ${state.amount:.2f} {state.currency}")

    # Simulate order creation
    order_ref = f"ORD-{uuid.uuid4().hex[:8].upper()}"

    print(f"   ✓ Order created: {order_ref}")

    return {
        "order_created": True,
        "order_reference": order_ref,
        "workflow_status": "order_created"
    }


def cancel_order(state: PaymentState, context: StepContext, **kwargs) -> dict:
    """
    COMPENSATION: Cancel order if workflow fails
    """
    print(f"\n🔄 COMPENSATION: Canceling order {state.order_reference}")

    # Simulate order cancellation
    print(f"   ✓ Order {state.order_reference} canceled")

    state.compensations_run.append("cancel_order")

    return {
        "order_created": False,
        "workflow_status": "order_canceled"
    }


# ============================================================================
# STEP 2: Charge Payment
# ============================================================================

def charge_payment(state: PaymentState, context: StepContext, **kwargs) -> dict:
    """
    Charge customer's payment method
    """
    print(f"\n💳 Charging payment: ${state.amount:.2f}")

    # Simulate payment processing
    transaction_id = f"TXN-{uuid.uuid4().hex[:12].upper()}"
    payment_method = "card_****1234"

    print(f"   Payment Method: {payment_method}")
    print(f"   ✓ Payment charged: {transaction_id}")

    # SIMULATE FAILURE: Uncomment to test compensation
    # raise Exception("Payment gateway timeout")

    return {
        "payment_charged": True,
        "transaction_id": transaction_id,
        "payment_method": payment_method,
        "workflow_status": "payment_charged"
    }


def refund_payment(state: PaymentState, context: StepContext, **kwargs) -> dict:
    """
    COMPENSATION: Refund payment if workflow fails
    """
    print(f"\n🔄 COMPENSATION: Refunding payment {state.transaction_id}")
    print(f"   Amount: ${state.amount:.2f}")

    # Simulate refund processing
    print(f"   ✓ Refund processed: {state.transaction_id}")

    state.compensations_run.append("refund_payment")

    return {
        "payment_charged": False,
        "workflow_status": "payment_refunded"
    }


# ============================================================================
# STEP 3: Reserve Inventory
# ============================================================================

def reserve_inventory(state: PaymentState, context: StepContext, **kwargs) -> dict:
    """
    Reserve inventory for order
    """
    print(f"\n📦 Reserving inventory for order {state.order_reference}")

    # Simulate inventory reservation
    reservation_id = f"RES-{uuid.uuid4().hex[:8].upper()}"

    print(f"   ✓ Inventory reserved: {reservation_id}")

    return {
        "inventory_reserved": True,
        "reservation_id": reservation_id,
        "workflow_status": "inventory_reserved"
    }


def release_inventory(state: PaymentState, context: StepContext, **kwargs) -> dict:
    """
    COMPENSATION: Release inventory reservation if workflow fails
    """
    print(f"\n🔄 COMPENSATION: Releasing inventory {state.reservation_id}")

    # Simulate inventory release
    print(f"   ✓ Inventory released: {state.reservation_id}")

    state.compensations_run.append("release_inventory")

    return {
        "inventory_reserved": False,
        "workflow_status": "inventory_released"
    }


# ============================================================================
# STEP 4: Create Shipment
# ============================================================================

def create_shipment(state: PaymentState, context: StepContext, **kwargs) -> dict:
    """
    Create shipment with carrier
    """
    print(f"\n📮 Creating shipment for order {state.order_reference}")

    # SIMULATE FAILURE HERE (for testing compensation)
    # Uncomment to trigger rollback:
    # raise Exception("Carrier API unavailable")

    # Simulate shipment creation
    tracking_number = f"TRACK-{uuid.uuid4().hex[:10].upper()}"

    print(f"   ✓ Shipment created: {tracking_number}")

    return {
        "shipment_created": True,
        "tracking_number": tracking_number,
        "workflow_status": "completed"
    }


def cancel_shipment(state: PaymentState, context: StepContext, **kwargs) -> dict:
    """
    COMPENSATION: Cancel shipment if workflow fails
    """
    print(f"\n🔄 COMPENSATION: Canceling shipment {state.tracking_number}")

    # Simulate shipment cancellation
    print(f"   ✓ Shipment canceled: {state.tracking_number}")

    state.compensations_run.append("cancel_shipment")

    return {
        "shipment_created": False,
        "workflow_status": "shipment_canceled"
    }
```

**Key Points:**
- Each forward step has a **compensation function**
- Compensation functions **undo** the forward step
- Compensations run in **reverse order** on failure
- Track compensations in `state.compensations_run` for debugging

---

## Step 3: Define Workflow with Compensation

Create `config/workflow.yaml`:

```yaml
workflow_type: "PaymentProcessing"
workflow_version: "1.0.0"
initial_state_model: "payment_processor.models.PaymentState"
description: "Payment workflow with Saga pattern compensation"

steps:
  - name: "Create_Order"
    type: "STANDARD"
    function: "payment_processor.steps.create_order"
    compensate_function: "payment_processor.steps.cancel_order"
    automate_next: true
    description: "Create order in OMS"

  - name: "Charge_Payment"
    type: "STANDARD"
    function: "payment_processor.steps.charge_payment"
    compensate_function: "payment_processor.steps.refund_payment"
    automate_next: true
    description: "Charge customer payment method"

  - name: "Reserve_Inventory"
    type: "STANDARD"
    function: "payment_processor.steps.reserve_inventory"
    compensate_function: "payment_processor.steps.release_inventory"
    automate_next: true
    description: "Reserve inventory for shipment"

  - name: "Create_Shipment"
    type: "STANDARD"
    function: "payment_processor.steps.create_shipment"
    compensate_function: "payment_processor.steps.cancel_shipment"
    description: "Create shipment with carrier"
```

**YAML Configuration:**
- `compensate_function`: Python path to compensation function
- Compensation functions called in **reverse order** on failure
- All steps are compensatable in this workflow

---

## Step 4: Enable Saga Mode

Create `main.py`:

```python
"""
Payment Processing with Saga Pattern

Demonstrates:
- Compensatable steps
- Saga mode activation
- Automatic rollback on failure
"""

import asyncio
from pathlib import Path

from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.memory import InMemoryPersistenceProvider
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine


async def main():
    print("="*70)
    print("  RUFUS SAGA PATTERN DEMO")
    print("="*70)

    # Create workflow builder
    persistence = InMemoryPersistenceProvider()
    builder = WorkflowBuilder(
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )

    # Create payment workflow
    print("\n" + "="*70)
    print("  PROCESSING PAYMENT")
    print("="*70)

    initial_data = {
        "order_id": "ORD-12345",
        "customer_id": "CUST-789",
        "amount": 299.99,
        "currency": "USD"
    }

    workflow = await builder.create_workflow(
        workflow_type="PaymentProcessing",
        persistence_provider=persistence,
        execution_provider=SyncExecutor(),
        workflow_observer=LoggingObserver(),
        workflow_builder=builder,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        initial_data=initial_data,
    )

    # ========================================================================
    # ENABLE SAGA MODE (Required for compensation)
    # ========================================================================
    workflow.enable_saga_mode()
    print("✓ Saga mode enabled (compensation active)\n")

    # Execute workflow
    try:
        while workflow.status == "ACTIVE":
            result = await workflow.next_step()

            if workflow.status == "COMPLETED":
                print("\n" + "="*70)
                print("  WORKFLOW COMPLETED SUCCESSFULLY")
                print("="*70 + "\n")
                break

            elif workflow.status == "FAILED":
                print("\n" + "="*70)
                print("  WORKFLOW FAILED - INITIATING ROLLBACK")
                print("="*70 + "\n")
                break

    except Exception as e:
        print(f"\n❌ Workflow execution failed: {e}")

    # Show final state
    print("\n" + "="*70)
    print("  FINAL STATE")
    print("="*70 + "\n")

    print(f"Workflow ID: {workflow.id}")
    print(f"Status: {workflow.status}")
    print(f"Order Reference: {workflow.state.order_reference}")
    print(f"\nStep Results:")
    print(f"  Order Created: {workflow.state.order_created}")
    print(f"  Payment Charged: {workflow.state.payment_charged}")
    print(f"  Inventory Reserved: {workflow.state.inventory_reserved}")
    print(f"  Shipment Created: {workflow.state.shipment_created}")

    if workflow.state.compensations_run:
        print(f"\n⚠️  Compensations Run:")
        for comp in workflow.state.compensations_run:
            print(f"  - {comp}")
    else:
        print(f"\n✅ No compensations needed")

    print(f"\nFinal Workflow Status: {workflow.state.workflow_status}")


if __name__ == '__main__':
    asyncio.run(main())
```

**Critical Step:**
```python
workflow.enable_saga_mode()  # Must call before executing steps!
```

---

## Step 5: Test Success Scenario

Run the workflow:

```bash
python main.py
```

Output (success):

```
======================================================================
  RUFUS SAGA PATTERN DEMO
======================================================================

======================================================================
  PROCESSING PAYMENT
======================================================================
✓ Saga mode enabled (compensation active)

📝 Creating order for customer CUST-789
   Amount: $299.99 USD
   ✓ Order created: ORD-A1B2C3D4

💳 Charging payment: $299.99
   Payment Method: card_****1234
   ✓ Payment charged: TXN-1234567890AB

📦 Reserving inventory for order ORD-A1B2C3D4
   ✓ Inventory reserved: RES-E5F6G7H8

📮 Creating shipment for order ORD-A1B2C3D4
   ✓ Shipment created: TRACK-I9J0K1L2M3

======================================================================
  WORKFLOW COMPLETED SUCCESSFULLY
======================================================================

======================================================================
  FINAL STATE
======================================================================

Workflow ID: 550e8400-e29b-41d4-a716-446655440000
Status: COMPLETED
Order Reference: ORD-A1B2C3D4

Step Results:
  Order Created: True
  Payment Charged: True
  Inventory Reserved: True
  Shipment Created: True

✅ No compensations needed

Final Workflow Status: completed
```

---

## Step 6: Test Failure Scenario

Now let's simulate a failure and watch the compensations run.

Edit `payment_processor/steps.py`, uncomment the failure in `create_shipment()`:

```python
def create_shipment(state: PaymentState, context: StepContext, **kwargs) -> dict:
    """
    Create shipment with carrier
    """
    print(f"\n📮 Creating shipment for order {state.order_reference}")

    # SIMULATE FAILURE
    raise Exception("Carrier API unavailable")

    # ... rest of function
```

Run again:

```bash
python main.py
```

Output (with compensation):

```
======================================================================
  RUFUS SAGA PATTERN DEMO
======================================================================

======================================================================
  PROCESSING PAYMENT
======================================================================
✓ Saga mode enabled (compensation active)

📝 Creating order for customer CUST-789
   Amount: $299.99 USD
   ✓ Order created: ORD-A1B2C3D4

💳 Charging payment: $299.99
   Payment Method: card_****1234
   ✓ Payment charged: TXN-1234567890AB

📦 Reserving inventory for order ORD-A1B2C3D4
   ✓ Inventory reserved: RES-E5F6G7H8

📮 Creating shipment for order ORD-A1B2C3D4

======================================================================
  WORKFLOW FAILED - INITIATING ROLLBACK
======================================================================

🔄 COMPENSATION: Releasing inventory RES-E5F6G7H8
   ✓ Inventory released: RES-E5F6G7H8

🔄 COMPENSATION: Refunding payment TXN-1234567890AB
   Amount: $299.99
   ✓ Refund processed: TXN-1234567890AB

🔄 COMPENSATION: Canceling order ORD-A1B2C3D4
   ✓ Order ORD-A1B2C3D4 canceled

======================================================================
  FINAL STATE
======================================================================

Workflow ID: 550e8400-e29b-41d4-a716-446655440000
Status: FAILED_ROLLED_BACK
Order Reference: ORD-A1B2C3D4

Step Results:
  Order Created: False
  Payment Charged: False
  Inventory Reserved: False
  Shipment Created: False

⚠️  Compensations Run:
  - release_inventory
  - refund_payment
  - cancel_order

Final Workflow Status: inventory_released
```

**What happened:**
1. Steps 1-3 completed successfully
2. Step 4 failed (carrier API error)
3. Compensations ran in **reverse order**:
   - Step 3 compensation: Release inventory
   - Step 2 compensation: Refund payment
   - Step 1 compensation: Cancel order
4. Workflow status: `FAILED_ROLLED_BACK`

---

## Understanding Compensation Flow

### Forward Execution (Success)

```
Create Order → Charge Payment → Reserve Inventory → Create Shipment
     ✓              ✓                  ✓                  ✓
Status: COMPLETED
```

### Forward + Rollback (Failure)

```
Create Order → Charge Payment → Reserve Inventory → Create Shipment
     ✓              ✓                  ✓                  ✗ FAIL!

Rollback (reverse order):
Cancel Shipment  (skipped - never created)
     ←
Release Inventory
     ←
Refund Payment
     ←
Cancel Order

Status: FAILED_ROLLED_BACK
```

---

## Best Practices

### ✅ Do:

1. **Make compensations idempotent**
   ```python
   def refund_payment(state, context, **kwargs):
       if not state.transaction_id:
           return {}  # Nothing to refund

       # Idempotent refund
       refund_id = refund_service.refund(state.transaction_id)
       return {"refund_id": refund_id}
   ```

2. **Log compensation execution**
   ```python
   state.compensations_run.append("refund_payment")
   await context.persistence.log_execution(
       workflow_id=context.workflow_id,
       log_level="WARNING",
       message=f"Compensation: refund_payment executed",
       step_name="Charge_Payment"
   )
   ```

3. **Test failure scenarios**
   ```python
   # Add failure injection for testing
   if os.getenv("SIMULATE_FAILURE") == "payment":
       raise Exception("Simulated payment failure")
   ```

4. **Handle partial compensations**
   ```python
   def cancel_order(state, context, **kwargs):
       try:
           order_service.cancel(state.order_reference)
       except OrderNotFoundError:
           # Order might be already canceled or never created
           logger.warning("Order not found during compensation")
       return {"order_created": False}
   ```

### ❌ Don't:

1. **Forget to enable Saga mode**
   ```python
   # WRONG: Compensations won't run
   workflow = builder.create_workflow("PaymentProcessing", data)
   await workflow.next_step()  # No compensation on failure!

   # RIGHT:
   workflow = builder.create_workflow("PaymentProcessing", data)
   workflow.enable_saga_mode()  # Compensation active
   await workflow.next_step()
   ```

2. **Assume compensation always succeeds**
   ```python
   # BAD: What if refund API is down?
   def refund_payment(state, context, **kwargs):
       payment_api.refund(state.transaction_id)  # Might fail!

   # GOOD: Handle compensation failures
   def refund_payment(state, context, **kwargs):
       try:
           payment_api.refund(state.transaction_id)
       except RefundError as e:
           logger.error(f"Refund failed: {e}")
           # Alert operations team
           alert_ops_team(f"Manual refund needed: {state.transaction_id}")
       return {}
   ```

3. **Use Saga for irreversible operations**
   ```python
   # BAD: Can't "unring the bell"
   def send_email(state, context, **kwargs):
       email_service.send(state.customer_email, "Order confirmed")
       return {}

   def unsend_email(state, context, **kwargs):
       # ??? Can't unsend email
       pass
   ```

---

## Advanced: Compensation with External State

Sometimes compensation requires data from the forward step:

```python
def charge_payment(state: PaymentState, context: StepContext, **kwargs) -> dict:
    """Charge payment and store provider info"""
    result = payment_gateway.charge(
        amount=state.amount,
        method=state.payment_method
    )

    # Store EVERYTHING needed for compensation
    return {
        "payment_charged": True,
        "transaction_id": result.transaction_id,
        "gateway_provider": result.provider,  # Need this for refund!
        "gateway_token": result.token,        # Need this too!
        "charged_amount": result.actual_amount  # Might differ from requested
    }


def refund_payment(state: PaymentState, context: StepContext, **kwargs) -> dict:
    """Refund using stored gateway info"""
    # Use data stored by forward step
    refund_result = payment_gateway.refund(
        provider=state.gateway_provider,
        token=state.gateway_token,
        amount=state.charged_amount,
        transaction_id=state.transaction_id
    )

    return {
        "payment_charged": False,
        "refund_id": refund_result.refund_id
    }
```

---

## What You've Learned

1. **Saga Pattern**: Distributed transaction management via compensation
2. **Compensatable Steps**: Link forward functions with compensation functions
3. **Saga Mode**: Enable via `workflow.enable_saga_mode()`
4. **Reverse Order**: Compensations run in reverse of execution
5. **Idempotency**: Make compensations safe to run multiple times
6. **Error Handling**: Handle compensation failures gracefully

---

## Next Steps

**Try these enhancements:**
1. Add compensation for partially completed steps
2. Implement retry logic before compensation
3. Add metrics tracking for compensation execution
4. Test compensation with async operations
5. Implement manual compensation approval for critical operations

**Recommended Next Tutorial:**
- [Edge Deployment](./edge-deployment.md) - Deploy workflows to hardware

---

## Troubleshooting

**Compensations don't run:**
- Check `workflow.enable_saga_mode()` is called before execution
- Verify `compensate_function` is defined in YAML
- Check workflow status is `FAILED_ROLLED_BACK`

**Compensations run on success:**
- Should never happen - file a bug report if this occurs

**Partial compensation:**
- Check logs to see which compensations failed
- Implement alert system for failed compensations

**Compensation runs twice:**
- Make compensation functions **idempotent**
- Check for duplicate workflow execution

---

## Reference: Workflow Status Values

| Status | Description |
|--------|-------------|
| `ACTIVE` | Workflow executing normally |
| `COMPLETED` | All steps completed successfully |
| `FAILED` | Step failed, no Saga mode (no compensation) |
| `FAILED_ROLLED_BACK` | Step failed, Saga mode enabled, compensations completed |
| `PAUSED` | Workflow paused (human input required) |
