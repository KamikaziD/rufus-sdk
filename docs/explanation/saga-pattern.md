# Saga Pattern: Distributed Transaction Compensation

The Saga pattern is Rufus's solution to the distributed transaction problem: how do you maintain consistency across multiple independent operations when you can't use a traditional database transaction?

## The Problem

Imagine a booking workflow:

```
1. Reserve flight seat → SUCCESS
2. Reserve hotel room → SUCCESS
3. Charge credit card → FAILURE (card declined)
```

Now you have a problem: the flight and hotel are reserved, but payment failed. In a traditional database, you'd rollback the transaction. But these are external services—they don't support rollback.

**You need to manually undo the flight and hotel reservations.**

This is what the Saga pattern does.

## What is a Saga?

A Saga is a sequence of local transactions where each transaction has a compensating transaction that semantically undoes its effects.

```
Forward Transactions         Compensating Transactions
─────────────────────       ──────────────────────────
Reserve Flight      ←──────  Cancel Flight
Reserve Hotel       ←──────  Release Hotel
Charge Payment      ←──────  Refund Payment (if charged)
```

**Key Insight**: Compensations run in **reverse order** (LIFO - Last In, First Out). This is because later steps may depend on earlier steps.

Example: You can't cancel the flight until you've released the hotel, because both might share the same booking reference.

## How Rufus Implements Sagas

### 1. Define Compensatable Steps

Each step that modifies external state should have a compensation function:

```python
def reserve_flight(state: BookingState, context: StepContext) -> dict:
    """Reserve a flight seat."""
    reservation_id = flight_api.reserve(
        flight_number=state.flight_number,
        passenger=state.passenger_name
    )
    return {"flight_reservation_id": reservation_id}

def cancel_flight(state: BookingState, context: StepContext) -> dict:
    """Compensation: Cancel the flight reservation."""
    if state.flight_reservation_id:
        flight_api.cancel(state.flight_reservation_id)
    return {"flight_reservation_cancelled": True}
```

### 2. Link Steps in YAML

```yaml
steps:
  - name: "Reserve_Flight"
    type: "STANDARD"
    function: "booking.steps.reserve_flight"
    compensate_function: "booking.steps.cancel_flight"

  - name: "Reserve_Hotel"
    type: "STANDARD"
    function: "booking.steps.reserve_hotel"
    compensate_function: "booking.steps.release_hotel"

  - name: "Charge_Payment"
    type: "STANDARD"
    function: "booking.steps.charge_payment"
    compensate_function: "booking.steps.refund_payment"
```

### 3. Enable Saga Mode

```python
workflow = await builder.create_workflow("BookingWorkflow", initial_data)

# Enable saga mode
workflow.enable_saga_mode()

# Now execute workflow
await workflow.next_step(user_input={})  # Reserve_Flight
await workflow.next_step(user_input={})  # Reserve_Hotel
await workflow.next_step(user_input={})  # Charge_Payment (fails)

# Saga automatically triggered:
# 1. Refund_Payment (no-op, payment never charged)
# 2. Release_Hotel (cancels hotel)
# 3. Cancel_Flight (cancels flight)
```

## Saga Execution Flow

### Normal Execution (No Failure)

```
Step 1: Reserve_Flight
  - Executes reserve_flight()
  - Records to saga log: ("Reserve_Flight", "cancel_flight")
  - State: ACTIVE

Step 2: Reserve_Hotel
  - Executes reserve_hotel()
  - Records to saga log: ("Reserve_Hotel", "release_hotel")
  - State: ACTIVE

Step 3: Charge_Payment
  - Executes charge_payment()
  - Records to saga log: ("Charge_Payment", "refund_payment")
  - State: COMPLETED

Saga log: [
  ("Reserve_Flight", "cancel_flight"),
  ("Reserve_Hotel", "release_hotel"),
  ("Charge_Payment", "refund_payment")
]

All steps succeeded, compensations not needed.
```

### Failure with Compensation

```
Step 1: Reserve_Flight
  - Executes reserve_flight()
  - Records to saga log: ("Reserve_Flight", "cancel_flight")
  - State: ACTIVE

Step 2: Reserve_Hotel
  - Executes reserve_hotel()
  - Records to saga log: ("Reserve_Hotel", "release_hotel")
  - State: ACTIVE

Step 3: Charge_Payment
  - Executes charge_payment()
  - FAILS! (card declined)
  - State: Executing compensation...

Compensation (reverse order):
  3. refund_payment() → no-op (payment never charged)
  2. release_hotel() → cancels hotel reservation
  1. cancel_flight() → cancels flight reservation

State: FAILED_ROLLED_BACK
```

## Compensation Guarantees

### Idempotency

Compensations must be **idempotent**—safe to execute multiple times:

```python
def refund_payment(state: BookingState, context: StepContext) -> dict:
    """Compensation: Refund the payment."""
    if not state.transaction_id:
        # No transaction to refund
        return {"refund_status": "not_applicable"}

    # Check if already refunded
    if payment_api.is_refunded(state.transaction_id):
        return {"refund_status": "already_refunded"}

    # Issue refund
    payment_api.refund(state.transaction_id)
    return {"refund_status": "refunded"}
```

**Why**: Worker crashes, retries, or network failures may cause compensation to run multiple times.

### Best Effort

Compensations are **best effort**, not guaranteed to succeed:

```python
def cancel_flight(state: BookingState, context: StepContext) -> dict:
    """Compensation: Cancel the flight reservation."""
    try:
        flight_api.cancel(state.flight_reservation_id)
        return {"flight_cancelled": True}
    except FlightAlreadyDeparted:
        # Can't cancel - flight already departed
        logger.error(f"Cannot cancel flight {state.flight_reservation_id}: already departed")
        return {"flight_cancelled": False, "reason": "already_departed"}
```

**What happens if compensation fails?**
- Rufus logs the failure to audit log
- Continues with remaining compensations
- Final state: `FAILED_ROLLED_BACK` (even if some compensations failed)
- Ops team investigates and manually fixes

### Semantic Rollback

Compensations provide **semantic rollback**, not technical rollback:

**Technical rollback** (database transaction):
- Exact state restoration
- Guaranteed consistency
- All-or-nothing

**Semantic rollback** (Saga):
- Approximate state restoration
- Best-effort consistency
- May leave side effects

Example: Cancelling a flight reservation doesn't undo the airline's system log entry. But semantically, the customer doesn't have a reserved seat.

## Advanced Saga Patterns

### Partial Compensation

Not all steps need compensation:

```yaml
steps:
  - name: "Validate_Input"
    type: "STANDARD"
    function: "steps.validate_input"
    # No compensation - validation has no side effects

  - name: "Reserve_Flight"
    type: "STANDARD"
    function: "steps.reserve_flight"
    compensate_function: "steps.cancel_flight"  # Needs compensation

  - name: "Send_Confirmation_Email"
    type: "STANDARD"
    function: "steps.send_email"
    # No compensation - emails can't be "unsent"
```

**Best Practice**: Only define compensations for steps with reversible external side effects.

### Conditional Compensation

Compensation logic can check state:

```python
def compensate_inventory(state: OrderState, context: StepContext) -> dict:
    """Compensation: Release allocated inventory."""

    # Check if inventory was actually allocated
    if not state.inventory_allocated:
        return {"inventory_released": False, "reason": "not_allocated"}

    # Check if order was already shipped
    if state.order_status == "shipped":
        # Can't release inventory - order already shipped
        logger.warning(f"Cannot release inventory for shipped order {state.order_id}")
        return {"inventory_released": False, "reason": "already_shipped"}

    # Release inventory
    inventory_api.release(state.order_id, state.items)
    return {"inventory_released": True}
```

### Nested Sagas (Sub-Workflows)

Parent workflow with saga spawns child workflow with saga:

```python
# Parent: Order Processing (saga enabled)
steps:
  - name: "Allocate_Inventory"
    # Spawns InventoryAllocation sub-workflow (also saga-enabled)

  - name: "Charge_Payment"
    compensate_function: "refund_payment"

# If payment fails:
# 1. Parent saga triggers
# 2. Compensation for "Allocate_Inventory" step
# 3. This triggers child workflow's saga
# 4. Child releases inventory locks
# 5. Parent continues with remaining compensations
```

**Behavior**: Child saga runs first (unwinding), then parent saga continues.

## Saga vs Traditional Transactions

| Feature | Database Transaction | Saga Pattern |
|---------|---------------------|--------------|
| **Scope** | Single database | Multiple services |
| **Consistency** | ACID guaranteed | Eventual consistency |
| **Isolation** | Locks prevent concurrent access | No isolation (concurrent sagas possible) |
| **Duration** | Milliseconds (held locks) | Minutes to hours |
| **Rollback** | Exact state restoration | Semantic undo |
| **Failure Handling** | Automatic rollback | Manual compensation |
| **Complexity** | Low (handled by DB) | High (manual design) |

**When to use Sagas**:
- Distributed systems with multiple services
- Long-running workflows (hours/days)
- External APIs (payment gateways, booking systems)
- Microservices architecture

**When to use DB transactions**:
- Single database operations
- Short-lived operations (< 1 second)
- Need strong consistency guarantees

## Saga Logging and Debugging

### Saga Log Structure

```python
workflow.saga_log = [
    {
        "step_name": "Reserve_Flight",
        "compensation_function": "cancel_flight",
        "executed_at": "2026-02-13T10:15:00Z",
        "result": {"flight_reservation_id": "FL-12345"}
    },
    {
        "step_name": "Reserve_Hotel",
        "compensation_function": "release_hotel",
        "executed_at": "2026-02-13T10:16:00Z",
        "result": {"hotel_reservation_id": "HTL-67890"}
    }
]
```

