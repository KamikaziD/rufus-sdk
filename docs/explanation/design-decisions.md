# Design Decisions: Why Rufus is Built This Way

Rufus makes specific architectural choices that shape how you use it. Understanding the "why" behind these decisions helps you work with the framework, not against it.

## 1. Provider Pattern vs Monolithic Architecture

**Decision**: Abstract external dependencies behind provider interfaces.

**Alternatives Considered**:
- **Monolithic**: Hardcode PostgreSQL, Celery, etc. (like Confucius)
- **Microservices**: Separate services for persistence, execution, etc.
- **Plugin System**: Dynamic plugin loading at runtime

**Why Provider Pattern**:
- ✅ **Testability**: Inject in-memory providers for fast tests
- ✅ **Flexibility**: Swap SQLite ↔ PostgreSQL without code changes
- ✅ **Simplicity**: No separate services to deploy (unlike microservices)
- ✅ **Type Safety**: Protocol-based providers get type checking (unlike dynamic plugins)

**Trade-off**: More boilerplate (define provider interfaces), but significant flexibility gains.

**Example Impact**:
```python
# Without providers (Confucius)
# ALWAYS requires Redis + Celery for testing
def test_workflow():
    # Start Redis container...
    # Start Celery worker...
    workflow = Workflow(...)
    # Test logic
    # Stop Redis, Celery...

# With providers (Rufus)
# In-memory providers, no infrastructure
def test_workflow():
    persistence = MemoryPersistenceProvider()
    execution = SyncExecutionProvider()
    workflow = Workflow(..., persistence, execution)
    # Test logic (fast!)
```

## 2. SDK-First vs Framework-First

**Decision**: Rufus is a library (SDK), not a framework.

**Alternatives Considered**:
- **Framework**: Applications extend Rufus (like Django)
- **Service**: Rufus as a separate service (like Temporal)

**Why SDK-First**:
- ✅ **Embeddable**: Import into any Python application
- ✅ **Lightweight**: Core SDK is 10,373 lines, not 100k+
- ✅ **Flexible**: Use only what you need (no forced conventions)
- ✅ **Ownership**: Application owns the workflow lifecycle, not Rufus

**Trade-off**: Less "magic" (no auto-discovery, no CLI for free), but more control.

**Example Impact**:
```python
# SDK approach (Rufus)
from rufus.builder import WorkflowBuilder

builder = WorkflowBuilder(config_dir="config/")
workflow = builder.create_workflow("MyWorkflow", data)

# Application controls execution
if condition:
    await workflow.execute_next_step()

# Framework approach (alternative)
# Rufus would control execution, application extends
class MyWorkflowHandler(RufusWorkflowHandler):
    def on_step_executed(self, step, result):
        # Application logic
        pass

# Rufus runs application code, not vice versa
```

## 3. YAML Configuration vs Code-First

**Decision**: Workflows defined in YAML, step logic in Python.

**Alternatives Considered**:
- **Code-First**: Workflows defined in Python (like Airflow DAGs)
- **GUI-First**: Visual workflow editor (like n8n)
- **DSL**: Custom domain-specific language

**Why YAML**:
- ✅ **Separation of Concerns**: "What" (YAML) vs "How" (Python)
- ✅ **Version Control**: Easy to diff and review changes
- ✅ **Non-Programmer Friendly**: Business analysts can define workflows
- ✅ **Tooling**: YAML editors, linters, validators are mature

**Trade-off**: Boilerplate (separate files for config and code), but clearer separation.

**Example Impact**:
```yaml
# YAML approach (Rufus)
# config/order_processing.yaml
steps:
  - name: "Validate_Order"
    function: "myapp.steps.validate_order"
  - name: "Charge_Payment"
    function: "myapp.steps.charge_payment"

# Code-first approach (alternative)
# myapp/workflows.py
workflow = Workflow("OrderProcessing")
workflow.add_step("Validate_Order", validate_order)
workflow.add_step("Charge_Payment", charge_payment)
```

**Why Not Code-First**:
- Code-first mixes orchestration logic with business logic
- Harder to visualize (need to run code to see structure)
- Can't change workflow without changing code

## 4. Async/Await vs Callbacks

**Decision**: Async/await for I/O-bound operations (database, HTTP).

**Alternatives Considered**:
- **Synchronous**: Blocking I/O (simpler but slower)
- **Callbacks**: Node.js-style callbacks
- **Threads**: Threading for parallelism

**Why Async/Await**:
- ✅ **Performance**: Non-blocking I/O scales to 1000+ concurrent workflows
- ✅ **Pythonic**: Native Python async/await (since 3.5)
- ✅ **Readable**: Linear code flow (vs callback hell)
- ✅ **Efficient**: Event loop handles concurrency without thread overhead

**Trade-off**: Complexity (need to understand async/await), but significant performance gains.

