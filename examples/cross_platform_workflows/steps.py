"""
Cross-Platform Workflow Step Functions
========================================
Extracted verbatim from examples/browser_demo/worker.js PYTHON_SETUP.

All `try: from js import ...; except:` blocks are preserved as-is:
  - Browser  → JS FFI succeeds (GPU embedding, wllama, NER model)
  - Cloud / Edge → ImportError; Python fallback runs automatically

No SDK changes required — same YAML + same functions on all three targets.
"""

import json
import math
import random
import re as _re
import uuid

from cross_platform_workflows.state_models import (
    OrderState,
    SensorState,
    TransactionState,
    DocumentState,
    FieldTechState,
    PagedReasoningState,
)
from ruvon.models import StepContext, WorkflowJumpDirective


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 1 — Order Fulfillment
# ══════════════════════════════════════════════════════════════════════════════

def validate_order(state: OrderState, context: StepContext, **_):
    total = sum(
        item.get("price", 0.0) * item.get("qty", 1)
        for item in state.items
    )
    order_id = state.order_id or f"ORD-{random.randint(1000, 9999)}"
    return {"total": round(total, 2), "order_id": order_id}


# Parallel tasks receive state as a plain dict (from model_dump())
def check_warehouse_uk(state: dict, context: StepContext, **_):
    in_stock = random.random() > 0.35  # 65% in stock
    return {"stock_uk": in_stock}


def check_warehouse_eu(state: dict, context: StepContext, **_):
    in_stock = random.random() > 0.35
    return {"stock_eu": in_stock}


def fulfillment_decision(state: OrderState, context: StepContext, **_):
    if not state.stock_uk and not state.stock_eu:
        raise WorkflowJumpDirective(target_step_name="BackorderNotice")
    return {"fulfillment_path": "UK" if state.stock_uk else "EU"}


def process_payment(state: OrderState, context: StepContext, **_):
    pay_ref = f"PAY-{random.randint(100000, 999999)}"
    return {"payment_ref": pay_ref}


def send_confirmation(state: OrderState, context: StepContext, **_):
    return {"status": "SHIPPED"}


def backorder_notice(state: OrderState, context: StepContext, **_):
    # Guard: only run if the jump path brought us here (not already shipped)
    if state.fulfillment_path in ("UK", "EU"):
        return {}   # normal path passed through — no-op, workflow completes
    return {"status": "BACKORDERED", "fulfillment_path": "BACKORDER"}


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 2 — IoT Sensor Pipeline
# ══════════════════════════════════════════════════════════════════════════════

def init_pipeline(state: SensorState, context: StepContext, **_):
    return {
        "device_id": state.device_id or "sensor-001",
        "max_threshold": 50.0,
        "min_threshold": 0.0,
    }


def collect_sensor_data(state: SensorState, context: StepContext, **_):
    readings = [round(25.0 + random.gauss(0, 7), 2) for _ in range(10)]
    readings[3] = round(random.uniform(55.0, 70.0), 2)   # spike above max
    readings[7] = round(random.uniform(-8.0, -1.0), 2)   # dip below min
    return {"readings": readings}


def process_readings(state: SensorState, context: StepContext, **_):
    """Iterate over readings (loop logic inline — identical to a LOOP step)."""
    processed = []
    anomalies = []
    for r in state.readings:
        processed.append(round(r, 2))
        if r > state.max_threshold or r < state.min_threshold:
            anomalies.append(r)
    return {"processed": processed, "anomalies": anomalies}


def compute_statistics(state: SensorState, context: StepContext, **_):
    vals = state.processed or state.readings
    if not vals:
        return {"mean": 0.0, "stddev": 0.0, "anomaly_rate": 0.0}
    n = len(vals)
    mean = sum(vals) / n
    variance = sum((v - mean) ** 2 for v in vals) / n
    stddev = math.sqrt(variance)
    anomaly_rate = round(len(state.anomalies) / max(len(state.readings), 1), 3)
    return {
        "mean": round(mean, 3),
        "stddev": round(stddev, 3),
        "anomaly_rate": anomaly_rate,
    }


