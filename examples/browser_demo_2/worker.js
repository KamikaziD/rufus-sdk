/**
 * worker.js — Rufus Browser Demo 2 — PaymentSimulation Sovereign Dispatcher
 *
 * Each browser device runs a full PaymentSimulation + TransactionMonitoring
 * pipeline — identical workflow types to the Docker edge simulators.
 *
 * Online:  gateway approval → workflows sync to cloud in real-time
 * Offline: floor-limit check → SAF queue with real amounts/merchants/cards
 *          + workflow records cached locally, flushed on reconnect
 */

// ── Device states ──────────────────────────────────────────────────────────
const STATE = {
  IDLE:          0,
  ONLINE:        1,
  WASM_EXEC:     2,   // payment processing (includes monitoring)
  WORKFLOW_DONE: 3,
  OFFLINE:       4,
  SAF_QUEUED:    5,
  SYNCING:       6,
  SYNCED:        7,
  MESH_RELAY:    8,   // routing SAF through a peer (transient)
};

// ── Constants ──────────────────────────────────────────────────────────────
const PAYMENT_INTERVAL = 15000;   // ms between payment cycles per device

// Known merchant sets — transactions to unknown merchants raise merchant_novelty
const KNOWN_POS_MERCHANTS = new Set(["WALMART-001", "TARGET-002", "STARBUCKS-003"]);
const KNOWN_ATM_LOCATIONS = new Set(["ATM-CHASE-001", "ATM-WELLS-002"]);

// Typology catalogue — mirrors txn_monitoring_steps.py _TYPOLOGIES
const TYPOLOGIES = {
  card_testing:               new Set(["pos_r001_velocity", "pos_r003_card_testing"]),
  micro_structuring_pos:      new Set(["pos_r002_micro_struct", "pos_r001_velocity"]),
  velocity_fraud:             new Set(["pos_r001_velocity", "pos_r005_amount_spike"]),
  unknown_merchant:           new Set(["pos_r004_unknown_merchant"]),
  unknown_merchant_large_txn: new Set(["pos_r004_unknown_merchant", "pos_r005_amount_spike"]),
  unknown_merchant_velocity:  new Set(["pos_r004_unknown_merchant", "pos_r001_velocity"]),
  cash_structuring_atm:       new Set(["atm_r003_structuring", "atm_r004_velocity"]),
  nighttime_account_raid:     new Set(["atm_r002_after_hours", "atm_r001_large_cash"]),
  atm_velocity_fraud:         new Set(["atm_r004_velocity", "atm_r005_large_daily"]),
  nighttime_structuring:      new Set(["atm_r002_after_hours", "atm_r003_structuring"]),
  unknown_atm_location:       new Set(["atm_r006_unknown_location"]),
  unknown_atm_large_cash:     new Set(["atm_r006_unknown_location", "atm_r001_large_cash"]),
  unknown_atm_velocity:       new Set(["atm_r006_unknown_location", "atm_r004_velocity"]),
};

// ── Runtime globals ────────────────────────────────────────────────────────
let running         = false;
let networkUp       = true;
let cloudReachable  = false;
let cloudUrl        = "http://localhost:8000";
let registrationKey = "dev-registration-key";
let batchSize       = 50;
let condition       = "good";
let numDevices      = 0;
let devices         = [];
let legacyMode      = false;

// Stats
let latencyTimings  = [];
let totalSynced     = 0;
let txnCount        = 0;
let txnWindowStart  = Date.now();
let approvedOnline  = 0;
let approvedOffline = 0;
let declined        = 0;
let highRiskCount   = 0;
let meshRelayed     = 0;

// Wire format tracking (JSON vs Proto sizes)
let lastHeartbeatJsonBytes  = 0;
let lastHeartbeatProtoBytes = 0;
let lastSafBatchJsonBytes   = 0;
let lastSafBatchProtoBytes  = 0;
let lastSafBatchCount       = 0;

// ── Message handler ────────────────────────────────────────────────────────
self.onmessage = async (e) => {
  const { type, ...payload } = e.data;

  switch (type) {
    case "INIT":
      cloudUrl        = payload.cloudUrl        || cloudUrl;
      registrationKey = payload.registrationKey || registrationKey;
      batchSize       = payload.batchSize       || batchSize;
      numDevices      = payload.numDevices      || 50;
      legacyMode      = payload.legacyMode      || false;
      cloudReachable  = payload.cloudReachable  || false;
      initDevices(numDevices);
      break;

    case "CLOUD_STATUS":
      cloudReachable = payload.reachable;
      if (cloudReachable) {
        log("☁  Control plane reachable — enabling cloud sync");
        for (const dev of devices) {
          if (!dev.registered) registerDevice(dev).catch(() => {});
        }
      } else {
        log("☁  Control plane unreachable — running in simulation mode");
      }
      break;

    case "START":
      if (!running) {
        running = true;
        if (legacyMode) {
          runLegacyMode();
        } else {
          startAllDevices();
        }
        startStatsLoop();
      }
      break;

    case "STOP":
      running = false;
      devices = [];
      break;

    case "CUT_NETWORK":
      networkUp = false;
      log("⚡ Network cut — devices will queue SAF after next cycle");
      break;

    case "RESTORE_NETWORK":
      networkUp = true;
      log("🔄 Network restored — SAF drain will fire on next heartbeat");
      for (const dev of devices) {
        if (dev.safQueue.length > 0 && networkUp) {
          drainSAF(dev).catch(() => {});
        }
      }
      break;

    case "SET_CONDITION":
      condition = payload.condition || "good";
      log(`[net] condition → ${condition}`);
      break;
  }
};

