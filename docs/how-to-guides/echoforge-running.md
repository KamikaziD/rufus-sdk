# Running EchoForge

This guide covers every way to start the full EchoForge stack — from a one-command Docker Compose run to individual local processes for development.

---

## Quick start

```bash
cd packages/ruvon-echoforge
./start.sh          # interactive — choose Docker Compose or local processes
./start.sh --local  # local processes, no prompt
./start.sh --compose # Docker Compose, no prompt
./start.sh stop     # stop Compose stack
./start.sh logs     # tail Compose logs
```

Flags:

| Flag | Effect |
|------|--------|
| `--local` | Skip prompt, use local processes |
| `--compose` | Skip prompt, use Docker Compose |
| `--no-nats` | Local mode: skip NATS (bridge still starts) |
| `--no-dash` | Local mode: skip the Next.js dashboard |

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | ≥ 3.10 | For the bridge and mock exchange |
| Node.js | ≥ 20 | For the dashboard and tracker |
| Docker + Compose | Any recent | Required only for the Docker path |
| `ruvon-echoforge` | installed | `pip install -e packages/ruvon-echoforge` |

---

## Option A — Docker Compose (recommended)

```bash
cd packages/ruvon-echoforge

# Core: NATS + bridge + mock exchange + Trystero tracker
docker compose up

# Everything including the Next.js dashboard
docker compose --profile full up
```

Then serve the browser node from a separate terminal:

```bash
python packages/ruvon-echoforge/browser/serve.py
# Open http://localhost:8080
```

### Env overrides

Create `.env` next to `docker-compose.yml`:

```bash
cp packages/ruvon-echoforge/.env.sample packages/ruvon-echoforge/.env
```

