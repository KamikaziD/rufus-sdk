> ⚙️ SOP: Always read `.claude/agent_standard_operating_procedure.md` before starting a new task.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Rufus Edge** is a Python-native workflow engine designed for **fintech edge devices** - POS terminals, ATMs, mobile readers, and kiosks. It provides:

- **Offline-first architecture** with SQLite for edge deployment
- **Store-and-Forward (SAF)** for offline payment transactions
- **Cloud control plane** for device fleet management
- **ETag-based config push** for fraud rules and workflow updates
- **Saga pattern** for transaction compensation/rollback
- **PCI-DSS ready** architecture with encryption support

The project consists of:

1. **Core SDK** (`src/rufus/`) - The reusable workflow engine library
2. **Edge Agent** (`src/rufus_edge/`) - Runtime for edge devices with offline support
3. **Cloud Control Plane** (`src/rufus_server/`) - FastAPI server for device management
4. **CLI Tool** (`src/rufus_cli/`) - Command-line interface for workflow management

### Fintech Edge Architecture

```
CLOUD CONTROL PLANE (PostgreSQL)          EDGE DEVICE (SQLite)
├── Device Registry API                    ├── RufusEdgeAgent
├── Config Server (ETag)         <─────>   ├── SyncManager (SAF)
├── Transaction Sync API                   ├── ConfigManager
└── Settlement Gateway                     └── Local Workflows
```

### Key Use Cases

| Use Case | Description |
|----------|-------------|
| **Store-and-Forward** | Process payments offline, sync when online |
| **TMS Config Push** | Hot-deploy fraud rules without firmware updates |
| **Transaction Compensation** | Saga-based rollback for failed operations |
| **Offline Floor Limits** | Approve small transactions without network |

### Heritage and Evolution

**Rufus is extracted from "Confucius"**, a monolithic workflow engine prototype.

**Inherited from Confucius:** HTTP Steps, Phase 8 Step Types (Loop, Fire-and-Forget, Cron), Semantic Firewall, PostgresExecutor Pattern, Saga Pattern, Sub-Workflows, Dynamic Injection.

**Rufus Additions:** Provider Pattern, Multi-Executor Support, Production Tooling (Docker/K8s/Helm), CLI Tool, SQLite Support, Performance Optimizations (uvloop, orjson, connection pooling, import caching), Zombie Workflow Recovery, Workflow Versioning.

**Not Yet Ported:** Debug UI (planned).

**Key Difference:** Confucius was monolithic (4,637 lines, 22 files). Rufus is modular SDK + CLI + Server (31,112 lines, 125 files).

---

## Development Commands

### Setup

```bash
# Full dev install (all three packages from source)
pip install -e ".[postgres,performance,cli]"
pip install -e "packages/rufus-sdk-edge[edge]"
pip install -e "packages/rufus-sdk-server[server,celery,auth]"

# For Redis/Celery: docker run -d --name redis-server -p 6379:6379 redis
```

**PyPI install by role:**
```bash
# Edge device only (~15 MB installed)
pip install 'rufus-sdk-edge[edge]'

# Cloud server (API + workers)
pip install 'rufus-sdk[postgres,performance]' 'rufus-sdk-server[server,celery,auth]'
```

### Testing

```bash
pytest                                          # All tests with coverage
pytest tests/sdk/test_engine.py                 # Specific module
pytest -v                                       # Verbose
pytest tests/sdk/test_workflow.py::test_name    # Single test
```

Tests automatically exclude `confucius/` and `original_implementation_files/` directories.

### CLI Commands

**Configuration:**
```bash
rufus config show               # Show current configuration
rufus config set-persistence    # Set persistence provider (interactive)
rufus config set-execution      # Set execution provider (interactive)
rufus config set-default        # Set default behaviors (interactive)
rufus config reset              # Reset to defaults
rufus config path               # Show config file location
```

**Workflow Management:**
```bash
rufus list [--status ACTIVE] [--type OrderProcessing] [--limit 10]
rufus show <workflow-id> [--state] [--logs]
rufus start <workflow-type> [--data '{"field": "value"}'] [--data-file data.json] [--config wf.yaml] [--auto] [--interactive/-i] [--dry-run]
rufus resume <workflow-id> [--input '{"approval": true}'] [--input-file input.json] [--auto]
rufus retry <workflow-id> [--from-step StepName]
rufus cancel <workflow-id> [--force] [--reason "User cancelled"]
rufus logs <workflow-id> [--step StepName] [--level ERROR] [--limit 50]
rufus metrics [--workflow-id <id>] [--type execution_time]
rufus interactive run <workflow-type> [--data '{}'] [--config wf.yaml]
```

