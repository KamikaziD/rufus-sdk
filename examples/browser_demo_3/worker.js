/**
 * worker.js — Browser Demo 3: Tab-to-Tab Pod Mesh Worker
 *
 * Each browser tab runs this Worker. Pods discover each other via
 * BroadcastChannel("rufus-mesh") — a native browser API that routes
 * messages across all same-origin tabs/windows with zero server involvement.
 *
 * RUVON concepts demonstrated:
 *   - Capability vector broadcast (RAM/load/tier → S(Vc) score)
 *   - Deterministic leader election (highest score = Sovereign)
 *   - SAF relay: offline pod routes transactions through the Sovereign
 *   - Tier classification: T1/T2/T3 from navigator.deviceMemory + navigator.gpu
 *
 * Message types on BroadcastChannel:
 *   ANNOUNCE    — pod registers and broadcasts initial capability vector
 *   HEARTBEAT   — periodic capability vector update (every 5 s)
 *   RELAY_REQUEST — offline pod asks Sovereign to execute a workflow payload
 *   RELAY_RESULT  — Sovereign posts execution result back to requesting pod
 *   ELECTION    — mesh leader election event (new Sovereign elected)
 *   GOODBYE     — pod is going offline / tab closing
 *
 * Messages to/from main thread (postMessage):
 *   From main: { type: "INIT" | "GO_OFFLINE" | "GO_ONLINE" | "RUN_PAYMENT" | "STOP" }
 *   To main:   { type: "READY" | "PEER_UPDATE" | "STEP_DONE" | "WORKFLOW_DONE"
 *                       | "WORKFLOW_ERROR" | "RELAY_SENT" | "RELAY_RECEIVED" | "ELECTION" }
 */

// ---------------------------------------------------------------------------
// Pod identity
// ---------------------------------------------------------------------------
const POD_ID = "pod-" + Math.random().toString(36).slice(2, 8).toUpperCase();
let isOnline = true;
let isSovereign = false;

// ---------------------------------------------------------------------------
// Capability vector + scoring
// ---------------------------------------------------------------------------

function detectTier() {
  const ram = navigator.deviceMemory || 2; // GB, may be undefined on some browsers
  const hasGpu = !!navigator.gpu;
  if (ram >= 8 || hasGpu) return 3;
  if (ram >= 1) return 2;
  return 1;
}

function buildCapabilityVector() {
  const tier = detectTier();
  // Simulate dynamic load (in production this would come from performance.memory etc.)
  const cpuLoad = 0.1 + Math.random() * 0.4;
  const ramMb = (navigator.deviceMemory || 2) * 1024 * (0.5 + Math.random() * 0.3);
  const queue = pendingSAF.length;
  return {
    pod_id: POD_ID,
    tier,
    cpu_load: parseFloat(cpuLoad.toFixed(3)),
    available_ram_mb: parseFloat(ramMb.toFixed(1)),
    task_queue_length: queue,
    timestamp: Date.now(),
  };
}

/** RUVON scoring formula: S(Vc) = 0.50·C + 0.15·(1/H) + 0.25·U + 0.10·P */
function score(vec) {
  const C = Math.max(0, 1 - vec.cpu_load);           // connectivity proxy
  const H = 1;                                        // hop distance (always 1 in browser mesh)
  const U = vec.available_ram_mb / 8192;             // uptime/capacity proxy
  const P = 1 - vec.task_queue_length / 10;          // capacity (lower queue = more capacity)
  return 0.50 * C + 0.15 * (1.0 / Math.max(H, 1)) + 0.25 * Math.min(U, 1) + 0.10 * Math.max(P, 0);
}

// ---------------------------------------------------------------------------
// Peer registry
// ---------------------------------------------------------------------------
const peers = {};        // pod_id → capability vector
const STALE_MS = 15000;  // drop peer after 15 s without heartbeat

function pruneStale() {
  const now = Date.now();
  for (const [id, vec] of Object.entries(peers)) {
    if (now - vec.timestamp > STALE_MS) delete peers[id];
  }
}

function allPods() {
  return Object.values(peers).concat([buildCapabilityVector()]);
}

function electLeader() {
  pruneStale();
  const all = allPods();
  all.sort((a, b) => score(b) - score(a));
  return all[0]?.pod_id ?? POD_ID;
}

// ---------------------------------------------------------------------------
// SAF queue (store-and-forward)
// ---------------------------------------------------------------------------
const pendingSAF = [];     // transactions pending while offline

