/**
 * Rufus Browser Runtime — Web Worker
 *
 * Runs Pyodide (Python 3.12) + Transformers.js (WebGPU) in a dedicated worker thread.
 * Serves three demo workflows:
 *   1. OrderFulfillment   — STANDARD + PARALLEL + WorkflowJumpDirective
 *   2. IoTSensorPipeline  — STANDARD steps (loop logic inline) + WorkflowJumpDirective
 *   3. TransactionRiskScoring — STANDARD + async GPU embedding via JS FFI
 */

// No top-level static imports — use dynamic imports inside init() so CDN fetch
// failures produce a real error message instead of an opaque worker onerror.

// ─── Transformers.js (loaded dynamically in init) ─────────────────────────────
// Candidates in preference order; first successful load wins.
const TRANSFORMERS_CDNS = [
    "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3/dist/transformers.min.js",
    "https://cdn.jsdelivr.net/npm/@xenova/transformers@2/dist/transformers.min.js",
];

const _gpuDevice = (typeof navigator !== "undefined" && "gpu" in navigator) ? "webgpu" : "wasm";
let _extractor = null;
let _pipeline = null;   // set after dynamic import

/**
 * Called from Python via `from js import runWebGPUInference`.
 * Returns a plain JS object: { embedding: TypedArray, latency_ms, device_used }
 */
globalThis.runWebGPUInference = async (text) => {
    if (!_pipeline) throw new Error("Transformers.js not loaded");
    const t0 = performance.now();
    if (!_extractor) {
        self.postMessage({ type: "model_loading" });
        _extractor = await _pipeline(
            "feature-extraction",
            "Xenova/all-MiniLM-L6-v2",
            { device: _gpuDevice }
        );
        self.postMessage({ type: "model_ready", device: _gpuDevice });
    }
    const out = await _extractor(text, { pooling: "mean", normalize: true });
    return {
        embedding: out.data,
        latency_ms: performance.now() - t0,
        device_used: _gpuDevice,
    };
};

// ─── Python → JS callbacks ────────────────────────────────────────────────────
globalThis.notifyStepDone = (stepName, resultJson) => {
    self.postMessage({ type: "step_done", stepName, result: JSON.parse(resultJson) });
};

globalThis.notifyWorkflowDone = (stateJson) => {
    self.postMessage({ type: "workflow_done", state: JSON.parse(stateJson) });
};

globalThis.notifyWorkflowError = (msg) => {
    self.postMessage({ type: "workflow_error", message: msg });
};

// ─── IndexedDB helpers (exposed to Python via Pyodide FFI) ───────────────────
const IDB_NAME    = "rufus-demo";
const IDB_VERSION = 1;

function openIDB() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open(IDB_NAME, IDB_VERSION);
        req.onupgradeneeded = (e) => {
            const db = e.target.result;
            if (!db.objectStoreNames.contains("workflows")) {
                const ws = db.createObjectStore("workflows", { keyPath: "id" });
                ws.createIndex("by_type",    "workflow_type", { unique: false });
                ws.createIndex("by_created", "created_at",    { unique: false });
            }
            if (!db.objectStoreNames.contains("audit_events")) {
                const as = db.createObjectStore("audit_events", { autoIncrement: true });
                as.createIndex("by_workflow", "workflow_id", { unique: false });
            }
        };
        req.onsuccess = (e) => resolve(e.target.result);
        req.onerror   = (e) => reject(e.target.error);
    });
}

globalThis.idbPutWorkflow = async (json) => {
    const db = await openIDB();
    return new Promise((resolve, reject) => {
        const tx  = db.transaction("workflows", "readwrite");
        tx.objectStore("workflows").put(JSON.parse(json));
        tx.oncomplete = () => { db.close(); resolve(); };
        tx.onerror    = (e) => { db.close(); reject(e.target.error); };
    });
};

globalThis.idbGetWorkflow = async (id) => {
    const db = await openIDB();
    return new Promise((resolve, reject) => {
        const tx  = db.transaction("workflows", "readonly");
        const req = tx.objectStore("workflows").get(id);
        req.onsuccess = (e) => {
            db.close();
            resolve(e.target.result ? JSON.stringify(e.target.result) : null);
        };
        req.onerror = (e) => { db.close(); reject(e.target.error); };
    });
};

