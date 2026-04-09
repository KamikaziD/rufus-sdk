"""Sidecar decision step functions.

All functions follow the Ruvon step function signature:
  (state, context, **kwargs) -> dict

DECISION steps may raise WorkflowJumpDirective to branch the workflow.

Risk-tier governance
--------------------
Changes are classified into three levels before any approval or apply step:

  Level 1 — Config/UI tweaks (fraud thresholds, floor limits, timeouts):
      Auto-deploy.  Operator is notified but no approval required.
      Jump directly to ApplyChange.

  Level 2 — Logic/behaviour changes (execution provider, NATS, max workers):
      Canary deployment + 1-click operator approval.
      Fall through to ApprovalGate (HUMAN_IN_LOOP).

  Level 3 — Security-critical changes (persistence provider, DB path, encryption):
      Never auto-execute.  Open a draft PR on the cloud control plane only.
      Jump to DraftPROnly, which notifies the operator and skips apply entirely.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from ruvon.models import WorkflowJumpDirective

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Risk tier key classification
# ---------------------------------------------------------------------------

# Level 1: safe to hot-swap automatically with no human approval
LEVEL_1_KEYS: frozenset[str] = frozenset({
    "fraud_threshold",
    "floor_limit",
    "max_retry_count",
    "saf_sync_interval_seconds",
    "http_timeout_seconds",
    "log_level",
    "max_concurrent_workflows",
    "heartbeat_interval_seconds",
    "ui_theme",
    "receipt_footer",
})

# Level 2: behavioural — require canary + operator approval
LEVEL_2_KEYS: frozenset[str] = frozenset({
    "execution_provider",
    "nats_subjects",
    "nats_url",
    "worker_concurrency",
    "max_parallel_workflows",
    "retry_backoff_factor",
    "celery_broker_url",
    "workflow_registry",
    "uvloop_enabled",
})

# Level 3: security-critical — draft PR only, never auto-execute
LEVEL_3_KEYS: frozenset[str] = frozenset({
    "persistence_provider",
    "db_path",
    "encryption_key",
    "tls_cert_path",
    "tls_key_path",
    "api_key",
    "hmac_secret",
    "jwt_secret",
    "root_ca_cert",
})


def _classify_change_key(key: str) -> int:
    """Return the risk tier (1, 2, or 3) for a config change key.

    Unknown keys default to Level 2 (require approval).
    """
    if key in LEVEL_3_KEYS:
        return 3
    if key in LEVEL_2_KEYS:
        return 2
    if key in LEVEL_1_KEYS:
        return 1
    # Unknown key: require approval (Level 2) as a safe default
    logger.warning(
        "[decisions] Unknown config key %r — defaulting to risk tier 2 (approval required)", key
    )
    return 2


def health_gate(state: Any, context: Any, **kwargs) -> Dict[str, Any]:
    """DECISION step: jump to ReportOutcome if device health score is acceptable.

    Called at the HealthDecision step. If health_score >= 0.7, the device is
    healthy and no suggestion is needed — jump directly to ReportOutcome.
    Otherwise, fall through to GenerateSuggestions.
    """
    raw = getattr(state, "health_score", None)
    if isinstance(raw, dict):
        # Step returned a dict (automate_next path)
        health_score = float(raw.get("health_score", 0.0))
    elif raw is not None:
        health_score = float(raw)
    else:
        health_score = 0.0

    if health_score >= 0.7:
        logger.info(
            "[Sidecar:health_gate] health_score=%.3f >= 0.7 — device healthy, skipping suggestions",
            health_score,
        )
        raise WorkflowJumpDirective(target_step_name="ReportOutcome")

    logger.info(
        "[Sidecar:health_gate] health_score=%.3f < 0.7 — generating improvement suggestion",
        health_score,
    )
    return {}


def approval_gate(state: Any, context: Any, **kwargs) -> Dict[str, Any]:
    """DECISION step: jump to ReportOutcome if operator rejected the suggestion.

    Called at the ApprovalDecision step, after the HUMAN_IN_LOOP ApprovalGate
    has been resumed with operator input. If approved=False, skip ApplyChange
    and jump to ReportOutcome to report the rejection.
    """
    approved = getattr(state, "approved", False)
    if isinstance(approved, str):
        approved = approved.lower() in ("true", "yes", "1")

    if not approved:
        logger.info(
            "[Sidecar:approval_gate] Operator rejected suggestion — skipping ApplyChange"
        )
        raise WorkflowJumpDirective(target_step_name="ReportOutcome")

    logger.info("[Sidecar:approval_gate] Operator approved — proceeding to ApplyChange")
    return {}


def risk_tier_gate(state: Any, context: Any, **kwargs) -> Dict[str, Any]:
    """DECISION step: classify the suggested change and enforce governance policy.

    Reads state.suggestion (set by GenerateSuggestions step).

    Outcomes:
      - Level 1: sets state.risk_tier=1, jumps to ApplyChange (auto-deploy).
      - Level 2: sets state.risk_tier=2, falls through to ApprovalGate.
      - Level 3: sets state.risk_tier=3, falls through to DraftPROnly.

    The risk tier is persisted in state so downstream steps can adapt their
    behaviour (e.g. DraftPROnly reads risk_tier before creating a PR).
    """
    suggestion = getattr(state, "suggestion", None) or {}
    if isinstance(suggestion, dict):
        change = suggestion.get("change", {})
        if isinstance(change, dict):
            change_key = change.get("key", "")
        else:
            change_key = ""
    else:
        change_key = ""

    tier = _classify_change_key(change_key)

    logger.info(
        "[Sidecar:risk_tier_gate] key=%r classified as Level %d", change_key, tier
    )

    if tier == 1:
        # Auto-deploy: jump straight to apply, no human gate needed.
        raise WorkflowJumpDirective(target_step_name="ApplyChange")

    # Level 2 and 3 fall through.  DraftPROnly (next DECISION step) handles Level 3.
    return {"risk_tier": tier}


def draft_pr_only(state: Any, context: Any, **kwargs) -> Dict[str, Any]:
    """DECISION step: handle Level 3 security-critical changes.

    Level 3 changes (crypto/auth/kernel) must NEVER be auto-applied.
    This step opens a draft PR on the cloud control plane and then jumps
    to ReportOutcome — skipping ApprovalGate and ApplyChange entirely.

    For Level 1/2 changes (risk_tier < 3) this step is a no-op and falls
    through to ApprovalGate.
    """
    risk_tier = getattr(state, "risk_tier", 2)
    if isinstance(risk_tier, int) and risk_tier != 3:
        # Not Level 3 — fall through to ApprovalGate
        return {}

    suggestion = getattr(state, "suggestion", {}) or {}
    change_key = ""
    if isinstance(suggestion, dict):
        change = suggestion.get("change", {})
        if isinstance(change, dict):
            change_key = change.get("key", "")

    control_plane_url = os.environ.get(
        "RUVON_CONTROL_PLANE_URL", "http://localhost:8000"
    )
    device_id = os.environ.get("RUVON_DEVICE_ID", "unknown")

    try:
        import urllib.request
        import json as _json

        payload = _json.dumps({
            "device_id": device_id,
            "workflow_id": getattr(context, "workflow_id", ""),
            "change_key": change_key,
            "suggestion": suggestion,
            "risk_tier": 3,
            "status": "draft_pr",
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{control_plane_url}/api/v1/devices/{device_id}/draft-pr",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec
            pr_data = _json.loads(resp.read())
            pr_url = pr_data.get("pr_url", "")

        logger.info(
            "[Sidecar:draft_pr_only] Created draft PR for Level 3 change key=%r: %s",
            change_key, pr_url,
        )
        result = {"draft_pr_url": pr_url, "apply_outcome": "draft_pr_only"}
    except Exception as exc:
        logger.error(
            "[Sidecar:draft_pr_only] Failed to create draft PR for key=%r: %s",
            change_key, exc,
        )
        result = {"apply_outcome": "draft_pr_failed", "draft_pr_error": str(exc)}

    raise WorkflowJumpDirective(target_step_name="ReportOutcome")


def check_should_suggest(state: Any, context: Any, **kwargs) -> Dict[str, Any]:
    """Legacy DECISION step (superseded by health_gate). Kept for backwards compatibility."""
    if not getattr(state, "should_generate_suggestions", True):
        raise WorkflowJumpDirective(target_step_name="ReportOutcome")
    return {}