**Example Impact**:
```python
# Async approach (Rufus)
async def save_workflow(self, workflow_id, workflow_dict):
    await self.conn.execute(
        "INSERT INTO workflow_executions ...",
        workflow_id, workflow_dict
    )
# Non-blocking, 1000+ concurrent workflows

# Sync approach (alternative)
def save_workflow(self, workflow_id, workflow_dict):
    self.conn.execute(...)
# Blocks thread, ~50 concurrent workflows max
```

## 5. State Model via Pydantic vs Raw Dicts

**Decision**: Workflow state is a Pydantic model.

**Alternatives Considered**:
- **Raw Dicts**: `state = {"order_id": "123", ...}`
- **Dataclasses**: Standard library dataclasses
- **Custom Classes**: Hand-written classes with validation

**Why Pydantic**:
- ✅ **Validation**: Automatic type checking and validation
- ✅ **Serialization**: Built-in JSON serialization
- ✅ **Documentation**: Models self-document state structure
- ✅ **IDE Support**: Autocomplete, type hints

**Trade-off**: Dependency on Pydantic (external library), but significant DX gains.

**Example Impact**:
```python
# Pydantic approach (Rufus)
class OrderState(BaseModel):
    order_id: str
    total_amount: float  # Validated as float

    @validator('total_amount')
    def amount_positive(cls, v):
        if v <= 0:
            raise ValueError('Amount must be positive')
        return v

# Raw dict approach (alternative)
state = {"order_id": "123", "total_amount": -10}  # No validation!
```

## 6. Snapshot Versioning vs Shared Definition

**Decision**: Each workflow gets a snapshot of its definition at creation time.

**Alternatives Considered**:
- **Shared Definition**: All workflows use latest YAML (breaking changes break running workflows)
- **Version Pinning**: Workflows specify version, load that version
- **Immutable Workflows**: Can't resume after YAML change

**Why Snapshots**:
- ✅ **Safety**: Running workflows immune to breaking changes
- ✅ **Zero Coordination**: Deploy new YAML without coordinating with running workflows
- ✅ **Natural Migration**: Old workflows drain, new workflows start

**Trade-off**: Storage overhead (~5-10KB per workflow), but critical for production reliability.

**Example Impact**:
```yaml
# Monday: Deploy v1 (with Manual_Approval step)
# 10,000 workflows created, some paused at Manual_Approval

# Tuesday: Deploy v2 (removes Manual_Approval)
# New workflows use v2
# Old workflows (from Monday) still use v1 snapshot
# Both versions coexist safely
```

## 7. Heartbeat-Based Zombie Detection vs Timeouts

**Decision**: Workers send periodic heartbeats, scanner detects stale heartbeats.

**Alternatives Considered**:
- **Simple Timeouts**: Mark workflow as failed after N seconds
- **Task Acknowledgment**: Worker acknowledges before task execution
- **Health Checks**: Periodic health checks to workers

**Why Heartbeats**:
- ✅ **Granular**: Detects crashes during execution (not just before)
- ✅ **Flexible**: Different steps have different durations
- ✅ **Non-Invasive**: Background thread handles heartbeats

**Trade-off**: Database overhead (heartbeat writes), but robust crash detection.

**Example Impact**:
```python
# Heartbeat approach (Rufus)
# Long-running step (5 minutes)
async with HeartbeatManager(..., interval_seconds=30):
    result = await process_large_file()
# Heartbeats every 30s, crash detected within 60s

# Timeout approach (alternative)
# Set timeout: 5 minutes (too short? too long?)
# If step crashes after 4 minutes, not detected for another minute
```

## 8. Protocol-Based Providers vs ABC Inheritance

**Decision**: Providers are Python Protocols (structural subtyping).

**Alternatives Considered**:
- **ABC**: Abstract base classes (nominal subtyping)
- **Duck Typing**: No interface definition at all

**Why Protocols**:
- ✅ **Flexibility**: Don't need to inherit from base class
- ✅ **Type Safety**: Still get type checking (mypy, pyright)
- ✅ **Third-Party**: External providers don't need to import Rufus

**Trade-off**: Less enforcement (no runtime check), but more flexibility.

**Example Impact**:
```python
# Protocol approach (Rufus)
class PersistenceProvider(Protocol):
    async def save_workflow(self, ...) -> None: ...

# Any class with this method works
class MyCustomPersistence:
    async def save_workflow(self, ...):
        # Custom implementation
        pass

persistence = MyCustomPersistence()  # Works!

# ABC approach (alternative)
class PersistenceProvider(ABC):
    @abstractmethod
    async def save_workflow(self, ...): ...

class MyCustomPersistence(PersistenceProvider):  # Must inherit
    async def save_workflow(self, ...):
        pass
```

## 9. SQLite Support vs PostgreSQL-Only

**Decision**: First-class support for both SQLite and PostgreSQL.

**Alternatives Considered**:
- **PostgreSQL-Only**: Simpler codebase, but no offline support
- **Multiple Backends**: Support many databases (MySQL, MongoDB, etc.)

