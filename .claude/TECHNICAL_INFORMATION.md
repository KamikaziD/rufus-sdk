# Technical Reference

This document contains all code examples, YAML configs, and technical reference extracted from CLAUDE.md.
Referenced as `→ See TECHNICAL_INFORMATION.md §N` throughout CLAUDE.md.

---

## §1 Workflow Definition (YAML + Python examples)

### State Model Definition

```python
# my_app/state_models.py
from pydantic import BaseModel
from typing import Optional

class MyWorkflowState(BaseModel):
    user_id: str
    status: Optional[str] = None
    result_data: Optional[dict] = None
```

### Step Function Signatures

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

### Workflow YAML Structure

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

### Step Configuration Keys Reference

| Key | Description |
|-----|-------------|
| `name` | Unique step identifier within workflow |
| `type` | Execution type (STANDARD, ASYNC, DECISION, PARALLEL, HTTP, LOOP, FIRE_AND_FORGET, CRON_SCHEDULE, HUMAN_IN_LOOP) |
| `function` | Python path to step function |
| `compensate_function` | Optional compensation for Saga pattern |
| `input_model` | Pydantic model for input validation |
| `automate_next` | Boolean flag to auto-execute next step |
| `dependencies` | List of prerequisite step names |
| `dynamic_injection` | Rules for runtime step insertion |
| `routes` | Declarative routing for DECISION steps |

### Registry Format

```yaml
# config/workflow_registry.yaml
workflows:
  - type: "MyWorkflow"
    description: "My custom workflow"
    config_file: "my_workflow.yaml"
    initial_state_model: "my_app.state_models.MyWorkflowState"
```

---

## §2 Control Flow Code Examples

### Automated Step Chaining (automate_next)

Set `automate_next: true` in step config — return value becomes input for next step automatically.

### Conditional Branching (WorkflowJumpDirective)

```python
from rufus.models import WorkflowJumpDirective

def decision_step(state: MyState, context: StepContext):
    if state.amount > 10000:
        raise WorkflowJumpDirective(target_step_name="High_Value_Process")
    else:
        raise WorkflowJumpDirective(target_step_name="Standard_Process")
```

### Human-in-the-Loop (WorkflowPauseDirective)

```python
from rufus.models import WorkflowPauseDirective

def approval_step(state: MyState, context: StepContext):
    raise WorkflowPauseDirective(result={"awaiting_approval": True})
```

### Sub-Workflows (StartSubWorkflowDirective)

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

### Parallel Execution YAML Config

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

---

## §3 Saga Pattern (Code Examples)

### Enable Saga Mode

```python
workflow = workflow_builder.create_workflow("OrderProcessing", initial_data)
workflow.enable_saga_mode()
```

### Compensatable Step Functions

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

### Saga YAML Linkage

```yaml
- name: "Charge_Payment"
  type: "STANDARD"
  function: "my_app.steps.charge_payment"
  compensate_function: "my_app.steps.refund_payment"
```

**Behavior:** On failure, compensation functions execute in reverse order. Workflow status becomes `FAILED_ROLLED_BACK`.

---

## §4 Advanced Step Types (Complete Configs)

### Loop Steps

```yaml
# Basic loop over collection
- name: "Process_Batch"
  type: "LOOP"
  loop_config:
    items: "{{state.user_ids}}"
    item_var: "current_user_id"
    max_iterations: 100
  function: "steps.process_user"
  automate_next: true

# Conditional loop
- name: "Poll_Until_Ready"
  type: "LOOP"
  loop_config:
    condition: "state.status != 'ready'"
    max_iterations: 10
    delay_seconds: 5
  function: "steps.check_status"
```

Loop step function (receives `item_var` as parameter):
```python
def process_user(state: MyState, context: StepContext, current_user_id: str) -> dict:
    result = process_single_user(current_user_id)
    return {"processed_count": state.processed_count + 1}
```

### Fire-and-Forget Steps

```yaml
- name: "Send_Notification"
  type: "FIRE_AND_FORGET"
  function: "steps.send_email"
  fire_and_forget_config:
    timeout_seconds: 30
    on_error: "log"  # Options: log, ignore, fail_workflow
```

```python
def send_email(state: OrderState, context: StepContext) -> dict:
    """Executes asynchronously — workflow doesn't wait."""
    email_service.send(
        to=state.customer_email,
        subject="Order Confirmation",
        body=f"Order {state.order_id} confirmed"
    )
    return {}  # Return value not merged into workflow state
```

### Cron Schedule Steps

```yaml
- name: "Daily_Report"
  type: "CRON_SCHEDULE"
  cron_config:
    cron_expression: "0 9 * * *"  # Every day at 9 AM
    timezone: "America/New_York"
  function: "steps.generate_report"

- name: "Hourly_Sync"
  type: "CRON_SCHEDULE"
  cron_config:
    cron_expression: "0 * * * *"  # Every hour
    max_runs: 100
  function: "steps.sync_data"
```

