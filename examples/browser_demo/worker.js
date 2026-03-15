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
let _summariser = null;
let _nerPipeline = null;
let _summariserTask = "text-generation";  // updated if fallback loads FLAN-T5
let _pipeline = null;   // set after dynamic import
let _activeModel  = null;              // "extractor" | "summariser" | "ner" | null
let _modelMutex   = Promise.resolve(); // promise-chain mutex (no SharedArrayBuffer needed)
let _workflowRunning = false;          // busy flag — prevents concurrent workflow runs
let _currentModelSettings = {};       // model params forwarded from the main thread (W4)

// ─── Preflight tracking ───────────────────────────────────────────────────────
let _loadedPyodideUrl = null;
let _loadedTransformersUrl = null;
let _wheelUrl = null;

/**
 * Low-level model loader — caller must hold the mutex before calling this.
 * Unloads the currently resident model (if different) then loads `which`.
 */
async function _loadModel(which) {
    if (_activeModel === which) return;   // fast path

    // Unload whichever model is currently resident
    if (_activeModel === "extractor" && _extractor) {
        self.postMessage({ type: "model_unloading", model: "extractor",
                           message: "Unloading MiniLM to free memory…" });
        try { await _extractor.dispose(); } catch (_) {}
        _extractor = null; _activeModel = null;
        self.postMessage({ type: "model_unloaded", model: "extractor" });
    } else if (_activeModel === "summariser" && _summariser) {
        self.postMessage({ type: "model_unloading", model: "summariser",
                           message: `Unloading ${_summariserTask === "text-generation" ? "Qwen2.5" : "FLAN-T5"} model to free memory…` });
        try { await _summariser.dispose(); } catch (_) {}
        _summariser = null; _activeModel = null;
        self.postMessage({ type: "model_unloaded", model: "summariser" });
    } else if (_activeModel === "ner" && _nerPipeline) {
        self.postMessage({ type: "model_unloading", model: "ner",
                           message: "Unloading NER model to free memory…" });
        try { await _nerPipeline.dispose(); } catch (_) {}
        _nerPipeline = null; _activeModel = null;
        self.postMessage({ type: "model_unloaded", model: "ner" });
    }

    // Load the requested model
    if (which === "extractor") {
        self.postMessage({ type: "model_loading" });
        _extractor = await _pipeline("feature-extraction", "Xenova/all-MiniLM-L6-v2",
                                     { device: _gpuDevice });
        _activeModel = "extractor";
        self.postMessage({ type: "model_ready", device: _gpuDevice });
    } else if (which === "summariser") {
        self.postMessage({ type: "summariser_loading" });
        const TIMEOUT_MS = 120_000;
        let loaded = false;
        try {
            const modelPromise = _pipeline("text-generation", "onnx-community/Qwen2.5-0.5B-Instruct", {
                device: _gpuDevice,
                dtype: "q4",
                progress_callback: ({ status, progress, file }) => {
                    if (status === "progress" && progress != null) {
                        self.postMessage({ type: "summariser_progress",
                                           progress: Math.round(progress),
                                           file: file ?? "" });
                    }
                },
            });
            const timeoutPromise = new Promise((_, reject) =>
                setTimeout(() => reject(new Error("timeout")), TIMEOUT_MS)
            );
            _summariser = await Promise.race([modelPromise, timeoutPromise]);
            _summariserTask = "text-generation";
            loaded = true;
        } catch (e) {
            self.postMessage({ type: "summariser_fallback",
                               reason: e.message === "timeout" ? "download timed out" : e.message });
            _summariser = await _pipeline("text2text-generation", "Xenova/flan-t5-small",
                                          { device: _gpuDevice, dtype: "q8" });
            _summariserTask = "text2text-generation";
            loaded = true;
        }
        if (loaded) {
            _activeModel = "summariser";
            self.postMessage({ type: "summariser_ready", device: _gpuDevice,
                               model: _summariserTask === "text-generation" ? "Qwen2.5-0.5B" : "FLAN-T5-small" });
        }
    } else if (which === "ner") {
        self.postMessage({ type: "ner_model_loading" });
        _nerPipeline = await _pipeline("token-classification", "Xenova/bert-base-NER", {
            device: "wasm",  // NER runs efficiently on WASM without WebGPU
            dtype: "q8",     // 8-bit quantized — ~27 MB
            aggregation_strategy: "simple",
        });
        _activeModel = "ner";
        self.postMessage({ type: "ner_model_ready" });
    }
}

/**
 * Called from Python via `from js import runWebGPUInference`.
 * Returns a plain JS object: { embedding: TypedArray, latency_ms, device_used }
 */
