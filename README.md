# Rufus - Python-Native Workflow Orchestration Engine

**Rufus** is a production-ready, SDK-first workflow engine for building and orchestrating complex business processes and AI pipelines. Unlike heavyweight systems like Temporal or Airflow, Rufus embeds directly into your Python applications while maintaining the flexibility to scale to distributed execution when needed.

```python
# Define workflows in YAML
workflow_type: "OrderProcessing"
steps:
  - name: "Process_Payment"
    type: "STANDARD"
    function: "payments.charge"
    compensate_function: "payments.refund"  # Saga pattern
    automate_next: true

# Execute with embedded SDK
workflow = builder.create_workflow("OrderProcessing", initial_data)
result = await workflow.next_step()
```

---

## 🎯 Why Rufus?

### The Problem with Existing Solutions

**Temporal/Cadence**: Heavyweight infrastructure, complex deployment, high operational overhead
**Airflow**: Designed for batch jobs, not real-time workflows
**AWS Step Functions**: Vendor lock-in, expensive, limited flexibility
**Custom Solutions**: Reinventing the wheel, maintaining orchestration logic

### The Rufus Approach

✅ **Embedded SDK** - Run workflows in-process, no external server required
✅ **YAML + Python** - Declarative workflows, imperative logic
✅ **Pluggable Architecture** - Swap persistence, execution, observability providers
✅ **Production-Ready** - Saga pattern, human-in-the-loop, sub-workflows, parallel execution
✅ **Developer-Friendly** - Type-safe, validated, testable, with CLI tooling

---

## 🚀 Quick Start (30 seconds)

### Installation

```bash
pip install -r requirements.txt  # Includes SQLite support by default
```

### Run Your First Workflow

```bash
# Validate a workflow
rufus validate examples/quickstart/greeting_workflow.yaml

# Run it locally (in-memory)
rufus run examples/quickstart/greeting_workflow.yaml -d '{"name": "World"}'

# Output:
# Workflow ID: wf_abc123
# Status: COMPLETED
# Result: {"greeting": "Hello, World!"}
```

### Try the SQLite Task Manager Example

Zero setup, no database server needed:

```bash
python examples/sqlite_task_manager/simple_demo.py
```

This demonstrates:
- In-memory SQLite database (`:memory:`)
- Human-in-the-loop approval workflow
- Workflow pause/resume with user input
- Complete workflow lifecycle

---

## 📦 What's Inside

Rufus consists of three main components:

### 1. Core SDK (`src/rufus/`)

The embedded workflow engine library for Python applications.

**Key Features**:
- **Workflow orchestration** with state management
- **8+ step types**: STANDARD, ASYNC, PARALLEL, DECISION, LOOP, HTTP, FIRE_AND_FORGET, CRON_SCHEDULER
- **Control flow**: Automated chaining, conditional branching, sub-workflows, human-in-the-loop
- **Saga pattern**: Automatic compensation and rollback
- **Provider interfaces**: Pluggable persistence, execution, observability
- **Type-safe**: Pydantic models for validation

**Example**:
```python
from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.execution.sync import SyncExecutionProvider

# Initialize with SQLite (or PostgreSQL, Redis, In-Memory)
persistence = SQLitePersistenceProvider(db_path=":memory:")
await persistence.initialize()

builder = WorkflowBuilder(
    registry_path="workflow_registry.yaml",
    persistence_provider=persistence,
    execution_provider=SyncExecutionProvider()
)

# Create and execute workflow
workflow = builder.create_workflow("OrderProcessing", initial_data={"order_id": "123"})
while workflow.status == "ACTIVE":
    result = await workflow.next_step(user_input={})
```

### 2. CLI Tool (`src/rufus_cli/`)

Comprehensive command-line interface with 21 commands across 4 categories.