Cron expression format: `minute hour day-of-month month day-of-week`

Common expressions:
- `0 0 * * *` — Daily at midnight
- `0 9 * * 1-5` — Weekdays at 9 AM
- `*/15 * * * *` — Every 15 minutes
- `0 0 1 * *` — First day of every month

### Combined E-commerce Example (Loop + Fire-and-Forget + HTTP + Cron)

```yaml
workflow_type: "OrderProcessing"
initial_state_model: "models.OrderState"

steps:
  - name: "Validate_Order"
    type: "STANDARD"
    function: "steps.validate_order"
    automate_next: true

  - name: "Reserve_Inventory"
    type: "LOOP"
    loop_config:
      items: "{{state.order_items}}"
      item_var: "item"
      max_iterations: 50
    function: "steps.reserve_item"
    automate_next: true

  - name: "Send_SMS_Notification"
    type: "FIRE_AND_FORGET"
    function: "steps.send_sms"

  - name: "Process_Payment"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "https://payment-gateway.com/charge"
      body:
        amount: "{{state.total_amount}}"
        token: "{{state.payment_token}}"
    automate_next: true

  - name: "Schedule_Followup"
    type: "CRON_SCHEDULE"
    cron_config:
      cron_expression: "0 0 * * *"
      max_runs: 7
    function: "steps.check_delivery_status"
```

---

## §5 HTTP Steps / Polyglot Workflows

### HTTP Step Configuration

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

### Multi-Language Pipeline Example

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

---

## §6 Celery Distributed Execution

### Installation

```bash
# Install with Celery support
pip install "rufus[celery] @ git+https://github.com/KamikaziD/rufus-sdk.git"

# Or install directly
pip install celery redis psycopg2-binary prometheus-client

# Start Redis
docker run -d --name redis -p 6379:6379 redis:latest
```

### Configuration (Environment Variables)

```bash
export CELERY_BROKER_URL="redis://localhost:6379/0"
export CELERY_RESULT_BACKEND="redis://localhost:6379/0"
export DATABASE_URL="postgresql://user:pass@localhost:5432/rufus"

# Optional worker config
export WORKER_ID="worker-01"
export WORKER_REGION="us-east-1"
export WORKER_ZONE="us-east-1a"
export WORKER_CAPABILITIES='{"gpu": true, "memory_gb": 16}'
```

### Celery App Setup

```python
# my_app/celery_app.py
from rufus.celery_app import celery_app

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

app = celery_app
```

### Worker Startup Commands

```bash
# Basic worker (development)
celery -A rufus.celery_app worker --loglevel=info --autoreload

# Production worker
celery -A rufus.celery_app worker --loglevel=warning --concurrency=4

# Regional workers
export WORKER_REGION="us-east-1"
celery -A rufus.celery_app worker -Q us-east-1,default --loglevel=info

# GPU-enabled worker
export WORKER_CAPABILITIES='{"gpu": true, "cuda_version": "12.1"}'
celery -A rufus.celery_app worker -Q gpu-tasks --loglevel=info
```

### CeleryExecutionProvider Usage

```python
from rufus.builder import WorkflowBuilder
from rufus.implementations.execution.celery import CeleryExecutionProvider
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
from rufus.implementations.observability.logging import LoggingObserver

execution_provider = CeleryExecutionProvider()
persistence = PostgresPersistenceProvider(db_url="postgresql://localhost/rufus")
await persistence.initialize()

builder = WorkflowBuilder(
    config_dir="config/",
    persistence_provider=persistence,
    execution_provider=execution_provider,
    observer=LoggingObserver()
)

workflow = await builder.create_workflow(
    workflow_type="OrderProcessing",
    initial_data={"order_id": "12345"},
    data_region="us-east-1"
)
await workflow.next_step()
```

### Async Steps Example

```python
# my_app/tasks.py
from rufus.celery_app import celery_app

@celery_app.task
def process_payment(state: dict, workflow_id: str):
    """Long-running payment processing task."""
    import time
    time.sleep(10)
    return {
        "transaction_id": "tx_12345",
        "status": "approved",
        "amount": state.get("amount", 0)
    }
```

```yaml
# YAML for async step
- name: "Process_Payment"
  type: "ASYNC"
  function: "my_app.tasks.process_payment"
  automate_next: true
```

Execution flow: workflow hits step → status `PENDING_ASYNC` → Celery task dispatched → worker processes → `resume_from_async_task` called → workflow resumes.

### Parallel Execution Example

```yaml
steps:
  - name: "Parallel_Checks"
    type: "PARALLEL"
    tasks:
      - name: "credit_check"
        function_path: "my_app.tasks.check_credit"
      - name: "inventory_check"
        function_path: "my_app.tasks.check_inventory"
      - name: "fraud_check"
        function_path: "my_app.tasks.check_fraud"
    merge_strategy: "SHALLOW"
    merge_conflict_behavior: "PREFER_NEW"
    allow_partial_success: false
    timeout_seconds: 60
```

