# Rufus - Python Workflow Engine for Fintech Edge Devices

**Stop fighting with Temporal's infrastructure. Stop limiting yourself to Airflow's batch-only world.**

Rufus is a Python-native workflow engine designed for **fintech edge devices** - POS terminals, ATMs, mobile readers, and kiosks. It provides offline-first architecture, store-and-forward, and production-grade reliability features.

```bash
pip install rufus-sdk[all]  # SQLite included, zero setup
```

---

## Why Rufus?

| Feature | Rufus | Temporal | Airflow | AWS Step Functions |
|---------|-------|----------|---------|-------------------|
| **Setup** | 30 seconds (pip install) | 2-4 hours (cluster) | 1-2 hours (server) | 30 min (AWS setup) |
| **Edge Deployment** | ✅ SQLite, offline-first | ❌ Requires server | ❌ Requires server | ❌ Cloud only |
| **Network Overhead** | 0-2 calls/step | 4 calls/step | 3 calls/step | N/A (cloud) |
| **Store-and-Forward** | ✅ Built-in for fintech | ❌ Not designed for | ❌ Not designed for | ❌ Not applicable |
| **Language** | Python-native | Polyglot | Python | JSON DSL |
| **Cost** | Free | Infrastructure | Infrastructure | Pay-per-execution |

---

## Quick Start (30 Seconds)

### 1. Install

```bash
# Install from PyPI (recommended)
pip install rufus-sdk[all]

# Or install from source for development
git clone https://github.com/KamikaziD/rufus-sdk.git
cd rufus-sdk
pip install -e .
```

### 2. Run Your First Workflow

```bash
# Run the SQLite task manager demo (zero setup)
python examples/sqlite_task_manager/simple_demo.py
```

**What Just Happened?**
- ✅ Created embedded SQLite database (no server needed)
- ✅ Ran multi-step workflow with state persistence
- ✅ Demonstrated workflow lifecycle (create → execute → complete)
- ✅ All in-memory, **under 1 second**

### 3. Explore Examples

```bash
# Loan application with parallel risk checks
python examples/loan_application/run_loan_workflow.py

# Payment terminal with offline support (fintech edge)
python examples/payment_terminal/terminal_simulator.py

# Healthcare wearable with vital monitoring
python examples/healthcare_wearable/device_simulator.py
```

---

## Key Features

### 🏦 Fintech Edge Architecture

**Built for POS terminals, ATMs, mobile readers, and kiosks:**

- **Offline-First** - SQLite + Store-and-Forward queues transactions when offline
- **ETag-Based Config Push** - Hot-deploy fraud rules without firmware updates
- **Transaction Compensation** - Saga pattern for automatic payment rollback
- **Zombie Recovery** - Heartbeat-based detection of crashed workers
- **Workflow Versioning** - Definition snapshots protect running workflows from YAML changes

**Architecture:**

```
CLOUD CONTROL PLANE (PostgreSQL)          EDGE DEVICE (SQLite)
├── Device Registry API                    ├── RufusEdgeAgent
├── Config Server (ETag)         <─────>   ├── SyncManager (SAF)
├── Transaction Sync API                   ├── ConfigManager
└── Settlement Gateway                     └── Local Workflows
```

### 🚀 Production-Grade Workflow Engine

- **Saga Pattern** - Automatic compensation (rollback) on failure
- **Parallel Execution** - Run credit check + fraud detection simultaneously
- **Human-in-the-Loop** - Pause workflows for manual approval
- **Sub-Workflows** - Hierarchical composition with status bubbling
- **HTTP Steps** - Polyglot workflows (call Go/Rust/Node.js services)
- **LOOP/CRON Steps** - Continuous monitoring and scheduled workflows
- **Decision Steps** - Declarative routing with condition evaluation

### ⚡ Performance Optimizations

- **uvloop** - 2-4x faster async I/O operations
- **orjson** - 3-5x faster JSON serialization
- **Import Caching** - 162x speedup for step function imports
- **Optimized PostgreSQL Pool** - Tuned for high concurrency (10-50 connections)

**Benchmark Results:**
```
Serialization: 2,453,971 ops/sec (orjson)
Import Caching: 162x speedup
Async Latency: 5.5µs p50, 12.7µs p99 (uvloop)
Workflow Throughput: 703,633 workflows/sec (simplified)
```

---

## Use Cases

### 1. **Fintech - Payment Terminal (Offline Support)**

```yaml
# Payment workflow with automatic compensation
steps:
  - name: "Reserve_Inventory"
    type: "STANDARD"
    function: "inventory.reserve"
    compensate_function: "inventory.release"  # Auto-rollback on failure

  - name: "Charge_Payment"
    type: "STANDARD"
    function: "payments.charge"
    compensate_function: "payments.refund"  # Auto-refund on failure
```

**Example:** [`examples/payment_terminal/`](examples/payment_terminal/)

---

### 2. **Business Automation - Loan Application (Parallel Execution)**

