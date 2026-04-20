"""
Cross-Platform Workflow State Models
=====================================
Shared across all three Ruvon runtime targets:
  - Browser  (Pyodide + BrowserSyncExecutor)
  - Cloud     (FastAPI server + Celery workers + PostgreSQL)
  - Edge      (RuvonEdgeAgent + SQLite)

Same YAML drives all three; only the execution backend and AI
inference quality differ.
"""

from pydantic import BaseModel


# ── Workflow 1 — Order Fulfillment ────────────────────────────────────────────
class OrderState(BaseModel):
    order_id: str = ""
    items: list = []
    total: float = 0.0
    stock_uk: bool = False
    stock_eu: bool = False
    payment_ref: str = ""
    status: str = ""
    fulfillment_path: str = ""


# ── Workflow 2 — IoT Sensor Pipeline ─────────────────────────────────────────
class SensorState(BaseModel):
    device_id: str = "sensor-001"
    readings: list = []
    processed: list = []
    anomalies: list = []
    mean: float = 0.0
    stddev: float = 0.0
    anomaly_rate: float = 0.0
    health_status: str = ""
    alert_sent: bool = False
    max_threshold: float = 50.0
    min_threshold: float = 0.0


# ── Workflow 3 — Transaction Risk Scoring ────────────────────────────────────
class TransactionState(BaseModel):
    txn_id: str = ""
    amount: float = 100.0
    merchant_category: str = "retail"
    location: str = "London"
    feature_text: str = ""
    embedding: list = []
    risk_score: float = 0.0
    decision: str = ""
    explanation: str = ""
    inference_ms: float = 0.0
    device_used: str = ""


# ── Workflow 4 — Document Summarisation ──────────────────────────────────────
class DocumentState(BaseModel):
    raw_text: str = ""
    doc_type: str = ""
    word_count: int = 0
    sentence_count: int = 0
    summary: str = ""
    keywords: list = []
    compression_ratio: float = 0.0
    quality: str = ""
    inference_ms: float = 0.0
    device_used: str = ""
    method: str = ""


# ── Workflow 5 — Field Tech Triage ───────────────────────────────────────────
class FieldTechState(BaseModel):
    raw_input: str = ""
    severity: str = "UNKNOWN"
    incident_type: str = "GENERAL"
    redacted_text: str = ""
    pii_entities: list = []
    saf_record_id: str = ""
    routed_to: str = ""
    ner_latency_ms: float = 0.0


# ── Workflow 6 — Paged Reasoning ─────────────────────────────────────────────
class PagedReasoningState(BaseModel):
    prompt: str = ""
    complexity_score: float = 0.0
    shards_loaded: int = 0
    generated_text: str = ""
    tokens_generated: int = 0
    latency_ms: float = 0.0
    path_taken: str = ""
