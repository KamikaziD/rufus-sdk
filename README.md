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

- **`PersistenceProvider`** - How workflow state/logs are stored (Postgres, Redis, In-Memory)
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
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor

builder = WorkflowBuilder(
    registry_path="workflow_registry.yaml",
    persistence_provider=InMemoryPersistence(),
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

**Recent Migration**: The project was recently refactored from "Confucius" to "Rufus" with focus on:
- Extracting core SDK from monolithic application
- Unified `Workflow` class architecture
- Improved provider interfaces and dependency injection
- Better separation: Core SDK vs Server vs CLI
- Enhanced sub-workflow status propagation

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

- **[CLAUDE.md](CLAUDE.md)** - Detailed project guidance for AI assistants
- **[USAGE_GUIDE.md](USAGE_GUIDE.md)** - Comprehensive usage documentation
- **[YAML_GUIDE.md](YAML_GUIDE.md)** - Complete YAML workflow syntax reference
- **[API_REFERENCE.md](API_REFERENCE.md)** - SDK API documentation
- **[CLI_REFERENCE.md](CLI_REFERENCE.md)** - Command-line tool documentation
- **[TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md)** - Architecture deep-dive

---

This is a robust, production-oriented workflow engine designed for Python developers who need sophisticated orchestration without the complexity of heavyweight workflow systems like Temporal or Airflow. Perfect for embedding workflows directly into applications while maintaining flexibility for distributed execution when needed.
