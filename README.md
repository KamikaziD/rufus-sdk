# Rufus — Workflow Runtime for Edge and Cloud

Rufus is a Python workflow engine built around provider-based dependency injection. The same SDK runs on a constrained edge device (SQLite, offline-first) and on a cloud control plane (PostgreSQL, Celery, distributed) — different backends, identical step functions and YAML definitions.

```
DEVICE RUNTIME   │  CLOUD WORKER  │  CONTROL PLANE  │  DASHBOARD
SQLite / WAL     │  PostgreSQL    │  PostgreSQL      │  Next.js 14
SyncExecution    │  Celery        │  Celery          │  Keycloak RBAC
Offline-first    │  Horizontal    │  Fleet & policy  │  9-page UI
```

---

## Deployment Contexts

- **Robotics & autonomous systems** — deterministic mission plans that survive connectivity loss
- **Medical devices & wearables** — air-gapped procedure logs with guaranteed local persistence
- **Industrial IoT & factory automation** — local processing and ML inference without cloud dependency
- **Field operations & logistics** — resilient mobile workflows with automatic sync on reconnect
- **Point-of-sale & payment terminals** — offline transaction queuing with store-and-forward
- **Any environment** where local execution, intermittent connectivity, or fleet management matters

---

## The Ecosystem

Rufus ships as five composable layers. Deploy only what you need.

| Layer | Package | Runtime | Purpose |
|-------|---------|---------|---------|
| **Core SDK** | `rufus-sdk` | Any Python app | Workflow engine, providers, 11 step types |
| **CLI** | `rufus-sdk` | Terminal | Local run / validate / manage |
| **Edge Agent** | `rufus-sdk-edge` | Device (SQLite) | Offline-first runtime, SAF, config sync |
| **Cloud Server** | `rufus-sdk-server` | Docker / K8s | REST API, fleet commands, 86 endpoints |
| **Dashboard** | `rufus-dashboard` | Docker / K8s | Management UI, RBAC, DAG editor |

---

## Quick Start — Docker Compose (30 seconds)

```bash
git clone https://github.com/KamikaziD/rufus-sdk.git
cd rufus-sdk/docker
cp .env.example .env   # Set RUFUS_ENCRYPTION_KEY
docker compose up -d
```

Or use the published images directly:

```yaml
# docker-compose.yml
services:
  rufus-server:
    image: ruhfuskdev/rufus-server:1.0.0rc2
    env_file: .env
    ports: ["8000:8000"]
    depends_on: [postgres, redis]

  rufus-worker:
    image: ruhfuskdev/rufus-worker:1.0.0rc2
    env_file: .env
    volumes:
      - ./my_workflows:/app/workflows
    depends_on: [postgres, redis]

  rufus-flower:
    image: ruhfuskdev/rufus-flower:1.0.0rc2
    ports: ["5555:5555"]

  rufus-dashboard:
    image: ruhfuskdev/rufus-dashboard:1.0.0rc2
    ports: ["3000:3000"]
    environment:
      NEXTAUTH_URL: http://localhost:3000
      NEXTAUTH_SECRET: change-me-in-production
      KEYCLOAK_ISSUER: http://localhost:8080/realms/rufus
      KEYCLOAK_ID: rufus-dashboard
      KEYCLOAK_SECRET: your-keycloak-secret
    depends_on: [rufus-server]

  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: rufus
      POSTGRES_PASSWORD: secret
      POSTGRES_DB: rufus_cloud

  redis:
    image: redis:7-alpine
```

API at `http://localhost:8000` · Swagger UI at `http://localhost:8000/docs` · Dashboard at `http://localhost:3000` · Flower at `http://localhost:5555`

---

## 5-Minute Tutorial

```bash
pip install --index-url https://test.pypi.org/simple/ rufus-sdk==1.0.0rc2
```

```python
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.execution.sync import SyncExecutor
from rufus.builder import WorkflowBuilder

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
python examples/healthcare_wearable/device_simulator.py

# Browser demo (no Python install needed — runs entirely in-browser)
python -m http.server 8080   # then open http://localhost:8080/examples/browser_demo/
```

---

## Architecture

### Three Roles, One SDK

