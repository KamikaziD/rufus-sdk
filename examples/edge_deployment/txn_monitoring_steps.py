"""
txn_monitoring_steps.py — Tazama-inspired rule + typology + ML fraud screening.

TransactionMonitoring sub-workflow for POS and ATM devices.

Pipeline:
  1. Extract_Features  — normalise [0,1] feature vector from transaction data
  2. Route_By_Type     — DECISION: jump to POS_Rules or ATM_Rules
  3. POS_Rules         — 5 POS-specific rules; jumps to Score_With_Wasm
  4. ATM_Rules         — 5 ATM-specific rules; automate_next → Score_With_Wasm
  5. Score_With_Wasm   — Rust logistic regression via Wasmtime (Python fallback)
  6. Apply_Typologies  — map rule combos to named fraud patterns
  7. Monitoring_Verdict— DECISION: route HIGH/CRITICAL to Flag_Transaction
  8. Flag_Transaction  — create alert, finalise risk_level + action

Velocity tracking uses a module-level dict (keyed by card_token). Works correctly
with SyncExecutor (same process) — resets on container restart, intentional for demo.
"""

import hashlib
import logging
import math
import os
import time
import uuid
from collections import defaultdict

from pydantic import BaseModel

from rufus.models import WorkflowJumpDirective

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Velocity tracker  (card_token → [unix_timestamp, ...])
# ─────────────────────────────────────────────────────────────────────────────

_velocity_tracker: dict = defaultdict(list)

# ─────────────────────────────────────────────────────────────────────────────
# Pending fraud review decisions  (alert_id → {decision, reviewer_notes})
# Written by edge_device_sim._handle_resume_fraud_review() via cloud command.
# ─────────────────────────────────────────────────────────────────────────────

_pending_fraud_decisions: dict = {}


def _get_velocity(card_token: str, window_sec: int) -> int:
    """Return the number of transactions for *card_token* within *window_sec*.

    Also records the current transaction (appends now).
    Purges entries older than max(window_sec, 3600) to bound memory growth.
    """
    now = time.time()
    timestamps = _velocity_tracker[card_token]
    timestamps[:] = [t for t in timestamps if now - t < max(window_sec, 3600)]
    timestamps.append(now)
    return sum(1 for t in timestamps if now - t < window_sec)


# ─────────────────────────────────────────────────────────────────────────────
# Known merchant sets (demo seed data)
# ─────────────────────────────────────────────────────────────────────────────

_KNOWN_POS_MERCHANTS = {
    "merch-001-corner-store",
    "merch-002-fuel-station",
    "merch-003-pharmacy",
}

_KNOWN_ATM_LOCATIONS = {
    "atm-loc-001-mall",
    "atm-loc-002-station",
    "atm-loc-003-airport",
}

# ─────────────────────────────────────────────────────────────────────────────
# Typology catalogue
# ─────────────────────────────────────────────────────────────────────────────

_TYPOLOGIES: dict[str, set] = {
    # POS typologies
    "card_testing":                {"pos_r001_velocity", "pos_r003_card_testing"},
    "micro_structuring_pos":       {"pos_r002_micro_struct", "pos_r001_velocity"},
    "velocity_fraud":              {"pos_r001_velocity", "pos_r005_amount_spike"},
    "unknown_merchant":            {"pos_r004_unknown_merchant"},
    "unknown_merchant_large_txn":  {"pos_r004_unknown_merchant", "pos_r005_amount_spike"},
    "unknown_merchant_velocity":   {"pos_r004_unknown_merchant", "pos_r001_velocity"},
    # ATM typologies
    "cash_structuring_atm":        {"atm_r003_structuring", "atm_r004_velocity"},
    "nighttime_account_raid":      {"atm_r002_after_hours", "atm_r001_large_cash"},
    "atm_velocity_fraud":          {"atm_r004_velocity", "atm_r005_large_daily"},
    "nighttime_structuring":       {"atm_r002_after_hours", "atm_r003_structuring"},
    "unknown_atm_location":        {"atm_r006_unknown_location"},
    "unknown_atm_large_cash":      {"atm_r006_unknown_location", "atm_r001_large_cash"},
    "unknown_atm_velocity":        {"atm_r006_unknown_location", "atm_r004_velocity"},
}


# ─────────────────────────────────────────────────────────────────────────────
# State model
# ─────────────────────────────────────────────────────────────────────────────

