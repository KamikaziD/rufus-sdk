/**
 * formations.js — Preset formation target positions for the Ruvon Swarm Studio.
 *
 * Each preset is defined as a function that returns an array of normalized
 * {x, y} coordinates in [0, 1] space. The renderer scales to canvas size.
 *
 * Patterns: HORSE, HEART, BIRDS, WATERFALL, CIRCLE, SPIRAL, DIAMOND, RUVON
 */

"use strict";

// ---------------------------------------------------------------------------
// Utility: sample N points from a parametric curve
// ---------------------------------------------------------------------------
function sampleCurve(fn, n, tMin = 0, tMax = 1) {
  const pts = [];
  for (let i = 0; i < n; i++) {
    const t = tMin + (i / (n - 1)) * (tMax - tMin);
    pts.push(fn(t));
  }
  return pts;
}

// Normalize a point cloud so it fills [margin, 1-margin]² centered
function normalize(pts, margin = 0.05) {
  const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const rangeX = maxX - minX || 1, rangeY = maxY - minY || 1;
  const scale = Math.min((1 - 2 * margin) / rangeX, (1 - 2 * margin) / rangeY);
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  return pts.map(p => ({
    x: 0.5 + (p.x - cx) * scale,
    y: 0.5 + (p.y - cy) * scale,
  }));
}

// Add grid-jittered fill points to reach target count
function fillToCount(pts, n, jitter = 0.015) {
  if (pts.length >= n) return pts.slice(0, n);
  const result = [...pts];
  let i = 0;
  while (result.length < n) {
    const base = pts[i % pts.length];
    result.push({
      x: Math.max(0.02, Math.min(0.98, base.x + (Math.random() - 0.5) * jitter * 2)),
      y: Math.max(0.02, Math.min(0.98, base.y + (Math.random() - 0.5) * jitter * 2)),
    });
    i++;
  }
  return result;
}

// ---------------------------------------------------------------------------
// CIRCLE — baseline / default / unknown intent
// ---------------------------------------------------------------------------
function circleFormation(n) {
  const pts = [];
  // Concentric rings
  let remaining = n;
  let ring = 0;
  while (remaining > 0) {
    const r = 0.08 + ring * 0.08;
    const count = ring === 0 ? 1 : Math.min(remaining, Math.round(2 * Math.PI * r / 0.06));
    for (let i = 0; i < count && remaining > 0; i++) {
      const angle = (2 * Math.PI * i) / count;
      pts.push({ x: 0.5 + r * Math.cos(angle), y: 0.5 + r * Math.sin(angle) });
      remaining--;
    }
    ring++;
  }
  return pts;
}

// ---------------------------------------------------------------------------
// HEART
// ---------------------------------------------------------------------------
function heartFormation(n) {
  // Parametric heart: x = 16sin³(t), y = 13cos(t) - 5cos(2t) - 2cos(3t) - cos(4t)
  const outline = Math.min(n, Math.ceil(n * 0.6));
  const fill    = n - outline;

  const outlinePts = sampleCurve(t => {
    const a = t * 2 * Math.PI;
    return {
      x:  16 * Math.pow(Math.sin(a), 3) / 17,
      y: -(13 * Math.cos(a) - 5 * Math.cos(2 * a) - 2 * Math.cos(3 * a) - Math.cos(4 * a)) / 17,
    };
  }, outline);

  // Fill: random points inside the heart (rejection sampling)
  const fillPts = [];
  let attempts = 0;
  while (fillPts.length < fill && attempts < fill * 20) {
    attempts++;
    const u = Math.random() * 2 - 1, v = Math.random() * 2 - 1;
    // Heart interior test: u² + (v - |u|^(2/3))² < 1  (approximate)
    const abs = Math.abs(u);
    if (u * u + Math.pow(v - Math.pow(abs, 2 / 3), 2) < 0.85) {
      fillPts.push({ x: u / 1.7, y: (-v + 0.3) / 1.7 });
    }
  }

  return normalize([...outlinePts, ...fillPts]);
}

