/**
 * browser_loader.js — Pyodide bootstrap for rufus-sdk-edge (browser target).
 *
 * This script runs inside a Web Worker and performs three stages:
 *
 *   1. Load Pyodide (Python runtime compiled to WASM via Emscripten).
 *   2. Initialise wa-sqlite (SQLite compiled to WASM via Emscripten JSPI).
 *   3. Import rufus_edge and start a RufusEdgeAgent instance.
 *
 * The worker communicates with the main thread via postMessage / onmessage.
 *
 * Usage (from main thread):
 *
 *   const worker = new Worker('/path/to/browser_loader.js');
 *   worker.postMessage({
 *     type: 'init',
 *     config: {
 *       device_id: 'browser-001',
 *       cloud_url: 'https://control.example.com',
 *       api_key: 'your-api-key',
 *       db_name: 'rufus_edge',         // IndexedDB / OPFS database name
 *     }
 *   });
 *
 *   worker.onmessage = (event) => {
 *     if (event.data.type === 'ready') console.log('Edge agent started');
 *     if (event.data.type === 'error') console.error(event.data.message);
 *   };
 *
 * Constraints (see TECHNICAL_INFORMATION.md §20):
 *   - Requires Pyodide >= 0.26 with JSPI support (Chrome 123+ / Firefox Nightly)
 *   - wa-sqlite must be available at _RUFUS_WA_SQLITE_URL (see constant below)
 *   - psutil, websockets, httpx are NOT available — replaced by adapter shims
 *   - numpy IS available (bundled with Pyodide)
 */

// ─────────────────────────────────────────────────────────────────────────────
// Configuration constants — adjust for your deployment
// ─────────────────────────────────────────────────────────────────────────────

/** CDN URL for Pyodide. Pin to a specific version for reproducibility. */
const PYODIDE_INDEX_URL = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/';

/** URL for wa-sqlite ES module (OPFS async VFS variant). */
const WA_SQLITE_URL = './wa-sqlite.mjs';

/** Wheel URLs for rufus packages (uploaded to CDN or served locally). */
const RUFUS_WHEEL_URLS = [
  './rufus_sdk-latest-py3-none-any.whl',
  './rufus_sdk_edge-latest-py3-none-any.whl',
];

// ─────────────────────────────────────────────────────────────────────────────
// Stage 1 — Load Pyodide
// ─────────────────────────────────────────────────────────────────────────────

importScripts('https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js');

async function loadPyodideRuntime() {
  const pyodide = await loadPyodide({ indexURL: PYODIDE_INDEX_URL });
  await pyodide.loadPackage(['micropip']);
  return pyodide;
}

// ─────────────────────────────────────────────────────────────────────────────
// Stage 2 — Initialise wa-sqlite and expose to Python
// ─────────────────────────────────────────────────────────────────────────────

async function initWaSqlite(dbName) {
  const { default: SQLiteESMFactory } = await import(WA_SQLITE_URL);
  const sqlite3 = await SQLiteESMFactory();

  // Use OPFS (Origin Private File System) for persistent storage when available,
  // fall back to in-memory storage otherwise.
  let vfs;
  try {
    const { OPFSCoopSyncVFS } = await import('./wa-sqlite-opfs.mjs');
    vfs = new OPFSCoopSyncVFS(sqlite3);
    await vfs.isReady;
    sqlite3.vfs_register(vfs, true);
    console.log('[rufus] wa-sqlite: using OPFS VFS (persistent)');
  } catch (_) {
    console.warn('[rufus] wa-sqlite: OPFS unavailable, falling back to in-memory storage');
  }

  const db = await sqlite3.open_v2(
    dbName,
    sqlite3.SQLITE_OPEN_CREATE | sqlite3.SQLITE_OPEN_READWRITE,
    vfs ? vfs.name : null,
  );

  // Expose handles to Python via globalThis so PyodidePlatformAdapter can find them
  globalThis._rufus_wa_sqlite3 = sqlite3;
  globalThis._rufus_wa_sqlite_db = db;

  console.log(`[rufus] wa-sqlite: database '${dbName}' opened`);
  return { sqlite3, db };
}

// ─────────────────────────────────────────────────────────────────────────────
// Stage 3 — Install rufus wheels and start the edge agent
// ─────────────────────────────────────────────────────────────────────────────

async function startEdgeAgent(pyodide, config) {
  // Install rufus packages from wheel URLs
  const micropip = pyodide.pyimport('micropip');
  for (const wheelUrl of RUFUS_WHEEL_URLS) {
    await micropip.install(wheelUrl);
  }

  // Mark js and pyodide modules as available (detect_platform() uses them)
  // They are already available via Pyodide's built-in js bridge.

  // Bootstrap the edge agent
  await pyodide.runPythonAsync(`
import asyncio
import sys

# Ensure platform detection picks up Pyodide
import pyodide  # noqa — marks 'pyodide' in sys.modules

from rufus_edge.agent import RufusEdgeAgent
from rufus_edge.platform.pyodide import PyodidePlatformAdapter

adapter = PyodidePlatformAdapter()

agent = RufusEdgeAgent(
    device_id="${config.device_id}",
    cloud_url="${config.cloud_url}",
    api_key="${config.api_key || ''}",
    db_path=":memory:",          # wa-sqlite handles persistence via JS bridge
    platform_adapter=adapter,
    workflow_sync_enabled=False, # Browser: no background sync loop
)

# Store globally so JS can call agent methods later
import js
js.globalThis._rufus_agent = agent

await agent.start()
print("[rufus] RufusEdgeAgent started in browser")
`);
}

// ─────────────────────────────────────────────────────────────────────────────
// Main — orchestrate stages
// ─────────────────────────────────────────────────────────────────────────────

self.onmessage = async (event) => {
  if (event.data.type !== 'init') return;

  const config = event.data.config || {};
  const dbName = config.db_name || 'rufus_edge';

  try {
    self.postMessage({ type: 'progress', stage: 'loading_pyodide' });
    const pyodide = await loadPyodideRuntime();

    self.postMessage({ type: 'progress', stage: 'init_sqlite' });
    await initWaSqlite(dbName);

    self.postMessage({ type: 'progress', stage: 'starting_agent' });
    await startEdgeAgent(pyodide, config);

    self.postMessage({ type: 'ready' });
  } catch (err) {
    console.error('[rufus] browser_loader fatal error:', err);
    self.postMessage({ type: 'error', message: String(err) });
  }
};