```python
@celery_app.task
def check_credit(state: dict, workflow_id: str):
    return {"credit_score": 750, "approved": True}

@celery_app.task
def check_inventory(state: dict, workflow_id: str):
    return {"in_stock": True, "quantity": 50}

@celery_app.task
def check_fraud(state: dict, workflow_id: str):
    return {"fraud_score": 0.05, "risk_level": "low"}
```

### Sub-Workflow Example

```python
from rufus.models import StartSubWorkflowDirective

def trigger_kyc(state: OrderState, context: StepContext):
    raise StartSubWorkflowDirective(
        workflow_type="KYC",
        initial_data={"user_id": state.user_id, "document_url": state.id_document},
        data_region="eu-central-1"
    )
```

Execution flow: parent creates child → status `PENDING_SUB_WORKFLOW` → Celery `execute_sub_workflow` dispatched → child completes → `resume_parent_from_child` dispatched → parent resumes with `state.sub_workflow_results["KYC"]`.

### Worker Registry SQL

```sql
CREATE TABLE worker_nodes (
    worker_id VARCHAR(100) PRIMARY KEY,
    hostname VARCHAR(255),
    region VARCHAR(50),
    zone VARCHAR(50),
    capabilities JSONB DEFAULT '{}',
    status VARCHAR(20),  -- 'online', 'offline'
    last_heartbeat TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Active workers query
SELECT worker_id, hostname, region, last_heartbeat
FROM worker_nodes
WHERE status = 'online'
  AND last_heartbeat > NOW() - INTERVAL '2 minutes';

-- Workers by region
SELECT region, COUNT(*) as worker_count
FROM worker_nodes WHERE status = 'online'
GROUP BY region;
```

### Event Publishing

```bash
# Redis Streams (persistent events)
redis-cli XREAD STREAMS workflow:persistence 0
redis-cli XREAD STREAMS workflow:retry:bridge 0
```

```python
import redis.asyncio as redis

async def monitor_workflow(workflow_id: str):
    r = redis.from_url("redis://localhost:6379")
    pubsub = r.pubsub()
    await pubsub.subscribe(f"workflow:events:{workflow_id}")
    async for message in pubsub.listen():
        if message['type'] == 'message':
            print(f"Event: {message['data']}")
```

### Monitoring with Flower

```bash
pip install flower
celery -A rufus.celery_app flower --port=5555
# Open http://localhost:5555
```

### Production Docker Compose

```yaml
version: '3.8'
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: rufus
      POSTGRES_PASSWORD: secret
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  worker:
    build: .
    command: celery -A rufus.celery_app worker --loglevel=info --concurrency=4
    environment:
      DATABASE_URL: postgresql://postgres:secret@postgres/rufus
      CELERY_BROKER_URL: redis://redis:6379/0
      CELERY_RESULT_BACKEND: redis://redis:6379/0
      WORKER_REGION: us-east-1
    depends_on:
      - postgres
      - redis
    deploy:
      replicas: 3

  api:
    build: .
    command: uvicorn rufus_server.main:app --host 0.0.0.0
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://postgres:secret@postgres/rufus
    depends_on:
      - postgres
      - redis
      - worker
```

### Kubernetes Deployment YAML

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rufus-worker
spec:
  replicas: 5
  selector:
    matchLabels:
      app: rufus-worker
  template:
    metadata:
      labels:
        app: rufus-worker
    spec:
      containers:
      - name: worker
        image: myregistry/rufus-worker:latest
        command: ["celery", "-A", "rufus.celery_app", "worker", "--concurrency=4"]
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: rufus-secrets
              key: database-url
        - name: CELERY_BROKER_URL
          value: "redis://redis-service:6379/0"
        - name: WORKER_REGION
          value: "us-east-1"
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
```

### Troubleshooting

```bash
# Workers not picking up tasks
redis-cli ping
celery -A rufus.celery_app inspect active
celery -A rufus.celery_app inspect registered

# Workflows stuck in PENDING_ASYNC
celery -A rufus.celery_app events
redis-cli GET celery-task-meta-<task_id>
celery -A rufus.celery_app worker --loglevel=debug
```

```sql
-- Worker registry not updating
SELECT * FROM worker_nodes ORDER BY last_heartbeat DESC;
UPDATE worker_nodes SET status = 'offline' WHERE last_heartbeat < NOW() - INTERVAL '10 minutes';
```

### Performance Tuning

```bash
# CPU-bound tasks
celery -A rufus.celery_app worker --concurrency=2

# I/O-bound tasks
celery -A rufus.celery_app worker --concurrency=20

# Auto-scale
celery -A rufus.celery_app worker --autoscale=10,2
```

```python
@celery_app.task(time_limit=300, soft_time_limit=270)
def long_running_task(state: dict, workflow_id: str):
    pass

