/**
 * intent_worker.js — Semantic intent resolution for Ruvon Swarm Studio.
 *
 * Uses Xenova/all-MiniLM-L6-v2 (23 MB, cached in OPFS after first load) to
 * embed the user's free-text query and return the closest formation preset by
 * cosine similarity.
 *
 * Embeddings are pre-computed for each preset's description at startup and
 * stored in memory; only the user's query needs inference at request time.
 *
 * Messages in  (from main thread):
 *   { type: "INIT" }                  — load model, pre-compute preset embeddings
 *   { type: "RESOLVE", text, reqId }  — classify text, reply with RESOLVED
 *
 * Messages out (to main thread):
 *   { type: "LOADING" }               — model download started
 *   { type: "READY" }                 — model loaded, embeddings cached
 *   { type: "PROGRESS", pct }         — download progress (0–100)
 *   { type: "RESOLVED", preset, confidence, reqId }
 *   { type: "ERROR", message }
 */

"use strict";

const TRANSFORMERS_CDNS = [
  "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3/dist/transformers.min.js",
  "https://cdn.jsdelivr.net/npm/@xenova/transformers@2/dist/transformers.min.js",
];

// ---------------------------------------------------------------------------
// Formation descriptions — richer than preset names for better embedding match
// ---------------------------------------------------------------------------
const PRESET_DESCRIPTIONS = {
  circle:    "circular ring concentric loops orbit rotating round formation",
  heart:     "heart love romantic Valentine affection pulsing heart shape",
  horse:     "running galloping horse animal silhouette equestrian quadruped",
  birds:     "V-formation bird flock flying geese migrating wing spread",
  waterfall: "cascading waterfall streaming water falling droplets torrent",
  spiral:    "spiral helix swirl galaxy tornado vortex spinning outward",
  diamond:   "diamond rhombus square geometric facets crystal gem lattice",
  ruvon:     "R letter logo brand Ruvon identity monogram initial",
};

const PRESET_NAMES = Object.keys(PRESET_DESCRIPTIONS);

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let _pipeline = null;
let _presetEmbeddings = null;  // Map<preset, Float32Array>
let _ready = false;

// ---------------------------------------------------------------------------
// Cosine similarity between two Float32Arrays
// ---------------------------------------------------------------------------
function cosineSim(a, b) {
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na  += a[i] * a[i];
    nb  += b[i] * b[i];
  }
  return dot / (Math.sqrt(na) * Math.sqrt(nb) + 1e-8);
}

// Mean-pool token embeddings → single sentence vector
function meanPool(tensor) {
  // tensor.data: Float32Array of shape [1, seq_len, hidden_dim]
  const data = tensor.data;
  const [, seqLen, dim] = tensor.dims;
  const result = new Float32Array(dim);
  for (let t = 0; t < seqLen; t++) {
    for (let d = 0; d < dim; d++) {
      result[d] += data[t * dim + d];
    }
  }
  for (let d = 0; d < dim; d++) result[d] /= seqLen;
  return result;
}

// ---------------------------------------------------------------------------
// Model initialisation
// ---------------------------------------------------------------------------
async function loadModel() {
  self.postMessage({ type: "LOADING" });

  let mod = null;
  for (const url of TRANSFORMERS_CDNS) {
    try {
      mod = await import(url);
      break;
    } catch (_) {}
  }
  if (!mod) throw new Error("Could not load transformers.js from any CDN");

  const { pipeline, env } = mod;

  // Use OPFS for model caching (same pattern as demo1)
  if (typeof caches !== "undefined" || typeof globalThis.FileSystemDirectoryHandle !== "undefined") {
    try { env.useCustomCache = true; } catch (_) {}
  }
  env.allowLocalModels = false;

  _pipeline = await pipeline(
    "feature-extraction",
    "Xenova/all-MiniLM-L6-v2",
    {
      device: "wasm",   // reliable cross-browser; GPU not needed for 23MB model
      dtype: "fp32",
      progress_callback: ({ status, progress }) => {
        if (status === "progress" && typeof progress === "number") {
          self.postMessage({ type: "PROGRESS", pct: Math.round(progress) });
        }
      },
    }
  );

  // Pre-compute embeddings for all preset descriptions
  _presetEmbeddings = new Map();
  for (const [preset, desc] of Object.entries(PRESET_DESCRIPTIONS)) {
    const out = await _pipeline(desc, { pooling: "mean", normalize: true });
    _presetEmbeddings.set(preset, out.data.slice());  // clone Float32Array
  }

  _ready = true;
  self.postMessage({ type: "READY" });
}

// ---------------------------------------------------------------------------
// Resolve a free-text query to a preset name
// ---------------------------------------------------------------------------
async function resolve(text, reqId) {
  if (!_ready) {
    // Fall back gracefully — main thread will use client-side resolver
    self.postMessage({ type: "RESOLVED", preset: null, confidence: 0, reqId });
    return;
  }

  const out = await _pipeline(text, { pooling: "mean", normalize: true });
  const qVec = out.data.slice();

  let bestPreset = "circle", bestSim = -1;
  for (const [preset, vec] of _presetEmbeddings) {
    const sim = cosineSim(qVec, vec);
    if (sim > bestSim) { bestSim = sim; bestPreset = preset; }
  }

  self.postMessage({
    type: "RESOLVED",
    preset: bestPreset,
    confidence: parseFloat(bestSim.toFixed(3)),
    reqId,
  });
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
        await loadModel();
        break;
      case "RESOLVE":
        await resolve(msg.text, msg.reqId);
        break;
    }
  } catch (err) {
    self.postMessage({ type: "ERROR", message: err.message });
  }
};
