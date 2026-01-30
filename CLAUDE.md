# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Rufus is a Python-native, SDK-first workflow engine designed for orchestrating complex business processes and AI pipelines. It emphasizes a declarative, developer-friendly approach where workflows are defined in YAML and executed via an embedded SDK. The project consists of:

1. **Core SDK** (`src/rufus/`) - The reusable workflow engine library
2. **CLI Tool** (`src/rufus_cli/`) - Command-line interface for validation and local testing
3. **Server** (`src/rufus_server/`) - Optional FastAPI wrapper for REST API access

The architecture separates workflow definition (YAML) from implementation (Python functions) and decouples core engine logic from external dependencies through pluggable provider interfaces.

## Development Commands

### Setup
```bash
# Install in development mode with all dependencies
pip install -r requirements.txt

# SQLite support is included by default (no server required)
# For PostgreSQL support (production)
pip install asyncpg

# For Redis/Celery executor (optional, for distributed execution)
docker run -d --name redis-server -p 6379:6379 redis
```

### Testing
```bash
# Run all tests with coverage
pytest

# Run specific test module
pytest tests/sdk/test_engine.py

# Run with verbose output
pytest -v

# Run single test
pytest tests/sdk/test_workflow.py::test_workflow_initialization

# Tests automatically exclude confucius/ and original_implementation_files/ directories
```

### Running the CLI

**Configuration Management:**
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
# List and inspect workflows
rufus list [--status ACTIVE] [--type OrderProcessing] [--limit 10]
rufus show <workflow-id> [--state] [--logs]

# Start and control workflows
rufus start <workflow-type> [--data '{"field": "value"}']
rufus resume <workflow-id> [--input '{"approval": true}']
rufus retry <workflow-id> [--from-step StepName]
rufus cancel <workflow-id> [--force] [--reason "User cancelled"]

