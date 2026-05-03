# How to use saga mode for compensation

This guide covers implementing transaction compensation using the Saga pattern.

## Overview

Saga mode enables automatic rollback when workflows fail. Each step can define a compensation function that reverses its effects. On failure, compensation functions execute in reverse order.

## Basic saga workflow

### Enable saga mode

```python
from ruvon.builder import WorkflowBuilder

# Create workflow
workflow = await builder.create_workflow(
    workflow_type="OrderProcessing",
    initial_data={"order_id": "ORD-001", "amount": 99.99}
)

# Enable saga mode
workflow.enable_saga_mode()

# Execute workflow
try:
    await workflow.next_step()
except Exception as e:
    # If any step fails, compensation runs automatically
    print(f"Workflow failed and rolled back: {e}")
```

### Define compensatable steps

```python
from ruvon.models import StepContext
from my_app.state_models import OrderState

def charge_payment(state: OrderState, context: StepContext) -> dict:
    """Charge customer payment."""

    # Execute charge
    transaction_id = payment_service.charge(
        customer_id=state.customer_id,
        amount=state.amount
    )

    state.transaction_id = transaction_id
    state.payment_status = "charged"

    return {
        "transaction_id": transaction_id,
        "payment_status": "charged"
    }

def refund_payment(state: OrderState, context: StepContext) -> dict:
    """Compensate for charge_payment - issue refund."""

    if state.transaction_id:
        # Reverse the charge
        refund_id = payment_service.refund(state.transaction_id)

        state.refund_id = refund_id
        state.payment_status = "refunded"

        return {
            "refund_id": refund_id,
            "payment_status": "refunded"
        }

    return {"payment_status": "no_charge_to_refund"}
```

### Configure in YAML

```yaml
workflow_type: "OrderProcessing"
initial_state_model: "my_app.state_models.OrderState"

steps:
  - name: "Reserve_Inventory"
    type: "STANDARD"
    function: "my_app.steps.reserve_inventory"
    compensate_function: "my_app.steps.release_inventory"
    automate_next: true

  - name: "Charge_Payment"
    type: "STANDARD"
    function: "my_app.steps.charge_payment"
    compensate_function: "my_app.steps.refund_payment"
    automate_next: true

  - name: "Ship_Order"
    type: "STANDARD"
    function: "my_app.steps.ship_order"
    compensate_function: "my_app.steps.cancel_shipment"
    automate_next: true

  - name: "Send_Confirmation"
    type: "STANDARD"
    function: "my_app.steps.send_confirmation"
    # No compensation - email already sent
```

## How compensation works

### Execution order

**Normal execution (success):**
```
1. Reserve_Inventory → success
2. Charge_Payment → success
3. Ship_Order → success
4. Send_Confirmation → success
Status: COMPLETED
```

**Failed execution with compensation:**
```
1. Reserve_Inventory → success
2. Charge_Payment → success
3. Ship_Order → FAILURE

Compensation (reverse order):
3. (Ship_Order compensation skipped - never completed)
2. Refund_Payment → success
1. Release_Inventory → success

Status: FAILED_ROLLED_BACK
```

### Workflow status

After saga compensation:
- Status: `FAILED_ROLLED_BACK`
- All completed steps compensated in reverse order
- State contains compensation results
- Audit log records compensation steps

## Multi-step saga example

Complete e-commerce order processing:

```python
# State model
from pydantic import BaseModel
from typing import Optional

class OrderState(BaseModel):
    order_id: str
    customer_id: str
    items: list
    amount: float

    # Populated during execution
    inventory_reserved: bool = False
    reservation_id: Optional[str] = None
    transaction_id: Optional[str] = None
    shipping_id: Optional[str] = None

# Forward steps
def reserve_inventory(state: OrderState, context: StepContext) -> dict:
    """Reserve inventory for order items."""
    reservation_id = inventory_service.reserve(state.items)
    state.inventory_reserved = True
    state.reservation_id = reservation_id
    return {"reservation_id": reservation_id}

def charge_payment(state: OrderState, context: StepContext) -> dict:
    """Charge customer payment."""
    transaction_id = payment_service.charge(state.customer_id, state.amount)
    state.transaction_id = transaction_id
    return {"transaction_id": transaction_id}

def ship_order(state: OrderState, context: StepContext) -> dict:
    """Ship order to customer."""
    shipping_id = shipping_service.ship(state.order_id, state.items)
    state.shipping_id = shipping_id
    return {"shipping_id": shipping_id}

# Compensation steps
def release_inventory(state: OrderState, context: StepContext) -> dict:
    """Release reserved inventory."""
    if state.reservation_id:
        inventory_service.release(state.reservation_id)
        state.inventory_reserved = False
    return {"inventory_released": True}

def refund_payment(state: OrderState, context: StepContext) -> dict:
    """Refund payment."""
    if state.transaction_id:
        refund_id = payment_service.refund(state.transaction_id)
        return {"refund_id": refund_id}
    return {"no_refund_needed": True}

def cancel_shipment(state: OrderState, context: StepContext) -> dict:
    """Cancel shipment."""
    if state.shipping_id:
        shipping_service.cancel(state.shipping_id)
        return {"shipment_cancelled": True}
    return {"no_shipment_to_cancel": True}
```

```yaml
# YAML configuration
steps:
  - name: "Reserve_Inventory"
    type: "STANDARD"
    function: "my_app.steps.reserve_inventory"
    compensate_function: "my_app.steps.release_inventory"
    automate_next: true

  - name: "Charge_Payment"
    type: "STANDARD"
    function: "my_app.steps.charge_payment"
    compensate_function: "my_app.steps.refund_payment"
    automate_next: true

  - name: "Ship_Order"
    type: "STANDARD"
    function: "my_app.steps.ship_order"
    compensate_function: "my_app.steps.cancel_shipment"
```

## Conditional compensation

Only compensate if action was taken:

```python
def refund_payment(state: OrderState, context: StepContext) -> dict:
    """Compensate payment charge."""

    # Check if payment was actually charged
    if not state.transaction_id:
        return {"no_charge_to_refund": True}

    # Check if already refunded
    if state.payment_status == "refunded":
        return {"already_refunded": True}

    # Execute refund
    try:
        refund_id = payment_service.refund(state.transaction_id)
        state.payment_status = "refunded"
        state.refund_id = refund_id

        return {
            "refund_id": refund_id,
            "payment_status": "refunded"
        }

    except AlreadyRefundedException:
        # Idempotent - safe to call multiple times
        return {"already_refunded": True}
```

## Idempotent compensation

Design compensation for safe retries:

```python
def cancel_shipment(state: OrderState, context: StepContext) -> dict:
    """Idempotent shipment cancellation."""

    if not state.shipping_id:
        return {"no_shipment_to_cancel": True}

    try:
        # Call external service
        shipping_service.cancel(state.shipping_id)
        state.shipping_status = "cancelled"

        return {"shipment_cancelled": True}

    except ShipmentNotFoundException:
        # Already cancelled or never created
        state.shipping_status = "cancelled"
        return {"shipment_already_cancelled": True}

    except ShipmentAlreadyCancelledException:
        # Idempotent - safe to retry
        state.shipping_status = "cancelled"
        return {"shipment_already_cancelled": True}
```

## Partial compensation

Handle compensation failures:

```python
def refund_payment(state: OrderState, context: StepContext) -> dict:
    """Attempt refund with error handling."""

    try:
        refund_id = payment_service.refund(state.transaction_id)
        return {"refund_id": refund_id}

    except RefundException as e:
        # Log compensation failure
        print(f"Refund failed: {e}")

        # Store error for manual resolution
        state.refund_error = str(e)
        state.requires_manual_refund = True

        # Don't raise - allow other compensations to run
        return {
            "refund_failed": True,
            "error": str(e)
        }
```

## Testing saga workflows