### Audit Trail

PostgreSQL backend logs compensation execution:

```sql
SELECT step_name, event_type, event_data, created_at
FROM workflow_audit_log
WHERE workflow_id = '550e8400-...'
  AND event_type IN ('STEP_EXECUTED', 'COMPENSATION_EXECUTED')
ORDER BY created_at ASC;
```

Example output:
```
step_name          | event_type            | created_at
-------------------|-----------------------|-------------------------
Reserve_Flight     | STEP_EXECUTED         | 2026-02-13 10:15:00
Reserve_Hotel      | STEP_EXECUTED         | 2026-02-13 10:16:00
Charge_Payment     | STEP_FAILED           | 2026-02-13 10:17:00
Refund_Payment     | COMPENSATION_EXECUTED | 2026-02-13 10:17:01
Release_Hotel      | COMPENSATION_EXECUTED | 2026-02-13 10:17:02
Cancel_Flight      | COMPENSATION_EXECUTED | 2026-02-13 10:17:03
```

### Compensation Failures

If a compensation fails:

```sql
SELECT step_name, event_data->'error' AS error_message
FROM workflow_audit_log
WHERE workflow_id = '550e8400-...'
  AND event_type = 'COMPENSATION_FAILED';
```

**Manual Intervention**: Ops team reviews failed compensations and fixes manually (e.g., call hotel to cancel reservation).

## Saga Design Principles

### 1. Pivot Transaction

The **pivot transaction** is the point of no return—after this, compensation is no longer an option:

```yaml
steps:
  - name: "Reserve_Flight"
    compensate_function: "cancel_flight"

  - name: "Charge_Payment"
    compensate_function: "refund_payment"

  - name: "Issue_Ticket"  # ← Pivot transaction
    # No compensation - tickets can't be unissued

  - name: "Send_Confirmation"
    # After pivot, no compensations
```

**Design Principle**: Put the pivot transaction as late as possible, after all compensatable steps.

### 2. Compensating Actions vs Compensating Transactions

**Compensating Action**: Undo one step
```python
def cancel_flight(state, context):
    flight_api.cancel(state.flight_reservation_id)
```

**Compensating Transaction**: Undo multiple related steps
```python
def cancel_booking(state, context):
    # Undo multiple steps atomically
    flight_api.cancel(state.flight_reservation_id)
    hotel_api.cancel(state.hotel_reservation_id)
    car_api.cancel(state.car_reservation_id)
```

**Recommendation**: Use compensating actions (one per step) for granular control.

### 3. Timeout Handling

Long-running compensations should have timeouts:

```python
def cancel_flight(state: BookingState, context: StepContext) -> dict:
    """Compensation with timeout."""
    try:
        # 30-second timeout
        flight_api.cancel(state.flight_reservation_id, timeout=30)
        return {"flight_cancelled": True}
    except TimeoutError:
        logger.error(f"Compensation timeout for flight {state.flight_reservation_id}")
        # Log for manual retry
        return {"flight_cancelled": False, "reason": "timeout"}
```

## Common Pitfalls

### Pitfall 1: Non-Idempotent Compensations

```python
# ❌ Bad: Assumes refund hasn't happened
def refund_payment(state, context):
    payment_api.refund(state.transaction_id)  # May fail if already refunded

# ✅ Good: Checks first
def refund_payment(state, context):
    if payment_api.is_refunded(state.transaction_id):
        return {"already_refunded": True}
    payment_api.refund(state.transaction_id)
    return {"refunded": True}
```

### Pitfall 2: Assuming All Compensations Succeed

```python
# ❌ Bad: Assumes compensation always works
def cancel_hotel(state, context):
    hotel_api.cancel(state.hotel_reservation_id)  # May fail!

# ✅ Good: Handles failure
def cancel_hotel(state, context):
    try:
        hotel_api.cancel(state.hotel_reservation_id)
        return {"hotel_cancelled": True}
    except HotelCancellationFailed as e:
        logger.error(f"Failed to cancel hotel: {e}")
        # Alert ops team for manual intervention
        send_alert("hotel_cancellation_failed", state.hotel_reservation_id)
        return {"hotel_cancelled": False, "error": str(e)}
```

### Pitfall 3: Forgetting to Enable Saga Mode

```python
# ❌ Bad: Define compensations but don't enable saga
workflow = await builder.create_workflow("BookingWorkflow", data)
# If step fails, compensations won't run!

# ✅ Good: Enable saga mode
workflow = await builder.create_workflow("BookingWorkflow", data)
workflow.enable_saga_mode()  # Now compensations will run on failure
```

## What's Next

Now that you understand the Saga pattern:
- [Workflow Lifecycle](workflow-lifecycle.md) - How FAILED_ROLLED_BACK state works
- [Sub-Workflows](sub-workflows.md) - Nested sagas in parent-child workflows
- [Parallel Execution](parallel-execution.md) - Compensating parallel tasks