celery_app.conf.update(result_expires=3600)
```

---

## §7 Testing Patterns

### TestHarness Usage

```python
from rufus.testing.harness import TestHarness

harness = TestHarness()
workflow = harness.start_workflow(
    workflow_type="MyWorkflow",
    initial_data={"user_id": "123"}
)
result = harness.next_step(workflow.id, user_input={"param": "value"})
assert workflow.state.status == "completed"
```

### SQLite Fixture for Tests

```python
import pytest
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider

@pytest.fixture
async def persistence():
    provider = SQLitePersistenceProvider(db_path=":memory:")
    await provider.initialize()
    yield provider
    await provider.close()
```

### Executor Portability Testing

```python
import pytest
from rufus.implementations.execution.sync import SyncExecutionProvider
from rufus.implementations.execution.thread_pool import ThreadPoolExecutionProvider

@pytest.mark.parametrize("executor", [
    SyncExecutionProvider(),
    ThreadPoolExecutionProvider()
])
def test_workflow_executor_portable(executor):
    """Test that workflow works with both sync and threaded execution."""
    builder = WorkflowBuilder(config_dir="config/", execution_provider=executor)
    workflow = builder.create_workflow("MyWorkflow", initial_data={...})
    ...
```

---

## §8 Performance Optimizations (Code)

### uvloop

```python
# Automatically enabled on import
import rufus  # uvloop configured here

# Disable for debugging
# export RUFUS_USE_UVLOOP=false
```

### orjson Serialization

```python
from rufus.utils.serialization import serialize, deserialize

json_str = serialize({"key": "value"})
data = deserialize(json_str)

# Disable for debugging
# export RUFUS_USE_ORJSON=false
```

### PostgreSQL Connection Pool Config

```python
persistence = PostgresPersistenceProvider(
    db_url=db_url,
    pool_min_size=10,
    pool_max_size=50
)
```

Environment variables:
- `POSTGRES_POOL_MIN_SIZE` (default: 10)
- `POSTGRES_POOL_MAX_SIZE` (default: 50)
- `POSTGRES_POOL_COMMAND_TIMEOUT` (default: 10)
- `POSTGRES_POOL_MAX_QUERIES` (default: 50000)
- `POSTGRES_POOL_MAX_INACTIVE_LIFETIME` (default: 300)

### Import Caching

```python
# Cached automatically — no code changes needed
func = WorkflowBuilder._import_from_string("my_app.steps.process_data")
# 162x speedup for repeated imports
```

### Benchmark Results

```
Serialization: 2,453,971 ops/sec (orjson)
Import Caching: 162x speedup
Async Latency: 5.5µs p50, 12.7µs p99 (uvloop)
Workflow Throughput: 703,633 workflows/sec (simplified)
```

Run: `python tests/benchmarks/workflow_performance.py`

---

## §9 Database Schema Management

> **Schema governance update (v0.4.2+):** `src/rufus/db_schema/database.py` now covers
> all 33 cloud PostgreSQL tables. `migrations/schema.yaml` is deprecated — do not add
> new tables there. See §16 for the complete table inventory and edge vs cloud separation.

### Alembic Migration Commands

```bash
cd src/rufus

# Auto-generate migration from SQLAlchemy model changes
alembic revision --autogenerate -m "add user preferences table"

# Create empty migration for manual SQL
alembic revision -m "add custom index"

# Apply migrations
export DATABASE_URL="postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud"
alembic upgrade head

# Inspect
alembic current
alembic history
alembic downgrade -1  # Rollback one migration

# SQLite
export DATABASE_URL="sqlite:///workflow.db"
alembic upgrade head
```

### SQLAlchemy Table Definition Example

```python
# src/rufus/db_schema/database.py
from sqlalchemy import Table, Column, String, Text, DateTime, func

user_preferences = Table(
    'user_preferences',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('user_id', String(200), nullable=False, index=True),
    Column('preferences', Text, server_default='{}'),
    Column('created_at', DateTime, server_default=func.now()),
)
```

### Type Mappings

| SQLAlchemy Type | PostgreSQL | SQLite | Notes |
|-----------------|------------|--------|-------|
| `String(36)` | VARCHAR(36) | TEXT | For UUIDs |
| `Text` | TEXT | TEXT | For JSONB in SQLite |
| `DateTime` | TIMESTAMPTZ | TEXT | Timezone-aware |
| `Boolean` | BOOLEAN | INTEGER | 0/1 in SQLite |
| `Integer` | INTEGER | INTEGER | Auto-increment |
| `LargeBinary` | BYTEA | BLOB | For encrypted state |

### Schema Modification Process

1. Edit `src/rufus/db_schema/database.py`
2. `alembic revision --autogenerate -m "description"`
3. Review generated migration (Alembic ~15% false positive rate)
4. Test: `alembic upgrade head` then `alembic downgrade -1` then `alembic upgrade head`
5. Update raw SQL in persistence providers if schema changed
6. Commit both SQLAlchemy models + migration file

### Deployment Recipes

```bash
# Development (SQLite)
export DATABASE_URL="sqlite:///dev.db"
cd src/rufus && alembic upgrade head