**Features**:
- **Validation**: JSON Schema-based with IDE autocomplete support
- **Workflow management**: List, start, resume, retry, cancel workflows
- **Database operations**: Initialize, migrate, validate schema
- **Monitoring**: View logs, metrics, execution traces
- **Configuration**: Persistent settings in `~/.rufus/config.yaml`

**Command Categories**:

```bash
# Configuration (6 commands)
rufus config show               # Show current configuration
rufus config set-persistence    # Set database (SQLite/PostgreSQL)
rufus config set-execution      # Set executor (sync/thread_pool/celery)

# Workflow Management (8 commands)
rufus list --status ACTIVE      # List workflows
rufus start OrderProcessing -d '{"customer_id": "123"}'
rufus show <workflow-id> --state --logs
rufus resume <workflow-id> --input '{"approved": true}'
rufus retry <workflow-id> --from-step Process_Payment
rufus logs <workflow-id> --level ERROR
rufus metrics --summary
rufus cancel <workflow-id>

# Database Management (5 commands)
rufus db init                   # Initialize schema
rufus db migrate                # Apply migrations
rufus db status                 # Check migration status
rufus db stats                  # Database statistics
rufus db validate               # Validate schema integrity

# Validation & Testing (2 commands)
rufus validate workflow.yaml --strict  # Enhanced validation
rufus run workflow.yaml -d '{}'        # Local testing
```

**Enhanced Validation**:
```bash
$ rufus validate order_workflow.yaml --strict
✓ Successfully validated order_workflow.yaml

# Catches errors before runtime:
# - Missing dependencies
# - Invalid function imports
# - Schema violations
# - Type mismatches
```

See [docs/CLI_USAGE_GUIDE.md](docs/CLI_USAGE_GUIDE.md) for complete CLI documentation.

### 3. Server (Optional) (`src/rufus_server/`)

FastAPI REST API wrapper for workflows when you need HTTP access.

**Features**:
- RESTful API for workflow operations
- OpenAPI/Swagger documentation
- Authentication/authorization hooks
- Health checks and metrics endpoints

**Start Server**:
```bash
uvicorn rufus_server.main:app --reload
```

**API Endpoints**:
```bash
POST   /workflows              # Create workflow
GET    /workflows/{id}         # Get workflow details
POST   /workflows/{id}/next    # Execute next step
GET    /workflows              # List workflows
DELETE /workflows/{id}         # Cancel workflow
```

---

## 🏗️ Architecture

### Provider-Based Design

Rufus uses Python Protocol interfaces to decouple core logic from external dependencies:

```
┌─────────────────────────────────────────┐
│         Your Application                │
│  ┌───────────────────────────────────┐  │
│  │      Workflow (YAML + Python)     │  │
│  └───────────────┬───────────────────┘  │
│                  │                       │
│  ┌───────────────▼───────────────────┐  │
│  │       WorkflowBuilder/Engine      │  │
│  └───────────────┬───────────────────┘  │
│                  │                       │
│     ┌────────────┼────────────┐         │
│     ▼            ▼             ▼         │
│  Persistence  Execution   Observability │
│  Provider     Provider      Provider    │
└─────┬────────────┬─────────────┬────────┘
      │            │             │
  ┌───▼───┐    ┌───▼───┐     ┌──▼──┐
  │  DB   │    │Workers│     │Logs │
  └───────┘    └───────┘     └─────┘
```

### Built-In Implementations

**Persistence Providers**:
- `PostgresPersistenceProvider` - Production-ready with JSONB, connection pooling
- `SQLitePersistenceProvider` - Embedded database for development/testing
- `RedisPersistenceProvider` - Redis-backed state storage
- `InMemoryPersistence` - Fast in-memory storage for testing

**Execution Providers**:
- `SyncExecutionProvider` - Single-process synchronous execution
- `CeleryExecutor` - Distributed async execution via Celery workers
- `ThreadPoolExecutionProvider` - Thread-based parallel execution
- `PostgresExecutor` - PostgreSQL-backed task queue

