# EchoForge Quickstart

Run the full EchoForge stack from a single command — mock exchange, bridge, and browser node.

## Prerequisites

```bash
pip install -e "packages/ruvon-echoforge"
pip install httpx websockets        # quickstart script deps
```

## Run the automated demo

```bash
python examples/echoforge_quickstart/run_quickstart.py
```

The script:
1. Starts the Mock VALR exchange on port 8766
2. Starts the EchoForge bridge on port 8765
3. Starts the browser node server on port 8080
4. Waits 15 seconds, then injects a VPIN toxicity spike
5. Listens for the Nociceptor `CANCEL_ORDERS` sentinel alert on the metrics WebSocket
6. Prints the alert and shuts down cleanly

**Open the browser** at `http://localhost:8080` after the script starts to see the live VPIN gauge, regime detection, and sentinel alerts in the UI. The automated demo runs the full stack for you; the browser UI is optional but shows the governance panel.

## Manual walkthrough

### 1 — Start services

```bash
# Terminal 1 — Mock exchange
python -m ruvon_echoforge.tests.mock_valr.server

# Terminal 2 — Bridge
echoforge
# or: uvicorn ruvon_echoforge.bridge.main:app --port 8765

# Terminal 3 — Browser node
python packages/ruvon-echoforge/browser/serve.py
```

### 2 — Open the browser node

Navigate to `http://localhost:8080`. Click **Connect** to start receiving tick data from the mock exchange. Within a few seconds you should see:

- **VPIN gauge** updating (typically 0.05–0.15 in normal synthetic flow)
- **Regime** showing `LowVol`
- **Echo table** showing pattern aliveness scores

### 3 — Inject toxicity (triggers Nociceptor)

```bash
curl -X POST localhost:8766/mock/toxicity \
  -H "Content-Type: application/json" \
  -d '{"duration_seconds": 10, "volatility_spike": 0.008}'
```

Watch VPIN spike above the crisis threshold (0.70). The Nociceptor sentinel fires `CANCEL_ORDERS` and the regime shifts to `Crisis`. The sentinel alert appears in:
- The browser UI sentinel feed
- The bridge metrics WebSocket (`ws://localhost:8765/api/v1/metrics`)
- The bridge logs

### 4 — Try PHIC governance

```bash
# Set autonomy to 0 (fully manual — no signals route)
curl -X POST localhost:8765/api/v1/phic/config \
  -H "Content-Type: application/json" \
  -d '{"autonomy_level": 0, "stop_loss_pct": 2.5, "max_total_exposure_pct": 20.0}'

# Emergency freeze (halts all execution immediately)
curl -X POST localhost:8765/api/v1/phic/freeze

# Read current PHIC config
curl localhost:8765/api/v1/phic/config
```

### 5 — Export session and tune decay parameters

After running for a few minutes, export the session log from the browser console:

```js
// In browser DevTools console:
window.exportSession()
// Downloads echoforge_session_<timestamp>.json
```

Then feed it to the Decay Tuner to find optimal `(decay_rate, loss_multiplier)`:

```bash
python -m ruvon_echoforge.tests.decay_tuner echoforge_session_<timestamp>.json \
  --out results.json
cat results.json | python -m json.tool
```

## Ports

| Service | URL | Notes |
|---------|-----|-------|
| Browser node | http://localhost:8080 | Open in browser |
| Bridge docs | http://localhost:8765/docs | Swagger UI |
| Bridge PHIC | http://localhost:8765/api/v1/phic/config | REST |
| Mock VALR | http://localhost:8766 | Synthetic exchange |

## PHIC default values

| Field | Default | Description |
|-------|---------|-------------|
| `autonomy_level` | `0.5` | 50% autonomous |
| `max_total_exposure_pct` | `20.0` | CAP_TRIM fires at 20.2% |
| `max_pattern_exposure_pct` | `0.30` | Any one pattern ≤ 30% of position |
| `stop_loss_pct` | `2.5` | Sell 50% if price drops 2.5% below avg entry |
| `max_drawdown_pct` | `2.0` | Freeze if portfolio drops 2% from high-water |

See [PHIC Architecture](../../docs/explanation/echoforge-architecture.md#phic--partial-human-in-control) for the full governance reference.
