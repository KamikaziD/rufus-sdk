# Ruvon — Workflow Runtime for Edge and Cloud

**Describe it. Run it. Scale it.**

Ruvon is a Python workflow engine built around provider-based dependency injection. The same SDK runs on a constrained edge device (SQLite, offline-first) and on a cloud control plane (PostgreSQL, Celery, distributed) — different backends, identical step functions and YAML definitions.

```
DEVICE RUNTIME   │  CLOUD WORKER  │  CONTROL PLANE  │  DASHBOARD
SQLite / WAL     │  PostgreSQL    │  PostgreSQL      │  Next.js 14
SyncExecution    │  Celery        │  Celery          │  Keycloak RBAC
Offline-first    │  Horizontal    │  Fleet & policy  │  9-page UI
```

---

## Deployment Contexts

- **Point-of-sale & payment terminals** — offline transaction queuing with store-and-forward
- **Robotics & autonomous systems** — deterministic mission plans that survive connectivity loss
- **Medical devices & wearables** — air-gapped procedure logs with guaranteed local persistence
- **Industrial IoT & factory automation** — local processing and ML inference without cloud dependency
- **Field operations & logistics** — resilient mobile workflows with automatic sync on reconnect
- **Any environment** where local execution, intermittent connectivity, or fleet management matters

---

## The Ecosystem

Ruvon ships as five composable layers. Deploy only what you need.

| Layer | Package | Runtime | Purpose |
|-------|---------|---------|---------|
| **Core SDK** | `ruvon-sdk` | Any Python app | Workflow engine, providers, 11 step types |
| **CLI** | `ruvon-sdk` | Terminal | Local run / validate / manage |
| **Edge Agent** | `ruvon-edge` | Device (SQLite) | Offline-first runtime, SAF, config sync |
| **Cloud Server** | `ruvon-server` | Docker / K8s | REST API, fleet commands, 86 endpoints |
| **Dashboard** | bundled in server | Docker / K8s | Management UI, RBAC, DAG editor |

---

## Quick Start — Docker Compose (30 seconds)

```bash
git clone https://github.com/KamikaziD/ruvon-sdk.git
cd ruvon-sdk/docker
cp .env.example .env   # Set RUVON_ENCRYPTION_KEY
docker compose up -d
```

Or use the published images directly:

```yaml
# docker-compose.yml
services:
  ruvon-server:
    image: ruvondev/ruvon-server:0.1.0
    env_file: .env
    ports: ["8000:8000"]
    depends_on: [postgres, redis]

  ruvon-worker:
    image: ruvondev/ruvon-worker:0.1.0
    env_file: .env
    volumes:
      - ./my_workflows:/app/workflows
    depends_on: [postgres, redis]

  ruvon-flower:
    image: ruvondev/ruvon-flower:0.1.0
    ports: ["5555:5555"]

  ruvon-dashboard:
    image: ruvondev/ruvon-dashboard:0.1.0
    ports: ["3000:3000"]
    environment:
      NEXTAUTH_URL: http://localhost:3000
      NEXTAUTH_SECRET: change-me-in-production
      KEYCLOAK_ISSUER: http://localhost:8080/realms/ruvon
      KEYCLOAK_ID: ruvon-dashboard
      KEYCLOAK_SECRET: your-keycloak-secret
    depends_on: [ruvon-server]

  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: ruvon
      POSTGRES_PASSWORD: secret
      POSTGRES_DB: ruvon_cloud

  redis:
    image: redis:7-alpine
```

API at `http://localhost:8000` · Swagger UI at `http://localhost:8000/docs` · Dashboard at `http://localhost:3000` · Flower at `http://localhost:5555`

---

## 5-Minute Tutorial

```bash
pip install ruvon-sdk
```

```python
from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider
from ruvon.implementations.execution.sync import SyncExecutor
from ruvon.builder import WorkflowBuilder

def validate_payment(state, context, **_):
    return {"validated": True}

def process_charge(state, context, **_):
    print(f"Charging ${state.amount}")
    return {"charged": True, "txn_id": "txn_abc123"}

builder = WorkflowBuilder(
    persistence_provider=SQLitePersistenceProvider(db_path=":memory:"),
    execution_provider=SyncExecutor(),
)
builder.register_workflow_inline("Payment", steps=[
    {"name": "Validate", "type": "STANDARD", "function": validate_payment},
    {"name": "Charge",   "type": "STANDARD", "function": process_charge},
])

workflow = builder.create_workflow("Payment", {"amount": 49.99})
workflow.start()
print(workflow.status)   # COMPLETED
```

Or run a complete example:

```bash
python examples/payment_terminal/terminal_simulator.py
python examples/loan_application/run_loan_workflow.py

# Browser demo (no Python install needed — runs entirely in-browser via Pyodide)
python -m http.server 8080   # then open http://localhost:8080/examples/browser_demo/
```

---

## Architecture

### Three Roles, One SDK