let _txCounter = 0;
function buildTransaction() {
  _txCounter++;
  return {
    tx_id: `${POD_ID}-tx-${_txCounter.toString().padStart(4, "0")}`,
    amount_cents: Math.floor(Math.random() * 99900) + 100,
    merchant_id: `MER-${Math.floor(Math.random() * 9000) + 1000}`,
    timestamp: new Date().toISOString(),
    pod_id: POD_ID,
  };
}

// ---------------------------------------------------------------------------
// BroadcastChannel — peer mesh
// ---------------------------------------------------------------------------
const mesh = new BroadcastChannel("rufus-mesh");

mesh.onmessage = (evt) => {
  const msg = evt.data;
  if (!msg || !msg.type) return;

  switch (msg.type) {
    case "ANNOUNCE":
    case "HEARTBEAT": {
      if (msg.pod_id === POD_ID) break; // ignore own broadcast echo
      peers[msg.pod_id] = msg.vec;
      notifyPeerUpdate();
      maybeUpdateElection();
      break;
    }
    case "GOODBYE": {
      delete peers[msg.pod_id];
      notifyPeerUpdate();
      maybeUpdateElection();
      break;
    }
    case "RELAY_REQUEST": {
      // Only the Sovereign processes relay requests
      if (!isSovereign) break;
      handleRelayRequest(msg);
      break;
    }
    case "RELAY_RESULT": {
      if (msg.target_pod_id !== POD_ID) break;
      self.postMessage({
        type: "RELAY_RECEIVED",
        tx_id: msg.tx_id,
        result: msg.result,
        from_pod: msg.sovereign_pod_id,
      });
      break;
    }
    case "ELECTION": {
      const wasMe = isSovereign;
      isSovereign = msg.sovereign_pod_id === POD_ID;
      if (wasMe !== isSovereign) {
        self.postMessage({ type: "ELECTION", sovereign_pod_id: msg.sovereign_pod_id, is_me: isSovereign });
      }
      break;
    }
  }
};

function broadcast(msg) {
  mesh.postMessage(msg);
}

// ---------------------------------------------------------------------------
// Relay request handler (Sovereign side)
// ---------------------------------------------------------------------------
async function handleRelayRequest(msg) {
  const tx = msg.transaction;
  self.postMessage({ type: "RELAY_RECEIVED", tx_id: tx.tx_id, from_pod: msg.requesting_pod_id, sovereign: true });

  // Execute the transaction workflow synchronously (Python-free for the relay demo)
  const result = executePaymentWorkflow(tx);

  broadcast({
    type: "RELAY_RESULT",
    tx_id: tx.tx_id,
    target_pod_id: msg.requesting_pod_id,
    sovereign_pod_id: POD_ID,
    result,
  });
}

// ---------------------------------------------------------------------------
// Local payment workflow (pure JS — mirrors the Python Rufus step functions)
// ---------------------------------------------------------------------------
function executePaymentWorkflow(tx) {
  const FLOOR_LIMIT_CENTS = 5000; // $50.00 — approve offline without auth
  const steps = [];

  // Step 1: Validate transaction
  steps.push({ name: "ValidateTransaction", status: "DONE", result: { valid: true } });

  // Step 2: Floor limit check
  const approved_offline = tx.amount_cents <= FLOOR_LIMIT_CENTS;
  steps.push({ name: "FloorLimitCheck", status: "DONE", result: { approved_offline, floor_limit_cents: FLOOR_LIMIT_CENTS } });

  // Step 3: Fraud score (simple heuristic)
  const fraud_score = tx.amount_cents > 50000 ? 0.6 : 0.1 + Math.random() * 0.2;
  const fraud_flagged = fraud_score > 0.5;
  steps.push({ name: "FraudScore", status: "DONE", result: { fraud_score: parseFloat(fraud_score.toFixed(3)), fraud_flagged } });

  // Step 4: Authorise
  const authorised = approved_offline && !fraud_flagged;
  steps.push({ name: "Authorise", status: "DONE", result: { authorised } });

  return {
    tx_id: tx.tx_id,
    authorised,
    steps,
    executed_by: POD_ID,
    relay: true,
  };
}

// ---------------------------------------------------------------------------
// Election logic
// ---------------------------------------------------------------------------
function maybeUpdateElection() {
  const leader = electLeader();
  const becameSovereign = leader === POD_ID && !isSovereign;
  const lostSovereignty = leader !== POD_ID && isSovereign;
  if (becameSovereign || lostSovereignty) {
    isSovereign = (leader === POD_ID);
    broadcast({ type: "ELECTION", sovereign_pod_id: leader });
    self.postMessage({ type: "ELECTION", sovereign_pod_id: leader, is_me: isSovereign });
  }
}