globalThis.idbListWorkflows = async () => {
    const db = await openIDB();
    return new Promise((resolve, reject) => {
        const tx  = db.transaction("workflows", "readonly");
        const req = tx.objectStore("workflows").getAll();
        req.onsuccess = (e) => {
            db.close();
            const sorted = (e.target.result || []).sort(
                (a, b) => (b.created_at || "").localeCompare(a.created_at || "")
            );
            resolve(JSON.stringify(sorted));
        };
        req.onerror = (e) => { db.close(); reject(e.target.error); };
    });
};

globalThis.idbLogAudit = async (json) => {
    const db = await openIDB();
    return new Promise((resolve, reject) => {
        const tx = db.transaction("audit_events", "readwrite");
        tx.objectStore("audit_events").add(JSON.parse(json));
        tx.oncomplete = () => { db.close(); resolve(); };
        tx.onerror    = (e) => { db.close(); reject(e.target.error); };
    });
};

globalThis.idbGetHistory = async (n) => {
    const db = await openIDB();
    return new Promise((resolve, reject) => {
        const tx  = db.transaction("workflows", "readonly");
        const req = tx.objectStore("workflows").getAll();
        req.onsuccess = (e) => {
            db.close();
            const sorted = (e.target.result || []).sort(
                (a, b) => (b.created_at || "").localeCompare(a.created_at || "")
            );
            resolve(JSON.stringify(sorted.slice(0, n)));
        };
        req.onerror = (e) => { db.close(); reject(e.target.error); };
    });
};

globalThis.idbClear = async () => {
    const db = await openIDB();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(["workflows", "audit_events"], "readwrite");
        tx.objectStore("workflows").clear();
        tx.objectStore("audit_events").clear();
        tx.oncomplete = () => { db.close(); resolve(); };
        tx.onerror    = (e) => { db.close(); reject(e.target.error); };
    });
};