**Observability Providers**:
- `LoggingObserver` - Console-based event logging
- `NoOpObserver` - Silent mode for testing
- (Extensible for metrics systems like Prometheus, DataDog)

**Template Engines**:
- `Jinja2TemplateEngine` - Dynamic content rendering

**Expression Evaluators**:
- `SimpleExpressionEvaluator` - Python expression evaluation for conditions

---

## ⚡ Performance & Optimizations

### Performance Model

Rufus uses an **embedded SDK architecture** that eliminates central orchestrator overhead:

| Architecture | Orchestrator Hop | Persistence Hop | Network Calls/Step |
|--------------|------------------|-----------------|-------------------|
| **Temporal/Cadence** | Yes (2x network) | Yes (2x) | **4 per step** |
| **Rufus + PostgreSQL** | ❌ No | Yes (2x) | **2 per step** |
| **Rufus + SQLite** | ❌ No | Local I/O only | **0 network** |
| **Rufus + In-Memory** | ❌ No | ❌ No | **0** |

**Key Advantage**: Workflows execute **in-process**, avoiding the Worker → Orchestrator → Worker round-trip that centralized systems require. With PostgreSQL, you still have database I/O (load state, save state), but you eliminate the orchestrator bottleneck.

### Built-In Optimizations

1. **uvloop Event Loop** (2-4x faster async I/O)
   - Automatically enabled by default
   - Drop-in replacement for stdlib `asyncio`

2. **orjson Serialization** (3-5x faster JSON)
   - High-performance Rust-based JSON library
   - Used for all state persistence

3. **Optimized PostgreSQL Connection Pool**
   - Default: 10-50 connections (tuned for high concurrency)
   - Configurable via environment variables

4. **Import Caching** (162x speedup)
   - Automatic caching of imported step functions
   - Reduces overhead by 5-10ms per step

### Benchmark Results

```
JSON Serialization: 2,453,971 ops/sec (orjson)
Import Caching: 162x speedup for cached imports
Async Latency: 5.5µs p50, 12.7µs p99 (uvloop)
SQLite Workflows: ~9,000 ops/sec (in-memory)
```

### Expected Production Gains

- **+50-100% throughput** for I/O-bound workflows
- **-30-40% latency** for async operations
- **-80% serialization time** for state persistence
- **-50% network overhead** vs. centralized orchestrators

All optimizations are backwards compatible and can be disabled via environment variables.

---

## 🎨 Workflow Features

### Step Types

**STANDARD** - Synchronous execution
```yaml
- name: "Process_Order"
  type: "STANDARD"
  function: "orders.process"
  automate_next: true
```

**ASYNC** - Distributed async execution (Celery/threads)
```yaml
- name: "Send_Email"
  type: "ASYNC"
  function: "notifications.send_email"
```

**PARALLEL** - Concurrent execution with merge strategies
```yaml
- name: "Risk_Assessment"
  type: "PARALLEL"
  tasks:
    - name: "Credit_Check"
      function: "credit.check"
    - name: "Fraud_Detection"
      function: "fraud.detect"
  merge_strategy: "SHALLOW"
  merge_conflict_behavior: "PREFER_NEW"
```

**DECISION** - Conditional branching
```yaml
- name: "Check_Amount"
  type: "DECISION"
  function: "checks.amount"
  routes:
    - condition: "state.amount > 10000"
      target: "High_Value_Review"
    - condition: "state.amount <= 10000"
      target: "Standard_Processing"
```

**LOOP** - Iterate over collections or conditions
```yaml
- name: "Process_Items"
  type: "LOOP"
  mode: "ITERATE"
  iterate_over: "state.items"
  loop_body:
    - name: "Update_Inventory"
      function: "inventory.update"
```

**HTTP** - HTTP API calls
```yaml
- name: "Call_External_API"
  type: "HTTP"
  http_config:
    url: "https://api.example.com/process"
    method: "POST"
    headers:
      Authorization: "Bearer {{state.api_token}}"
```

