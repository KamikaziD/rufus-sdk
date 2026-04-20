# Ruvon SDK - Quick Start Guide

Get started with Ruvon in under 5 minutes. This guide walks you through installation and running your first workflow.

## What is Ruvon?

Ruvon is a **Python-native, SDK-first workflow engine** for orchestrating complex business processes and AI pipelines. Unlike heavyweight systems like Temporal or Airflow, Ruvon embeds directly into your Python applications with zero infrastructure requirements.

**Key Benefits:**
- ✅ **Embedded SDK** - No external servers required, runs in-process
- ✅ **SQLite Built-In** - Start immediately with embedded database
- ✅ **Declarative YAML** - Define workflows without writing orchestration code
- ✅ **Production-Ready** - Saga patterns, parallel execution, human-in-the-loop
- ✅ **Type-Safe** - Pydantic validation catches errors before runtime

---

## Installation (2 minutes)

### Prerequisites
- Python 3.9 or higher
- pip

### Install Ruvon

```bash
# Clone the repository
git clone https://github.com/your-org/ruvon-sdk.git
cd ruvon-sdk

# Install in development mode
pip install -e .

# Install core dependencies
pip install aiosqlite orjson asyncpg uvloop
```

### Verify Installation

```bash
# Test CLI
ruvon --help

# Test SDK import
python -c "from ruvon.builder import WorkflowBuilder; print('✅ Ruvon SDK ready!')"
```

---

## Choose Your Installation Path

Ruvon offers three installation paths depending on your needs. Choose the one that fits your use case:

### 🔀 Decision Tree

```
Start Here
    │
    ├─ Need Docker containerization?
    │  │
    │  ├─ Yes → Want full cloud control plane + edge simulation?
    │  │         ├─ Yes → PATH 1: Docker Compose (Full Stack)
    │  │         └─ No  → PATH 2: Docker (SDK + PostgreSQL)
    │  │
    │  └─ No  → PATH 3: Direct Install (SDK + SQLite)
```

### PATH 1: Docker Compose - Full Stack (Recommended for Edge Development)

**Best for:** Testing edge device scenarios, cloud control plane development

**What you get:**
- ✅ Cloud control plane (FastAPI server)
- ✅ PostgreSQL database with seed data
- ✅ All edge-specific tables (devices, commands, webhooks)
- ✅ Zero manual setup - everything automatic

```bash
cd docker
docker compose up -d

# Verify services
docker compose ps
# Expected: postgres (healthy), ruvon-server (healthy)

# Check API
curl http://localhost:8000/health
# Expected: {"status": "healthy"}

# Database automatically seeded with:
# - 4 demo workflows
# - 5 edge devices
```

**When to use:**
- Testing edge device workflows
- Developing cloud APIs
- Full-stack local development
- Load testing with device simulation

**Ports:**
- `8000` - Ruvon API server
- `5433` - PostgreSQL database

### PATH 2: Docker (SDK + PostgreSQL) - Lightweight

**Best for:** SDK development with production database, without full cloud services

**What you get:**
- ✅ PostgreSQL database in Docker
- ✅ Ruvon SDK in your local Python environment
- ✅ No server overhead

```bash
# Start only PostgreSQL
cd docker
docker compose up postgres -d

# Install SDK
pip install -r requirements.txt

# Initialize database with Alembic migrations
cd src/ruvon
export DATABASE_URL="postgresql://ruvon:ruvon_secret_2024@localhost:5433/ruvon_cloud"
alembic upgrade head

# (Optional) Seed demo data
cd ../..
python tools/seed_data.py \
  --db-url "postgresql://ruvon:ruvon_secret_2024@localhost:5433/ruvon_cloud" \
  --type all

# Verify
python -c "
from ruvon.implementations.persistence.postgres import PostgresPersistenceProvider
import asyncio

async def test():
    p = PostgresPersistenceProvider('postgresql://ruvon:ruvon_secret_2024@localhost:5433/ruvon_cloud')
    await p.initialize()
    workflows = await p.list_workflows()
    print(f'✅ PostgreSQL ready! Found {len(workflows)} workflows')
    await p.close()

asyncio.run(test())
"
```

**When to use:**
- SDK development with PostgreSQL
- Testing migrations
- Production-like environment locally
- CI/CD pipelines

### PATH 3: Direct Install (SDK + SQLite) - Fastest

**Best for:** Quick testing, examples, SDK-only development

**What you get:**
- ✅ Zero infrastructure (embedded SQLite)
- ✅ Instant start - no Docker required
- ✅ Perfect for learning and prototyping

```bash
# Install SDK
pip install -r requirements.txt

# Run example with automatic SQLite setup
cd examples/sqlite_task_manager
python simple_demo.py

# Or use CLI with SQLite
ruvon config set-persistence
# Choose: SQLite
# Database path: workflow.db

ruvon db init
```

**When to use:**
- Learning Ruvon SDK
- Running examples
- Quick prototyping
- Testing without infrastructure
- CI/CD without Docker

---

### 📊 Installation Path Comparison

