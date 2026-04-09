"""Sidecar Step 2 — Score device health.

Evaluates collected metrics and produces a 0.0–1.0 health score.
A score < 0.7 triggers the suggestion generation stage.

Two modes:
  - ONNX model (if model file exists): fast inference, no cloud call
  - Rule-based fallback (always available): deterministic scoring

The ONNX model is optional; rule-based scoring is always used as fallback.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Rule-based thresholds
_WARN_CPU = 80.0      # > 80% CPU is concerning
_CRIT_CPU = 95.0
_WARN_RAM = 75.0
_CRIT_RAM = 90.0
_WARN_SAF = 50        # > 50 queued SAF transactions
_CRIT_SAF = 200
_WARN_FAIL = 5        # > 5 failures in last hour
_CRIT_FAIL = 20
_WARN_LATENCY = 500   # > 500ms p95 step latency
_CRIT_LATENCY = 2000

_HEALTH_TRIGGER = 0.7  # Score below this → generate suggestions


def score_device_health(state: Any, context: Any, **kwargs) -> Dict[str, Any]:
    """Ruvon step function: score device health from collected metrics.

    Reads state.metrics (set by collect_device_metrics step).
    Returns dict with health_score and health_issues list.
    """
    metrics = getattr(state, "metrics", {}) if hasattr(state, "metrics") else {}
    scorer = HealthScorer()
    score, issues = scorer.score(metrics, context)

    logger.info(
        "[Sidecar] Health score: %.2f  issues: %s",
        score, issues or "none",
    )

    return {
        "health_score": round(score, 3),
        "health_issues": issues,
        "should_generate_suggestions": score < _HEALTH_TRIGGER,
    }


class HealthScorer:
    """Scores device health from a metrics dict.

    Tries ONNX model first; falls back to rule-based scoring.
    """

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or "models/health_scorer_v1.onnx"
        self._onnx_model = None

    def score(self, metrics: Dict, context: Any) -> tuple[float, list[str]]:
        """Return (health_score, issues_list).

        health_score: 1.0 = perfect, 0.0 = critical.
        """
        if self._try_load_onnx():
            return self._score_onnx(metrics)
        return self._score_rules(metrics)

    def _try_load_onnx(self) -> bool:
        """Try to load ONNX model. Returns False if not available."""
        if self._onnx_model is not None:
            return True
        try:
            import onnxruntime as ort
            from pathlib import Path
            if Path(self.model_path).exists():
                self._onnx_model = ort.InferenceSession(self.model_path)
                logger.debug("[HealthScorer] Loaded ONNX model: %s", self.model_path)
                return True
        except (ImportError, Exception) as e:
            logger.debug("[HealthScorer] ONNX not available: %s", e)
        return False

    def _score_onnx(self, metrics: Dict) -> tuple[float, list[str]]:
        """Score using ONNX model (falls back to rules on error)."""
        try:
            import numpy as np
            features = [
                metrics.get("cpu_percent", 0.0) / 100.0,
                metrics.get("ram_percent", 0.0) / 100.0,
                min(metrics.get("pending_saf_count", 0) / 200.0, 1.0),
                min(metrics.get("failed_last_hour", 0) / 20.0, 1.0),
                min(metrics.get("step_latency_p95_ms", 0.0) / 2000.0, 1.0),
            ]
            inputs = {self._onnx_model.get_inputs()[0].name: np.array([features], dtype=np.float32)}
            outputs = self._onnx_model.run(None, inputs)
            score = float(outputs[0][0][0])
            return score, []
        except Exception as e:
            logger.warning("[HealthScorer] ONNX inference failed, using rules: %s", e)
            return self._score_rules(metrics)

    def _score_rules(self, metrics: Dict) -> tuple[float, list[str]]:
        """Rule-based health scoring. Deducts points for each violation."""
        score = 1.0
        issues = []

        cpu = metrics.get("cpu_percent", 0.0)
        if cpu > _CRIT_CPU:
            score -= 0.30
            issues.append(f"CPU critical: {cpu:.0f}% (threshold: {_CRIT_CPU}%)")
        elif cpu > _WARN_CPU:
            score -= 0.15
            issues.append(f"CPU high: {cpu:.0f}% (threshold: {_WARN_CPU}%)")

        ram = metrics.get("ram_percent", 0.0)
        if ram > _CRIT_RAM:
            score -= 0.25
            issues.append(f"RAM critical: {ram:.0f}% (threshold: {_CRIT_RAM}%)")
        elif ram > _WARN_RAM:
            score -= 0.10
            issues.append(f"RAM high: {ram:.0f}% (threshold: {_WARN_RAM}%)")

        saf = metrics.get("pending_saf_count", 0)
        if saf > _CRIT_SAF:
            score -= 0.25
            issues.append(f"SAF queue critical: {saf} transactions (threshold: {_CRIT_SAF})")
        elif saf > _WARN_SAF:
            score -= 0.10
            issues.append(f"SAF queue growing: {saf} transactions (threshold: {_WARN_SAF})")

        failed = metrics.get("failed_last_hour", 0)
        if failed > _CRIT_FAIL:
            score -= 0.20
            issues.append(f"Failure rate critical: {failed}/hr (threshold: {_CRIT_FAIL})")
        elif failed > _WARN_FAIL:
            score -= 0.08
            issues.append(f"Failure rate elevated: {failed}/hr (threshold: {_WARN_FAIL})")

        latency = metrics.get("step_latency_p95_ms", 0.0)
        if latency > _CRIT_LATENCY:
            score -= 0.15
            issues.append(f"Latency critical: {latency:.0f}ms p95 (threshold: {_CRIT_LATENCY}ms)")
        elif latency > _WARN_LATENCY:
            score -= 0.05
            issues.append(f"Latency elevated: {latency:.0f}ms p95 (threshold: {_WARN_LATENCY}ms)")

        return max(0.0, score), issues
