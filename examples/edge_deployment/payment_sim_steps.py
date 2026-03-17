"""
payment_sim_steps.py — Step functions for the PaymentSimulation workflow.

Signature: async def func(state, context, **kw) -> dict
Bound to the workflow YAML via dotted path: payment_sim_steps.<function_name>

Simulates card payments on an edge device:
  - Probes control plane /health — online if reachable, offline if not
  - Online  → gateway approval
  - Offline → floor-limit check → SAF queue or decline
  - All paths → Launch_Monitoring (inline TransactionMonitoring sub-workflow)

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
# Set by edge_device_sim.py after agent.start() — used by launch_monitoring
_agent = None


# ─────────────────────────────────────────────────────────────────────────────
# State model
# ─────────────────────────────────────────────────────────────────────────────

class PaymentSimState(BaseModel):
    # Passed in via initial_data
    device_id: str = ""
    cloud_url: str = ""
    db_path: str = ""
    cycle: int = 0

    # Device context
    device_type: str = "pos"         # "pos" or "atm" — set from env via initial_data

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

    # Monitoring (set by launch_monitoring)
    monitoring_result: dict = {}


# ─────────────────────────────────────────────────────────────────────────────
# Step functions
# ─────────────────────────────────────────────────────────────────────────────

async def generate_payment(state, context, **kw) -> dict:
    """Step 1: Generate randomised card payment data (ATM or POS depending on device_type)."""
    last_four = "".join(random.choices(string.digits, k=4))

    if state.device_type == "atm":
        # ATM: fixed denominations, ATM location merchants
        amount = float(random.choice([20, 50, 100, 200, 300, 400, 500, 800]))
        merchant_id = random.choice([
            "atm-loc-001-mall",
            "atm-loc-002-station",
            "atm-loc-003-airport",
            "atm-loc-004-hotel",
            "atm-loc-005-casino",
        ])
    else:
        # POS: continuous range, retail merchants
        amount = round(random.uniform(1.0, 500.0), 2)
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
    raise WorkflowJumpDirective("Launch_Monitoring")


async def check_floor_limit(state, context, **kw) -> dict:
    """Step 4 (offline path): Route by floor-limit.

    First checks if offline mode is enabled.  If it has been disabled via cloud
    config, ALL offline transactions are declined immediately regardless of amount.
    """
    # Check offline-mode feature flag from cloud config
    if _agent and _agent.config_manager and not _agent.config_manager.get_offline_mode():
        logger.info(
            f"[Payment cycle {state.cycle}] DECLINED — offline mode disabled by cloud config  "
            f"txn={state.transaction_id[:8]}... amount=${state.amount:.2f}"
        )
        state.status = "DECLINED_NO_OFFLINE_AUTH"
        state.outcome = "DECLINED_NO_OFFLINE_AUTH offline mode disabled in device config"
        raise WorkflowJumpDirective("Launch_Monitoring")

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
    raise WorkflowJumpDirective("Launch_Monitoring")


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


async def _run_monitoring_inline(agent, payment_state) -> dict:
    """
    Create and run a TransactionMonitoring workflow to completion.

    Runs inline (same event loop) using the edge agent's SyncExecutionProvider.
    Both the PaymentSimulation and TransactionMonitoring workflows appear as
    separate executions in the dashboard.
    """
    from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
    from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

    workflow = await agent.workflow_builder.create_workflow(
        workflow_type="TransactionMonitoring",
        persistence_provider=agent.persistence,
        execution_provider=agent.executor,
        workflow_builder=agent.workflow_builder,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=agent.observer,
        initial_data={
            "device_id": payment_state.device_id,
            "device_type": payment_state.device_type,
            "transaction_id": payment_state.transaction_id,
            "amount": payment_state.amount,
            "floor_limit": payment_state.floor_limit,
            "merchant_id": payment_state.merchant_id,
            "card_token": payment_state.card_token,
            "payment_status": payment_state.status,
        },
        owner_id=payment_state.device_id,
    )

    while workflow.status not in ("COMPLETED", "FAILED", "CANCELLED", "FAILED_ROLLED_BACK"):
        await workflow.next_step(user_input={})

    if hasattr(workflow.state, "model_dump"):
        s = workflow.state.model_dump()
        return {
            "monitoring_workflow_id": workflow.id,
            "risk_level": s.get("risk_level", "LOW"),
            "action": s.get("action", "ALLOW"),
            "ml_risk_score": s.get("ml_risk_score", 0.0),
            "rules_fired": s.get("rules_fired", []),
            "typologies_triggered": s.get("typologies_triggered", []),
            "alert_id": s.get("alert_id", ""),
        }
    return {}


async def launch_monitoring(state, context, **kw) -> dict:
    """
    Run TransactionMonitoring as an inline sub-workflow then continue.

    Creates a separate workflow execution (visible in dashboard) without
    using StartSubWorkflowDirective, which is incompatible with SyncExecutor.
    """
    if _agent is None:
        logger.warning("[Monitoring] Agent not wired — skipping fraud screening")
        return {}

    try:
        result = await _run_monitoring_inline(_agent, state)
        logger.info(
            "[Payment cycle %d] Monitoring complete — risk=%s action=%s score=%.3f",
            state.cycle,
            result.get("risk_level", "LOW"),
            result.get("action", "ALLOW"),
            result.get("ml_risk_score", 0.0),
        )
        return {"monitoring_result": result}
    except Exception as exc:
        logger.warning("[Payment cycle %d] Monitoring failed: %s", state.cycle, exc)
        return {"monitoring_result": {}}


async def complete_payment(state, context, **kw) -> dict:
    """Step 6: Log final outcome."""
    logger.info(
        f"[Payment cycle {state.cycle}] ─── COMPLETE ─── "
        f"status={state.status} outcome={state.outcome} "
        f"txn={state.transaction_id[:8]}..."
    )
    return {"outcome": state.outcome or state.status}