// ─── Python setup string ──────────────────────────────────────────────────────
const PYTHON_SETUP = `
import os
# Disable uvloop and orjson before rufus/__init__.py runs — the mock packages
# have no attributes, and these optimisations don't apply in Pyodide anyway.
os.environ["RUFUS_USE_UVLOOP"] = "false"
os.environ["RUFUS_USE_ORJSON"] = "false"

import asyncio
import json
import math
import random
import uuid

from pydantic import BaseModel
from typing import List, Optional, Dict, Any

from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
from rufus.builder import WorkflowBuilder
from rufus.models import (
    WorkflowStep, ParallelWorkflowStep, ParallelExecutionTask,
    StepContext, WorkflowJumpDirective,
    MergeStrategy, MergeConflictBehavior,
)
from rufus.workflow import Workflow

# ── Global browser function registry (for PARALLEL tasks) ─────────────────────
_BROWSER_FUNCS: dict = {}


# ── BrowserSyncExecutor ────────────────────────────────────────────────────────
class BrowserSyncExecutor(SyncExecutor):
    """Thread-free executor for Pyodide. Runs parallel tasks sequentially."""

    async def initialize(self, engine):
        self._engine = engine
        self._thread_pool_executor = None  # No threads in Pyodide
        self._loop = asyncio.get_event_loop()

    async def dispatch_parallel_tasks(
        self, tasks, state_data, workflow_id, current_step_index, **kw
    ):
        results = {}
        for task in tasks:
            func = _BROWSER_FUNCS.get(task.func_path)
            if func is None:
                raise ValueError(f"[BrowserSyncExecutor] No func registered for: {task.func_path}")
            ctx = StepContext(
                workflow_id=workflow_id,
                step_name=task.name,
                previous_step_result=None,
            )
            extra = task.kwargs or {}
            if asyncio.iscoroutinefunction(func):
                r = await func(state_data, ctx, **extra)
            else:
                r = func(state_data, ctx, **extra)
            if isinstance(r, dict):
                results.update(r)
        return {
            "_async_dispatch": False,
            "_sync_parallel_result": results,
            "task_results": results,
            "errors": {},
        }


# ── BrowserObserver ────────────────────────────────────────────────────────────
class BrowserObserver:
    """Bridges workflow events to JS via Pyodide FFI."""

    async def on_step_executed(self, wf_id, step_name, step_index, status, result, state):
        try:
            from js import notifyStepDone
            notifyStepDone(step_name, json.dumps(result or {}))
        except Exception:
            pass

    async def on_workflow_completed(self, wf_id, wf_type, state):
        try:
            from js import notifyWorkflowDone
            notifyWorkflowDone(json.dumps(
                state.model_dump() if hasattr(state, "model_dump") else {}
            ))
        except Exception:
            pass

    async def on_workflow_failed(self, wf_id, wf_type, error, state):
        try:
            from js import notifyWorkflowError
            notifyWorkflowError(str(error))
        except Exception:
            pass

    # Required no-ops
    async def on_workflow_started(self, wf_id, wf_type, state): pass
    async def on_workflow_status_changed(self, *a, **kw): pass
    async def on_workflow_rolled_back(self, *a, **kw): pass
    async def on_step_failed(self, *a, **kw): pass
    async def initialize(self): pass
    async def close(self): pass


# ── IndexedDBPersistence ───────────────────────────────────────────────────────
class IndexedDBPersistence(InMemoryPersistence):
    """InMemoryPersistence that mirrors workflow state and audit events to IndexedDB."""

    async def save_workflow(self, workflow_id: str, workflow_data):
        await super().save_workflow(workflow_id, workflow_data)
        try:
            import time as _t
            from js import idbPutWorkflow
            await idbPutWorkflow(json.dumps({
                **workflow_data,
                "created_at": workflow_data.get("created_at") or
                              _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime()),
            }))
        except Exception:
            pass

    async def load_workflow(self, workflow_id: str):
        result = await super().load_workflow(workflow_id)
        if result:
            return result
        try:
            from js import idbGetWorkflow
            raw = await idbGetWorkflow(workflow_id)
            if raw:
                data = json.loads(str(raw))
                await super().save_workflow(workflow_id, data)
                return data
        except Exception:
            pass
        return None

    async def list_workflows(self, **filters):
        results = await super().list_workflows(**filters)
        if results:
            return results
        try:
            from js import idbListWorkflows
            all_wfs = json.loads(str(await idbListWorkflows()))
            for key, val in filters.items():
                all_wfs = [w for w in all_wfs if w.get(key) == val]
            return all_wfs
        except Exception:
            return []

    async def log_audit_event(self, workflow_id: str, event_type: str,
                              step_name=None, **kwargs):
        await super().log_audit_event(
            workflow_id, event_type, step_name=step_name, **kwargs)
        try:
            import time as _t
            from js import idbLogAudit
            await idbLogAudit(json.dumps({
                "workflow_id": workflow_id,
                "event_type": event_type,
                "step_name": step_name,
                "ts": _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime()),
            }))
        except Exception:
            pass


# ── Shared providers ───────────────────────────────────────────────────────────
_persistence = IndexedDBPersistence()
_executor = BrowserSyncExecutor()
_observer = BrowserObserver()
_builder = WorkflowBuilder({}, SimpleExpressionEvaluator, Jinja2TemplateEngine)

await _persistence.initialize()
await _executor.initialize(None)


# ── Workflow factory ───────────────────────────────────────────────────────────
async def _make_workflow(wf_type, steps, state_class, initial_data=None):
    state = state_class(**(initial_data or {}))
    return Workflow(
        workflow_type=wf_type,
        workflow_steps=steps,
        initial_state_model=state,
        state_model_path="__browser__",
        persistence_provider=_persistence,
        execution_provider=_executor,
        workflow_builder=_builder,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=_observer,
    )


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 1 — Order Fulfillment
# Steps: ValidateOrder → CheckInventory (PARALLEL) → FulfillmentDecision →
#         ProcessPayment → SendConfirmation
#        ↳ [jump if out of stock] → BackorderNotice
# ══════════════════════════════════════════════════════════════════════════════

class OrderState(BaseModel):
    order_id: str = ""
    items: list = []
    total: float = 0.0
    stock_uk: bool = False
    stock_eu: bool = False
    payment_ref: str = ""
    status: str = ""
    fulfillment_path: str = ""


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


# Register parallel task functions by their pseudo-path key
_BROWSER_FUNCS["__br__.check_warehouse_uk"] = check_warehouse_uk
_BROWSER_FUNCS["__br__.check_warehouse_eu"] = check_warehouse_eu


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


wf1_steps = [
    WorkflowStep(name="ValidateOrder",        func=validate_order,        automate_next=True),
    ParallelWorkflowStep(
        name="CheckInventory",
        tasks=[
            ParallelExecutionTask(name="check_uk", func_path="__br__.check_warehouse_uk"),
            ParallelExecutionTask(name="check_eu", func_path="__br__.check_warehouse_eu"),
        ],
        merge_strategy=MergeStrategy.SHALLOW,
        merge_conflict_behavior=MergeConflictBehavior.PREFER_NEW,
        automate_next=True,
    ),
    WorkflowStep(name="FulfillmentDecision",  func=fulfillment_decision,  automate_next=True),
    WorkflowStep(name="ProcessPayment",        func=process_payment,       automate_next=True),
    WorkflowStep(name="SendConfirmation",      func=send_confirmation,     automate_next=False),
    WorkflowStep(name="BackorderNotice",       func=backorder_notice,      automate_next=False),
]


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 2 — IoT Sensor Pipeline
# Steps: InitPipeline → CollectSensorData → ProcessReadings → ComputeStatistics
#         → HealthDecision → [jump if critical] → SendAlert
# ══════════════════════════════════════════════════════════════════════════════

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


def init_pipeline(state: SensorState, context: StepContext, **_):
    return {
        "device_id": state.device_id or "sensor-001",
        "max_threshold": 50.0,
        "min_threshold": 0.0,
    }


def collect_sensor_data(state: SensorState, context: StepContext, **_):
    # 10 synthetic readings with realistic noise
    readings = [round(25.0 + random.gauss(0, 7), 2) for _ in range(10)]
    # Inject anomalies to make the demo interesting
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


wf2_steps = [
    WorkflowStep(name="InitPipeline",       func=init_pipeline,       automate_next=True),
    WorkflowStep(name="CollectSensorData",  func=collect_sensor_data, automate_next=True),
    WorkflowStep(name="ProcessReadings",    func=process_readings,    automate_next=True),
    WorkflowStep(name="ComputeStatistics",  func=compute_statistics,  automate_next=True),
    WorkflowStep(name="HealthDecision",     func=health_decision,     automate_next=True),
    WorkflowStep(name="SendAlert",          func=send_alert,          automate_next=False),
]


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 3 — Transaction Risk Scoring (WebGPU AI)
# Steps: ExtractFeatures → GPUEmbedding → ComputeRiskScore → ScoreDecision
#        → [jump if high risk] → RecordOutcome
# ══════════════════════════════════════════════════════════════════════════════

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


def extract_features(state: TransactionState, context: StepContext, **_):
    txn_id = state.txn_id or f"TXN-{random.randint(10000, 99999)}"
    text = (
        f"Transaction: {state.amount:.2f} USD at {state.merchant_category} "
        f"in {state.location}"
    )
    return {"feature_text": text, "txn_id": txn_id}


async def gpu_embedding(state: TransactionState, context: StepContext, **_):
    """Calls Transformers.js via Pyodide JS FFI."""
    try:
        from js import runWebGPUInference
        result = await runWebGPUInference(state.feature_text)
        embedding = list(result.embedding.to_py())
        return {
            "embedding": embedding,
            "inference_ms": round(result.latency_ms, 1),
            "device_used": result.device_used,
        }
    except Exception as e:
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

    # Linearly map similarity advantage to [0, 1]
    # Positive advantage → higher risk score
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


wf3_steps = [
    WorkflowStep(name="ExtractFeatures",  func=extract_features,   automate_next=True),
    WorkflowStep(name="GPUEmbedding",     func=gpu_embedding,      automate_next=True),
    WorkflowStep(name="ComputeRiskScore", func=compute_risk_score, automate_next=True),
    WorkflowStep(name="ScoreDecision",    func=score_decision,     automate_next=True),
    WorkflowStep(name="RecordOutcome",    func=record_outcome,     automate_next=False),
]


# ── Main entry point ───────────────────────────────────────────────────────────
async def run_workflow(wf_type: str, data_json: str) -> str:
    data = json.loads(data_json) if data_json else {}

    if wf_type == "OrderFulfillment":
        wf = await _make_workflow(wf_type, wf1_steps, OrderState, data)
    elif wf_type == "IoTSensorPipeline":
        wf = await _make_workflow(wf_type, wf2_steps, SensorState, data)
    elif wf_type == "TransactionRiskScoring":
        wf = await _make_workflow(wf_type, wf3_steps, TransactionState, data)
    else:
        raise ValueError(f"Unknown workflow type: {wf_type}")

    # Drive the workflow. automate_next=True causes recursive advancement;
    # WorkflowJumpDirective returns without auto-advancing, so we loop.
    for _ in range(50):
        if wf.status != "ACTIVE":
            break
        await wf.next_step(user_input={})

    return json.dumps({
        "status": wf.status,
        "state": wf.state.model_dump() if wf.state else {},
    })
`;