// ---------------------------------------------------------------------------
// HORSE (running silhouette approximated from key waypoints)
// ---------------------------------------------------------------------------
function horseFormation(n) {
  // Rough running horse outline as hand-tuned control points (normalized 0..1)
  // Traced from a silhouette: head up-right, body, legs extended
  const controlPts = [
    // Head
    { x: 0.72, y: 0.08 }, { x: 0.78, y: 0.10 }, { x: 0.82, y: 0.14 },
    { x: 0.80, y: 0.18 }, { x: 0.76, y: 0.20 },
    // Neck
    { x: 0.70, y: 0.22 }, { x: 0.64, y: 0.26 },
    // Back (top line)
    { x: 0.56, y: 0.24 }, { x: 0.44, y: 0.25 }, { x: 0.32, y: 0.28 },
    { x: 0.22, y: 0.34 },
    // Rump + tail
    { x: 0.14, y: 0.30 }, { x: 0.08, y: 0.26 }, { x: 0.04, y: 0.28 },
    { x: 0.06, y: 0.32 },
    // Hind legs (extended back)
    { x: 0.12, y: 0.36 }, { x: 0.10, y: 0.50 }, { x: 0.08, y: 0.64 },
    { x: 0.10, y: 0.72 }, { x: 0.14, y: 0.74 },
    { x: 0.18, y: 0.70 }, { x: 0.20, y: 0.56 },
    { x: 0.24, y: 0.44 }, { x: 0.28, y: 0.38 },
    // Belly
    { x: 0.36, y: 0.40 }, { x: 0.48, y: 0.40 }, { x: 0.58, y: 0.40 },
    // Front legs (extended forward)
    { x: 0.62, y: 0.42 }, { x: 0.66, y: 0.54 }, { x: 0.68, y: 0.68 },
    { x: 0.72, y: 0.74 }, { x: 0.76, y: 0.72 },
    { x: 0.76, y: 0.58 }, { x: 0.74, y: 0.44 },
    { x: 0.78, y: 0.40 }, { x: 0.82, y: 0.44 }, { x: 0.84, y: 0.56 },
    { x: 0.86, y: 0.70 }, { x: 0.88, y: 0.74 },
    { x: 0.90, y: 0.72 }, { x: 0.88, y: 0.58 }, { x: 0.84, y: 0.44 },
    // Chest back to neck
    { x: 0.72, y: 0.34 }, { x: 0.68, y: 0.26 },
  ];

  return fillToCount(normalize(controlPts, 0.04), n, 0.025);
}

// ---------------------------------------------------------------------------
// BIRDS (V-formation flock)
// ---------------------------------------------------------------------------
function birdsFormation(n) {
  const pts = [];
  // Lead bird at center-top
  pts.push({ x: 0.5, y: 0.12 });

  // V-wings: each layer adds 2 birds per side
  let layer = 1;
  while (pts.length < n) {
    const spread = layer * 0.06;
    const drop   = layer * 0.05;
    // Left wing
    for (let k = 0; k < layer && pts.length < n; k++) {
      pts.push({ x: 0.5 - spread - k * 0.04, y: 0.12 + drop + k * 0.03 });
    }
    // Right wing
    for (let k = 0; k < layer && pts.length < n; k++) {
      pts.push({ x: 0.5 + spread + k * 0.04, y: 0.12 + drop + k * 0.03 });
    }
    layer++;
  }
  return normalize(pts.slice(0, n), 0.06);
}

// ---------------------------------------------------------------------------
// WATERFALL (cascading streams)
// ---------------------------------------------------------------------------
function waterfallFormation(n) {
  const streams = 7;
  const pts = [];
  for (let s = 0; s < streams; s++) {
    const xBase = 0.1 + (s / (streams - 1)) * 0.8;
    const count  = Math.round(n / streams);
    for (let i = 0; i < count; i++) {
      const t = i / count;
      // Slight sine sway per stream, staggered phase
      const xSway = 0.015 * Math.sin(t * Math.PI * 6 + (s * 0.8));
      pts.push({ x: xBase + xSway, y: 0.05 + t * 0.88 });
    }
  }
  return fillToCount(pts, n, 0.01);
}

// ---------------------------------------------------------------------------
// SPIRAL
// ---------------------------------------------------------------------------
function spiralFormation(n) {
  const turns = 3.5;
  return normalize(sampleCurve(t => {
    const angle = t * turns * 2 * Math.PI;
    const r = 0.05 + t * 0.42;
    return { x: r * Math.cos(angle), y: r * Math.sin(angle) };
  }, n), 0.04);
}