// ── Device initialisation ──────────────────────────────────────────────────
function initDevices(n) {
  devices = [];
  for (let i = 0; i < n; i++) {
    const deviceType = (i % 3 === 0) ? "atm" : "pos";
    devices.push({
      index: i,
      id: `browser-device-${crypto.randomUUID().slice(0, 8)}`,
      apiKey: null,
      state: STATE.IDLE,
      deviceType,
      floorLimit: deviceType === "atm" ? 200 : 500,
      cardToken: crypto.randomUUID(),
      velocityLog: [],       // [{ ts: ms }] — sliding window velocity
      pendingWorkflows: [],  // workflow records to sync when online
      safQueue: [],          // [{ txn, workflows }] — offline-approved payments
      lastWorkflowId: null,
      missedHeartbeats: 0,
      seqNum: 0,
      registered: false,
      relayLoad: 0,          // concurrent relay bursts currently carrying
      relayLoadTotal: 0,     // lifetime relay count for leaderboard
    });
  }
}

// ── Sovereign mode ─────────────────────────────────────────────────────────
async function startAllDevices() {
  if (cloudReachable) {
    const regBatch = 10;
    for (let i = 0; i < devices.length; i += regBatch) {
      const slice = devices.slice(i, i + regBatch);
      await Promise.allSettled(slice.map(d => registerDevice(d)));
      if (i + regBatch < devices.length) await sleep(200);
    }
  }
  for (let i = 0; i < devices.length; i++) {
    setTimeout(() => deviceLoop(devices[i]), i * 200);
  }
}

async function registerDevice(dev) {
  if (!networkUp) return;
  try {
    const resp = await fetchWithCondition(`${cloudUrl}/api/v1/devices/register`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Registration-Key": registrationKey,
      },
      body: JSON.stringify({
        device_id: dev.id,
        device_type: dev.deviceType,
        device_name: `Browser ${dev.deviceType.toUpperCase()} ${dev.index + 1}`,
        merchant_id: "browser-demo-merchant",
        firmware_version: "1.0.0",
        sdk_version: "1.0.0rc5",
        capabilities: ["workflow_execution"],
      }),
    });
    if (resp.ok) {
      const data = await resp.json();
      dev.apiKey = data.api_key || "browser-demo-key";
      dev.registered = true;
      postMessage({ type: "REGISTERED", deviceIndex: dev.index, deviceId: dev.id });
    }
  } catch {
    // Server not reachable — simulation mode
  }
}

// ── Per-device loop ────────────────────────────────────────────────────────
async function deviceLoop(dev) {
  while (running) {
    const startTs = Date.now();
    await runPaymentSimulation(dev);
    recordTiming(Date.now() - startTs);

    if (networkUp && cloudReachable) {
      const ok = await heartbeat(dev);
      if (ok) {
        dev.missedHeartbeats = 0;
        setState(dev, STATE.ONLINE);
        if (dev.pendingWorkflows.length > 0) {
          await syncWorkflows(dev, dev.pendingWorkflows.splice(0));
        }
        if (dev.safQueue.length > 0) {
          await drainSAF(dev);
        }
      } else {
        dev.missedHeartbeats++;
        if (dev.missedHeartbeats >= 2) {
          setState(dev, STATE.OFFLINE);
          log(`${devLabel(dev)} went OFFLINE (${dev.missedHeartbeats} missed heartbeats)`);
        }
      }
    }

    // Mesh relay: when globally offline with queued SAF, try to route via a peer
    if (!networkUp && dev.safQueue.length > 0) {
      await tryMeshRelay(dev);
    }

    const jitter = (dev.index % 10) * 200;
    await sleep(PAYMENT_INTERVAL + jitter);
  }
}

