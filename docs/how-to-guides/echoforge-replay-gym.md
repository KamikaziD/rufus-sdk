# L2 Replay Gym and Decay Tuner

EchoForge records every trading session to IndexedDB. Two tools let you turn those recordings into actionable parameter improvements:

- **L2 Replay Gym** — feeds historical ticks back through the mock VALR server so sentinels react to real market events at configurable speed
- **Decay Tuner** — grid-searches the Bayesian decay parameters against a real session's outcomes to find the (decay_rate, loss_multiplier) pair that maximises Sharpe ratio

---

## Exporting a session

From the browser console while a node is running:

```js
// Download session as JSON
window.exportSession()

// Print summary stats without downloading
await window.sessionStats()
```

Or click the **Export Session** button in the browser UI. The downloaded file is a JSON object with this schema:

```json
{
  "session_id": "uuid",
  "started_at": 1714000000000,
  "exported_at": 1714003600000,
  "phic_hash":  "a1b2c3d4",
  "ticks":      [...],
  "decisions":  [...],
  "outcomes":   [...],
  "events":     [...]
}
```

Ticks are sampled at 1 per second (raw rate is ~20/s) to keep file sizes manageable on 7-day runs. Decisions, outcomes, and events are recorded at full fidelity.

---

## L2 Replay Gym

The replay gym loads a session export, extracts the tick sequence, and POSTs it to the mock VALR server's `/mock/replay` endpoint. The mock server replays the ticks over WebSocket at the original inter-tick timing, scaled by a speed multiplier.

### Requirements

```bash
pip install httpx
```

The mock VALR server must be running:

```bash
python -m ruvon_echoforge.tests.mock_valr.server
```

### Usage

```bash
# Replay at real-time speed
python -m ruvon_echoforge.tests.mock_valr.replay_gym session_export.json

# Replay at 5× speed
python -m ruvon_echoforge.tests.mock_valr.replay_gym session_export.json --speed 5

# Validate and print stats without sending to server
python -m ruvon_echoforge.tests.mock_valr.replay_gym session_export.json --dry-run

# Custom server URL
python -m ruvon_echoforge.tests.mock_valr.replay_gym session_export.json \
  --server http://localhost:8766 --speed 10
```

### What it does

1. Parses the session export JSON and normalises tick fields (handles several field name variants from different browser versions)
2. POSTs the tick array to `POST /mock/replay` with the chosen speed multiplier
3. Polls `GET /mock/replay/status` every 500ms and renders a live progress bar
4. On completion, prints session stats: Sharpe ratio, win rate, signal pass rate, and sentinel breakdown

### Output example

```
Loading session: session_export.json
  4320 ticks  |  5.0× speed  |  pair=BTCUSDT

Starting replay on http://localhost:8766 …
  Server ack: {'status': 'started', 'total': 4320, 'speed': 5.0}

  [████████████████████████████████████████] 4320/4320 (100.0%)
  Replay complete: 4320/4320 ticks

── Session Replay Stats ─────────────────────────────
  Session ID : 3f8a1b2c4e6d…
  Ticks      : 4320
  Signals    : 87 passed / 213 dropped  (pass rate 29.00%)
  Executions : 61  |  Win rate: 57.38%  |  Sharpe: 0.8412
  Sentinels  : Nociceptor×3, Proprioceptor×1
─────────────────────────────────────────────────────
```

### Mock replay API

The mock VALR server exposes three replay endpoints for programmatic use:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/mock/replay` | POST | Start a replay (cancels any in-progress replay) |
| `/mock/replay/status` | GET | Progress: `{running, finished, total, played, progress, speed}` |
| `/mock/replay/stop` | POST | Cancel in-progress replay |

```bash
# Start replay directly via curl
curl -X POST localhost:8766/mock/replay \
  -H "Content-Type: application/json" \
  -d '{"ticks": [...], "speed": 2.0, "pair": "BTCUSDT"}'

