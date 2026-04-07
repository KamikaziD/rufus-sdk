/**
 * worker.js — Browser Demo 3: Tab-to-Tab Pod Mesh Worker
 *             v2 — Regenerative Top-Down Mesh
 *
 * Each browser tab runs this Worker. Pods discover each other via
 * BroadcastChannel("rufus-mesh") — zero server involvement for local tabs.
 * When a group_key is provided on INIT, the worker also connects to the
 * Rufus WebSocket signaling endpoint (/api/v1/signal/{group_key}) so that
 * pods on different devices can join the same private mesh.
 *
 * RUVON concepts demonstrated:
 *   - Capacity-proportional pull: high-S(Vc) pods heartbeat every ~300ms,
 *     low-S(Vc) pods back off to ~8–30 s
 *   - Adaptive backoff + jitter: ±25–50% random jitter per interval
 *   - Auto-unsubscribe / damping: propagated_count capped at 15 hops
 *   - Help-push from below: overloaded pods push HELP_REQUEST to top-k peers
 *   - Tier-aware fanout: T2/T3 re-broadcast; T1 only relays upward
 *   - Sovereign Pulse Mode: sovereign locks to base interval
 *
 * Transport:
 *   - Local (same device / same origin): BroadcastChannel("rufus-mesh")
 *   - Remote (cross-device): WebSocket to /api/v1/signal/{group_key}
 *   - Dedup cache prevents echo loops across both channels
 *
 * BroadcastChannel message types:
 *   ANNOUNCE      — pod registers, broadcasts initial capability vector
 *   HEARTBEAT     — periodic capability vector update
 *   GOODBYE       — pod going offline / tab closing
 *   RELAY_REQUEST — offline pod asks Sovereign to execute a workflow payload
 *   RELAY_RESULT  — Sovereign posts execution result back to requesting pod
 *   ELECTION      — mesh leader election event (new Sovereign elected)
 *   HELP_REQUEST  — overloaded pod asks top-k peers for help
 *   HELP_OFFER    — high-capacity peer responds to a HELP_REQUEST
 *
 * Messages to/from main thread (postMessage):
 *   From main: { type: "INIT" | "GO_OFFLINE" | "GO_ONLINE" | "RUN_PAYMENT" | "STOP"
 *                       group_key?, nickname?, server_base? }
 *   To main:   { type: "READY" | "PEER_UPDATE" | "STEP_DONE" | "WORKFLOW_DONE"
 *                       | "WORKFLOW_ERROR" | "RELAY_SENT" | "RELAY_RECEIVED"
 *                       | "ELECTION" | "WS_CONNECTED" | "WS_DISCONNECTED"
 *                       | "HELP_SENT" | "HELP_OFFER_SENT" | "HELP_OFFER_RECEIVED" }
 */

// ---------------------------------------------------------------------------
// Pod identity
// ---------------------------------------------------------------------------
const POD_ID = "pod-" + Math.random().toString(36).slice(2, 8).toUpperCase();
let isOnline = true;
let isSovereign = false;

// ---------------------------------------------------------------------------
// Group mesh config (set on INIT, null = local BroadcastChannel only)
// ---------------------------------------------------------------------------
let groupKey = null;

// Peer source: pod_id → "local" | "remote"
const peerSources = {};

// Message dedup: LRU of "pod_id:timestamp" to prevent echo loops across channels
const _dedupCache = [];
const DEDUP_MAX = 50;
function isDuplicate(podId, ts) {
  const k = podId + ":" + ts;
  if (_dedupCache.includes(k)) return true;
  _dedupCache.push(k);
  if (_dedupCache.length > DEDUP_MAX) _dedupCache.shift();
  return false;
}

// ---------------------------------------------------------------------------
// Capability vector + RUVON scoring
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
  // Simulate dynamic load (in production: performance.memory, etc.)
  const cpuLoad = 0.1 + Math.random() * 0.4;
  const ramMb = (navigator.deviceMemory || 2) * 1024 * (0.5 + Math.random() * 0.3);
  const queue = pendingSAF.length;
  return {
    pod_id: POD_ID,
    tier,
    cpu_load: parseFloat(cpuLoad.toFixed(3)),
    available_ram_mb: parseFloat(ramMb.toFixed(1)),
    task_queue_length: queue,
    running_tasks: _runningTasks,
    timestamp: Date.now(),
  };
}

