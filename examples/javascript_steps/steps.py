"""Python step functions for JavaScript steps example."""

import uuid
from rufus.models import StepContext
from state_models import OrderState


def validate_order(state: OrderState, context: StepContext) -> dict:
    """Validate order has items and customer."""
    if not state.items:
        raise ValueError("Order must have at least one item")

    if not state.customer_id:
        raise ValueError("Customer ID is required")

    # Mark as validated
    state.validated = True

    return {
        "validated": True,
        "item_count": len(state.items),
        "message": f"Order validated with {len(state.items)} items"
    }


def process_order(state: OrderState, context: StepContext) -> dict:
    """Final order processing."""
    # Generate order ID
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"

    return {
        "processed": True,
        "order_id": order_id,
        "status": "confirmed",
        "message": f"Order {order_id} confirmed for ${state.final_pricing['total']:.2f}"
    }