```
┌────────────────────────────────────────────────────────────────┐
│                         Rufus SDK (Core)                       │
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
├── Rufus Dashboard (port 3000)     ├── RufusEdgeAgent
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
| `AI_INFERENCE` | On-device ML inference — TFLite, ONNX, or shard-paged LLM via `PagedInferenceRuntime` |
| `WASM` | Execute a WebAssembly binary — WASI stdin/stdout (core) or Component Model typed interface (v0.8.0) |

### Provider Pattern

```python
builder = WorkflowBuilder(
    persistence_provider=SQLitePersistenceProvider("device.db"),    # or PostgreSQL
    execution_provider=CeleryExecutionProvider(broker_url="..."),   # or Sync
    observer=LoggingObserver(),
)
```

---

## Rufus Dashboard

The dashboard is a 9-page management UI that ships as `ruhfuskdev/rufus-dashboard:0.8.0`. It connects to the REST API and provides role-based access to every aspect of a Rufus deployment.

### Pages

| Page | Who | What you can do |
|------|-----|-----------------|
| **Overview** | All roles | Live KPI cards: active workflows, online workers, pending approvals, device count |
| **Workflows** | Operator+ | List, filter, start, resume, cancel, retry; debug step-through with DAG view; audit trail |
| **Approvals** | Operator+ | `HUMAN_IN_LOOP` approval queue; approve or reject with notes |
| **Devices** | Fleet Mgr+ | Device registry; per-device status, last heartbeat, command history |
| **Workers** | Fleet Mgr+ | Celery worker fleet; 9 command types (restart, drain, update\_code…); broadcast to fleet |
| **Policies** | Admin / Fleet Mgr | Fraud rules and config policy CRUD |
| **Schedules** | Admin / Operator | Cron-based workflow scheduling |
| **Audit** | Admin / Auditor | Full compliance log; export to JSON |
| **Admin** | SUPER\_ADMIN only | Live workflow definitions (YAML upload, ReactFlow DAG editor, push to devices), server commands |

### Role-Based Access Control

Five roles map to least-privilege access across all pages:

| Role | Access |
|------|--------|
| `SUPER_ADMIN` | Everything — Admin panel, policy management, server commands |
| `FLEET_MANAGER` | Devices, Workers, Policies (read), Schedules |
| `WORKFLOW_OPERATOR` | Workflows, Approvals, Schedules, Workers (read) |
| `AUDITOR` | Workflows (read), Devices (read), Audit log, Policies (read) |
| `READ_ONLY` | Workflows and Devices (read-only) |

Roles are assigned in Keycloak (or any OIDC provider) and propagated via JWT claims on every API request.

### Admin Panel — Live Workflow Updates (v0.7.4)

The Admin panel's **Server** tab unlocks live workflow management without redeployment:

- **Upload or edit YAML inline** — paste a new workflow definition or edit an existing one
- **ReactFlow DAG preview** — see the execution graph update as you type; DECISION step conditions are editable in a side panel without touching raw YAML
- **Push to Devices** — broadcasts the updated YAML to the entire edge fleet instantly via the `update_workflow` server command
- **Server commands** — trigger `reload_workflows`, `gc_caches`, `update_code`, or `restart` across all connected workers from the UI

See [Dashboard Guide](docs/how-to-guides/dashboard.md) for deploy instructions, environment variables, and a step-by-step live-update walkthrough.

---

## Key Features

### Offline-First Architecture
- SQLite with WAL mode — data survives restarts and power loss
- Store-and-Forward (SAF) queues transactions when offline; syncs on reconnect
- Workflows resume from exactly where they stopped, no cloud check-in required
- ETag-based config push — hot-deploy fraud rules or workflow updates without firmware

### Production Reliability
- **Saga Pattern** — automatic compensation (rollback) on any step failure
- **Zombie Recovery** — heartbeat-based detection of crashed workers, auto-recovery
- **Workflow Versioning** — YAML definition snapshots protect running workflows from updates
- **Idempotent Operations** — safe retries without duplicate effects

### Distributed Execution
- Celery workers with Redis broker for horizontal scaling
- Parallel step execution across multiple workers
- Sub-workflow hierarchies with parent status bubbling
- Human-in-the-loop with resume from any step

### Observability
- **Rufus Dashboard** at `http://localhost:3000` — 9-page management UI with role-based access
- Grouped Swagger UI at `/docs` (14 tag groups, 86 endpoints)
- Flower monitoring at port 5555
- Audit log table captures every workflow event
- CLI metrics: `rufus metrics`, `rufus logs <id>`