**Database Management:**
```bash
rufus db init [--db-url postgresql://...]  # Initialize database schema
rufus db migrate [--dry-run]               # Apply pending migrations
rufus db status                            # Show migration status
rufus db stats                             # Show database statistics
rufus db validate                          # Validate schema definition
```

**Validate & Run (local):**
```bash
rufus validate <workflow.yaml> [--strict] [--json] [--graph] [--graph-format mermaid|dot|text]
rufus run <workflow.yaml> [--data '{}']
```

**Zombie Workflow Recovery:**
```bash
rufus scan-zombies --db <URL> [--fix] [--threshold 120]   # Scan for zombie workflows (--db required)
rufus zombie-daemon --db <URL> [--interval 60]            # Run scanner as daemon (--db required)
```

**Alternative subcommand syntax:** `rufus workflow list`, `rufus workflow start <type>`, etc.

### Running the Server

```bash
uvicorn rufus_server.main:app --reload
celery -A rufus.implementations.execution.celery worker --loglevel=info
```

---

## Architecture

### Core Components

**Workflow Class (`src/rufus/workflow.py`)** — Main class managing workflow lifecycle, state, and execution. Delegates to providers for persistence, execution, and observability. Handles all step types, directives, and control flow.

**WorkflowEngine (Legacy, `src/rufus/engine.py`)** — Being migrated to unified `Workflow` class. Contains orchestration logic including Saga pattern and dynamic injection.

**WorkflowBuilder (`src/rufus/builder.py`)** — Loads workflow definitions from YAML, resolves function/model paths via `importlib`, manages workflow registry and auto-discovers `rufus-*` packages, creates `Workflow` instances with dependency injection.

**Models (`src/rufus/models.py`)** — Pydantic-based data structures. `StepContext` provides context to step functions. `WorkflowStep` subclasses: `CompensatableStep`, `AsyncWorkflowStep`, `HttpWorkflowStep`, `ParallelWorkflowStep`, `FireAndForgetWorkflowStep`, `LoopStep`, `CronScheduleWorkflowStep`. Directives (as exceptions): `WorkflowJumpDirective`, `WorkflowPauseDirective`, `StartSubWorkflowDirective`, `SagaWorkflowException`.

### Provider Interfaces (`src/rufus/providers/`)

All external integrations are abstracted via Python Protocol interfaces:

- **PersistenceProvider** (`persistence.py`) — Workflow state, audit logs, task records. Methods: `save_workflow`, `get_workflow`, `claim_next_task`, etc.
- **ExecutionProvider** (`execution.py`) — Task execution environment. Methods: `dispatch_async_task`, `dispatch_parallel_tasks`, `dispatch_sub_workflow`, `report_child_status_to_parent`, `execute_sync_step_function`.
- **WorkflowObserver** (`observer.py`) — Workflow event hooks. Methods: `on_workflow_started`, `on_step_executed`, `on_workflow_completed`, `on_workflow_failed`, `on_workflow_status_changed`.
- **ExpressionEvaluator** (`expression_evaluator.py`) — Evaluates conditions for decision steps. Default: simple Python expression evaluation.
- **TemplateEngine** (`template_engine.py`) — Renders dynamic content from workflow state. Default: Jinja2.

### Default Implementations (`src/rufus/implementations/`)

**Persistence:** `postgres.py` (production), `sqlite.py` (development/testing), `memory.py` (testing), `redis.py`.

**Execution:** `sync.py` (simple/testing), `celery.py` (distributed async/parallel), `thread_pool.py` (thread-based parallel), `postgres_executor.py` (PostgreSQL task queue).

**Observability:** `logging.py` (console-based). **Templating:** `jinja2.py`. **Expression Evaluation:** `simple.py`.

### Workflow Configuration

**Registry** (`config/workflow_registry.yaml`) — Master list of available workflows. Each entry: `type`, `config_file`, `initial_state_model`. Optional `requires` key lists external `rufus-*` packages.

**Available Step Types:**