```python
import pytest
from ruvon.testing.harness import TestHarness
from unittest.mock import Mock, patch

@pytest.mark.asyncio
async def test_saga_compensation():
    """Test saga compensation on failure."""

    harness = TestHarness()

    # Start workflow
    workflow = await harness.start_workflow(
        workflow_type="OrderProcessing",
        initial_data={
            "order_id": "ORD-001",
            "customer_id": "CUST-123",
            "amount": 99.99
        }
    )

    # Enable saga
    workflow.enable_saga_mode()

    # Mock shipping service to fail
    with patch('my_app.services.shipping_service.ship') as mock_ship:
        mock_ship.side_effect = Exception("Shipping unavailable")

        # Execute workflow - should fail and compensate
        try:
            await harness.next_step(workflow.id)
        except Exception:
            pass

        # Verify compensation ran
        assert workflow.status == "FAILED_ROLLED_BACK"
        assert workflow.state.inventory_reserved == False
        assert workflow.state.refund_id is not None

@pytest.mark.asyncio
async def test_saga_success():
    """Test saga with successful execution."""

    harness = TestHarness()

    workflow = await harness.start_workflow(
        workflow_type="OrderProcessing",
        initial_data={"order_id": "ORD-002"}
    )

    workflow.enable_saga_mode()

    # Execute successfully
    await harness.next_step(workflow.id)

    # No compensation should run
    assert workflow.status == "COMPLETED"
    assert workflow.state.inventory_reserved == True
    assert workflow.state.transaction_id is not None
```

## Audit logging

Track compensation in audit logs:

```python
# Query compensation events
from ruvon.implementations.persistence.postgres import PostgresPersistenceProvider

persistence = PostgresPersistenceProvider(db_url)
await persistence.initialize()

audit_logs = await persistence.get_audit_log(workflow_id)

for log in audit_logs:
    if log['event_type'] == 'COMPENSATION_EXECUTED':
        print(f"Compensated step: {log['step_name']}")
        print(f"Compensation result: {log['result']}")
```

## Use cases

### Financial transactions

```yaml
# ATM withdrawal with saga
steps:
  - name: "Verify_PIN"
    type: "STANDARD"
    function: "atm.steps.verify_pin"

  - name: "Reserve_Cash"
    type: "STANDARD"
    function: "atm.steps.reserve_cash"
    compensate_function: "atm.steps.release_cash"

  - name: "Debit_Account"
    type: "STANDARD"
    function: "atm.steps.debit_account"
    compensate_function: "atm.steps.credit_account"

  - name: "Dispense_Cash"
    type: "STANDARD"
    function: "atm.steps.dispense_cash"
    # No compensation - cash already dispensed
```

### Booking systems

```yaml
# Hotel + flight booking with saga
steps:
  - name: "Book_Flight"
    type: "STANDARD"
    function: "booking.steps.book_flight"
    compensate_function: "booking.steps.cancel_flight"

  - name: "Book_Hotel"
    type: "STANDARD"
    function: "booking.steps.book_hotel"
    compensate_function: "booking.steps.cancel_hotel"

  - name: "Book_Car_Rental"
    type: "STANDARD"
    function: "booking.steps.book_car"
    compensate_function: "booking.steps.cancel_car"
```

### Microservices transactions

```yaml
# Distributed transaction across services
steps:
  - name: "Create_Order"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://order-service/orders"
    compensate_function: "compensations.delete_order"

  - name: "Reserve_Inventory"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://inventory-service/reserve"
    compensate_function: "compensations.release_inventory"

  - name: "Charge_Payment"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://payment-service/charge"
    compensate_function: "compensations.refund_payment"
```

## Best practices

1. **Design idempotent compensations** - Safe to retry if compensation fails
2. **Check state before compensating** - Only reverse actions that were completed
3. **Log compensation details** - Audit trail for debugging
4. **Handle compensation failures** - Don't fail entire rollback if one step fails
5. **Test compensation paths** - Verify rollback works correctly
6. **Use external transaction IDs** - Store IDs needed for compensation
7. **Document compensation logic** - Explain what each compensation does
8. **Consider time windows** - Some actions may not be reversible after time passes

## Limitations

**Irreversible actions:**
- Sending emails (can't unsend)
- External notifications (can't unnotify)
- Physical actions (can't un-dispense cash)

**Workarounds:**
- Send "cancellation" email instead of "unsending"
- Mark notifications as cancelled in system
- Track physical state separately

## Next steps

- [Add decision steps](decision-steps.md)
- [Implement human-in-the-loop](human-in-loop.md)
- [Deploy to production](deployment.md)

## See also

- [Create workflow guide](create-workflow.md)
- [Testing guide](testing.md)
- CLAUDE.md "Saga Pattern (Compensation)" section
- USAGE_GUIDE.md section 9.5 for saga patterns
