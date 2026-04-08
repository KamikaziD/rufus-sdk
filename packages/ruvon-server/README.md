# ruvon-server

**Cloud control plane and fleet management for edge workflows.**

`ruvon-server` is the server-side runtime for the [Ruvon](https://pypi.org/project/ruvon-sdk/) workflow engine. It provides a production-grade REST API, device fleet management, distributed task execution, and a real-time observability dashboard — deployable in minutes with Docker.

---

## What It Does

### Device Fleet Management
Register, authenticate, and command an arbitrary number of edge devices. Push workflow definitions, fraud rules, and config updates to your entire fleet with a single API call. Monitor device heartbeats, sync status, and SAF transaction queues in real time.

### Transaction Settlement
Receive, validate, and settle Store-and-Forward transactions from offline edge devices. Full idempotency — duplicate submissions are safely deduplicated. Settlement results are pushed back to the originating device on its next sync.

### Distributed Task Execution
Celery-based worker pool with PostgreSQL task queue. Supports async steps, parallel fan-out, sub-workflows, and cross-worker state propagation. Workers auto-register with the fleet for visibility and command dispatch.

### RBAC + OIDC Authentication
Role-based access control with Keycloak or any OIDC provider. Fine-grained permissions across workflow management, device commands, audit access, and policy administration.

### Compliance Audit Log
Immutable, append-only audit trail for every workflow event across the fleet. Designed for 7-year retention. Queryable by device, workflow, step, actor, and time range.

### Real-Time Dashboard
Next.js 14 management UI with live device status, workflow execution graphs, SAF queue depth, Celery worker health, and a built-in DAG editor for workflow definitions.

### ETag Config Distribution
Efficiently push fraud rules and workflow definitions to edge devices. Devices poll with `If-None-Match`; the server responds `304 Not Modified` when nothing has changed — zero bandwidth waste on idle fleets.

---

## Installation

```bash
# Minimal server (API only)
pip install 'ruvon-server[server]'

# With Celery distributed workers
pip install 'ruvon-server[server,celery]'

# Full production stack (API + Celery + OIDC auth)
pip install 'ruvon-server[server,celery,auth]'

# With NATS JetStream transport
pip install 'ruvon-server[server,celery,auth,nats]'
```

**Requires:** `ruvon-sdk>=0.1.0`

---

## Quick Start — Docker Compose

```bash
git clone https://github.com/KamikaziD/ruvon-sdk.git
cd ruvon-sdk/docker
cp .env.example .env
# Edit .env: set RUVON_ENCRYPTION_KEY, POSTGRES_PASSWORD

docker compose up -d
```

Services start on:
- **API + Swagger** → `http://localhost:8000` / `http://localhost:8000/docs`
- **Dashboard** → `http://localhost:3000`
- **Flower (Celery monitor)** → `http://localhost:5555`

---

## Quick Start — Python

```python
# Run the FastAPI server directly
import uvicorn
from ruvon_server.main import app

uvicorn.run(app, host="0.0.0.0", port=8000)
```

```bash
# Or with uvicorn CLI
uvicorn ruvon_server.main:app --host 0.0.0.0 --port 8000 --reload

# Start a Celery worker
celery -A ruvon.celery_app worker --loglevel=info

# Start a region-specific worker
celery -A ruvon.celery_app worker -Q us-east-1 --loglevel=info
```

---

## API Overview

The server exposes 86+ REST endpoints across these resource groups:

| Group | Prefix | Description |
|-------|--------|-------------|
| Workflows | `/api/v1/workflows` | Create, resume, cancel, list executions |
| Devices | `/api/v1/devices` | Register, heartbeat, command, patch |
| SAF | `/api/v1/devices/{id}/sync` | Transaction sync and settlement |
| Config | `/api/v1/devices/{id}/config` | ETag-based config push |
| Commands | `/api/v1/devices/commands` | Broadcast and targeted device commands |
| Audit | `/api/v1/audit` | Query audit log |
| Metrics | `/api/v1/metrics` | Workflow throughput and latency |
| Workers | `/api/v1/workers` | Celery worker fleet |
| Policies | `/api/v1/policies` | Fraud rules and floor limits |
| Admin | `/api/v1/admin` | User management, RBAC |

Full interactive documentation: `http://localhost:8000/docs`

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                  Ruvon Server                        │
│                                                      │
│  FastAPI (86 endpoints)                              │
│  ├── Device Registry & Auth (RBAC/OIDC)              │
│  ├── ETag Config Distribution                        │
│  ├── SAF Settlement Gateway                          │
│  ├── Command Broadcast                               │
│  └── Compliance Audit Log                            │
│                                                      │
│  Celery Worker Pool                                  │
│  ├── Async Step Execution                            │
│  ├── Parallel Fan-out                                │
│  ├── Sub-workflow Dispatch                           │
│  └── Scheduled Workflows (Cron)                      │
└────────────────────┬─────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
   PostgreSQL      Redis       NATS
   (workflows,    (Celery     (optional
    audit, fleet)  broker)     mesh)
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RUVON_ENCRYPTION_KEY` | — | **Required.** Fernet key for state encryption |
| `RUVON_AUTH_PROVIDER` | `disabled` | Auth mode: `disabled`, `keycloak`, `jwt`, `api_key` |
| `RUVON_API_KEYS` | — | Comma-separated API keys (when `api_key` mode) |
| `RUVON_REGISTRATION_KEY` | `dev-registration-key` | Key required for device registration |
| `RUVON_WORKFLOW_REGISTRY_PATH` | `config/workflow_registry.yaml` | Path to workflow registry |
| `RUVON_CONFIG_DIR` | `config` | Directory containing workflow YAML files |
| `RUVON_CORS_ORIGINS` | `*` | Allowed dashboard origins |
| `DATABASE_URL` | — | PostgreSQL connection string |
| `REDIS_URL` | — | Redis connection string (Celery broker) |
| `RUVON_NATS_URL` | — | NATS URL (enables mesh transport) |
| `RUVON_HEARTBEAT_TIMEOUT_SECONDS` | `300` | Worker stale threshold |

---

## Production Deployment

### Docker (recommended)

```yaml
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
      - ./workflows:/app/workflows
    depends_on: [postgres, redis]
    command: celery -A ruvon.celery_app worker --loglevel=info

  ruvon-dashboard:
    image: ruvondev/ruvon-dashboard:0.1.0
    ports: ["3000:3000"]
    environment:
      NEXTAUTH_URL: http://localhost:3000
      KEYCLOAK_ISSUER: http://keycloak:8080/realms/ruvon
```

### Kubernetes

See `docker/kubernetes/` in the [ruvon-deploy](https://github.com/KamikaziD/ruvon-deploy) repository for Deployment, Service, ConfigMap, and Secret manifests.

---

## Related Packages

| Package | Purpose |
|---------|---------|
| [`ruvon-sdk`](https://pypi.org/project/ruvon-sdk/) | Core workflow engine (required dependency) |
| [`ruvon-edge`](https://pypi.org/project/ruvon-edge/) | Edge device agent |

---

## License

Apache 2.0
