# Ruvon SDK Examples

Complete working examples demonstrating Rufus workflows across different industries and use cases.

## Learning Path

**New to Rufus?** Follow this path:

1. **[Quickstart](quickstart/)** ⭐ - 5-minute introduction (Beginner)
2. **[SQLite Task Manager](sqlite_task_manager/)** ⭐ - Complete tutorial (Beginner)
3. **[Loan Application](loan_application/)** ⭐⭐ - Business workflows (Intermediate)
4. **[Payment Terminal](payment_terminal/)** ⭐⭐⭐ - Fintech edge device (Advanced)
5. **[Healthcare Wearable](healthcare_wearable/)** ⭐⭐⭐ - IoT data processing (Advanced)
6. **[Industrial IoT](industrial_iot/)** ⭐⭐⭐ - Manufacturing automation (Advanced)
7. **[Edge Deployment](edge_deployment/)** ⭐⭐⭐⭐ - Production edge setup (Expert)
8. **[Celery Workflows](celery_workflows/)** ⭐⭐⭐⭐ - Distributed execution (Expert)
9. **[Browser Demo](browser_demo/)** ⭐⭐⭐⭐ - In-browser Pyodide + WebGPU (Expert)

---

## Examples by Difficulty

### ⭐ Beginner (Start Here!)

#### [Quickstart](quickstart/)
**Time:** 5 minutes
**What You'll Learn:**
- Install Rufus
- Create a simple workflow
- Run it with the CLI

**Features Demonstrated:**
- Basic YAML workflow definition
- STANDARD step types
- State management

**Run It:**
```bash
cd examples/quickstart/
rufus start HelloWorkflow --data '{"name": "World"}'
```

---

#### [SQLite Task Manager](sqlite_task_manager/)
**Time:** 15 minutes
**What You'll Learn:**
- Build a complete application
- Use SQLite for persistence
- Implement CRUD operations

**Features Demonstrated:**
- SQLitePersistenceProvider
- Multiple workflows
- State transitions
- Basic error handling

**Run It:**
```bash
cd examples/sqlite_task_manager/
python main.py
# Or try the simple demo:
python simple_demo.py
```

---

### ⭐⭐ Intermediate

#### [Loan Application](loan_application/)
**Time:** 30 minutes
**What You'll Learn:**
- Parallel execution
- Decision steps
- Human-in-the-loop workflows
- Sub-workflows

**Features Demonstrated:**
- PARALLEL step type (credit check + fraud check simultaneously)
- DECISION steps for routing
- WorkflowPauseDirective for manual approval
- Sub-workflow composition (KYC as child workflow)
- Saga pattern for compensation

**Industry:** Financial Services
**Use Case:** Loan origination with risk assessment

**Run It:**
```bash
cd examples/loan_application/
python run_loan_workflow.py
```

---

### ⭐⭐⭐ Advanced

#### [Payment Terminal](payment_terminal/)
**Time:** 45 minutes
**What You'll Learn:**
- Store-and-Forward pattern
- Offline-first architecture
- Transaction compensation
- Edge device deployment

**Features Demonstrated:**
- SQLite for edge storage
- Saga pattern (automatic refunds)
- Offline transaction queuing
- Sync when online
- PCI-DSS considerations

**Industry:** Fintech (Point-of-Sale)
**Use Case:** POS terminal processing payments offline

**Run It:**
```bash
cd examples/payment_terminal/
python terminal_simulator.py
```

**Scenarios:**
- Online payment processing
- Offline payment queuing
- Connection restore and sync
- Failed payment rollback

---

#### [Healthcare Wearable](healthcare_wearable/)
**Time:** 45 minutes
**What You'll Learn:**
- IoT data ingestion
- Stream processing
- Alert generation
- Cloud sync patterns

**Features Demonstrated:**
- Real-time sensor data processing
- LOOP steps for continuous monitoring
- FIRE_AND_FORGET for async alerts
- HTTP steps for cloud API calls
- Threshold-based decisions

**Industry:** Healthcare IoT
**Use Case:** Wearable device monitoring vital signs

**Run It:**
```bash
cd examples/healthcare_wearable/
python device_simulator.py
```

---

#### [Industrial IoT](industrial_iot/)
**Time:** 45 minutes
**What You'll Learn:**
- Manufacturing automation
- Equipment monitoring
- Predictive maintenance
- Multi-sensor fusion

**Features Demonstrated:**
- CRON_SCHEDULE for periodic checks
- PARALLEL for multi-sensor reading
- Sub-workflows for maintenance procedures
- Alert escalation workflows
- Equipment state machines

**Industry:** Manufacturing
**Use Case:** Factory equipment monitoring and maintenance

**Run It:**
```bash
cd examples/industrial_iot/
python factory_monitor.py
```

---

### ⭐⭐⭐⭐ Expert

#### [Edge Deployment](edge_deployment/)
**Time:** 1-2 hours
**What You'll Learn:**
- Production edge deployment
- Device fleet management
- Config distribution
- Centralized monitoring

**Features Demonstrated:**
- Docker containerization
- Multi-device orchestration
- ETag-based config push
- Heartbeat monitoring
- Log aggregation
- Certificate management

**Industry:** Multi-sector (ATMs, POS, Kiosks)
**Use Case:** Fleet of edge devices with central management

**Run It:**
```bash
cd examples/edge_deployment/
docker compose up
```

**Components:**
- Edge agent (SQLite + sync manager)
- Cloud control plane (PostgreSQL + Redis)
- Config server (ETag-based updates)
- Monitoring dashboard

---

#### [Celery Workflows](celery_workflows/)
**Time:** 1-2 hours
**What You'll Learn:**
- Distributed execution
- Celery integration
- Worker scaling
- Production deployment