// ── Payment simulation ─────────────────────────────────────────────────────
async function runPaymentSimulation(dev) {
  setState(dev, STATE.WASM_EXEC);
  await sleep(2 + Math.random() * 8);   // simulated processing time

  const workflowId = crypto.randomUUID();
  const payment    = generatePayment(dev);
  const isOnline   = networkUp && cloudReachable;
  let paymentStatus, authCode = null;

  if (isOnline) {
    authCode = "AUTH-" + Math.random().toString(36).slice(2, 10).toUpperCase();
    paymentStatus = "APPROVED_ONLINE";
    await sleep(5 + Math.random() * 30);   // gateway round-trip simulation
    approvedOnline++;
  } else if (payment.amount <= dev.floorLimit) {
    paymentStatus = "APPROVED_OFFLINE";
    approvedOffline++;
  } else {
    paymentStatus = "DECLINED";
    declined++;
  }

  // Update velocity log (add current payment)
  const now = Date.now();
  dev.velocityLog.push({ ts: now });
  const velocityWindowMs = dev.deviceType === "atm" ? 1800000 : 3600000;
  dev.velocityLog = dev.velocityLog.filter(e => now - e.ts < velocityWindowMs);

  // TransactionMonitoring — always runs synchronously (no network needed)
  const monitoringWfId = crypto.randomUUID();
  const monitoring = runTransactionMonitoring(payment, dev, monitoringWfId);
  if (monitoring.risk_level === "HIGH" || monitoring.risk_level === "CRITICAL") {
    highRiskCount++;
  }

  txnCount++;

  // Build workflow records
  const paymentWfRecord    = buildPaymentSimRecord(workflowId, dev, payment, paymentStatus, authCode, monitoring, monitoringWfId);
  const monitoringWfRecord = buildMonitoringRecord(monitoringWfId, dev, payment, monitoring);
  dev.lastWorkflowId = workflowId;

  const label   = devLabel(dev);
  const typeTag = `[${dev.deviceType.toUpperCase()}]`;
  const riskTag = monitoring.risk_level !== "LOW" ? `  risk: ${monitoring.risk_level}` : "";

  if (paymentStatus === "APPROVED_OFFLINE") {
    const safTxn = await makeSafTransactionFromPayment(dev, payment, workflowId);
    dev.safQueue.push({ txn: safTxn, workflows: [paymentWfRecord, monitoringWfRecord] });
    setState(dev, STATE.SAF_QUEUED);
    postMessage({ type: "SAF_CHANGE", deviceIndex: dev.index, queueDepth: dev.safQueue.length });
    log(`${label} ${typeTag} OFFLINE  ${payment.merchant_id}  $${payment.amount.toFixed(2)}  SAF queue: ${dev.safQueue.length}`);
  } else {
    dev.pendingWorkflows.push(paymentWfRecord, monitoringWfRecord);
    setState(dev, STATE.WORKFLOW_DONE);
    if (paymentStatus === "APPROVED_ONLINE") {
      log(`${label} ${typeTag} ONLINE   ${payment.merchant_id}  $${payment.amount.toFixed(2)}  APPROVED_ONLINE${riskTag}`);
    } else {
      log(`${label} ${typeTag} DECLINED ${payment.merchant_id}  $${payment.amount.toFixed(2)}  (exceeds floor $${dev.floorLimit})`);
    }
  }
}

// ── Payment generation ─────────────────────────────────────────────────────
function generatePayment(dev) {
  const posMerchants = ["WALMART-001", "TARGET-002", "STARBUCKS-003", "MCDONALDS-004", "BESTBUY-006"];
  const atmMerchants = ["ATM-CHASE-001", "ATM-WELLS-002", "ATM-BOA-003", "ATM-CITI-004"];

  let amount, merchant_id;
  if (dev.deviceType === "atm") {
    amount = Math.round((20 + Math.random() * 580) * 100) / 100;   // $20–$600
    merchant_id = atmMerchants[Math.floor(Math.random() * atmMerchants.length)];
  } else {
    amount = Math.round((5 + Math.random() * 495) * 100) / 100;    // $5–$500
    merchant_id = posMerchants[Math.floor(Math.random() * posMerchants.length)];
  }

  return {
    transaction_id:  crypto.randomUUID(),
    idempotency_key: crypto.randomUUID(),
    amount,
    amount_cents:    Math.round(amount * 100),
    currency:        "USD",
    card_last_four:  String(Math.floor(1000 + Math.random() * 9000)),
    card_token:      dev.cardToken,
    merchant_id,
  };
}

// ── Transaction monitoring (JS port of txn_monitoring_steps.py) ───────────
function runTransactionMonitoring(payment, dev, monitoringWfId) {
  // 1. Extract features
  const features = extractFeatures(payment, dev);

  // 2. Evaluate rules (POS or ATM)
  const { fired, passed } = dev.deviceType === "atm"
    ? evaluateAtmRules(features, payment, dev)
    : evaluatePosRules(features, payment, dev);

  features.rules_signal = parseFloat((fired.length / (dev.deviceType === "atm" ? 6 : 5)).toFixed(4));

  // 3. ML scoring (same weights as Python fallback, adjusted for demo)
  const ml_risk_score = jsFraudScore(features);
  const ml_confidence = parseFloat(Math.abs(ml_risk_score - 0.5) * 2).toFixed(4);

  // 4. Anomaly features
  const anomaly_features = [];
  if (features.normalized_amount > 0.8)   anomaly_features.push("near_floor_limit");
  if (features.velocity_normalized > 0.4) anomaly_features.push("high_velocity");
  if (features.merchant_novelty > 0.5)    anomaly_features.push("unknown_merchant");
  if (features.rules_signal > 0.4)        anomaly_features.push("multiple_rules_fired");
  if (features.time_risk > 0.5)           anomaly_features.push("after_hours");

  // 5. Typologies
  const firedSet = new Set(fired);
  const typologies_triggered = Object.entries(TYPOLOGIES)
    .filter(([, required]) => [...required].every(r => firedSet.has(r)))
    .map(([name]) => name);

  // 6. Verdict
  let risk_level, action;
  if (ml_risk_score >= 0.80)      { risk_level = "CRITICAL"; action = "BLOCK"; }
  else if (ml_risk_score >= 0.60) { risk_level = "HIGH";     action = "REVIEW"; }
  else if (ml_risk_score >= 0.30) { risk_level = "MEDIUM";   action = "ALLOW"; }
  else                             { risk_level = "LOW";      action = "ALLOW"; }

  const alert_id = (risk_level === "HIGH" || risk_level === "CRITICAL")
    ? Math.random().toString(36).slice(2, 14) : "";

  return {
    monitoring_workflow_id: monitoringWfId,
    device_type: dev.deviceType,
    transaction_id: payment.transaction_id,
    amount: payment.amount,
    merchant_id: payment.merchant_id,
    features,
    rules_fired: fired,
    rules_passed: passed,
    ml_risk_score: parseFloat(ml_risk_score.toFixed(4)),
    ml_confidence: parseFloat(ml_confidence),
    anomaly_features,
    typologies_triggered,
    risk_level,
    action,
    alert_id,
  };
}