# Development (PostgreSQL Docker)
docker compose up postgres -d
export DATABASE_URL="postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud"
cd src/rufus && alembic upgrade head

# Production fresh install
export DATABASE_URL="postgresql://user:pass@host:5432/dbname"
cd src/rufus && alembic upgrade head
```

Docker entrypoint:
```yaml
command: >
  sh -c "
    cd /app/src/rufus &&
    alembic upgrade head &&
    cd /app &&
    uvicorn rufus_server.main:app --host 0.0.0.0
  "
```

---

## §10 SQLite Persistence Provider

### Usage Examples

```python
# In-memory (testing)
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider

persistence = SQLitePersistenceProvider(db_path=":memory:")
await persistence.initialize()

# File-based (development)
persistence = SQLitePersistenceProvider(db_path="workflows.db")
await persistence.initialize()
```

### Full Workflow Integration

```python
from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.execution.sync import SyncExecutionProvider
from rufus.implementations.observability.logging import LoggingObserver

persistence = SQLitePersistenceProvider(db_path="workflows.db")
await persistence.initialize()

builder = WorkflowBuilder(
    config_dir="config/",
    persistence_provider=persistence,
    execution_provider=SyncExecutionProvider(),
    observer=LoggingObserver()
)

workflow = await builder.create_workflow("MyWorkflow", initial_data={"user_id": "123"})
```

### Configuration Options

```python
SQLitePersistenceProvider(
    db_path=":memory:",        # or "path/to/db.sqlite"
    timeout=5.0,               # Lock timeout in seconds
    check_same_thread=False    # Allow multi-threaded access
)
```

### Performance Benchmarks (Single-threaded, In-Memory)

```
save_workflow:  ~9,000 ops/sec
load_workflow:  ~6,500 ops/sec
create_task:    ~7,800 ops/sec
log_execution:  ~9,000 ops/sec
record_metric:  ~8,500 ops/sec
```

Run: `python tests/benchmarks/persistence_benchmark.py`

### Limitations and Workarounds

**No LISTEN/NOTIFY — use polling:**
```python
async def poll_workflow_status(workflow_id):
    while True:
        workflow = await persistence.load_workflow(workflow_id)
        if workflow['status'] in ['COMPLETED', 'FAILED']:
            break
        await asyncio.sleep(1)
```

**"database is locked" — increase timeout:**
```python
persistence = SQLitePersistenceProvider(db_path="workflows.db", timeout=30.0)
```

**Check WAL mode:**
```python
async with persistence.conn.execute("PRAGMA journal_mode") as cursor:
    mode = await cursor.fetchone()
    print(f"Journal mode: {mode[0]}")  # Should be 'wal'
```

---

## §11 Production Reliability

### HeartbeatManager Usage

```python
from rufus.heartbeat import HeartbeatManager

async def custom_step(state: MyState, context: StepContext):
    heartbeat = HeartbeatManager(
        persistence=context.persistence,
        workflow_id=context.workflow_id,
        heartbeat_interval_seconds=30
    )
    async with heartbeat:
        result = await complex_computation(state)
        return {"result": result}
```

Manual control:
```python
heartbeat = HeartbeatManager(
    persistence=persistence_provider,
    workflow_id=uuid.UUID(...),
    worker_id="custom-worker-123",
    heartbeat_interval_seconds=30
)
await heartbeat.start(current_step="Process_Payment", metadata={"custom": "data"})
# ... execute step ...
await heartbeat.stop()
```

### ZombieScanner (CLI)

```bash
# One-shot scan (dry-run)
rufus scan-zombies --db postgresql://localhost/rufus

# Scan and fix
rufus scan-zombies --db postgresql://localhost/rufus --fix

# Custom threshold
rufus scan-zombies --db postgresql://localhost/rufus --fix --threshold 180

# JSON output
rufus scan-zombies --db postgresql://localhost/rufus --json

# Continuous daemon
rufus zombie-daemon --db postgresql://localhost/rufus
rufus zombie-daemon --db postgresql://localhost/rufus --interval 60 --threshold 120
```

### ZombieScanner (Programmatic)

```python
from rufus.zombie_scanner import ZombieScanner
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider

persistence = PostgresPersistenceProvider(db_url)
await persistence.initialize()

scanner = ZombieScanner(persistence=persistence, stale_threshold_seconds=120)

summary = await scanner.scan_and_recover(dry_run=False)
print(f"Found {summary['zombies_found']}, recovered {summary['zombies_recovered']}")

# Or separately
zombies = await scanner.scan()
recovered_count = await scanner.recover(zombies, dry_run=False)

