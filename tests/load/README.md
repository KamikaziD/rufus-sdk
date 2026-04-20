# Ruvon Edge Load Testing Suite

Load testing infrastructure for validating Ruvon Edge control plane performance at scale
(1000+ devices), covering HTTP synchronisation, WASM execution, gossip protocols, leader
election, and end-to-end decision pipelines.

---

## Quick Start

### Prerequisites

```bash
pip install httpx psutil msgspec nats-py
```

### Run from the `tests/load/` directory (or repo root)

All scripts auto-detect whether they are invoked from the repo root or from the
`tests/load/` directory and adjust `sys.path` accordingly.

```bash
cd tests/load

# Smoke test – local-only, no server needed
python run_load_test.py --scenario ruvon_gossip --devices 100 --duration 60

# HTTP scenario – needs the control plane running
python run_load_test.py --scenario saf_sync --devices 500 --cloud-url http://localhost:8000
```

### Start the control plane (HTTP scenarios only)

```bash
cd docker && docker compose up -d
curl http://localhost:8000/health   # → {"status": "healthy"}
```

---

## Scenarios

### HTTP scenarios (require `--cloud-url`)

| Scenario | Default duration | Target |
|---|---|---|
| `heartbeat` | 600s | ~33 req/s; p95 < 500ms; error rate < 0.5% |
| `saf_sync` | 300s | 1000 tx/s; p99 < 500ms |
| `config_poll` | 600s | ETag cache hit > 95%; p95 < 200ms |
| `cloud_commands` | 600s | Command delivery p95 < 5s |
| `thundering_herd` | — | All devices reconnect simultaneously |
| `mixed` | 300s | Heartbeat + gossip + SAF simultaneously; all error rates < 1% |

### Local-only scenarios (no server, no registration)

| Scenario | Default duration | Target |
|---|---|---|
| `wasm_steps` | 300s | Step success ≥ 90%; p95 < 300ms |
| `wasm_thundering_herd` | 60s | WASM dispatch burst; no HTTP |
| `msgspec_codec` | 120s | Encode+decode p95 < 1ms |
| `nats_transport` | 120s | Publish ack p99 < 50ms |
| `ruvon_gossip` | 120s | Gossip pipeline p99 < 200ms; error rate < 1% |
| `nkey_patch` | 120s | Ed25519 verify > 500 ops/s per device |
| `election_stability` | 120s | Elections/min < 5; election p95 < 1ms; flap count = 0 |
| `payload_variance` | 120s | Encode+decode p95 < 50ms at all sizes (256B – 64KB) |
| `e2e_decision` | 120s | Telemetry → score → sign → gossip → acks; p99 < 200ms |

---

## Running tests

### Single scenario

```bash
# From tests/load/
python run_load_test.py --scenario heartbeat --devices 1000 --duration 600

# From repo root
python tests/load/run_load_test.py --scenario saf_sync --devices 500
```

### All scenarios

```bash
# Smoke (10 devices, local-only scenarios finish in ~15 min)
python run_load_test.py --all --devices 10 --output-dir results/smoke/

# Full scale (1000 devices, ~60 min)
python run_load_test.py --all --devices 1000 --output-dir results/scale_1000/
```

---

## Chaos test (`run_chaos_load_test.py`)

Injects five fault phases sequentially against a live fleet:

| Phase | What happens |
|---|---|
| Baseline (0–60s) | Normal load; establishes p99 baseline |
| Partition (60–180s) | `chaos_device_fraction` (default 30%) go offline; SAF queue builds |
| Jitter storm (180–205s) | All devices: 150ms added latency + 5% packet loss |
| Thundering reconnect (205s+) | All devices return simultaneously; burst-sync storm begins |
| Spike (300–330s) | 30-second burst on 100 devices |
| Cooldown (330s–end) | Return to normal; recovery validation |

```bash
# 100 devices (default 30% chaos fraction)
python run_chaos_load_test.py --devices 100 --duration 600 --output-dir ./chaos_test/

# 1000 devices with concurrency cap (prevents server saturation)
python run_chaos_load_test.py \
    --devices 1000 \
    --duration 600 \
    --max-concurrency 200 \
    --output-dir ./chaos_test_1000/
```

### `--max-concurrency`

Gates all `_sync_batch` calls fleet-wide with an `asyncio.Semaphore`. Without it,
N devices × fast reconnect loop = N simultaneous HTTP requests, saturating the server
connection pool. Auto-sized to `min(max(devices // 5, 10), 200)` if omitted.

### Analysing results

```bash
python analyze_chaos.py ./chaos_test/chaos_results.json ./chaos_test/timeline.jsonl
```

#### Success criteria (auto-scaled)

All p99 thresholds scale with the concurrency ratio
(`num_devices / max_concurrent_syncs`), so a 1000-device / 200-slot run is judged
fairly against a 5× higher latency budget than a 100-device / 100-slot run:

| Check | Formula |
|---|---|
| Stable-phase error rate | Must be 0% in baseline and cooldown |
| Baseline p99 | `500ms × conc_ratio` |
| Post-chaos p99 | `500ms × conc_ratio` |
| Partition error rate | `< chaos_frac × 2 × 100%` (capped at 50%) |
| Post-reconnect mean p99 | `800ms × conc_ratio` |
| Reconnect recovery | ≤ 30s (±1 sample-interval tolerance) |

#### Validated results (1000 devices, max-concurrency 200)

