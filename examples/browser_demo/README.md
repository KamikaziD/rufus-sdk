# Rufus Browser Demo

A step-by-step guide to running the Rufus SDK entirely in the browser — no backend, no
Node.js, no cloud. The same Python `WorkflowBuilder` + `Workflow` step functions that run on
a POS terminal or cloud worker execute here via Pyodide (Python 3.12 compiled to WebAssembly).
Workflow 3 adds WebGPU-accelerated AI inference via Transformers.js, called from Python through
Pyodide's JS FFI bridge.

---

## What you will build

```
index.html (main thread)
  │
  ├── spawns Worker(worker.js)
  │     ├── Pyodide v0.27 — Python 3.12 runtime (WASM)
  │     │     ├── rufus-sdk 0.8.0 wheel (served from /dist/)
  │     │     ├── IndexedDBPersistence  — InMemoryPersistence + IDB mirror
  │     │     ├── BrowserSyncExecutor   — thread-free SyncExecutor subclass
  │     │     ├── BrowserObserver       — WorkflowObserver → postMessage bridge
  │     │     └── 3 inline workflow definitions
  │     │
  │     └── Transformers.js v3 (WebGPU / WASM ML, loaded dynamically)
  │           └── Xenova/all-MiniLM-L6-v2  (~23 MB, cached by browser)
  │
  └── UI — 3 workflow cards, step pipeline visualiser, run history, console log
```

Four demo workflows, each illustrating different SDK patterns:

| # | Name | SDK patterns |
|---|------|-------------|
| 1 | Order Fulfillment | STANDARD + PARALLEL fan-out + `WorkflowJumpDirective` |
| 2 | IoT Sensor Pipeline | STANDARD + inline loop logic + health jump |
| 3 | Transaction Risk Scoring | STANDARD + async WebGPU embedding via JS FFI |
| 4 | Document Summarisation | STANDARD + T5-small text generation + DECISION quality gate + extractive fallback |

---

## Prerequisites

- Python ≥ 3.10 (to serve the wheel locally)
- The repo cloned and the `rufus-sdk` wheel built (see step 1)
- Chrome 113+ recommended (best WebGPU support); Firefox works (WASM fallback for Workflow 3)

---

## Quick start

```bash
# 1. From repo root — build the wheel (if not already present)
pip install build
python -m build --wheel --outdir dist

# 2. Start the static server from repo root
python examples/browser_demo/serve.py 8080
# or: python -m http.server 8080  (no compression)

# 3. Open in browser
open http://localhost:8080/examples/browser_demo/
```

First load: ~8–15 s (Pyodide + pure-Python deps from CDN).
Workflow 3 first run: additional ~5–10 s (23 MB model, cached thereafter).
Workflow 4 first run: additional ~20–40 s (90 MB T5-small q8 model, cached thereafter). If the 30 s timeout fires, just click Run again — the model is already cached.

---

## Step-by-step build guide

The demo lives in two files: `worker.js` and `index.html`. Nothing in the SDK is modified.

### Step 1 — Build and serve the wheel

The browser fetches the `rufus-sdk` wheel from the same origin as the page.

```bash
# From repo root
python -m build --wheel --outdir dist
# produces dist/rufus_sdk-0.8.0-py3-none-any.whl

python -m http.server 8080  # serve from repo root
# wheel reachable at http://localhost:8080/dist/rufus_sdk-0.8.0-py3-none-any.whl
```

The worker derives the wheel URL from `self.location.origin` at runtime:

```js
const BASE = self.location.origin;
_wheelUrl = `${BASE}/dist/rufus_sdk-0.8.0-py3-none-any.whl`;
```

### Step 2 — Load Pyodide in a Web Worker

All Python runs inside a dedicated `Web Worker` so the main thread (UI) is never blocked.
Pyodide is loaded dynamically so CDN failures produce real error messages:

```js
// worker.js
const PYODIDE_CDNS = [
    "https://cdn.jsdelivr.net/pyodide/v0.27.0/full/pyodide.mjs",
    "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.mjs",
    // ... fallback versions
];

async function init() {
    const { loadPyodide, indexURL } = await loadPyodideDynamic();
    pyodide = await loadPyodide({ indexURL });
    // ...
}
```

### Step 3 — Install the SDK wheel via micropip

`rufus-sdk` depends on `cryptography`, `orjson`, `uvloop`, and `asyncpg` which have no
pure-Python WASM wheels. Register them as mocks so micropip's resolver sees them as
satisfied, then install the SDK wheel normally:

```python
import micropip

for _pkg, _ver in [
    ("cryptography", "41.0.0"),
    ("orjson",       "3.9.0"),
    ("uvloop",       "0.19.0"),
    ("asyncpg",      "0.29.0"),
]:
    micropip.add_mock_package(_pkg, _ver)

await micropip.install(wheel_url, keep_going=True)
```

Also disable uvloop and orjson **before** rufus is imported, otherwise `rufus/__init__.py`
tries to call `uvloop.EventLoopPolicy()` on the mock:

```python
import os
os.environ["RUFUS_USE_UVLOOP"] = "false"
os.environ["RUFUS_USE_ORJSON"] = "false"
```

### Step 4 — Create browser-adapted providers

The SDK uses three providers. Two need browser-specific subclasses; the third works
unchanged.

#### 4a. BrowserSyncExecutor — thread-free parallel execution

`SyncExecutor.initialize()` creates a `ThreadPoolExecutor`. Pyodide has no real threads
(no `SharedArrayBuffer` without COOP/COEP headers). Override to skip it:

```python
class BrowserSyncExecutor(SyncExecutor):
    async def initialize(self, engine):
        self._engine = engine
        self._thread_pool_executor = None  # no threads in Pyodide
        self._loop = asyncio.get_event_loop()

    async def dispatch_parallel_tasks(self, tasks, state_data, workflow_id, ...):
        results = {}
        for task in tasks:
            func = _BROWSER_FUNCS[task.func_path]  # global registry (see step 6)
            r = await func(state_data, ctx)
            results.update(r)
        return {"_async_dispatch": False, "_sync_parallel_result": results, ...}
```

PARALLEL tasks receive `state_data` as a plain `dict` (from `model_dump()`), not a
Pydantic model. Register task functions in a global dict under their pseudo-path key
before creating the workflow:

```python
_BROWSER_FUNCS: dict = {}
_BROWSER_FUNCS["__br__.check_warehouse_uk"] = check_warehouse_uk
_BROWSER_FUNCS["__br__.check_warehouse_eu"] = check_warehouse_eu
```

#### 4b. IndexedDBPersistence — cross-refresh history

Subclass `InMemoryPersistence` to mirror workflow state to IndexedDB. In-memory is the
primary store (fast, synchronous); IDB is a best-effort mirror that survives page refresh.

```python
class IndexedDBPersistence(InMemoryPersistence):
    async def save_workflow(self, workflow_id, workflow_data):
        # Cap in-memory dict to 50 entries (evict oldest on overflow)
        MAX_MEM = 50
        if len(self._workflows) >= MAX_MEM:
            oldest_key = next(iter(self._workflows))
            del self._workflows[oldest_key]
        await super().save_workflow(workflow_id, workflow_data)
        # Mirror to IDB via JS FFI (best-effort — errors are swallowed)
        try:
            from js import idbPutWorkflow
            await idbPutWorkflow(json.dumps({**workflow_data, "created_at": ...}))
        except Exception:
            pass
```

`idbPutWorkflow` is a `globalThis` function in `worker.js` — Pyodide can call any
`globalThis` function via `from js import <name>`.

#### 4c. BrowserObserver — workflow events → postMessage

Bridge Python workflow events back to the main thread:

```python
class BrowserObserver:
    async def on_step_executed(self, wf_id, step_name, ...):
        from js import notifyStepDone
        notifyStepDone(step_name, json.dumps(result or {}))

    async def on_workflow_completed(self, wf_id, wf_type, state):
        from js import notifyWorkflowDone
        notifyWorkflowDone(json.dumps(state.model_dump()))

    async def on_workflow_failed(self, wf_id, wf_type, error, state):
        from js import notifyWorkflowError
        notifyWorkflowError(str(error))
```

The corresponding `globalThis` functions in `worker.js` forward to `self.postMessage(...)`.

### Step 5 — Define state models and step functions

State models are standard Pydantic `BaseModel` subclasses — identical to what you'd write
for any other Rufus deployment:

```python
class OrderState(BaseModel):
    order_id: str = ""
    items: list = []
    total: float = 0.0
    stock_uk: bool = False
    stock_eu: bool = False
    payment_ref: str = ""
    status: str = ""
    fulfillment_path: str = ""
```

Step functions follow the standard `(state, context, **user_input) -> dict` signature:

```python
def validate_order(state: OrderState, context: StepContext, **_):
    total = sum(item["price"] * item.get("qty", 1) for item in state.items)
    return {"total": round(total, 2), "order_id": state.order_id or f"ORD-{random.randint(1000,9999)}"}
```

### Step 6 — Wire up WorkflowBuilder and Workflow

Create shared providers once at setup time, then construct `Workflow` instances per run:

```python
_persistence = IndexedDBPersistence()
_executor    = BrowserSyncExecutor()
_observer    = BrowserObserver()
_builder     = WorkflowBuilder({}, SimpleExpressionEvaluator, Jinja2TemplateEngine)

await _persistence.initialize()
await _executor.initialize(None)

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
```

### Step 7 — Write the run loop

`WorkflowJumpDirective` returns control to the caller without auto-advancing, so a simple
`automate_next=True` chain isn't enough for branching workflows. Drive it with a loop:

```python
async def run_workflow(wf_type: str, data_json: str):
    data = json.loads(data_json) if data_json else {}
    wf = await _make_workflow(wf_type, ..., data)

    for _ in range(50):
        if wf.status != "ACTIVE":
            break
        await wf.next_step(user_input={})
```

### Step 8 — Handle messages in worker.js

Dispatch incoming `postMessage` calls and forward Python results back to the main thread.
The `run_workflow` handler includes a 30 s timeout that unblocks the UI immediately if
Python hangs (Python continues running in the background; its eventual `notifyWorkflowDone`
is ignored):

```js
self.onmessage = async (e) => {
    const { type, workflowType, data } = e.data;

    if (type === "run_workflow") {
        self.postMessage({ type: "workflow_start", workflowType });
        const timeoutId = setTimeout(() => {
            self.postMessage({ type: "workflow_timeout", workflowType });
        }, 30_000);
        try {
            pyodide.globals.set("_wf_type", workflowType);
            pyodide.globals.set("_wf_data", JSON.stringify(data || {}));
            await pyodide.runPythonAsync("await run_workflow(_wf_type, _wf_data)");
        } finally {
            clearTimeout(timeoutId);
        }
    }
};
```

### Step 9 — Build the main thread UI (index.html)

Create a `Worker`, listen for messages, and update the DOM:

```js
const worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module" });
worker.onmessage = handleWorkerMessage;

function handleWorkerMessage(e) {
    switch (e.data.type) {
        case "ready":          enableButtons(); break;
        case "workflow_start": setButton(e.data.workflowType, true, "Running…"); break;
        case "step_done":      markStep(currentWfType, e.data.stepName, "done"); break;
        case "workflow_done":  showResult(currentWfType, e.data.state, elapsed); break;
        case "workflow_error": setButton(e.data.workflowType, false, "Run"); break;
        // ... storage + timeout + GPU fallback cases
    }
}

window.runWorkflow = (workflowType) => {
    worker.postMessage({ type: "run_workflow", workflowType, data: defaultData[workflowType] });
};
```

---

## Worker ↔ main thread message protocol

### main → worker

| type | payload | purpose |
|---|---|---|
| `run_workflow` | `{ workflowType, data }` | Start a workflow run |
| `preflight_check` | — | Request environment inspector data |
| `get_history` | — | Fetch run history from IDB |
| `clear_history` | — | Wipe IDB + in-memory stores |

### worker → main

| type | payload | purpose |
|---|---|---|
| `status` | `{ message }` | Init progress text |
| `ready` | — | Init complete; enable run buttons |
| `init_error` | `{ message }` | Fatal init failure |
| `webgpu_status` | `{ supported }` | WebGPU detection result |
| `model_loading` | — | Transformers.js model download started |
| `model_ready` | `{ device }` | Model loaded |
| `workflow_start` | `{ workflowType }` | Workflow execution began |
| `step_done` | `{ stepName, result }` | A step completed |
| `workflow_done` | `{ state }` | Workflow completed successfully |
| `workflow_error` | `{ workflowType, message }` | Workflow failed |
| `workflow_timeout` | `{ workflowType }` | 30 s wall-clock limit exceeded |
| `storage_warning` | `{ usageBytes, quotaBytes, pct }` | IDB usage crossed 80% quota |
| `storage_quota_exceeded` | `{ store, pruned }` | QuotaExceededError; auto-pruned + retried |
| `gpu_fallback` | — | WebGPU inference failed; CPU pseudo-embeddings active |
| `preflight_result` | `{ data }` | Environment inspector payload |
| `history_data` | `{ workflows }` | Run history records |
| `history_cleared` | — | History wipe confirmed |