**Features Demonstrated:**
- CeleryExecutor for async tasks
- Redis as broker/backend
- Worker pools and concurrency
- Kubernetes deployment
- Horizontal pod autoscaling

**Industry:** High-volume scenarios
**Use Case:** Processing thousands of workflows/second

**Run It:**
```bash
cd examples/celery_workflows/
docker compose up

# Scale workers:
docker compose up --scale celery-worker=5
```

---

#### [Browser Demo](browser_demo/)
**Time:** 30 minutes to explore, 2+ hours to extend
**What You'll Learn:**
- Running Rufus workflows entirely in-browser via Pyodide
- WebGPU-accelerated ML inference with Transformers.js
- Shard-paged LLM inference for memory-constrained environments
- Service Worker offline caching and PWA installation

**Features Demonstrated:**
- Pyodide runtime with InMemoryPersistenceProvider + BrowserSyncExecutor
- 6 demo workflows: OrderFulfillment, IoTSensorPipeline, TransactionRiskScoring, DocumentSummarisation, FieldTechTriage (air-gapped NER + AI dispatch), PagedReasoning (BitNet shard paging)
- Transformers.js WebGPU pipeline with WASM fallback
- OPFS shard cache with double-buffer prefetch
- Q2_K / Q3_K_S quantisation selector; logic-gate fast path (shard-0 only, ~1.5s)
- Service Worker offline support (sw.js v3)

**No install required — runs entirely in the browser:**
```bash
# Serve from repo root (worker.js fetches the wheel from /dist/)
python -m http.server 8080
# Open: http://localhost:8080/examples/browser_demo/
```

**Industry:** Cross-sector (field tech, IoT, fintech, logistics)
**Use Case:** Air-gapped device with full ML inference and workflow orchestration in the browser

---

## Examples by Feature

### Workflow Patterns

| Feature | Examples |
|---------|----------|
| **STANDARD steps** | All examples |
| **ASYNC steps** | Celery Workflows |
| **DECISION steps** | Loan Application, Healthcare Wearable |
| **PARALLEL steps** | Loan Application, Industrial IoT |
| **HTTP steps** | Healthcare Wearable (cloud API) |
| **LOOP steps** | Healthcare Wearable (continuous monitoring) |
| **FIRE_AND_FORGET** | Healthcare Wearable (alerts) |
| **CRON_SCHEDULE** | Industrial IoT (periodic checks) |
| **Human-in-the-Loop** | Loan Application (manual approval) |
| **AI_INFERENCE** | Browser Demo (Paged Reasoning, FieldTechTriage) |
| **WASM** | Browser Demo (Pyodide runtime) |

### Architectural Patterns

| Pattern | Examples |
|---------|----------|
| **Saga/Compensation** | Payment Terminal, Loan Application |
| **Store-and-Forward** | Payment Terminal, Edge Deployment |
| **Sub-Workflows** | Loan Application (KYC child) |
| **Parallel Execution** | Loan Application, Industrial IoT |
| **Offline-First** | Payment Terminal, Edge Deployment, Browser Demo (SW + OPFS) |

### Infrastructure

| Technology | Examples |
|------------|----------|
| **SQLite** | Quickstart, SQLite Task Manager, Payment Terminal |
| **PostgreSQL** | Celery Workflows, Edge Deployment (cloud) |
| **Redis/Celery** | Celery Workflows |
| **Docker** | Edge Deployment, Celery Workflows |
| **Kubernetes** | Celery Workflows (k8s/) |

---

## Industry Examples

### Financial Services
- **[Payment Terminal](payment_terminal/)** - POS with offline support
- **[Loan Application](loan_application/)** - Loan origination workflow

### Healthcare
- **[Healthcare Wearable](healthcare_wearable/)** - Vital sign monitoring

### Manufacturing
- **[Industrial IoT](industrial_iot/)** - Equipment monitoring

### Field Operations / Industrial
- **[Browser Demo — FieldTechTriage](browser_demo/)** - Air-gapped NER + AI triage in-browser
- **[Browser Demo — PagedReasoning](browser_demo/)** - LLM paging for memory-constrained devices

### General Purpose
- **[SQLite Task Manager](sqlite_task_manager/)** - Task management app
- **[Quickstart](quickstart/)** - Hello world

---

## Running Examples

### Prerequisites

All examples require:
```bash
# Install Ruvon SDK
pip install -r requirements.txt
```

Some examples have additional requirements (Docker, Redis, PostgreSQL) - see their individual READMEs.

### Quick Test

To verify your setup works:
```bash
cd examples/quickstart/
rufus start HelloWorkflow --data '{"name": "Test"}'
```

If this works, you're ready to explore other examples!

---

## Example Structure

Each example includes:
- **README.md** - Detailed explanation and instructions
- **config/** - Workflow YAML definitions
- **steps.py** or workflow_functions.py - Step implementations
- **state_models.py** - Pydantic state models (if needed)
- **run_*.py** - Example runner scripts
- **requirements.txt** - Example-specific dependencies (if any)

---

## Contributing Examples

Have a great example to share? We'd love to include it!

**What makes a good example:**
- ✅ Solves a real-world problem
- ✅ Demonstrates specific Rufus features
- ✅ Includes working code and clear documentation
- ✅ Follows the example structure above
- ✅ Can run with minimal setup

See [Contributing Guide](../docs/appendices/contributing.md) for details.

---

## Need Help?

- **General questions:** See [Documentation](../docs/index.md)
- **Example-specific:** Check the example's README.md
- **Stuck?** Try the [Troubleshooting Guide](../docs/how-to-guides/troubleshooting.md)
- **Still stuck?** Open an issue on [GitHub](https://github.com/KamikaziD/ruvon-sdk/issues)

---

**Happy Learning!** 🚀
