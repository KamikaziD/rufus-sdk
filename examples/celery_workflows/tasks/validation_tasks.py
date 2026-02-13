"""
Validation tasks for credit check, fraud check, etc.

These tasks are designed to run in parallel.
"""
import time
import random
from rufus.celery_app import celery_app


@celery_app.task
def validate_card_task(state: dict, workflow_id: str):
    """
    Validates credit card format and type.

    This is a sync task that runs before parallel checks.
    """
    print(f"[VALIDATE] Validating credit card")

    card_number = state.get("card_number", "")

    # Simple card type detection
    if card_number.startswith("4"):
        card_type = "Visa"
    elif card_number.startswith(("51", "52", "53", "54", "55")):
        card_type = "Mastercard"
    elif card_number.startswith(("34", "37")):
        card_type = "American Express"
    else:
        card_type = "Unknown"

    # Basic validation (Luhn algorithm would go here in production)
    card_valid = len(card_number) >= 13 and card_number.isdigit()

    time.sleep(1)

    print(f"[VALIDATE] Card type: {card_type}")
    print(f"[VALIDATE] Valid: {card_valid}")

    return {
        "card_valid": card_valid,
        "card_type": card_type
    }


@celery_app.task
def check_credit_task(state: dict, workflow_id: str):
    """
    Checks customer credit score and approval.

    This runs in parallel with fraud and limit checks.
    """
    print(f"[CREDIT] Checking credit score")

    # Simulate credit bureau API call
    time.sleep(random.uniform(2, 4))

    # Generate random credit score (650-850)
    credit_score = random.randint(650, 850)
    credit_approved = credit_score >= 700

    print(f"[CREDIT] Credit score: {credit_score}")
    print(f"[CREDIT] Approved: {credit_approved}")

    return {
        "credit_score": credit_score,
        "credit_approved": credit_approved
    }


@celery_app.task
def check_fraud_task(state: dict, workflow_id: str):
    """
    Checks for fraudulent activity.

    This runs in parallel with credit and limit checks.
    """
    print(f"[FRAUD] Running fraud detection")

    amount = state.get("amount", 0)

    # Simulate fraud detection API call
    time.sleep(random.uniform(2, 4))

    # Generate random fraud score (0.0-1.0, lower is better)
    fraud_score = random.uniform(0.0, 0.3)

    if fraud_score < 0.1:
        fraud_risk_level = "low"
    elif fraud_score < 0.2:
        fraud_risk_level = "medium"
    else:
        fraud_risk_level = "high"

    print(f"[FRAUD] Fraud score: {fraud_score:.3f}")
    print(f"[FRAUD] Risk level: {fraud_risk_level}")

    return {
        "fraud_score": fraud_score,
        "fraud_risk_level": fraud_risk_level
    }


@celery_app.task
def check_limit_task(state: dict, workflow_id: str):
    """
    Checks available credit limit.

    This runs in parallel with credit and fraud checks.
    """
    print(f"[LIMIT] Checking available credit limit")

    amount = state.get("amount", 0)

    # Simulate credit limit API call
    time.sleep(random.uniform(2, 4))

    # Generate random available limit ($1,000-$50,000)
    available_limit = random.uniform(1000, 50000)
    limit_approved = available_limit >= amount

    print(f"[LIMIT] Available limit: ${available_limit:.2f}")
    print(f"[LIMIT] Requested amount: ${amount:.2f}")
    print(f"[LIMIT] Approved: {limit_approved}")

    return {
        "available_limit": available_limit,
        "limit_approved": limit_approved
    }
