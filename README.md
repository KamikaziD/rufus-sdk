# Rufus SDK - Project Overview

## What is Rufus?

**Rufus** is a Python-native, SDK-first workflow orchestration engine designed for building and managing complex business processes and AI pipelines. It's a developer-friendly framework that emphasizes:

- **Declarative Configuration**: Define workflows in YAML, implement logic in Python
- **Embedded SDK Architecture**: Run workflows directly in your Python applications (no external server required)
- **Pluggable Architecture**: Swap out persistence, execution, and observability providers as needed
- **Production-Ready**: Built-in support for distributed execution, rollback patterns, and human-in-the-loop processes

---

## 🏗️ Architecture Components

### Core Package (`src/rufus/`)

The heart of the workflow engine consists of:

1. **`workflow.py`** - Main `Workflow` class managing lifecycle, state, and execution
2. **`builder.py`** - `WorkflowBuilder` that loads YAML definitions and creates workflow instances
3. **`models.py`** - Pydantic data models for steps, directives, and state management
4. **`engine.py`** - Legacy `WorkflowEngine` (being phased out in favor of unified `Workflow` class)

### Provider Interfaces (`src/rufus/providers/`)

All external integrations abstracted via Python Protocol interfaces:

- **`PersistenceProvider`** - How workflow state/logs are stored (PostgreSQL, SQLite, Redis, In-Memory)
- **`ExecutionProvider`** - Task execution environment (Sync, Celery, Thread Pool, Postgres-backed)
- **`WorkflowObserver`** - Event hooks for monitoring (Logging, NoOp)
- **`ExpressionEvaluator`** - Condition evaluation for decision steps
- **`TemplateEngine`** - Dynamic content rendering (Jinja2)

### Default Implementations (`src/rufus/implementations/`)

Ready-to-use implementations:

```
implementations/
├── persistence/       # postgres.py, redis.py, memory.py
├── execution/         # sync.py, celery.py, thread_pool.py, postgres_executor.py
├── observability/     # logging.py, noop.py
├── templating/        # jinja2.py
├── expression_evaluator/  # simple.py
└── security/          # secrets_provider.py, crypto_utils.py, semantic_firewall.py
```

### Additional Packages

- **`src/rufus_cli/`** - Command-line tool (`rufus validate`, `rufus run`)
- **`src/rufus_server/`** - Optional FastAPI REST API wrapper for workflows

### Database & Tooling

```
migrations/                 # Database schema definitions
├── schema.yaml            # Unified schema specification
├── 002_postgres_standardized.sql
├── 002_sqlite_initial.sql
└── README.md

tools/                      # Development tools
├── compile_schema.py      # Generate DB-specific SQL from YAML
├── validate_schema.py     # Validate schema consistency
└── migrate.py             # Migration management
```

---

## 🎯 Key Features

### 1. **Step Types**
- **STANDARD** - Synchronous execution
- **ASYNC** - Distributed async execution (via Celery, etc.)
- **PARALLEL** - Run multiple tasks concurrently
- **DECISION** - Conditional branching
- **LOOP** - Iterate over collections
- **HTTP** - HTTP request steps
- **FIRE_AND_FORGET** - Non-blocking execution
- **CRON_SCHEDULE** - Scheduled execution

### 2. **Workflow Control Flow**

**Automated Step Chaining**
```yaml
- name: "Process_Data"
  automate_next: true  # Automatically proceeds to next step
```

**Conditional Branching**
```python
raise WorkflowJumpDirective(target_step_name="Approval_Step")
```

**Human-in-the-Loop**
```python
raise WorkflowPauseDirective(result={"awaiting_approval": True})
```

**Sub-Workflows**
```python
raise StartSubWorkflowDirective(
    workflow_type="ChildWorkflow",
    initial_data={...}
)
```

### 3. **Saga Pattern (Compensation)**

Automatic rollback for distributed transactions:

```yaml
- name: "Charge_Payment"
  function: "payments.charge"
  compensate_function: "payments.refund"  # Called on failure
```

