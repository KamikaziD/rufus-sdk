# How to install Rufus

This guide covers installing Rufus for different scenarios.

## Package structure (v0.6.0+)

Rufus ships as three separate wheels so each deployment target only installs what it needs:

| Package | Contents | Install command |
|---------|----------|----------------|
| `rufus-sdk` | Core engine + CLI | `pip install rufus-sdk` |
| `rufus-sdk-edge` | Edge agent (`rufus_edge`) | `pip install rufus-sdk-edge` |
| `rufus-sdk-server` | Cloud control plane (`rufus_server`) | `pip install rufus-sdk-server` |

`rufus-sdk-edge` and `rufus-sdk-server` each declare `rufus-sdk` as a dependency, so installing either sub-package also installs the core.

## Prerequisites

- Python 3.9 or higher
- pip package manager
- (Optional) Docker for containerized setup

## Installation paths

Choose the installation path that fits your needs:

### Path 1: Edge device install

Best for: POS terminals, ATMs, kiosks, and other resource-constrained hardware

```bash
# Minimal (offline payment, SAF queue, SQLite — ~25 MB on disk)
pip install rufus-sdk-edge

# With WebSocket commands + system health metrics (~40 MB)
pip install 'rufus-sdk-edge[edge]'
```

### Path 2: Cloud server install

Best for: Running the REST API + Celery workers in production

```bash
# REST API server
pip install 'rufus-sdk-server[server,auth]'

# Celery workers
pip install 'rufus-sdk-server[celery]'

# Everything (API + workers + auth)
pip install 'rufus-sdk-server[all]'
```

### Path 3: Core SDK only (SQLite)

Best for: Learning, prototyping, SDK development without server or edge agent

Install the SDK with SQLite support (no external database required):

```bash
# Clone repository
git clone https://github.com/your-org/rufus-sdk.git
cd rufus-sdk

# Install in development mode
pip install -e ".[postgres,performance,cli]"
pip install -e "packages/rufus-sdk-edge[edge]"
pip install -e "packages/rufus-sdk-server[server,celery,auth]"

# Install core dependencies
pip install aiosqlite orjson uvloop
```

Verify installation:

```bash
# Test CLI
rufus --help

# Test SDK import
python -c "from rufus.builder import WorkflowBuilder; print('✅ Rufus SDK ready!')"
```

Configure SQLite persistence:

```bash
rufus config set-persistence
# Choose: SQLite
# Database path: workflow.db

rufus db init
```

### Path 2: Docker with PostgreSQL

Best for: SDK development with production-like database

Start PostgreSQL in Docker:

```bash
cd docker
docker compose up postgres -d
```

Install SDK:

```bash
pip install -r requirements.txt
```

Initialize database with Alembic migrations:

```bash
cd src/rufus
export DATABASE_URL="postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud"
alembic upgrade head
```

Verify connection:

```python
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
import asyncio

async def test():
    p = PostgresPersistenceProvider('postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud')
    await p.initialize()
    workflows = await p.list_workflows()
    print(f'✅ PostgreSQL ready! Found {len(workflows)} workflows')
    await p.close()

asyncio.run(test())
```

### Path 3: Full stack with Docker Compose

Best for: Edge device development, full cloud control plane

Start all services:

```bash
cd docker
docker compose up -d
```

Verify services:

```bash
docker compose ps
# Expected: postgres (healthy), rufus-server (healthy)

curl http://localhost:8000/health
# Expected: {"status": "healthy"}
```

The database is automatically seeded with demo workflows and edge devices.

**Ports:**
- `8000` - Rufus API server
- `5433` - PostgreSQL database

## Optional dependencies

### Celery for distributed execution

```bash
pip install celery redis

# Start Redis
docker run -d --name redis-server -p 6379:6379 redis

# Start Celery worker
export DATABASE_URL="postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud"
export CELERY_BROKER_URL="redis://localhost:6379/0"
export CELERY_RESULT_BACKEND="redis://localhost:6379/0"

celery -A rufus.celery_app worker --loglevel=info
```

### PostgreSQL support

```bash
pip install asyncpg
```

### FastAPI server components

```bash
pip install fastapi uvicorn
```

## Verify installation

Run the SQLite demo:

```bash
cd examples/sqlite_task_manager
python simple_demo.py
```

Expected output:

```
======================================================================
  RUFUS SDK - SQLITE SIMPLE DEMO
======================================================================

🗄️  Using in-memory SQLite database

1. Initializing SQLite persistence...
   ✓ SQLite provider initialized

2. Creating a sample workflow...
   ✓ Workflow created: demo_workflow_001

[... more output ...]

======================================================================
  DEMO COMPLETED SUCCESSFULLY
======================================================================
```

## Common issues

### Import error: "No module named 'rufus'"

Install the SDK in editable mode:

```bash
pip install -e .
```

### Database schema missing

For PostgreSQL:

```bash
cd src/rufus
export DATABASE_URL="postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud"
alembic upgrade head
```

For SQLite (auto-creates schema):

```bash
rufus config set-persistence  # Choose SQLite
rufus db init
```

### Missing dependencies

Install all dependencies:

```bash
pip install aiosqlite orjson asyncpg uvloop
```

## Next steps

- [Create your first workflow](create-workflow.md)
- [Configure providers](configuration.md)
- [Test your installation](testing.md)

## Package footprint

As of v0.6.0 each wheel only ships the code you actually need:

| Wheel | On-disk size | Contents |
|-------|:-----------:|---------|
| `rufus-sdk` | ~2.5 MB | Core engine (`rufus/`) + CLI (`rufus_cli/`) |
| `rufus-sdk-edge` | ~250 KB | Edge agent (`rufus_edge/`) |
| `rufus-sdk-server` | ~9.5 MB | Cloud control plane (`rufus_server/`) |

**Total installed footprint** (wheel + core dependencies):

| Scenario | Command | Disk | RAM |
|----------|---------|:----:|:---:|
| Edge, minimal | `pip install rufus-sdk-edge` | ~15–20 MB | ~50 MB |
| Edge + WebSocket/metrics | `pip install 'rufus-sdk-edge[edge]'` | ~30–35 MB | ~65 MB |
| Edge + ONNX fraud scoring | above + `pip install onnxruntime` | ~80–600 MB* | ~115–165 MB |
| Cloud server (full) | `pip install 'rufus-sdk-server[all]'` | ~35–45 MB | — |

\* Varies by model file size. Model files are downloaded separately.

> For per-file breakdowns, hardware requirements, and footprint reduction tips see
> [Edge Device Package Footprint](../reference/configuration/edge-footprint.md).

## See also

- [Configuration guide](configuration.md)
- [Deployment guide](deployment.md)
- [Edge Device Package Footprint](../reference/configuration/edge-footprint.md)
- QUICKSTART.md for quick start instructions
