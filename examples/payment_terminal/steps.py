"""
Payment workflow step functions.

These functions implement the business logic for payment processing
including online authorization, offline approval, and compensation.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any
import uuid

from ruvon.models import StepContext, WorkflowJumpDirective

logger = logging.getLogger(__name__)

# Simulated floor limit (would come from config in production)
DEFAULT_FLOOR_LIMIT = Decimal("25.00")


def validate_payment(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Validate payment request data.

    Checks:
    - Card token is present
    - Amount is positive
    - Merchant ID is present
    """
    logger.info(f"Validating payment: amount={state.amount}, merchant={state.merchant_id}")

    errors = []

    if not state.card_token:
        errors.append("Card token is required")

    if not state.amount or state.amount <= 0:
        errors.append("Amount must be positive")

    if not state.merchant_id:
        errors.append("Merchant ID is required")

    if errors:
        state.status = "failed"
        state.error_message = "; ".join(errors)
        raise ValueError(f"Validation failed: {state.error_message}")

    # Calculate amount in cents for gateway
    state.amount_cents = int(state.amount * 100)

    logger.info(f"Payment validated: {state.transaction_id}")
    return {"validated": True, "amount_cents": state.amount_cents}


def check_connectivity(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Check network connectivity to determine online/offline path.

    In production, this would ping the payment gateway.
    For demo, uses the is_online flag from state.
    """
    # In production, actually test connectivity:
    # try:
    #     response = httpx.get("https://gateway.example.com/health", timeout=5)
    #     state.is_online = response.status_code == 200
    # except:
    #     state.is_online = False

    logger.info(f"Connectivity check: is_online={state.is_online}")

    # Return decision for routing
    if state.is_online:
        raise WorkflowJumpDirective(target_step_name="Online_Authorization")
    else:
        raise WorkflowJumpDirective(target_step_name="Check_Floor_Limit")


def authorize_online(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Send authorization request to payment gateway.

    In production, this would make an HTTP call to the gateway.
    For demo, simulates a successful authorization.
    """
    logger.info(f"Authorizing online: {state.transaction_id}, amount={state.amount}")

    # Simulate gateway call
    # In production:
    # response = await httpx.post(
    #     "https://gateway.example.com/authorize",
    #     json={
    #         "amount_cents": state.amount_cents,
    #         "card_token": state.card_token,
    #         "merchant_id": state.merchant_id,
    #         "idempotency_key": state.idempotency_key,
    #     }
    # )

    # Simulate successful authorization
    auth_code = f"AUTH{uuid.uuid4().hex[:8].upper()}"

    state.authorization_code = auth_code
    state.status = "approved"
    state.gateway_response = {
        "auth_code": auth_code,
        "response_code": "00",
        "response_text": "Approved",
    }

    logger.info(f"Authorization approved: {auth_code}")

    # Auto-advance to completion
    raise WorkflowJumpDirective(target_step_name="Complete_Transaction")


def void_authorization(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Compensation function: Void an authorization.

    Called if a later step fails and we need to rollback.
    """
    logger.warning(f"Voiding authorization: {state.authorization_code}")

    if state.authorization_code:
        # In production, call gateway to void
        # response = await httpx.post(
        #     "https://gateway.example.com/void",
        #     json={"auth_code": state.authorization_code}
        # )

        state.status = "voided"
        state.gateway_response = {
            "void_successful": True,
            "voided_at": datetime.utcnow().isoformat(),
        }

    return {"voided": True, "auth_code": state.authorization_code}


def check_floor_limit(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Check if transaction amount is under floor limit for offline approval.
    """
    floor_limit = DEFAULT_FLOOR_LIMIT
    state.floor_limit_checked = True

    logger.info(f"Checking floor limit: amount={state.amount}, limit={floor_limit}")

    if state.amount <= floor_limit:
        raise WorkflowJumpDirective(target_step_name="Offline_Approval")
    else:
        raise WorkflowJumpDirective(target_step_name="Decline_Offline")


def approve_offline(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Approve transaction offline (Store-and-Forward).

    The transaction will be synced to the cloud when connectivity is restored.
    """
    logger.info(f"Approving offline: {state.transaction_id}, amount={state.amount}")

    # Generate offline approval code
    offline_code = f"OFF{uuid.uuid4().hex[:8].upper()}"

    state.authorization_code = offline_code
    state.status = "approved_offline"
    state.stored_for_sync = True
    state.offline_approved_at = datetime.utcnow()

    logger.info(f"Offline approval granted: {offline_code}")

    # Auto-advance to completion
    raise WorkflowJumpDirective(target_step_name="Complete_Transaction")


def decline_offline(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Decline transaction - amount exceeds offline floor limit.
    """
    logger.info(f"Declining offline: {state.transaction_id}, amount={state.amount}")

    state.status = "declined"
    state.decline_reason = f"Amount ${state.amount} exceeds offline floor limit"

    return {
        "declined": True,
        "reason": state.decline_reason,
    }


def complete_transaction(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Finalize the transaction and return result.
    """
    state.completed_at = datetime.utcnow()

    logger.info(
        f"Transaction completed: {state.transaction_id}, "
        f"status={state.status}, auth_code={state.authorization_code}"
    )

    return {
        "transaction_id": state.transaction_id,
        "status": state.status,
        "authorization_code": state.authorization_code,
        "amount": str(state.amount),
        "completed_at": state.completed_at.isoformat() if state.completed_at else None,
        "requires_sync": state.stored_for_sync,
    }
