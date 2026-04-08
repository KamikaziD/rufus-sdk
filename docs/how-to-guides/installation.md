# How to install Ruvon

This guide covers installing Ruvon for different scenarios.

## Package structure (v0.6.0+)

Ruvon ships as three separate wheels so each deployment target only installs what it needs:

| Package | Contents | Install command |
|---------|----------|----------------|
| `ruvon-sdk` | Core engine + CLI | `pip install ruvon-sdk` |
| `ruvon-edge` | Edge agent (`ruvon_edge`) | `pip install ruvon-edge` |
| `ruvon-server` | Cloud control plane (`ruvon_server`) | `pip install ruvon-server` |

`ruvon-edge` and `ruvon-server` each declare `ruvon-sdk` as a dependency, so installing either sub-package also installs the core.

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
pip install ruvon-edge

# With WebSocket commands + system health metrics (~40 MB)
pip install 'ruvon-edge[edge]'
```

### Path 2: Cloud server install

Best for: Running the REST API + Celery workers in production

```bash
# REST API server
pip install 'ruvon-server[server,auth]'

# Celery workers
pip install 'ruvon-server[celery]'

# Everything (API + workers + auth)
pip install 'ruvon-server[all]'
```

### Path 3: Core SDK only (SQLite)

Best for: Learning, prototyping, SDK development without server or edge agent

Install the SDK with SQLite support (no external database required):

```bash
# Clone repository
git clone https://github.com/your-org/ruvon-sdk.git
cd ruvon-sdk

# Install in development mode
pip install -e ".[postgres,performance,cli]"
pip install -e "packages/ruvon-edge[edge]"
pip install -e "packages/ruvon-server[server,celery,auth]"

# Install core dependencies
pip install aiosqlite orjson uvloop
```

Verify installation:

```bash
# Test CLI
ruvon --help

# Test SDK import
python -c "from ruvon.builder import WorkflowBuilder; print('✅ Ruvon SDK ready!')"
```

Configure SQLite persistence:

```bash
ruvon config set-persistence
# Choose: SQLite
# Database path: workflow.db

ruvon db init
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
cd src/ruvon
export DATABASE_URL="postgresql://ruvon:ruvon_secret_2024@localhost:5433/ruvon_cloud"
alembic upgrade head
```

Verify connection:

```python
from ruvon.implementations.persistence.postgres import PostgresPersistenceProvider
import asyncio

async def test():
    p = PostgresPersistenceProvider('postgresql://ruvon:ruvon_secret_2024@localhost:5433/ruvon_cloud')
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
# Expected: postgres (healthy), ruvon-server (healthy)

curl http://localhost:8000/health
# Expected: {"status": "healthy"}
```

The database is automatically seeded with demo workflows and edge devices.

**Ports:**
- `8000` - Ruvon API server
- `5433` - PostgreSQL database

## Optional dependencies

### Celery for distributed execution

```bash
pip install celery redis

# Start Redis
docker run -d --name redis-server -p 6379:6379 redis

# Start Celery worker
export DATABASE_URL="postgresql://ruvon:ruvon_secret_2024@localhost:5433/ruvon_cloud"
export CELERY_BROKER_URL="redis://localhost:6379/0"
export CELERY_RESULT_BACKEND="redis://localhost:6379/0"

celery -A ruvon.celery_app worker --loglevel=info
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

### Import error: "No module named 'ruvon'"

Install the SDK in editable mode:

```bash
pip install -e .
```

### Database schema missing

For PostgreSQL:

```bash
cd src/ruvon
export DATABASE_URL="postgresql://ruvon:ruvon_secret_2024@localhost:5433/ruvon_cloud"
alembic upgrade head
```

For SQLite (auto-creates schema):

```bash
ruvon config set-persistence  # Choose SQLite
ruvon db init
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
| `ruvon-sdk` | ~2.5 MB | Core engine (`ruvon/`) + CLI (`ruvon_cli/`) |
| `ruvon-edge` | ~250 KB | Edge agent (`ruvon_edge/`) |
| `ruvon-server` | ~9.5 MB | Cloud control plane (`ruvon_server/`) |

**Total installed footprint** (wheel + core dependencies):

| Scenario | Command | Disk | RAM |
|----------|---------|:----:|:---:|
| Edge, minimal | `pip install ruvon-edge` | ~15–20 MB | ~50 MB |
| Edge + WebSocket/metrics | `pip install 'ruvon-edge[edge]'` | ~30–35 MB | ~65 MB |
| Edge + ONNX fraud scoring | above + `pip install onnxruntime` | ~80–600 MB* | ~115–165 MB |
| Cloud server (full) | `pip install 'ruvon-server[all]'` | ~35–45 MB | — |

\* Varies by model file size. Model files are downloaded separately.

> For per-file breakdowns, hardware requirements, and footprint reduction tips see
> [Edge Device Package Footprint](../reference/configuration/edge-footprint.md).

## See also

- [Configuration guide](configuration.md)
- [Deployment guide](deployment.md)
- [Edge Device Package Footprint](../reference/configuration/edge-footprint.md)
- QUICKSTART.md for quick start instructions
