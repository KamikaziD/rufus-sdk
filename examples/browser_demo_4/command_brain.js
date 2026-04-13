/**
 * command_brain.js — Agentic command brain for Ruvon Swarm Studio.
 *
 * Two-tier inference:
 *   Tier 1 (fast):  MiniLM-L6-v2 (23 MB) — semantic embedding, instant preset match
 *   Tier 2 (smart): wllama GGUF — full LLM reasoning, structured JSON output
 *
 * Model selector:
 *   SmolLM2-135M   88 MB   fast, default
 *   Qwen2.5-0.5B  395 MB   smart
 *   Nemotron-Mini-4B  2.7 GB   powerful (paged loading via wllama)
 *
 * Output (worker → main thread):
 *   LOADING / PROGRESS / READY          — MiniLM download lifecycle
 *   MODEL_LOADING { model, ramMb }      — wllama model download started
 *   MODEL_PROGRESS { loaded, total }    — wllama download progress
 *   MODEL_READY { model }               — wllama model loaded and ready
 *   MODEL_THINKING                      — LLM generation started
 *   TOKEN { piece }                     — streaming token from LLM
 *   COMMAND { action, preset?, content?, pct?, reqId }
 *   ERROR { message }
 *   MODEL_SWITCHED { model }
 *
 * Input (main thread → worker):
 *   INIT
 *   SET_MODEL { model }
 *   RESOLVE { text, reqId }
 *   MODEL_LOADED                        — main thread signals LLM is ready (for mesh scoring)
 */

"use strict";

// ---------------------------------------------------------------------------
// Transformers.js (MiniLM — Tier 1)
// ---------------------------------------------------------------------------
const TRANSFORMERS_CDNS = [
  "https://cdn.jsdelivr.net/npm/@xenova/transformers@2/dist/transformers.min.js",
  "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3/dist/transformers.min.js",
];

// ---------------------------------------------------------------------------
// wllama (GGUF — Tier 2)
// ---------------------------------------------------------------------------
const WLLAMA_CDN  = "https://cdn.jsdelivr.net/npm/wllama@2/esm/wllama.js";
const WLLAMA_BASE = "https://cdn.jsdelivr.net/npm/wllama@2/esm/";
const WLLAMA_PATHS = {
  "single-thread/wllama.wasm": WLLAMA_BASE + "single-thread/wllama.wasm",
  "multi-thread/wllama.wasm":  WLLAMA_BASE + "multi-thread/wllama.wasm",
};
let _wllama = null;
let _wllamaClass = null;

// ---------------------------------------------------------------------------
// Model configs
// ---------------------------------------------------------------------------
const MODEL_CONFIGS = {
  "SmolLM2-135M": {
    label: "SmolLM2-135M · 88 MB · fast",
    urls: ["https://huggingface.co/QuantFactory/SmolLM2-135M-Instruct-GGUF/resolve/main/SmolLM2-135M-Instruct.Q4_K_M.gguf"],
    ramMb: 120,
    maxTokens: 80,
  },
  "Qwen2.5-0.5B": {
    label: "Qwen2.5-0.5B · 395 MB · smart",
    urls: ["https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"],
    ramMb: 450,
    maxTokens: 100,
  },
  "Nemotron-Mini-4B": {
    label: "Nemotron-Mini-4B · 2.7 GB · powerful",
    // Single Q4_K_M file — wllama handles fetch in chunks; OPFS caches after first load
    urls: ["https://huggingface.co/bartowski/Nemotron-Mini-4B-Instruct-GGUF/resolve/main/Nemotron-Mini-4B-Instruct-Q4_K_M.gguf"],
    ramMb: 2700,
    maxTokens: 120,
  },
};

let _activeModel = "SmolLM2-135M";

// ---------------------------------------------------------------------------
// OPFS shard cache (verbatim from browser_demo/worker.js)
// ---------------------------------------------------------------------------
class OPFSShardCache {
  constructor() { this._root = null; }

  async init() {
    try {
      this._root = await navigator.storage.getDirectory();
    } catch (_) {
      this._root = null;
    }
  }

  async has(id) {
    if (!this._root) return false;
    try { await this._root.getFileHandle(id); return true; } catch { return false; }
  }

  async write(id, buffer) {
    if (!this._root) return;
    try {
      const fh = await this._root.getFileHandle(id, { create: true });
      const writable = await fh.createWritable();
      await writable.write(buffer);
      await writable.close();
    } catch (_) {}
  }

  async read(id) {
    if (!this._root) return null;
    try {
      const fh = await this._root.getFileHandle(id);
      const file = await fh.getFile();
      return file.arrayBuffer();
    } catch { return null; }
  }
}

const _opfsCache = new OPFSShardCache();

// ---------------------------------------------------------------------------
// Promise-chain model mutex (verbatim from browser_demo/worker.js)
// ---------------------------------------------------------------------------
let _modelMutex = Promise.resolve();