| Type | Description |
|------|-------------|
| `STANDARD` | Synchronous function execution |
| `ASYNC` | Long-running task via async executor (e.g., Celery) |
| `DECISION` | Can raise `WorkflowJumpDirective` to change flow |
| `PARALLEL` | Multiple tasks concurrently, results merged |
| `HTTP` | Call external services (polyglot workflows) |
| `LOOP` | Execute repeatedly over collection or until condition *(Phase 8)* |
| `FIRE_AND_FORGET` | Async execution without waiting *(Phase 8)* |
| `CRON_SCHEDULE` | Schedule step at specific times/intervals *(Phase 8)* |
| `HUMAN_IN_LOOP` | Pauses workflow, raises `WorkflowPauseDirective` |
| `AI_INFERENCE` | On-device ML inference (TFLite, ONNX) |
| `WASM` | Execute a pre-compiled WebAssembly binary via WASI; state passed as JSON on stdin, result read from stdout. Requires `wasmtime`. |

→ See [TECHNICAL_INFORMATION.md §1](/.claude/TECHNICAL_INFORMATION.md) for full YAML + Python examples.
→ See [TECHNICAL_INFORMATION.md §15](/.claude/TECHNICAL_INFORMATION.md) for WASM runtime details, module contract, and edge distribution.

---

## Key Patterns

### Adding a New Workflow

1. **Define State Model** — Pydantic `BaseModel` subclass with workflow fields
2. **Implement Step Functions** — Functions accepting `(state, context, **user_input) -> dict`
3. **Create Workflow YAML** — Define `workflow_type`, `initial_state_model`, `steps`
4. **Register** in `config/workflow_registry.yaml`

→ See [TECHNICAL_INFORMATION.md §1](/.claude/TECHNICAL_INFORMATION.md) for complete code examples.

### Step Function Signature

All step functions accept `(state: BaseModel, context: StepContext, **user_input) -> dict`. The returned dict is merged into workflow state.

→ See [TECHNICAL_INFORMATION.md §1](/.claude/TECHNICAL_INFORMATION.md) for full signature and examples.

### Control Flow Mechanisms

- **`automate_next: true`** — return value becomes input for next step automatically
- **`WorkflowJumpDirective`** — raise to branch to any step by name
- **`WorkflowPauseDirective`** — raise to pause workflow for human input
- **`StartSubWorkflowDirective`** — raise to spawn child workflow; parent resumes when child completes
- **Parallel YAML** — declare tasks list with `merge_strategy` and `merge_conflict_behavior`

→ See [TECHNICAL_INFORMATION.md §2](/.claude/TECHNICAL_INFORMATION.md) for code examples.

### Saga Pattern (Compensation)

Enable saga mode on a workflow instance. Define `compensate_function` alongside each step's `function` in YAML. On failure, compensations run in reverse order; status becomes `FAILED_ROLLED_BACK`.

→ See [TECHNICAL_INFORMATION.md §3](/.claude/TECHNICAL_INFORMATION.md) for code examples.

### Sub-Workflow Status Bubbling

Child workflows report status changes to parents:
- `PENDING_SUB_WORKFLOW` — child is running
- `WAITING_CHILD_HUMAN_INPUT` — child paused for input
- `FAILED_CHILD_WORKFLOW` — child failed
- Parent resumes when child completes; results in `state.sub_workflow_results[workflow_type]`

### Polyglot Support (HTTP Steps)

HTTP Steps enable Python-orchestrated workflows to call services in any language (Go, Rust, Node.js, etc.). Supports Jinja2 templating for dynamic URLs/headers/body, all HTTP methods, automatic JSON parsing, configurable timeouts.

**Architecture:** `Rufus Engine (Python) → HTTP/REST → External Services`

→ See [TECHNICAL_INFORMATION.md §5](/.claude/TECHNICAL_INFORMATION.md) for full YAML configs and multi-language pipeline example.

### Advanced Step Types (Phase 8)

| Type | Key Config | Use Cases |
|------|-----------|-----------|
| `LOOP` | `items`, `item_var`, `max_iterations`, `condition` | Batch processing, polling, retry logic |
| `FIRE_AND_FORGET` | `timeout_seconds`, `on_error` | Notifications, audit logging, analytics |
| `CRON_SCHEDULE` | `cron_expression`, `timezone`, `max_runs` | Reports, periodic sync, recurring payments |

**Best Practices:** Always set `max_iterations` on loops; only use Fire-and-Forget for non-critical ops; set `max_runs` for finite cron workflows; test with `SyncExecutionProvider`.

→ See [TECHNICAL_INFORMATION.md §4](/.claude/TECHNICAL_INFORMATION.md) for complete YAML configs, Python examples, and combined e-commerce example.

---

## Distributed Execution with Celery

### Architecture

