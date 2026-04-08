"""Device Suggestions API — receives performance suggestions from sidecar agents.

POST /api/v1/devices/{device_id}/suggestions
  Edge device → cloud: sidecar proposes a config change for operator review.

GET  /api/v1/devices/{device_id}/suggestions
  Dashboard → cloud: list pending suggestions for a device.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/devices", tags=["device-suggestions"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SuggestionChange(BaseModel):
    key: str = Field(..., description="Config key to change")
    value: Any = Field(..., description="Proposed new value")


class DeviceSuggestion(BaseModel):
    """A performance suggestion from a sidecar agent."""
    issue: str = Field(..., description="Brief description of the performance problem")
    change: SuggestionChange
    expected_improvement: str = Field(..., description="Expected outcome if change is applied")
    risk: str = Field("low", description="Risk level: low | medium | high")


class SuggestionPayload(BaseModel):
    """Payload received from the sidecar agent."""
    workflow_id: str
    suggestion: DeviceSuggestion
    health_score_before: float
    metrics_snapshot: Dict[str, Any] = Field(default_factory=dict)
    device_id: str
    timestamp: str


class SuggestionRecord(BaseModel):
    """A suggestion stored on the control plane, awaiting operator approval."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    device_id: str
    workflow_id: str
    suggestion: DeviceSuggestion
    health_score_before: float
    metrics_snapshot: Dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"   # pending | approved | rejected | applied
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: Optional[str] = None
    operator_notes: Optional[str] = None


# In-memory store (replace with DB in production)
_suggestions: Dict[str, List[SuggestionRecord]] = {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/{device_id}/suggestions",
    status_code=status.HTTP_201_CREATED,
    response_model=SuggestionRecord,
    summary="Receive a performance suggestion from a device sidecar",
)
async def create_suggestion(
    device_id: str,
    payload: SuggestionPayload,
) -> SuggestionRecord:
    """Called by the DeploymentMonitor sidecar after the LLM generates a suggestion.

    The suggestion is stored as 'pending' until an operator approves or rejects it
    via the dashboard or the POST /approvals endpoint.
    """
    if device_id != payload.device_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"device_id mismatch: path={device_id} body={payload.device_id}",
        )

    record = SuggestionRecord(
        device_id=device_id,
        workflow_id=payload.workflow_id,
        suggestion=payload.suggestion,
        health_score_before=payload.health_score_before,
        metrics_snapshot=payload.metrics_snapshot,
    )

    _suggestions.setdefault(device_id, []).append(record)
    logger.info(
        "[DeviceSuggestions] New suggestion for device %s: %s → %s=%s",
        device_id,
        payload.suggestion.issue,
        payload.suggestion.change.key,
        payload.suggestion.change.value,
    )
    return record


@router.get(
    "/{device_id}/suggestions",
    response_model=List[SuggestionRecord],
    summary="List suggestions for a device",
)
async def list_suggestions(
    device_id: str,
    pending_only: bool = True,
) -> List[SuggestionRecord]:
    """List performance suggestions for a device.

    Used by the operator dashboard to show pending suggestions.
    """
    records = _suggestions.get(device_id, [])
    if pending_only:
        records = [r for r in records if r.status == "pending"]
    return records


@router.get(
    "/{device_id}/suggestions/{suggestion_id}",
    response_model=SuggestionRecord,
    summary="Get a specific suggestion",
)
async def get_suggestion(device_id: str, suggestion_id: str) -> SuggestionRecord:
    for record in _suggestions.get(device_id, []):
        if record.id == suggestion_id:
            return record
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")