---

## The three workflows

### Workflow 1 — Order Fulfillment

```
ValidateOrder → CheckInventory ──┬── [in stock]  → FulfillmentDecision → ProcessPayment → SendConfirmation
               (PARALLEL:         └── [all OOS]  → FulfillmentDecision → ↩ BackorderNotice
                check_uk +
                check_eu)
```

**SDK patterns:**
- `ParallelWorkflowStep` with two `ParallelExecutionTask` entries
- `WorkflowJumpDirective` raised in `FulfillmentDecision` when both warehouses out-of-stock
- Terminal branch guard in `BackorderNotice` to no-op on the normal path

**State:** `order_id`, `items[]`, `total`, `stock_uk`, `stock_eu`, `payment_ref`, `status`,
`fulfillment_path`

### Workflow 2 — IoT Sensor Pipeline

```
InitPipeline → CollectSensorData → ProcessReadings → ComputeStatistics → HealthDecision
                (10 synthetic         (iterates over    (mean, stddev,      ├── HEALTHY
                 readings + 2          readings list)    anomaly_rate)       ├── WARNING
                 injected anomalies)                                         └── CRITICAL → SendAlert
```

**SDK patterns:**
- Loop logic inline in a STANDARD step (identical behaviour to a `LOOP` step type)
- `WorkflowJumpDirective` raised in `HealthDecision` on high anomaly rate or σ

**State:** `device_id`, `readings[]`, `processed[]`, `anomalies[]`, `mean`, `stddev`,
`anomaly_rate`, `health_status`, `alert_sent`

### Workflow 3 — Transaction Risk Scoring

```
ExtractFeatures → GPUEmbedding → ComputeRiskScore → ScoreDecision
                   (calls           (cosine sim vs     ├── APPROVED
                    runWebGPUInference  3 risk patterns) ├── MANUAL_REVIEW → RecordOutcome
                    via JS FFI)                          └── DECLINED → RecordOutcome
```

**SDK patterns:**
- Async step calling a JS `globalThis` function via Pyodide FFI
- Risk pattern embeddings computed lazily on first run, cached in `_RISK_PATTERNS`
- GPU → CPU pseudo-embedding fallback with user notification

**State:** `txn_id`, `amount`, `merchant_category`, `location`, `feature_text`,
`embedding[]`, `risk_score`, `decision`, `explanation`, `inference_ms`, `device_used`

**Risk pattern texts:**
- `"high value wire transfer crypto exchange after midnight"` → HIGH
- `"small grocery purchase coffee shop weekday morning"` → LOW
- `"online subscription streaming service monthly payment"` → LOW

---

## Resilience features

The demo handles four resource failure modes with minimal, surgical JS:

### Storage quota handling

`idbPutWorkflow` wraps the IDB write in a prune-on-quota + retry loop:

```js
globalThis.idbPutWorkflow = async (json) => {
    try {
        await attempt();
        await checkStorageQuota();  // proactive warning at >80% quota
    } catch (err) {
        if (err?.name === "QuotaExceededError") {
            const pruned = await idbPruneOldest();  // delete oldest records
            self.postMessage({ type: "storage_quota_exceeded", store: "workflows", pruned });
            try { await attempt(); } catch (_) {}  // one retry
        }
    }
};
```

`checkStorageQuota()` calls `navigator.storage.estimate()` after every successful write and
posts a `storage_warning` message when usage crosses a new 5% band above 80% (debounced).

`idbLogAudit` clears the entire audit store on `QuotaExceededError` — audit events are
best-effort; the authoritative copy is the Python in-memory list.

The Python `save_workflow` implementation also caps its in-memory dict at 50 entries,
evicting the oldest by insertion order.

### Workflow execution timeout

The `run_workflow` handler fires a 30 s `setTimeout`. When it triggers the UI unblocks
immediately (run button re-enables, toast shown). Python continues executing in the
background; if it eventually finishes, `notifyWorkflowDone` arrives and is silently
discarded. This avoids the expensive `Worker.terminate()` + re-initialise cycle.

### GPU → CPU fallback notification

The `gpu_embedding` step wraps `runWebGPUInference` in a try/except. On failure it calls
`notifyGpuFallback()` (a `globalThis` registered in `worker.js`) before falling through to
the deterministic pseudo-embedding path:

```python
except Exception:
    try:
        from js import notifyGpuFallback
        notifyGpuFallback()
    except Exception:
        pass
    # deterministic pseudo-embedding fallback follows...
```

### Toast notification system

All four failure modes surface in the UI as dismissable toasts (`#toast-container`).
The header badge `#badge-storage` updates to orange/red when storage is above 80%/90%.
The Inspect panel shows a coloured storage bar and exact byte counts.

---

## Key patterns reference

### Python f-strings inside JS template literals

Python f-strings containing `${...}` will break the outer JS template literal. Remove `$`
before any `{expression}`:

```python
# BAD  — JS parse error
f"Transaction: ${state.amount:.2f} USD"

# GOOD
f"Transaction: {state.amount:.2f} USD"
```

### Terminal branch guard

Alternate-path terminal steps sit at the end of the step list and would execute on the
normal path too. A guard at the top prevents this:

```python
def backorder_notice(state: OrderState, context: StepContext, **_):
    if state.fulfillment_path in ("UK", "EU"):
        return {}   # normal path: no-op
    return {"status": "BACKORDERED", "fulfillment_path": "BACKORDER"}
```

### PARALLEL tasks in Pyodide

`dispatch_parallel_tasks` cannot use `asyncio.gather` on coroutines that touch Pyodide
internals — run them sequentially and merge:

```python
async def dispatch_parallel_tasks(self, tasks, state_data, ...):
    results = {}
    for task in tasks:
        func = _BROWSER_FUNCS.get(task.func_path)
        r = await func(state_data, ctx) if asyncio.iscoroutinefunction(func) else func(state_data, ctx)
        if isinstance(r, dict):
            results.update(r)
    return {"_async_dispatch": False, "_sync_parallel_result": results, "task_results": results, "errors": {}}
```

---

## Files

```
examples/browser_demo/
├── index.html   — Dark-themed SPA; workflow cards, pipeline visualiser,
│                  run history, console, toast system, environment inspector
├── worker.js    — ES-module Web Worker; Pyodide + Transformers.js;
│                  IndexedDB helpers; all Python workflow code embedded as
│                  a template literal (PYTHON_SETUP)
└── serve.py     — Compressed static server (gzip default; brotli if installed)
```

No SDK files are modified by the demo.

---

## Console output reference

| Message | Source | Normal? |
|---|---|---|
| `WebSocket ws://localhost:8081/ failed` | Browser live-reload extension | Yes — ignore |
| `favicon.ico 404` | Missing icon | Harmless |
| `Loading micropip, pydantic…` | Pyodide package loader | Expected |
| `dtype not specified… Using fp32` | Transformers.js | Informational |
| `Some nodes were not assigned to preferred EP` | ONNX Runtime WebGPU | Normal first session |

---

## Troubleshooting

**`micropip` install fails / `alembic` dependency error**
→ Do not use `deps=False` — use `add_mock_package` for native-extension packages (see step 3).

**`AttributeError: module 'uvloop' has no attribute 'EventLoopPolicy'`**
→ Set `RUFUS_USE_UVLOOP=false` before importing rufus (see step 3).

**`SyntaxError: Missing } in template expression` in worker.js**
→ A Python f-string inside `PYTHON_SETUP` contains `${`. Remove the `$`.

**Worker fires `onerror` immediately with `message: undefined`**
→ JS syntax error in `worker.js`. Run `node --input-type=module < examples/browser_demo/worker.js` to find it.

**Wheels 404**
→ The server must be started from the **repo root**, not from `examples/browser_demo/`:
```bash
cd /path/to/rufus
python -m http.server 8080   # correct — wheel at /dist/rufus_sdk-0.8.0-py3-none-any.whl
```

**Storage quota toast appears immediately**
→ DevTools → Application → Storage has a custom quota set. Clear it or click the toast to dismiss.

**Workflow 4 times out on first run (30 s timeout)**
→ The T5-small q8 model is ~90 MB and may take 30–60 s to download on a slow connection. The timeout fires naturally and re-enables the Run button. Click Run again — the model is already cached in the browser and the second run completes in ~2–5 s.

**Workflow 4 shows `quality=FALLBACK`**
→ This is normal if the T5 model produces a very short output. The `QualityDecision` step jumps to `FallbackExtract`, which uses extractive sentence selection instead.