// ─── Pyodide CDN candidates (newest first) ────────────────────────────────────
const PYODIDE_CDNS = [
    "https://cdn.jsdelivr.net/pyodide/v0.27.0/full/pyodide.mjs",
    "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.mjs",
    "https://cdn.jsdelivr.net/pyodide/v0.26.3/full/pyodide.mjs",
    "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/pyodide.mjs",
];

async function loadPyodideDynamic() {
    for (const url of PYODIDE_CDNS) {
        try {
            const mod = await import(url);
            // indexURL is the directory containing the mjs file
            const indexURL = url.replace(/[^/]+$/, "");
            return { loadPyodide: mod.loadPyodide, indexURL };
        } catch (_) {
            // try next version
        }
    }
    throw new Error("Could not load Pyodide from any CDN — check network connectivity");
}

// ─── Worker init ──────────────────────────────────────────────────────────────
let pyodide = null;

async function init() {
    self.postMessage({ type: "status", message: "Loading Pyodide runtime…" });

    // Dynamic import — errors are catchable and produce real messages
    const { loadPyodide, indexURL } = await loadPyodideDynamic();
    pyodide = await loadPyodide({ indexURL });

    // Load Transformers.js (optional — workflow 3 falls back gracefully if absent)
    for (const url of TRANSFORMERS_CDNS) {
        try {
            const tfMod = await import(url);
            _pipeline = tfMod.pipeline;
            if (tfMod.env) {
                tfMod.env.allowLocalModels = false;
                tfMod.env.useBrowserCache = true;
            }
            break;
        } catch (_) {
            // try next URL or continue without GPU inference
        }
    }

    self.postMessage({ type: "status", message: "Installing packages…" });
    await pyodide.loadPackage("micropip");

    const BASE = self.location.origin;
    pyodide.globals.set("_wheel_url", `${BASE}/dist/rufus_sdk-0.8.0-py3-none-any.whl`);
    // Mock native-code packages that have no WASM wheel so micropip's dependency
    // resolver sees them as satisfied without trying to download them.
    // Then install the rufus-sdk wheel normally — micropip resolves all the
    // remaining pure-Python deps (pydantic, jinja2, alembic, sqlalchemy…) from PyPI.
    await pyodide.runPythonAsync(`
import micropip

# Stub out the packages that require C extensions / Rust — not used on the
# in-memory + sync execution path, but listed in rufus-sdk wheel metadata.
for _pkg, _ver in [
    ("cryptography", "41.0.0"),
    ("orjson",       "3.9.0"),
    ("uvloop",       "0.19.0"),
    ("asyncpg",      "0.29.0"),
]:
    micropip.add_mock_package(_pkg, _ver)

# Install the rufus-sdk wheel; micropip resolves pure-Python deps from PyPI.
await micropip.install(_wheel_url, keep_going=True)
`);

    self.postMessage({ type: "status", message: "Initialising Python workflow engine…" });
    await pyodide.runPythonAsync(PYTHON_SETUP);

    const gpuAvailable = _pipeline !== null && _gpuDevice === "webgpu";
    self.postMessage({ type: "webgpu_status", supported: gpuAvailable });
    self.postMessage({ type: "ready" });
}