Enable saga mode:
```python
workflow.enable_saga_mode()
```

### 4. **Dynamic Step Injection**

Add steps at runtime based on state:

```yaml
dynamic_injection:
  rules:
    - condition_key: "loan_amount"
      value_match: "high"
      action: "INSERT_AFTER_CURRENT"
      steps_to_insert: [...]
```

### 5. **Parallel Execution with Merge Strategies**

```yaml
- name: "Parallel_Tasks"
  type: "PARALLEL"
  tasks:
    - name: "Credit_Check"
      function: "credit.check"
    - name: "Fraud_Detection"
      function: "fraud.detect"
  merge_strategy: "SHALLOW"  # or DEEP
  merge_conflict_behavior: "PREFER_NEW"  # or PREFER_OLD, RAISE_ERROR
  allow_partial_success: true
```

---

## ⚡ Performance Optimizations

Rufus SDK includes **Phase 1 performance optimizations** for production workloads:

### Built-in Optimizations

1. **uvloop Event Loop** (2-4x faster async I/O)
   - Automatically enabled by default
   - Drop-in replacement for stdlib `asyncio`
   - Disable with `RUFUS_USE_UVLOOP=false`

2. **orjson Serialization** (3-5x faster JSON)
   - High-performance Rust-based JSON library
   - Used for all state persistence and API responses
   - Disable with `RUFUS_USE_ORJSON=false`

3. **Optimized PostgreSQL Connection Pool**
   - Default: 10-50 connections (tuned for high concurrency)
   - Configurable via environment variables:
     ```bash
     POSTGRES_POOL_MIN_SIZE=10
     POSTGRES_POOL_MAX_SIZE=50
     POSTGRES_POOL_COMMAND_TIMEOUT=10
     ```

4. **Import Caching** (162x speedup for repeated step functions)
   - Automatic caching of imported step functions
   - Reduces overhead by 5-10ms per step execution

### Benchmark Results

Run benchmarks: `python tests/benchmarks/workflow_performance.py`

```
JSON Serialization: 2,453,971 ops/sec (orjson)
Import Caching: 162x speedup for cached imports
Async Latency: 5.5µs p50, 12.7µs p99 (uvloop)
```

### Expected Production Gains

- **+50-100% throughput** for I/O-bound workflows
- **-30-40% latency** for async operations
- **-80% serialization time** for state persistence
- **Minimal memory overhead** (<5% increase)

All optimizations are backwards compatible and can be disabled via environment variables.

---

## 🗄️ Database Schema Management

Rufus uses a **unified schema definition** system to support multiple databases (PostgreSQL and SQLite) without schema divergence.

### Multi-Database Support

- **PostgreSQL** - Production-ready with full feature support (LISTEN/NOTIFY, advanced indexing, triggers)
- **SQLite** - Embedded database for development, testing, and single-server deployments

### Schema Standardization Architecture

All database schemas are generated from a single source of truth:

```
migrations/schema.yaml (unified definition)
           │
    ┌──────┴──────┐
    ▼             ▼
PostgreSQL     SQLite
 .sql files    .sql files
```

**Key Components:**

1. **`migrations/schema.yaml`** - Database-agnostic schema definition
   - Unified type system (uuid, jsonb, timestamp, etc.)
   - Automatic type mapping for each database
   - Tables, indexes, triggers, views, constraints

2. **`tools/compile_schema.py`** - Schema compiler
   - Generates database-specific SQL from YAML
   - Handles type conversions (JSONB→TEXT for SQLite)
   - Preserves database-specific optimizations

3. **`tools/validate_schema.py`** - Schema validation
   - Ensures generated SQL matches specifications
   - Verifies type mappings are correct
   - Validates completeness across databases

4. **`tools/migrate.py`** - Migration management
   - Tracks applied migrations via `schema_migrations` table
   - Applies pending migrations in order
   - Supports both PostgreSQL and SQLite

