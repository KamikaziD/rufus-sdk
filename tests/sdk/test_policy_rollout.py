"""
Tests for PolicyRollout workflow step functions.

Covers:
  1. Happy path: validate → persist → finalize → rollout_outcome="success"
  2. Saga compensation: persist failure triggers compensate_persist_policy
  3. Validation rejection: invalid policy_name raises ValueError
"""

import asyncio
import concurrent.futures
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict

from rufus_server.steps.policy_rollout_steps import (
    PolicyRolloutState,
    validate_policy,
    persist_policy,
    compensate_persist_policy,
    finalize_policy_rollout,
    init_services,
)
from rufus.models import StepContext


# ---------------------------------------------------------------------------
# Minimal valid policy fixture
# ---------------------------------------------------------------------------

def _valid_policy_data() -> Dict[str, Any]:
    return {
        "policy_name": "Test_Policy",
        "rules": [
            {"condition": "default", "artifact": "model_v1.pex"}
        ],
        "rollout": {"strategy": "immediate"},
    }


def _make_context() -> StepContext:
    ctx = MagicMock(spec=StepContext)
    ctx.loop_item = None
    ctx.loop_index = None
    return ctx


# ---------------------------------------------------------------------------
# Mock persistence + evaluator fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_conn():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    return conn


@pytest.fixture
def mock_pool(mock_conn):
    pool = MagicMock()
    # pool.acquire() used as async context manager
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)
    return pool


@pytest.fixture
def mock_persistence(mock_pool):
    p = MagicMock()
    p.pool = mock_pool
    return p


@pytest.fixture
def mock_evaluator():
    ev = MagicMock()
    ev.add_policy = MagicMock()
    ev.remove_policy = MagicMock()
    return ev


@pytest.fixture(autouse=True)
def inject_services(mock_persistence, mock_evaluator):
    """Inject mock services before each test; restore None after."""
    init_services(mock_persistence, mock_evaluator)
    yield
    init_services(None, None)


# ---------------------------------------------------------------------------
# 1. Happy path — validate → persist → finalize
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_validate_policy_passes_valid_data():
    state = PolicyRolloutState(policy_data=_valid_policy_data())
    result = await validate_policy(state, _make_context())
    assert result == {}


@pytest.mark.asyncio
async def test_persist_policy_inserts_and_syncs(mock_conn, mock_evaluator):
    state = PolicyRolloutState(policy_data=_valid_policy_data(), created_by="admin")
    result = await persist_policy(state, _make_context())

    assert "policy_id" in result
    assert result["policy_name"] == "Test_Policy"

    # DB insert called once
    mock_conn.execute.assert_called_once()
    insert_sql = mock_conn.execute.call_args[0][0]
    assert "INSERT INTO policies" in insert_sql

    # In-memory evaluator updated
    mock_evaluator.add_policy.assert_called_once()


@pytest.mark.asyncio
async def test_finalize_returns_success():
    state = PolicyRolloutState(
        policy_data=_valid_policy_data(),
        policy_id="some-uuid",
        policy_name="Test_Policy",
    )
    result = await finalize_policy_rollout(state, _make_context())
    assert result["rollout_outcome"] == "success"
    assert "completed_at" in result


# ---------------------------------------------------------------------------
# 2. Saga compensation — removes from DB and evaluator
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compensate_persist_policy_cleans_up(mock_conn, mock_evaluator):
    from uuid import uuid4
    policy_id = str(uuid4())
    state = PolicyRolloutState(
        policy_data=_valid_policy_data(),
        policy_id=policy_id,
    )
    result = await compensate_persist_policy(state, _make_context())

    assert result["rollout_outcome"] == "compensated"
    mock_conn.execute.assert_called_once()
    delete_sql = mock_conn.execute.call_args[0][0]
    assert "DELETE FROM policies" in delete_sql
    mock_evaluator.remove_policy.assert_called_once()


@pytest.mark.asyncio
async def test_compensate_persist_policy_noop_when_no_id(mock_conn, mock_evaluator):
    """Compensation is a no-op when policy_id was never set (persist never ran)."""
    state = PolicyRolloutState(policy_data=_valid_policy_data())
    result = await compensate_persist_policy(state, _make_context())

    mock_conn.execute.assert_not_called()
    mock_evaluator.remove_policy.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Validation rejects bad inputs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_validate_rejects_empty_policy_name():
    data = _valid_policy_data()
    data["policy_name"] = ""
    state = PolicyRolloutState(policy_data=data)
    with pytest.raises(ValueError, match="policy_name must be non-empty"):
        await validate_policy(state, _make_context())


@pytest.mark.asyncio
async def test_validate_rejects_dangerous_condition():
    data = _valid_policy_data()
    data["rules"] = [{"condition": "__import__('os').system('rm -rf /')", "artifact": "x.pex"}]
    state = PolicyRolloutState(policy_data=data)
    with pytest.raises(ValueError, match="Dangerous pattern"):
        await validate_policy(state, _make_context())


@pytest.mark.asyncio
async def test_validate_rejects_empty_rules():
    data = _valid_policy_data()
    data["rules"] = []
    state = PolicyRolloutState(policy_data=data)
    with pytest.raises(ValueError, match="rules must be a non-empty list"):
        await validate_policy(state, _make_context())
