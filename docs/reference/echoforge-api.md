# EchoForge Bridge API Reference

The EchoForge bridge is a FastAPI server that connects browser nodes to NATS and to the PHIC dashboard. All WebSocket and REST endpoints are documented here.

Base URL: `http://localhost:8765` (configurable via `ECHOFORGE_PORT`)

Interactive docs (Swagger): `http://localhost:8765/docs`

---

## WebSocket: Tick Ingestion

### `WS /api/v1/tick`

Browser nodes connect here to send market ticks and receive sentinel decisions back.

**Connection headers**

| Header | Required | Description |
|--------|----------|-------------|
| `x-node-id` | No | Arbitrary string identifying the node. Included in relayed events on the dashboard. Defaults to `"unknown"`. |

**Messages: browser → bridge**

```jsonc
// Market tick (runs Nociceptor + Proprioceptor)
{
  "type":       "tick",
  "symbol":     "BTC/USDT",
  "bid":        42000.0,
  "ask":        42001.0,
  "buy_volume": 1.5,
  "sell_volume":0.8,
  "timestamp":  1714000000000   // epoch ms — used to measure arrival latency
}

// Execution outcome (updates echo aliveness)
{
  "type":       "execution_result",
  "pattern_id": "abc123",
  "outcome_score": 0.8         // [-1.0, 1.0]; positive = win
}

// Passthrough telemetry — relayed verbatim to all dashboard /metrics subscribers
// type may be: "metrics_snapshot" | "echo_snapshot" | "sentinel_alert"
//              "order_submitted" | "order_failed" | "saf_queued" | "sovereign_update"
{
  "type": "metrics_snapshot",
  "vpin": 0.22,
  "latency_ms": 15,
  ...
}

// Keep-alive
{ "type": "ping" }
```

**Messages: bridge → browser**

```jsonc
// Sentinel alert (one message per firing sentinel)
{
  "type":          "sentinel",
  "sentinel_type": "Nociceptor",   // "Nociceptor" | "Proprioceptor" | "Metabolic"
  "action":        "CANCEL_ORDERS",
  "severity":      0.83,
  "detail":        "VPIN=0.830 > threshold=0.700",
  "timestamp":     1714000000000
}

// Echo aliveness update (after execution_result)
{
  "type":          "echo_update",
  "pattern_id":    "abc123",
  "net_aliveness": 0.71,
  "regime_tag":    "HighVol",
  "net_alpha":     0.000312
}

// Pong (response to ping)
{ "type": "pong" }
```

---

## WebSocket: Metrics Stream

### `WS /api/v1/metrics`

PHIC dashboard connects here to receive live node telemetry. The bridge pushes a `metrics_snapshot` every 100ms aggregating all connected nodes. Any typed event relayed from the tick WS also appears here.

**Messages: dashboard → bridge**

```jsonc
// Report this node's own metrics into the aggregate store
{
  "type":                "node_metrics",
  "node_id":             "node-abc",
  "tick_latency_p99_ms": 12.3,
  "vpin":                0.18,
  "regime":              "LowVol"
}
```

**Messages: bridge → dashboard**

```jsonc
// Aggregated node telemetry (every 100ms, only when nodes are connected)
{
  "type":      "metrics_snapshot",
  "nodes": [
    { "node_id": "node-abc", "tick_latency_p99_ms": 12.3, "vpin": 0.18, "updated_at": 1714000000000 }
  ],
  "timestamp": 1714000000000
}

// Pass-through relayed events from any connected browser node:
// "sentinel_alert" | "echo_snapshot" | "order_submitted" | "order_failed"
// "saf_queued" | "sovereign_update" | "metrics_snapshot"
```

---

## WebSocket: PHIC Live Updates

### `WS /api/v1/phic/ws`

Dashboard connects here to receive PHIC config pushes in real time. The bridge sends the current config immediately on connect, then pushes an update whenever `POST /api/v1/phic/config` is called.

**Messages: bridge → dashboard**

```jsonc
// Sent on connect and on every config change
{
  "type": "phic_update",
  "config": {
    // Core
    "autonomy_level":           0.5,
    "vetoed_patterns":          [],
    "regime_caps":              {},
    "emergency_freeze":         false,
    // Position sizing
    "max_position_pct":         1.0,
    "max_total_exposure_pct":   20.0,
    "max_pattern_exposure_pct": 0.30,
    // Risk controls
    "stop_loss_pct":            2.5,
    "max_drawdown_pct":         2.0,
    "drawdown_hysteresis_n":    3,
    // Correlation
    "correlation_enabled":      true,
    "rvr_threshold":            1.5,
    "pearson_threshold":        0.5,
    "cross_pair_boost":         0.04,
    // Consensus
    "min_consensus_pct":        60.0,
    // Advanced calibration (written by PHIC calibration wizard)
    "vpin_crisis_threshold":    0.70,
    "vpin_highvol_threshold":   0.40,
    "regime_strain_exp":        { "LowVol": 0.0, "HighVol": 0.5, "Crisis": 1.5 }
  },
  "config_hash": "a1b2c3d4"   // MD5 fingerprint (first 8 hex chars); absent on initial send
}
```

---

## REST: PHIC Governance

### `GET /api/v1/phic/config`

Returns the current PHIC config.

**Response 200**
```json
{
  "autonomy_level":           0.5,
  "vetoed_patterns":          [],
  "regime_caps":              {},
  "emergency_freeze":         false,
  "max_position_pct":         1.0,
  "max_total_exposure_pct":   20.0,
  "max_pattern_exposure_pct": 0.30,
  "stop_loss_pct":            2.5,
  "max_drawdown_pct":         2.0,
  "drawdown_hysteresis_n":    3,
  "correlation_enabled":      true,
  "rvr_threshold":            1.5,
  "pearson_threshold":        0.5,
  "cross_pair_boost":         0.04,
  "min_consensus_pct":        60.0,
  "vpin_crisis_threshold":    0.70,
  "vpin_highvol_threshold":   0.40,
  "regime_strain_exp":        { "LowVol": 0.0, "HighVol": 0.5, "Crisis": 1.5 }
}
```