globalThis.runWebGPUInference = async (text) => {
    if (!_pipeline) throw new Error("Transformers.js not loaded");
    let release;
    const prev  = _modelMutex;
    _modelMutex = new Promise(r => { release = r; });
    await prev;
    try {
        await _loadModel("extractor");
        const t0  = performance.now();
        const out = await _extractor(text, { pooling: "mean", normalize: true });
        return { embedding: out.data, latency_ms: performance.now() - t0,
                 device_used: _gpuDevice };
    } finally { release(); }
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

globalThis.notifyGpuFallback = () => {
    self.postMessage({ type: "gpu_fallback" });
};

// ── PAGED INFERENCE ───────────────────────────────────────────────────────────
// Shard-level LLM paging for memory-constrained browsers (Safari: ~300 MB WASM
// limit) and edge devices.  Architecture:
//   OPFSShardCache  — write-once LRU cache in Origin Private File System
//   ShardScheduler  — rolling window of `windowSize` shards + 1-ahead prefetch
//   runPagedInference — main entry point (called from Python via JS FFI)
//   classifyComplexity — lightweight heuristic; returns 0.0–1.0 complexity score
//
// Production note: replace BITNET_SHARD_URLS with real CDN paths to your split
// GGUF shards (llama-gguf-split --split-max-size 120M bitnet-2b.gguf shard).
// wllama is loaded on first call and cached for subsequent runs.

const BITNET_SHARD_URLS = [
    // Placeholder URLs — swap for real split-GGUF shard paths in production.
    // Example: "https://cdn.example.com/bitnet-2b/bitnet-2b-00001-of-00010.gguf"
    "shard-0-placeholder.gguf",
    "shard-1-placeholder.gguf",
    "shard-2-placeholder.gguf",
];

// wllama CDN — loaded dynamically on first inference call
const WLLAMA_CDN = "https://cdn.jsdelivr.net/npm/wllama@2/esm/wllama.js";
let _wllama = null;
let _wllamaClass = null;

class OPFSShardCache {
    constructor() { this._root = null; }

    async init() {
        try {
            this._root = await navigator.storage.getDirectory();
        } catch (_) {
            this._root = null;   // OPFS unavailable (non-secure context / older Safari)
        }
    }

    async has(shardId) {
        if (!this._root) return false;
        try { await this._root.getFileHandle(shardId); return true; } catch { return false; }
    }

    async write(shardId, buffer) {
        if (!this._root) return;
        try {
            const fh = await this._root.getFileHandle(shardId, { create: true });
            const writable = await fh.createWritable();
            await writable.write(buffer);
            await writable.close();
        } catch (_) {}
    }

    async read(shardId) {
        if (!this._root) return null;
        try {
            const fh = await this._root.getFileHandle(shardId);
            const file = await fh.getFile();
            return file.arrayBuffer();
        } catch { return null; }
    }
}

const _opfsCache = new OPFSShardCache();

class ShardScheduler {
    constructor(shardUrls, windowSize = 2, prefetch = 1) {
        this._shards = shardUrls;
        this._window = windowSize;
        this._prefetch = prefetch;
    }

    async _ensureShard(idx) {
        const id = `rufus-shard-${idx}.gguf`;
        const cached = await _opfsCache.read(id);
        if (cached) return cached;

        // Fetch from remote; ignore errors (placeholder URLs will fail gracefully)
        try {
            const resp = await fetch(this._shards[idx]);
            if (!resp.ok) return null;
            const buf = await resp.arrayBuffer();
            await _opfsCache.write(id, buf);
            return buf;
        } catch { return null; }
    }

    async getWindow(startIdx, shardsToUse) {
        const indices = (shardsToUse || Array.from({ length: this._window },
            (_, i) => startIdx + i)).filter(i => i < this._shards.length);

        // Fire-and-forget prefetch for next shard
        const prefetchIdx = Math.max(...indices) + 1;
        if (prefetchIdx < this._shards.length) {
            this._ensureShard(prefetchIdx).catch(() => {});
        }

        return Promise.all(indices.map(i => this._ensureShard(i)));
    }
}

const _shardScheduler = new ShardScheduler(BITNET_SHARD_URLS, 2, 1);

/**
 * Lightweight complexity classifier — called from Python `assess_complexity` step.
 * Returns 0.0–1.0 complexity score.  0.0 = trivial (fast path); 1.0 = complex (full inference).
 */
globalThis.classifyComplexity = async (prompt) => {
    const tokenEst = prompt.trim().split(/\s+/).length;
    const complexRe = /diagnos|analys|explain|reason|troubleshoot|root cause|cascad|intermittent|multi.step/i;
    const isComplex = tokenEst > 50 || complexRe.test(prompt);
    return isComplex ? 1.0 : 0.2;
};

/**
 * Main paged inference entry point — called from Python via `from js import runPagedInference`.
 * Serialises through _modelMutex so concurrent calls queue safely.
 *
 * @param {string} inputJson  JSON: { prompt: string, threshold?: number }
 * @param {number} maxTokens  Token generation cap (default 128)
 * @returns {{ text, tokens_generated, shards_loaded, latency_ms, complexity_score }}
 */
globalThis.runPagedInference = async (inputJson, maxTokens = 128) => {
    let release;
    const prev = _modelMutex;
    _modelMutex = new Promise(r => { release = r; });
    await prev;
    try {
        const { prompt, threshold = 0.5 } = JSON.parse(inputJson);
        const complexity = await globalThis.classifyComplexity(prompt);

        // Logic gate: use shard-0 only when prompt is simple
        const useFastPath = complexity < threshold;
        const shardIndices = useFastPath ? [0] : BITNET_SHARD_URLS.map((_, i) => i);

        self.postMessage({
            type: "paged_shard_status",
            shardsTotal: BITNET_SHARD_URLS.length,
            shardsLoading: shardIndices.length,
            fastPath: useFastPath,
        });

        // Fetch active shard window (OPFS-backed)
        const shardBuffers = await _shardScheduler.getWindow(0, shardIndices);
        const loadedShards = shardBuffers.filter(Boolean).length;

        // Load wllama on first call
        if (!_wllamaClass) {
            try {
                const mod = await import(WLLAMA_CDN);
                _wllamaClass = mod.Wllama || mod.default;
            } catch (_) {
                _wllamaClass = null;
            }
        }

        const t0 = performance.now();
        let text = "";

        if (_wllamaClass && loadedShards > 0) {
            // Real wllama inference path (requires actual GGUF shard files)
            if (!_wllama) _wllama = new _wllamaClass({});
            const blobs = shardBuffers.filter(Boolean).map(buf => new Blob([buf]));
            await _wllama.loadModelFromBlob(blobs.length === 1 ? blobs[0] : blobs);
            await _wllama.createCompletion(prompt, {
                nPredict: maxTokens,
                onNewToken: (_, piece) => {
                    text += piece;
                    self.postMessage({ type: "paged_token", piece });
                },
            });
        } else {
            // Simulation fallback — placeholder shards can't run real inference
            const pathLabel = useFastPath ? "fast path (shard-0 only)" : "full inference";
            text = useFastPath
                ? `[Demo] Simple query resolved via ${pathLabel}. `
                  + `In production, BitNet shard-0 (~120 MB) answers common lookups in ~1.5s.`
                : `[Demo] Complex reasoning via ${pathLabel}. `
                  + `In production, ${BITNET_SHARD_URLS.length} × 120 MB shards are loaded `
                  + `from OPFS into a rolling 2-shard window, yielding full root-cause analysis.`;
            // Simulate streaming tokens
            for (const word of text.split(" ")) {
                self.postMessage({ type: "paged_token", piece: word + " " });
            }
        }

        const latency_ms = performance.now() - t0;
        return {
            text: text.trim(),
            tokens_generated: text.trim().split(/\s+/).filter(Boolean).length,
            shards_loaded: loadedShards || shardIndices.length,
            latency_ms,
            complexity_score: complexity,
        };
    } finally {
        release();
    }
};

globalThis.runSummarisation = async (text) => {
    if (!_pipeline) throw new Error("Transformers.js not loaded");
    let release;
    const prev  = _modelMutex;
    _modelMutex = new Promise(r => { release = r; });
    await prev;
    try {
        await _loadModel("summariser");
        const t0 = performance.now();
        let summary;
        if (_summariserTask === "text-generation") {
            // Qwen2.5-Instruct: chat template — returns array of messages
            const messages = [
                { role: "system", content: "You are a concise summarizer. Respond only with the summary. Do not copy sentences verbatim." },
                { role: "user",   content: `Write a 2-3 sentence summary (under 60 words) that captures the key facts. Do not quote the source directly.\n\n${text.substring(0, 1500)}` },
            ];
            const s = _currentModelSettings;
            const genOpts = {
                max_new_tokens:     s.max_new_tokens     ?? 200,
                do_sample:          s.do_sample          ?? false,
                repetition_penalty: s.repetition_penalty ?? 1.3,
            };
            if (genOpts.do_sample) genOpts.temperature = s.temperature ?? 0.7;
            const result = await _summariser(messages, genOpts);
            const generated = result[0].generated_text;
            summary = Array.isArray(generated)
                ? (generated.at(-1)?.content ?? "")
                : generated;
        } else {
            // FLAN-T5-small fallback: text2text-generation
            const prompt = `Summarize the following passage in 2-3 sentences: ${text.substring(0, 1500)}`;
            const result = await _summariser(prompt, {
                max_new_tokens:       80,
                min_length:           20,
                num_beams:            2,
                repetition_penalty:   3.0,
                no_repeat_ngram_size: 4,
                early_stopping:       true,
            });
            summary = result[0].generated_text;
        }
        return { summary, latency_ms: performance.now() - t0, device_used: _gpuDevice };
    } finally { release(); }
};

/**
 * Called from Python via `from js import runNERInference`.
 * Returns a plain JS object: { entities_json: string, latency_ms }
 * Uses bert-base-NER (q8, ~27 MB) for named entity recognition.
 */
globalThis.runNERInference = async (text) => {
    if (!_pipeline) throw new Error("Transformers.js not loaded");
    let release;
    const prev  = _modelMutex;
    _modelMutex = new Promise(r => { release = r; });
    await prev;
    try {
        await _loadModel("ner");
        const t0 = performance.now();
        const entities = await _nerPipeline(text, { aggregation_strategy: "simple" });
        return {
            entities_json: JSON.stringify(entities),
            latency_ms: performance.now() - t0,
        };
    } finally { release(); }
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
    const attempt = async () => {
        const db = await openIDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction("workflows", "readwrite");
            tx.objectStore("workflows").put(JSON.parse(json));
            tx.oncomplete = () => { db.close(); resolve(); };
            tx.onerror    = (e) => { db.close(); reject(e.target.error); };
        });
    };
    try {
        await attempt();
        await checkStorageQuota();   // proactive warning after successful write
    } catch (err) {
        if (err?.name === "QuotaExceededError") {
            const pruned = await idbPruneOldest().catch(() => 0);
            self.postMessage({ type: "storage_quota_exceeded", store: "workflows", pruned });
            try { await attempt(); } catch (_) { /* give up after one retry */ }
        }
        // Non-quota errors: silently swallow (IDB is best-effort mirror)
    }
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
    try {
        await new Promise((resolve, reject) => {
            const tx = db.transaction("audit_events", "readwrite");
            tx.objectStore("audit_events").add(JSON.parse(json));
            tx.oncomplete = () => { db.close(); resolve(); };
            tx.onerror    = (e) => { db.close(); reject(e.target.error); };
        });
    } catch (err) {
        if (err?.name === "QuotaExceededError") {
            const db2 = await openIDB();
            await new Promise((res) => {
                const tx = db2.transaction("audit_events", "readwrite");
                tx.objectStore("audit_events").clear();
                tx.oncomplete = () => { db2.close(); res(); };
                tx.onerror    = () => { db2.close(); res(); };
            });
        }
    }
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