// ---------------------------------------------------------------------------
// Notify main thread
// ---------------------------------------------------------------------------
function notifyPeerUpdate() {
  const peerList = Object.entries(peers).map(([id, vec]) => ({
    pod_id: id,
    tier: vec.tier,
    score: parseFloat(score(vec).toFixed(3)),
    cpu_load: vec.cpu_load,
    available_ram_mb: vec.available_ram_mb,
    task_queue_length: vec.task_queue_length,
    age_ms: Date.now() - vec.timestamp,
  }));
  self.postMessage({ type: "PEER_UPDATE", peers: peerList, own_pod_id: POD_ID, is_sovereign: isSovereign });
}

// ---------------------------------------------------------------------------
// Heartbeat broadcast loop
// ---------------------------------------------------------------------------
let _heartbeatInterval = null;

function startHeartbeat() {
  if (_heartbeatInterval) return;
  // Announce immediately
  broadcast({ type: "ANNOUNCE", pod_id: POD_ID, vec: buildCapabilityVector() });
  maybeUpdateElection();
  _heartbeatInterval = setInterval(() => {
    broadcast({ type: "HEARTBEAT", pod_id: POD_ID, vec: buildCapabilityVector() });
    pruneStale();
    maybeUpdateElection();
    notifyPeerUpdate();
  }, 5000);
}

// ---------------------------------------------------------------------------
// Message handler from main thread
// ---------------------------------------------------------------------------
self.onmessage = async (evt) => {
  const msg = evt.data;
  if (!msg || !msg.type) return;

  switch (msg.type) {
    case "INIT": {
      startHeartbeat();
      self.postMessage({ type: "READY", pod_id: POD_ID });
      break;
    }

    case "GO_OFFLINE": {
      isOnline = false;
      self.postMessage({ type: "STATUS", pod_id: POD_ID, online: false });
      break;
    }

    case "GO_ONLINE": {
      isOnline = true;
      // Flush pending SAF queue
      if (pendingSAF.length > 0) {
        const leader = electLeader();
        if (leader === POD_ID) {
          // We are Sovereign — process our own SAF
          for (const tx of pendingSAF.splice(0)) {
            const result = executePaymentWorkflow(tx);
            self.postMessage({ type: "WORKFLOW_DONE", tx_id: tx.tx_id, result, relayed: false });
          }
        } else {
          // Relay through Sovereign
          for (const tx of pendingSAF.splice(0)) {
            broadcast({ type: "RELAY_REQUEST", requesting_pod_id: POD_ID, transaction: tx });
            self.postMessage({ type: "RELAY_SENT", tx_id: tx.tx_id, to_pod: leader });
          }
        }
      }
      self.postMessage({ type: "STATUS", pod_id: POD_ID, online: true });
      break;
    }

    case "RUN_PAYMENT": {
      const tx = buildTransaction();
      if (!isOnline) {
        // Store-and-forward: queue for later relay
        pendingSAF.push(tx);
        self.postMessage({ type: "STEP_DONE", step: "SAF_QUEUED", tx_id: tx.tx_id, saf_queue_depth: pendingSAF.length });
      } else {
        const leader = electLeader();
        if (leader === POD_ID || Object.keys(peers).length === 0) {
          // We are Sovereign or alone — process locally
          self.postMessage({ type: "STEP_DONE", step: "ValidateTransaction", tx_id: tx.tx_id });
          self.postMessage({ type: "STEP_DONE", step: "FloorLimitCheck", tx_id: tx.tx_id });
          self.postMessage({ type: "STEP_DONE", step: "FraudScore", tx_id: tx.tx_id });
          self.postMessage({ type: "STEP_DONE", step: "Authorise", tx_id: tx.tx_id });
          const result = executePaymentWorkflow(tx);
          self.postMessage({ type: "WORKFLOW_DONE", tx_id: tx.tx_id, result, relayed: false });
        } else {
          // Relay through Sovereign
          broadcast({ type: "RELAY_REQUEST", requesting_pod_id: POD_ID, transaction: tx });
          self.postMessage({ type: "RELAY_SENT", tx_id: tx.tx_id, to_pod: leader });
        }
      }
      break;
    }

    case "STOP": {
      broadcast({ type: "GOODBYE", pod_id: POD_ID });
      clearInterval(_heartbeatInterval);
      _heartbeatInterval = null;
      mesh.close();
      break;
    }
  }
};

// Say goodbye when the tab closes
self.addEventListener("close", () => {
  broadcast({ type: "GOODBYE", pod_id: POD_ID });
});