class TransactionMonitoringState(BaseModel):
    # Input context — passed via initial_data from PaymentSimulation
    device_id: str = ""
    device_type: str = "pos"      # "pos" or "atm"
    transaction_id: str = ""
    amount: float = 0.0
    floor_limit: float = 1000.0
    merchant_id: str = ""
    card_token: str = ""
    payment_status: str = "PENDING"

    # Feature engineering (filled by Extract_Features)
    features: dict = {}

    # Rule evaluation (filled by POS_Rules / ATM_Rules)
    rules_fired: list = []
    rules_passed: list = []

    # ML output (filled by Score_With_Wasm)
    ml_risk_score: float = 0.0
    ml_confidence: float = 0.5
    anomaly_features: list = []

    # Typology (filled by Apply_Typologies)
    typologies_triggered: list = []

    # Verdict (filled by Monitoring_Verdict / Flag_Transaction)
    risk_level: str = "LOW"
    action: str = "ALLOW"
    alert_id: str = ""
    monitoring_notes: list = []

    # HITL bubble-up (cloud_url required for review to reach control plane)
    cloud_url: str = ""
    review_timeout_sec: int = 90
    review_decision: str = ""
    review_notes: str = ""
    review_source: str = ""   # "cloud_hitl" | "ondevice_hitl" | "offline_fallback"


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Extract_Features
# ─────────────────────────────────────────────────────────────────────────────

async def extract_features(state, context, **kw) -> dict:
    """Build normalised [0, 1] feature vector for downstream ML scoring."""
    is_atm = state.device_type == "atm"
    hour_utc = int(time.gmtime().tm_hour)

    # Record velocity and get count within window
    velocity = _get_velocity(state.card_token, 1800 if is_atm else 3600)

    known_merchants = _KNOWN_ATM_LOCATIONS if is_atm else _KNOWN_POS_MERCHANTS
    merchant_novelty = 0.0 if state.merchant_id in known_merchants else 1.0

    time_risk = 1.0 if hour_utc in {23, 0, 1, 2, 3, 4, 5} else 0.0

    floor = max(state.floor_limit, 1.0)
    normalized_amount = min(state.amount / floor, 1.0)
    velocity_normalized = min(velocity / 5.0, 1.0)

    features = {
        "normalized_amount": round(normalized_amount, 4),
        "velocity_normalized": round(velocity_normalized, 4),
        "velocity_count": velocity,          # raw count for rule evaluation
        "time_risk": time_risk,
        "merchant_novelty": merchant_novelty,
        "rules_signal": 0.0,                 # updated after rule evaluation
    }

    logger.info(
        "[Monitoring] %s features: amt=%.2f vel=%d (%.2f) "
        "time_risk=%.0f merchant_novelty=%.0f",
        state.transaction_id[:8],
        normalized_amount, velocity, velocity_normalized,
        time_risk, merchant_novelty,
    )
    return {"features": features}


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Route_By_Type (DECISION)
# ─────────────────────────────────────────────────────────────────────────────

async def route_by_type(state, context, **kw) -> dict:
    """Route to device-type-specific rule evaluation."""
    if state.device_type == "atm":
        raise WorkflowJumpDirective("ATM_Rules")
    raise WorkflowJumpDirective("POS_Rules")


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: POS_Rules (STANDARD — jumps to Score_With_Wasm to skip ATM_Rules)
# ─────────────────────────────────────────────────────────────────────────────

async def evaluate_pos_rules(state, context, **kw) -> dict:
    """Evaluate 5 POS fraud rules, then jump to Score_With_Wasm."""
    fired: list[str] = []
    passed: list[str] = []
    amount = state.amount
    velocity = state.features.get("velocity_count", 0)

    # pos_r001: velocity — ≥3 transactions in 60 min
    if velocity >= 3:
        fired.append("pos_r001_velocity")
    else:
        passed.append("pos_r001_velocity")

    # pos_r002: micro-structuring — $900–$999 (just below $1000 floor)
    if 900 <= amount <= 999:
        fired.append("pos_r002_micro_struct")
    else:
        passed.append("pos_r002_micro_struct")

    # pos_r003: card testing — amount < $5
    if amount < 5.0:
        fired.append("pos_r003_card_testing")
    else:
        passed.append("pos_r003_card_testing")

    # pos_r004: unknown merchant
    if state.merchant_id not in _KNOWN_POS_MERCHANTS:
        fired.append("pos_r004_unknown_merchant")
    else:
        passed.append("pos_r004_unknown_merchant")

    # pos_r005: amount spike — > $200 at a single terminal (vending/ATM terminal threshold)
    if amount > 200.0:
        fired.append("pos_r005_amount_spike")
    else:
        passed.append("pos_r005_amount_spike")

    total_rules = 5
    features = dict(state.features)
    features["rules_signal"] = round(len(fired) / total_rules, 4)

    logger.info("[Monitoring] POS rules fired: %s", fired)

    # Update state before jump so values are persisted
    state.rules_fired = list(state.rules_fired) + fired
    state.rules_passed = list(state.rules_passed) + passed
    state.features = features
    raise WorkflowJumpDirective("Score_With_Wasm")