**Why SQLite + PostgreSQL**:
- ✅ **Development**: SQLite for local development (zero setup)
- ✅ **Edge Devices**: SQLite for offline-first (POS terminals, ATMs)
- ✅ **Production**: PostgreSQL for cloud deployments (ACID, scalability)
- ✅ **Testing**: SQLite in-memory for fast tests

**Trade-off**: Maintain two persistence providers, but critical for edge use cases.

**Example Impact**:
```python
# Development
persistence = SQLitePersistenceProvider(db_path="dev.db")

# Testing
persistence = SQLitePersistenceProvider(db_path=":memory:")

# Production
persistence = PostgresPersistenceProvider(db_url=os.environ["DATABASE_URL"])

# Same workflow code works everywhere
```

## 10. Saga Pattern vs Distributed Transactions

**Decision**: Saga pattern for distributed transaction compensation.

**Alternatives Considered**:
- **2PC**: Two-phase commit (requires distributed transaction coordinator)
- **No Rollback**: Accept eventual consistency, no compensation

**Why Saga**:
- ✅ **Practical**: Works with external APIs (payment gateways, etc.)
- ✅ **Flexible**: Compensation logic is application-specific
- ✅ **No Coordinator**: No need for XA transactions

**Trade-off**: Best-effort compensation (not guaranteed), but suitable for distributed systems.

**Example Impact**:
```python
# Saga approach (Rufus)
# Reserve flight, hotel, charge payment
# If payment fails, compensate (cancel flight + hotel)

# 2PC approach (alternative)
# Requires all services support 2PC (most don't)
# Payment gateway doesn't support XA transactions
```

## 11. CLI + Server vs Server-Only

**Decision**: Separate CLI tool (`rufus`) and API server (`rufus_server`).

**Alternatives Considered**:
- **Server-Only**: All operations via REST API
- **CLI-Only**: No server, local operations only

**Why Both**:
- ✅ **Ops Workflows**: CLI for automation, cron jobs, kubectl exec
- ✅ **UI Integration**: Server for web dashboards, integrations
- ✅ **Flexibility**: Use CLI for dev, server for prod

**Trade-off**: More components to maintain, but better DX.

**Example Impact**:
```bash
# CLI approach (Rufus)
rufus list --status ACTIVE
rufus retry <workflow-id> --from-step Process_Payment

# API approach (alternative)
curl -X GET http://localhost:8000/api/v1/workflows?status=ACTIVE
curl -X POST http://localhost:8000/api/v1/workflows/<id>/retry \
  -d '{"from_step": "Process_Payment"}'
```

## 12. Explicit Step Dependencies vs Implicit Ordering

**Decision**: Steps can declare dependencies, but default is sequential.

**Alternatives Considered**:
- **DAG-First**: All workflows are DAGs (like Airflow)
- **Implicit-Only**: Steps execute in order, no dependencies

**Why Hybrid**:
- ✅ **Simple Workflows**: Sequential steps (90% of workflows)
- ✅ **Complex Workflows**: Explicit dependencies for parallel execution
- ✅ **Opt-In Complexity**: Only use dependencies when needed

**Trade-off**: Two ways to express ordering, but flexibility for advanced use cases.

**Example Impact**:
```yaml
# Simple (sequential)
steps:
  - name: "A"
  - name: "B"  # Runs after A
  - name: "C"  # Runs after B

# Complex (with dependencies)
steps:
  - name: "A"
  - name: "B"
    dependencies: ["A"]
  - name: "C"
    dependencies: ["A"]  # B and C run in parallel after A
```

## Trade-offs Summary

| Decision | Benefit | Cost |
|----------|---------|------|
| **Provider Pattern** | Flexibility, testability | More boilerplate |
| **SDK-First** | Embeddable, lightweight | Less "magic" |
| **YAML Config** | Separation, version control | File duplication |
| **Async/Await** | Performance, scalability | Complexity |
| **Pydantic Models** | Validation, DX | External dependency |
| **Snapshots** | Safety, zero-downtime deploys | Storage overhead |
| **Heartbeats** | Robust crash detection | Database overhead |
| **Protocols** | Flexibility, third-party providers | Less enforcement |
| **SQLite Support** | Dev/test/edge use cases | Maintain 2 backends |
| **Saga Pattern** | Distributed compensation | Best-effort only |
| **CLI + Server** | DX, ops workflows | More components |
| **Hybrid Dependencies** | Simplicity + power | Two ordering models |

## Lessons from Confucius

Rufus learned from Confucius's shortcomings:

1. **Hardcoded Dependencies** → Provider pattern
2. **No Testability** → In-memory providers
3. **Breaking Changes** → Workflow snapshots
4. **No Zombie Detection** → Heartbeat system
5. **Manual Scaling** → Kubernetes + auto-scaling
6. **No CLI** → Rufus CLI tool

These lessons shaped Rufus's production-first philosophy.

## What's Next

Now that you understand the design decisions:
- [Architecture](architecture.md) - How decisions shape architecture
- [Provider Pattern](provider-pattern.md) - Deep dive on providers
- [Performance](performance.md) - How design enables performance