# Check progress
curl localhost:8766/mock/replay/status
```

---

## Decay Tuner

The Decay Tuner grid-searches two parameters of the Bayesian aliveness model:

- `DEFAULT_DECAY_RATE` — passive decay per tick (α)
- `LOSS_DECAY_MULTIPLIER` — how much faster losing patterns decay

It runs the simulation against the real decisions and outcomes from a session export, ranks by Sharpe ratio, and tells you the exact constants to copy into `echoforge_worker.js`.

### Usage

```bash
# Default grid (12 × 10 = 120 cells)
python -m ruvon_echoforge.tests.decay_tuner session_export.json

# Custom grid ranges
python -m ruvon_echoforge.tests.decay_tuner session_export.json \
  --decay-range 0.0005 0.01 15 \
  --loss-range  2.0    8.0  10

# Minimum echo survival filter (default 0.30)
python -m ruvon_echoforge.tests.decay_tuner session_export.json \
  --survival-floor 0.50

# Save full results for further analysis
python -m ruvon_echoforge.tests.decay_tuner session_export.json \
  --out tuner_results.json

# Show top 20 instead of top 10
python -m ruvon_echoforge.tests.decay_tuner session_export.json --top 20
```

### Output example

```
Session: 3f8a1b2c4e6d…
  decisions=300  outcomes=61  events=47

Grid: 12 × 10 = 120 cells

  grid search: 120/120 (100%)

── Top Results ──────────────────────────────────────────────────────────
  decay_rate  loss_mult    sharpe  win_rate  pass_rate  survival  execs
──────────────────────────────────────────────────────────────────────────
    0.00400      3.000    0.9214   61.54%    29.50%   100.00%     52
    0.00491      2.556    0.8907   59.62%    30.20%   100.00%     53
    ...
─────────────────────────────────────────────────────────────────────────

── Best Parameters ──────────────────────────────────────────────────────
  DEFAULT_DECAY_RATE      = 0.004
  LOSS_DECAY_MULTIPLIER   = 3.0

  Sharpe                  = 0.9214
  Win rate                = 61.54%
  Pass rate               = 29.50%
  Echo survival           = 100.00%
  Executions in session   = 52

To apply, update echoforge_worker.js:
  const DEFAULT_DECAY_RATE     = 0.004;
  const LOSS_DECAY_MULTIPLIER  = 3.0;
```

### How the simulation works

The tuner mirrors the `echoforge_worker.js` aliveness model exactly:

```
aliveness = max(0, aliveness × (1 - decay_rate))        # passive decay per decision
aliveness = min(1, aliveness + 0.12 × net_alpha)        # boosted on signal pass
aliveness = max(0, aliveness × (1 - decay_rate × loss_multiplier))  # on outcome loss
```

Signals that arrive when `aliveness < 0.30` are treated as dropped (gated out). The grid search finds the parameters that maximise `mean(outcome_scores) / std(outcome_scores)` (Sharpe-like ratio) across all signals that were not gated.

### Interpreting results

- **High Sharpe + high win rate** — good parameters; the decay is calibrated well for this session's regime mix
- **High pass rate + low win rate** — decay is too slow; the echo lets too many signals through including bad ones — increase `decay_rate` or `loss_multiplier`
- **Low pass rate + high win rate** — decay is too aggressive; good signals are being gated — lower `decay_rate`
- **Low echo survival** — the echo dies before the session ends; lower `decay_rate` or run more frequent replays

### Typical tuning workflow

1. Run a live session for at least 2 hours
2. `window.exportSession()` → download JSON
3. `python -m ruvon_echoforge.tests.decay_tuner session_export.json --out results.json`
4. Copy the best params into `echoforge_worker.js`
5. Verify with replay: `python -m ruvon_echoforge.tests.mock_valr.replay_gym session_export.json --dry-run`
6. Repeat after each market regime change