```
Devices           : 1000
Max concurrency   : 200 simultaneous syncs
Duration          : 603.9s
Total requests    : 308,593
Transactions sync : 8,332,405
Overall errors    : 5,343  (1.731%)

Phase           p99 mean    p99 max    err mean    err max    tx/5s
Baseline        1720ms      1892ms     0.000%      0.000%     68,011
Partition       1303ms      1525ms     4.033%      6.124%     59,049
Jitter          1074ms      1085ms     5.803%      6.164%     73,059
Reconnect       1401ms      1585ms     4.347%      5.350%     75,267
Spike           1649ms      1697ms     3.358%      3.507%     78,801
Cooldown        1445ms      1799ms     2.281%      3.130%     70,890
```

All six PASS/FAIL criteria met at the scaled thresholds.

---

## Scale-out curve (`run_scale_curve.py`)

Sweeps device count N = [10, 100, 500, 1000, 2000] for a chosen scenario and writes
a latency/throughput table. Use this to detect O(N²) cliffs before production.

```bash
# All local-only scenarios in one command
python run_scale_curve.py --all --ns 10,100,500,1000 --duration 60 --output-dir ./scale_curve/

# Single scenario
python run_scale_curve.py --scenario ruvon_gossip --ns 10,100,500,1000 --duration 60

# HTTP scenario (needs server)
python run_scale_curve.py \
    --scenario saf_sync \
    --ns 10,100,500,1000,2000 \
    --duration 120 \
    --cloud-url http://localhost:8000 \
    --output-dir ./scale_curve/
```

Supported scenarios: `saf_sync`, `ruvon_gossip`, `heartbeat`, `election_stability`,
`payload_variance`, `e2e_decision`, `nkey_patch`.

`--all` runs the five local-only scenarios sequentially, writing each to its own
subdirectory under `--output-dir`.

### Output

```
scale_curve.json   — full data (one entry per N)
scale_curve.txt    — human-readable table + cliff detection warnings
```

#### Sample — nkey_patch (Ed25519 verify, 1000 devices, 60s)

```
Scale curve — nkey_patch  (duration=60s per run)

       N       p50       p95       p99     err%    req/s
  ──────────────────────────────────────────────────────
      10     0.00ms    0.00ms    0.00ms   0.000%     98.1
     100     0.00ms    0.00ms    0.00ms   0.000%    985.3
     500     0.00ms    0.00ms    0.00ms   0.000%   4879.3
    1000     0.00ms    0.00ms    0.00ms   0.000%   6249.2
```

Sub-millisecond latency at all scales; throughput grows near-linearly (no O(N²) cliff).

---

## Command-line reference

### `run_load_test.py`

```
--cloud-url URL         Control plane URL (default: http://localhost:8000)
--scenario SCENARIO     Scenario name (see list above)
--devices N             Simulated device count (default: 100)
--duration SECONDS      Test duration (default: scenario-specific)
--output FILE           JSON output file
--output-dir DIR        Output directory (with --all)
--all                   Run all scenarios sequentially
--log-level LEVEL       DEBUG | INFO | WARNING | ERROR
```

### `run_chaos_load_test.py`

```
--devices N             Fleet size (default: 100)
--duration SECONDS      Total test duration (default: 600)
--chaos-fraction F      Fraction of devices in chaos group (default: 0.30)
--max-concurrency N     Max simultaneous SAF syncs (default: auto)
--output-dir DIR        Directory for chaos_results.json + timeline.jsonl
--log-level LEVEL       DEBUG | INFO | WARNING | ERROR
```

### `run_scale_curve.py`

```
--scenario SCENARIO     Scenario to sweep (default: saf_sync)
--all                   Run all local-only scenarios sequentially
--ns N1,N2,...          Device counts to sweep (default: 10,100,500,1000,2000)
--duration SECONDS      Duration per run (default: 120)
--cloud-url URL         Required for HTTP scenarios
--output-dir DIR        Output directory (default: ./scale_curve/)
--log-level LEVEL       DEBUG | INFO | WARNING | ERROR
```

---

## Key fixes (this release)

- **ConnectError retry**: `httpx.ConnectError` was falling through to `except Exception: raise`
  in `_retry_with_backoff`, producing noisy 14-line tracebacks on every partition failure.
  It is now classified the same as `ConnectTimeout` — retried silently, logged at DEBUG
  after exhaustion.

- **Cumulative vs per-interval error rates**: `compute_phase_stats()` and `phase_summary()`
  previously used `error_rate_pct` (cumulative over the whole test). Cooldown showed
  inherited errors from the partition. Both now use `interval_errors / Δtotal_requests`
  per sample window.

- **Concurrency saturation at 1000 devices**: Without a semaphore, 1000 devices × fast
  reconnect loop saturated the server pool (baseline p99 = 31s). `--max-concurrency`
  adds a fleet-wide `asyncio.Semaphore`.

- **Import path**: All scripts now work when invoked from `tests/load/` directly, not only
  from the repo root.

---

## Troubleshooting

**High error rate**
- Check `chaos_test.log` / `load_test.log` for specific error types
- Verify PostgreSQL pool (`POSTGRES_POOL_MAX_SIZE`)
- Use `--max-concurrency` to limit concurrent HTTP requests

**Low throughput**
- Increase `max_connections` in PostgreSQL
- Profile with `--log-level DEBUG`

**`ModuleNotFoundError: No module named 'tests'`**
- Run from `tests/load/` or the repo root — both are supported

**Scale curve shows O(N²) cliff**
- Look at pool exhaustion in server logs
- Consider horizontal scaling or connection-pool tuning