// ─── Storage quota helpers ────────────────────────────────────────────────────
const STORAGE_WARN_PCT  = 0.80;
const IDB_MAX_WORKFLOWS = 50;
let _lastStorageWarnPct = 0;

async function checkStorageQuota() {
    if (!navigator.storage?.estimate) return null;
    const { usage, quota } = await navigator.storage.estimate();
    const pct = quota > 0 ? usage / quota : 0;
    if (pct >= STORAGE_WARN_PCT && Math.floor(pct * 20) > Math.floor(_lastStorageWarnPct * 20)) {
        _lastStorageWarnPct = pct;
        self.postMessage({ type: "storage_warning", usageBytes: usage, quotaBytes: quota, pct });
    }
    return { usageBytes: usage, quotaBytes: quota, pct };
}

async function idbPruneOldest() {
    const db = await openIDB();
    const all = await new Promise((res, rej) => {
        const tx = db.transaction("workflows", "readonly");
        const req = tx.objectStore("workflows").getAll();
        req.onsuccess = (e) => { db.close(); res(e.target.result || []); };
        req.onerror   = (e) => { db.close(); rej(e.target.error); };
    });
    all.sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));
    const toDelete = all.slice(0, Math.max(0, all.length - IDB_MAX_WORKFLOWS + 5));
    if (!toDelete.length) return 0;
    const db2 = await openIDB();
    return new Promise((res, rej) => {
        const tx = db2.transaction("workflows", "readwrite");
        const store = tx.objectStore("workflows");
        toDelete.forEach(w => store.delete(w.id));
        tx.oncomplete = () => { db2.close(); res(toDelete.length); };
        tx.onerror    = (e) => { db2.close(); rej(e.target.error); };
    });
}

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

    async def on_step_executed(self, wf_id, step_name, step_index, status, result, state, duration_ms=None):
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
        # Evict oldest entry when at capacity (insertion-order dict, Python 3.7+)
        MAX_MEM = 50
        import time as _t
        if len(self._workflows) >= MAX_MEM:
            oldest_key = next(iter(self._workflows))
            del self._workflows[oldest_key]
        # Ensure created_at is set before writing to in-memory dict AND IDB
        enriched = {
            **workflow_data,
            "created_at": workflow_data.get("created_at") or
                          _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime()),
        }
        await super().save_workflow(workflow_id, enriched)
        try:
            from js import idbPutWorkflow
            await idbPutWorkflow(json.dumps(enriched))
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


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 4 — Document Summarisation Pipeline
# Steps: IngestDocument → PreprocessText → GenerateSummary → ExtractKeywords
#         → QualityDecision → [jump if low quality] → FallbackExtract
# ══════════════════════════════════════════════════════════════════════════════