| Feature | PATH 1: Docker Compose | PATH 2: Docker DB Only | PATH 3: Direct Install |
|---------|----------------------|---------------------|---------------------|
| **Setup Time** | 2 min | 3 min | 1 min |
| **Infrastructure** | Docker Compose | Docker | None |
| **Database** | PostgreSQL | PostgreSQL | SQLite |
| **Cloud API Server** | ✅ Yes | ❌ No | ❌ No |
| **Edge Tables** | ✅ Yes | ✅ Yes | ❌ No |
| **Auto Seed Data** | ✅ Yes | ⚠️ Manual | ⚠️ Manual |
| **Best For** | Edge dev, Full stack | SDK + Postgres | Learning, Examples |

---

## Run Your First Workflow (3 minutes)

### Option 1: SQLite Task Manager Demo (Recommended)

The simplest way to see Ruvon in action:

```bash
cd examples/sqlite_task_manager
python simple_demo.py
```

**What this demonstrates:**
- ✅ In-memory SQLite database (no setup required)
- ✅ Workflow creation and execution
- ✅ State persistence
- ✅ Logging and metrics

**Expected Output:**
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

### Option 2: Interactive Quickstart Example

Run the full quickstart example with proper Python path:

```bash
cd /path/to/ruvon-sdk
PYTHONPATH=$PWD:$PYTHONPATH python examples/quickstart/run_quickstart.py
```

**What this demonstrates:**
- ✅ Workflow builder initialization
- ✅ Sequential step execution
- ✅ State management with Pydantic models
- ✅ Automated step chaining

---

## Understanding What Just Happened

### Architecture Overview

```
┌─────────────────────────────────────────┐
│         Your Application                │
│  ┌───────────────────────────────────┐  │
│  │   Workflow (YAML + Python)        │  │
│  │   - State Model (Pydantic)        │  │
│  │   - Step Functions (Python)       │  │
│  │   - Workflow Config (YAML)        │  │
│  └───────────────┬───────────────────┘  │
│                  │                       │
│  ┌───────────────▼───────────────────┐  │
│  │      WorkflowBuilder/Engine       │  │
│  │      (Orchestration Logic)        │  │
│  └───────────────┬───────────────────┘  │
│                  │                       │
│     ┌────────────┼────────────┐         │
│     ▼            ▼             ▼         │
│ Persistence  Execution   Observability  │
│  Provider     Provider      Provider    │
│  (SQLite)     (Sync)       (Logging)    │
└─────┬────────────┬─────────────┬────────┘
      │            │             │
  ┌───▼───┐    ┌───▼───┐     ┌──▼──┐
  │  DB   │    │Workers│     │Logs │
  │(File) │    │(Local)│     │(CLI)│
  └───────┘    └───────┘     └─────┘
```

### Key Concepts

**1. State Model (Pydantic)**
- Defines workflow data structure
- Type validation
- Serialized to database

**2. Step Functions (Python)**
- Receive `state` and `context`
- Return dict to update state
- Isolated, testable functions

**3. Workflow Config (YAML)**
- Declarative step definitions
- Dependencies and routing
- No orchestration code needed

**4. Providers (Pluggable)**
- **Persistence** - Where state is stored (SQLite, PostgreSQL, Redis)
- **Execution** - How steps run (Sync, Thread Pool, Celery)
- **Observability** - What you see (Logging, Metrics)

---

## Next Steps

### 1. Try More Examples

```bash
# Simple task workflow
cd examples/sqlite_task_manager
python main.py

# Complex loan application workflow
cd examples/loan_application
python run_loan_workflow.py

# FastAPI integration
cd examples/fastapi_api
uvicorn main:app --reload
```

### 2. Create Your Own Workflow

**Step 1: Define State Model**
```python
# my_workflow/state_models.py
from pydantic import BaseModel
from typing import Optional

class MyWorkflowState(BaseModel):
    user_id: str
    status: Optional[str] = None
    result: Optional[dict] = None
```

**Step 2: Implement Step Functions**
```python
# my_workflow/steps.py
from ruvon.models import StepContext
from state_models import MyWorkflowState

def process_data(state: MyWorkflowState, context: StepContext) -> dict:
    """Process user data."""
    state.status = "processing"
    # Your business logic here
    return {"processed": True}
```

**Step 3: Define Workflow YAML**
```yaml
# my_workflow/workflow.yaml
workflow_type: "MyWorkflow"
workflow_version: "1.0"
initial_state_model: "my_workflow.state_models.MyWorkflowState"

steps:
  - name: "Process_Data"
    type: "STANDARD"
    function: "my_workflow.steps.process_data"
    automate_next: true
```

**Step 4: Execute**
```python
# my_workflow/run.py
import asyncio
from ruvon.builder import WorkflowBuilder
from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider
from ruvon.implementations.execution.sync import SyncExecutionProvider

async def main():
    # Initialize providers
    persistence = SQLitePersistenceProvider(db_path=":memory:")
    await persistence.initialize()

    # Create builder
    builder = WorkflowBuilder(
        config_dir="my_workflow/",
        persistence_provider=persistence,
        execution_provider=SyncExecutionProvider()
    )

    # Start workflow
    workflow = await builder.create_workflow(
        workflow_type="MyWorkflow",
        initial_data={"user_id": "123"}
    )

    # Execute steps
    while workflow.status == "ACTIVE":
        await workflow.next_step()

    print(f"✅ Workflow completed: {workflow.status}")
    print(f"Final state: {workflow.state}")

asyncio.run(main())
```