// ─── Message dispatcher ───────────────────────────────────────────────────────
self.onmessage = async (e) => {
    const { type, workflowType, data } = e.data;

    if (type === "run_workflow") {
        self.postMessage({ type: "workflow_start", workflowType });
        try {
            pyodide.globals.set("_wf_type", workflowType);
            pyodide.globals.set("_wf_data", JSON.stringify(data || {}));
            await pyodide.runPythonAsync("await run_workflow(_wf_type, _wf_data)");
            // result dispatched inside Python via notifyWorkflowDone / notifyWorkflowError
        } catch (err) {
            self.postMessage({
                type: "workflow_error",
                workflowType,
                message: err.message || String(err),
            });
        }

    } else if (type === "get_history") {
        try {
            const jsonStr = await pyodide.runPythonAsync(
                "import json as _j; _j.dumps(await _persistence.list_workflows())"
            );
            self.postMessage({ type: "history_data", workflows: JSON.parse(jsonStr || "[]") });
        } catch (_) {
            self.postMessage({ type: "history_data", workflows: [] });
        }

    } else if (type === "clear_history") {
        try {
            await idbClear();
            await pyodide.runPythonAsync("_persistence._workflows.clear(); _persistence._audit_events.clear()");
        } catch (_) {}
        self.postMessage({ type: "history_cleared" });
    }
};

init().catch((err) => {
    self.postMessage({ type: "init_error", message: err.message || String(err) });
});
