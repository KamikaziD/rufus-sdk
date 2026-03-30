"""Rufus Edge — Deployment Sidecar Agent.

The sidecar is a Rufus workflow that runs alongside the main edge agent,
autonomously monitoring device health and surfacing improvement proposals
to human operators via HITL before applying any changes.

Architecture:
  - CollectMetrics  → gathers CPU/RAM/queue/latency data
  - ScoreHealth     → ONNX anomaly score (local, no cloud call)
  - GenerateSuggestions → local Ollama LLM proposes ONE config change
  - ApprovalGate    → HITL via cloud control plane (SAF when offline)
  - ApplyChange     → WASM-sandboxed config write (hot-swap or drain+restart)
  - ReportOutcome   → HTTP to cloud control plane

See config/workflows/deployment_monitor.yaml for the workflow definition.
"""

from rufus_edge.sidecar.metrics import collect_device_metrics, DeviceMetrics
from rufus_edge.sidecar.health_scorer import HealthScorer, score_device_health
from rufus_edge.sidecar.decisions import health_gate, approval_gate

__all__ = [
    "collect_device_metrics",
    "DeviceMetrics",
    "HealthScorer",
    "score_device_health",
    "health_gate",
    "approval_gate",
]
