"""
ConfigRollout Workflow Step Functions

Fleet-wide config push with progressive rollout, LOOP-based monitoring,
and saga compensation for rollback.

Service injection is via init_services() called from startup_event().
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from ruvon.models import StepContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service handles — injected at startup
# ---------------------------------------------------------------------------

_persistence_provider = None
_broadcast_service = None
_device_service = None


def init_services(persistence, broadcast_svc, device_svc):
    """Wire services into this module. Called from startup_event()."""
    global _persistence_provider, _broadcast_service, _device_service
    _persistence_provider = persistence
    _broadcast_service = broadcast_svc
    _device_service = device_svc


# ---------------------------------------------------------------------------
# State Model
# ---------------------------------------------------------------------------

class ConfigRolloutState(BaseModel):
    # ── Input ────────────────────────────────────────────────────────────────
    config_version: str
    config_data: Dict[str, Any]
    created_by: Optional[str] = None
    description: Optional[str] = None
    rollout_strategy: str = "all_at_once"
    rollout_phases: List[float] = [1.0]
    target_filter: Dict[str, Any] = {"status": "online"}
    circuit_breaker_threshold: float = 0.2
    max_poll_count: int = 30

    # ── Set during workflow ──────────────────────────────────────────────────
    previous_config_version: Optional[str] = None
    new_config_etag: Optional[str] = None
    broadcast_id: Optional[str] = None
    poll_count: int = 0
    keep_monitoring: bool = True      # WHILE loop condition field
    broadcast_status: Optional[str] = None
    broadcast_success_rate: float = 0.0
    broadcast_failure_rate: float = 0.0
    broadcast_completed: int = 0
    broadcast_failed: int = 0
    broadcast_total: int = 0
    rollout_outcome: Optional[str] = None
    completed_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Step 1: Validate Config
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r'^[\w\-.]{1,100}$')
_VALID_STRATEGIES = {"all_at_once", "canary", "blue_green"}


async def validate_config(state: ConfigRolloutState, context: StepContext, **_) -> dict:
    """Pure validation — no side effects."""
    if not _VERSION_RE.match(state.config_version):
        raise ValueError(
            f"config_version '{state.config_version}' is invalid. "
            "Must match ^[\\w\\-.]{1,100}$"
        )
    if not state.config_data:
        raise ValueError("config_data must be non-empty")
    if state.rollout_strategy not in _VALID_STRATEGIES:
        raise ValueError(
            f"rollout_strategy '{state.rollout_strategy}' must be one of {_VALID_STRATEGIES}"
        )
    phases = state.rollout_phases
    if not phases or phases[-1] != 1.0:
        raise ValueError("rollout_phases must end at 1.0")
    if phases != sorted(phases):
        raise ValueError("rollout_phases must be sorted ascending")

    logger.info(f"[ConfigRollout] Config {state.config_version} validated")
    return {}


# ---------------------------------------------------------------------------
# Step 2: Create Config Version
# ---------------------------------------------------------------------------

async def create_config_version(state: ConfigRolloutState, context: StepContext, **_) -> dict:
    """Persist config to the database and return etag."""
    # Capture previous version for saga compensation
    active = await _device_service.get_active_config()
    previous_version = active["config_version"] if active else None

    result = await _device_service.create_config(
        config_version=state.config_version,
        config_data=state.config_data,
        created_by=state.created_by,
        description=state.description,
    )

    logger.info(
        f"[ConfigRollout] Created config {state.config_version} "
        f"(etag={result['etag']}, previous={previous_version})"
    )
    return {
        "previous_config_version": previous_version,
        "new_config_etag": result["etag"],
    }


async def compensate_create_config(state: ConfigRolloutState, context: StepContext, **_) -> dict:
    """Saga compensation: restore previous config version as active."""
    async with _persistence_provider.pool.acquire() as conn:
        # Deactivate the rolled-back version
        await conn.execute(
            "UPDATE device_configs SET is_active = false WHERE config_version = $1",
            state.config_version,
        )
        # Re-activate previous version (if one existed)
        if state.previous_config_version:
            rows = await conn.execute(
                "UPDATE device_configs SET is_active = true WHERE config_version = $1",
                state.previous_config_version,
            )
            logger.info(
                f"[ConfigRollout][Compensation] Restored config {state.previous_config_version}"
            )
        else:
            logger.warning(
                "[ConfigRollout][Compensation] No previous config version to restore"
            )
    return {"rollout_outcome": "compensated"}


# ---------------------------------------------------------------------------
# Step 3: Broadcast To Fleet
# ---------------------------------------------------------------------------

async def broadcast_to_fleet(state: ConfigRolloutState, context: StepContext, **_) -> dict:
    """Send update_config command to all matching devices."""
    from ruvon_server.broadcast import CommandBroadcast, TargetFilter, RolloutConfig, RolloutStrategy

    # Build target filter from state
    target_filter = TargetFilter(**state.target_filter)

    # Build rollout config
    strategy_map = {
        "all_at_once": RolloutStrategy.ALL_AT_ONCE,
        "canary": RolloutStrategy.CANARY,
        "blue_green": RolloutStrategy.BLUE_GREEN,
    }
    rollout_config = RolloutConfig(
        strategy=strategy_map.get(state.rollout_strategy, RolloutStrategy.ALL_AT_ONCE),
        phases=state.rollout_phases,
        circuit_breaker_threshold=state.circuit_breaker_threshold,
    )

    broadcast = CommandBroadcast(
        command_type="update_config",
        command_data={
            "config_version": state.config_version,
            "config_data": state.config_data,
            "etag": state.new_config_etag,
        },
        target_filter=target_filter,
        rollout_config=rollout_config,
        created_by=state.created_by,
    )

    broadcast_id = await _broadcast_service.create_broadcast(broadcast)

    logger.info(f"[ConfigRollout] Broadcast {broadcast_id} created")
    return {"broadcast_id": broadcast_id}


async def compensate_broadcast(state: ConfigRolloutState, context: StepContext, **_) -> dict:
    """Saga compensation: cancel the broadcast."""
    if state.broadcast_id:
        cancelled = await _broadcast_service.cancel_broadcast(state.broadcast_id)
        logger.info(
            f"[ConfigRollout][Compensation] Broadcast {state.broadcast_id} "
            f"{'cancelled' if cancelled else 'was already terminal'}"
        )
    return {"rollout_outcome": "compensated"}


# ---------------------------------------------------------------------------
# Step 4 (LOOP body): Poll Broadcast Status
# ---------------------------------------------------------------------------

_TERMINAL_STATUSES = {"completed", "failed", "paused", "cancelled"}


async def poll_broadcast_status(state: ConfigRolloutState, context: StepContext, **_) -> dict:
    """
    Single poll iteration — called inside a WHILE loop.

    Sets keep_monitoring=False when the broadcast reaches a terminal state
    or when max_poll_count is exceeded.
    """
    new_poll_count = state.poll_count + 1

    progress = await _broadcast_service.get_broadcast_progress(state.broadcast_id)
    if progress is None:
        logger.warning(
            f"[ConfigRollout] Broadcast {state.broadcast_id} not found on poll #{new_poll_count}"
        )
        return {
            "poll_count": new_poll_count,
            "keep_monitoring": new_poll_count < state.max_poll_count,
        }

    broadcast_status = progress.status.value
    is_terminal = broadcast_status in _TERMINAL_STATUSES
    exceeded_limit = new_poll_count >= state.max_poll_count
    keep = not (is_terminal or exceeded_limit)

    logger.info(
        f"[ConfigRollout] Poll #{new_poll_count}: broadcast={broadcast_status}, "
        f"completed={progress.completed_devices}/{progress.total_devices}, "
        f"failed={progress.failed_devices}, keep_monitoring={keep}"
    )

    # Brief sleep between polls to avoid hammering the DB
    if keep:
        await asyncio.sleep(10)

    return {
        "poll_count": new_poll_count,
        "keep_monitoring": keep,
        "broadcast_status": broadcast_status,
        "broadcast_success_rate": progress.success_rate,
        "broadcast_failure_rate": progress.failure_rate,
        "broadcast_completed": progress.completed_devices,
        "broadcast_failed": progress.failed_devices,
        "broadcast_total": progress.total_devices,
    }


# ---------------------------------------------------------------------------
# Step 5: Finalize Rollout
# ---------------------------------------------------------------------------

async def finalize_rollout(state: ConfigRolloutState, context: StepContext, **_) -> dict:
    """Evaluate outcome and raise on failure (triggers saga compensation)."""
    outcome = "unknown"

    if state.broadcast_status == "completed":
        if state.broadcast_failure_rate <= state.circuit_breaker_threshold:
            outcome = "success"
        else:
            raise ValueError(
                f"Config rollout failure rate {state.broadcast_failure_rate:.1%} "
                f"exceeds threshold {state.circuit_breaker_threshold:.1%}"
            )
    elif state.broadcast_status in ("failed", "paused"):
        raise ValueError(
            f"Config broadcast ended in '{state.broadcast_status}' state"
        )
    elif state.poll_count >= state.max_poll_count:
        raise ValueError(
            f"Config rollout timed out after {state.poll_count} polling intervals"
        )
    else:
        raise ValueError(
            f"Config broadcast in unexpected state '{state.broadcast_status}'"
        )

    logger.info(f"[ConfigRollout] Rollout {state.config_version} outcome: {outcome}")
    return {
        "rollout_outcome": outcome,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
