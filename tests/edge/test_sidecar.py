"""Tests for the deployment sidecar agent — metrics, health scoring, config apply."""

from __future__ import annotations

import importlib.util
import pathlib
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Direct sidecar module imports (bypass rufus_edge/__init__.py which needs numpy)
# ---------------------------------------------------------------------------

def _import_sidecar(module_leaf: str):
    base = pathlib.Path(__file__).parents[2] / "src" / "rufus_edge" / "sidecar"
    path = base / (module_leaf + ".py")
    spec = importlib.util.spec_from_file_location(f"rufus_edge.sidecar.{module_leaf}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_metrics_mod = _import_sidecar("metrics")
_health_mod = _import_sidecar("health_scorer")
_applier_mod = _import_sidecar("config_applier")


# ---------------------------------------------------------------------------
# DeviceMetrics model
# ---------------------------------------------------------------------------

def test_device_metrics_defaults():
    DeviceMetrics = _metrics_mod.DeviceMetrics
    m = DeviceMetrics()
    assert m.cpu_percent == 0.0
    assert m.ram_percent == 0.0
    assert m.pending_saf_count == 0
    assert m.collected_at > 0


# ---------------------------------------------------------------------------
# Health scorer — rule-based
# ---------------------------------------------------------------------------

def test_health_scorer_perfect_metrics():
    HealthScorer = _health_mod.HealthScorer
    scorer = HealthScorer()
    metrics = {
        "cpu_percent": 10.0,
        "ram_percent": 30.0,
        "pending_saf_count": 5,
        "failed_last_hour": 0,
        "step_latency_p95_ms": 50.0,
    }
    score, issues = scorer._score_rules(metrics)
    assert score == 1.0
    assert issues == []


def test_health_scorer_high_cpu():
    HealthScorer = _health_mod.HealthScorer
    scorer = HealthScorer()
    metrics = {
        "cpu_percent": 96.0,
        "ram_percent": 50.0,
        "pending_saf_count": 0,
        "failed_last_hour": 0,
        "step_latency_p95_ms": 100.0,
    }
    score, issues = scorer._score_rules(metrics)
    assert score < 1.0
    assert any("CPU" in issue for issue in issues)


def test_health_scorer_critical_saf_queue():
    HealthScorer = _health_mod.HealthScorer
    scorer = HealthScorer()
    metrics = {
        "cpu_percent": 20.0,
        "ram_percent": 40.0,
        "pending_saf_count": 250,
        "failed_last_hour": 0,
        "step_latency_p95_ms": 100.0,
    }
    score, issues = scorer._score_rules(metrics)
    assert score <= 0.75
    assert any("SAF" in issue for issue in issues)


def test_health_scorer_multiple_issues():
    HealthScorer = _health_mod.HealthScorer
    scorer = HealthScorer()
    metrics = {
        "cpu_percent": 97.0,
        "ram_percent": 92.0,
        "pending_saf_count": 300,
        "failed_last_hour": 25,
        "step_latency_p95_ms": 3000.0,
    }
    score, issues = scorer._score_rules(metrics)
    assert score < 0.3, f"Expected very low score, got {score}"
    assert len(issues) >= 4


def test_score_device_health_step_function():
    score_fn = _health_mod.score_device_health
    state = MagicMock()
    state.metrics = {
        "cpu_percent": 10.0,
        "ram_percent": 30.0,
        "pending_saf_count": 0,
        "failed_last_hour": 0,
        "step_latency_p95_ms": 50.0,
    }
    result = score_fn(state, None)
    assert "health_score" in result
    assert "should_generate_suggestions" in result
    assert result["health_score"] == 1.0
    assert result["should_generate_suggestions"] is False


def test_score_device_health_triggers_suggestions():
    score_fn = _health_mod.score_device_health
    state = MagicMock()
    state.metrics = {
        "cpu_percent": 97.0,
        "ram_percent": 92.0,
        "pending_saf_count": 300,
        "failed_last_hour": 25,
        "step_latency_p95_ms": 3000.0,
    }
    result = score_fn(state, None)
    assert result["should_generate_suggestions"] is True
    assert result["health_score"] < 0.7


# ---------------------------------------------------------------------------
# Percentile helper
# ---------------------------------------------------------------------------

def test_percentile_helper():
    _percentile = _metrics_mod._percentile
    assert _percentile([], 95) == 0.0
    assert _percentile([100], 95) == 100.0
    assert _percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90) >= 9.0


# ---------------------------------------------------------------------------
# Config applier — hot swap key detection
# ---------------------------------------------------------------------------