**FIRE_AND_FORGET** - Non-blocking sub-workflow launch
```yaml
- name: "Trigger_Analytics"
  type: "FIRE_AND_FORGET"
  target_workflow_type: "AnalyticsPipeline"
  initial_data_template:
    user_id: "{{state.user_id}}"
```

**CRON_SCHEDULER** - Scheduled recurring workflows
```yaml
- name: "Schedule_Weekly_Report"
  type: "CRON_SCHEDULER"
  cron_expression: "0 9 * * MON"
  target_workflow_type: "WeeklyReport"
```

### Control Flow Mechanisms

**Automated Step Chaining**:
```yaml
automate_next: true  # Automatically proceeds to next step
```

**Conditional Branching**:
```python
raise WorkflowJumpDirective(target_step_name="Approval_Step")
```

**Human-in-the-Loop**:
```python
raise WorkflowPauseDirective(result={"awaiting_approval": True})
```

**Sub-Workflows**:
```python
raise StartSubWorkflowDirective(
    workflow_type="KYC",
    initial_data={"user_id": state.user_id}
)
```

### Saga Pattern (Distributed Transactions)

Automatic rollback for distributed transactions:

```yaml
steps:
  - name: "Reserve_Inventory"
    function: "inventory.reserve"
    compensate_function: "inventory.release"  # Called on failure

  - name: "Charge_Payment"
    function: "payments.charge"
    compensate_function: "payments.refund"  # Called on failure
```

Enable saga mode:
```python
workflow.enable_saga_mode()
```

On failure, compensation functions execute in reverse order automatically.

---

## 💾 Database Support

### Multi-Database Architecture

Rufus uses a **unified schema definition** system to support multiple databases without schema divergence.

**Supported Databases**:

**PostgreSQL** (Production):
- Full feature support
- LISTEN/NOTIFY for real-time updates
- Advanced indexing (GIN, partial indexes)
- Triggers and stored procedures
- Connection pooling
- Recommended for >100 concurrent workflows

**SQLite** (Development/Testing):
- Embedded database (no server needed)
- Fast in-memory mode (`:memory:`)
- Single-file portability
- WAL mode for better concurrency
- Zero setup friction
- Recommended for <50 concurrent workflows

### Schema Management

All schemas generated from a single source of truth:

```
migrations/schema.yaml (unified definition)
           │
    ┌──────┴──────┐
    ▼             ▼
PostgreSQL     SQLite
 .sql files    .sql files
```

**Tools**:
```bash
# Generate migrations from schema
python tools/compile_schema.py --all

# Validate schema consistency
python tools/validate_schema.py --all

# Apply migrations
python tools/migrate.py --db postgresql://... --up
python tools/migrate.py --db sqlite:///workflows.db --up
```

### Usage Examples

**PostgreSQL (Production)**:
```python
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider

persistence = PostgresPersistenceProvider(
    db_url="postgresql://user:pass@localhost/rufus",
    pool_min_size=10,
    pool_max_size=50
)
```

**SQLite (Development)**:
```python
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider

# In-memory (testing)
persistence = SQLitePersistenceProvider(db_path=":memory:")

# File-based (development)
persistence = SQLitePersistenceProvider(db_path="workflows.db")
```

**In-Memory (Testing)**:
```python
from rufus.implementations.persistence.memory import InMemoryPersistence

persistence = InMemoryPersistence()
```

---

## 🔍 YAML Validation & IDE Support

### Enhanced Validation

Rufus includes JSON Schema-based validation with IDE autocomplete support:

**Basic Validation**:
```bash
$ rufus validate order_workflow.yaml
✓ Successfully validated order_workflow.yaml
```

**Strict Validation** (checks function imports):
```bash
$ rufus validate order_workflow.yaml --strict
✗ Validation failed

3 Error(s):
  1. Step 'Process_Payment': dependency 'Validate_Order' does not exist
  2. Step_A: Cannot import function module 'nonexistent.module'
  3. State model 'OrderState' not found in module 'state_models'
```

