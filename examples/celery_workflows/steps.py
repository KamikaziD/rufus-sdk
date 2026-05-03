"""
Synchronous step functions for workflows.

These are simple, fast functions executed immediately (not via Celery).
"""
from ruvon.models import StepContext, StartSubWorkflowDirective
from models.state_models import OrderState, PaymentState, NotificationState
import time


def validate_order(state: OrderState, context: StepContext):
    """Validates order data before processing."""
    print(f"\n{'='*60}")
    print(f"[VALIDATE] Validating order {state.order_id}")
    print(f"[VALIDATE] Customer: {state.customer_email}")
    print(f"[VALIDATE] Amount: ${state.amount:.2f} {state.currency}")
    print(f"{'='*60}\n")

    # Basic validation
    if not state.order_id:
        raise ValueError("Order ID is required")
    if not state.customer_email:
        raise ValueError("Customer email is required")
    if state.amount <= 0:
        raise ValueError("Amount must be positive")

    print("✅ Order validation passed")

    return {"validated": True}


def trigger_notifications(state: OrderState, context: StepContext):
    """Triggers notification sub-workflow."""
    print(f"\n[SUB-WORKFLOW] Triggering notifications for order {state.order_id}")

    # Start sub-workflow for notifications
    raise StartSubWorkflowDirective(
        workflow_type="SendNotifications",
        initial_data={
            "user_email": state.customer_email,
            "user_phone": state.customer_phone,
            "user_device_token": f"device_{state.order_id}",
            "order_id": state.order_id,
            "message": f"Your order {state.order_id} has been processed!"
        }
    )


def mark_order_complete(state: OrderState, context: StepContext):
    """Marks order as complete after all processing."""
    print(f"\n{'='*60}")
    print(f"[COMPLETE] Order {state.order_id} processing complete!")
    print(f"[COMPLETE] Transaction ID: {state.transaction_id}")
    print(f"[COMPLETE] Amount charged: ${state.amount_charged:.2f}")

    # Check sub-workflow results
    if "SendNotifications" in state.sub_workflow_results:
        notifications = state.sub_workflow_results["SendNotifications"]
        print(f"[COMPLETE] Notifications sent:")
        print(f"  - Email: {notifications.get('email_sent', False)}")
        print(f"  - SMS: {notifications.get('sms_sent', False)}")
        print(f"  - Push: {notifications.get('push_sent', False)}")

    print(f"{'='*60}\n")

    return {
        "status": "completed",
        "completed_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }


def verify_payment_checks(state: PaymentState, context: StepContext):
    """Verifies that all payment checks passed."""
    print(f"\n{'='*60}")
    print("[VERIFY] Checking parallel validation results:")
    print(f"  - Credit approved: {state.credit_approved} (score: {state.credit_score})")
    print(f"  - Fraud risk: {state.fraud_risk_level} (score: {state.fraud_score:.3f})")
    print(f"  - Limit approved: {state.limit_approved} (available: ${state.available_limit:.2f})")

    # Check if all validations passed
    if not state.credit_approved:
        raise ValueError(f"Credit check failed: score {state.credit_score} below 700")

    if state.fraud_risk_level == "high":
        raise ValueError(f"Fraud risk too high: {state.fraud_score:.3f}")

    if not state.limit_approved:
        raise ValueError(f"Insufficient limit: ${state.available_limit:.2f} < ${state.amount:.2f}")

    print("✅ All payment checks passed")
    print(f"{'='*60}\n")

    return {"all_checks_passed": True}


def mark_notifications_sent(state: NotificationState, context: StepContext):
    """Marks notifications as sent."""
    print(f"\n{'='*60}")
    print("[NOTIFICATIONS] All notifications sent:")
    print(f"  - Email to {state.user_email}: {state.email_sent}")
    print(f"  - SMS to {state.user_phone}: {state.sms_sent}")
    print(f"  - Push to device: {state.push_sent}")
    print(f"{'='*60}\n")

    return {
        "sent_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "all_sent": state.email_sent and state.sms_sent and state.push_sent
    }