```
┌────────────────────────────────────────────────────────────────┐
│                        Ruvon SDK (Core)                        │
│         WorkflowBuilder · Workflow · Providers · Steps         │
└─────────────┬──────────────────┬──────────────────┬───────────┘
              │                  │                  │
   ┌──────────▼──────┐  ┌───────▼────────┐  ┌─────▼──────────┐
   │  Device Runtime  │  │  Cloud Worker  │  │ Control Plane  │
   │  SQLite / WAL    │  │  PostgreSQL    │  │  PostgreSQL    │
   │  SyncExecution   │  │  Celery        │  │  Celery        │
   │  Offline-first   │  │  Distributed   │  │  Fleet mgmt    │
   └──────────────────┘  └────────────────┘  └────────────────┘
```

### Cloud Control Plane ↔ Edge Device

```
CLOUD                               EDGE (SQLite)
├── Ruvon Dashboard (port 3000)     ├── RuvonEdgeAgent
│   └── Keycloak RBAC               ├── SyncManager (SAF)
├── REST API (port 8000)   <──>     ├── ConfigManager (ETag)
│   ├── Device Registry             └── Local Workflows
│   ├── Worker Fleet Commands
│   ├── Workflow Definitions
│   └── Audit & Policies
└── Celery Workers (Redis)
```

### Step Types (11 built-in)

| Type | Description |
|------|-------------|
| `STANDARD` | Synchronous function execution |
| `ASYNC` | Long-running task via Celery or thread pool |
| `DECISION` | Conditional branching with `WorkflowJumpDirective` |
| `PARALLEL` | Concurrent tasks with configurable merge strategy |
| `HTTP` | Call external services — Go, Rust, Node.js (polyglot) |
| `LOOP` | Iterate over collections or poll until condition |
| `FIRE_AND_FORGET` | Non-blocking async for notifications/audit |
| `CRON_SCHEDULE` | Scheduled recurring execution |
| `HUMAN_IN_LOOP` | Pause workflow for manual approval |
| `AI_INFERENCE` | On-device ML inference — TFLite, ONNX, or shard-paged LLM |
| `WASM` | Execute a WebAssembly binary via WASI or Component Model |

### Provider Pattern

```python
builder = WorkflowBuilder(
    persistence_provider=SQLitePersistenceProvider("device.db"),    # or PostgreSQL
    execution_provider=CeleryExecutionProvider(broker_url="..."),   # or Sync
    observer=LoggingObserver(),
)
```

---

## Key Features

### Store-and-Forward (Edge)
Payments and transactions queue locally when offline. Automatic sync when connectivity returns. Cryptographic HMAC signing for tamper-evident records.

### Saga Compensation
Define a `compensate_function` per step. On failure, compensations run in reverse order. Status becomes `FAILED_ROLLED_BACK`. No saga coordinator required.

```yaml
steps:
  - name: ReserveInventory
    type: STANDARD
    function: steps.reserve_inventory
    compensate_function: steps.release_inventory
  - name: ChargeCard
    type: STANDARD
    function: steps.charge_card
    compensate_function: steps.refund_card
```

### ETag Config Push
Push fraud rules and workflow definitions to your entire device fleet without firmware updates. Edge devices poll with `If-None-Match`; the server responds with `304 Not Modified` when nothing changed.

### AI Workflow Builder
Describe what you need in plain English. Ruvon generates the YAML.

```bash
ruvon build generate "handle incoming loan applications with credit check and human approval"
```

### Zombie Recovery
Worker crashes leave workflows stuck in `RUNNING`. Ruvon's heartbeat system detects stale workers and marks them `FAILED_WORKER_CRASH` automatically.

```bash
ruvon scan-zombies --fix
ruvon zombie-daemon --interval 60
```

---

## CLI

```bash
# Workflow management
ruvon list --status ACTIVE
ruvon start PaymentWorkflow --data '{"amount": 49.99}'
ruvon show <workflow-id> --state --logs
ruvon resume <workflow-id> --input '{"approved": true}'
ruvon cancel <workflow-id>

# Local development
ruvon validate workflow.yaml --strict
ruvon run workflow.yaml --data '{"key": "value"}'

# AI builder
ruvon build generate "describe your workflow"
ruvon build interactive

# Database
ruvon db init
ruvon db migrate
ruvon db status
```

---

## Installation

```bash
# Core SDK + CLI
pip install ruvon-sdk

# With PostgreSQL support
pip install 'ruvon-sdk[postgres]'

# With performance optimizations (uvloop, orjson)
pip install 'ruvon-sdk[postgres,performance]'

# Edge device runtime
pip install 'ruvon-edge[edge]'

# Cloud control plane
pip install 'ruvon-server[server,celery,auth]'
```

---

## Related Packages

| Package | PyPI | Purpose |
|---------|------|---------|
| `ruvon-sdk` | [pypi.org/project/ruvon-sdk](https://pypi.org/project/ruvon-sdk/) | Core engine + CLI |
| `ruvon-edge` | [pypi.org/project/ruvon-edge](https://pypi.org/project/ruvon-edge/) | Edge device agent |
| `ruvon-server` | [pypi.org/project/ruvon-server](https://pypi.org/project/ruvon-server/) | Cloud control plane |

---

## License

Apache 2.0 — see [LICENSE](LICENSE)