import re as _re

_DEMO_TEXTS = [
    """OpenAI has unveiled GPT-5, its most advanced language model to date, representing a significant leap forward in artificial intelligence capabilities. The new model demonstrates unprecedented reasoning abilities, scoring in the top percentile across a wide range of professional and academic benchmarks including law, medicine, and mathematics. GPT-5 features a context window of one million tokens, enabling it to process entire codebases or legal documents in a single pass. The model introduces a novel mixture-of-experts architecture that allows it to selectively activate specialised sub-networks depending on the task at hand, dramatically improving efficiency. Enterprise customers will have access to fine-tuning capabilities that allow the model to adapt to proprietary datasets while maintaining strict data isolation guarantees. The release has prompted immediate reactions from competitors, with Google and Anthropic announcing accelerated development timelines for their own frontier models. Regulatory bodies in the European Union have indicated they will scrutinise the deployment under the AI Act framework, particularly around transparency and high-risk use cases.""",

    """Revenue for the quarter exceeded analyst expectations by a substantial margin, growing 18 percent year-over-year to reach 4.2 billion dollars. The company attributed the outperformance to strong demand in its enterprise software segment, which expanded 31 percent driven by new customer acquisitions and higher average contract values. Gross margins improved by 240 basis points to 68.4 percent, reflecting continued operational leverage and a favourable shift in product mix toward higher-margin subscription offerings. Operating cash flow reached 1.1 billion dollars, enabling the board to authorise an additional share buyback programme of 500 million dollars. The CFO highlighted that international markets, particularly Southeast Asia and Latin America, contributed disproportionately to growth, accounting for 38 percent of new bookings despite representing only 22 percent of the installed base. Looking ahead, management raised full-year guidance to a revenue range of 16.5 to 17.0 billion dollars, implying approximately 15 percent growth at the midpoint.""",

    """Researchers at MIT's Computer Science and Artificial Intelligence Laboratory have developed a breakthrough method for training neural networks that reduces energy consumption by up to 94 percent compared to conventional approaches. The technique, called Sparse Activation with Momentum Reuse, exploits temporal redundancy in sequential data by reusing intermediate computations across adjacent time steps rather than recalculating them from scratch. In benchmark experiments on image recognition and natural language processing tasks, the method achieved accuracy within 0.3 percentage points of the dense baseline while consuming a fraction of the computational resources. The researchers demonstrated the approach on edge hardware including a modified Raspberry Pi and a custom RISC-V chip, showing that inference latency dropped below 15 milliseconds for a 7-billion-parameter language model. Industry observers have noted that the findings could have significant implications for on-device AI in smartphones, medical devices, and autonomous vehicles where battery life and thermal constraints are critical.""",
]


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
    text = _re.sub(r'\\s+', ' ', state.raw_text).strip()
    sentences = _re.split(r'(?<=[.!?])\\s+', text)
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
        sentences = _re.split(r'(?<=[.!?])\\s+', state.raw_text)
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
    words = _re.findall(r'\\b[a-zA-Z]{4,}\\b', text)
    freq = {}
    for w in words:
        if w not in _sw:
            freq[w] = freq.get(w, 0) + 1
    return {"keywords": sorted(freq, key=freq.get, reverse=True)[:8]}