function extractFeatures(payment, dev) {
  const velocityCount = dev.velocityLog.length;   // already pruned in runPaymentSimulation
  const velocityNorm  = Math.min(velocityCount / 5.0, 1.0);
  const hour = new Date().getUTCHours();
  const timeRisk = (hour >= 23 || hour <= 5) ? 1.0 : 0.0;
  const normalizedAmount = Math.min(payment.amount / dev.floorLimit, 1.0);
  const knownSet = dev.deviceType === "atm" ? KNOWN_ATM_LOCATIONS : KNOWN_POS_MERCHANTS;
  const merchantNovelty = knownSet.has(payment.merchant_id) ? 0.0 : 1.0;

  return {
    normalized_amount:    parseFloat(normalizedAmount.toFixed(4)),
    velocity_normalized:  parseFloat(velocityNorm.toFixed(4)),
    velocity_count:       velocityCount,
    time_risk:            timeRisk,
    merchant_novelty:     merchantNovelty,
    rules_signal:         0.0,   // updated after rule evaluation
  };
}

function evaluatePosRules(features, payment) {
  const fired = [], passed = [];
  const a = payment.amount;
  const v = features.velocity_count;

  // pos_r001: velocity ≥ 3 in 60 min
  (v >= 3 ? fired : passed).push("pos_r001_velocity");
  // pos_r002: micro-structuring $900–$999 (just below $1000 floor)
  (a >= 900 && a <= 999 ? fired : passed).push("pos_r002_micro_struct");
  // pos_r003: card testing — amount < $5
  (a < 5.0 ? fired : passed).push("pos_r003_card_testing");
  // pos_r004: unknown merchant
  (!KNOWN_POS_MERCHANTS.has(payment.merchant_id) ? fired : passed).push("pos_r004_unknown_merchant");
  // pos_r005: amount spike > $200
  (a > 200.0 ? fired : passed).push("pos_r005_amount_spike");

  return { fired, passed };
}

function evaluateAtmRules(features, payment) {
  const fired = [], passed = [];
  const a = payment.amount;
  const v = features.velocity_count;
  const hour = new Date().getUTCHours();

  // atm_r001: large cash > $400
  (a > 400 ? fired : passed).push("atm_r001_large_cash");
  // atm_r002: after-hours 23:00–06:00 UTC
  (hour >= 23 || hour <= 5 ? fired : passed).push("atm_r002_after_hours");
  // atm_r003: structuring $450–$499 (just below $500 floor)
  (a >= 450 && a <= 499 ? fired : passed).push("atm_r003_structuring");
  // atm_r004: velocity ≥ 2 in 30 min
  (v >= 2 ? fired : passed).push("atm_r004_velocity");
  // atm_r005: large daily > $700
  (a > 700 ? fired : passed).push("atm_r005_large_daily");
  // atm_r006: unknown ATM location
  (!KNOWN_ATM_LOCATIONS.has(payment.merchant_id) ? fired : passed).push("atm_r006_unknown_location");

  return { fired, passed };
}

function jsFraudScore(features) {
  // Weights tuned for browser demo (velocity contribution reduced — single card
  // per device inherently drives high velocity in steady state).
  // merchant_novelty and rules_signal remain strong signals.
  const logit = 0.8 * features.normalized_amount
              + 0.5 * features.velocity_normalized
              + 1.5 * features.time_risk
              + 1.8 * features.merchant_novelty
              + 3.0 * features.rules_signal
              - 2.5;
  return 1.0 / (1.0 + Math.exp(-logit));
}

