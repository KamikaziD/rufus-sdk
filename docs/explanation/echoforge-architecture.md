# EchoForge Architecture

EchoForge is a browser-first, sovereign distributed quant intelligence mesh built on top of the Ruvon ecosystem. This page explains how the components fit together and why they were designed the way they were.

---

## What EchoForge Is

EchoForge runs multiple autonomous "nodes" — each a browser tab — that collectively form a fog network. Each node:

- Ingests raw exchange tick data via WebSocket
- Runs risk sentinels locally in Web Workers (no round-trip latency)
- Maintains a Bayesian pattern memory ("echoes") that decays over time
- Gossips only anonymised aliveness scores to peers via WebRTC
- Routes execution through the lowest-latency peer (the "Sovereign")
- Falls back to a local SAF queue if exchange connectivity drops

No capital amounts, API keys, balances, or trade history ever leave the local node.

---

## Component Map

```
┌────────────────────────────────────────────────────────────────────────┐
│  Browser Node (one per tab)                                            │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  Main Thread (index.html)                                       │   │
│  │  • Regime detection (VPIN + latency hysteresis)                 │   │
│  │  • Mesh coordination (Trystero WebRTC)                          │   │
│  │  • Bridge telemetry (WebSocket → FastAPI)                       │   │
│  │  • Session recording (IndexedDB)                                │   │
│  │  • Governance: CAP_TRIM, STOP_LOSS, exposure tracking           │   │
│  └───────────────┬─────────────────────────────────────────────────┘   │
│                  │ postMessage                                          │
│  ┌───────────────▼─────────────────────────────────────────────────┐   │
│  │  Web Workers (6)                                                │   │
│  │  • orderbook_worker.js  — ring buffer writer, L2 tick parsing   │   │
│  │  • nociceptor_worker.js — VPIN, proprioceptor, metabolic filter │   │
│  │  • echoforge_worker.js  — Bayesian echo decay, position gating  │   │
│  │  • execution_worker.js  — order routing, SAF, exposure tracking │   │
│  │  • inference_worker.js  — ONNX ML model (p_up, kelly sizing)    │   │
│  │  • correlation_worker.js— cross-pair + cross-exchange lag       │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  SharedArrayBuffer ring buffer (1 MB, lock-free)                │   │
│  │  orderbook_worker (writer) → nociceptor_worker (reader)         │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└───────────────┬──────────────────┬─────────────────────────────────────┘
                │ WebSocket        │ WebRTC DataChannels
                │                  │ (Trystero torrent strategy)
                ▼                  ▼
┌─────────────────┐   ┌────────────────────────────────────────────┐
│  FastAPI Bridge │   │  Fog Network (other browser nodes)         │
│  (Python)       │   │  • Gossip: aliveness scores, regime votes  │
│                 │   │  • Intent: execution routing               │
│  /api/v1/tick   │   │  • Vote: regime shift quorum               │
│  /api/v1/phic   │   │  • Pain maps: anonymised drop events       │
│  /api/v1/metrics│   └────────────────────────────────────────────┘
└────────┬────────┘
         │ optional
         ▼
┌─────────────────┐   ┌─────────────────────────────────────────────┐
│  NATS JetStream │   │  PHIC Dashboard (Next.js)                   │
│  echoforge.phic │   │  • Live VPIN + sovereign ring               │
│  .config        │   │  • Echo aliveness table                     │
└─────────────────┘   │  • Sentinel alert feed                      │
                       │  • Full PHIC governance controls            │
                       └─────────────────────────────────────────────┘
```

---

## Worker Responsibilities

### `orderbook_worker.js`

Owns the ring buffer write path. Receives L2 book snapshots and trade ticks from the exchange WebSocket, normalises them, and writes entries into the SharedArrayBuffer. Computes per-tick fields passed downstream: `price`, `bid`, `ask`, `buy_volume`, `sell_volume`, `imbalance`, `spread`, `vwap_dev`, `twap_score`, `vwap_anchor`.

### `nociceptor_worker.js`

Three sentinels in one worker:

- **Nociceptor** — reads the ring buffer via `RingBufferReader`, computes VPIN using EWMA buy/sell volumes. Raises `CANCEL_ORDERS` when VPIN exceeds crisis threshold. Throttled to at most one `sentinel_alert` per 3 seconds.
- **Proprioceptor** — tracks EWMA exchange latency and clock skew. Raises `FORCE_PASSIVE` when either exceeds ceiling. Clears passiveOnly mode with hysteresis (must drop to 70% of ceiling before clearing).
- **Metabolic Filter** — gates each signal through a dynamic fee hurdle: `hurdle = base_exec_cost × e^(regime_strain) × vpin_multiplier(strategy_type)`. Mean-reversion patterns face a much steeper hurdle in toxic flow than momentum patterns.

Emits `pain_map` gossip messages when a signal drops AND VPIN ≥ 0.35, allowing peer nodes to pre-emptively dampen the same pattern.

### `echoforge_worker.js`

Maintains the Bayesian echo registry. Each echo decays between ticks and is boosted by successful signals. Handles:

- Pattern aliveness lifecycle (decay, boost, death, revival)
- Cross-pair signal integration (correlation_worker boosts)
- Drawdown enforcement: tracks high-water mark; if portfolio drops `max_drawdown_pct`% below it for `drawdown_hysteresis_n` consecutive samples, sets `emergency_freeze`.
- Pain map reception: applies preemptive aliveness penalties from peer-reported drops. Quorum of 3+ peers with VPIN > 0.5 triggers a local pattern veto.

### `execution_worker.js`

Handles all order submission and portfolio tracking:

- Maintains `_livePrice` — updated from both fill confirmations and `price_tick` messages forwarded from every orderbook tick. This prevents stale price during Crisis regime blackouts when execution_intent messages stop.
- Tracks `_exposureByPattern` — per-pattern BTC exposure map for cap enforcement. Proportionally realigned after CAP_TRIM and STOP_LOSS fills so aggregate sells don't cause tracker drift.
- CAP_TRIM logic: when total BTC exposure exceeds `max_total_exposure_pct + 0.2%`, trims to 70% of cap. 15-second cooldown.
- STOP_LOSS logic: checks every 30 seconds whether `_livePrice` has dropped `stop_loss_pct`% below `avg_cost`. If so, sells 50% of position. 120-second cooldown.
- Kelly fraction sizing: `f* = (p_up - 0.5) / (1 - p_up)`, capped at 40%.
- Strong bear sell floor: when `net_alpha < -0.005` and `unrealized_pnl_norm < -0.003`, floors the conviction × kelly product at 0.15 to prevent micro-only exits.

### `inference_worker.js`

Runs an ONNX model (`_model.onnx`) trained via the Decay Tuner or Retrain Workflow. Probes feature width automatically on load (`_probeWidth()`). Outputs `p_up` (probability price will rise) used for Kelly sizing. In Bun/Node.js the universal shim `browser/ort.js` selects `onnxruntime-node` over `onnxruntime-web`.

### `correlation_worker.js`

Tracks multiple pairs simultaneously. Computes:

- **RVR** (`σ_BTC / σ_ETH`) — when > `rvr_threshold` (default 1.5), BTC is abnormally volatile
- **Momentum Divergence** — `ema_fast_BTC - ema_fast_ETH` (normalised)
- **Rolling Pearson** — 60-tick window; when < `pearson_threshold` (default 0.5), correlation is breaking down → arb signal
- **Flow Confirmation** — buy/sell ratio sync across pairs

Emits `cross_pair_signal` consumed by `echoforge_worker` to boost or suppress pattern aliveness. All thresholds are PHIC-configurable and can be turned off entirely with `correlation_enabled: false`.

---

## The Sovereign (S(Ex)) Election

Every node computes a score for execution rights using:

```
S(Ex) = 0.50·L + 0.25·U + 0.15·C + 0.10·P
```

