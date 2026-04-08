# ruvon-edge

**Offline-resilient workflow agent for edge devices.**

`ruvon-edge` is the device-side runtime for the [Ruvon](https://pypi.org/project/ruvon-sdk/) workflow engine. It runs full workflow orchestration on POS terminals, ATMs, mobile readers, kiosks, and industrial controllers — with or without network connectivity.

---

## What It Does

### Store-and-Forward (SAF)
Transactions queue locally in SQLite when the network is unavailable. When connectivity returns, the sync manager batches and forwards records to the cloud control plane with automatic retry and idempotency.

### ETag Config Push
The edge agent polls the cloud server using `If-None-Match`. Fraud rules, floor limits, and workflow definitions are hot-deployed without firmware updates or device restarts.

### Cryptographic Device Identity
NKey-based signing for every heartbeat and SAF batch. Tamper-evident audit trails at the device level.

### WASM Step Execution
Run sandboxed business logic modules compiled to WebAssembly. Supports both legacy WASI (stdin/stdout) and the Component Model typed interface. Modules are distributed by the cloud control plane and verified by NKey signature before execution.

### Gossip Mesh Coordination
Peer-to-peer coordination between edge devices on the same network segment. Includes capability scoring, local master election, and vector-based relay advisory — no central broker required for intra-fleet communication.

### Platform Adapters
The same Python code targets three runtimes:
- **Native CPython** — POS terminals, ATMs, Raspberry Pi
- **Pyodide** — Browser via WebAssembly (offline-capable web kiosks)
- **WASI 0.3** — Constrained embedded targets

---

## Installation

```bash
# Standard edge device (native CPython)
pip install 'ruvon-edge[edge]'

# With NATS JetStream mesh transport
pip install 'ruvon-edge[edge,nats]'

# Browser target (Pyodide — install inside micropip)
import micropip
await micropip.install('ruvon-edge')

# With Component Model WASM support
pip install 'ruvon-edge[native]'   # includes wasmtime
```

**Requires:** `ruvon-sdk>=0.1.0`

---

## Quick Start

```python
from ruvon_edge.agent import RuvonEdgeAgent

agent = RuvonEdgeAgent(
    device_id="pos-terminal-001",
    cloud_url="https://your-ruvon-server.example.com",
    api_key="your-api-key",
    db_path="edge.db",
)

await agent.start()
# Agent connects, polls for config, starts workflow execution loop
# Queues transactions locally if cloud is unreachable
```

### Register a Command Handler

```python
async def handle_update_workflow(command_data: dict):
    print(f"Received workflow update: {command_data['workflow_type']}")
    return True

agent.register_command_handler("update_workflow", handle_update_workflow)
```

### Run a Workflow on Device

```python
from ruvon_edge.agent import RuvonEdgeAgent
from ruvon.builder import WorkflowBuilder

# Workflows run on the device using SQLite persistence
workflow = builder.create_workflow("PaymentFlow", {"amount": 49.99})
workflow.start()
print(workflow.status)   # COMPLETED (local execution, no network needed)
```

---

## Architecture

```
┌────────────────────────────────────┐
│          RuvonEdgeAgent            │
│  ┌─────────────┐  ┌─────────────┐ │
│  │ SyncManager │  │ConfigManager│ │
│  │  (SAF/sync) │  │ (ETag poll) │ │
│  └──────┬──────┘  └──────┬──────┘ │
│         │                │        │
│  ┌──────▼────────────────▼──────┐ │
│  │   SQLite (WAL mode)          │ │
│  │   workflow_executions        │ │
│  │   saf_pending_transactions   │ │
│  │   edge_workflow_cache        │ │
│  │   device_config_cache        │ │
│  └──────────────────────────────┘ │
└────────────┬───────────────────────┘
             │ HTTPS / NATS (when online)
┌────────────▼───────────────────────┐
│       Ruvon Cloud Control Plane    │
│  POST /api/v1/devices/{id}/sync    │
│  GET  /api/v1/devices/{id}/config  │
│  GET  /api/v1/devices/{id}/commands│
└────────────────────────────────────┘
```

---

## Edge-Specific Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RUVON_DEVICE_ID` | — | Unique device identifier |
| `RUVON_CLOUD_URL` | — | Cloud control plane base URL |
| `RUVON_API_KEY` | — | Device authentication key |
| `RUVON_DB_PATH` | `edge.db` | SQLite database path |
| `RUVON_SYNC_INTERVAL` | `30` | SAF sync interval (seconds) |
| `RUVON_LOG_LEVEL` | `INFO` | Logging level |
| `RUVON_ENCRYPTION_KEY` | — | Fernet key for state encryption |
| `RUVON_NATS_URL` | — | NATS broker URL (enables mesh transport) |

---

## Offline Capabilities

| Scenario | Behaviour |
|----------|-----------|
| No network at startup | Agent starts with cached config; queues all transactions |
| Network lost mid-session | Seamless fallback to local queue; no data loss |
| Network restored | Automatic batch sync; idempotent retry on failure |
| Config update pushed | Hot-reload without restart |
| WASM module updated | Verified, patched, and applied at next execution |

---

## Related Packages

| Package | Purpose |
|---------|---------|
| [`ruvon-sdk`](https://pypi.org/project/ruvon-sdk/) | Core workflow engine (required dependency) |
| [`ruvon-server`](https://pypi.org/project/ruvon-server/) | Cloud control plane for fleet management |

---

## License

Apache 2.0