```yaml
# Parallel risk assessment
- name: "Risk_Assessment"
  type: "PARALLEL"
  tasks:
    - name: "Credit_Check"
      function: "credit.check_bureau"
    - name: "Fraud_Detection"
      function: "fraud.run_ml_model"

# Conditional routing
- name: "Route_Application"
  type: "DECISION"
  routes:
    - condition: "state.credit_score > 700"
      target: "Fast_Track_Approval"
    - default: "Manual_Underwriting"
```

**Example:** [`examples/loan_application/`](examples/loan_application/)

---

### 3. **Healthcare IoT - Wearable Device (Continuous Monitoring)**

```yaml
# Continuous vital monitoring
- name: "Process_Vital_Stream"
  type: "LOOP"
  mode: "ITERATE"
  iterate_over: "state.vital_readings"
  loop_body:
    - name: "Analyze_Reading"
      type: "STANDARD"
      function: "health.analyze_vital"
    - name: "Check_Anomaly"
      type: "DECISION"
      routes:
        - condition: "state.heart_rate > 120 or state.heart_rate < 50"
          target: "Trigger_Alert"
```

**Example:** [`examples/healthcare_wearable/`](examples/healthcare_wearable/)

---

### 4. **Polyglot Integration - Multi-Language Pipeline**

```yaml
# Orchestrate Go/Rust/Node.js services from Python
steps:
  # Python: Validation
  - name: "Validate"
    type: "STANDARD"
    function: "steps.validate"

  # Go: High-performance processing
  - name: "Process_Go"
    type: "HTTP"
    http_config:
      url: "http://go-processor:8080/process"
      method: "POST"
      body: "{{state.validated_data}}"

  # Rust: ML inference
  - name: "Predict_Rust"
    type: "HTTP"
    http_config:
      url: "http://rust-ml:8080/predict"
      body: "{{state.features}}"

  # Node.js: Notifications
  - name: "Notify_Node"
    type: "HTTP"
    http_config:
      url: "http://notification:3000/send"
      body: "{{state.result}}"
```

---

## Documentation

