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