### Type Mappings

| Unified Type | PostgreSQL | SQLite |
|--------------|------------|--------|
| uuid | UUID | TEXT |
| jsonb | JSONB | TEXT |
| timestamp | TIMESTAMPTZ | TEXT (ISO8601) |
| boolean | BOOLEAN | INTEGER (0/1) |
| bigserial | BIGSERIAL | INTEGER AUTOINCREMENT |

### Usage

**Generate migrations from schema:**
```bash
python tools/compile_schema.py --all
```

**Validate schema:**
```bash
python tools/validate_schema.py --all
```

**Apply migrations:**
```bash
# PostgreSQL
python tools/migrate.py --db postgres://user:pass@localhost/rufus --up

# SQLite
python tools/migrate.py --db sqlite:///rufus.db --up
```

**Use SQLite for development:**
```python
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider

persistence = SQLitePersistenceProvider(db_path=":memory:")  # In-memory
# or
persistence = SQLitePersistenceProvider(db_path="rufus.db")  # File-based
```

### Schema Validation Results

```
PostgreSQL: ✅ 6 tables, 18 indexes, 4 triggers, 2 views
SQLite:     ✅ 6 tables, 18 indexes, 3 triggers, 2 views
            ✅ Full type mapping validation
```

All schema changes are made in `schema.yaml` and automatically compiled to database-specific SQL, ensuring consistency across databases.

See [migrations/README.md](migrations/README.md) for detailed schema management documentation.

---

## 📝 How Workflows Work

### 1. Define State Model
```python
from pydantic import BaseModel

class MyWorkflowState(BaseModel):
    user_id: str
    status: Optional[str] = None
```

### 2. Implement Step Functions
```python
from rufus.models import StepContext

def process_data(state: MyWorkflowState, context: StepContext) -> dict:
    state.status = "processing"
    return {"processed": True}
```

### 3. Define Workflow in YAML
```yaml
workflow_type: "MyWorkflow"
initial_state_model: "my_app.state_models.MyWorkflowState"

steps:
  - name: "Process_Data"
    type: "STANDARD"
    function: "my_app.steps.process_data"
    automate_next: true
```

### 4. Execute with SDK
```python
from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.execution.sync import SyncExecutor

# Initialize SQLite persistence (in-memory for testing)
persistence = SQLitePersistenceProvider(db_path=":memory:")
await persistence.initialize()

builder = WorkflowBuilder(
    registry_path="workflow_registry.yaml",
    persistence_provider=persistence,
    execution_provider=SyncExecutor()
)

workflow = builder.create_workflow(
    "MyWorkflow",
    initial_data={"user_id": "123"}
)

# Execute steps
while workflow.status == "ACTIVE":
    result = workflow.next_step(user_input={})
```

**Alternative persistence options:**
```python
# PostgreSQL (production)
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
persistence = PostgresPersistenceProvider(db_url="postgresql://...")

# SQLite file-based (development)
persistence = SQLitePersistenceProvider(db_path="workflows.db")

# In-memory (testing)
from rufus.implementations.persistence.memory import InMemoryPersistence
persistence = InMemoryPersistence()
```

---

## 🚀 Getting Started

### Installation
```bash
pip install -r requirements.txt
```

### Run Tests
```bash
pytest
```

### Validate a Workflow
```bash
rufus validate config/my_workflow.yaml
```

### Run a Workflow Locally
```bash
rufus run config/my_workflow.yaml -d '{"field": "value"}'
```

### Start FastAPI Server (Optional)
```bash
uvicorn rufus_server.main:app --reload
```

---

## 📚 Examples

### **Quickstart** (`examples/quickstart/`)
Simple greeting workflow demonstrating:
- Basic state management
- Step function implementation
- YAML configuration
- SDK execution

### **Loan Application** (`examples/loan_application/`)
Production-ready loan processing workflow with:
- Parallel risk assessment (credit check + fraud detection)
- Conditional branching (fast-track vs detailed review)
- Dynamic step injection (simplified vs full underwriting)
- Human-in-the-loop approval
- Saga compensation patterns
- Sub-workflow integration (KYC verification)