Rufus follows the [Diátaxis](https://diataxis.fr/) framework for comprehensive, organized documentation:

### 📖 **Getting Started**

| Document | Description | Time |
|----------|-------------|------|
| [Getting Started Tutorial](docs/tutorials/getting-started.md) | 5-minute quickstart | ⭐ 5 min |
| [Example Learning Path](examples/README.md) | 8 progressive examples (beginner → expert) | ⭐-⭐⭐⭐⭐ |

### 🛠️ **How-To Guides** (Task-Oriented)

| Guide | Use When |
|-------|----------|
| [Installation](docs/how-to-guides/installation.md) | Setting up SQLite, PostgreSQL, or Docker |
| [Create Workflow](docs/how-to-guides/create-workflow.md) | Building your first workflow from scratch |
| [Decision Steps](docs/how-to-guides/decision-steps.md) | Adding conditional branching |
| [HTTP Steps](docs/how-to-guides/http-steps.md) | Calling external services (polyglot) |
| [Human-in-the-Loop](docs/how-to-guides/human-in-loop.md) | Adding manual approval steps |
| [Saga Mode](docs/how-to-guides/saga-mode.md) | Implementing compensation/rollback |
| [Testing](docs/how-to-guides/testing.md) | Testing workflows with TestHarness |
| [Deployment](docs/how-to-guides/deployment.md) | Deploying to Docker/Kubernetes |
| [Troubleshooting](docs/how-to-guides/troubleshooting.md) | Common issues and solutions |

[**All How-To Guides →**](docs/how-to-guides/)

### 💡 **Explanation** (Understanding-Oriented)

| Topic | Learn About |
|-------|-------------|
| [Architecture](docs/explanation/architecture.md) | System design and components |
| [Provider Pattern](docs/explanation/provider-pattern.md) | Pluggable persistence/execution |
| [Workflow Lifecycle](docs/explanation/workflow-lifecycle.md) | Creation → execution → completion |
| [Saga Pattern](docs/explanation/saga-pattern.md) | Distributed transaction compensation |
| [Zombie Recovery](docs/explanation/zombie-recovery.md) | Handling worker crashes |
| [Workflow Versioning](docs/explanation/workflow-versioning.md) | Definition snapshots for safe deployments |
| [Edge Architecture](docs/explanation/edge-architecture.md) | Fintech edge device design |
| [Confucius Heritage](docs/explanation/confucius-heritage.md) | Feature provenance and evolution |

[**All Explanations →**](docs/explanation/)

### 📚 **Reference** (Information-Oriented)

| Reference | Contains |
|-----------|----------|
| [API Reference](docs/reference/api/) | WorkflowBuilder, Workflow, Providers, StepContext, Directives |
| [YAML Schema](docs/reference/configuration/yaml-schema.md) | Complete workflow YAML specification |
| [Step Types](docs/reference/configuration/step-types.md) | All 9 step types with configurations |
| [CLI Commands](docs/reference/configuration/cli-commands.md) | All 26 rufus CLI commands |
| [Database Schema](docs/reference/configuration/database-schema.md) | PostgreSQL/SQLite table schemas |

[**All Reference Docs →**](docs/reference/)

### ⚠️ **Advanced Topics** (Expert-Level)

| Topic | Read Before |
|-------|-------------|
| [Executor Portability](docs/advanced/executor-portability.md) | ⚠️ CRITICAL: Stateless step functions |
| [Dynamic Injection](docs/advanced/dynamic-injection.md) | ⚠️ CAUTION: Non-determinism pitfalls |
| [Custom Providers](docs/advanced/custom-providers.md) | Building custom persistence/execution |
| [Security](docs/advanced/security.md) | PCI-DSS compliance, encryption, RBAC |
| [Resource Management](docs/advanced/resource-management.md) | Connection pooling, memory management |

[**All Advanced Topics →**](docs/advanced/)

### 📚 **Appendices**

- [Glossary](docs/appendices/glossary.md) - 50+ term definitions
- [Changelog](docs/appendices/changelog.md) - Version history (v0.1.0 → v0.3.1)
- [Roadmap](docs/appendices/roadmap.md) - Development plans through 2026
- [Migration Notes](docs/appendices/migration-notes.md) - Upgrade guides
- [Contributing](docs/appendices/contributing.md) - Contribution guidelines

[**All Appendices →**](docs/appendices/)

---

## CLI Quick Reference

```bash
# Configuration
rufus config show                # Show current configuration
rufus config set-persistence     # Choose database (SQLite/PostgreSQL)
rufus config set-execution       # Choose executor (sync/thread_pool)

# Workflow Management
rufus list                       # List all workflows
rufus start <workflow-type>      # Start a workflow
rufus show <workflow-id>         # Show workflow details
rufus resume <workflow-id>       # Resume paused workflow
rufus cancel <workflow-id>       # Cancel running workflow
rufus logs <workflow-id>         # View execution logs

# Database Management
cd src/rufus
alembic upgrade head             # Apply migrations (PostgreSQL)
alembic current                  # Show current version
rufus db init                    # Initialize SQLite (auto-creates schema)

# Zombie Recovery
rufus scan-zombies --fix         # Detect and recover crashed workflows
rufus zombie-daemon              # Run continuous monitoring

# Validation
rufus validate workflow.yaml     # Validate YAML syntax
```

---

## Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Your Application                         │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         WorkflowBuilder (YAML Loader)                 │  │
│  └────────────────────┬─────────────────────────────────┘  │
│                       │                                     │
│  ┌────────────────────▼─────────────────────────────────┐  │
│  │         Workflow (Orchestration Engine)              │  │
│  │  - State management (Pydantic validation)            │  │
│  │  - Step execution (sync/async/parallel)              │  │
│  │  - Directives (pause, jump, sub-workflow)            │  │
│  │  - Saga compensation (rollback)                      │  │
│  └────────┬──────────────┬────────────────┬─────────────┘  │
│           │              │                │                 │
│     ┌─────▼─────┐  ┌────▼────┐    ┌─────▼──────┐         │
│     │Persistence│  │Execution│    │Observability│         │
│     │ Provider  │  │ Provider│    │  Provider   │         │
│     └─────┬─────┘  └────┬────┘    └─────┬──────┘         │
└───────────┼─────────────┼───────────────┼────────────────┘
            │             │               │
     ┌──────▼──────┐ ┌───▼────┐    ┌────▼─────┐
     │  Database   │ │Workers │    │  Logs    │
     │(SQLite/PG)  │ │(Celery)│    │ (Metrics)│
     └─────────────┘ └────────┘    └──────────┘
```

### Provider Pattern (Pluggable)

- **PersistenceProvider** - SQLite, PostgreSQL, Redis, Memory
- **ExecutionProvider** - Sync, Thread Pool, Celery
- **WorkflowObserver** - Logging, Metrics, Real-time events

---

## Testing

Run the full test suite:

```bash
# Unit tests
pytest tests/sdk/ -v

# Integration tests (requires Docker)
cd tests/integration
docker compose up -d
pytest test_celery_execution.py -v

# Benchmarks
python tests/benchmarks/workflow_performance.py
```

---

## Contributing

We welcome contributions! See [Contributing Guide](docs/appendices/contributing.md) for:
- Code of conduct
- Development setup
- Coding standards (PEP 8, type hints, 100 char lines)
- Testing requirements (80% coverage)
- Pull request process

---

## License

MIT License - See [LICENSE](LICENSE) file for details.

---

## Support

- 📖 [Documentation](docs/index.md)
- 💬 [GitHub Discussions](https://github.com/KamikaziD/rufus-sdk/discussions)
- 🐛 [Report Issues](https://github.com/KamikaziD/rufus-sdk/issues)

---

**Current Version:** v0.3.1 (Documentation Release)
**Next Release:** v0.9.1 (March 2026) - Bug fixes and polish
**Stability Release:** v1.0.0 (Q2 2026) - Production ready

Built with ❤️ for fintech edge computing