// ── Heartbeat ──────────────────────────────────────────────────────────────
async function heartbeat(dev) {
  if (!dev.registered && !dev.apiKey) return false;
  const key = dev.apiKey || "browser-demo-key";
  try {
    const bodyObj = {
      device_status: "online",
      pending_saf_count: dev.safQueue.length,
      sdk_version: "1.0.0rc5",
    };
    const bodyStr = JSON.stringify(bodyObj);
    // Track wire sizes for benchmark panel
    lastHeartbeatJsonBytes  = new TextEncoder().encode(bodyStr).length;
    lastHeartbeatProtoBytes = estimateHeartbeatProto(dev);

    const resp = await fetchWithCondition(`${cloudUrl}/api/v1/devices/${dev.id}/heartbeat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": key },
      body: bodyStr,
    });
    return resp.ok;
  } catch {
    return false;
  }
}

// ── SAF drain — supersonic batch upload ───────────────────────────────────
async function drainSAF(dev) {
  if (dev.safQueue.length === 0) return;
  setState(dev, STATE.SYNCING);

  // Partition by relay_source: own txns vs foreign (relayed) txns
  const allItems = dev.safQueue.splice(0);
  const ownItems = allItems.filter(it => !it.txn.relay_source);
  const foreignGroups = {};
  for (const it of allItems.filter(it => it.txn.relay_source)) {
    const src = it.txn.relay_source;
    (foreignGroups[src] = foreignGroups[src] || []).push(it);
  }

  const key   = dev.apiKey || "browser-demo-key";
  const label = devLabel(dev);
  const typeTag = `[${dev.deviceType.toUpperCase()}]`;
  const totalCount = allItems.length;

  log(`${label} ${typeTag} SYNCING  uploading ${totalCount} txns (${ownItems.length} own, ${totalCount - ownItems.length} relayed)…`);

  // POST own transactions
  if (ownItems.length > 0) {
    const wfRecords = ownItems.flatMap(p => p.workflows || []);
    const ok = await postSafBatch(dev, ownItems.map(it => it.txn), null, key);
    if (ok && wfRecords.length > 0) await syncWorkflows(dev, wfRecords);
  }

  // POST each foreign group to the originating device's endpoint with mesh_relay metadata
  for (const [sourceId, items] of Object.entries(foreignGroups)) {
    const sourceDev = devices.find(d => d.id === sourceId);
    if (!sourceDev) continue;
    const firstItem = items[0];
    const relayMeta = {
      relay_device_id: dev.id,
      hop_count: firstItem.txn.relay_hops || 1,
      relayed_at: new Date(firstItem.txn.relayed_at || Date.now()).toISOString(),
    };
    const wfRecords = items.flatMap(p => p.workflows || []);
    const ok = await postSafBatch(sourceDev, items.map(it => it.txn), relayMeta, sourceDev.apiKey || "browser-demo-key");
    if (ok && wfRecords.length > 0) await syncWorkflows(sourceDev, wfRecords);
  }

  postMessage({ type: "SAF_CHANGE", deviceIndex: dev.index, queueDepth: 0 });

  // Summarise risk from all workflow records
  const allWfRecords = allItems.flatMap(p => p.workflows || []);
  const risks = allWfRecords
    .filter(w => w.workflow_type === "TransactionMonitoring")
    .map(w => { try { return JSON.parse(w.state).risk_level || "LOW"; } catch { return "LOW"; } });
  const riskSummary = [...new Set(risks)].join("/") || "LOW";

  setState(dev, STATE.SYNCED);
  log(`${label} ${typeTag} SYNCED   ✓ ${totalCount} txns  risk: ${riskSummary}`);
  await sleep(800);
  setState(dev, STATE.ONLINE);
}

async function postSafBatch(targetDev, txns, relayMeta, key) {
  if (txns.length === 0) return true;
  // Strip relay metadata fields from txn objects before posting
  const cleaned = txns.map(({ relay_source, relay_hops, relayed_at, ...rest }) => rest);
  const body = {
    transactions: cleaned,
    device_sequence: targetDev.seqNum++,
    device_timestamp: new Date().toISOString(),
  };
  if (relayMeta) body.mesh_relay = relayMeta;

  // Track wire sizes for benchmark panel (own txns only, not relay)
  if (!relayMeta) {
    const bodyStr = JSON.stringify(body);
    lastSafBatchJsonBytes  = new TextEncoder().encode(bodyStr).length;
    lastSafBatchProtoBytes = estimateSafBatchProto(cleaned);
    lastSafBatchCount      = cleaned.length;
  }

  try {
    const resp = await fetchWithCondition(
      `${cloudUrl}/api/v1/devices/${targetDev.id}/sync`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(key ? { "X-API-Key": key } : {}),
        },
        body: JSON.stringify(body),
      }
    );
    if (resp.ok) {
      totalSynced += txns.length;
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

// ── SAF transaction from real payment data ─────────────────────────────────
async function makeSafTransactionFromPayment(dev, payment, workflowId) {
  const encrypted_blob    = btoa(JSON.stringify({ device: dev.id, ts: Date.now() }));
  const encryption_key_id = "browser-demo";
  const hmac = await computeHmac(
    dev.apiKey || "",
    `${payment.transaction_id}|${encrypted_blob}|${encryption_key_id}`
  );
  return {
    transaction_id:   payment.transaction_id,
    encrypted_blob,
    encryption_key_id,
    hmac,
    merchant_id:      payment.merchant_id,
    amount_cents:     payment.amount_cents,
    currency:         payment.currency,
    card_last_four:   payment.card_last_four,
    workflow_id:      workflowId,
  };
}

// HMAC-SHA256 — returns lowercase hex string
async function computeHmac(key, data) {
  const enc = new TextEncoder();
  const cryptoKey = await crypto.subtle.importKey(
    "raw", enc.encode(key || "browser-demo"),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", cryptoKey, enc.encode(data));
  return Array.from(new Uint8Array(sig)).map(b => b.toString(16).padStart(2, "0")).join("");
}

// ── Workflow sync ──────────────────────────────────────────────────────────
async function syncWorkflows(dev, wfRecords) {
  if (!wfRecords.length || !dev.apiKey) return;
  try {
    await fetchWithCondition(`${cloudUrl}/api/v1/devices/${dev.id}/sync/workflows`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": dev.apiKey },
      body: JSON.stringify({ workflows: wfRecords, audit_logs: [] }),
    });
  } catch {
    // Non-fatal — SAF transaction already accepted
  }
}

// ── Workflow record builders ───────────────────────────────────────────────
const PAYMENT_SIM_STEPS_CONFIG = JSON.stringify([
  { name: "Generate_Payment",   type: "STANDARD" },
  { name: "Check_Connectivity", type: "STANDARD" },
  { name: "Authorize_Online",   type: "STANDARD" },
  { name: "Check_Floor_Limit",  type: "STANDARD" },
  { name: "Approve_Offline",    type: "STANDARD" },
  { name: "Decline_Payment",    type: "STANDARD" },
  { name: "Launch_Monitoring",  type: "STANDARD" },
  { name: "Complete_Payment",   type: "STANDARD" },
]);

const MONITORING_STEPS_CONFIG = JSON.stringify([
  { name: "Extract_Features",   type: "STANDARD" },
  { name: "Route_By_Type",      type: "STANDARD" },
  { name: "POS_Rules",          type: "STANDARD" },
  { name: "ATM_Rules",          type: "STANDARD" },
  { name: "Score_With_Wasm",    type: "STANDARD" },
  { name: "Apply_Typologies",   type: "STANDARD" },
  { name: "Monitoring_Verdict", type: "STANDARD" },
  { name: "Flag_Transaction",   type: "STANDARD" },
]);

function buildPaymentSimRecord(workflowId, dev, payment, paymentStatus, authCode, monitoring, monitoringWfId) {
  const now = new Date().toISOString().replace("Z", "");

  // Completed steps depend on the execution path taken
  let completedSteps;
  if (paymentStatus === "APPROVED_ONLINE") {
    completedSteps = ["Generate_Payment", "Check_Connectivity", "Authorize_Online", "Launch_Monitoring", "Complete_Payment"];
  } else if (paymentStatus === "APPROVED_OFFLINE") {
    completedSteps = ["Generate_Payment", "Check_Connectivity", "Check_Floor_Limit", "Approve_Offline", "Launch_Monitoring", "Complete_Payment"];
  } else {
    completedSteps = ["Generate_Payment", "Check_Connectivity", "Check_Floor_Limit", "Decline_Payment", "Launch_Monitoring", "Complete_Payment"];
  }

  return {
    id:                    workflowId,
    workflow_type:         "PaymentSimulation",
    workflow_version:      "1.1.0",
    definition_snapshot:   JSON.stringify({
      workflow_type: "PaymentSimulation",
      workflow_version: "1.1.0",
      steps: JSON.parse(PAYMENT_SIM_STEPS_CONFIG),
    }),
    current_step:          "Complete_Payment",
    status:                "COMPLETED",
    state:                 JSON.stringify({
      device_id:              dev.id,
      device_type:            dev.deviceType,
      transaction_id:         payment.transaction_id,
      amount:                 payment.amount,
      amount_cents:           payment.amount_cents,
      currency:               payment.currency,
      card_last_four:         payment.card_last_four,
      merchant_id:            payment.merchant_id,
      is_online:              paymentStatus === "APPROVED_ONLINE",
      status:                 paymentStatus,
      authorization_code:     authCode || "",
      risk_level:             monitoring.risk_level,
      action:                 monitoring.action,
      typologies_triggered:   monitoring.typologies_triggered,
      monitoring_workflow_id: monitoringWfId,
    }),
    steps_config:          PAYMENT_SIM_STEPS_CONFIG,
    state_model_path:      "payment_sim_steps.PaymentSimState",
    saga_mode:             0,
    completed_steps_stack: JSON.stringify(completedSteps),
    data_region:           "edge",
    priority:              5,
    metadata:              JSON.stringify({ source: "browser-demo", device_index: dev.index }),
    created_at:            now,
    updated_at:            now,
    completed_at:          now,
  };
}

function buildMonitoringRecord(monitoringWfId, dev, payment, monitoring) {
  const now = new Date().toISOString().replace("Z", "");
  const routedRule = dev.deviceType === "atm" ? "ATM_Rules" : "POS_Rules";
  const completedSteps = [
    "Extract_Features", "Route_By_Type", routedRule,
    "Score_With_Wasm", "Apply_Typologies", "Monitoring_Verdict", "Flag_Transaction",
  ];

  return {
    id:                    monitoringWfId,
    workflow_type:         "TransactionMonitoring",
    workflow_version:      "1.0.0",
    definition_snapshot:   JSON.stringify({
      workflow_type: "TransactionMonitoring",
      workflow_version: "1.0.0",
      steps: JSON.parse(MONITORING_STEPS_CONFIG),
    }),
    current_step:          "Flag_Transaction",
    status:                "COMPLETED",
    state:                 JSON.stringify({
      device_id:            dev.id,
      device_type:          dev.deviceType,
      transaction_id:       payment.transaction_id,
      amount:               payment.amount,
      merchant_id:          payment.merchant_id,
      features:             monitoring.features,
      rules_fired:          monitoring.rules_fired,
      ml_risk_score:        monitoring.ml_risk_score,
      ml_confidence:        monitoring.ml_confidence,
      anomaly_features:     monitoring.anomaly_features,
      typologies_triggered: monitoring.typologies_triggered,
      risk_level:           monitoring.risk_level,
      action:               monitoring.action,
      alert_id:             monitoring.alert_id,
    }),
    steps_config:          MONITORING_STEPS_CONFIG,
    state_model_path:      "txn_monitoring_steps.TransactionMonitoringState",
    saga_mode:             0,
    completed_steps_stack: JSON.stringify(completedSteps),
    data_region:           "edge",
    priority:              5,
    metadata:              JSON.stringify({ source: "browser-demo", device_index: dev.index }),
    created_at:            now,
    updated_at:            now,
    completed_at:          now,
  };
}

// ── Legacy mode ────────────────────────────────────────────────────────────
function runLegacyMode() {
  log("⚠️  Legacy mode: scheduling 100 independent setTimeout callbacks — UI will freeze");
  for (let i = 0; i < Math.min(devices.length, 100); i++) {
    scheduleLegacyDevice(devices[i]);
  }
}

function scheduleLegacyDevice(dev) {
  if (!running || !legacyMode) return;
  const start = Date.now();
  const duration = 1 + Math.floor(Math.random() * 15);
  while (Date.now() - start < duration) { /* spin */ }
  setState(dev, STATE.WASM_EXEC);
  setTimeout(() => {
    setState(dev, STATE.ONLINE);
    scheduleLegacyDevice(dev);
  }, 100 + Math.random() * 200);
}

// ── Network condition simulation ───────────────────────────────────────────
async function fetchWithCondition(url, options = {}) {
  if (condition === "degraded") {
    await sleep(100 + Math.random() * 100);
  } else if (condition === "lossy") {
    if (Math.random() < 0.2) throw new Error("[NetSim] packet loss");
    await sleep(50 + Math.random() * 50);
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

// ── Mesh peer relay (BFS, max 3 hops) ─────────────────────────────────────
const PEER_RADIUS = 5;  // devices within ±PEER_RADIUS index are spatial peers

function lcgNext(seed) {
  return (seed * 1664525 + 1013904223) & 0xffffffff;
}

function getPeerIndices(dev) {
  const indices = [];
  for (let d = -PEER_RADIUS; d <= PEER_RADIUS; d++) {
    if (d === 0) continue;
    const idx = dev.index + d;
    if (idx >= 0 && idx < devices.length) indices.push(idx);
  }
  // Seeded shuffle — each device has a stable but different ordering
  let seed = dev.index * 2654435761;
  for (let i = indices.length - 1; i > 0; i--) {
    seed = lcgNext(seed);
    const j = Math.abs(seed) % (i + 1);
    [indices[i], indices[j]] = [indices[j], indices[i]];
  }
  return indices;
}

function findRelayPeer(forDev, maxDepth = 3) {
  const visited = new Set([forDev.index]);
  let frontier = getPeerIndices(forDev);

  for (let depth = 1; depth <= maxDepth; depth++) {
    const nextFrontier = [];
    for (const idx of frontier) {
      if (visited.has(idx)) continue;
      visited.add(idx);
      const peer = devices[idx];
      if (!peer) continue;
      if ((peer.state === STATE.ONLINE || peer.state === STATE.SYNCED) && peer.relayLoad < 5) {
        return { peer, hops: depth };
      }
      // Expand: add peer's spatial neighbours to next frontier
      for (const ni of getPeerIndices(peer)) {
        if (!visited.has(ni)) nextFrontier.push(ni);
      }
    }
    frontier = nextFrontier;
    if (frontier.length === 0) break;
  }
  return null;
}

async function tryMeshRelay(dev) {
  if (dev.safQueue.length === 0) return false;
  const relay = findRelayPeer(dev);
  if (!relay) return false;

  const { peer, hops } = relay;
  setState(dev, STATE.MESH_RELAY);
  peer.relayLoad++;

  const label   = devLabel(dev);
  const typeTag = `[${dev.deviceType.toUpperCase()}]`;
  const items   = dev.safQueue.splice(0);
  const count   = items.length;
  const hopWord = hops === 1 ? "hop" : "hops";

  // Tag items with relay metadata
  for (const item of items) {
    item.txn.relay_source   = dev.id;
    item.txn.relay_hops     = hops;
    item.txn.relayed_at     = Date.now();
    peer.safQueue.push(item);
  }

  postMessage({ type: "SAF_CHANGE", deviceIndex: dev.index, queueDepth: 0 });
  postMessage({ type: "RELAY_EDGE", from: dev.index, to: peer.index, hops, count });
  meshRelayed += count;
  peer.relayLoadTotal += count;

  log(
    `${label} ${typeTag} MESH_RELAY  via device-${String(peer.index + 1).padStart(3, "0")} ` +
    `(${hops} ${hopWord})  ${count} txn${count !== 1 ? "s" : ""} relayed`
  );

  // Prompt relay peer to drain immediately if it's currently online
  if (peer.state === STATE.ONLINE || peer.state === STATE.SYNCED) {
    drainSAF(peer).catch(() => {});
  }

  // relayLoad released after drain completes (or peer drains asynchronously)
  // Use a brief delay to decrement after the drain has likely started
  setTimeout(() => { peer.relayLoad = Math.max(0, peer.relayLoad - 1); }, 5000);

  setState(dev, STATE.OFFLINE);
  return true;
}

// ── Stats loop ─────────────────────────────────────────────────────────────
function startStatsLoop() {
  setInterval(() => {
    if (!running) return;

    const now       = Date.now();
    const windowMs  = now - txnWindowStart;
    const txnsPerSec = windowMs > 0 ? Math.round((txnCount / windowMs) * 1000) : 0;

    let p99 = 0;
    if (latencyTimings.length > 0) {
      const sorted = [...latencyTimings].sort((a, b) => a - b);
      p99 = sorted[Math.floor(sorted.length * 0.99)] || sorted[sorted.length - 1];
    }

    const safTotal    = devices.reduce((s, d) => s + d.safQueue.length, 0);
    const onlineCount = devices.filter(d =>
      d.state === STATE.ONLINE || d.state === STATE.SYNCED || d.state === STATE.WORKFLOW_DONE
    ).length;

    postMessage({
      type: "STATS",
      txnsPerSec,
      p99Payment: Math.round(p99),
      totalSynced,
      totalSafQueued: safTotal,
      onlineCount,
      totalDevices: devices.length,
      approvedOnline,
      approvedOffline,
      declined,
      highRiskCount,
      meshRelayed,
      wireStats: {
        hbJson:   lastHeartbeatJsonBytes,
        hbProto:  lastHeartbeatProtoBytes,
        safJson:  lastSafBatchJsonBytes,
        safProto: lastSafBatchProtoBytes,
        safCount: lastSafBatchCount,
      },
    });

    // Post leaderboard update
    const heroMap = {};
    for (const d of devices) {
      if (d.relayLoadTotal > 0) heroMap[d.id] = { count: d.relayLoadTotal, index: d.index };
    }
    const heroes = Object.entries(heroMap)
      .sort((a, b) => b[1].count - a[1].count)
      .slice(0, 5)
      .map(([id, v]) => [id, v.count]);
    postMessage({ type: "LEADERBOARD", heroes });

    txnCount = 0;
    txnWindowStart = now;
    if (latencyTimings.length > 1000) latencyTimings = latencyTimings.slice(-1000);
  }, 1000);
}

// ── Proto wire size estimator ──────────────────────────────────────────────
// Mirrors src/rufus/proto/edge.proto field definitions.
// Used for JSON vs proto payload comparison panel — no library needed.
function _varintSize(n) {
  if (n <= 0) return 1;
  let size = 0; while (n > 0) { n >>>= 7; size++; } return size;
}
function _protoStr(s) {
  const bytes = new TextEncoder().encode(s || "").length;
  return 1 + _varintSize(bytes) + bytes;  // tag(1B) + length-varint + content
}
function _protoInt(v) { return 1 + _varintSize(Math.abs(v | 0)); }

function estimateHeartbeatProto(dev) {
  // HeartbeatMsg fields: device_id(1), device_status(2), pending_saf_count(3),
  //                      sdk_version(4), timestamp_ms(5 int64)
  return _protoStr(dev.id) + _protoStr("online") + _protoInt(dev.safQueue.length) +
         _protoStr("1.0.0rc5") + 9;  // int64: tag(1) + fixed 8 bytes
}

function estimateSafBatchProto(txns) {
  // EncryptedTransaction fields: transaction_id(1), encrypted_blob(2),
  //   encryption_key_id(3), hmac(4), merchant_id(5), amount_cents(6),
  //   currency(7), card_last_four(8), workflow_id(9)
  // SyncBatch: transactions(1 repeated), device_sequence(2), device_timestamp(3)
  if (!txns || txns.length === 0) return 0;
  const t = txns[0];
  const perTxn = _protoStr(t.transaction_id || "") + _protoStr(t.encrypted_blob || "") +
    _protoStr(t.encryption_key_id || "") + _protoStr(t.hmac || "") +
    _protoStr(t.merchant_id || "") + _protoInt(t.amount_cents || 0) +
    _protoStr(t.currency || "USD") + _protoStr(t.card_last_four || "") +
    _protoStr(t.workflow_id || "");
  const txnsTotal = perTxn * txns.length;
  // SyncBatch wrapper: repeated field tag+len + sequence int + timestamp str
  return 1 + _varintSize(txnsTotal) + txnsTotal + _protoInt(0) +
         _protoStr(new Date().toISOString());
}

// ── Helpers ────────────────────────────────────────────────────────────────
function devLabel(dev) {
  return `browser-device-${String(dev.index + 1).padStart(3, "0")}`;
}

function setState(dev, newState) {
  if (dev.state === newState) return;
  dev.state = newState;
  postMessage({ type: "STATE_UPDATE", deviceIndex: dev.index, newState });
}

function log(msg) {
  const ts = new Date().toLocaleTimeString("en-GB", { hour12: false });
  postMessage({ type: "LOG", message: `${ts}  ${msg}` });
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function recordTiming(ms) {
  latencyTimings.push(ms);
  if (latencyTimings.length > 2000) latencyTimings.shift();
}