Edit as needed — all port and behaviour overrides go there. See [Environment Variables](#environment-variables) below for the full list.

---

## Option B — Local processes

Run each service in its own terminal. This is the recommended path during active development because it gives you live reload on the bridge and direct access to logs.

### 1 — NATS (optional)

NATS enables PHIC config to be published to external subscribers. The bridge starts fine without it — the PHIC WebSocket push to the dashboard works regardless.

```bash
# Docker (quickest):
docker run -d --name echoforge-nats \
  -p 4222:4222 -p 8222:8222 \
  nats:2.10-alpine -js -m 8222

# macOS (Homebrew):
brew install nats-server && nats-server -js

# Monitor at http://localhost:8222
```

### 2 — Bridge

```bash
pip install -e "packages/ruvon-echoforge"

# Without NATS:
echoforge

# With NATS:
NATS_URL=nats://localhost:4222 echoforge
# Listening on ws://localhost:8765
```

### 3 — Exchange

**Mock VALR** (synthetic data, no real credentials needed):

```bash
python -m ruvon_echoforge.tests.mock_valr.server
# REST + WS on http://localhost:8766
```

Control the mock at runtime:

```bash
# Inject a 10-second VPIN toxicity spike (triggers Nociceptor)
curl -X POST localhost:8766/mock/toxicity \
  -H "Content-Type: application/json" \
  -d '{"duration_seconds": 10, "volatility_spike": 0.005}'

# Add 200ms REST latency (triggers Proprioceptor)
curl -X POST localhost:8766/mock/latency \
  -H "Content-Type: application/json" \
  -d '{"jitter_ms": 200}'

# Make orders reject (tests SAF queue)
curl -X POST localhost:8766/mock/order-fill \
  -H "Content-Type: application/json" \
  -d '{"mode": "reject"}'

# Check current state
curl localhost:8766/mock/state
```

### 4 — Trystero tracker (optional)

The browser nodes use `wss://tracker.openwebtorrent.com` by default. Run the self-hosted tracker when you need air-gapped operation or want to restrict which rooms are allowed:

```bash
cd packages/ruvon-echoforge/signaling
npm install
npm start
# WS on ws://localhost:8888
```

Set the Relay URL in the browser UI to `ws://localhost:8888` when starting a node.

### 5 — Browser node

```bash
python packages/ruvon-echoforge/browser/serve.py
# http://localhost:8080

# Custom port:
python packages/ruvon-echoforge/browser/serve.py 9000
```

The server sets `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Embedder-Policy: require-corp` automatically — required for `SharedArrayBuffer` (the ring buffer) and WebGPU.

### 6 — PHIC dashboard

```bash
cd packages/ruvon-echoforge/dashboard
npm install   # first time only
npm run dev
# http://localhost:3001/echoforge
```

The dashboard connects to the bridge at `NEXT_PUBLIC_BRIDGE_URL` (default `http://localhost:8765`).

---

## Port reference

| Service | Default port | Protocol | Health check |
|---------|-------------|----------|-------------|
| Bridge | 8765 | HTTP + WS | `GET /docs` |
| Mock VALR | 8766 | HTTP + WS | `GET /v1/public/time` |
| Browser node server | 8080 | HTTP | — |
| Trystero tracker | 8888 | WS | — |
| NATS client | 4222 | TCP | — |
| NATS monitoring | 8222 | HTTP | `GET /healthz` |
| PHIC dashboard | 3001 | HTTP | — |

---

## Environment variables

All variables are optional. The bridge runs with sensible defaults if none are set.

| Variable | Default | Description |
|----------|---------|-------------|
| `NATS_URL` | *(unset)* | e.g. `nats://localhost:4222`. If unset, NATS publish is skipped silently. |
| `ECHOFORGE_HOST` | `0.0.0.0` | Bridge bind address |
| `ECHOFORGE_PORT` | `8765` | Bridge listen port |
| `ECHOFORGE_CORS_ORIGINS` | `*` | Comma-separated allowed CORS origins |
| `NEXT_PUBLIC_BRIDGE_URL` | `http://localhost:8765` | Dashboard → bridge URL (baked at Next.js build time) |
| `BRIDGE_PORT` | `8765` | Docker Compose port override |
| `MOCK_VALR_PORT` | `8766` | Docker Compose port override |
| `TRACKER_PORT` | `8888` | Docker Compose port override |
| `NATS_PORT` | `4222` | Docker Compose port override |
| `DASHBOARD_PORT` | `3001` | Docker Compose port override |
| `TRACKER_ALLOW_ALL` | `true` | Allow all info-hashes. Set to `false` with `TRACKER_ALLOW_HASHES` for allowlist. |
| `TRACKER_ALLOW_HASHES` | *(unset)* | Comma-separated 8-char info-hash prefixes to allow |
| `TRACKER_TRUST_PROXY` | *(unset)* | Set to any value to trust `X-Forwarded-For` |

Copy `.env.sample` to `.env` in `packages/ruvon-echoforge/` and uncomment the variables you need.

---

## Typical dev workflow

```bash
# Terminal 1 — NATS
docker run --rm -p 4222:4222 nats:2.10-alpine -js

# Terminal 2 — bridge (auto-restarts on file change with --reload)
NATS_URL=nats://localhost:4222 uvicorn ruvon_echoforge.bridge.main:app \
  --host 0.0.0.0 --port 8765 --reload

# Terminal 3 — mock exchange
python -m ruvon_echoforge.tests.mock_valr.server

# Terminal 4 — browser node
python packages/ruvon-echoforge/browser/serve.py

# Terminal 5 — dashboard
cd packages/ruvon-echoforge/dashboard && npm run dev
```

Open:
- Browser node: http://localhost:8080
- PHIC dashboard: http://localhost:3001/echoforge
- NATS monitoring: http://localhost:8222
- Bridge docs: http://localhost:8765/docs

---

## Multi-tab mesh

To simulate a private fog network locally, open http://localhost:8080 in multiple tabs. Each tab is a separate peer. They will discover each other via the Trystero tracker and form a WebRTC mesh. The dashboard at http://localhost:3001/echoforge shows all peers' S(Ex) scores and which node currently holds Sovereign execution rights.

To test regime quorum:

1. Open 3 tabs (3 peers)
2. Inject toxicity on the mock server: `curl -X POST localhost:8766/mock/toxicity -d '{"duration_seconds":30}'`
3. Watch all three nodes independently detect the VPIN spike and reach Crisis regime quorum

---

## Running tests

```bash
# Integration tests (bridge ↔ dashboard flow)
python -m pytest packages/ruvon-echoforge/tests/test_bridge_integration.py -v

# Mock VALR server tests
python -m pytest packages/ruvon-echoforge/tests/mock_valr/ -v

# All echoforge tests
python -m pytest packages/ruvon-echoforge/tests/ -v
```