### Polyglot Execution
- **HTTP steps** — orchestrate services written in Go, Rust, Node.js, or any language via REST
- **WASM steps** — run pre-compiled WebAssembly binaries via WASI stdin/stdout or the Component Model typed interface; runs natively, in-browser (Pyodide), or as a compiled WASI 0.3 target (requires `wasmtime>=15.0`)
- **AI_INFERENCE steps** — on-device ML inference via TFLite, ONNX, or `PagedInferenceRuntime` (shard-paged LLM for browser + edge devices with <300 MB RAM budget)

### Browser PWA — Pyodide + WebGPU
- **Live demo** (`examples/browser_demo/`) — 6 demo workflows running in-browser via Pyodide + Transformers.js (WebGPU); no server required; installable as a PWA
- `python -m http.server 8080` from repo root → `http://localhost:8080/examples/browser_demo/`
- Workflow 6: Paged Reasoning — Q2_K / Q3_K_S model selector, logic-gate fast path (shard-0 only, ~1.5s), full paged inference (rolling 2-shard OPFS window, ~260 MB peak), live token streaming

### Performance
- uvloop — 2–4× faster async I/O
- orjson — 3–5× faster JSON serialization
- 162× import cache speedup
- Tunable PostgreSQL connection pool (default: min=10, max=50)

---

## Use Cases

### Saga Pattern — Compensatable Steps

```yaml
steps:
  - name: "Reserve_Inventory"
    type: "STANDARD"
    function: "inventory.reserve"
    compensate_function: "inventory.release"   # Auto-rollback on failure

  - name: "Charge_Payment"
    type: "STANDARD"
    function: "payments.charge"
    compensate_function: "payments.refund"
```

### Autonomous Systems — Parallel Sensor Fusion

```yaml
- name: "Sensor_Fusion"
  type: "PARALLEL"
  tasks:
    - name: "GPS_Fix"
      function: "sensors.gps_reading"
    - name: "LiDAR_Scan"
      function: "sensors.lidar_sweep"
    - name: "Camera_Frame"
      function: "sensors.camera_capture"
  merge_strategy: "SHALLOW"
```

### MedTech — Sterile Procedure Log (Air-Gapped)

```yaml
- name: "Log_Procedure_Step"
  type: "LOOP"
  mode: "ITERATE"
  iterate_over: "state.procedure_checklist"
  loop_body:
    - name: "Record_Step"
      type: "STANDARD"
      function: "audit.record_step"
    - name: "Verify_Complete"
      type: "DECISION"
      routes:
        - condition: "state.step_verified == False"
          target: "Alert_Surgeon"
```

### Polyglot — Multi-Language Pipeline

```yaml
steps:
  - name: "Validate"
    type: "STANDARD"
    function: "steps.validate"

  - name: "Process_Go"
    type: "HTTP"
    http_config:
      url: "http://go-processor:8080/process"
      method: "POST"
      body: "{{state.validated_data}}"

  - name: "Predict_Rust"
    type: "HTTP"
    http_config:
      url: "http://rust-ml:8080/predict"
      body: "{{state.features}}"
```

---

## Documentation