def quality_decision(state: DocumentState, context: StepContext, **_):
    summary = state.summary or ""
    words   = summary.split()

    # Gate 1 — too short
    if len(words) < 10:
        raise WorkflowJumpDirective(target_step_name="FallbackExtract")

    # Gate 2 — garbage / multilingual hallucination
    # Flag if more than 12% of characters are non-ASCII
    non_ascii = sum(1 for c in summary if ord(c) > 127)
    if non_ascii / max(len(summary), 1) > 0.12:
        raise WorkflowJumpDirective(target_step_name="FallbackExtract")

    # Gate 3 — repetition loop (any 4-gram appearing > 2 times)
    lower = [w.lower() for w in words]
    ngrams = [" ".join(lower[i:i+4]) for i in range(len(lower) - 3)]
    if ngrams and max(ngrams.count(g) for g in set(ngrams)) > 2:
        raise WorkflowJumpDirective(target_step_name="FallbackExtract")

    # Gate 4 — hallucination check (< 20% of summary words in source)
    src_words  = set(state.raw_text.lower().split())
    summ_words = set(lower)
    if summ_words and len(summ_words & src_words) / len(summ_words) < 0.20:
        raise WorkflowJumpDirective(target_step_name="FallbackExtract")

    ratio = round(len(words) / max(state.word_count, 1), 3)
    return {"compression_ratio": ratio, "quality": "GOOD"}


