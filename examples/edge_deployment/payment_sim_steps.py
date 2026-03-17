"""
payment_sim_steps.py — Step functions for the PaymentSimulation workflow.

Signature: async def func(state, context, **kw) -> dict
Bound to the workflow YAML via dotted path: payment_sim_steps.<function_name>

Simulates card payments on an edge device:
  - Probes control plane /health — online if reachable, offline if not
  - Online  → gateway approval
  - Offline → floor-limit check → SAF queue or decline

State-mutation note: steps that both need to update state AND jump use direct
mutation (state.field = value) before raising WorkflowJumpDirective.  The jump
handler in workflow.py calls save_workflow(self.to_dict()) which captures the
already-mutated state object.
"""
import logging
import random
import string
import uuid
from decimal import Decimal

from pydantic import BaseModel

from rufus.models import WorkflowJumpDirective

logger = logging.getLogger(__name__)

# Set by edge_device_sim.py before payment_loop() starts
_sync_manager = None


# ─────────────────────────────────────────────────────────────────────────────
# State model
# ─────────────────────────────────────────────────────────────────────────────

class PaymentSimState(BaseModel):
    # Passed in via initial_data
    device_id: str = ""
    cloud_url: str = ""
    db_path: str = ""
    cycle: int = 0

    # Generated in Generate_Payment
    transaction_id: str = ""
    idempotency_key: str = ""

    # Random payment data
    amount: float = 0.0
    amount_cents: int = 0
    currency: str = "USD"
    card_last_four: str = ""
    card_token: str = ""
    merchant_id: str = ""

    # Connectivity / routing
    is_online: bool = True
    floor_limit: float = 1000.0

    # Outcome
    status: str = "PENDING"          # APPROVED_ONLINE / APPROVED_OFFLINE / DECLINED
    authorization_code: str = ""
    stored_for_sync: bool = False
    outcome: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Step functions
# ─────────────────────────────────────────────────────────────────────────────

async def generate_payment(state, context, **kw) -> dict:
    """Step 1: Generate randomised card payment data."""
    amount = round(random.uniform(1.0, 500.0), 2)
    last_four = "".join(random.choices(string.digits, k=4))
    merchant_id = random.choice([
        "merch-001-corner-store",
        "merch-002-fuel-station",
        "merch-003-pharmacy",
        "merch-004-atm-terminal",
        "merch-005-vending-machine",
    ])
    txn_id = str(uuid.uuid4())
    idem_key = f"{txn_id}-{state.cycle}"
    card_token = f"tok_{last_four}_{uuid.uuid4().hex[:8]}"

    logger.info(
        f"[Payment cycle {state.cycle}] Generated txn={txn_id[:8]}... "
        f"amount=${amount:.2f} card=****{last_four} merchant={merchant_id}"
    )

    return {
        "transaction_id": txn_id,
        "idempotency_key": idem_key,
        "amount": amount,
        "amount_cents": int(amount * 100),
        "currency": "USD",
        "card_last_four": last_four,
        "card_token": card_token,
        "merchant_id": merchant_id,
    }


async def check_connectivity(state, context, **kw) -> dict:
    """Step 2: Probe the control plane — go offline if unreachable."""
    import httpx
    is_online = False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{state.cloud_url}/health")
            is_online = resp.status_code == 200
    except Exception:
        is_online = False

    state.is_online = is_online  # mutate so state is persisted with jump
    logger.info(
        f"[Payment cycle {state.cycle}] Connectivity → {'ONLINE' if is_online else 'OFFLINE'}"
    )
    if is_online:
        raise WorkflowJumpDirective("Authorize_Online")
    raise WorkflowJumpDirective("Check_Floor_Limit")


async def authorize_online(state, context, **kw) -> dict:
    """Step 3a (online path): Simulate gateway approval, then jump to Complete_Payment."""
    auth_code = "AUTH-" + uuid.uuid4().hex[:6].upper()
    # Mutate state before jump so changes survive the exception path
    state.status = "APPROVED_ONLINE"
    state.authorization_code = auth_code
    state.outcome = f"APPROVED_ONLINE auth={auth_code}"
    logger.info(
        f"[Payment cycle {state.cycle}] ONLINE APPROVED  "
        f"txn={state.transaction_id[:8]}... auth={auth_code} "
        f"amount=${state.amount:.2f}"
    )
    raise WorkflowJumpDirective("Complete_Payment")


async def check_floor_limit(state, context, **kw) -> dict:
    """Step 4 (offline path): Route by floor-limit."""
    if state.amount <= state.floor_limit:
        raise WorkflowJumpDirective("Approve_Offline")
    raise WorkflowJumpDirective("Decline_Payment")


async def approve_offline(state, context, **kw) -> dict:
    """Step 5a: Approve offline and queue into SyncManager SAF."""
    from rufus_edge.models import SAFTransaction, TransactionStatus

    txn = SAFTransaction(
        transaction_id=state.transaction_id,
        idempotency_key=state.idempotency_key,
        device_id=state.device_id,
        merchant_id=state.merchant_id,
        amount=Decimal(str(state.amount)),
        currency=state.currency,
        card_token=state.card_token,
        card_last_four=state.card_last_four,
        encrypted_payload=b"",   # sim: no real encryption
        encryption_key_id="sim",
        status=TransactionStatus.APPROVED_OFFLINE,
        workflow_id=context.workflow_id,  # FK into workflow_executions
    )

    if _sync_manager is not None:
        await _sync_manager.queue_for_sync(txn)
        logger.info(
            f"[Payment cycle {state.cycle}] OFFLINE APPROVED (floor limit) — "
            f"queued for SAF  txn={state.transaction_id[:8]}... "
            f"amount=${state.amount:.2f} (limit=${state.floor_limit:.2f})"
        )
    else:
        logger.warning(
            f"[Payment cycle {state.cycle}] OFFLINE APPROVED but _sync_manager is None — "
            "SAF queue skipped"
        )

    # Mutate state before jump so changes survive the exception path
    state.status = "APPROVED_OFFLINE"
    state.stored_for_sync = True
    state.outcome = f"APPROVED_OFFLINE queued_saf=True amount=${state.amount:.2f}"
    raise WorkflowJumpDirective("Complete_Payment")


async def decline_payment(state, context, **kw) -> dict:
    """Step 5b: Decline — amount exceeds offline floor limit. automate_next flows to Complete_Payment."""
    logger.info(
        f"[Payment cycle {state.cycle}] DECLINED (offline, exceeds floor limit "
        f"${state.floor_limit:.2f})  txn={state.transaction_id[:8]}... "
        f"amount=${state.amount:.2f}"
    )
    return {
        "status": "DECLINED",
        "outcome": f"DECLINED offline_amount=${state.amount:.2f} floor=${state.floor_limit:.2f}",
    }


async def complete_payment(state, context, **kw) -> dict:
    """Step 6: Log final outcome."""
    logger.info(
        f"[Payment cycle {state.cycle}] ─── COMPLETE ─── "
        f"status={state.status} outcome={state.outcome} "
        f"txn={state.transaction_id[:8]}..."
    )
    return {"outcome": state.outcome or state.status}