def health_decision(state: SensorState, context: StepContext, **_):
    if state.anomaly_rate > 0.25 or state.stddev > 14:
        raise WorkflowJumpDirective(target_step_name="SendAlert")
    elif state.anomaly_rate > 0.1 or state.stddev > 9:
        return {"health_status": "WARNING"}
    else:
        return {"health_status": "HEALTHY"}


def send_alert(state: SensorState, context: StepContext, **_):
    # Guard: only run if the jump path brought us here (not already resolved)
    if state.health_status in ("HEALTHY", "WARNING"):
        return {}   # normal path passed through — no-op
    return {"health_status": "CRITICAL", "alert_sent": True}


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 3 — Transaction Risk Scoring (WebGPU AI / CPU fallback)
# ══════════════════════════════════════════════════════════════════════════════

def extract_features(state: TransactionState, context: StepContext, **_):
    txn_id = state.txn_id or f"TXN-{random.randint(10000, 99999)}"
    text = (
        f"Transaction: {state.amount:.2f} USD at {state.merchant_category} "
        f"in {state.location}"
    )
    return {"feature_text": text, "txn_id": txn_id}


async def gpu_embedding(state: TransactionState, context: StepContext, **_):
    """Calls Transformers.js via Pyodide JS FFI; falls back to CPU on cloud/edge."""
    try:
        from js import runWebGPUInference
        result = await runWebGPUInference(state.feature_text)
        embedding = list(result.embedding.to_py())
        return {
            "embedding": embedding,
            "inference_ms": round(result.latency_ms, 1),
            "device_used": result.device_used,
        }
    except Exception:
        try:
            from js import notifyGpuFallback
            notifyGpuFallback()
        except Exception:
            pass
        # Fallback: deterministic pseudo-embedding
        random.seed(hash(state.feature_text) % (2**32))
        embedding = [random.gauss(0, 0.1) for _ in range(384)]
        mag = math.sqrt(sum(x * x for x in embedding)) or 1.0
        embedding = [x / mag for x in embedding]
        return {"embedding": embedding, "inference_ms": 0.0, "device_used": "cpu-fallback"}


# Risk pattern embeddings — computed lazily on first workflow 3 run
_RISK_PATTERNS = None
_RISK_PATTERN_LABELS = ["high_risk", "low_risk_grocery", "low_risk_subscription"]
_RISK_PATTERN_TEXTS = [
    "high value wire transfer crypto exchange after midnight",
    "small grocery purchase coffee shop weekday morning",
    "online subscription streaming service monthly payment",
]


async def _ensure_risk_patterns():
    global _RISK_PATTERNS
    if _RISK_PATTERNS is not None:
        return
    try:
        from js import runWebGPUInference
        patterns = []
        for text in _RISK_PATTERN_TEXTS:
            result = await runWebGPUInference(text)
            patterns.append(list(result.embedding.to_py()))
        _RISK_PATTERNS = patterns
    except Exception:
        # Hash-based fallback embeddings (deterministic, not semantic)
        patterns = []
        for text in _RISK_PATTERN_TEXTS:
            random.seed(hash(text) % (2**32))
            v = [random.gauss(0, 1) for _ in range(384)]
            mag = math.sqrt(sum(x * x for x in v)) or 1.0
            patterns.append([x / mag for x in v])
        _RISK_PATTERNS = patterns


def _cosine_sim(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-8)


async def compute_risk_score(state: TransactionState, context: StepContext, **_):
    await _ensure_risk_patterns()
    if not state.embedding:
        return {"risk_score": 0.5, "explanation": "No embedding available"}

    emb = state.embedding
    sims = [_cosine_sim(emb, p) for p in _RISK_PATTERNS]

    high_risk_sim = sims[0]
    max_low_sim = max(sims[1], sims[2])

    raw = 0.5 + (high_risk_sim - max_low_sim) * 2.5
    risk_score = round(max(0.0, min(1.0, raw)), 3)
    return {"risk_score": risk_score}


