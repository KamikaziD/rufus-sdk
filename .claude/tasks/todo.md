# EchoForge Syndicate — Active Tasks

## Phase 1: Sovereign Node (Weeks 1-2)
### Existing Package Enhancements (rufus-sdk + rufus-sdk-edge)
- [x] planning/ruvon_echoforge_masterplan.md — written to project
- [ ] rufus-sdk-edge: `src/rufus_edge/nkey_signer.py` — NKeyPatchSigner (closes `""` sig gap in agent.py:955)
- [ ] rufus-sdk-edge: `src/rufus_edge/echoforge_gossip.py` — SharedEcho dataclass + EchoForgeGossipManager
- [ ] rufus-sdk-edge: `src/rufus_edge/transport/nats_transport.py` — add 4 echoforge NATS methods
- [ ] rufus-sdk: `src/rufus/proto/echoforge.proto` — SharedEcho, SentinelAlert, PHICConfig schemas
- [ ] tests: `tests/edge/test_nkey_signer.py` — sign/verify roundtrip, from_env, generate_keypair
- [ ] tests: `tests/edge/test_echoforge_gossip.py` — SharedEcho ser/deser, staleness, gossip manager

### ruvon-echoforge Bootstrap (new repo)
- [ ] Repo directory structure + README
- [ ] `core/Cargo.toml` — wasm32-wasip2 workspace
- [ ] `core/src/ring_buffer.rs` — SharedArrayBuffer 1MB lock-free circular tick buffer
- [ ] `core/src/nociceptor.rs` — VPIN formula + threshold guard (<10ms target)
- [ ] `core/src/proprioceptor.rs` — EWMA latency + clock-skew detection (<5ms target)
- [ ] `core/src/metabolic.rs` — NetAlpha = GrossDelta - (fees + slippage) (<8ms target)
- [ ] `core/echoforge.wit` — WIT interface extending rufus.wit with sentinel interface
- [ ] `engine/echo_store.py` — SQLite-backed MarketEcho pattern store
- [ ] `engine/decay_engine.py` — Bayesian α-update: a_{t+1} = a_t·(1-α) + outcome·α
- [ ] `engine/regime_detector.py` — VolatilityRegime classification (LowVol/HighVol/Toxic)
- [ ] `api/tick_bridge.py` — Exchange WS/REST → NATS tick ingestion stub

## Phase 2: PHIC Dashboard (Weeks 3-4)
- [ ] Duplicate rufus-dashboard → ruvon-echoforge/phic/ (strip Rufus-specific routes)
- [ ] 4-quadrant layout: Syndicate Health | Active Echoes | Sentinel Alerts | Risk Metrics
- [ ] `SentinelPanel` component — WebSocket-fed stream of reflex triggers
- [ ] `EchoTable` component — live aliveness scores, regime tags, per-pattern veto toggles
- [ ] `RiskMetrics` component — drawdown curve, position exposure, fee-efficiency gauge
- [ ] PHIC controls: autonomy slider (0.0–1.0), veto list, regime caps, emergency freeze
- [ ] `api/main.py` — FastAPI adapted from rufus_server: POST /phic/config, GET /ws/metrics, POST /session/record
- [ ] Wire PHIC dashboard → EchoForge API WebSocket (100ms push)

## Phase 3: Private Fog Network (Weeks 5-6)
- [ ] `network/signaling/` — Node.js + Socket.io signaling server (STUN/TURN fallback)
- [ ] `network/worker.js` — Adapted browser_demo_3 for EchoForge (ANNOUNCE→ECHO_ANNOUNCE, HEARTBEAT→ALIVENESS_UPDATE)
- [ ] `network/gossip_router.py` — Quorum consensus engine (N/2+1) for regime shifts
- [ ] Wire ruvon.echoforge.* NATS subjects in echoforge-api nats_bridge
- [ ] Integration test: 3 nodes gossip SharedEcho, quorum vote regime, verify <50ms P2P

## Phase 4: Live Micro-Test (Weeks 7-8)
- [ ] `api/tick_bridge.py` — Full VALR/Binance WebSocket integration (ExchangeAdapter)
- [ ] `gym/replay_engine.py` — L2 snapshot replay at 1x–10x speed through NATS mesh
- [ ] `gym/latency_injector.py` — Synthetic 10–100ms latency injection
- [ ] `gym/metrics.py` — Sharpe ratio, max drawdown, echo survival rate, fee ratio
- [ ] `engine/session_recorder.py` — IndexedDB/SQLite session log (deterministic replay)
- [ ] `security/key_manager.py` — Python ed25519 keypair gen, rotation, audit trail
- [ ] `security/key_manager.ts` — Browser IndexedDB + Web Crypto AES-GCM
- [ ] 7-day live micro-test ($50–100 capital, decay tuning via L2 Gym)

## Review
_Updated after each phase completes._
