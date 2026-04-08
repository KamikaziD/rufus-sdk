"""Sidecar Step 1 — Collect device metrics.

Gathers CPU, RAM, queue depth, and step latency data from the local
RufusEdgeAgent. Aggregates into summary statistics — no raw transaction
IDs or card numbers are collected; only counts and latency percentiles.

This module is a standard Rufus step function callable:
  def collect_device_metrics(state, context, **kwargs) -> dict
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DeviceMetrics(BaseModel):
    """Aggregated device health metrics (no PII, no raw transactions)."""
    # System
    cpu_percent: float = Field(0.0, description="CPU usage 0-100")
    ram_used_mb: float = Field(0.0, description="RAM used in MB")
    ram_total_mb: float = Field(0.0, description="Total RAM in MB")
    ram_percent: float = Field(0.0, description="RAM usage 0-100")

    # Workflow engine
    pending_saf_count: int = Field(0, description="Transactions queued in SAF")
    active_workflow_count: int = Field(0, description="Currently running workflows")
    failed_last_hour: int = Field(0, description="Failed workflow count in last hour")

    # Latency (p95, ms)
    step_latency_p95_ms: float = Field(0.0, description="95th percentile step execution latency")
    http_latency_p95_ms: float = Field(0.0, description="95th percentile HTTP step latency")

    # Timestamp
    collected_at: float = Field(default_factory=time.time)


class SidecarState(BaseModel):
    """Workflow state for the DeploymentMonitor sidecar workflow."""
    # Collected by CollectMetrics
    metrics: Optional[Dict[str, Any]] = Field(default=None)
    current_config: Optional[Dict[str, Any]] = Field(default=None)

    # Set by ScoreHealth
    health_score: float = Field(0.0, description="Device health 0.0–1.0")

    # Set by GenerateSuggestions — the improvement proposal
    suggestion: Optional[Dict[str, Any]] = Field(default=None)

    # Set by ApprovalGate HUMAN_IN_LOOP resume input
    approved: bool = Field(False)
    operator_notes: Optional[str] = Field(default=None)

    # Set by ApplyChange
    apply_outcome: Optional[str] = Field(default=None)

    # Set by RiskTierGate (added in Part E)
    risk_tier: int = Field(1, description="Risk tier 1/2/3 for the suggested change")


def collect_device_metrics(state: Any, context: Any, **kwargs) -> Dict[str, Any]:
    """Rufus step function: collect device metrics and return as state update.

    Returns:
        dict with 'metrics' key containing a DeviceMetrics-compatible dict.
    """
    metrics = _gather_metrics()
    logger.info(
        "[Sidecar] Metrics: cpu=%.1f%% ram=%.1f%% saf_queue=%d failed_1h=%d",
        metrics.cpu_percent,
        metrics.ram_percent,
        metrics.pending_saf_count,
        metrics.failed_last_hour,
    )
    return {"metrics": metrics.model_dump()}


def _gather_metrics() -> DeviceMetrics:
    """Gather system + workflow engine metrics."""
    cpu_pct = 0.0
    ram_used = 0.0
    ram_total = 0.0
    ram_pct = 0.0

    try:
        import psutil
        cpu_pct = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        ram_total = mem.total / 1_048_576
        ram_used = mem.used / 1_048_576
        ram_pct = mem.percent
    except ImportError:
        logger.debug("[Sidecar] psutil not available; skipping system metrics")

    saf_count, active_count, failed_1h = _query_workflow_engine()
    step_p95, http_p95 = _query_latency_metrics()

    return DeviceMetrics(
        cpu_percent=cpu_pct,
        ram_used_mb=ram_used,
        ram_total_mb=ram_total,
        ram_percent=ram_pct,
        pending_saf_count=saf_count,
        active_workflow_count=active_count,
        failed_last_hour=failed_1h,
        step_latency_p95_ms=step_p95,
        http_latency_p95_ms=http_p95,
    )


def _query_workflow_engine() -> tuple[int, int, int]:
    """Query the local SQLite persistence for queue + failure counts."""
    db_path = os.environ.get("RUVON_EDGE_DB_PATH", "edge_workflows.db")
    try:
        import sqlite3
        con = sqlite3.connect(db_path, timeout=2.0)
        saf = con.execute(
            "SELECT COUNT(*) FROM workflow_executions WHERE status = 'SAF_QUEUED'"
        ).fetchone()[0]
        active = con.execute(
            "SELECT COUNT(*) FROM workflow_executions WHERE status = 'RUNNING'"
        ).fetchone()[0]
        failed = con.execute(
            "SELECT COUNT(*) FROM workflow_executions "
            "WHERE status IN ('FAILED','FAILED_ROLLED_BACK') "
            "AND created_at > datetime('now', '-1 hour')"
        ).fetchone()[0]
        con.close()
        return saf, active, failed
    except Exception as e:
        logger.debug("[Sidecar] Could not query workflow engine: %s", e)
        return 0, 0, 0


def _query_latency_metrics() -> tuple[float, float]:
    """Query p95 latency from workflow_metrics table (last 100 records)."""
    db_path = os.environ.get("RUVON_EDGE_DB_PATH", "edge_workflows.db")
    try:
        import sqlite3
        con = sqlite3.connect(db_path, timeout=2.0)
        rows = con.execute(
            "SELECT metric_value FROM workflow_metrics "
            "WHERE metric_name = 'step_duration_ms' "
            "ORDER BY recorded_at DESC LIMIT 100"
        ).fetchall()
        latencies = sorted(r[0] for r in rows if r[0] is not None)
        p95 = _percentile(latencies, 95) if latencies else 0.0

        http_rows = con.execute(
            "SELECT metric_value FROM workflow_metrics "
            "WHERE metric_name = 'http_duration_ms' "
            "ORDER BY recorded_at DESC LIMIT 100"
        ).fetchall()
        http_latencies = sorted(r[0] for r in http_rows if r[0] is not None)
        http_p95 = _percentile(http_latencies, 95) if http_latencies else 0.0
        con.close()
        return p95, http_p95
    except Exception as e:
        logger.debug("[Sidecar] Could not query latency metrics: %s", e)
        return 0.0, 0.0


def _percentile(sorted_values: list, p: int) -> float:
    if not sorted_values:
        return 0.0
    idx = int(len(sorted_values) * p / 100)
    return float(sorted_values[min(idx, len(sorted_values) - 1)])
