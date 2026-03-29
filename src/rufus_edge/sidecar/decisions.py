"""Sidecar decision step functions."""

from __future__ import annotations

from typing import Any, Dict

from rufus.models import WorkflowJumpDirective


def check_should_suggest(state: Any, context: Any, **kwargs) -> Dict[str, Any]:
    """DECISION step: skip suggestion generation if device is healthy."""
    if not getattr(state, "should_generate_suggestions", True):
        raise WorkflowJumpDirective(next_step_name="ReportHealthy")
    return {}
