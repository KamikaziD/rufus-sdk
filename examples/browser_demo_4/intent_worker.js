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

// v2 first — proven to work in demo1; v3 as fallback
const TRANSFORMERS_CDNS = [
  "https://cdn.jsdelivr.net/npm/@xenova/transformers@2/dist/transformers.min.js",
  "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3/dist/transformers.min.js",
];

// ---------------------------------------------------------------------------
// Formation descriptions — richer than preset names for better embedding match
// ---------------------------------------------------------------------------
// Full sentences work much better with MiniLM than keyword lists —
// the model was trained on sentence pairs and activates properly on prose.
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

  let pipeline, env;
  let lastErr = null;
  for (const url of TRANSFORMERS_CDNS) {
    try {
      const mod = await import(url);
      pipeline = mod.pipeline;
      env = mod.env;
      break;
    } catch (e) {
      lastErr = e;
    }
  }
  if (!pipeline) throw new Error("Could not load transformers.js: " + (lastErr?.message ?? "unknown"));

  // Disable local model lookup — we always pull from HuggingFace Hub
  try { env.allowLocalModels = false; } catch (_) {}
  try { env.allowRemoteModels = true; } catch (_) {}

  _pipeline = await pipeline(
    "feature-extraction",
    "Xenova/all-MiniLM-L6-v2",
    {
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
    // out may be Tensor{dims:[1,384]} or nested — grab the flat Float32Array
    const vec = out.data instanceof Float32Array ? out.data.slice() : new Float32Array(out.data);
    _presetEmbeddings.set(preset, vec);
  }
  // Debug: log embedding dim so we can verify pooling worked
  const sampleDim = _presetEmbeddings.get("circle")?.length ?? 0;
  console.log("[intent_worker] preset embedding dim:", sampleDim);

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
  const qVec = out.data instanceof Float32Array ? out.data.slice() : new Float32Array(out.data);

  const scores = {};
  let bestPreset = "circle", bestSim = -1;
  for (const [preset, vec] of _presetEmbeddings) {
    const sim = cosineSim(qVec, vec);
    scores[preset] = parseFloat(sim.toFixed(3));
    if (sim > bestSim) { bestSim = sim; bestPreset = preset; }
  }
  console.log("[intent_worker] query:", text, "scores:", scores, "best:", bestPreset, bestSim.toFixed(3));

  self.postMessage({
    type: "RESOLVED",
    preset: bestPreset,
    confidence: parseFloat(bestSim.toFixed(3)),
    scores,
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
    console.error("[intent_worker]", err);
    self.postMessage({ type: "ERROR", message: err.message });
  }
};