Rufus follows the [Diátaxis](https://diataxis.fr/) framework:

### Getting Started

| Document | Description |
|----------|-------------|
| [Getting Started Tutorial](docs/tutorials/getting-started.md) | First workflow in 5 minutes |
| [Edge Device Deployment](docs/tutorials/edge-deployment.md) | Deploy to real hardware |
| [Example Learning Path](examples/README.md) | 8 progressive examples |

### How-To Guides

| Guide | Use When |
|-------|----------|
| [Installation](docs/how-to-guides/installation.md) | SQLite, PostgreSQL, or Docker setup |
| [Create Workflow](docs/how-to-guides/create-workflow.md) | Build a workflow from scratch |
| [Saga Mode](docs/how-to-guides/saga-mode.md) | Compensation and rollback |
| [Human-in-the-Loop](docs/how-to-guides/human-in-loop.md) | Manual approval steps |
| [Deployment](docs/how-to-guides/deployment.md) | Docker / Kubernetes |
| [Dashboard Guide](docs/how-to-guides/dashboard.md) | Deploy, log in, navigate, manage fleet |

### Reference

| Reference | Contains |
|-----------|----------|
| [YAML Schema](docs/reference/configuration/yaml-schema.md) | Complete workflow YAML spec |
| [Step Types](docs/reference/configuration/step-types.md) | All 11 step types |
| [Database Schema](docs/reference/configuration/database-schema.md) | 34 cloud + 12 edge tables |
| [Configuration](docs/reference/configuration/configuration.md) | All environment variables |
| [CLI Commands](docs/reference/configuration/cli-commands.md) | All 26 CLI commands |

### Explanation

| Topic | Learn About |
|-------|-------------|
| [Architecture](docs/explanation/architecture.md) | System design and three roles |
| [Self-Hosting](docs/explanation/self-hosting.md) | Rufus orchestrates itself |
| [Zombie Recovery](docs/explanation/zombie-recovery.md) | Worker crash handling |
| [Workflow Versioning](docs/explanation/workflow-versioning.md) | YAML snapshots |
| [Performance](docs/explanation/performance.md) | uvloop, orjson, pooling |

### Advanced Topics

| Topic | Read Before |
|-------|-------------|
| [Executor Portability](docs/advanced/executor-portability.md) | CRITICAL: Stateless step functions |
| [Custom Providers](docs/advanced/custom-providers.md) | Building custom persistence/execution |
| [Extending Rufus](docs/advanced/extending-rufus.md) | Custom tables, custom routers |
| [Security](docs/advanced/security.md) | PCI-DSS, encryption, device auth |

### Appendices

- [Changelog](docs/appendices/changelog.md) — v0.1.0 → v1.0.0rc2
- [Roadmap](docs/appendices/roadmap.md)
- [Migration Notes](docs/appendices/migration-notes.md)
- [Glossary](docs/appendices/glossary.md)

---

## CLI Quick Reference

```bash
# Configuration
rufus config show                # Show current configuration
rufus config set-persistence     # Choose database (SQLite/PostgreSQL)
rufus config set-execution       # Choose executor (sync/thread_pool/celery)

# Workflow management
rufus list                       # List workflows
rufus start <workflow-type>      # Start a workflow
rufus show <workflow-id>         # Show details + state
rufus resume <workflow-id>       # Resume paused workflow
rufus cancel <workflow-id>       # Cancel running workflow
rufus logs <workflow-id>         # View execution logs

# Database
alembic upgrade head             # Apply migrations (PostgreSQL)
rufus db init                    # Initialize SQLite schema

# Zombie recovery
rufus scan-zombies --fix         # Detect and recover crashed workflows
rufus zombie-daemon              # Continuous monitoring daemon
```

---

## Testing

```bash
pytest tests/sdk/ -v

# Integration tests (requires Docker)
cd tests/integration
docker compose up -d
pytest test_celery_execution.py -v
```

---

## Contributing

See [Contributing Guide](docs/appendices/contributing.md) for code of conduct, development setup, coding standards (PEP 8, type hints), testing requirements, and PR process.

---

## License

MIT License — See [LICENSE](LICENSE) file for details.

---

## Distribution

**Docker Hub:** `ruhfuskdev/rufus-server:1.0.0rc2` · `ruhfuskdev/rufus-worker:1.0.0rc2` · `ruhfuskdev/rufus-flower:1.0.0rc2` · `ruhfuskdev/rufus-dashboard:1.0.0rc2`

> Dashboard auth requires Keycloak (included in `docker/docker-compose.keycloak.yml`) or any OIDC provider configured via `KEYCLOAK_ISSUER`, `KEYCLOAK_ID`, and `KEYCLOAK_SECRET`.

**TestPyPI:**
```bash
pip install --index-url https://test.pypi.org/simple/ rufus-sdk==1.0.0rc2

# Optional extras
pip install 'rufus-sdk[wasm]'                  # WASM steps (wasmtime>=15.0)
pip install 'rufus-sdk[otel]'                  # OpenTelemetry tracing (OtelObserver)
pip install 'rufus-sdk-edge[browser]'          # Browser target (Pyodide + wa-sqlite)
pip install 'rufus-sdk-edge[wasi]'             # WASI 0.3 compiled target
```

---

**Current Version:** v1.0.0rc2
**Support:** 📖 [Documentation](docs/index.md) · 💬 [Discussions](https://github.com/KamikaziD/rufus-sdk/discussions) · 🐛 [Issues](https://github.com/KamikaziD/rufus-sdk/issues)
