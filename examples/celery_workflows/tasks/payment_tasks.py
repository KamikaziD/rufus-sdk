"""
Payment processing tasks.

These are async tasks executed by Celery workers.
"""
import time
import random
from ruvon.celery_app import celery_app


@celery_app.task
def process_payment_task(state: dict, workflow_id: str):
    """
    Simulates async payment processing.

    In production, this would call a payment gateway API.
    """
    print(f"[PAYMENT] Processing payment for workflow {workflow_id}")
    print(f"[PAYMENT] Amount: ${state.get('amount', 0):.2f}")

    # Simulate payment processing delay (3-5 seconds)
    processing_time = random.uniform(3, 5)
    time.sleep(processing_time)

    # Generate transaction ID
    transaction_id = f"tx_{workflow_id[:8]}_{int(time.time())}"

    print(f"[PAYMENT] Payment processed: {transaction_id}")

    return {
        "transaction_id": transaction_id,
        "payment_status": "approved",
        "amount_charged": state.get("amount", 0),
        "processing_time_seconds": processing_time
    }


@celery_app.task
def send_receipt_task(state: dict, workflow_id: str):
    """
    Sends payment receipt to customer.

    In production, this would send an email via SendGrid, SES, etc.
    """
    print(f"[RECEIPT] Sending receipt for transaction {state.get('transaction_id', 'unknown')}")

    customer_email = state.get("customer_email", "unknown@example.com")
    amount = state.get("amount_charged", 0)

    # Simulate email sending delay
    time.sleep(2)

    print(f"[RECEIPT] Receipt sent to {customer_email}")
    print(f"[RECEIPT] Amount: ${amount:.2f}")

    return {
        "receipt_sent": True,
        "receipt_email": customer_email,
        "receipt_sent_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }


@celery_app.task
def charge_payment_task(state: dict, workflow_id: str):
    """
    Charges the payment after all checks pass.

    This is the final payment step after credit/fraud/limit checks.
    """
    print(f"[CHARGE] Charging payment for workflow {workflow_id}")

    amount = state.get("amount", 0)
    card_number = state.get("card_number", "****")

    # Mask card number for display
    masked_card = f"****-****-****-{card_number[-4:]}" if len(card_number) >= 4 else "****"

    # Simulate payment gateway API call
    time.sleep(3)

    transaction_id = f"tx_{workflow_id[:8]}_{int(time.time())}"

    print(f"[CHARGE] Charged ${amount:.2f} to card {masked_card}")
    print(f"[CHARGE] Transaction ID: {transaction_id}")

    return {
        "transaction_id": transaction_id,
        "payment_status": "charged",
        "amount_charged": amount,
        "charged_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