def fallback_extract(state: DocumentState, context: StepContext, **_):
    if state.quality == "GOOD":
        return {}  # normal path — no-op
    sentences = _re.split(r'(?<=[.!?])\\s+', state.raw_text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
    summary = " ".join(sentences[:3])
    ratio = round(len(summary.split()) / max(state.word_count, 1), 3)
    return {
        "summary": summary,
        "compression_ratio": ratio,
        "quality": "FALLBACK",
        "method": "extractive-sentence",
    }


wf4_steps = [
    WorkflowStep(name="IngestDocument",  func=ingest_document,  automate_next=True),
    WorkflowStep(name="PreprocessText",  func=preprocess_text,  automate_next=True),
    WorkflowStep(name="GenerateSummary", func=generate_summary, automate_next=True),
    WorkflowStep(name="ExtractKeywords", func=extract_keywords, automate_next=True),
    WorkflowStep(name="QualityDecision", func=quality_decision, automate_next=True),
    WorkflowStep(name="FallbackExtract", func=fallback_extract, automate_next=False),
]


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 5 — Air-Gapped Field Tech Triage (PII Redaction + Semantic Routing)
# Steps: CaptureReport → RunNERAnalysis → BuildRedactedPayload →
#         RouteByPriority → LogStandard ⤷ EscalateIncident → StoreForForward
# On-device NER strips PII before any SAF record is created.
# ══════════════════════════════════════════════════════════════════════════════

import re as _re

class FieldTechState(BaseModel):
    raw_input: str = ""
    severity: str = "UNKNOWN"
    incident_type: str = "GENERAL"
    redacted_text: str = ""
    pii_entities: list = []
    saf_record_id: str = ""
    routed_to: str = ""
    ner_latency_ms: float = 0.0


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
        ids = _re.findall(r'\b(?:employee\s+ID|ID)[:\s#]?\s*\d{4,}\b', state.raw_input, _re.IGNORECASE)
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


wf5_steps = [
    WorkflowStep(name="CaptureReport",        func=capture_report,        automate_next=True),
    WorkflowStep(name="RunNERAnalysis",        func=run_ner_analysis,      automate_next=True),
    WorkflowStep(name="BuildRedactedPayload",  func=build_redacted_payload, automate_next=True),
    WorkflowStep(name="RouteByPriority",       func=route_by_priority,     automate_next=True),
    WorkflowStep(name="LogStandard",           func=log_standard_incident, automate_next=True),
    WorkflowStep(name="EscalateIncident",      func=escalate_incident,     automate_next=True),
    WorkflowStep(name="StoreForForward",       func=store_for_forward,     automate_next=False),
]


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW 6 — Paged Reasoning (BitNet shard paging demo)
# Steps: AssessComplexity → [jump if simple] → FullPagedInference
#        → FastPath (guard) → FormatOutput
# ══════════════════════════════════════════════════════════════════════════════

class PagedReasoningState(BaseModel):
    prompt: str = ""
    complexity_score: float = 0.0
    shards_loaded: int = 0
    generated_text: str = ""
    tokens_generated: int = 0
    latency_ms: float = 0.0
    path_taken: str = ""


# Default prompts shown in the UI when the text area is empty
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
        complex_keywords = ["diagnos", "analys", "explain", "reason", "troubleshoot",
                            "root cause", "cascad", "intermittent", "multi-step"]
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
        import json as _json
        payload = _json.dumps({"prompt": state.prompt or _PAGED_DEMO_PROMPTS[1], "threshold": 0.4})
        result = await runPagedInference(payload, 128)
        return {
            "generated_text": str(result.text),
            "tokens_generated": int(result.tokens_generated),
            "shards_loaded": int(result.shards_loaded),
            "latency_ms": round(float(result.latency_ms), 1),
        }
    except Exception:
        # Fallback: simulate full inference output without wllama
        return {
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
    # Guard: normal path that didn't jump here (complexity >= 0.4)
    if state.complexity_score >= 0.4:
        return {}
    try:
        from js import runPagedInference  # type: ignore[import]
        import json as _json
        payload = _json.dumps({"prompt": state.prompt or _PAGED_DEMO_PROMPTS[0], "threshold": 0.9})
        result = await runPagedInference(payload, 64)
        return {
            "generated_text": str(result.text),
            "tokens_generated": int(result.tokens_generated),
            "shards_loaded": int(result.shards_loaded),
            "latency_ms": round(float(result.latency_ms), 1),
        }
    except Exception:
        return {
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


wf6_steps = [
    WorkflowStep(name="AssessComplexity",    func=assess_complexity,     automate_next=True),
    WorkflowStep(name="FullPagedInference",  func=full_paged_inference,  automate_next=True),
    WorkflowStep(name="FastPath",            func=fast_path,             automate_next=True),
    WorkflowStep(name="FormatOutput",        func=format_output,         automate_next=False),
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
    elif wf_type == "DocumentSummarisation":
        wf = await _make_workflow(wf_type, wf4_steps, DocumentState, data)
    elif wf_type == "FieldTechTriage":
        wf = await _make_workflow(wf_type, wf5_steps, FieldTechState, data)
    elif wf_type == "PagedReasoning":
        wf = await _make_workflow(wf_type, wf6_steps, PagedReasoningState, data)
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
            _loadedPyodideUrl = url;
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

    // Initialise OPFS shard cache (Workflow 6 — Paged Reasoning)
    await _opfsCache.init();

    // Dynamic import — errors are catchable and produce real messages
    const { loadPyodide, indexURL } = await loadPyodideDynamic();
    pyodide = await loadPyodide({ indexURL });

    // Load Transformers.js (optional — workflow 3 falls back gracefully if absent)
    for (const url of TRANSFORMERS_CDNS) {
        try {
            const tfMod = await import(url);
            _pipeline = tfMod.pipeline;
            _loadedTransformersUrl = url;
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

    // Probe for a co-located wheel (works for local dev AND GitHub Pages / any
    // host that serves the wheel alongside the demo).  Falls back to TestPyPI
    // when no wheel is found at the same origin (bare two-file share scenario).
    try {
        const probe = await fetch(
            `${self.location.origin}/dist/rufus_sdk-1.0.0rc2-py3-none-any.whl`,
            { method: "HEAD" }
        );
        if (probe.ok) {
            _wheelUrl = `${self.location.origin}/dist/rufus_sdk-1.0.0rc2-py3-none-any.whl`;
        }
    } catch (_) {
        // network error or CORS block → leave _wheelUrl as null → TestPyPI path
    }

    const _usingLocalWheel = _wheelUrl !== null;
    self.postMessage({ type: "status", message: _usingLocalWheel
        ? "Installing rufus-sdk from local wheel…"
        : "Installing rufus-sdk from TestPyPI…" });

    pyodide.globals.set("_wheel_url", _wheelUrl);
    // Mock native-code packages that have no WASM wheel so micropip's dependency
    // resolver sees them as satisfied without trying to download them.
    // Then install the rufus-sdk wheel (or fetch from TestPyPI as fallback).
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

if _wheel_url:
    # Local dev or Pages deploy: load from co-located wheel (fast, no CDN needed)
    await micropip.install(_wheel_url, keep_going=True)
else:
    # Bare two-file share: TestPyPI doesn't carry all transitive deps, so
    # pre-install the ones that only exist on PyPI, then pull rufus-sdk itself
    # from TestPyPI (micropip skips deps it already sees as satisfied).
    await micropip.install(
        ["anyio", "alembic", "typer", "aiosqlite", "python-dotenv", "croniter"],
        keep_going=True,
    )
    await micropip.install(
        "rufus-sdk==1.0.0rc2",
        index_urls=["https://test.pypi.org/simple/", "https://pypi.org/simple/"],
        keep_going=True,
    )
`);

    self.postMessage({ type: "status", message: "Initialising Python workflow engine…" });
    await pyodide.runPythonAsync(PYTHON_SETUP);

    const gpuAvailable = _pipeline !== null && _gpuDevice === "webgpu";
    self.postMessage({ type: "webgpu_status", supported: gpuAvailable });
    self.postMessage({ type: "ready" });
}

// ─── Preflight inspector ──────────────────────────────────────────────────────
async function gatherPreflight() {
    // runtime section
    const est = await checkStorageQuota().catch(() => null);
    const runtime = {
        pyodide_url:       _loadedPyodideUrl,
        pyodide_version:   pyodide ? pyodide.version : null,
        transformers_url:  _loadedTransformersUrl,
        webgpu:            _gpuDevice,
        active_model:      _activeModel,
        wheel_url:         _wheelUrl,
        storage_usage:     est?.usageBytes ?? null,
        storage_quota:     est?.quotaBytes ?? null,
        storage_pct:       est?.pct        ?? null,
    };

    // packages — from micropip.list() in Python
    let packages = {};
    if (pyodide) {
        try {
            const raw = await pyodide.runPythonAsync(
                "import micropip, json; json.dumps({k: {'version': str(v.version), 'source': str(getattr(v, 'source', '') or '')} for k, v in micropip.list().items()})"
            );
            packages = JSON.parse(raw);
        } catch (_) {}
    }

    // cache stores — iterate Cache Storage, sum Content-Length headers (no body reads)
    let cacheStores = [];
    try {
        const cacheNames = await caches.keys();
        for (const name of cacheNames) {
            try {
                const cache = await caches.open(name);
                const requests = await cache.keys();
                let sizeBytes = 0;
                for (const req of requests) {
                    try {
                        const resp = await cache.match(req);
                        if (resp) {
                            const cl = resp.headers.get("Content-Length");
                            if (cl) sizeBytes += parseInt(cl, 10);
                        }
                    } catch (_) {}
                }
                cacheStores.push({ name, count: requests.length, size_bytes: sizeBytes });
            } catch (_) {}
        }
    } catch (_) {}

    // IndexedDB counts
    let idb = { workflows: 0, audit_events: 0 };
    try {
        const db = await openIDB();
        await new Promise((resolve) => {
            const tx = db.transaction(["workflows", "audit_events"], "readonly");
            const wReq = tx.objectStore("workflows").count();
            const aReq = tx.objectStore("audit_events").count();
            let done = 0;
            const check = () => { if (++done === 2) { db.close(); resolve(); } };
            wReq.onsuccess = () => { idb.workflows    = wReq.result; check(); };
            aReq.onsuccess = () => { idb.audit_events = aReq.result; check(); };
            wReq.onerror = aReq.onerror = () => { check(); };
        });
    } catch (_) {}

    return { runtime, packages, cacheStores, idb };
}

// ─── Message dispatcher ───────────────────────────────────────────────────────
self.onmessage = async (e) => {
    const { type, workflowType, data, modelSettings } = e.data;

    if (type === "run_workflow") {
        if (modelSettings) _currentModelSettings = modelSettings;
        if (_workflowRunning) {
            self.postMessage({ type: "workflow_error", workflowType,
                               message: "A workflow is already running — please wait." });
            return;
        }
        _workflowRunning = true;
        self.postMessage({ type: "workflow_start", workflowType });
        const TIMEOUT_MS = { TransactionRiskScoring: 60_000,
                             DocumentSummarisation:  90_000,
                             FieldTechTriage:        60_000,
                             PagedReasoning:         120_000 }[workflowType] ?? 30_000;
        let timedOut = false;
        const timeoutId = setTimeout(() => {
            timedOut = true;
            self.postMessage({ type: "workflow_timeout", workflowType });
        }, TIMEOUT_MS);
        try {
            pyodide.globals.set("_wf_type", workflowType);
            pyodide.globals.set("_wf_data", JSON.stringify(data || {}));
            await pyodide.runPythonAsync("await run_workflow(_wf_type, _wf_data)");
            // result dispatched inside Python via notifyWorkflowDone / notifyWorkflowError
        } catch (err) {
            if (!timedOut) {
                self.postMessage({ type: "workflow_error", workflowType,
                                   message: err.message || String(err) });
            }
        } finally {
            clearTimeout(timeoutId);
            _workflowRunning = false;
        }

    } else if (type === "preflight_check") {
        try {
            const data = await gatherPreflight();
            self.postMessage({ type: "preflight_result", data });
        } catch (err) {
            self.postMessage({ type: "preflight_result", data: null, error: err.message });
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