# Daemon mode
await scanner.run_daemon(scan_interval_seconds=60, stale_threshold_seconds=120)
```

### Zombie Heartbeats Schema

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

### Deployment Options

**Cron job:**
```bash
* * * * * rufus scan-zombies --db $DATABASE_URL --fix >> /var/log/rufus/zombie-scanner.log 2>&1
```

**Systemd service:**
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

**Kubernetes CronJob:**
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: rufus-zombie-scanner
spec:
  schedule: "*/5 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: scanner
            image: myapp/rufus:latest
            command: ["rufus", "scan-zombies", "--db", "postgresql://postgres/rufus", "--fix"]
          restartPolicy: OnFailure
```

### Configuration Recommendations

| Workload | Heartbeat Interval | Stale Threshold | Scan Interval |
|----------|-------------------|-----------------|---------------|
| Fast steps (< 1 min) | 15s | 60s | 30s |
| Medium steps (1–10 min) | 30s | 120s | 60s |
| Long steps (10+ min) | 60s | 300s | 120s |
| Very long steps (hours) | 300s | 900s | 300s |

**Key rule:** `Stale Threshold > 2 × Heartbeat Interval` to avoid false positives.

---

## §12 Workflow Versioning

### Automatic Snapshotting

Snapshotting is **automatic** — no code changes required:

```python
workflow = await builder.create_workflow("OrderProcessing", initial_data)

# Snapshot automatically stored
assert workflow.definition_snapshot is not None
assert workflow.definition_snapshot['workflow_type'] == "OrderProcessing"
print(f"Workflow version: {workflow.workflow_version}")
```

### YAML Versioning

```yaml
workflow_type: "OrderProcessing"
workflow_version: "1.5.0"  # Explicit version
initial_state_model: "my_app.models.OrderState"
steps:
  - name: "Validate_Order"
    ...
```

### Breaking Changes Strategy

**Option A: Multiple YAML files (different types):**
```yaml
# workflow_registry.yaml
workflows:
  - type: "OrderProcessing_v1"
    config_file: "order_processing_v1.yaml"
    deprecated: true
  - type: "OrderProcessing_v2"
    config_file: "order_processing_v2.yaml"
```

**Option B: Rely on snapshots (recommended)** — just update the YAML and bump `workflow_version`. Running workflows use their saved snapshot; new workflows use updated YAML.

### Version Compatibility Check (Optional)

```python
def check_version_compatibility(snapshot_version: str, current_version: str) -> bool:
    if not snapshot_version or not current_version:
        return True
    snap_major = int(snapshot_version.split('.')[0])
    curr_major = int(current_version.split('.')[0])
    return snap_major == curr_major
```

### Troubleshooting SQL

```sql
-- Check snapshot contents
SELECT
    AVG(LENGTH(definition_snapshot::text)) AS avg_snapshot_size_bytes,
    MAX(LENGTH(definition_snapshot::text)) AS max_snapshot_size_bytes
FROM workflow_executions
WHERE definition_snapshot IS NOT NULL;

-- Existing workflows without snapshots (backward compatible)
SELECT COUNT(*) FROM workflow_executions WHERE definition_snapshot IS NULL;
```

---

## §13 Executor Portability (Code Examples)

### Anti-patterns vs Correct Patterns

```python
# ❌ BREAKS in CeleryExecutor — global state lost between steps
global_cache = {}

def step_a(state: MyState, context: StepContext):
    global_cache['user_data'] = fetch_user(state.user_id)
    return {}

def step_b(state: MyState, context: StepContext):
    user_data = global_cache['user_data']  # KeyError in Celery!
    return {"name": user_data['name']}


# ❌ BREAKS in CeleryExecutor — module-level state lost
_connection = None

def step_c(state: MyState, context: StepContext):
    global _connection
    if _connection is None:
        _connection = create_db_connection()
    _connection.query(...)  # Different worker, _connection is None!


# ✅ WORKS everywhere — persist everything in workflow state
def step_a_correct(state: MyState, context: StepContext):
    user_data = fetch_user(state.user_id)
    state.user_data = user_data  # Persisted to database
    return {"user_data": user_data}

def step_b_correct(state: MyState, context: StepContext):
    user_data = state.user_data  # Loaded from database
    return {"name": user_data['name']}


# ✅ WORKS everywhere — create resources per step
def step_c_correct(state: MyState, context: StepContext):
    connection = create_db_connection()
    result = connection.query(...)
    return {"query_result": result}
```

---

## §14 Dynamic Injection (Code Examples)

### Problem Illustration

```yaml
# my_workflow.yaml — dynamic_injection creates steps invisible in YAML
steps:
  - name: "Process_Order"
    type: "STANDARD"
    function: "steps.process_order"
    dynamic_injection:
      condition: "state.amount > 10000"
      steps:
        - name: "High_Value_Review"  # NOT in YAML!
          function: "steps.high_value_review"
      insert_after: "Process_Order"
```