// ---------------------------------------------------------------------------
// MiniLM — Tier 1 semantic embeddings
// ---------------------------------------------------------------------------
const PRESET_DESCRIPTIONS = {
  circle:    "Form a circular ring shape with drones arranged in concentric orbit loops.",
  heart:     "Arrange drones into a heart shape, like a love symbol or Valentine's day heart.",
  horse:     "Make the drones form a running horse or galloping animal silhouette.",
  birds:     "Fly the drones in a V-formation like a migrating bird flock or geese in the sky.",
  waterfall: "Let the drones cascade downward in streams like a waterfall or falling water.",
  spiral:    "Form a spiral or galaxy shape, like a swirling vortex, helix, or spinning galaxy.",
  diamond:   "Arrange drones into a diamond or rhombus shape, like a gem or crystal lattice.",
  ruvon:     "Form the letter R or the Ruvon logo shape with the drones.",
};

// Trigger words that force LLM escalation regardless of MiniLM confidence
const ESCALATION_RE = /\bwrite\b|\bdisplay\b|\bshow\s+\w*\s*word|\bspell\b|\bdraw\b|\bprint\b|\bthe\s+word\b|\btext\b|\bletter\b|\bword\b|\btype\b|\bsay\b/i;

let _miniLm = null;
let _presetEmbeddings = null;
let _miniLmReady = false;

function cosineSim(a, b) {
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i];
  }
  return dot / (Math.sqrt(na) * Math.sqrt(nb) + 1e-8);
}

async function loadMiniLm() {
  self.postMessage({ type: "LOADING" });

  let pipeline, env;
  let lastErr = null;
  for (const url of TRANSFORMERS_CDNS) {
    try {
      const mod = await import(url);
      pipeline = mod.pipeline; env = mod.env;
      break;
    } catch (e) { lastErr = e; }
  }
  if (!pipeline) throw new Error("Could not load transformers.js: " + (lastErr?.message ?? "unknown"));

  try { env.allowLocalModels = false; } catch (_) {}
  try { env.allowRemoteModels = true; } catch (_) {}

  _miniLm = await pipeline(
    "feature-extraction",
    "Xenova/all-MiniLM-L6-v2",
    {
      progress_callback: ({ status, progress }) => {
        if (status === "progress" && typeof progress === "number")
          self.postMessage({ type: "PROGRESS", pct: Math.round(progress) });
      },
    }
  );

  // Pre-compute preset embeddings
  _presetEmbeddings = new Map();
  for (const [preset, desc] of Object.entries(PRESET_DESCRIPTIONS)) {
    const out = await _miniLm(desc, { pooling: "mean", normalize: true });
    _presetEmbeddings.set(preset, out.data instanceof Float32Array ? out.data.slice() : new Float32Array(out.data));
  }

  _miniLmReady = true;
  self.postMessage({ type: "READY" });
}

async function runMiniLm(text) {
  if (!_miniLmReady || !_miniLm) return { preset: "circle", confidence: 0 };
  const out = await _miniLm(text, { pooling: "mean", normalize: true });
  const qVec = out.data instanceof Float32Array ? out.data.slice() : new Float32Array(out.data);
  let best = "circle", bestSim = -1;
  for (const [preset, vec] of _presetEmbeddings) {
    const sim = cosineSim(qVec, vec);
    if (sim > bestSim) { bestSim = sim; best = preset; }
  }
  return { preset: best, confidence: parseFloat(bestSim.toFixed(3)) };
}

// ---------------------------------------------------------------------------
// wllama — Tier 2 LLM reasoning
// ---------------------------------------------------------------------------
const SYSTEM_PROMPT = `You are the command brain of a drone swarm. Parse the user's instruction and respond with ONLY a single-line JSON object. No prose, no markdown, no explanation.

Available actions:
  {"action":"formation","preset":"circle|heart|horse|birds|waterfall|spiral|diamond|ruvon"}
  {"action":"text","content":"SHORT TEXT OR WORD"}
  {"action":"scatter"}
  {"action":"fail","pct":10}
  {"action":"recover"}

Examples:
"show a running horse" -> {"action":"formation","preset":"horse"}
"display the word RUVON" -> {"action":"text","content":"RUVON"}
"write TEST" -> {"action":"text","content":"TEST"}
"spell HELLO WORLD" -> {"action":"text","content":"HELLO WORLD"}
"form a galaxy" -> {"action":"formation","preset":"spiral"}
"arrange like a blooming flower" -> {"action":"formation","preset":"spiral"}
"scatter" -> {"action":"scatter"}
"fail 20 percent" -> {"action":"fail","pct":20}`;

let _wllama_loaded_model = null;  // track which model is currently loaded

async function ensureWllama() {
  if (_wllamaClass) return;
  try {
    const mod = await import(WLLAMA_CDN);
    _wllamaClass = mod.Wllama || mod.default;
  } catch (_) {
    _wllamaClass = null;
  }
}

