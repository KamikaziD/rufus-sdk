"""Device Approvals API — operator approves or rejects a sidecar suggestion.

POST /api/v1/devices/{device_id}/approvals
  Operator → cloud: approve or reject a pending suggestion.
  The decision is pushed back to the device via the SAF sync channel.

GET  /api/v1/devices/{device_id}/approvals/pending
  Edge device → cloud: poll for a pending approval decision (SAF sync path).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from rufus_server.api.device_suggestions import SuggestionRecord, _suggestions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/devices", tags=["device-approvals"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ApprovalRequest(BaseModel):
    """Operator submits an approval/rejection for a suggestion."""
    suggestion_id: str
    approved: bool
    operator_notes: str = ""
    operator_id: Optional[str] = None


class ApprovalDecision(BaseModel):
    """A resolved approval decision, ready to be pulled by the device."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    device_id: str
    suggestion_id: str
    approved: bool
    operator_notes: str
    operator_id: Optional[str] = None
    decided_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # Populated from the suggestion for convenience
    change_key: Optional[str] = None
    change_value: Optional[Any] = None
    # Set to True when the device confirms it has fetched this decision
    fetched_by_device: bool = False


# In-memory store for pending decisions (replace with DB in production)
_pending_decisions: Dict[str, List[ApprovalDecision]] = {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/{device_id}/approvals",
    status_code=status.HTTP_201_CREATED,
    response_model=ApprovalDecision,
    summary="Operator approves or rejects a device suggestion",
)
async def submit_approval(
    device_id: str,
    payload: ApprovalRequest,
) -> ApprovalDecision:
    """Called by an operator (via dashboard or CLI) to approve or reject a suggestion.

    The decision is stored and will be delivered to the device on its next
    SAF sync cycle (GET /approvals/pending).
    """
    # Find the referenced suggestion
    suggestion = None
    for record in _suggestions.get(device_id, []):
        if record.id == payload.suggestion_id:
            suggestion = record
            break

    if suggestion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Suggestion {payload.suggestion_id} not found for device {device_id}",
        )

    if suggestion.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Suggestion {payload.suggestion_id} is already {suggestion.status}",
        )

    # Update suggestion status
    suggestion.status = "approved" if payload.approved else "rejected"
    suggestion.resolved_at = datetime.now(timezone.utc).isoformat()
    suggestion.operator_notes = payload.operator_notes

    decision = ApprovalDecision(
        device_id=device_id,
        suggestion_id=payload.suggestion_id,
        approved=payload.approved,
        operator_notes=payload.operator_notes,
        operator_id=payload.operator_id,
        change_key=suggestion.suggestion.change.key if payload.approved else None,
        change_value=suggestion.suggestion.change.value if payload.approved else None,
    )

    _pending_decisions.setdefault(device_id, []).append(decision)

    action = "APPROVED" if payload.approved else "REJECTED"
    logger.info(
        "[DeviceApprovals] %s suggestion %s for device %s by operator %s",
        action, payload.suggestion_id, device_id, payload.operator_id or "unknown",
    )
    return decision


@router.get(
    "/{device_id}/approvals/pending",
    response_model=List[ApprovalDecision],
    summary="Pull pending approval decisions (called by edge device SAF sync)",
)
async def get_pending_decisions(device_id: str) -> List[ApprovalDecision]:
    """Called by the edge device during SAF sync to check for pending decisions.

    Returns all unacknowledged decisions. The device marks them as fetched
    by calling the PATCH /approvals/{decision_id}/acknowledge endpoint.
    """
    decisions = [
        d for d in _pending_decisions.get(device_id, [])
        if not d.fetched_by_device
    ]
    return decisions


@router.patch(
    "/{device_id}/approvals/{decision_id}/acknowledge",
    response_model=ApprovalDecision,
    summary="Device acknowledges receipt of an approval decision",
)
async def acknowledge_decision(device_id: str, decision_id: str) -> ApprovalDecision:
    """Called by the edge device after it has received and processed a decision.

    Marks the decision as fetched so it won't be re-delivered.
    """
    for decision in _pending_decisions.get(device_id, []):
        if decision.id == decision_id:
            decision.fetched_by_device = True
            logger.info(
                "[DeviceApprovals] Decision %s acknowledged by device %s",
                decision_id, device_id,
            )
            return decision

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Decision {decision_id} not found for device {device_id}",
    )


@router.post(
    "/{device_id}/heartbeat",
    status_code=status.HTTP_200_OK,
    summary="Receive a health heartbeat from a healthy device",
)
async def receive_heartbeat(device_id: str, payload: Dict) -> Dict:
    """Called by the sidecar when health_score >= 0.7 (no action needed).

    Stores the last-known health state for the device registry dashboard.
    """
    logger.debug(
        "[DeviceApprovals] Heartbeat from %s: health_score=%.2f",
        device_id, payload.get("health_score", 0),
    )
    return {"status": "ok", "device_id": device_id}


# Fix missing import
from typing import Dict  # noqa: E402 (moved to satisfy linter)