---

## 🧪 Testing

```bash
# Run all tests with coverage
pytest

# Run specific test module
pytest tests/sdk/test_workflow.py

# Run single test
pytest tests/sdk/test_workflow.py::test_workflow_initialization
```

Tests automatically exclude legacy `confucius/` and `original_implementation_files/` directories.

---

## 📦 Project Status

**Current State**: Alpha (v0.1.0)

### Recent Updates

**✅ Phase 1 Performance Optimizations (Completed)**
- uvloop integration (2-4x async I/O speedup)
- orjson serialization (3-5x faster JSON)
- Optimized PostgreSQL connection pooling
- Import caching (162x speedup)
- Comprehensive benchmarking suite

**✅ Phase 1 Database Schema Standardization (Completed)**
- Unified schema definition system (`schema.yaml`)
- Multi-database support (PostgreSQL + SQLite)
- Automated schema compilation and validation
- Migration management tooling
- 20 unit tests for schema compiler

**✅ Phase 2 SQLitePersistenceProvider (Completed)**
- Full SQLite persistence implementation (800+ lines)
- All 20 PersistenceProvider methods
- In-memory and file-based modes
- 14 unit tests + 6 integration tests (all passing)
- WAL mode, foreign keys, idempotency support

**Recent Migration**: The project was recently refactored from "Confucius" to "Rufus" with focus on:
- Extracting core SDK from monolithic application
- Unified `Workflow` class architecture
- Improved provider interfaces and dependency injection
- Better separation: Core SDK vs Server vs CLI
- Enhanced sub-workflow status propagation

**Next**: Phase 3 production testing and documentation

**Note**: Some legacy `confucius/` code still exists in the repo for reference.

---

## 🎯 Use Cases

- **Business Process Automation** - Order processing, approval workflows, onboarding
- **AI/ML Pipelines** - Multi-stage AI agent orchestration
- **Distributed Transactions** - Saga pattern for microservices coordination
- **Human-AI Collaboration** - Workflows combining automated steps with human review
- **Event-Driven Systems** - Complex event processing with state management

---

## 🔑 Key Design Principles

1. **SDK-First**: Embed workflows directly in Python apps (no mandatory external server)
2. **Separation of Concerns**: Workflow definition (YAML) separate from implementation (Python)
3. **Provider Abstraction**: Swap persistence/execution/observability without code changes
4. **Type Safety**: Pydantic models for validation and IDE autocomplete
5. **Developer Experience**: Declarative YAML + Pythonic step functions

---

## 📖 Documentation

### Core Documentation
- **[CLAUDE.md](CLAUDE.md)** - Detailed project guidance for AI assistants
- **[USAGE_GUIDE.md](USAGE_GUIDE.md)** - Comprehensive usage documentation
- **[YAML_GUIDE.md](YAML_GUIDE.md)** - Complete YAML workflow syntax reference
- **[API_REFERENCE.md](API_REFERENCE.md)** - SDK API documentation
- **[CLI_REFERENCE.md](CLI_REFERENCE.md)** - Command-line tool documentation
- **[TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md)** - Architecture deep-dive

### Database & Operations
- **[migrations/README.md](migrations/README.md)** - Database schema management guide
- **[SQLITE_IMPLEMENTATION_PLAN.md](SQLITE_IMPLEMENTATION_PLAN.md)** - SQLite integration roadmap
- **[PERFORMANCE_OPTIMIZATION_PLAN.md](PERFORMANCE_OPTIMIZATION_PLAN.md)** - Performance optimization strategy

---

This is a robust, production-oriented workflow engine designed for Python developers who need sophisticated orchestration without the complexity of heavyweight workflow systems like Temporal or Airflow. Perfect for embedding workflows directly into applications while maintaining flexibility for distributed execution when needed.