This makes audit logs reference steps not in the YAML file — debugging nightmare.

### Recommended Alternatives

**1. DECISION step with explicit routes (preferred):**
```yaml
steps:
  - name: "Check_Order_Value"
    type: "DECISION"
    function: "steps.check_order_value"
    routes:
      - condition: "state.amount > 10000"
        target: "High_Value_Review"
      - condition: "state.amount <= 10000"
        target: "Standard_Processing"

  - name: "High_Value_Review"
    type: "STANDARD"
    function: "steps.high_value_review"
    dependencies: ["Check_Order_Value"]
```

**2. Conditional logic within a single step:**
```python
def process_order(state: OrderState, context: StepContext):
    if state.amount > 10000:
        perform_high_value_checks(state)
    else:
        perform_standard_checks(state)
    return {"processed": True}
```

**3. Multiple workflow types:**
```yaml
# order_processing_standard.yaml + order_processing_high_value.yaml
# High-value step explicit in its own YAML
```

### If You Must Use Dynamic Injection

```yaml
steps:
  - name: "Process_Data"
    type: "STANDARD"
    function: "steps.process_data"
    dynamic_injection:
      # DOCUMENT WHY: Multi-tenant workflow, tenants define custom validation
      condition: "state.tenant_config.has_custom_validation"
      steps:
        - name: "Custom_Validation"
          function: "state.tenant_config.validation_function"
      insert_after: "Process_Data"
      audit_injection: true
```

---

## §15 — Workflow API Error Reference

| Status | Condition | Example `detail` |
|--------|-----------|------------------|
| 400 | Invalid workflow type / bad input | `"Workflow type 'Foo' not found in registry."` |
| 400 | UUID format invalid in retry/rewind/resume | `"Invalid workflow ID format"` |
| 404 | Workflow ID not found | `"Workflow with ID abc... not found."` |
| 409 | Saga rollback occurred | `"Saga rollback triggered by step 'charge_card': ..."` |
| 409 | Workflow in non-advanceable state | `"Workflow is in 'COMPLETED' state. Cannot advance."` |
| 422 | Step execution failure | `"Step 'validate_kyc' failed: ..."` |
| 501 | Feature requires PostgreSQL backend | `"Audit logs require PostgreSQL backend"` |
| 503 | Engine not initialized | `"Workflow Engine not initialized."` |
| 500 | Unexpected / DB error | `"Unexpected error executing step: ..."` |

### Endpoints with documented error contracts (Swagger `responses=`)

- `POST /api/v1/workflow/start` — 400, 503
- `GET /api/v1/workflow/{id}/status` — 404, 503
- `POST /api/v1/workflow/{id}/next` — 404, 409, 422, 503
- `POST /api/v1/workflow/{id}/resume` — 400, 404, 422, 503

---

## §16 — Database Schema Reference

### Schema Governance

| Layer | Tool | Target | Tables |
|-------|------|--------|--------|
| PostgreSQL — all 33 cloud tables | **Alembic** (`alembic upgrade head`) | PostgreSQL only | See inventory below |
| PostgreSQL — extensions bootstrap | `docker/init-db.sql` (init script) | PostgreSQL only | N/A — extensions only |
| Edge SQLite — core workflow (7) | `sqlite.py` `SQLITE_SCHEMA` | SQLite only | workflow_executions, workflow_audit_log, workflow_execution_logs, workflow_metrics, workflow_heartbeats, tasks, compensation_log |
| Edge SQLite — edge-specific (3) | `sqlite.py` `SQLITE_SCHEMA` (appended) | SQLite only | saf_pending_transactions, device_config_cache, edge_sync_state |

`database.py` is the **single source of truth** for all 33 PostgreSQL tables.
`sqlite.py:SQLITE_SCHEMA` is the single source of truth for the 10 edge SQLite tables.
`edge_database.py` documents the edge schema (constants + SQL strings, no Alembic).

### Complete Table Inventory

#### Core Workflow Tables (7) — shared by PostgreSQL and SQLite
| Table | Notes |
|-------|-------|
| `workflow_executions` | Main workflow state |
| `workflow_audit_log` | Event compliance log |
| `workflow_execution_logs` | Debug / structured logs |
| `workflow_metrics` | Performance metrics |
| `workflow_heartbeats` | Zombie detection |
| `tasks` | Async task queue; also used by SyncManager (SAF_Sync) and ConfigManager (CONFIG_CACHE) |
| `compensation_log` | Saga rollback history |

#### Scheduling (1) — PostgreSQL only
| Table | Notes |
|-------|-------|
| `scheduled_workflows` | Cron-based workflow triggers; referenced in `postgres.py:register_scheduled_workflow` |

#### Edge Device Management — Cloud Side (2) — PostgreSQL only
| Table | Notes |
|-------|-------|
| `edge_devices` | Device registry |
| `device_commands` | Per-device command queue; expanded with batch/broadcast/retry columns in migration a1b2c3d4e5f6 |