async function runLLM(text, reqId) {
  const cfg = MODEL_CONFIGS[_activeModel];
  self.postMessage({ type: "MODEL_LOADING", model: _activeModel, ramMb: cfg.ramMb });

  await ensureWllama();
  if (!_wllamaClass) {
    // wllama unavailable — graceful fallback
    self.postMessage({ type: "MODEL_READY", model: _activeModel });
    return null;
  }

  // Evict if different model loaded
  if (_wllama && _wllama_loaded_model !== _activeModel) {
    try { await _wllama.exit(); } catch (_) {}
    _wllama = null;
    _wllama_loaded_model = null;
  }

  if (!_wllama) {
    _wllama = new _wllamaClass(WLLAMA_PATHS);
    const url = cfg.urls.length === 1 ? cfg.urls[0] : cfg.urls;
    await _wllama.loadModelFromUrl(url, {
      useCache: true,
      progressCallback: ({ loaded, total }) => {
        self.postMessage({ type: "MODEL_PROGRESS", loaded, total, model: _activeModel });
      },
    });
    _wllama_loaded_model = _activeModel;
    self.postMessage({ type: "MODEL_READY", model: _activeModel });
    // Tell main thread the LLM is ready (for mesh scoring boost)
    self.postMessage({ type: "LLM_READY" });
  }

  self.postMessage({ type: "MODEL_THINKING" });

  // Build chat prompt
  const prompt = `<|system|>\n${SYSTEM_PROMPT}\n<|user|>\n${text}\n<|assistant|>\n`;
  let accumulated = "";
  await _wllama.createCompletion(prompt, {
    nPredict: cfg.maxTokens,
    temperature: 0.1,
    onNewToken: (_, piece) => {
      accumulated += piece;
      self.postMessage({ type: "TOKEN", piece });
    },
  });

  return accumulated;
}

// ---------------------------------------------------------------------------
// Command parser — extract first valid JSON object from LLM output
// ---------------------------------------------------------------------------
const VALID_ACTIONS = new Set(["formation", "text", "scatter", "fail", "recover"]);
const VALID_PRESETS = new Set(["circle","heart","horse","birds","waterfall","spiral","diamond","ruvon"]);

function parseCommand(raw) {
  if (!raw) return null;
  // Find first {...} block
  const m = raw.match(/\{[^}]+\}/);
  if (!m) return null;
  try {
    const obj = JSON.parse(m[0]);
    if (!VALID_ACTIONS.has(obj.action)) return null;
    if (obj.action === "formation" && !VALID_PRESETS.has(obj.preset)) obj.preset = "circle";
    if (obj.action === "text" && (!obj.content || typeof obj.content !== "string")) return null;
    if (obj.action === "fail") obj.pct = Math.max(1, Math.min(100, Number(obj.pct) || 10));
    return obj;
  } catch (_) {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Main resolve entry point
// ---------------------------------------------------------------------------
async function resolve(text, reqId) {
  const trimmed = text.trim();
  if (!trimmed) return;

  // Tier 1: MiniLM
  const { preset: miniLmPreset, confidence } = await runMiniLm(trimmed);
  const needsEscalation = confidence < 0.4 || ESCALATION_RE.test(trimmed);

  if (!needsEscalation) {
    // Fast path — MiniLM is confident, no LLM needed
    self.postMessage({
      type: "COMMAND",
      action: "formation",
      preset: miniLmPreset,
      confidence,
      reqId,
    });
    return;
  }

  // Tier 2: LLM
  let release;
  const prev = _modelMutex;
  _modelMutex = new Promise(r => { release = r; });
  await prev;
  try {
    const raw = await runLLM(trimmed, reqId);
    const cmd = parseCommand(raw);
    if (cmd) {
      self.postMessage({ type: "COMMAND", ...cmd, reqId });
    } else {
      // LLM output not parseable — fall back to MiniLM result
      self.postMessage({
        type: "COMMAND",
        action: "formation",
        preset: miniLmPreset,
        confidence,
        reqId,
      });
    }
  } finally {
    release();
  }
}

// ---------------------------------------------------------------------------
// Message handler
// ---------------------------------------------------------------------------
self.onmessage = async (evt) => {
  const msg = evt.data;
  if (!msg?.type) return;

  try {
    switch (msg.type) {
      case "INIT":
        await _opfsCache.init();
        await loadMiniLm();
        break;

      case "SET_MODEL": {
        const model = msg.model;
        if (!MODEL_CONFIGS[model]) {
          self.postMessage({ type: "ERROR", message: `Unknown model: ${model}` });
          break;
        }
        _activeModel = model;
        // Evict loaded wllama so next inference reloads with new URLs
        // (wllama OPFS cache is preserved — won't re-download)
        if (_wllama && _wllama_loaded_model !== model) {
          let release;
          const prev = _modelMutex;
          _modelMutex = new Promise(r => { release = r; });
          await prev;
          try {
            try { await _wllama.exit(); } catch (_) {}
            _wllama = null;
            _wllama_loaded_model = null;
          } finally { release(); }
        }
        self.postMessage({ type: "MODEL_SWITCHED", model, config: MODEL_CONFIGS[model] });
        break;
      }

      case "RESOLVE":
        await resolve(msg.text, msg.reqId);
        break;
    }
  } catch (err) {
    console.error("[command_brain]", err);
    self.postMessage({ type: "ERROR", message: err.message });
  }
};