# ─────────────────────────────────────────────────────────────────────────────
# Step 4: ATM_Rules (STANDARD, automate_next: true → Score_With_Wasm)
# ─────────────────────────────────────────────────────────────────────────────

async def evaluate_atm_rules(state, context, **kw) -> dict:
    """Evaluate 5 ATM fraud rules. automate_next advances to Score_With_Wasm."""
    fired: list[str] = []
    passed: list[str] = []
    amount = state.amount
    hour_utc = int(time.gmtime().tm_hour)
    velocity = state.features.get("velocity_count", 0)

    # atm_r001: large cash — > $400
    if amount > 400:
        fired.append("atm_r001_large_cash")
    else:
        passed.append("atm_r001_large_cash")

    # atm_r002: after-hours — 23:00–06:00 UTC
    if hour_utc in {23, 0, 1, 2, 3, 4, 5}:
        fired.append("atm_r002_after_hours")
    else:
        passed.append("atm_r002_after_hours")

    # atm_r003: structuring — $450–$499 (just below $500 floor)
    if 450 <= amount <= 499:
        fired.append("atm_r003_structuring")
    else:
        passed.append("atm_r003_structuring")

    # atm_r004: velocity — ≥2 ATM withdrawals in 30 min
    if velocity >= 2:
        fired.append("atm_r004_velocity")
    else:
        passed.append("atm_r004_velocity")

    # atm_r005: large daily — > $700
    if amount > 700:
        fired.append("atm_r005_large_daily")
    else:
        passed.append("atm_r005_large_daily")

    # atm_r006: unknown ATM location — not in registered location set
    if state.merchant_id not in _KNOWN_ATM_LOCATIONS:
        fired.append("atm_r006_unknown_location")
    else:
        passed.append("atm_r006_unknown_location")

    total_rules = 6
    features = dict(state.features)
    features["rules_signal"] = round(len(fired) / total_rules, 4)

    logger.info("[Monitoring] ATM rules fired: %s", fired)

    return {
        "rules_fired": list(state.rules_fired) + fired,
        "rules_passed": list(state.rules_passed) + passed,
        "features": features,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Score_With_Wasm (STANDARD, automate_next: true)
# ─────────────────────────────────────────────────────────────────────────────

def _python_logistic_regression(features: dict) -> dict:
    """
    Python reimplementation of the Rust fraud scorer logistic regression.

    Used as fallback when fraud_scorer.wasm is not available.

    Weights (tuned for fintech fraud patterns):
        logit = 1.2 * normalized_amount
              + 2.5 * velocity_normalized
              + 1.8 * time_risk
              + 1.5 * merchant_novelty
              + 3.0 * rules_signal
              - 2.5  (bias)
    """
    logit = (
        1.2 * features.get("normalized_amount", 0.0)
        + 2.5 * features.get("velocity_normalized", 0.0)
        + 1.8 * features.get("time_risk", 0.0)
        + 1.5 * features.get("merchant_novelty", 0.0)
        + 3.0 * features.get("rules_signal", 0.0)
        - 2.5
    )
    risk_score = 1.0 / (1.0 + math.exp(-logit))          # sigmoid
    confidence = abs(risk_score - 0.5) * 2                # 1.0 at extremes

    anomaly: list[str] = []
    if features.get("normalized_amount", 0) > 0.8:
        anomaly.append("near_floor_limit")
    if features.get("velocity_normalized", 0) > 0.4:
        anomaly.append("high_velocity")
    if features.get("merchant_novelty", 0) > 0.5:
        anomaly.append("unknown_merchant")
    if features.get("rules_signal", 0) > 0.4:
        anomaly.append("multiple_rules_fired")
    if features.get("time_risk", 0) > 0.5:
        anomaly.append("after_hours")

    return {
        "ml_risk_score": round(risk_score, 4),
        "ml_confidence": round(confidence, 4),
        "anomaly_features": anomaly,
    }


async def score_with_wasm(state, context, **kw) -> dict:
    """
    Invoke Rust logistic regression via Wasmtime WASI.
    Falls back to a Python implementation using the same weights when the
    pre-compiled fraud_scorer.wasm binary is not present.
    """
    features = state.features

    wasm_path = os.path.join(os.path.dirname(__file__), "fraud_scorer.wasm")

    # Only attempt WASM if binary is present and non-empty (placeholder is 0 bytes)
    if os.path.exists(wasm_path) and os.path.getsize(wasm_path) > 0:
        try:
            from rufus.implementations.execution.wasm_runtime import WasmRuntime
            from rufus.models import WasmConfig

            wasm_bytes = open(wasm_path, "rb").read()
            wasm_hash = hashlib.sha256(wasm_bytes).hexdigest()

            class _InlineResolver:
                async def resolve(self, h: str) -> bytes:
                    return wasm_bytes

            runtime = WasmRuntime(resolver=_InlineResolver())
            config = WasmConfig(
                wasm_hash=wasm_hash,
                entrypoint="_start",
                state_mapping={
                    "features": "features",
                    "device_type": "device_type",
                },
                timeout_ms=500,
                fallback_on_error="default",
                default_result={
                    "ml_risk_score": 0.3,
                    "ml_confidence": 0.5,
                    "anomaly_features": [],
                },
            )
            result = await runtime.execute(config, state.model_dump())
            logger.info(
                "[Monitoring] WASM score=%.3f confidence=%.3f",
                result.get("ml_risk_score", 0),
                result.get("ml_confidence", 0),
            )
            return {
                "ml_risk_score": result.get("ml_risk_score", 0.3),
                "ml_confidence": result.get("ml_confidence", 0.5),
                "anomaly_features": result.get("anomaly_features", []),
            }
        except Exception as exc:
            logger.warning("[Monitoring] WASM unavailable (%s) — using Python fallback", exc)

    # Python logistic regression fallback
    result = _python_logistic_regression(features)
    logger.info(
        "[Monitoring] Python score=%.3f confidence=%.3f anomaly=%s",
        result["ml_risk_score"], result["ml_confidence"], result["anomaly_features"],
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Step 6: Apply_Typologies (STANDARD, automate_next: true)
# ─────────────────────────────────────────────────────────────────────────────

async def apply_typologies(state, context, **kw) -> dict:
    """Map fired rule combinations to named fraud typologies."""
    fired_set = set(state.rules_fired)
    triggered = [
        name
        for name, required_rules in _TYPOLOGIES.items()
        if required_rules.issubset(fired_set)
    ]
    if triggered:
        logger.info("[Monitoring] Typologies triggered: %s", triggered)
    return {"typologies_triggered": triggered}


# ─────────────────────────────────────────────────────────────────────────────
# Step 7: Monitoring_Verdict (DECISION, automate_next: true)
# ─────────────────────────────────────────────────────────────────────────────

async def monitoring_verdict(state, context, **kw) -> dict:
    """
    Classify ml_risk_score into a risk tier and choose an action.

    Jumps directly to Flag_Transaction for HIGH/CRITICAL.
    For LOW/MEDIUM, returns {} and automate_next advances to Flag_Transaction.
    """
    score = state.ml_risk_score

    if score >= 0.80:
        risk_level, action = "CRITICAL", "BLOCK"
    elif score >= 0.60:
        risk_level, action = "HIGH", "REVIEW"
    elif score >= 0.30:
        risk_level, action = "MEDIUM", "ALLOW"
    else:
        risk_level, action = "LOW", "ALLOW"

    notes = list(state.monitoring_notes)
    notes.append(
        f"score={score:.3f} risk={risk_level} action={action} "
        f"typologies={state.typologies_triggered} rules={state.rules_fired}"
    )

    logger.info(
        "[Monitoring] txn=%s risk=%s action=%s score=%.3f",
        state.transaction_id[:8], risk_level, action, score,
    )

    # Mutate state before jump so values survive the exception path
    state.risk_level = risk_level
    state.action = action
    state.monitoring_notes = notes

    if risk_level in ("HIGH", "CRITICAL"):
        raise WorkflowJumpDirective("Flag_Transaction")

    return {"risk_level": risk_level, "action": action, "monitoring_notes": notes}


# ─────────────────────────────────────────────────────────────────────────────
# Step 8: Flag_Transaction (STANDARD, last step)
# ─────────────────────────────────────────────────────────────────────────────

async def _bubble_up_for_review(state, alert_id: str, notes: list) -> dict:
    """
    POST to the cloud control plane to start a FraudCaseReview workflow, then
    poll _pending_fraud_decisions for the analyst's decision (written back via
    a 'resume_fraud_review' device command).

    Always returns a dict — never raises.  This is critical because
    _run_monitoring_inline()'s loop only exits on COMPLETED/FAILED and the
    launch_monitoring wrapper catches Exception.
    """
    import asyncio
    import httpx

    payload = {
        "workflow_type": "FraudCaseReview",
        "initial_data": {
            "device_id": state.device_id,
            "device_type": state.device_type,
            "transaction_id": state.transaction_id,
            "alert_id": alert_id,
            "amount": state.amount,
            "rules_fired": state.rules_fired,
            "typologies_triggered": state.typologies_triggered,
            "ml_risk_score": state.ml_risk_score,
            "cloud_url": state.cloud_url,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{state.cloud_url}/api/v1/workflow/start", json=payload
            )
        case_wf_id = resp.json().get("workflow_id", "?")
        logger.info(
            "[Monitoring] HITL case started: workflow_id=%s alert=%s",
            case_wf_id, alert_id,
        )
    except Exception as exc:
        logger.warning(
            "[Monitoring] Could not reach cloud for HITL (%s) — offline fallback", exc
        )
        return {
            "alert_id": alert_id,
            "monitoring_notes": notes + [f"HITL unreachable: {exc}"],
            "review_decision": "APPROVED_LOCAL",
            "review_source": "offline_fallback",
            "action": "ALLOW",
        }

    # Poll for decision (asyncio.sleep — non-blocking)
    poll_sec = 3
    elapsed = 0
    timeout = getattr(state, "review_timeout_sec", 90)
    while elapsed < timeout:
        decision_data = _pending_fraud_decisions.pop(alert_id, None)
        if decision_data:
            decision = decision_data.get("decision", "APPROVE")
            action = "ALLOW" if decision == "APPROVE" else "BLOCK"
            logger.info(
                "[Monitoring] Cloud HITL decision: alert=%s decision=%s",
                alert_id, decision,
            )
            return {
                "alert_id": alert_id,
                "monitoring_notes": notes + [f"Cloud HITL: {decision}"],
                "review_decision": decision,
                "review_notes": decision_data.get("reviewer_notes", ""),
                "review_source": "cloud_hitl",
                "action": action,
            }
        await asyncio.sleep(poll_sec)
        elapsed += poll_sec

    # Timeout — on-device manager authorisation simulation
    logger.warning(
        "[Monitoring] Review timeout (%ds) — on-device manager authorisation", timeout
    )
    await asyncio.sleep(1.5)
    manager_code = f"MGR-{uuid.uuid4().hex[:6].upper()}"
    return {
        "alert_id": alert_id,
        "monitoring_notes": notes + [f"TIMEOUT: manager_code={manager_code}"],
        "review_decision": "APPROVED_LOCAL",
        "review_notes": f"Manager override: {manager_code}",
        "review_source": "ondevice_hitl",
        "action": "ALLOW",
    }


async def flag_transaction(state, context, **kw) -> dict:
    """Create an alert record for HIGH/CRITICAL; log PASS for LOW/MEDIUM."""
    alert_id = ""
    notes = list(state.monitoring_notes)

    if state.risk_level in ("HIGH", "CRITICAL"):
        alert_id = uuid.uuid4().hex[:12]
        notes.append(
            f"ALERT {alert_id}: {state.risk_level} risk — "
            f"txn={state.transaction_id[:8]} device={state.device_id} "
            f"action={state.action}"
        )
        logger.warning(
            "[Monitoring] ALERT %s: %s risk txn=%s device=%s action=%s "
            "rules=%s typologies=%s",
            alert_id, state.risk_level, state.transaction_id[:8],
            state.device_id, state.action,
            state.rules_fired, state.typologies_triggered,
        )
        if state.action == "REVIEW" and state.cloud_url:
            result = await _bubble_up_for_review(state, alert_id, notes)
            return result
    else:
        notes.append(
            f"PASS: {state.risk_level} risk — "
            f"txn={state.transaction_id[:8]} score={state.ml_risk_score:.3f}"
        )
        logger.info(
            "[Monitoring] PASS txn=%s risk=%s score=%.3f",
            state.transaction_id[:8], state.risk_level, state.ml_risk_score,
        )

    return {"alert_id": alert_id, "monitoring_notes": notes}