// ---------------------------------------------------------------------------
// DIAMOND
// ---------------------------------------------------------------------------
function diamondFormation(n) {
  const pts = [];
  const layers = Math.ceil(Math.sqrt(n / 2));
  for (let l = 0; l <= layers && pts.length < n; l++) {
    const w = l;
    for (let i = -w; i <= w && pts.length < n; i++) {
      if (Math.abs(i) + Math.abs(l - layers / 2) <= layers) {
        pts.push({ x: i / layers * 0.5, y: (l / layers - 0.5) * 0.9 });
      }
    }
  }
  return normalize(fillToCount(pts, n, 0.02), 0.04);
}

// ---------------------------------------------------------------------------
// RUVON logo-ish (R shape)
// ---------------------------------------------------------------------------
function ruvonFormation(n) {
  const pts = [];
  // Vertical stroke
  for (let i = 0; i < 20; i++) pts.push({ x: 0.2, y: 0.1 + i * 0.04 });
  // Top arch of R
  for (let t = 0; t <= 1; t += 0.05) {
    const angle = -Math.PI / 2 + t * Math.PI;
    pts.push({ x: 0.2 + 0.18 + 0.18 * Math.cos(angle), y: 0.1 + 0.12 + 0.12 * Math.sin(angle) });
  }
  // Horizontal mid-bar
  for (let i = 0; i < 8; i++) pts.push({ x: 0.2 + i * 0.022, y: 0.34 });
  // Diagonal leg
  for (let i = 0; i < 14; i++) pts.push({ x: 0.38 + i * 0.03, y: 0.34 + i * 0.045 });

  return fillToCount(normalize(pts, 0.06), n, 0.03);
}

// ---------------------------------------------------------------------------
// Lookup table + fuzzy matcher
// ---------------------------------------------------------------------------
export const PRESETS = {
  circle:    circleFormation,
  heart:     heartFormation,
  horse:     horseFormation,
  birds:     birdsFormation,
  waterfall: waterfallFormation,
  spiral:    spiralFormation,
  diamond:   diamondFormation,
  ruvon:     ruvonFormation,
};

// Aliases and common variants
const ALIASES = {
  "running horse": "horse", "galloping horse": "horse", "horse running": "horse",
  "flock": "birds", "flocking birds": "birds", "bird flock": "birds", "v formation": "birds",
  "pulsing heart": "heart", "love": "heart",
  "cascading waterfall": "waterfall", "cascade": "waterfall", "falling water": "waterfall",
  "helix": "spiral", "swirl": "spiral",
  "rhombus": "diamond", "square": "diamond",
  "logo": "ruvon", "r": "ruvon",
};

/** Levenshtein distance for fuzzy matching */
function levenshtein(a, b) {
  const m = a.length, n = b.length;
  const dp = Array.from({ length: m + 1 }, (_, i) => [i, ...Array(n).fill(0)]);
  for (let j = 0; j <= n; j++) dp[0][j] = j;
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1]
               : 1 + Math.min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1]);
  return dp[m][n];
}

/**
 * Resolve a free-text intent string to a preset name.
 * Returns the preset name (always valid — falls back to "circle").
 */
export function resolveIntent(text) {
  const t = text.trim().toLowerCase();
  if (!t) return "circle";

  // Exact match
  if (PRESETS[t]) return t;

  // Alias match
  if (ALIASES[t]) return ALIASES[t];

  // Fuzzy: find closest preset/alias key
  const candidates = [...Object.keys(PRESETS), ...Object.keys(ALIASES)];
  let best = "circle", bestDist = Infinity;
  for (const cand of candidates) {
    const dist = levenshtein(t, cand);
    if (dist < bestDist && dist <= Math.max(3, Math.floor(cand.length / 3))) {
      bestDist = dist;
      best = ALIASES[cand] ?? cand;
    }
  }
  return best;
}

/**
 * Get N formation target positions for a named preset.
 * @param {string} preset  — preset name (from resolveIntent)
 * @param {number} n       — number of drones
 * @returns Array<{x, y}>  normalized [0,1] coordinates
 */
export function getFormationTargets(preset, n) {
  const fn = PRESETS[preset] ?? circleFormation;
  return fn(n);
}