**JSON Output** (CI/CD integration):
```bash
$ rufus validate workflow.yaml --json
{
  "valid": true,
  "file": "workflow.yaml",
  "errors": [],
  "warnings": []
}
```

### IDE Autocomplete

Add to your workflow YAML files:

```yaml
# yaml-language-server: $schema=../../schema/workflow_schema.json
workflow_type: "MyWorkflow"
steps:
  - name: "My_Step"
    type: "STANDARD"  # Autocomplete suggests all step types
    function: "module.function"
```

**Supported IDEs**:
- VS Code (with YAML extension)
- IntelliJ IDEA / PyCharm
- Sublime Text (with LSP-yaml)

**Features**:
- ✅ Autocomplete for step types, merge strategies, etc.
- ✅ Validation warnings for missing fields
- ✅ Hover documentation for all fields
- ✅ Error highlighting for invalid values
- ✅ Real-time syntax checking

See [schema/README.md](schema/README.md) for complete IDE setup guide.

---

## ⚠️ Production Best Practices

### Critical: Executor Portability

**THE PROBLEM**: Step functions must be **stateless and process-isolated** to work across all execution providers.

Code that works with `SyncExecutionProvider` (single process) often breaks with `CeleryExecutor` (distributed processes) due to shared state.

**❌ BREAKS in Distributed Execution**:
```python
# Global state lost between steps
global_cache = {}

def step_a(state, context):
    global_cache['data'] = expensive_computation()
    return {}

def step_b(state, context):
    data = global_cache['data']  # KeyError in Celery!
    return {"result": process(data)}
```

**✅ WORKS Everywhere**:
```python
# Store in workflow state - persisted to database
def step_a(state, context):
    data = expensive_computation()
    state.cached_data = data  # Persisted
    return {"cached_data": data}

def step_b(state, context):
    data = state.cached_data  # Loaded from DB
    return {"result": process(data)}
```

**5 Golden Rules**:
1. **Store everything in workflow state** - `state.field = value`
2. **Return data from steps** - Return dict merges into state
3. **No global variables** - Each step is isolated
4. **No module-level state** - Don't rely on `_module_var`
5. **Create resources per step** - DB connections, API clients created fresh each time

**Test for Portability**:
```python
@pytest.mark.parametrize("executor", [
    SyncExecutionProvider(),
    ThreadPoolExecutionProvider()
])
def test_workflow_portable(executor):
    builder = WorkflowBuilder(execution_provider=executor)
    workflow = builder.create_workflow("MyWorkflow", initial_data={})
    # Should work with both executors
```

See [CLAUDE.md](CLAUDE.md) for detailed warnings and examples.

### Caution: Dynamic Injection

**WARNING**: Dynamic step injection makes workflows **non-deterministic** and hard to debug.

**Recommended Alternatives**:
- Use **DECISION steps** with explicit routes (visible in YAML)
- Use **conditional logic** within step functions
- Use **multiple workflow versions** (OrderProcessing_v1, OrderProcessing_v2)

Only use dynamic injection for rare cases like plugin systems, multi-tenant workflows, or A/B testing.

See [USAGE_GUIDE.md](USAGE_GUIDE.md) for detailed best practices.

---

## 📚 Examples

### SQLite Task Manager (`examples/sqlite_task_manager/`)

Zero-setup workflow example using embedded SQLite:
- In-memory database (no PostgreSQL required)
- Human-in-the-loop approval workflow
- Task creation, assignment, and completion
- Workflow pause/resume with user input

**Run**: `python examples/sqlite_task_manager/simple_demo.py`

### Loan Application (`examples/loan_application/`)