def score_decision(state: TransactionState, context: StepContext, **_):
    if state.risk_score > 0.65:
        raise WorkflowJumpDirective(target_step_name="RecordOutcome")
    elif state.risk_score > 0.40:
        return {
            "decision": "MANUAL_REVIEW",
            "explanation": f"Score {state.risk_score:.3f} — elevated risk, manual review required",
        }
    else:
        return {
            "decision": "APPROVED",
            "explanation": f"Score {state.risk_score:.3f} — low risk, approved",
        }


def record_outcome(state: TransactionState, context: StepContext, **_):
    # Guard: only run if the jump path brought us here (high risk case)
    if state.decision in ("APPROVED", "MANUAL_REVIEW"):
        return {}   # normal path passed through — decision already set
    return {
        "decision": "DECLINED",
        "explanation": f"Score {state.risk_score:.3f} — high risk: transaction declined",
    }


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 4 — Document Summarisation Pipeline
# ══════════════════════════════════════════════════════════════════════════════

_DEMO_TEXTS = [
    """OpenAI has unveiled GPT-5, its most advanced language model to date, representing a significant leap forward in artificial intelligence capabilities. The new model demonstrates unprecedented reasoning abilities, scoring in the top percentile across a wide range of professional and academic benchmarks including law, medicine, and mathematics. GPT-5 features a context window of one million tokens, enabling it to process entire codebases or legal documents in a single pass. The model introduces a novel mixture-of-experts architecture that allows it to selectively activate specialised sub-networks depending on the task at hand, dramatically improving efficiency. Enterprise customers will have access to fine-tuning capabilities that allow the model to adapt to proprietary datasets while maintaining strict data isolation guarantees. The release has prompted immediate reactions from competitors, with Google and Anthropic announcing accelerated development timelines for their own frontier models. Regulatory bodies in the European Union have indicated they will scrutinise the deployment under the AI Act framework, particularly around transparency and high-risk use cases.""",

    """Revenue for the quarter exceeded analyst expectations by a substantial margin, growing 18 percent year-over-year to reach 4.2 billion dollars. The company attributed the outperformance to strong demand in its enterprise software segment, which expanded 31 percent driven by new customer acquisitions and higher average contract values. Gross margins improved by 240 basis points to 68.4 percent, reflecting continued operational leverage and a favourable shift in product mix toward higher-margin subscription offerings. Operating cash flow reached 1.1 billion dollars, enabling the board to authorise an additional share buyback programme of 500 million dollars. The CFO highlighted that international markets, particularly Southeast Asia and Latin America, contributed disproportionately to growth, accounting for 38 percent of new bookings despite representing only 22 percent of the installed base. Looking ahead, management raised full-year guidance to a revenue range of 16.5 to 17.0 billion dollars, implying approximately 15 percent growth at the midpoint.""",

    """Researchers at MIT's Computer Science and Artificial Intelligence Laboratory have developed a breakthrough method for training neural networks that reduces energy consumption by up to 94 percent compared to conventional approaches. The technique, called Sparse Activation with Momentum Reuse, exploits temporal redundancy in sequential data by reusing intermediate computations across adjacent time steps rather than recalculating them from scratch. In benchmark experiments on image recognition and natural language processing tasks, the method achieved accuracy within 0.3 percentage points of the dense baseline while consuming a fraction of the computational resources. The researchers demonstrated the approach on edge hardware including a modified Raspberry Pi and a custom RISC-V chip, showing that inference latency dropped below 15 milliseconds for a 7-billion-parameter language model. Industry observers have noted that the findings could have significant implications for on-device AI in smartphones, medical devices, and autonomous vehicles where battery life and thermal constraints are critical.""",
]


def ingest_document(state: DocumentState, context: StepContext, **_):
    text = (state.raw_text or random.choice(_DEMO_TEXTS)).strip()
    words = text.split()
    lower = text.lower()
    doc_type = "news"
    if any(w in lower for w in ["revenue", "profit", "earnings", "quarter", "shares", "cfo", "bookings"]):
        doc_type = "financial"
    elif any(w in lower for w in ["researchers", "study", "findings", "experiment", "benchmark", "published"]):
        doc_type = "scientific"
    elif any(w in lower for w in ["model", "ai", "software", "architecture", "inference", "neural"]):
        doc_type = "technology"
    return {"raw_text": text, "doc_type": doc_type, "word_count": len(words)}