# Monitoring and debugging
rufus logs <workflow-id> [--step StepName] [--level ERROR] [--limit 100]
rufus metrics [--workflow-id <id>] [--type execution_time]
```

**Database Management:**
```bash
rufus db init [--db-url postgresql://...]  # Initialize database schema
rufus db migrate [--dry-run]               # Apply pending migrations
rufus db status                            # Show migration status
rufus db stats                             # Show database statistics
rufus db validate                          # Validate schema definition
```

**Zombie Workflow Recovery:**
```bash
rufus scan-zombies [--fix] [--threshold 120]  # Scan for zombie workflows
rufus zombie-daemon [--interval 60]           # Run scanner as daemon
```

**Legacy Commands (Preserved):**
```bash
# Validate a workflow YAML file
rufus validate config/my_workflow.yaml

# Run a workflow locally (in-memory, synchronous)
rufus run config/my_workflow.yaml -d '{"field": "value"}'

# Specify custom registry
rufus run config/my_workflow.yaml --registry config/workflow_registry.yaml
```

**Alternative Subcommand Syntax:**
```bash
# All workflow commands also available via subcommands
rufus workflow list              # Same as: rufus list
rufus workflow start <type>      # Same as: rufus start <type>
rufus workflow show <id>         # Same as: rufus show <id>
# ... etc for all workflow commands
```

### Running the Server (Optional)
```bash
# Start FastAPI development server
uvicorn rufus_server.main:app --reload

# Start Celery worker (for async execution)
celery -A rufus.implementations.execution.celery worker --loglevel=info
```

## Architecture

### Core Components

**Workflow Class (`src/rufus/workflow.py`)**
- Main class managing workflow lifecycle, state, and execution
- Delegates to providers for persistence, execution, and observability
- Handles all step types, directives, and control flow

**WorkflowEngine (Legacy, being phased out)**
- Located in `src/rufus/engine.py`
- Being migrated to unified `Workflow` class in `workflow.py`
- Contains orchestration logic including Saga pattern and dynamic injection

**WorkflowBuilder (`src/rufus/builder.py`)**
- Loads workflow definitions from YAML files
- Resolves function/model paths using `importlib`
- Manages workflow registry and auto-discovers `rufus-*` packages
- Creates `Workflow` instances with proper dependency injection

**Models (`src/rufus/models.py`)**
- Pydantic-based data structures for all workflow components
- `StepContext`: Provides context to step functions (workflow_id, step_name, previous results, loop state)
- `WorkflowStep` and subclasses: `CompensatableStep`, `AsyncWorkflowStep`, `HttpWorkflowStep`, `ParallelWorkflowStep`, `FireAndForgetWorkflowStep`, `LoopStep`, `CronScheduleWorkflowStep`
- Workflow directives (as exceptions): `WorkflowJumpDirective`, `WorkflowPauseDirective`, `StartSubWorkflowDirective`, `SagaWorkflowException`

### Provider Interfaces (`src/rufus/providers/`)

All external integrations are abstracted via Python Protocol interfaces:

**PersistenceProvider (`persistence.py`)**
- Defines how workflow state, audit logs, and task records are stored
- Methods: `save_workflow`, `get_workflow`, `claim_next_task`, etc.

**ExecutionProvider (`execution.py`)**
- Abstracts task execution environment
- Methods: `dispatch_async_task`, `dispatch_parallel_tasks`, `dispatch_sub_workflow`, `report_child_status_to_parent`, `execute_sync_step_function`

**WorkflowObserver (`observer.py`)**
- Hooks for workflow event observation
- Methods: `on_workflow_started`, `on_step_executed`, `on_workflow_completed`, `on_workflow_failed`, `on_workflow_status_changed`

**ExpressionEvaluator (`expression_evaluator.py`)**
- Evaluates conditions for decision steps and dynamic injection
- Default: simple Python expression evaluation

**TemplateEngine (`template_engine.py`)**
- Renders dynamic content from workflow state
- Default: Jinja2 implementation

### Default Implementations (`src/rufus/implementations/`)

**Persistence**
- `postgres.py`: PostgreSQL with JSONB, FOR UPDATE SKIP LOCKED, audit logging (production)
- `sqlite.py`: SQLite with WAL mode, foreign keys, type conversions (development/testing)
- `memory.py`: In-memory storage for testing
- `redis.py`: Redis-based persistence

**Execution**
- `sync.py`: Synchronous executor for simple scenarios and testing
- `celery.py`: Distributed async/parallel execution via Celery
- `thread_pool.py`: Thread-based parallel execution
- `postgres_executor.py`: PostgreSQL-backed task queue

**Observability**
- `logging.py`: Console-based workflow event logging

**Templating**
- `jinja2.py`: Jinja2 template rendering

**Expression Evaluation**
- `simple.py`: Basic Python expression evaluator

### Workflow Configuration

**Registry (`config/workflow_registry.yaml`)**
- Master list of all available workflows
- Each entry defines: `type`, `config_file`, `initial_state_model`
- Optional `requires` key lists external `rufus-*` packages

**Workflow YAML Structure**
- `workflow_type`: Unique identifier
- `workflow_version`: Optional version string
- `initial_state_model`: Python path to Pydantic state model
- `steps`: List of step definitions

**Step Configuration Keys**
- `name`: Unique step identifier within workflow
- `type`: Execution type (STANDARD, ASYNC, DECISION, PARALLEL, etc.)
- `function`: Python path to step function
- `compensate_function`: Optional compensation logic for Saga pattern
- `input_model`: Pydantic model for input validation
- `automate_next`: Boolean flag to auto-execute next step
- `dependencies`: List of prerequisite step names
- `dynamic_injection`: Rules for runtime step insertion
- `routes`: Declarative routing for DECISION steps

## Key Patterns

### Adding a New Workflow

1. **Define State Model** (create new file or add to existing):
   ```python
   # my_app/state_models.py
   from pydantic import BaseModel
   from typing import Optional

   class MyWorkflowState(BaseModel):
       user_id: str
       status: Optional[str] = None
       result_data: Optional[dict] = None
   ```

2. **Implement Step Functions**:
   ```python
   # my_app/workflow_steps.py
   from rufus.models import StepContext
   from my_app.state_models import MyWorkflowState

   def process_data(state: MyWorkflowState, context: StepContext) -> dict:
       """Synchronous step function"""
       state.status = "processing"
       return {"processed": True}

   def async_operation(state: MyWorkflowState, context: StepContext) -> dict:
       """Async step (dispatched to executor)"""
       # Long-running operation
       return {"async_result": "completed"}
   ```

3. **Create Workflow YAML** (`config/my_workflow.yaml`):
   ```yaml
   workflow_type: "MyWorkflow"
   workflow_version: "1.0.0"
   initial_state_model: "my_app.state_models.MyWorkflowState"
   description: "My custom workflow"

   steps:
     - name: "Process_Data"
       type: "STANDARD"
       function: "my_app.workflow_steps.process_data"
       automate_next: true

     - name: "Async_Operation"
       type: "ASYNC"
       function: "my_app.workflow_steps.async_operation"
       dependencies: ["Process_Data"]
   ```

4. **Register in `config/workflow_registry.yaml`**:
   ```yaml
   workflows:
     - type: "MyWorkflow"
       description: "My custom workflow"
       config_file: "my_workflow.yaml"
       initial_state_model: "my_app.state_models.MyWorkflowState"
   ```

### Step Function Signature

All step functions must accept:
```python
def step_function(state: BaseModel, context: StepContext, **user_input) -> dict:
    """
    Args:
        state: The workflow's state (Pydantic model)
        context: StepContext with workflow_id, step_name, previous_step_result, etc.
        **user_input: Additional validated inputs passed to this step

    Returns:
        dict: Result data merged into workflow state
    """
    pass
```

### Control Flow Mechanisms

**Automated Step Chaining (`automate_next`)**
- Set `automate_next: true` in step config
- Return value becomes input for next step
- No additional API call needed

**Conditional Branching**
```python
from rufus.models import WorkflowJumpDirective

def decision_step(state: MyState, context: StepContext):
    if state.amount > 10000:
        raise WorkflowJumpDirective(target_step_name="High_Value_Process")
    else:
        raise WorkflowJumpDirective(target_step_name="Standard_Process")
```

**Human-in-the-Loop**
```python
from rufus.models import WorkflowPauseDirective

def approval_step(state: MyState, context: StepContext):
    raise WorkflowPauseDirective(result={"awaiting_approval": True})
```

**Sub-Workflows**
```python
from rufus.models import StartSubWorkflowDirective

def trigger_child(state: MyState, context: StepContext):
    raise StartSubWorkflowDirective(
        workflow_type="ChildWorkflow",
        initial_data={"user_id": state.user_id},
        owner_id=state.owner_id,
        data_region="us-east-1"
    )
```

**Parallel Execution**
```yaml
- name: "Parallel_Tasks"
  type: "PARALLEL"
  tasks:
    - name: "task1"
      function_path: "my_app.tasks.task1"
    - name: "task2"
      function_path: "my_app.tasks.task2"
  merge_strategy: "SHALLOW"  # or DEEP
  merge_conflict_behavior: "PREFER_NEW"  # or PREFER_OLD, RAISE_ERROR
  allow_partial_success: true
  timeout_seconds: 300
```

### Saga Pattern (Compensation)

**Enable Saga Mode**:
```python
# In application code
workflow = workflow_builder.create_workflow("OrderProcessing", initial_data)
workflow.enable_saga_mode()
```

**Define Compensatable Steps**:
```python
def charge_payment(state: OrderState, context: StepContext):
    tx_id = payment_service.charge(state.amount)
    state.transaction_id = tx_id
    return {"transaction_id": tx_id}

def refund_payment(state: OrderState, context: StepContext):
    """Compensation function - reverses charge_payment"""
    if state.transaction_id:
        payment_service.refund(state.transaction_id)
    return {"refunded": True}
```

**Link in YAML**:
```yaml
- name: "Charge_Payment"
  type: "STANDARD"
  function: "my_app.steps.charge_payment"
  compensate_function: "my_app.steps.refund_payment"
```

**Behavior**:
- On failure, compensation functions execute in reverse order
- Workflow status becomes `FAILED_ROLLED_BACK`
- Compensation logged to audit table (PostgreSQL backend)

### Sub-Workflow Status Bubbling

Child workflows report status changes to parents:
- `PENDING_SUB_WORKFLOW`: Child is running
- `WAITING_CHILD_HUMAN_INPUT`: Child paused for input
- `FAILED_CHILD_WORKFLOW`: Child failed
- Parent resumes when child completes
- Child results available in `state.sub_workflow_results[workflow_type]`

### Polyglot Support (HTTP Steps)

Rufus supports **polyglot workflows** through HTTP Steps, enabling Python-orchestrated workflows to call services written in any programming language.

**Architecture**:
```
Rufus Engine (Python) → HTTP/REST → External Services (Go/Rust/Node.js/Java/etc.)
```

**HTTP Step Configuration**:
```yaml
- name: "Call_Go_Service"
  type: "HTTP"
  http_config:
    method: "POST"
    url: "http://go-service:8080/api/process"
    headers:
      Content-Type: "application/json"
      Authorization: "Bearer {{state.auth_token}}"
    body:
      user_id: "{{state.user_id}}"
      data: "{{state.payload}}"
    timeout: 30
  output_key: "go_response"
  automate_next: true
```

**Multi-Language Pipeline Example**:
```yaml
workflow_type: "PolyglotPipeline"
steps:
  # Python: Validation
  - name: "Validate"
    type: "STANDARD"
    function: "steps.validate"
    automate_next: true

  # Go: High-performance processing
  - name: "Process_Go"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://go-processor:8080/process"
      body: "{{state.validated_data}}"
    automate_next: true

  # Rust: ML inference
  - name: "Predict_Rust"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://rust-ml:8080/predict"
      body:
        features: "{{state.processed_data}}"
    automate_next: true

  # Node.js: Notifications
  - name: "Notify_Node"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://notification:3000/send"
      body:
        user: "{{state.user_id}}"
        result: "{{state.prediction}}"
```

**Key Features**:
- Jinja2 templating for dynamic URLs, headers, and body
- All HTTP methods supported (GET, POST, PUT, DELETE, PATCH)
- Automatic JSON parsing of responses
- Configurable timeouts and retry policies
- Response merged into workflow state

**Best Practices**:
- Keep orchestration logic in Python
- Implement idempotency in external services
- Use service discovery for production URLs
- Configure appropriate timeouts per service
- Handle HTTP errors with DECISION steps

**Documentation**: See [USAGE_GUIDE.md](USAGE_GUIDE.md#81-polyglot-workflows-http-steps) for complete polyglot documentation.

## Testing

### Using TestHarness
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

### Testing Patterns
- Use in-memory persistence for unit tests
- Set `TESTING=true` to run parallel tasks synchronously
- Mock external services in step functions
- Use `pytest` fixtures for common setup

## Performance Optimizations (Phase 1)

Rufus SDK includes production-grade performance optimizations enabled by default:

### Optimizations Implemented

1. **uvloop Event Loop**
   - 2-4x faster async I/O operations
   - Configured automatically in `src/rufus/__init__.py`
   - Control via `RUFUS_USE_UVLOOP` environment variable
   ```python
   # Automatically enabled on import
   import rufus  # uvloop configured here
   ```

2. **orjson Serialization**
   - 3-5x faster JSON serialization/deserialization
   - Utility module: `src/rufus/utils/serialization.py`
   - Used in: postgres.py, redis.py, celery.py
   ```python
   from rufus.utils.serialization import serialize, deserialize

   # Fast serialization
   json_str = serialize({"key": "value"})
   data = deserialize(json_str)
   ```

3. **Optimized PostgreSQL Connection Pool**
   - Default: min=10, max=50 connections (tuned for high concurrency)
   - Configurable via constructor or environment variables
   ```python
   persistence = PostgresPersistenceProvider(
       db_url=db_url,
       pool_min_size=10,
       pool_max_size=50
   )
   ```
   - Environment variables:
     - `POSTGRES_POOL_MIN_SIZE` (default: 10)
     - `POSTGRES_POOL_MAX_SIZE` (default: 50)
     - `POSTGRES_POOL_COMMAND_TIMEOUT` (default: 10)
     - `POSTGRES_POOL_MAX_QUERIES` (default: 50000)
     - `POSTGRES_POOL_MAX_INACTIVE_LIFETIME` (default: 300)

4. **Import Caching**
   - Class-level cache in `WorkflowBuilder._import_cache`
   - 162x speedup for repeated step function imports
   - Reduces 5-10ms overhead per step execution
   ```python
   # Cached automatically - no code changes needed
   func = WorkflowBuilder._import_from_string("my_app.steps.process_data")
   ```

### Benchmark Results

Run benchmarks: `python tests/benchmarks/workflow_performance.py`

```
Serialization: 2,453,971 ops/sec (orjson)
Import Caching: 162x speedup
Async Latency: 5.5µs p50, 12.7µs p99 (uvloop)
Workflow Throughput: 703,633 workflows/sec (simplified)
```

### Performance Guidelines

**When writing new code:**
- Use `from rufus.utils.serialization import serialize, deserialize` for JSON operations
- Import caching is automatic - no code changes needed
- PostgreSQL pool settings can be tuned per deployment

**Configuration for different workloads:**
- **Low concurrency** (< 10 concurrent workflows):
  - `POSTGRES_POOL_MIN_SIZE=5`
  - `POSTGRES_POOL_MAX_SIZE=20`
- **Medium concurrency** (10-100 concurrent workflows):
  - `POSTGRES_POOL_MIN_SIZE=10` (default)
  - `POSTGRES_POOL_MAX_SIZE=50` (default)
- **High concurrency** (> 100 concurrent workflows):
  - `POSTGRES_POOL_MIN_SIZE=20`
  - `POSTGRES_POOL_MAX_SIZE=100`

**Disabling optimizations** (for debugging):
```bash
export RUFUS_USE_UVLOOP=false  # Use stdlib asyncio
export RUFUS_USE_ORJSON=false  # Use stdlib json
```

### Expected Gains

- **+50-100% throughput** for I/O-bound workflows
- **-30-40% latency** for async operations
- **-80% serialization time** for state persistence
- **-90% import overhead** for repeated step function calls

## Database Schema Management

Rufus uses a **unified schema definition** approach to support multiple databases (PostgreSQL and SQLite) without schema divergence.

### Schema Standardization Architecture

```
migrations/schema.yaml (unified definition)
           │
    ┌──────┴──────┐
    ▼             ▼
PostgreSQL     SQLite
 .sql files    .sql files
```

**Key Components:**

1. **`migrations/schema.yaml`** - Single source of truth for database schema
   - Database-agnostic column types (uuid, jsonb, timestamp, etc.)
   - Type mappings for each database (JSONB→TEXT for SQLite)
   - Table definitions, indexes, triggers, views
   - Version: 1.0.0

2. **`tools/compile_schema.py`** - Schema compiler
   - Generates database-specific SQL from YAML
   - Handles type conversions automatically
   - Supports PostgreSQL and SQLite

3. **`tools/validate_schema.py`** - Schema validation
   - Compares generated SQL against original
   - Verifies type mappings are correct
   - Ensures all tables, indexes, triggers present

4. **`tools/migrate.py`** - Migration manager
   - Tracks applied migrations via `schema_migrations` table
   - Applies pending migrations in order
   - Supports both PostgreSQL and SQLite

### Type Mappings

| Unified Type | PostgreSQL | SQLite |
|--------------|------------|--------|
| `uuid` | UUID | TEXT |
| `jsonb` | JSONB | TEXT |
| `timestamp` | TIMESTAMPTZ | TEXT |
| `boolean` | BOOLEAN | INTEGER (0/1) |
| `bigserial` | BIGSERIAL | INTEGER AUTOINCREMENT |
| `numeric` | NUMERIC | REAL |
| `inet` | INET | TEXT |

### Workflow

**Generate Migrations:**
```bash
# Generate both PostgreSQL and SQLite migrations
python tools/compile_schema.py --all

# Generate specific database
python tools/compile_schema.py --target postgres --output migrations/002_postgres.sql
python tools/compile_schema.py --target sqlite --output migrations/002_sqlite.sql
```

**Validate Schema:**
```bash
# Validate all databases
python tools/validate_schema.py --all

# Validate specific database
python tools/validate_schema.py --target postgres
```

**Apply Migrations:**
```bash
# PostgreSQL
python tools/migrate.py --db postgres://user:pass@localhost/dbname --init
python tools/migrate.py --db postgres://user:pass@localhost/dbname --status
python tools/migrate.py --db postgres://user:pass@localhost/dbname --up

# SQLite
python tools/migrate.py --db sqlite:///path/to/db.sqlite --init
python tools/migrate.py --db sqlite:///path/to/db.sqlite --up
```

### Schema Modification Process

When modifying the database schema:

1. **Edit only `migrations/schema.yaml`** - Never edit .sql files directly
2. **Increment schema version** in schema.yaml
3. **Generate migrations** using compile_schema.py
4. **Validate** using validate_schema.py
5. **Test migrations** against test databases
6. **Commit all files** (schema.yaml + generated .sql files)

Example schema.yaml structure:
```yaml
version: "1.0.0"

type_mappings:
  uuid:
    postgres: "UUID"
    sqlite: "TEXT"

tables:
  my_table:
    description: "Table description"
    columns:
      - name: id
        type: uuid
        primary_key: true
        default:
          postgres: "gen_random_uuid()"
          sqlite: "lower(hex(randomblob(16)))"

      - name: data
        type: jsonb
        nullable: false
        default:
          postgres: "'{}'::jsonb"
          sqlite: "'{}'"

    indexes:
      - name: idx_my_table_id
        columns: [id]
```

### Database Support

**PostgreSQL (Production):**
- Full feature support
- LISTEN/NOTIFY for real-time updates
- Advanced indexing (GIN, partial indexes)
- Triggers and stored procedures
- Connection pooling

**SQLite (Development/Testing):**
- Embedded database (no server needed)
- Fast in-memory mode for tests
- Single-file portability
- Feature parity with PostgreSQL schema
- Limitations: No LISTEN/NOTIFY, simpler triggers

### Testing with SQLite

```python
# Use SQLite for fast tests
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider

persistence = SQLitePersistenceProvider(db_path=":memory:")
await persistence.initialize()
```

## SQLite Persistence Provider

Rufus SDK includes full SQLite support for development, testing, and low-concurrency deployments. SQLite provides a lightweight, embedded database option that requires no external server.

### When to Use SQLite

**✅ Recommended for:**
- **Development**: No PostgreSQL server required - zero setup friction
- **Testing**: Fast in-memory databases (`db_path=":memory:"`)
- **CI/CD**: Simplified pipelines without database containers
- **Demos**: Portable, self-contained examples
- **Single-server deployments**: Low-to-medium concurrency workloads
- **Edge computing**: Embedded workflows on IoT/edge devices
- **Prototyping**: Quick experimentation without infrastructure

**❌ Not recommended for:**
- **High concurrency**: SQLite has write serialization (single writer at a time)
- **Distributed systems**: No built-in replication or clustering
- **Real-time updates**: No LISTEN/NOTIFY support (use PostgreSQL)
- **Large-scale production**: PostgreSQL recommended for >100 concurrent workflows

### Installation and Setup

**Install dependencies:**
```bash
# SQLite support included in base requirements
pip install -r requirements.txt

# aiosqlite is automatically installed
```

**No server setup required** - SQLite is embedded in the Python process.

### Usage Examples

**1. In-Memory Database (Testing)**
```python
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider

# Fast, ephemeral database - perfect for tests
persistence = SQLitePersistenceProvider(db_path=":memory:")
await persistence.initialize()

# Run tests...
await persistence.close()
```

**2. File-Based Database (Development)**
```python
# Persistent database stored on disk
persistence = SQLitePersistenceProvider(db_path="workflows.db")
await persistence.initialize()

# Apply migrations
from tools.migrate import migrate_database
await migrate_database("sqlite:///workflows.db")
```

**3. Full Workflow Integration**
```python
from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.execution.sync import SyncExecutionProvider
from rufus.implementations.observability.logging import LoggingObserver

# Create SQLite persistence
persistence = SQLitePersistenceProvider(db_path="workflows.db")
await persistence.initialize()

# Build workflow with SQLite backend
builder = WorkflowBuilder(
    config_dir="config/",
    persistence_provider=persistence,
    execution_provider=SyncExecutionProvider(),
    observer=LoggingObserver()
)

# Use normally - no PostgreSQL required!
workflow = await builder.create_workflow(
    workflow_type="MyWorkflow",
    initial_data={"user_id": "123"}
)
```

**4. Example Application**
See `examples/sqlite_task_manager/` for a complete example:
```bash
# Run the simple demo
python examples/sqlite_task_manager/simple_demo.py

# Or run the full workflow example
python examples/sqlite_task_manager/main.py
```

### Configuration Options

```python
SQLitePersistenceProvider(
    db_path: str = ":memory:",        # Database file path or ":memory:"
    timeout: float = 5.0,              # Lock timeout in seconds
    check_same_thread: bool = False    # Allow multi-threaded access
)
```

**Key parameters:**
- **`db_path`**:
  - `":memory:"` - In-memory database (fast, ephemeral)
  - `"path/to/db.sqlite"` - File-based database (persistent)
  - Use absolute paths for production

- **`timeout`**:
  - How long to wait for database locks (default: 5 seconds)
  - Increase for high-contention scenarios

- **`check_same_thread`**:
  - Set to `False` for async/multi-threaded applications (default)
  - SQLite default is `True` but Rufus handles thread safety

### Performance Characteristics

**Benchmark Results** (single-threaded, in-memory):
```
save_workflow:  ~9,000 ops/sec
load_workflow:  ~6,500 ops/sec
create_task:    ~7,800 ops/sec
log_execution:  ~9,000 ops/sec
record_metric:  ~8,500 ops/sec
```

**vs PostgreSQL:**
- **Reads**: Similar performance for single-threaded workloads
- **Writes**: PostgreSQL faster for concurrent writes (10+ workers)
- **Latency**: SQLite slightly lower latency for local operations
- **Throughput**: PostgreSQL significantly better for concurrent workloads

### SQLite-Specific Features

**WAL Mode** (Write-Ahead Logging):
- Automatically enabled for file-based databases
- Improves concurrency (readers don't block writers)
- Better crash recovery

**Foreign Key Enforcement**:
- Enabled by default (SQLite disables by default)
- Ensures referential integrity (parent/child workflows)

**Type Conversions**:
- **UUID**: Stored as TEXT (hex format)
- **JSONB**: Stored as TEXT (JSON strings)
- **Timestamps**: Stored as TEXT (ISO8601 format)
- **Booleans**: Stored as INTEGER (0/1)
- Automatic conversion handled by persistence provider

### Migration Between Databases

**SQLite to PostgreSQL:**
```python
# 1. Export from SQLite
sqlite_persistence = SQLitePersistenceProvider(db_path="workflows.db")
workflows = await sqlite_persistence.list_workflows(limit=10000)

# 2. Import to PostgreSQL
postgres_persistence = PostgresPersistenceProvider(db_url="postgresql://...")
for workflow in workflows:
    await postgres_persistence.save_workflow(workflow['id'], workflow)
```

**PostgreSQL to SQLite:**
```python
# Similar process, reverse direction
# Note: LISTEN/NOTIFY features will be lost
```

### Best Practices

**Development:**
```python
# Use file-based database for development
persistence = SQLitePersistenceProvider(db_path="dev_workflows.db")

# Keep database in .gitignore
# Commit schema migrations, not database files
```

**Testing:**
```python
# Use in-memory database for tests
@pytest.fixture
async def persistence():
    provider = SQLitePersistenceProvider(db_path=":memory:")
    await provider.initialize()
    # Apply schema...
    yield provider
    await provider.close()
```

**Production (Low Concurrency):**
```python
# Use absolute path and WAL mode (automatic)
persistence = SQLitePersistenceProvider(
    db_path="/var/lib/rufus/workflows.db",
    timeout=10.0  # Increase timeout for production
)

# Regular backups with SQLite backup API
import shutil
shutil.copy("/var/lib/rufus/workflows.db", "/backups/workflows_backup.db")
```

### Limitations and Workarounds

**1. No LISTEN/NOTIFY**
- **Impact**: No real-time workflow status updates
- **Workaround**: Use polling or external pub/sub (Redis)
```python
# Polling approach
import asyncio
async def poll_workflow_status(workflow_id):
    while True:
        workflow = await persistence.load_workflow(workflow_id)
        if workflow['status'] in ['COMPLETED', 'FAILED']:
            break
        await asyncio.sleep(1)  # Poll every second
```

**2. Write Serialization**
- **Impact**: Only one writer at a time (concurrent reads OK)
- **Workaround**: Use connection pooling with retry logic
- **Recommendation**: Switch to PostgreSQL for >50 concurrent writers

**3. Simpler Triggers**
- **Impact**: Some PostgreSQL triggers simplified for SQLite
- **Effect**: Minimal - core functionality preserved
- **Details**: `updated_at` triggers use AFTER UPDATE instead of BEFORE UPDATE

### Troubleshooting

**Error: "database is locked"**
```python
# Increase timeout
persistence = SQLitePersistenceProvider(
    db_path="workflows.db",
    timeout=30.0  # Wait up to 30 seconds
)

# Or reduce concurrent writes
# Or switch to PostgreSQL for high concurrency
```

**Error: "no such table"**
```bash
# Apply migrations
python tools/migrate.py --db sqlite:///workflows.db --up

# Or use initialize_schema.py
python tools/initialize_schema.py --database sqlite --output workflows.db
```

**Error: "UNIQUE constraint failed"**
```python
# Check for duplicate idempotency keys
# SQLite uses INSERT OR REPLACE for idempotent operations
# This is expected behavior, not an error in most cases
```

**Performance Issues:**
```python
# 1. Use WAL mode (automatic for file-based databases)
# 2. Use in-memory database for tests
# 3. Reduce concurrent writes
# 4. Consider PostgreSQL for production workloads

# Check if WAL mode is enabled
async with persistence.conn.execute("PRAGMA journal_mode") as cursor:
    mode = await cursor.fetchone()
    print(f"Journal mode: {mode[0]}")  # Should be 'wal'
```

### Running Benchmarks

Compare SQLite vs PostgreSQL performance:
```bash
python tests/benchmarks/persistence_benchmark.py
```

## Production Reliability Features (Tier 2)

Rufus includes production-grade reliability features to handle worker crashes and workflow definition changes.

### Zombie Workflow Recovery

**Problem**: When a worker crashes while processing a workflow step, the workflow stays in `RUNNING` state forever with no way to detect or recover.

**Solution**: Heartbeat-based zombie detection and automatic recovery.

#### How It Works

1. **HeartbeatManager** (worker-side) sends periodic heartbeats while processing steps
2. **ZombieScanner** (monitoring process) detects stale heartbeats
3. Zombie workflows automatically marked as `FAILED_WORKER_CRASH`
4. Cleanup removes stale heartbeat records

#### Using HeartbeatManager

**In Step Functions** (automatic via execution provider):
```python
from rufus.heartbeat import HeartbeatManager

async def long_running_step(state: MyState, context: StepContext):
    # Heartbeat automatically managed by execution provider
    # Just write your step logic
    result = await process_payment(state.amount)
    return {"payment_id": result.id}
```

**Manual Heartbeat Control** (advanced):
```python
from rufus.heartbeat import HeartbeatManager

async def custom_step(state: MyState, context: StepContext):
    # Manual heartbeat control for custom execution logic
    heartbeat = HeartbeatManager(
        persistence=context.persistence,
        workflow_id=context.workflow_id,
        heartbeat_interval_seconds=30
    )

    async with heartbeat:  # Auto-start and stop
        # Long-running operation
        result = await complex_computation(state)
        return {"result": result}
```

**Configuration**:
```python
heartbeat = HeartbeatManager(
    persistence=persistence_provider,
    workflow_id=uuid.UUID(...),
    worker_id="custom-worker-123",  # Optional, auto-generated if not provided
    heartbeat_interval_seconds=30   # Default: 30s
)

# Start heartbeat
await heartbeat.start(
    current_step="Process_Payment",
    metadata={"custom": "data"}
)

# ... execute step ...

# Stop and cleanup
await heartbeat.stop()
```

#### Using ZombieScanner

**CLI - One-Shot Scan**:
```bash
# Scan for zombies (dry-run)
rufus scan-zombies --db postgresql://localhost/rufus

# Scan and fix
rufus scan-zombies --db postgresql://localhost/rufus --fix

# Custom threshold (default: 120s)
rufus scan-zombies --db postgresql://localhost/rufus --fix --threshold 180

# JSON output for monitoring
rufus scan-zombies --db postgresql://localhost/rufus --json
```

**CLI - Continuous Daemon**:
```bash
# Run as background daemon
rufus zombie-daemon --db postgresql://localhost/rufus

# Custom scan interval and threshold
rufus zombie-daemon --db postgresql://localhost/rufus --interval 60 --threshold 120
```

**Programmatic Usage**:
```python
from rufus.zombie_scanner import ZombieScanner
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider

# Create scanner
persistence = PostgresPersistenceProvider(db_url)
await persistence.initialize()

scanner = ZombieScanner(
    persistence=persistence,
    stale_threshold_seconds=120  # Heartbeats older than this are "stale"
)

# One-shot scan and recover
summary = await scanner.scan_and_recover(dry_run=False)
print(f"Found {summary['zombies_found']}, recovered {summary['zombies_recovered']}")

# Or scan and recover separately
zombies = await scanner.scan()
recovered_count = await scanner.recover(zombies, dry_run=False)

# Run as continuous daemon
await scanner.run_daemon(
    scan_interval_seconds=60,
    stale_threshold_seconds=120
)
```

#### Database Schema

The `workflow_heartbeats` table tracks worker health:

```sql
CREATE TABLE workflow_heartbeats (
    workflow_id UUID PRIMARY KEY REFERENCES workflow_executions(id) ON DELETE CASCADE,
    worker_id VARCHAR(100) NOT NULL,
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    current_step VARCHAR(200),
    step_started_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_heartbeat_time ON workflow_heartbeats(last_heartbeat ASC);
```

#### Production Deployment

**Option 1: Cron Job**
```bash
# Run every minute via cron
* * * * * rufus scan-zombies --db $DATABASE_URL --fix >> /var/log/rufus/zombie-scanner.log 2>&1
```

**Option 2: Systemd Service**
```ini
[Unit]
Description=Rufus Zombie Workflow Scanner
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/rufus zombie-daemon --db postgresql://localhost/rufus --interval 60
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Option 3: Kubernetes CronJob**
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: rufus-zombie-scanner
spec:
  schedule: "*/5 * * * *"  # Every 5 minutes
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: scanner
            image: myapp/rufus:latest
            command:
            - rufus
            - scan-zombies
            - --db
            - postgresql://postgres/rufus
            - --fix
          restartPolicy: OnFailure
```

#### Configuration Recommendations

| Workload | Heartbeat Interval | Stale Threshold | Scan Interval |
|----------|-------------------|-----------------|---------------|
| **Fast steps** (< 1 min) | 15s | 60s | 30s |
| **Medium steps** (1-10 min) | 30s | 120s | 60s |
| **Long steps** (10+ min) | 60s | 300s | 120s |
| **Very long steps** (hours) | 300s | 900s | 300s |

**Key Rule**: `Stale Threshold > 2 × Heartbeat Interval` to avoid false positives.

#### Monitoring

**Metrics to Track**:
- Zombie workflows detected per hour
- Recovery success rate
- Average time to detection
- False positive rate

**Alerts**:
```python
# Alert if many zombies detected
if summary['zombies_found'] > 10:
    send_alert("High zombie workflow count detected")

# Alert if recovery fails
if summary['zombies_recovered'] < summary['zombies_found']:
    send_alert("Zombie recovery failures detected")
```

---

### Workflow Versioning (Definition Snapshots)

**Problem**: Deploying new YAML workflow definitions breaks running workflows. If 10,000 workflows are running and you deploy a YAML file that removes a step, those workflows fail when they try to resume.

**Solution**: Snapshot workflow definitions at creation time. Running workflows use their snapshot, new workflows use the latest YAML.

#### How It Works

1. **WorkflowBuilder** snapshots complete workflow config on `create_workflow()`
2. **Workflow** stores snapshot in `definition_snapshot` field
3. **Persistence** saves snapshot to database (JSONB column)
4. **On Resume**: Workflow uses snapshot, immune to YAML changes

#### Automatic Snapshotting

Snapshotting is **automatic** - no code changes required:

```python
# WorkflowBuilder automatically snapshots on create
workflow = await builder.create_workflow(
    workflow_type="OrderProcessing",
    initial_data={"order_id": "12345"}
)

# Snapshot stored in workflow.definition_snapshot
assert workflow.definition_snapshot is not None
assert workflow.definition_snapshot['workflow_type'] == "OrderProcessing"
```

**What's Snapshotted**:
- Complete workflow YAML config
- All step definitions
- State model path
- Dependencies, routes, parallel tasks
- Everything needed to reconstruct workflow execution

#### Explicit Versioning

**Optional**: Add `workflow_version` to YAML for explicit version tracking:

```yaml
workflow_type: "OrderProcessing"
workflow_version: "1.5.0"  # Explicit version
initial_state_model: "my_app.models.OrderState"
description: "Order processing workflow"

steps:
  - name: "Validate_Order"
    type: "STANDARD"
    function: "my_app.steps.validate_order"
```

Access version in code:
```python
workflow = await builder.create_workflow("OrderProcessing", initial_data)

# Check version
print(f"Workflow version: {workflow.workflow_version}")  # "1.5.0"
```

#### Breaking Changes Strategy

**Option A: Keep Old YAML, Deploy New Version**

```yaml
# config/order_processing_v1.yaml (keep for running workflows)
workflow_type: "OrderProcessing_v1"
workflow_version: "1.0.0"
steps:
  - name: "Human_Approval"  # Legacy step

# config/order_processing_v2.yaml (new deployments)
workflow_type: "OrderProcessing_v2"
workflow_version: "2.0.0"
steps:
  # Human_Approval removed
```

Register both:
```yaml
# config/workflow_registry.yaml
workflows:
  - type: "OrderProcessing_v1"
    config_file: "order_processing_v1.yaml"
    deprecated: true

  - type: "OrderProcessing_v2"
    config_file: "order_processing_v2.yaml"
```

**Option B: Rely on Snapshots (Recommended)**

Just update the YAML - running workflows use their snapshot:

```yaml
# config/order_processing.yaml (updated)
workflow_type: "OrderProcessing"
workflow_version: "2.0.0"  # Bumped version
steps:
  # Human_Approval removed - running workflows unaffected!
```

Running workflows (created with v1.0.0):
- Use their snapshot (still has Human_Approval)
- Complete successfully

New workflows (created after deploy):
- Use new YAML (no Human_Approval)
- Follow new process

#### Version Compatibility Checking

**Check compatibility when resuming workflows** (optional):

```python
from rufus.builder import WorkflowBuilder

def check_version_compatibility(snapshot_version: str, current_version: str) -> bool:
    """Check if workflow snapshot is compatible with current YAML."""
    if not snapshot_version or not current_version:
        return True  # No version specified - allow

    snap_major = int(snapshot_version.split('.')[0])
    curr_major = int(current_version.split('.')[0])

    # Compatible if same major version
    return snap_major == curr_major

# In WorkflowBuilder.load_workflow:
workflow_dict = await persistence.load_workflow(workflow_id)

snapshot_version = workflow_dict.get('workflow_version')
current_config = self.get_workflow_config(workflow_dict['workflow_type'])
current_version = current_config.get('workflow_version')

if not check_version_compatibility(snapshot_version, current_version):
    raise ValueError(
        f"Workflow version {snapshot_version} incompatible with "
        f"current version {current_version}"
    )
```

#### Database Schema

The `workflow_executions` table includes version fields:

```sql
ALTER TABLE workflow_executions ADD COLUMN workflow_version VARCHAR(50);
ALTER TABLE workflow_executions ADD COLUMN definition_snapshot JSONB;
```

**Storage Overhead**:
- ~5-10 KB per workflow (typical)
- PostgreSQL: Stored as compressed JSONB
- SQLite: Stored as TEXT

#### Migration Strategy

**For Existing Workflows**:

```sql
-- Existing workflows without snapshots will have NULL
-- This is backward compatible - they'll continue using current YAML
SELECT COUNT(*) FROM workflow_executions WHERE definition_snapshot IS NULL;

-- Optionally backfill snapshots for running workflows
-- (requires custom migration script to reconstruct from current YAML)
```

#### Best Practices

**✅ Do:**
- Use automatic snapshotting (it's automatic!)
- Bump `workflow_version` for breaking changes
- Keep snapshots for audit/debugging
- Test migrations on staging first

**❌ Don't:**
- Delete old YAML files immediately (wait for running workflows to complete)
- Make breaking changes without version bump
- Disable snapshotting (wastes the protection)

#### Troubleshooting

**Check Snapshot Contents**:
```python
workflow = await persistence.load_workflow(workflow_id)
snapshot = workflow['definition_snapshot']

print(f"Snapshot workflow_type: {snapshot['workflow_type']}")
print(f"Snapshot version: {snapshot.get('workflow_version')}")
print(f"Steps in snapshot: {[s['name'] for s in snapshot['steps']]}")
```

**Verify Snapshot Protection**:
```python
# Create workflow with v1 YAML
workflow = await builder.create_workflow("MyWorkflow", initial_data)
workflow_id = workflow.id

# Deploy v2 YAML (breaking changes)
# ... update YAML file ...

# Resume workflow - should use v1 snapshot
loaded_workflow = await persistence.load_workflow(workflow_id)
snapshot = loaded_workflow['definition_snapshot']

# Snapshot should have v1 steps, not v2
assert snapshot['workflow_version'] == "1.0.0"
```

**Storage Analysis**:
```sql
-- Check snapshot storage usage
SELECT
    AVG(LENGTH(definition_snapshot::text)) AS avg_snapshot_size_bytes,
    MAX(LENGTH(definition_snapshot::text)) AS max_snapshot_size_bytes
FROM workflow_executions
WHERE definition_snapshot IS NOT NULL;
```

---

## Important Notes

- **Path Resolution**: All YAML paths resolved via `importlib.import_module`
- **State Serialization**: State must be JSON-serializable (Pydantic handles this)
- **Provider Injection**: All providers injected via `Workflow.__init__` or `WorkflowBuilder`
- **Async Execution**: Async steps dispatched to `ExecutionProvider`, not executed inline
- **Error Handling**: Uncaught exceptions set workflow status to `FAILED`
- **Parallel Merge Conflicts**: Logged as warnings when tasks return overlapping keys
- **Sub-Workflow Nesting**: Supports hierarchical composition with status propagation

### ⚠️ Executor Portability Warning

**CRITICAL**: Step functions must be **stateless and process-isolated** to work across all executors.

**The Problem**: Developers often test with `SyncExecutionProvider` (single process, shared memory) and deploy with `CeleryExecutor` (distributed, fresh process per task). Code that works locally breaks in production because:

- **SyncExecutor**: All steps run in the same Python process. Global variables, module-level state, and in-memory caches are shared.
- **CeleryExecutor/ThreadPoolExecutor**: Each step runs in a separate worker process/thread. No shared memory.

**Common Pitfalls**:

```python
# ❌ BREAKS in CeleryExecutor - global state lost between steps
global_cache = {}

def step_a(state: MyState, context: StepContext):
    global_cache['user_data'] = fetch_user(state.user_id)
    return {}

def step_b(state: MyState, context: StepContext):
    user_data = global_cache['user_data']  # KeyError in Celery!
    return {"name": user_data['name']}

# ❌ BREAKS in CeleryExecutor - module-level state lost
_connection = None

def step_c(state: MyState, context: StepContext):
    global _connection
    if _connection is None:
        _connection = create_db_connection()  # Created in worker process
    _connection.query(...)  # Different worker, _connection is None!

# ✅ WORKS everywhere - state persisted in workflow state
def step_a_correct(state: MyState, context: StepContext):
    user_data = fetch_user(state.user_id)
    state.user_data = user_data  # Persisted to database
    return {"user_data": user_data}

def step_b_correct(state: MyState, context: StepContext):
    user_data = state.user_data  # Loaded from database
    return {"name": user_data['name']}

# ✅ WORKS everywhere - return data to workflow state
def step_c_correct(state: MyState, context: StepContext):
    # Create connection per step (Celery worker will clean up)
    connection = create_db_connection()
    result = connection.query(...)
    return {"query_result": result}  # Result saved to state
```

**Best Practices**:
1. **Store everything in workflow state** - `state.field = value` persists to database
2. **Return data from steps** - Return dict merges into state automatically
3. **No global variables** - Treat each step as isolated function
4. **No module-level state** - Don't rely on `_module_var` between steps
5. **Create resources per step** - Database connections, API clients, etc. should be created and cleaned up within each step

**Testing for Portability**:
```python
import pytest
from rufus.implementations.execution.sync import SyncExecutionProvider
from rufus.implementations.execution.thread_pool import ThreadPoolExecutionProvider

@pytest.mark.parametrize("executor", [
    SyncExecutionProvider(),
    ThreadPoolExecutionProvider()  # Closer to Celery behavior
])
def test_workflow_executor_portable(executor):
    """Test that workflow works with both sync and threaded execution."""
    builder = WorkflowBuilder(
        config_dir="config/",
        execution_provider=executor
    )
    workflow = builder.create_workflow("MyWorkflow", initial_data={...})
    # Run workflow - should work with both executors
    ...
```

**Quick Check**: If your step function uses `global`, module-level variables, or relies on state from previous steps not in the workflow state object, it will likely break in distributed execution.

---

### ⚠️ Dynamic Injection Caution

**WARNING**: Dynamic step injection makes workflows **non-deterministic** and significantly harder to debug.

**The Problem**: When a workflow modifies its own structure at runtime based on data, the execution trace no longer matches the YAML definition. This creates serious operational challenges:

1. **Debugging Difficulty**: Audit logs show steps that don't exist in the workflow YAML file
2. **Compensation Complexity**: Saga rollback must track dynamically injected steps
3. **Non-Determinism**: Same workflow type with different data produces different execution paths
4. **Version Control**: Cannot reconstruct execution from Git history (definition changed at runtime)
5. **Audit Compliance**: Harder to prove regulatory compliance when workflow structure is dynamic

**Example of the Problem**:

```yaml
# my_workflow.yaml
steps:
  - name: "Process_Order"
    type: "STANDARD"
    function: "steps.process_order"
    dynamic_injection:
      condition: "state.amount > 10000"
      steps:
        - name: "High_Value_Review"  # This step NOT in YAML!
          function: "steps.high_value_review"
      insert_after: "Process_Order"
```

**What happens**:
- Low-value order ($100): Executes `Process_Order` → `Ship_Order` (matches YAML)
- High-value order ($20,000): Executes `Process_Order` → `High_Value_Review` → `Ship_Order` (YAML + injected step)

**When developer looks at audit log**: "Why did this workflow execute `High_Value_Review`? It's not in the YAML file!"

**When to Use Dynamic Injection** (Rare cases only):
1. **Plugin Systems**: Steps defined by external packages (e.g., `rufus-plugins`)
2. **Multi-Tenant Workflows**: Tenants provide custom validation logic
3. **A/B Testing**: Controlled experiments with workflow variations
4. **Dynamic Compliance**: Regulatory requirements vary by jurisdiction

**Recommended Alternatives** (Use these instead):

**1. DECISION Steps with Explicit Routes**:
```yaml
steps:
  - name: "Check_Order_Value"
    type: "DECISION"
    function: "steps.check_order_value"
    routes:
      - condition: "state.amount > 10000"
        target: "High_Value_Review"  # Visible in YAML!
      - condition: "state.amount <= 10000"
        target: "Standard_Processing"

  - name: "High_Value_Review"  # Explicit step
    type: "STANDARD"
    function: "steps.high_value_review"
    dependencies: ["Check_Order_Value"]
```

**2. Conditional Logic Within Steps**:
```python
def process_order(state: OrderState, context: StepContext):
    if state.amount > 10000:
        # High-value logic inline
        perform_high_value_checks(state)
    else:
        # Standard logic
        perform_standard_checks(state)
    return {"processed": True}
```

**3. Multiple Workflow Versions**:
```yaml
# order_processing_standard.yaml
workflow_type: "OrderProcessing_Standard"

# order_processing_high_value.yaml
workflow_type: "OrderProcessing_HighValue"
steps:
  - name: "High_Value_Review"  # Explicit in this version
```

**If You Must Use Dynamic Injection**:
1. **Enable Full Audit Logging**: Record when steps were injected and why
2. **Snapshot Workflow Definition**: Save final workflow structure to database
3. **Add Comments**: Document why dynamic injection is necessary
4. **Limit Scope**: Only inject in specific, well-documented scenarios
5. **Review Regularly**: Periodic audits of dynamic injection usage

**Configuration Example** (if necessary):
```yaml
steps:
  - name: "Process_Data"
    type: "STANDARD"
    function: "steps.process_data"
    dynamic_injection:
      # DOCUMENT WHY THIS IS NEEDED
      # Reason: Multi-tenant workflow, tenants define custom validation
      condition: "state.tenant_config.has_custom_validation"
      steps:
        - name: "Custom_Validation"
          function: "state.tenant_config.validation_function"
      insert_after: "Process_Data"
      # Log injection for audit
      audit_injection: true
```

**Remember**: Dynamic injection is a **power tool** that trades debuggability for flexibility. Use sparingly and document thoroughly.

## Recent Migration (SDK Extraction)

This codebase was recently refactored from "Confucius" to "Rufus" with a focus on:
- Extracting core SDK from monolithic application
- Unified `Workflow` class (consolidating `WorkflowEngine`)
- Improved provider interfaces and dependency injection
- Better separation of concerns (SDK vs Server vs CLI)
- Enhanced sub-workflow status propagation
- Improved parallel execution with conflict detection

When making changes, be aware that:
- Some legacy `confucius/` code still exists in the repo
- Documentation may reference old patterns
- Tests in `tests/sdk/` cover the new architecture