#### Workers (1) — PostgreSQL only
| Table | Notes |
|-------|-------|
| `worker_nodes` | Celery fleet registry; added in migration d08b401e4c86 |

#### Command Infrastructure (6) — PostgreSQL only
| Table | Notes |
|-------|-------|
| `command_broadcasts` | Fleet-wide command fans |
| `command_batches` | Atomic multi-command sequences per device |
| `command_templates` | Reusable command blueprints |
| `command_schedules` | One-time and recurring command scheduling |
| `schedule_executions` | Per-execution records for schedules |
| `command_versions` | Schema versioning per command type |
| `command_changelog` | Breaking-change history |

#### Audit & Compliance (2) — PostgreSQL only
| Table | Notes |
|-------|-------|
| `command_audit_log` | Compliance audit trail; has TSVECTOR generated column (PostgreSQL ≥ 12 only) |
| `audit_retention_policies` | PCI DSS retention rules; default: 7 years |

#### Authorization & RBAC (5) — PostgreSQL only
| Table | Notes |
|-------|-------|
| `authorization_roles` | Role definitions; seeded with admin/operator/viewer/approver |
| `role_assignments` | User↔role mapping |
| `authorization_policies` | Command-level access rules |
| `command_approvals` | Multi-party approval requests |
| `approval_responses` | Per-approver responses |

#### Webhooks & Rate Limiting (4) — PostgreSQL only
| Table | Notes |
|-------|-------|
| `webhook_registrations` | Outbound webhook subscriptions |
| `webhook_deliveries` | Per-delivery attempt records |
| `rate_limit_rules` | API rate limit configuration |
| `rate_limit_tracking` | Sliding-window counters |

#### Edge Config & SAF — Cloud Side (4) — PostgreSQL only
| Table | Notes |
|-------|-------|
| `device_configs` | Configuration versions; `etag` field enables If-None-Match push |
| `saf_transactions` | SAF transaction records synced from edge; `device_id` has no FK (device may not be registered at sync time) |
| `device_assignments` | Policy-to-device assignments |
| `policies` | Fraud rules and configuration policies |

#### Edge-Specific SQLite Tables (3) — SQLite (edge) only
| Table | Notes |
|-------|-------|
| `saf_pending_transactions` | Proper SAF outbox queue (future replacement for tasks hack) |
| `device_config_cache` | ETag-keyed config cache (future replacement for tasks hack) |
| `edge_sync_state` | Sync cursor / progress key-value store |

### Edge vs Cloud Schema (ASCII Diagram)

```
CLOUD (PostgreSQL)                    EDGE (SQLite)
══════════════════════════════════    ═══════════════════════════════════
database.py  ─►  Alembic migration   sqlite.py SQLITE_SCHEMA
33 tables                            10 tables
  ├── Core Workflow (7)                 ├── Core Workflow (7)  ◄── shared
  ├── Scheduling (1)                    └── Edge-Specific (3) ◄── new
  ├── Edge Device Mgmt (2+1 worker)
  ├── Command Infrastructure (7)
  ├── Audit & Compliance (2)
  ├── Authorization / RBAC (5)
  ├── Webhooks & Rate Limiting (4)
  └── Edge Config & SAF (4)
```

### Known Compatibility Notes

1. **tasks hack** — `SyncManager` (sync_manager.py) uses `step_name='SAF_Sync'` and `ConfigManager` uses `step_name='CONFIG_CACHE'` in the `tasks` table. The new `saf_pending_transactions` and `device_config_cache` tables exist but are not yet wired up. Future work.

2. **TSVECTOR limitation** — `command_audit_log.searchable_text` is a PostgreSQL-only GENERATED column. It is not modelable in SQLAlchemy's generic dialect and is applied via `op.execute(ALTER TABLE...)` in the migration. This column does not exist on SQLite.

3. **`command_id` vs `id`** — `device_commands` has both `id` (UUID PK) and `command_id` (human-readable VARCHAR(100), UNIQUE). The API uses `command_id` for user-facing references; internal joins use `id`.

4. **`saf_transactions.device_id`** — No FK constraint on this column. Edge devices may sync transactions before registering with the cloud. The service layer handles the lookup independently.

5. **`scheduled_workflows` SQLite** — `postgres.py:register_scheduled_workflow` has a full implementation. `sqlite.py:register_scheduled_workflow` logs a warning (not implemented). The table is PostgreSQL-only.

6. **`migrations/schema.yaml`** — Legacy file, not used by Alembic. Deprecated. Do not add new tables there.

### Running Migrations

```bash
# Fresh deployment
alembic upgrade head

# Check current version
alembic current

# Rollback one revision
alembic downgrade -1

# Generate new migration after editing database.py
alembic revision --autogenerate -m "description_of_change"
```

From Docker Compose:
```bash
docker-compose run --rm rufus-server alembic upgrade head
```
