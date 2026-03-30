"""Sidecar decision step functions.

All functions follow the Rufus step function signature:
  (state, context, **kwargs) -> dict

DECISION steps may raise WorkflowJumpDirective to branch the workflow.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from rufus.models import WorkflowJumpDirective

logger = logging.getLogger(__name__)


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
        raise WorkflowJumpDirective(next_step_name="ReportOutcome")

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
        raise WorkflowJumpDirective(next_step_name="ReportOutcome")

    logger.info("[Sidecar:approval_gate] Operator approved — proceeding to ApplyChange")
    return {}


def check_should_suggest(state: Any, context: Any, **kwargs) -> Dict[str, Any]:
    """Legacy DECISION step (superseded by health_gate). Kept for backwards compatibility."""
    if not getattr(state, "should_generate_suggestions", True):
        raise WorkflowJumpDirective(next_step_name="ReportOutcome")
    return {}