---

### `POST /api/v1/phic/config`

Update the PHIC config. Pushes new config to all connected PHIC WebSocket subscribers and publishes to NATS `echoforge.phic.config` if `NATS_URL` is set.

Partial updates are **not** supported — send the full config object. Unset fields revert to their defaults.

**Request body** — same schema as `GET` response above. All fields optional; defaults shown.

**Field constraints**

| Field | Type | Constraints |
|-------|------|-------------|
| `autonomy_level` | float | 0.0 – 1.0 |
| `vetoed_patterns` | list[str] | Pattern IDs to hard-block |
| `regime_caps` | dict[str, float] | Regime name → max position % |
| `emergency_freeze` | bool | Halts all execution when `true` |
| `max_position_pct` | float | 0.0 – 100.0 |
| `max_total_exposure_pct` | float | 0.0 – 100.0; CAP_TRIM triggers at +0.2% |
| `max_pattern_exposure_pct` | float | 0.0 – 1.0; blocks buys when any pattern exceeds this fraction |
| `stop_loss_pct` | float | 0.0 – 10.0; 0 disables; fires every 30s with 120s cooldown |
| `max_drawdown_pct` | float | 0.0 – 100.0 |
| `drawdown_hysteresis_n` | int | 1 – 10; consecutive samples required before freeze |
| `correlation_enabled` | bool | Disable to stop correlation_worker from boosting patterns |
| `rvr_threshold` | float | 0.5 – 3.0 |
| `pearson_threshold` | float | 0.1 – 0.9 |
| `cross_pair_boost` | float | 0.0 – 0.10 |
| `min_consensus_pct` | float | 0.0 – 100.0 |
| `vpin_crisis_threshold` | float | 0.0 – 1.0; written by calibration wizard |
| `vpin_highvol_threshold` | float | 0.0 – 1.0; written by calibration wizard |
| `regime_strain_exp` | dict | Regime name → float exponent |

**Response 200**
```json
{ "status": "applied", "config_hash": "a1b2c3d4" }
```

**Response 422** — validation error if any field is out of range.

---

### `POST /api/v1/phic/freeze`

Emergency freeze: sets `emergency_freeze: true` on the current config without requiring the full config object. Pushes update to all PHIC WS subscribers.

**Response 200**
```json
{ "status": "frozen", "config_hash": "b2c3d4e5" }
```

---

## Mock VALR Server API

The mock exchange server (`tests/mock_valr/server.py`) implements a subset of the VALR REST and WebSocket API plus a `/mock/*` control API for testing.

Base URL: `http://localhost:8766`

### VALR-compatible endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/public/time` | Server time |
| `GET` | `/v1/marketdata/{pair}/orderbook` | Synthetic L2 book |
| `POST` | `/v1/orders/limit` | Submit limit order |
| `POST` | `/v1/orders/market` | Submit market order |
| `DELETE` | `/v1/orders/{symbol}` | Cancel all orders |
| `GET` | `/v1/orders/open` | List open orders |
| `WS` | `/v1/ws` | Market data WebSocket (VALR format) |

### Mock control API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/mock/toxicity` | Inject VPIN spike |
| `POST` | `/mock/toxicity/clear` | Clear toxicity |
| `POST` | `/mock/latency` | Set REST jitter (ms) |
| `POST` | `/mock/rate-limit` | Toggle 429 responses on /orders |
| `POST` | `/mock/order-fill` | Set fill mode: `immediate` \| `delayed` \| `reject` |
| `POST` | `/mock/price` | Override base price and volatility |
| `GET` | `/mock/state` | Current mock state |
| `POST` | `/mock/replay` | Start session replay |
| `GET` | `/mock/replay/status` | Replay progress |
| `POST` | `/mock/replay/stop` | Stop replay |

**`POST /mock/toxicity`**
```json
{ "duration_seconds": 10.0, "volatility_spike": 0.005 }
```

**`POST /mock/latency`**
```json
{ "jitter_ms": 200 }
```

**`POST /mock/order-fill`**
```json
{ "mode": "reject", "reject_reason": "Insufficient balance" }
```

**`POST /mock/replay`**
```json
{
  "ticks": [
    { "price": 42000.0, "quantity": 0.5, "takerSide": "buy", "tradedAt": "2024-04-24T10:00:00.000Z" }
  ],
  "speed": 5.0,
  "pair": "BTCUSDT"
}
```

**`GET /mock/replay/status`**
```json
{ "running": true, "finished": false, "total": 4320, "played": 1240, "progress": 0.2870, "speed": 5.0 }
```

---

## NATS Subjects

| Subject | Direction | Content |
|---------|-----------|---------|
| `echoforge.phic.config` | bridge → subscribers | JSON: `{"config": {...}, "hash": "a1b2c3d4"}` |

NATS integration is optional. Set `NATS_URL` environment variable to enable. The bridge creates a fresh NATS connection per PHIC config update and drains it immediately (stateless publish pattern). A persistent connection with JetStream is planned for future versions.

---

## Tracker (Trystero Signaling)

The self-hosted WebTorrent tracker at `packages/ruvon-echoforge/signaling/tracker.js` accepts standard BitTorrent tracker WebSocket announces. It is not an HTTP API — clients (Trystero) communicate with it using the WebTorrent tracker protocol.

Configuration is via environment variables only (see [Running EchoForge](echoforge-running.md)).