```
┌─────────────────┐
│ Rufus API/CLI   │
└────────┬────────┘
         │
    ┌────▼─────┐
    │PostgreSQL│ ← Workflow State
    └────┬─────┘
         │
    ┌────▼─────┐
    │  Redis   │ ← Celery Broker/Backend
    └────┬─────┘
         │
    ┌────▼──────────────────┐
    │ Celery Workers (1-N)  │
    │ • Async Tasks         │
    │ • Parallel Execution  │
    │ • Sub-Workflows       │
    └───────────────────────┘
```

Celery enables distributed async/parallel execution. Workers auto-register with PostgreSQL for fleet management. Events published to Redis Streams/Pub-Sub for real-time monitoring.

**Execution flows:**
- **ASYNC step:** status → `PENDING_ASYNC` → task dispatched → worker completes → workflow resumes
- **PARALLEL step:** all tasks dispatched simultaneously → results merged per `merge_strategy`
- **Sub-workflow:** status → `PENDING_SUB_WORKFLOW` → child runs on worker → `resume_parent_from_child` when done

→ See [TECHNICAL_INFORMATION.md §6](/.claude/TECHNICAL_INFORMATION.md) for installation, config, worker commands, code examples, Docker Compose, Kubernetes YAML, troubleshooting, and performance tuning.

---

## Testing

Use in-memory persistence for unit tests. Set `TESTING=true` to run parallel tasks synchronously. Mock external services in step functions. Use `pytest` fixtures for common setup.

`TestHarness` provides a convenient wrapper with in-memory providers.

→ See [TECHNICAL_INFORMATION.md §7](/.claude/TECHNICAL_INFORMATION.md) for TestHarness usage, SQLite fixtures, and executor portability testing.

---

## Performance Optimizations

Enabled by default via environment variables (can be disabled for debugging):

| Optimization | Gain | Control |
|-------------|------|---------|
| **uvloop** event loop | 2–4× faster async I/O | `RUFUS_USE_UVLOOP=false` |
| **orjson** serialization | 3–5× faster JSON | `RUFUS_USE_ORJSON=false` |
| **PostgreSQL connection pool** | High concurrency | `POSTGRES_POOL_MIN_SIZE`, `POSTGRES_POOL_MAX_SIZE` |
| **Import caching** (`WorkflowBuilder._import_cache`) | 162× speedup | Automatic |

Pool defaults: min=10, max=50. Tune per workload (low: 5/20, medium: 10/50, high: 20/100).

→ See [TECHNICAL_INFORMATION.md §8](/.claude/TECHNICAL_INFORMATION.md) for code examples and benchmark results.

---

## Database Schema Management

Rufus uses **Alembic + SQLAlchemy** for schema migrations with a hybrid approach:
- **SQLAlchemy** for schema definition and migration generation (single source of truth)
- **Raw SQL** for all runtime queries (45% faster than SQLAlchemy Core)

**Migration workflow:**
1. Edit `src/rufus/db_schema/database.py` (SQLAlchemy table definitions)
2. `alembic revision --autogenerate -m "description"` — auto-detects changes (~15% false positive rate, always review)
3. Test migration: upgrade, downgrade, upgrade
4. Update raw SQL in persistence providers if needed
5. Commit both SQLAlchemy models + migration file

**Core tables managed by Alembic:** `workflow_executions`, `workflow_audit_log`, `workflow_metrics`, `workflow_heartbeats`, `alembic_version`, `edge_devices`, `device_commands`.

**Legacy systems (deprecated):** `migrations/schema.yaml` and `docker/init-db.sql` — use Alembic for all new deployments.

→ See [TECHNICAL_INFORMATION.md §9](/.claude/TECHNICAL_INFORMATION.md) for Alembic commands, SQLAlchemy table definition example, type mapping table, and deployment recipes.

---

## SQLite Persistence Provider

SQLite is included for development, testing, and edge deployments. No server required.

**Use when:** development, testing (in-memory), CI/CD, demos, single-server/edge deployments.

**Avoid when:** high concurrency (>50 concurrent writers), distributed systems, real-time LISTEN/NOTIFY.

**Key features:** WAL mode (auto-enabled), foreign key enforcement, automatic type conversions (UUID→TEXT, JSONB→TEXT, timestamps→ISO8601, booleans→0/1).

**Configuration:** `SQLitePersistenceProvider(db_path=":memory:", timeout=5.0, check_same_thread=False)`

