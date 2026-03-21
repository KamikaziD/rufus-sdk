# Rufus — Sovereign Dispatcher Browser Demo 2

Demonstrates **N sovereign browser-devices**, each running WASM workflows locally,
heartbeating to the control plane, and draining their Store-and-Forward (SAF) queue
when connectivity is restored.

## What This Demo Shows

**The problem:** 100k edge devices each running local ML inference via WebAssembly.
Naïve implementation (100 independent `setTimeout` callbacks) saturates the JavaScript
event loop — "Page Unresponsive" dialogs, multi-second p99 latency, OOM.

**The solution:** the Rufus **Sovereign Dispatcher** — devices run in a Web Worker
background thread; a batch queue ("Brain Pool") drains 1,000 devices per flush.
Result: p99 < 50ms at 100,000 devices, 60fps UI, no freezes.

**The offline story:** when the control plane is unreachable, each device queues
transactions locally (Store-and-Forward / SAF). On reconnect, all queued transactions
sync in one batch — "supersonic SAF".

## Architecture

```
BROWSER TAB (Main Thread)               DOCKER STACK (optional)
├── Canvas heatmap (1px = 1 device)     ├── rufus-server :8000 (control plane)
├── Stats ticker (steps/sec, p99)       ├── rufus-dashboard :3000
└── Network cut / restore controls      ├── rufus-edge-sim  (POS device)
         │ postMessage                   └── rufus-atm-sim   (ATM device)
         ▼
WEB WORKER (Background Thread)
├── Device loop × N  (heartbeat + WASM + SAF state machine)
├── Staggered registration (batches of 10, 200ms apart)
└── fetch() → localhost:8000 (when reachable + networkUp)
```

## Quick Start — Simulation Mode (no server needed)

```bash
cd examples/browser_demo_2
python serve.py
# Open http://localhost:8082
```

1. Click **▶ Start** — pixel heatmap fills green in ~10s (Sovereign mode, 60fps)
2. Click **⚡ Cut Network** — pixels turn amber as SAF queues build
3. Click **🔄 Restore Network** — blue sync wave sweeps to green (supersonic SAF)
4. Enable **Legacy Mode** checkbox then **▶ Start** — browser tab freezes

## Connected Mode — Sync with Control Plane

```bash
# Start the full Docker stack
docker compose -f /Users/kim/PycharmProjects/rufus_test/docker-compose.test-async.yml up -d

cd examples/browser_demo_2
python serve.py
# Open http://localhost:8082 — "Connected ✓" badge appears
```

Devices will register and appear at `http://localhost:3000/devices`.

## Network Condition Simulation (Container-to-Container)

```bash
# Degraded link for POS simulator
EDGE_NETWORK_CONDITION=degraded docker compose \
  -f /Users/kim/PycharmProjects/rufus_test/docker-compose.test-async.yml \
  up -d --force-recreate rufus-edge-sim

# Auto-cycling conditions for ATM simulator
ATM_NETWORK_CONDITION=auto docker compose \
  -f /Users/kim/PycharmProjects/rufus_test/docker-compose.test-async.yml \
  up -d --force-recreate rufus-atm-sim
```

Available profiles: `perfect` | `good` (default) | `lan` | `wan` | `degraded` | `flaky` | `offline` | `auto`

## Benchmark Numbers

| Metric                        | Legacy (main thread) | Sovereign Dispatcher |
|-------------------------------|----------------------|----------------------|
| 1k devices × 5 WASM steps     | p99 = 5,055ms        | p99 = 8ms (**609×**) |
| 100k devices × 5 steps        | OOM / crash          | 32,565 steps/sec     |
| UI framerate during 100k run  | 0 fps (frozen)       | 60 fps (smooth)      |

## Pixel Color Key

| Color  | State               |
|--------|---------------------|
| Deep blue | Idle (startup)   |
| Green  | Online + synced     |
| Red    | WASM step executing |
| Purple | Workflow complete   |
| Amber  | Offline / SAF queued|
| Blue   | Syncing SAF         |
| Teal   | Synced              |

## Mapping to Production SDK

| Browser Demo Concept         | SDK Component                                    |
|------------------------------|--------------------------------------------------|
| Web Worker batch flush        | `ComponentStepRuntime.execute_batch()`           |
| SAF queue                    | `SyncManager.queue_for_sync()` + `sync_all_pending()` |
| Device state machine          | `RufusEdgeAgent` heartbeat + reconnect loops     |
| NetworkConditionSimulator     | `examples/edge_deployment/network_simulator.py`  |
| Control plane endpoints       | Same API as Docker edge simulators               |

## Troubleshooting

**"Connected ✗" / grey badge:** The Docker stack is not running, or `rufus-server` is
not yet healthy. The demo works fully in simulation mode without a server.

**CORS error in browser console:** Ensure `RUFUS_CORS_ORIGINS` in docker-compose
includes `http://localhost:8082`. The current `docker-compose.test-async.yml` already
includes it.

**SAF transactions not appearing in dashboard:** The demo SAF sync uses
`hmac: "browser-demo-hmac"`. If the server rejects it, SAF syncs will fail silently
and devices will remain in SAF_QUEUED state — expected in strict HMAC mode.