/** RUVON scoring formula: S(Vc) = 0.50·C + 0.15·(1/H) + 0.25·U + 0.10·P */
function score(vec) {
  const C = Math.max(0, 1 - vec.cpu_load);            // connectivity proxy
  const H = 1;                                         // hop distance (always 1 in browser mesh)
  const U = vec.available_ram_mb / 8192;              // uptime/capacity proxy
  const P = 1 - vec.task_queue_length / 10;           // capacity (lower queue = more capacity)
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
    if (now - vec.timestamp > STALE_MS) {
      delete peers[id];
      delete peerSources[id];
    }
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
// Regenerative gossip constants + state
// ---------------------------------------------------------------------------
const BASE_INTERVAL_MS  = 2000;   // base pull interval for a perfectly-scored pod
const MAX_BACKOFF_MS    = 30000;  // cap for low-score pods
const JITTER_MIN        = 0.75;   // ×0.75 lower bound
const JITTER_MAX        = 1.50;   // ×1.50 upper bound
const PROPAGATION_LIMIT = 15;     // max hops before damping stops re-broadcast
const HELP_SCORE_DROP   = 0.15;   // score drop that triggers help-push
const HELP_QUEUE_GROW   = 3;      // SAF queue growth that triggers help-push

let _currentBackoffMs = BASE_INTERVAL_MS;
let _lastOwnScore = 0;
let _lastQueueLength = 0;
let _heartbeatInterval = null;

function ownScore() {
  const cpuLoad = 0.1 + Math.random() * 0.4;
  const ramMb = (navigator.deviceMemory || 2) * 1024 * (0.5 + Math.random() * 0.3);
  return score({ cpu_load: cpuLoad, available_ram_mb: ramMb, task_queue_length: pendingSAF.length });
}

/**
 * Compute next heartbeat delay based on current pod capacity.
 * Timing reference (no jitter, no backoff):
 *   S=0.95 → ~290ms | S=0.75 → ~465ms | S=0.50 → ~940ms | S=0.20 → ~4.1s | S=0.10 → ~10.2s
 */
function computePullIntervalMs() {
  if (isSovereign) return BASE_INTERVAL_MS; // sovereign always pulls at base rate
  const s = Math.max(ownScore(), 0.05);
  const raw = BASE_INTERVAL_MS / Math.pow(s, 1.2);
  const withBackoff = Math.min(raw * (_currentBackoffMs / BASE_INTERVAL_MS), MAX_BACKOFF_MS);
  const jitter = JITTER_MIN + Math.random() * (JITTER_MAX - JITTER_MIN);
  return Math.round(withBackoff * jitter);
}

function getTopKPeers(k = 3) {
  return Object.entries(peers)
    .map(([id, vec]) => ({ pod_id: id, vec, s: score(vec) }))
    .sort((a, b) => b.s - a.s)
    .slice(0, k);
}

/** Tier-aware fanout: T2/T3 re-broadcast received heartbeats; T1 only if Sovereign */
function shouldRebroadcast(msg) {
  if ((msg.propagated_count || 0) >= PROPAGATION_LIMIT) return false;
  return detectTier() >= 2 || isSovereign;
}

// ---------------------------------------------------------------------------
// Task distribution (Sovereign-side)
// ---------------------------------------------------------------------------
const _taskQueue   = [];           // pending tasks waiting for assignment
const _activeTasks = new Map();    // taskId → { task, timeout_handle, retries }
const ORPHAN_CHECK_MS = 2000;
const MAX_TASK_RETRIES = 2;
let _orphanTimer = null;

// Task distribution (Worker-side)
const _myTaskSlots = 2;            // max concurrent tasks this pod accepts
let _runningTasks = 0;

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
// Hybrid transport: BroadcastChannel (local) + PeerJS DataChannels (remote)
// Remote path: worker posts REMOTE_SEND → main thread → PeerJS DataChannel fans out
// Incoming remote messages: main thread posts REMOTE_MSG → worker
// ---------------------------------------------------------------------------
const mesh = new BroadcastChannel("rufus-mesh");

function broadcastLocal(msg) { mesh.postMessage(msg); }

function broadcastAll(msg) {
  broadcastLocal(msg);
  // Ask main thread to forward to any connected PeerJS DataChannels
  self.postMessage({ type: "REMOTE_SEND", msg });
}

// ---------------------------------------------------------------------------
// Unified incoming message handler (shared by both channels)
// ---------------------------------------------------------------------------
function processIncomingMsg(msg) {
  switch (msg.type) {
    case "ANNOUNCE":
    case "HEARTBEAT": {
      if (msg.pod_id === POD_ID) break;
      peers[msg.pod_id] = msg.vec;
      peerSources[msg.pod_id] = peerSources[msg.pod_id] || "local";
      _currentBackoffMs = BASE_INTERVAL_MS; // new peer → reset adaptive backoff
      // Tier-aware re-broadcast with propagation damping
      if (msg.type === "HEARTBEAT" && shouldRebroadcast(msg)) {
        broadcastAll({ ...msg, propagated_count: (msg.propagated_count || 0) + 1 });
      }
      notifyPeerUpdate();
      maybeUpdateElection();
      break;
    }
    case "GOODBYE": {
      const leavingId = msg.pod_id;
      delete peers[leavingId];
      delete peerSources[leavingId];
      // Sovereign: immediately re-enqueue any tasks assigned to the leaving pod
      if (isSovereign) _reEnqueueTasksFor(leavingId);
      notifyPeerUpdate();
      maybeUpdateElection();
      break;
    }
    case "RELAY_REQUEST": {
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
    case "HELP_REQUEST": handleHelpRequest(msg); break;
    case "HELP_OFFER": {
      if (msg.target_pod_id !== POD_ID) break;
      self.postMessage({ type: "HELP_OFFER_RECEIVED", from: msg.pod_id, score: msg.own_score });
      break;
    }

    // ── Task Distribution ─────────────────────────────────────────────────
    case "TASK_SUBMIT": {
      if (!isSovereign) break;          // only Sovereign schedules
      _enqueueTask(msg.task);
      break;
    }

    case "TASK_ASSIGN": {
      if (msg.task.assigned_pod_id !== POD_ID) break;
      _runningTasks++;
      notifyPeerUpdate();
      broadcastAll({ type: "TASK_ACK", task_id: msg.task.task_id, pod_id: POD_ID, timestamp: Date.now() });
      let resultMsg;
      try {
        const { result, duration_ms } = _executeTask(msg.task);
        resultMsg = { type: "TASK_RESULT", task_id: msg.task.task_id,
                      result, duration_ms, worker_pod_id: POD_ID,
                      submitter_pod_id: msg.task.submitter_pod_id,
                      pod_id: POD_ID, timestamp: Date.now() };
      } catch (err) {
        resultMsg = { type: "TASK_RESULT", task_id: msg.task.task_id,
                      error: err.message, worker_pod_id: POD_ID,
                      submitter_pod_id: msg.task.submitter_pod_id,
                      pod_id: POD_ID, timestamp: Date.now() };
      } finally {
        _runningTasks--;
        notifyPeerUpdate();
        self.postMessage({ type: "TASK_EXECUTED", task: msg.task });
      }
      broadcastAll(resultMsg);
      // BroadcastChannel doesn't echo — Sovereign needs cleanup, submitter needs notification
      setTimeout(() => processIncomingMsg(resultMsg), 0);
      break;
    }

    case "TASK_RESULT": {
      if (isSovereign) {
        const entry = _activeTasks.get(msg.task_id);
        if (entry) { clearTimeout(entry.timeout_handle); _activeTasks.delete(msg.task_id); }
        _assignNext();
      }
      if (msg.submitter_pod_id === POD_ID) {
        self.postMessage({ type: "TASK_COMPLETED", ...msg });
      }
      break;
    }

    case "TASK_ACK":
      // Receipt confirmed — timeout already running, nothing more to do
      break;

    case "TASK_ORPHAN":
      self.postMessage({ type: "TASK_ORPHANED", task_id: msg.task_id, reason: msg.reason });
      break;
  }
}

// BroadcastChannel routes through the same handler after dedup check
mesh.onmessage = (evt) => {
  const msg = evt.data;
  if (!msg?.type || msg.pod_id === POD_ID) return;
  if (isDuplicate(msg.pod_id, msg.timestamp || msg.vec?.timestamp || 0)) return;
  peerSources[msg.pod_id] = peerSources[msg.pod_id] || "local";
  processIncomingMsg(msg);
};

// ---------------------------------------------------------------------------
// Relay request handler (Sovereign side)
// ---------------------------------------------------------------------------
async function handleRelayRequest(msg) {
  const tx = msg.transaction;
  self.postMessage({ type: "RELAY_RECEIVED", tx_id: tx.tx_id, from_pod: msg.requesting_pod_id, sovereign: true });
  const result = executePaymentWorkflow(tx);
  broadcastAll({
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

  steps.push({ name: "ValidateTransaction", status: "DONE", result: { valid: true } });

  const approved_offline = tx.amount_cents <= FLOOR_LIMIT_CENTS;
  steps.push({ name: "FloorLimitCheck", status: "DONE", result: { approved_offline, floor_limit_cents: FLOOR_LIMIT_CENTS } });

  const fraud_score = tx.amount_cents > 50000 ? 0.6 : 0.1 + Math.random() * 0.2;
  const fraud_flagged = fraud_score > 0.5;
  steps.push({ name: "FraudScore", status: "DONE", result: { fraud_score: parseFloat(fraud_score.toFixed(3)), fraud_flagged } });

  const authorised = approved_offline && !fraud_flagged;
  steps.push({ name: "Authorise", status: "DONE", result: { authorised } });

  return { tx_id: tx.tx_id, authorised, steps, executed_by: POD_ID, relay: true };
}

// ---------------------------------------------------------------------------
// Task distribution — pure compute functions (no eval, no fetch)
// ---------------------------------------------------------------------------
function _fib(n) {
  if (n <= 1) return n;
  let a = 0, b = 1;
  for (let i = 2; i <= n; i++) { const t = a + b; a = b; b = t; }
  return b;
}

function _hashBatch(count) {
  let h = 5381;
  for (let i = 0; i < count; i++) {
    const s = "rufus-task-" + i;
    for (let j = 0; j < s.length; j++) { h = ((h << 5) + h) + s.charCodeAt(j); h |= 0; }
  }
  return h >>> 0;
}

function _sortLarge(size) {
  const arr = new Float32Array(size);
  for (let i = 0; i < size; i++) arr[i] = Math.random();
  arr.sort();
  return arr[0]; // return first element to prevent dead-code elimination
}

function _executeTask(task) {
  const t0 = performance.now();
  let result;
  switch (task.type) {
    case "FIBONACCI":  result = _fib(task.params.n);           break;
    case "HASH_BATCH": result = _hashBatch(task.params.count); break;
    case "SORT_LARGE": result = _sortLarge(task.params.size);  break;
    default: throw new Error("Unknown task type: " + task.type);
  }
  return { result, duration_ms: Math.round(performance.now() - t0) };
}

// ---------------------------------------------------------------------------
// Task distribution — Sovereign scheduling
// ---------------------------------------------------------------------------
function submitTask(type, params, priority) {
  priority = priority || "NORMAL";
  const task = {
    task_id: crypto.randomUUID(),
    type, params, priority,
    timeout_ms: 8000,
    submitter_pod_id: POD_ID,
    submitted_at: Date.now(),
    assigned_pod_id: null,
    assigned_at: null,
    retries: 0,
  };
  if (isSovereign) {
    _enqueueTask(task);
  } else {
    broadcastAll({ type: "TASK_SUBMIT", task, pod_id: POD_ID, timestamp: Date.now() });
  }
  self.postMessage({ type: "TASK_SUBMITTED", task });
}

function _enqueueTask(task) {
  const priority_order = { HIGH: 0, NORMAL: 1, LOW: 2 };
  _taskQueue.push(task);
  _taskQueue.sort((a, b) => (priority_order[a.priority] || 1) - (priority_order[b.priority] || 1));
  _assignNext();
}

function _selectWorker() {
  const self_vec = buildCapabilityVector();
  const candidates = Object.values(peers)
    .concat([self_vec])
    .filter(p => (p.running_tasks || 0) + (p.task_queue_length || 0) < _myTaskSlots * 2)
    .sort((a, b) => score(b) - score(a));
  return candidates[0]?.pod_id ?? POD_ID;
}

function _assignNext() {
  if (_taskQueue.length === 0) return;
  const workerId = _selectWorker();
  const task = _taskQueue.shift();
  task.assigned_pod_id = workerId;
  task.assigned_at = Date.now();

  const timeout_handle = setTimeout(() => {
    _activeTasks.delete(task.task_id);
    if ((task.retries || 0) < MAX_TASK_RETRIES) {
      task.retries = (task.retries || 0) + 1;
      task.assigned_pod_id = null;
      task.assigned_at = null;
      _enqueueTask(task);
    } else {
      broadcastAll({ type: "TASK_ORPHAN", task_id: task.task_id,
                     reason: "timeout after " + MAX_TASK_RETRIES + " retries", pod_id: POD_ID, timestamp: Date.now() });
    }
  }, task.timeout_ms);

  _activeTasks.set(task.task_id, { task, timeout_handle });
  const assignMsg = { type: "TASK_ASSIGN", task, pod_id: POD_ID, timestamp: Date.now() };
  broadcastAll(assignMsg);
  // BroadcastChannel doesn't echo to sender — self-assigned tasks need direct delivery
  if (task.assigned_pod_id === POD_ID) {
    setTimeout(() => processIncomingMsg(assignMsg), 0);
  }

  if (!_orphanTimer) {
    _orphanTimer = setInterval(_orphanCheck, ORPHAN_CHECK_MS);
  }
}

function _orphanCheck() {
  if (_activeTasks.size === 0) {
    clearInterval(_orphanTimer);
    _orphanTimer = null;
  }
}

function _reEnqueueTasksFor(podId) {
  for (const [taskId, entry] of _activeTasks.entries()) {
    if (entry.task.assigned_pod_id === podId) {
      clearTimeout(entry.timeout_handle);
      _activeTasks.delete(taskId);
      entry.task.assigned_pod_id = null;
      entry.task.assigned_at = null;
      _enqueueTask(entry.task);
    }
  }
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
    broadcastAll({ type: "ELECTION", sovereign_pod_id: leader });
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
    running_tasks: vec.running_tasks || 0,
    age_ms: Date.now() - vec.timestamp,
    source: peerSources[id] || "local",
  }));
  self.postMessage({
    type: "PEER_UPDATE",
    peers: peerList,
    own_pod_id: POD_ID,
    is_sovereign: isSovereign,
    group_key: groupKey,
    own_running_tasks: _runningTasks,
    own_queue_length: pendingSAF.length,
  });
}

// ---------------------------------------------------------------------------
// Help-push: overloaded pod asks top-k high-capacity peers for help
// ---------------------------------------------------------------------------
function sendHelpRequest() {
  const topK = getTopKPeers(3);
  if (topK.length === 0) return;
  broadcastAll({
    type: "HELP_REQUEST",
    pod_id: POD_ID,
    target_pod_ids: topK.map(p => p.pod_id),
    own_score: ownScore(),
    task_queue_length: pendingSAF.length,
    timestamp: Date.now(),
  });
  self.postMessage({ type: "HELP_SENT", targets: topK.map(p => p.pod_id) });
}

function handleHelpRequest(msg) {
  if (!msg.target_pod_ids.includes(POD_ID)) return; // not addressed to us
  broadcastAll({
    type: "HELP_OFFER",
    pod_id: POD_ID,
    target_pod_id: msg.pod_id,
    own_score: ownScore(),
    timestamp: Date.now(),
  });
  self.postMessage({ type: "HELP_OFFER_SENT", to: msg.pod_id });
}

// ---------------------------------------------------------------------------
// Adaptive gossip heartbeat (replaces fixed-interval setInterval)
// ---------------------------------------------------------------------------
function startAdaptiveGossip() {
  broadcastAll({ type: "ANNOUNCE", pod_id: POD_ID, vec: buildCapabilityVector() });
  maybeUpdateElection();
  scheduleNextHeartbeat();
}

function scheduleNextHeartbeat() {
  if (_heartbeatInterval !== null) return; // guard against double-scheduling
  const delay = computePullIntervalMs();
  _heartbeatInterval = setTimeout(() => {
    _heartbeatInterval = null;
    fireHeartbeat();
    scheduleNextHeartbeat(); // reschedule with updated score
  }, delay);
}

function fireHeartbeat() {
  const vec = buildCapabilityVector();
  const currentScore = score(vec);
  const currentQueue = vec.task_queue_length;

  broadcastAll({ type: "HEARTBEAT", pod_id: POD_ID, vec, propagated_count: 0 });
  pruneStale();
  maybeUpdateElection();
  notifyPeerUpdate();

  // Trigger help-push if score dropped or SAF queue spiked
  const scoreDrop = _lastOwnScore - currentScore;
  const queueGrowth = currentQueue - _lastQueueLength;
  if (_lastOwnScore > 0 && (scoreDrop > HELP_SCORE_DROP || queueGrowth >= HELP_QUEUE_GROW)) {
    sendHelpRequest();
  }
  _lastOwnScore = currentScore;
  _lastQueueLength = currentQueue;
}

// ---------------------------------------------------------------------------
// Message handler from main thread
// ---------------------------------------------------------------------------
self.onmessage = async (evt) => {
  const msg = evt.data;
  if (!msg || !msg.type) return;

  switch (msg.type) {
    case "INIT": {
      groupKey = msg.group_key || null;
      startAdaptiveGossip();
      self.postMessage({ type: "READY", pod_id: POD_ID, group_key: groupKey });
      break;
    }

    case "REMOTE_MSG": {
      // Message arrived from a remote pod via PeerJS DataChannel (forwarded by main thread)
      const m = msg.msg;
      if (!m?.type || !m.pod_id) break;
      if (m.pod_id === POD_ID) break;
      if (isDuplicate(m.pod_id, m.timestamp || m.vec?.timestamp || 0)) break;
      peerSources[m.pod_id] = "remote";
      processIncomingMsg(m);
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
            broadcastAll({ type: "RELAY_REQUEST", requesting_pod_id: POD_ID, transaction: tx });
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
          broadcastAll({ type: "RELAY_REQUEST", requesting_pod_id: POD_ID, transaction: tx });
          self.postMessage({ type: "RELAY_SENT", tx_id: tx.tx_id, to_pod: leader });
        }
      }
      break;
    }

    case "RUN_TASK": {
      submitTask(msg.task_type, msg.params, msg.priority || "NORMAL");
      break;
    }

    case "STOP": {
      broadcastAll({ type: "GOODBYE", pod_id: POD_ID });
      if (_heartbeatInterval) { clearTimeout(_heartbeatInterval); _heartbeatInterval = null; }
      if (_orphanTimer) { clearInterval(_orphanTimer); _orphanTimer = null; }
      for (const { timeout_handle } of _activeTasks.values()) clearTimeout(timeout_handle);
      _activeTasks.clear();
      mesh.close();
      break;
    }
  }
};

// Say goodbye when the tab closes
self.addEventListener("close", () => {
  broadcastAll({ type: "GOODBYE", pod_id: POD_ID });
});