def preprocess_text(state: DocumentState, context: StepContext, **_):
    text = _re.sub(r'\s+', ' ', state.raw_text).strip()
    sentences = _re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
    return {"sentence_count": len(sentences), "raw_text": text}


async def generate_summary(state: DocumentState, context: StepContext, **_):
    try:
        from js import runSummarisation
        result = await runSummarisation(state.raw_text)
        return {
            "summary": str(result.summary),
            "inference_ms": round(float(result.latency_ms), 1),
            "device_used": str(result.device_used),
            "method": "llm-abstractive",
        }
    except Exception:
        sentences = _re.split(r'(?<=[.!?])\s+', state.raw_text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
        summary = " ".join(sentences[:2]) if sentences else state.raw_text[:200]
        return {
            "summary": summary,
            "inference_ms": 0.0,
            "device_used": "cpu-extractive",
            "method": "extractive-fallback",
        }


def extract_keywords(state: DocumentState, context: StepContext, **_):
    _sw = {"the","a","an","is","in","of","to","and","for","with","that","this","are",
           "was","were","be","been","have","has","from","at","by","or","but","not","on",
           "as","it","its","their","they","we","he","she","his","her","which","who","will",
           "can","more","also","into","over","such","through","these","those","about","than",
           "up","after","before","between","each","no","some","our","your","all","per",
           "while","when","other","even","both","just","yet","still","new"}
    text = (state.summary + " " + state.raw_text).lower()
    words = _re.findall(r'\b[a-zA-Z]{4,}\b', text)
    freq = {}
    for w in words:
        if w not in _sw:
            freq[w] = freq.get(w, 0) + 1
    return {"keywords": sorted(freq, key=freq.get, reverse=True)[:8]}


def quality_decision(state: DocumentState, context: StepContext, **_):
    summary = state.summary or ""
    words   = summary.split()

    if len(words) < 10:
        raise WorkflowJumpDirective(target_step_name="FallbackExtract")

    non_ascii = sum(1 for c in summary if ord(c) > 127)
    if non_ascii / max(len(summary), 1) > 0.12:
        raise WorkflowJumpDirective(target_step_name="FallbackExtract")

    lower = [w.lower() for w in words]
    ngrams = [" ".join(lower[i:i+4]) for i in range(len(lower) - 3)]
    if ngrams and max(ngrams.count(g) for g in set(ngrams)) > 2:
        raise WorkflowJumpDirective(target_step_name="FallbackExtract")

    src_words  = set(state.raw_text.lower().split())
    summ_words = set(lower)
    if summ_words and len(summ_words & src_words) / len(summ_words) < 0.20:
        raise WorkflowJumpDirective(target_step_name="FallbackExtract")

    ratio = round(len(words) / max(state.word_count, 1), 3)
    return {"compression_ratio": ratio, "quality": "GOOD"}


def fallback_extract(state: DocumentState, context: StepContext, **_):
    if state.quality == "GOOD":
        return {}  # normal path — no-op
    sentences = _re.split(r'(?<=[.!?])\s+', state.raw_text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
    summary = " ".join(sentences[:3])
    ratio = round(len(summary.split()) / max(state.word_count, 1), 3)
    return {
        "summary": summary,
        "compression_ratio": ratio,
        "quality": "FALLBACK",
        "method": "extractive-sentence",
    }


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 5 — Air-Gapped Field Tech Triage (PII Redaction + Semantic Routing)
# ══════════════════════════════════════════════════════════════════════════════

_DEMO_REPORT = (
    "The pressure valve on generator 4 is leaking heavily near building C. "
    "John Smith (employee ID: 9982) was near the blast zone during the incident. "
    "Sarah Connor (supervisor) has been notified. Requesting immediate hazmat cleanup "
    "— chemical spill confirmed. CRITICAL: evacuate section B immediately."
)

_SEVERITY_KEYWORDS = {
    "CRITICAL": ["critical", "emergency", "hazmat", "explosion", "fire", "fatality",
                 "blast", "chemical spill", "spill", "leak", "evacuate", "evacuation",
                 "immediate", "severe", "toxic"],
    "HIGH":     ["injury", "hazard", "warning", "danger", "urgent", "toxic", "contamination"],
}

_INCIDENT_KEYWORDS = {
    "HAZMAT":      ["hazmat", "chemical", "toxic", "spill", "contamination", "biohazard"],
    "ELECTRICAL":  ["electrical", "power", "voltage", "electrocution", "short circuit"],
    "MECHANICAL":  ["valve", "pressure", "pump", "generator", "equipment failure"],
    "FIRE":        ["fire", "smoke", "flame", "burning", "combustion"],
}


def _classify_severity(text: str) -> str:
    lower = text.lower()
    for level in ("CRITICAL", "HIGH"):
        if any(kw in lower for kw in _SEVERITY_KEYWORDS[level]):
            return level
    return "NORMAL"


def _classify_incident_type(text: str) -> str:
    lower = text.lower()
    for itype, keywords in _INCIDENT_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return itype
    return "GENERAL"


def capture_report(state: FieldTechState, context: StepContext, **inp):
    text = inp.get("report_text") or state.raw_input or _DEMO_REPORT
    return {"raw_input": text.strip()}


async def run_ner_analysis(state: FieldTechState, context: StepContext, **_):
    try:
        from js import runNERInference
        result = await runNERInference(state.raw_input)
        entities_data = json.loads(str(result.entities_json))
        # Filter to person names (PER) and miscellaneous IDs (MISC)
        pii = [
            e["word"] for e in entities_data
            if e.get("entity_group") in ("PER", "MISC") and len(e.get("word", "")) > 1
        ]
        return {
            "pii_entities": pii,
            "ner_latency_ms": round(float(result.latency_ms), 1),
        }
    except Exception:
        # Fallback: regex-based ID detection only (names missed without model)
        ids = _re.findall(
            r'\b(?:employee\s+ID|ID)[:\s#]?\s*\d{4,}\b',
            state.raw_input,
            _re.IGNORECASE,
        )
        return {"pii_entities": ids, "ner_latency_ms": 0.0}


def build_redacted_payload(state: FieldTechState, context: StepContext, **_):
    redacted = state.raw_input
    for entity in state.pii_entities:
        if entity and len(entity.strip()) > 1:
            redacted = redacted.replace(entity, "[REDACTED]")
    # Also redact bare numeric IDs (e.g. "9982")
    redacted = _re.sub(r'\b\d{4,5}\b', '[ID-REDACTED]', redacted)
    severity = _classify_severity(state.raw_input)
    incident_type = _classify_incident_type(state.raw_input)
    return {
        "redacted_text": redacted,
        "severity": severity,
        "incident_type": incident_type,
    }


def route_by_priority(state: FieldTechState, context: StepContext, **_):
    if state.severity == "CRITICAL":
        raise WorkflowJumpDirective(target_step_name="EscalateIncident")
    return {}


def log_standard_incident(state: FieldTechState, context: StepContext, **_):
    return {
        "routed_to": "standard",
        "saf_record_id": f"SAF-{uuid.uuid4().hex[:8].upper()}",
    }


def escalate_incident(state: FieldTechState, context: StepContext, **_):
    # Guard: normal path passes through here after LogStandard
    if state.routed_to == "standard":
        return {}
    return {
        "routed_to": "escalation",
        "saf_record_id": f"ESC-{uuid.uuid4().hex[:8].upper()}",
    }


def store_for_forward(state: FieldTechState, context: StepContext, **_):
    # SAF record ID is set by log or escalate — confirm sync-pending status
    return {}


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 6 — Paged Reasoning (wllama GGUF / LlamaCpp / simulation fallback)
# ══════════════════════════════════════════════════════════════════════════════

_PAGED_DEMO_PROMPTS = [
    "What does error code E42 mean?",
    "Diagnose an intermittent relay failure on circuit breaker CB-42 under high thermal load with partial arc tracking.",
    "Is the pressure valve green?",
    "Explain multi-step root cause analysis for cascading sensor faults in a distributed SCADA network.",
]


async def assess_complexity(state: PagedReasoningState, context: StepContext, **_):
    """Classify prompt complexity via JS FFI; jump to fast path if simple."""
    try:
        from js import classifyComplexity  # type: ignore[import]
        score = float(await classifyComplexity(state.prompt or _PAGED_DEMO_PROMPTS[0]))
    except Exception:
        # Fallback: heuristic classifier (no JS runtime / FFI not registered)
        text = state.prompt or ""
        token_est = len(text.split())
        complex_keywords = ["diagnos", "analyz", "analys", "explain", "reason", "troubleshoot",
                            "root cause", "cascad", "intermittent", "multi-step",
                            "instruct", "agent", "scrape", "html", "forced", "popup", "spam"]
        keyword_hit = any(kw in text.lower() for kw in complex_keywords)
        score = 1.0 if (token_est > 50 or keyword_hit) else 0.2

    path = "fast_path" if score < 0.4 else "full_inference"
    result = {"complexity_score": round(score, 3), "path_taken": path}
    if score < 0.4:
        raise WorkflowJumpDirective(target_step_name="FastPath")
    return result


async def full_paged_inference(state: PagedReasoningState, context: StepContext, **_):
    """Full multi-shard inference — all shards loaded."""
    try:
        from js import runPagedInference  # type: ignore[import]
        payload = json.dumps({"prompt": state.prompt or _PAGED_DEMO_PROMPTS[1], "threshold": 0.4})
        result = await runPagedInference(payload, 128)
        return {
            "path_taken": "full_inference",
            "generated_text": str(result.text),
            "tokens_generated": int(result.tokens_generated),
            "shards_loaded": int(result.shards_loaded),
            "latency_ms": round(float(result.latency_ms), 1),
        }
    except Exception:
        # Fallback: simulate full inference output without wllama
        return {
            "path_taken": "full_inference",
            "generated_text": (
                "[Simulated full inference] Complex field diagnostic reasoning would appear here. "
                "In a live deployment, 2–3 × 120 MB BitNet shards are loaded from OPFS and "
                "processed sequentially by wllama, producing a detailed root-cause analysis."
            ),
            "tokens_generated": 42,
            "shards_loaded": 3,
            "latency_ms": 0.0,
        }


async def fast_path(state: PagedReasoningState, context: StepContext, **_):
    """Shard-0-only inference — fast path for simple queries."""
    # Guard: normal path passes through here with complexity_score already >= 0.4
    if state.complexity_score >= 0.4:
        return {}
    try:
        from js import runPagedInference  # type: ignore[import]
        payload = json.dumps({"prompt": state.prompt or _PAGED_DEMO_PROMPTS[0], "threshold": 0.9})
        result = await runPagedInference(payload, 64)
        return {
            "path_taken": "fast_path",
            "complexity_score": round(float(result.complexity_score), 3),
            "generated_text": str(result.text),
            "tokens_generated": int(result.tokens_generated),
            "shards_loaded": int(result.shards_loaded),
            "latency_ms": round(float(result.latency_ms), 1),
        }
    except Exception:
        return {
            "path_taken": "fast_path",
            "complexity_score": 0.2,
            "generated_text": (
                "[Simulated fast path] Simple query resolved from shard-0 embedding + "
                "first 2 transformer layers only. Latency ~1.5s, peak RAM ~140 MB."
            ),
            "tokens_generated": 12,
            "shards_loaded": 1,
            "latency_ms": 0.0,
        }


def format_output(state: PagedReasoningState, context: StepContext, **_):
    """Trim generated text and annotate with shard + path metadata."""
    text = (state.generated_text or "").strip()
    if len(text) > 500:
        text = text[:500] + "…"
    return {"generated_text": text}