| Term | Meaning |
|------|---------|
| L | Latency score (lower latency = higher score) |
| U | Uptime / stability score |
| C | Consensus score (how often this node's regime calls match the mesh) |
| P | Participation score (gossip activity) |

The peer with the highest S(Ex) becomes the **Sovereign** and routes execution intent from all nodes. Election is re-run when:
- A new peer joins
- The current Sovereign disconnects
- S(Ex) gap between top two nodes exceeds the anti-flap hysteresis margin (0.15)

Anti-flap protections: EWMA smoothing (α=0.25) and a 30-second cooldown after each election.

---

## Bayesian Echo Decay

Each trading pattern is an "echo" that lives in the worker's memory. Its `net_aliveness` decays continuously:

```
aliveness_{t+1} = aliveness_t × (1 - α)           # passive decay each tick
aliveness       += signal_strength × net_alpha      # boosted on signal pass
aliveness       *= (1 - α × LOSS_MULTIPLIER)        # extra decay on loss
```

Defaults (tunable via the Decay Tuner, or by running the Retrain workflow):

| Parameter | Default | Effect |
|-----------|---------|--------|
| `DEFAULT_DECAY_RATE` (α) | `0.005` | Passive decay per tick |
| `LOSS_DECAY_MULTIPLIER` | `2.0` | How much faster bad patterns die |
| `MIN_ALIVENESS` | `0.30` | Below this → echo is "dead", signals blocked |
| `BASE_SIGNAL_STRENGTH` | `0.12` | Aliveness boost per passing signal |

Only echoes with `net_aliveness ≥ 0.30` can route signals. Contested echoes (where the peer mesh disagrees by more than 0.30) require `net_aliveness ≥ 0.70`.

The Decay Tuner (`tests/decay_tuner.py`) performs a grid search over `(decay_rate, loss_multiplier)` pairs on exported session data and ranks by Sharpe ratio.

---

## Regime Detection

The main thread continuously classifies market conditions using VPIN and tick-latency:

| Regime | Trigger | Effect |
|--------|---------|--------|
| `LowVol` | VPIN < 0.40, latency < 100ms | Normal operation |
| `HighVol` | VPIN 0.40–0.70 or latency 100–150ms | Reduced position caps |
| `Crisis` | VPIN > 0.70 or latency > 150ms | Passive-only, Nociceptor fires |

Flap prevention uses three layers:
1. **Hysteresis** — 5 consecutive samples above threshold before promoting regime
2. **Cooldown** — 60-second lockout after each regime shift
3. **Quorum** — any regime shift requires ⌈(N+1)/2⌉ votes from connected peers; single-node failures trigger hard transitions immediately

---

## Sentinels

Sentinels are threshold monitors that run inside the Web Worker. They fire alerts which the main thread relays to the bridge and to any connected dashboard.

| Sentinel | Trigger | Alert action |
|----------|---------|-------------|
| Nociceptor | VPIN > crisis threshold | `CANCEL_ORDERS` |
| Proprioceptor | EWMA latency > 150ms or clock skew > 50ms | `FORCE_PASSIVE` |
| Metabolic | `net_alpha < dynamic_hurdle` | `DROP_SIGNAL` |
| Drawdown | Portfolio drops `max_drawdown_pct`% for N samples | `drawdown_freeze` |
| Contested | Peer aliveness delta > 0.30 (≥2 peers) | Raises echo's min-aliveness threshold |
| Regime | Quorum regime shift committed | Regime broadcast to all workers |

---

## PHIC — Partial Human In Control

PHIC is the governance layer. A human operator sets strategic bounds; the mesh executes within them.

### Core Controls

| Control | Type | Default | Effect |
|---------|------|---------|--------|
| `autonomy_level` | Float 0–1 | `0.5` | 0 = fully manual, 1 = fully autonomous |
| `vetoed_patterns` | List of IDs | `[]` | These echoes never route signals |
| `regime_caps` | Map: regime → max position % | `{}` | Per-regime position ceiling |
| `emergency_freeze` | Boolean | `false` | Halts all execution immediately |

### Position Sizing

| Control | Type | Default | Effect |
|---------|------|---------|--------|
| `max_position_pct` | Float 0–100 | `1.0` | Max % of portfolio in a single position |
| `max_total_exposure_pct` | Float 0–100 | `20.0` | Total BTC cap across all patterns. CAP_TRIM fires when exceeded by 0.2%. |
| `max_pattern_exposure_pct` | Float 0–1 | `0.30` | Max fraction of position any single pattern can hold. Blocks new buys when exceeded. |

### Risk Controls

| Control | Type | Default | Effect |
|---------|------|---------|--------|
| `stop_loss_pct` | Float 0–10 | `2.5` | Sell 50% of position when price drops this % below avg entry. 0 = disabled. 120s cooldown. |
| `max_drawdown_pct` | Float 0–100 | `2.0` | Freeze execution when portfolio drops this % below high-water mark |
| `drawdown_hysteresis_n` | Int 1–10 | `3` | Require N consecutive samples below drawdown limit before freezing (prevents false triggers) |

### Correlation Controls

| Control | Type | Default | Effect |
|---------|------|---------|--------|
| `correlation_enabled` | Boolean | `true` | Enable/disable the correlation worker entirely |
| `rvr_threshold` | Float 0.5–3.0 | `1.5` | RVR ratio above which BTC is considered abnormally volatile |
| `pearson_threshold` | Float 0.1–0.9 | `0.5` | Pearson correlation below which arb signals fire |
| `cross_pair_boost` | Float 0–0.10 | `0.04` | Aliveness boost applied when correlation confirms a pattern |

### Advanced Calibration

| Control | Type | Default | Effect |
|---------|------|---------|--------|
| `vpin_crisis_threshold` | Float | `0.70` | VPIN level that triggers CANCEL_ORDERS |
| `vpin_highvol_threshold` | Float | `0.40` | VPIN level that enters HighVol regime |
| `regime_strain_exp` | Map: regime → float | See defaults | Exponent in metabolic hurdle formula |
| `min_consensus_pct` | Float | `60.0` | Min % of peers that must agree before regime shift |

PHIC config is stored in the bridge, pushed to all subscribed dashboard WebSockets, and optionally published to NATS (`echoforge.phic.config`) for external audit/compliance systems.

---

## Exposure Management

### CAP_TRIM

When total BTC held exceeds `max_total_exposure_pct + 0.2%`, the execution worker fires a synthetic sell:

- Sells down to 70% of the cap (not 100%) to avoid immediately re-triggering on the next tick
- Uses `pattern_id: "CAP_TRIM"` for logging and PnL attribution
- 15-second cooldown between fires
- Does not increment `_exposureByPattern` for any pattern (it's a portfolio-level trim, not pattern-attributed)

### STOP_LOSS

Checked every 30 seconds by a dedicated `setInterval`:

- Fires when `(avg_cost - livePrice) / avg_cost × 100 ≥ stop_loss_pct`
- Sells 50% of current position
- `_livePrice` is updated from every orderbook tick via `price_tick` forwarding — not just from fills. This prevents stale prices during Crisis regime blackouts when execution_intent messages stop flowing.
- 120-second cooldown between fires
- Set `stop_loss_pct: 0` in PHIC to disable

### `_exposureByPattern` Proportional Realignment

After each CAP_TRIM or STOP_LOSS fill, the per-pattern exposure map is proportionally scaled so its sum matches `_portfolio.btc` (the actual position). This prevents accumulation drift where pattern-level caps remain inflated after aggregate sells, blocking all future buys.

Without realignment, a sequence like: buy MOMENTUM_V1 → buy REVERSION_A → CAP_TRIM sell would leave `_exposureByPattern` reporting 100% of the pre-trim quantities while the actual position is smaller — causing all subsequent buy attempts to fail the cap check.

---

## Pain Map Gossip

When a signal fails the metabolic filter AND VPIN ≥ 0.35, the nociceptor worker emits a `pain_map` event containing:

```js
{
  pattern_id, regime_tag,
  trigger_vpin,      // VPIN at the moment of pain
  hurdle_miss_pct,   // how far below the hurdle (fractional)
  strategy_type,     // "momentum" | "mean_reversion" | "arb"
  timestamp
}
```

Receiving nodes apply a preemptive aliveness penalty to the same pattern:
```
echo.net_aliveness *= (1 - 0.05 × hurdle_miss_pct)
```

A quorum of 3+ peer nodes all reporting pain for the same `pattern_id:regime_tag` combination with VPIN > 0.5 triggers a local temporary veto for that pattern in that regime. Pain maps expire after 60 seconds.

---

## Store-and-Forward (SAF)

When the exchange is unreachable the SAF queue absorbs execution intents. Intents are written to an IndexedDB queue inside the worker. On reconnection:

1. SAF detects `online` event or successful exchange ping
2. Replays queued intents in submission order
3. Broadcasts `saf_replay` to the mesh so other nodes know the partition healed

The SAF queue is scoped to the local node — intents are never shared over the mesh.

When running as the Bun daemon, the IndexedDB shim writes through to a local SQLite database (`edge-state.db`) and simultaneously enqueues the intent into ruvon-edge's `SyncManager` for canonical cloud-backed SAF persistence.

---

## Metabolic Hurdle Formula

```
hurdle = base_exec_cost × e^(regime_strain) × vpin_multiplier(strategy_type)
```

| Factor | Detail |
|--------|--------|
| `base_exec_cost` | `maker_fee + taker_fee` |
| `regime_strain` | LowVol: 0.0 · HighVol: 0.5 · Crisis: 1.5 (overridable via PHIC) |
| `vpin_multiplier` | mean_reversion: `1 + vpin_over × 8` · momentum: `max(0.5, 1 - vpin_over × 2)` · arb: `1.0` |
| `vpin_over` | `max(0, vpin - vpin_crisis_threshold)` |

In HighVol + mean-reversion, hurdle is 4–10× the base cost. In Crisis, it can be 20×. Momentum patterns are eased during toxic flow (VPIN is directional confirmation, not headwind). Arb patterns ignore VPIN entirely.

---

## Session Recording

Every node writes a local session log to IndexedDB (`echoforge_sessions`):

| Store | Content | Sample rate |
|-------|---------|-------------|
| `ticks` | Raw L2 ticks | 1 per second (throttled) |
| `decisions` | Signal pass/drop + `net_alpha` | Every decision |
| `outcomes` | Execution result + `outcome_score` | Every fill |
| `events` | Sentinel alerts, regime shifts, SAF events | Every event |

Sessions can be exported via `window.exportSession()` in the browser console, then fed back through the [L2 Replay Gym](../how-to-guides/echoforge-replay-gym.md) for deterministic replay and parameter tuning.

---

## Cross-Node Aliveness Validation

Peers share anonymised aliveness scores (`pattern_id + net_aliveness + regime_tag`). Each node tracks peer reports per echo:

- If ≥2 peers disagree with the local aliveness by > 0.30 → echo is **contested**
- Contested echoes show a warning badge in the dashboard
- Contested echoes require `net_aliveness ≥ 0.70` to route signals (vs 0.30 normal)
- Peer reports expire after 30 seconds to handle disconnections gracefully

This prevents a malfunctioning node from inflating its own pattern scores and routing bad signals through the Sovereign.

---

## WebRTC Transport (Trystero Torrent Strategy)

Peer-to-peer connections use Trystero with the BitTorrent tracker strategy. This replaces PeerJS as the signaling mechanism because:

- PeerJS's `0.peerjs.com` signaling server blocks non-UUID peer IDs and rejects connections from public origins
- Trystero uses a BitTorrent tracker (openwebtorrent.com or self-hosted) only for the ICE handshake — the tracker never sees gossip payloads
- The tracker can be self-hosted via `packages/ruvon-echoforge/signaling/tracker.js` for air-gapped or private deployments

Three action channels are established per room:

| Channel | Sender → Receiver | Content |
|---------|------------------|---------|
| `gossip` | broadcast | Echo aliveness, S(Ex) scores, sentinel alerts, pain maps |
| `intent` | Sovereign only | Execution intent (targeted P2P) |
| `vote` | broadcast | Regime shift proposals and votes |

The Trystero bundle (`browser/trystero-torrent.js`) is pre-built and committed to the repo. Fresh clones do not need to run `build.sh` unless upgrading the Trystero version.

---

## Portable Runtime (Bun Daemon)

The same six workers run unmodified inside a Bun subprocess via `worker_threads`. Portability gaps are closed by:

| Gap | Solution |
|-----|---------|
| `IndexedDB` | SQLite shim (`daemon/src/shims/indexed-db.js`) — write-through cache; SAF intents forwarded to Python via IPC |
| `onnxruntime-web` import path | Universal shim `browser/ort.js` — auto-selects `onnxruntime-node` in Node.js/Bun |
| `SharedArrayBuffer` | Native in Bun/Node.js 18+ — no changes needed |
| `fetch` / `crypto.randomUUID` | Native in Bun — no changes needed |

The Python host (`ruvon_edge.extensions.echoforge.EchoForgeExtension`) spawns the Bun subprocess, bridges PHIC config from `ConfigManager`, routes order intents to `SyncManager` for SAF, and publishes telemetry to NATS JetStream.
