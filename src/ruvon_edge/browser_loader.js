/**
 * browser_loader.js — Rufus Edge Agent bootstrap for Web Workers (Pyodide + JSPI)
 *
 * Usage (from a ServiceWorker or main thread):
 *
 *   const worker = new Worker("/static/browser_loader.js", { type: "module" });
 *   worker.postMessage({
 *     type: "start",
 *     deviceId: "pos-browser-001",
 *     cloudUrl: "https://control.example.com",
 *     apiKey: "your-api-key",
 *   });
 *
 * Requirements
 * ------------
 *  • Chrome 117+ (or any browser with JSPI flag enabled)
 *  • Pyodide 0.25+  (loaded from CDN or local)
 *  • wa-sqlite      (loaded from CDN or local)
 *
 * Message API
 * -----------
 *  Incoming (main thread → worker):
 *    { type: "start",   deviceId, cloudUrl, apiKey, dbName? }
 *    { type: "stop" }
 *    { type: "execute", workflowType, inputData }
 *
 *  Outgoing (worker → main thread):
 *    { type: "ready" }
 *    { type: "result",  workflowType, result }
 *    { type: "error",   message }
 *    { type: "log",     level, text }
 */

/* global self, loadPyodide */

// ─────────────────────────────────────────────────────────────────────────────
// Configuration — override via postMessage({ type: "config", ... }) before start
// ─────────────────────────────────────────────────────────────────────────────
const PYODIDE_CDN =
  "https://cdn.jsdelivr.net/pyodide/v0.25.1/full/pyodide.js";
const WA_SQLITE_CDN =
  "https://cdn.jsdelivr.net/npm/wa-sqlite@0.9.11/dist/wa-sqlite-async.mjs";
const RUFUS_EDGE_WHEEL =
  "https://files.pythonhosted.org/packages/rufus_sdk_edge-latest-py3-none-any.whl";

// ─────────────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────────────
let pyodide = null;
let waSqlite = null;
let agentStarted = false;

// ─────────────────────────────────────────────────────────────────────────────
// Logging helper
// ─────────────────────────────────────────────────────────────────────────────
function log(level, text) {
  self.postMessage({ type: "log", level, text });
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 1 — Load wa-sqlite and expose as globalThis.WaSqlite
// ─────────────────────────────────────────────────────────────────────────────
async function initWaSqlite() {
  log("info", "Loading wa-sqlite…");
  const { default: initWaSqliteFactory } = await import(WA_SQLITE_CDN);
  const sqlite3 = await initWaSqliteFactory();

  // Minimal wrapper that matches the API expected by PyodideSQLiteProvider
  globalThis.WaSqlite = {
    /**
     * Open an OPFS-backed database.
     * Returns a handle { execute, commit } used by _WaSqliteConn.
     */
    async open(dbName) {
      const { IDBBatchAtomicVFS } = await import(
        "https://cdn.jsdelivr.net/npm/wa-sqlite@0.9.11/dist/IDBBatchAtomicVFS.mjs"
      );
      const vfs = await IDBBatchAtomicVFS.create(dbName, sqlite3);
      sqlite3.vfs_register(vfs, true);
      const db = await sqlite3.open_v2(dbName);

      return {
        async execute(sql, params = []) {
          const rows = [];
          let columns = [];
          await sqlite3.exec(db, sql, {
            bind: params,
            callback(row, stmt) {
              if (columns.length === 0) {
                columns = sqlite3.column_names(stmt);
              }
              rows.push([...row]);
            },
          });
          return [rows, columns];
        },
        async commit() {
          // wa-sqlite auto-commits for non-transaction statements;
          // explicit commit is a no-op here but can be extended.
        },
      };
    },
  };

  log("info", "wa-sqlite ready");
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 2 — Load Pyodide
// ─────────────────────────────────────────────────────────────────────────────
async function initPyodide() {
  log("info", "Loading Pyodide…");
  importScripts(PYODIDE_CDN);          // adds loadPyodide to global scope
  pyodide = await loadPyodide({
    stdout: (text) => log("stdout", text),
    stderr: (text) => log("stderr", text),
  });
  log("info", `Pyodide ${pyodide.version} loaded`);
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 3 — Install rufus-sdk-edge
// ─────────────────────────────────────────────────────────────────────────────
async function installRufus(wheelUrl) {
  log("info", "Installing rufus-sdk-edge (browser extra)…");
  await pyodide.loadPackage("micropip");
  const micropip = pyodide.pyimport("micropip");
  // Install the browser extra (no psutil, no websockets, no httpx dep)
  await micropip.install(wheelUrl + "[browser]");
  log("info", "rufus-sdk-edge installed");
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 4 — Start RufusEdgeAgent inside Pyodide
// ─────────────────────────────────────────────────────────────────────────────
async function startAgent({ deviceId, cloudUrl, apiKey, dbName = "rufus_edge" }) {
  log("info", `Starting RufusEdgeAgent for device ${deviceId}`);

  await pyodide.runPythonAsync(`
import asyncio
from rufus_edge.platform.pyodide import PyodidePlatformAdapter
from rufus_edge.implementations.persistence.pyodide_sqlite import PyodideSQLiteProvider
from rufus_edge.agent import RufusEdgeAgent

_adapter = PyodidePlatformAdapter(default_headers={
    "X-API-Key": ${JSON.stringify(apiKey)},
    "X-Device-ID": ${JSON.stringify(deviceId)},
})
_persistence = PyodideSQLiteProvider(db_name=${JSON.stringify(dbName)})
await _persistence.initialize()

_agent = RufusEdgeAgent(
    device_id=${JSON.stringify(deviceId)},
    cloud_url=${JSON.stringify(cloudUrl)},
    api_key=${JSON.stringify(apiKey)},
    db_path=":memory:",          # unused — persistence provided directly
    platform_adapter=_adapter,
)
# Inject the wa-sqlite persistence before start() creates its own
_agent.persistence = _persistence
await _agent.start()
`);

  agentStarted = true;
  log("info", "RufusEdgeAgent started");
  self.postMessage({ type: "ready" });
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 5 — Execute a workflow on demand
// ─────────────────────────────────────────────────────────────────────────────
async function executeWorkflow(workflowType, inputData) {
  if (!agentStarted) throw new Error("Agent not started");

  const inputJson = JSON.stringify(inputData ?? {});
  const resultJson = await pyodide.runPythonAsync(`
import json
_result = await _agent.execute_workflow(
    ${JSON.stringify(workflowType)},
    json.loads(${JSON.stringify(inputJson)})
)
json.dumps(_result, default=str)
`);

  return JSON.parse(resultJson);
}

// ─────────────────────────────────────────────────────────────────────────────
// Message handler
// ─────────────────────────────────────────────────────────────────────────────
self.onmessage = async (event) => {
  const { type, ...payload } = event.data;

  try {
    if (type === "start") {
      await initWaSqlite();
      await initPyodide();
      await installRufus(payload.wheelUrl ?? RUFUS_EDGE_WHEEL);
      await startAgent(payload);
    } else if (type === "execute") {
      const result = await executeWorkflow(payload.workflowType, payload.inputData);
      self.postMessage({ type: "result", workflowType: payload.workflowType, result });
    } else if (type === "stop") {
      if (agentStarted) {
        await pyodide.runPythonAsync("await _agent.stop()");
        agentStarted = false;
      }
    }
  } catch (err) {
    log("error", String(err));
    self.postMessage({ type: "error", message: String(err) });
  }
};