Production-ready loan processing workflow with:
- Parallel risk assessment (credit check + fraud detection)
- Conditional branching (fast-track vs detailed review)
- Dynamic step injection (simplified vs full underwriting)
- Human-in-the-loop approval
- Saga compensation patterns
- Sub-workflow integration (KYC verification)

### FastAPI Integration (`examples/fastapi_api/`)

Complete REST API for order processing:
- FastAPI server with workflow endpoints
- Order processing with inventory management
- Payment processing with compensation
- Saga pattern for distributed transactions

### Flask Integration (`examples/flask_api/`)

Flask-based API wrapper for workflows:
- Blueprint-based organization
- RESTful workflow operations
- JSON serialization
- Error handling

---

## 🧪 Testing

### Running Tests

```bash
# Run all tests with coverage
pytest

# Run specific test module
pytest tests/sdk/test_workflow.py

# Run with verbose output
pytest -v

# Run single test
pytest tests/sdk/test_workflow.py::test_workflow_initialization
```

### Test Harness

```python
from rufus.testing.harness import TestHarness

# Create test harness with in-memory providers
harness = TestHarness()

# Start workflow
workflow = harness.start_workflow(
    workflow_type="MyWorkflow",
    initial_data={"user_id": "123"}
)

# Execute next step
result = harness.next_step(workflow.id, user_input={"param": "value"})

# Check state
assert workflow.state.status == "completed"
```

### Testing Best Practices

- Use in-memory persistence for unit tests
- Set `TESTING=true` to run parallel tasks synchronously
- Mock external services in step functions
- Use `pytest` fixtures for common setup
- Test with multiple executors to ensure portability

---

## 📖 Documentation

### Core Documentation

- **[CLAUDE.md](CLAUDE.md)** - Complete developer guide with critical warnings
- **[USAGE_GUIDE.md](USAGE_GUIDE.md)** - Comprehensive usage documentation and best practices
- **[YAML_GUIDE.md](YAML_GUIDE.md)** - Complete YAML workflow syntax reference
- **[API_REFERENCE.md](API_REFERENCE.md)** - SDK API documentation
- **[TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md)** - Architecture deep-dive

### CLI & Tools

- **[docs/CLI_USAGE_GUIDE.md](docs/CLI_USAGE_GUIDE.md)** - Complete CLI command reference
- **[docs/CLI_QUICK_REFERENCE.md](docs/CLI_QUICK_REFERENCE.md)** - One-page CLI cheat sheet
- **[schema/README.md](schema/README.md)** - JSON Schema and IDE integration guide

### Database & Operations

- **[migrations/README.md](migrations/README.md)** - Database schema management guide
- **[SQLITE_IMPLEMENTATION_PLAN.md](SQLITE_IMPLEMENTATION_PLAN.md)** - SQLite integration details
- **[PERFORMANCE_OPTIMIZATION_PLAN.md](PERFORMANCE_OPTIMIZATION_PLAN.md)** - Performance optimization strategy

### Architecture & Planning

- **[ARCHITECTURE_REVIEW_RESPONSE.md](ARCHITECTURE_REVIEW_RESPONSE.md)** - Tier 1 & 2 enhancement plan
- **[TIER1_IMPLEMENTATION_SUMMARY.md](TIER1_IMPLEMENTATION_SUMMARY.md)** - Recent improvements summary
- **[MIGRATION_GUIDE.md](MIGRATION_GUIDE.md)** - Migration from legacy systems

---

## 🚦 Project Status

**Current Version**: Alpha (v0.1.0)

### ✅ Recent Completions

**Tier 1 Architecture Improvements** (2026-01-24):
- ✅ JSON Schema-based YAML validation with IDE autocomplete
- ✅ Enhanced `rufus validate` with `--strict` mode
- ✅ Accurate performance model documentation
- ✅ Executor portability warnings (prevents production failures)
- ✅ Dynamic injection caution warnings
- ✅ Comprehensive CLI with 21 commands

