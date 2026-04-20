"""
PolicyRollout Workflow Step Functions

Durable policy creation with saga compensation. Write path only —
read/evaluate operations stay as direct PolicyEvaluator calls (hot path).

Service injection is via init_services() called from startup_event().
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel
from ruvon.models import StepContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service handles — injected at startup
# ---------------------------------------------------------------------------

_persistence_provider = None
_policy_evaluator = None


def init_services(persistence, policy_eval):
    """Wire services into this module. Called from startup_event()."""
    global _persistence_provider, _policy_evaluator
    _persistence_provider = persistence
    _policy_evaluator = policy_eval


# ---------------------------------------------------------------------------
# State Model
# ---------------------------------------------------------------------------

class PolicyRolloutState(BaseModel):
    # ── Input ────────────────────────────────────────────────────────────────
    policy_data: Dict[str, Any]          # raw Policy dict from request
    created_by: Optional[str] = None

    # ── Set during workflow ──────────────────────────────────────────────────
    policy_id: Optional[str] = None      # str(UUID) after persist
    policy_name: Optional[str] = None
    rollout_outcome: Optional[str] = None
    completed_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Step 1: Validate Policy
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r'^[\w\-. ]{1,100}$')
_DANGEROUS_PATTERNS = ["import", "exec", "eval", "open", "__", "lambda"]


async def validate_policy(state: PolicyRolloutState, context: StepContext, **_) -> dict:
    """Pure validation — no side effects."""
    data = state.policy_data
    name = data.get("policy_name", "")
    if not name:
        raise ValueError("policy_name must be non-empty")
    if not _NAME_RE.match(name):
        raise ValueError(
            f"policy_name '{name}' is invalid. Must match ^[\\w\\-. ]{{1,100}}$"
        )

    rules = data.get("rules", [])
    if not rules:
        raise ValueError("rules must be a non-empty list")
    for rule in rules:
        condition = rule.get("condition", "")
        if condition != "default":
            for pattern in _DANGEROUS_PATTERNS:
                if pattern in condition.lower():
                    raise ValueError(f"Dangerous pattern in condition: {pattern}")

    # Validate rollout strategy if present
    from ruvon_server.policy_engine import RolloutStrategy
    rollout = data.get("rollout", {})
    if rollout:
        strategy = rollout.get("strategy", "immediate")
        valid_strategies = {s.value for s in RolloutStrategy}
        if strategy not in valid_strategies:
            raise ValueError(
                f"rollout.strategy '{strategy}' must be one of {valid_strategies}"
            )

    logger.info(f"[PolicyRollout] Policy '{name}' validated")
    return {}


# ---------------------------------------------------------------------------
# Step 2: Persist Policy
# ---------------------------------------------------------------------------

async def persist_policy(state: PolicyRolloutState, context: StepContext, **_) -> dict:
    """Persist policy to DB and sync to in-memory evaluator (dual write)."""
    from ruvon_server.policy_engine import Policy

    # Build Policy model from raw dict (validates and assigns UUID if not present)
    policy_dict = dict(state.policy_data)
    if state.created_by:
        policy_dict["created_by"] = state.created_by
    policy = Policy(**policy_dict)

    # Insert into policies table
    async with _persistence_provider.pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO policies
                (id, policy_name, description, version, status, rules, rollout,
                 created_by, created_at, updated_at, tags)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
            str(policy.id),
            policy.policy_name,
            policy.description,
            policy.version,
            policy.status.value,
            json.dumps([r.model_dump() for r in policy.rules]),
            json.dumps(policy.rollout.model_dump()),
            policy.created_by,
            policy.created_at,
            policy.updated_at,
            json.dumps(policy.tags),
        )

    # Dual write: keep in-memory evaluator consistent
    _policy_evaluator.add_policy(policy)

    logger.info(
        f"[PolicyRollout] Policy '{policy.policy_name}' persisted (id={policy.id})"
    )
    return {
        "policy_id": str(policy.id),
        "policy_name": policy.policy_name,
    }


async def compensate_persist_policy(
    state: PolicyRolloutState, context: StepContext, **_
) -> dict:
    """Saga compensation: remove from DB and in-memory evaluator."""
    if state.policy_id:
        async with _persistence_provider.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM policies WHERE id = $1",
                state.policy_id,
            )
        _policy_evaluator.remove_policy(UUID(state.policy_id))
        logger.info(
            f"[PolicyRollout][Compensation] Policy {state.policy_id} removed"
        )
    return {"rollout_outcome": "compensated"}


# ---------------------------------------------------------------------------
# Step 3: Finalize Rollout
# ---------------------------------------------------------------------------

async def finalize_policy_rollout(
    state: PolicyRolloutState, context: StepContext, **_
) -> dict:
    """Record successful completion."""
    logger.info(
        f"[PolicyRollout] Policy '{state.policy_name}' rollout complete"
    )
    return {
        "rollout_outcome": "success",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