### 3. Explore Documentation

- **[USAGE_GUIDE.md](USAGE_GUIDE.md)** - Core concepts and common patterns
- **[docs/ADVANCED_GUIDE.md](docs/ADVANCED_GUIDE.md)** - Advanced features and production patterns
- **[docs/FEATURES_AND_CAPABILITIES.md](docs/FEATURES_AND_CAPABILITIES.md)** - Complete feature reference
- **[YAML_GUIDE.md](YAML_GUIDE.md)** - YAML configuration reference
- **[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)** - CLI command reference

### 4. Learn Key Features

**Human-in-the-Loop**
```python
from ruvon.models import WorkflowPauseDirective

def approval_step(state, context):
    raise WorkflowPauseDirective(result={"awaiting_approval": True})
```

**Parallel Execution**
```yaml
- name: "Risk_Assessment"
  type: "PARALLEL"
  tasks:
    - name: "Credit_Check"
      function: "checks.credit"
    - name: "Fraud_Detection"
      function: "checks.fraud"
```

**Saga Pattern (Rollback)**
```yaml
- name: "Charge_Payment"
  function: "payments.charge"
  compensate_function: "payments.refund"  # Auto-rollback on failure
```

**Sub-Workflows**
```python
from ruvon.models import StartSubWorkflowDirective

def trigger_kyc(state, context):
    raise StartSubWorkflowDirective(
        workflow_type="KYC_Verification",
        initial_data={"user_id": state.user_id}
    )
```

---

## Common Issues

### Import Error: "No module named 'ruvon'"
**Solution:** Install the SDK in editable mode:
```bash
pip install -e .
```

### Module Not Found: "examples.quickstart.steps"
**Solution:** Run from project root with PYTHONPATH:
```bash
PYTHONPATH=$PWD:$PYTHONPATH python examples/quickstart/run_quickstart.py
```

### Database Schema Missing
**Solution:** Initialize database schema with Alembic:
```bash
# For PostgreSQL
cd src/ruvon
export DATABASE_URL="postgresql://ruvon:ruvon_secret_2024@localhost:5433/ruvon_cloud"
alembic upgrade head

# For SQLite (CLI will auto-create schema)
ruvon config set-persistence  # Choose SQLite
ruvon db init  # Auto-creates SQLite schema
```

### Missing Dependencies
**Solution:** Install all dependencies:
```bash
pip install aiosqlite orjson asyncpg uvloop
```

---

## Quick Command Reference

```bash
# Configuration
ruvon config show                # Show current config
ruvon config set-persistence     # Choose database (SQLite/PostgreSQL)
ruvon config set-execution       # Choose executor (sync/thread_pool)

# Workflow Management
ruvon list                       # List all workflows
ruvon start <workflow-type>      # Start a workflow
ruvon show <workflow-id>         # Show workflow details
ruvon resume <workflow-id>       # Resume paused workflow
ruvon cancel <workflow-id>       # Cancel running workflow

# Database Management (Alembic)
cd src/ruvon
alembic upgrade head             # Apply all pending migrations
alembic current                  # Show current migration version
alembic history                  # Show migration history
alembic downgrade -1             # Rollback one migration

# Database Management (SQLite - CLI auto-creates schema)
ruvon db init                    # Initialize SQLite schema (auto)

# Monitoring
ruvon logs <workflow-id>         # View workflow logs
ruvon metrics                    # View performance metrics

# Validation
ruvon validate workflow.yaml     # Validate YAML syntax
```

---

## What Makes Ruvon Different?

| Feature | Ruvon | Temporal | Airflow | AWS Step Functions |
|---------|-------|----------|---------|-------------------|
| **Setup Complexity** | Zero (embedded SQLite) | High (cluster required) | Medium (server + DB) | Low (AWS only) |
| **Deployment** | In-process | Distributed | Server-based | Cloud-only |
| **Language** | Python-native | Polyglot | Python | JSON DSL |
| **Cost** | Free | Infrastructure costs | Infrastructure costs | Pay-per-execution |
| **Vendor Lock-in** | None | None | None | AWS only |

---

## Next Steps Checklist

- [ ] Run sqlite_task_manager demo successfully
- [ ] Understand State, Steps, and Providers
- [ ] Try modifying an example workflow
- [ ] Create your own simple workflow
- [ ] Read USAGE_GUIDE.md for common patterns
- [ ] Explore advanced features (Saga, Parallel, Sub-workflows)
- [ ] Join the community (link to Discord/GitHub)

---

**🎉 You're ready to build production workflows with Ruvon!**

For questions or issues:
- 📖 [Full Documentation](docs/README.md)
- 💬 [GitHub Discussions](https://github.com/your-org/ruvon-sdk/discussions)
- 🐛 [Report Issues](https://github.com/your-org/ruvon-sdk/issues)

---

**Last Updated:** 2026-02-02