**Phase 1 Performance Optimizations**:
- ✅ uvloop integration (2-4x async I/O speedup)
- ✅ orjson serialization (3-5x faster JSON)
- ✅ Optimized PostgreSQL connection pooling
- ✅ Import caching (162x speedup)
- ✅ Comprehensive benchmarking suite

**SQLite Persistence Implementation**:
- ✅ Full PersistenceProvider interface (20 methods)
- ✅ In-memory and file-based modes
- ✅ WAL mode for improved concurrency
- ✅ 14 unit tests + 6 integration tests
- ✅ Performance benchmarks (~9K ops/sec)
- ✅ Complete documentation and examples

**CLI Enhancement**:
- ✅ 21 commands across 4 categories
- ✅ Configuration management
- ✅ Workflow lifecycle operations
- ✅ Database management
- ✅ Monitoring and logging
- ✅ Beautiful terminal output with Rich library

### 🔜 Upcoming (Tier 2)

**Zombie Workflow Recovery**:
- Heartbeat-based detection of crashed workers
- Auto-recovery of stale RUNNING workflows
- CLI: `rufus db scan-zombies`

**Workflow Versioning Strategy**:
- Snapshot workflow definitions in database
- Protect running workflows from definition changes
- Support explicit versioning (OrderProcessing_v1, _v2)

See [ARCHITECTURE_REVIEW_RESPONSE.md](ARCHITECTURE_REVIEW_RESPONSE.md) for Tier 2 design details.

### 📝 Note

This project was recently refactored from "Confucius" to "Rufus" with focus on:
- Extracting core SDK from monolithic application
- Unified `Workflow` class architecture
- Improved provider interfaces and dependency injection
- Better separation: Core SDK vs Server vs CLI
- Enhanced sub-workflow status propagation

Some legacy `confucius/` code still exists in the repo for reference.

---

## 🎯 Use Cases

- **Business Process Automation** - Order processing, approval workflows, onboarding
- **AI/ML Pipelines** - Multi-stage AI agent orchestration with human review
- **Distributed Transactions** - Saga pattern for microservices coordination
- **Human-AI Collaboration** - Workflows combining automated steps with human review
- **Event-Driven Systems** - Complex event processing with state management
- **ETL Pipelines** - Data processing with error handling and retries
- **Scheduled Jobs** - Cron-based recurring workflows
- **Microservices Orchestration** - Coordinate multiple services with compensation

---

## 🔑 Design Principles

1. **SDK-First** - Embed workflows directly in Python apps (no mandatory external server)
2. **Separation of Concerns** - Workflow definition (YAML) separate from implementation (Python)
3. **Provider Abstraction** - Swap persistence/execution/observability without code changes
4. **Type Safety** - Pydantic models for validation and IDE autocomplete
5. **Developer Experience** - Declarative YAML + Pythonic step functions + comprehensive CLI
6. **Production-Ready** - Performance optimizations, error handling, observability, testing
7. **Scalability** - Start embedded, scale to distributed when needed

---

## 🤝 Contributing

We welcome contributions! Please see our contribution guidelines (coming soon).

**Areas for Contribution**:
- Additional persistence providers (MongoDB, DynamoDB)
- Additional execution providers (Kubernetes jobs, AWS Lambda)
- Observability integrations (Prometheus, DataDog, New Relic)
- Additional step types
- Example workflows for specific industries
- Documentation improvements

---

## 📄 License

[Add license information]

---

## 🙏 Acknowledgments

Rufus builds on lessons learned from:
- Temporal.io (workflow durability)
- Airflow (DAG orchestration)
- AWS Step Functions (state machines)
- Saga pattern (distributed transactions)

While taking a different approach optimized for Python-native applications.

---

**Rufus** - Sophisticated workflow orchestration without the complexity.
Perfect for Python developers who need production-ready workflow management embedded directly into their applications.

**Get Started**: `pip install -r requirements.txt` → `rufus validate workflow.yaml` → `rufus run workflow.yaml`