def test_hot_swap_key_classification():
    _HOT_SWAP_KEYS = _applier_mod._HOT_SWAP_KEYS
    _RESTART_REQUIRED_KEYS = _applier_mod._RESTART_REQUIRED_KEYS

    assert "fraud_threshold" in _HOT_SWAP_KEYS
    assert "floor_limit" in _HOT_SWAP_KEYS
    assert "execution_provider" in _RESTART_REQUIRED_KEYS
    assert "fraud_threshold" not in _RESTART_REQUIRED_KEYS


# ---------------------------------------------------------------------------
# Risk tier governance
# ---------------------------------------------------------------------------

_decisions_mod = _import_sidecar("decisions")


def _make_state(change_key: str, risk_tier: int = 1):
    """Build a minimal state object with suggestion + risk_tier."""
    state = MagicMock()
    state.suggestion = {"change": {"key": change_key, "value": 500}}
    state.risk_tier = risk_tier
    return state


def _make_context():
    ctx = MagicMock()
    ctx.workflow_id = "wf-test-001"
    return ctx


def test_risk_tier_gate_level1_jumps_to_apply_change():
    """Level 1 key → WorkflowJumpDirective to ApplyChange."""
    from rufus.models import WorkflowJumpDirective as _WJD

    state = _make_state("fraud_threshold")
    ctx = _make_context()

    with pytest.raises(_WJD) as exc_info:
        _decisions_mod.risk_tier_gate(state, ctx)

    assert exc_info.value.target_step_name == "ApplyChange"


def test_risk_tier_gate_level2_falls_through():
    """Level 2 key → returns dict with risk_tier=2 (falls through to ApprovalGate)."""
    state = _make_state("execution_provider")
    ctx = _make_context()

    result = _decisions_mod.risk_tier_gate(state, ctx)

    assert result == {"risk_tier": 2}


def test_risk_tier_gate_level3_falls_through():
    """Level 3 key → returns dict with risk_tier=3 (falls through to DraftPROnly)."""
    state = _make_state("encryption_key")
    ctx = _make_context()

    result = _decisions_mod.risk_tier_gate(state, ctx)

    assert result == {"risk_tier": 3}


def test_risk_tier_gate_unknown_key_defaults_to_level2():
    """Unknown config key defaults to Level 2 (safe fallback)."""
    state = _make_state("totally_unknown_key_xyz")
    ctx = _make_context()

    result = _decisions_mod.risk_tier_gate(state, ctx)

    assert result.get("risk_tier") == 2


def test_draft_pr_only_noop_for_level1():
    """draft_pr_only is a no-op for Level 1 changes (falls through to ApprovalGate)."""
    state = _make_state("fraud_threshold", risk_tier=1)
    ctx = _make_context()

    result = _decisions_mod.draft_pr_only(state, ctx)
    assert result == {}


def test_draft_pr_only_noop_for_level2():
    """draft_pr_only is a no-op for Level 2 changes."""
    state = _make_state("execution_provider", risk_tier=2)
    ctx = _make_context()

    result = _decisions_mod.draft_pr_only(state, ctx)
    assert result == {}


def test_draft_pr_only_jumps_to_report_outcome_for_level3(monkeypatch):
    """draft_pr_only raises WorkflowJumpDirective to ReportOutcome for Level 3."""
    from rufus.models import WorkflowJumpDirective as _WJD
    import urllib.request

    state = _make_state("encryption_key", risk_tier=3)
    ctx = _make_context()

    # Mock the HTTP call so no real request is made
    mock_response = MagicMock()
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.read = MagicMock(return_value=b'{"pr_url": "https://github.com/org/repo/pull/42"}')

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: mock_response)

    with pytest.raises(_WJD) as exc_info:
        _decisions_mod.draft_pr_only(state, ctx)

    assert exc_info.value.target_step_name == "ReportOutcome"


def test_deployment_monitor_yaml_has_risk_tier_gate():
    """deployment_monitor.yaml must contain RiskTierGate and DraftPROnly steps."""
    import yaml
    from pathlib import Path

    yaml_path = Path("config/workflows/deployment_monitor.yaml")
    if not yaml_path.exists():
        pytest.skip("deployment_monitor.yaml not found")

    config = yaml.safe_load(yaml_path.read_text())
    step_names = [s["name"] for s in config.get("steps", [])]

    assert "RiskTierGate" in step_names, "RiskTierGate step missing from deployment_monitor.yaml"
    assert "DraftPROnly" in step_names, "DraftPROnly step missing from deployment_monitor.yaml"

    # RiskTierGate must appear BEFORE ApprovalGate
    assert step_names.index("RiskTierGate") < step_names.index("ApprovalGate")
    # DraftPROnly must appear BEFORE ApprovalGate
    assert step_names.index("DraftPROnly") < step_names.index("ApprovalGate")
