"""
Step functions for the Order Processing workflow.
Each function receives state and context, and returns a dict of updates.
"""
from rufus.models import StepContext, WorkflowPauseDirective
from state_models import OrderState
import uuid
from datetime import datetime


def initialize_order(state: OrderState, context: StepContext):
    """Initialize the order with ID and timestamps"""
    state.order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    state.created_at = datetime.utcnow().isoformat()
    state.updated_at = state.created_at
    state.order_status = "PENDING"

    # Calculate total
    state.total_amount = sum(item.price * item.quantity for item in state.items)

    print(f"[Initialize] Created order {state.order_id} for ${state.total_amount:.2f}")
    return {
        "order_id": state.order_id,
        "total_amount": state.total_amount,
        "order_status": "PENDING"
    }


def reserve_inventory(state: OrderState, context: StepContext):
    """Simulate reserving inventory for the order"""
    print(f"[Inventory] Reserving {len(state.items)} items for order {state.order_id}")

    # Simulate inventory check
    state.inventory_reserved = True
    state.order_status = "PROCESSING"
    state.updated_at = datetime.utcnow().isoformat()

    return {"inventory_reserved": True, "order_status": "PROCESSING"}


def process_payment(state: OrderState, context: StepContext):
    """Simulate payment processing"""
    print(f"[Payment] Processing ${state.total_amount:.2f} for order {state.order_id}")

    # Simulate payment gateway call
    state.payment_processed = True
    state.payment_transaction_id = f"TXN-{uuid.uuid4().hex[:12].upper()}"
    state.updated_at = datetime.utcnow().isoformat()

    return {
        "payment_processed": True,
        "payment_transaction_id": state.payment_transaction_id
    }


def request_approval(state: OrderState, context: StepContext):
    """Pause workflow for manual approval (high-value orders)"""
    print(f"[Approval] Order {state.order_id} requires manual approval (${state.total_amount:.2f})")

    state.order_status = "PENDING_APPROVAL"
    state.updated_at = datetime.utcnow().isoformat()

    # Pause workflow and wait for human input
    raise WorkflowPauseDirective(result={
        "message": f"Order {state.order_id} requires approval",
        "order_id": state.order_id,
        "total_amount": state.total_amount
    })


def process_approval_decision(state: OrderState, context: StepContext):
    """Process the approval decision from manual review"""
    approval_input = context.validated_input

    if approval_input.approved:
        print(f"[Approval] Order {state.order_id} APPROVED by {approval_input.approver_id}")
        state.order_status = "APPROVED"
    else:
        print(f"[Approval] Order {state.order_id} REJECTED by {approval_input.approver_id}")
        state.order_status = "CANCELLED"

    state.updated_at = datetime.utcnow().isoformat()

    return {"order_status": state.order_status}


def create_shipment(state: OrderState, context: StepContext):
    """Create shipment for the order"""
    print(f"[Shipment] Creating shipment for order {state.order_id}")

    state.shipment_id = f"SHIP-{uuid.uuid4().hex[:8].upper()}"
    state.tracking_number = f"TRK{uuid.uuid4().hex[:12].upper()}"
    state.order_status = "SHIPPED"
    state.updated_at = datetime.utcnow().isoformat()

    return {
        "shipment_id": state.shipment_id,
        "tracking_number": state.tracking_number,
        "order_status": "SHIPPED"
    }


def send_confirmation_email(state: OrderState, context: StepContext):
    """Send confirmation email to customer"""
    print(f"[Email] Sending confirmation to {state.customer_email} for order {state.order_id}")

    # Simulate email sending
    state.updated_at = datetime.utcnow().isoformat()

    return {"email_sent": True}


# Compensation functions for Saga pattern
def compensate_reserve_inventory(state: OrderState, context: StepContext):
    """Rollback inventory reservation"""
    print(f"[Compensation] Releasing inventory for order {state.order_id}")
    state.inventory_reserved = False
    return {"inventory_reserved": False}


def compensate_process_payment(state: OrderState, context: StepContext):
    """Rollback payment (refund)"""
    print(f"[Compensation] Refunding payment {state.payment_transaction_id}")
    state.payment_processed = False
    return {"payment_processed": False, "refund_issued": True}