→ See [TECHNICAL_INFORMATION.md §10](/.claude/TECHNICAL_INFORMATION.md) for usage examples, full integration, benchmarks, limitations/workarounds, and troubleshooting.

---

## Production Reliability Features

### Zombie Workflow Recovery

**Problem:** Worker crashes leave workflows stuck in `RUNNING` forever.

**Solution:** Heartbeat-based detection. `HeartbeatManager` (worker-side) sends periodic heartbeats. `ZombieScanner` (monitoring process) detects stale heartbeats and marks zombies as `FAILED_WORKER_CRASH`.

`HeartbeatManager` is used automatically via the execution provider, or manually for custom logic via `async with heartbeat:` context manager.

`ZombieScanner` runs as one-shot CLI (`rufus scan-zombies --fix`) or continuous daemon (`rufus zombie-daemon`).

**Config rule:** `Stale Threshold > 2 × Heartbeat Interval` to avoid false positives.

→ See [TECHNICAL_INFORMATION.md §11](/.claude/TECHNICAL_INFORMATION.md) for HeartbeatManager usage, ZombieScanner CLI/programmatic, DB schema, cron/systemd/Kubernetes deployment, and configuration table.

### Workflow Versioning (Definition Snapshots)

**Problem:** Deploying new YAML breaks running workflows.

**Solution:** Automatic snapshot of complete workflow config on `create_workflow()`. Running workflows use their snapshot; new workflows use latest YAML. Completely automatic — no code changes required.

Optional: add `workflow_version` to YAML for explicit version tracking. On breaking changes, bump `workflow_version` — running workflows (with old snapshot) are unaffected.

**Storage:** ~5–10 KB per workflow (JSONB in PostgreSQL, TEXT in SQLite).

→ See [TECHNICAL_INFORMATION.md §12](/.claude/TECHNICAL_INFORMATION.md) for snapshotting code, breaking changes strategy, version compatibility check, and troubleshooting SQL.

---

## Important Notes

- **Path Resolution:** All YAML paths resolved via `importlib.import_module`
- **State Serialization:** State must be JSON-serializable (Pydantic handles this)
- **Provider Injection:** All providers injected via `Workflow.__init__` or `WorkflowBuilder`
- **Async Execution:** Async steps dispatched to `ExecutionProvider`, not executed inline
- **Error Handling:** Uncaught exceptions set workflow status to `FAILED`
- **Parallel Merge Conflicts:** Logged as warnings when tasks return overlapping keys
- **Sub-Workflow Nesting:** Supports hierarchical composition with status propagation

### ⚠️ Executor Portability Warning

**CRITICAL:** Step functions must be **stateless and process-isolated**.

- **SyncExecutor:** All steps run in the same Python process — global/module-level state is shared.
- **CeleryExecutor:** Each step runs in a separate worker process — **no shared memory**.

**Rules:**
1. Store everything in workflow state (`state.field = value` persists to DB)
2. Return data from steps (returned dict merges into state automatically)
3. No global variables between steps
4. No module-level state between steps
5. Create resources (DB connections, API clients) fresh per step

Code that uses `global`, module-level variables, or relies on in-memory state from previous steps will break in Celery.

→ See [TECHNICAL_INFORMATION.md §13](/.claude/TECHNICAL_INFORMATION.md) for anti-patterns vs correct patterns.

### ⚠️ Dynamic Injection Caution

**WARNING:** Dynamic step injection makes workflows non-deterministic and hard to debug. Injected steps don't appear in YAML, breaking audit logs and compliance.

**Problems:** Audit logs reference steps not in YAML; Saga rollback must track injected steps; non-deterministic execution paths; version control can't reconstruct execution.

**Prefer instead:**
1. **DECISION steps** with explicit routes (all paths visible in YAML)
2. **Conditional logic** within a single step function
3. **Multiple workflow types** for distinct business paths

**Rare valid uses:** Plugin systems, multi-tenant custom validation, A/B testing, dynamic compliance.

→ See [TECHNICAL_INFORMATION.md §14](/.claude/TECHNICAL_INFORMATION.md) for problem illustration and recommended alternatives.

### Recent Migration (SDK Extraction)

This codebase was recently refactored from "Confucius" to "Rufus":
- Extracting core SDK from monolithic application
- Unified `Workflow` class (consolidating `WorkflowEngine`)
- Improved provider interfaces and dependency injection
- Better separation of concerns (SDK vs Server vs CLI)

Some legacy `confucius/` code still exists in the repo. Documentation may reference old patterns. Tests in `tests/sdk/` cover the new architecture.
