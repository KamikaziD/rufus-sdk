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
initial_state_model_path: "my_app.state_models.MyWorkflowState"
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
    initial_state_model_path: "my_app.state_models.MyWorkflowState"
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
# Static task list
- name: "Parallel_Tasks"
  type: "PARALLEL"
  tasks:
    - name: "task1"
      function_path: "my_app.tasks.task1"
    - name: "task2"
      function_path: "my_app.tasks.task2"
  merge_strategy: "SHALLOW"  # or DEEP
  merge_conflict_behavior: "PREFER_NEW"  # or PREFER_EXISTING, RAISE_ERROR
  allow_partial_success: true
  timeout_seconds: 300

# Dynamic fan-out (one task per item in a state list)
- name: "Push_To_Fleet"
  type: "PARALLEL"
  iterate_over: "device_ids"       # dot-notation path to a list in state
  task_function: "steps.push_to_device"  # called once per item
  item_var_name: "device_id"       # kwarg name for each item (default: "item")
  batch_size: 50                   # optional: process 50 at a time (0 = all at once)
  merge_strategy: "SHALLOW"
  allow_partial_success: true
```

> **`batch_size`** — when set to a positive integer, the `iterate_over` list is split into sequential chunks. Supported by `SyncExecutor`/`ThreadPoolExecutor` only; ignored with a warning on `CeleryExecutionProvider`.

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
# ITERATE mode — loop body called once per item in a state list
- name: "Process_Batch"
  type: "LOOP"
  mode: "ITERATE"
  iterate_over: "user_ids"        # dot-notation path into state (e.g. "user_ids" or "order.items")
  item_var_name: "current_user_id"  # kwarg name passed to each loop_body step
  max_iterations: 100
  automate_next: true
  loop_body:
    - name: "Process_User"
      type: "STANDARD"
      function: "steps.process_user"

# WHILE mode — loop body repeats until a state field becomes False
- name: "Poll_Until_Ready"
  type: "LOOP"
  mode: "WHILE"
  while_condition: "keep_polling"  # name of a boolean state field; loop exits when False
  max_iterations: 10
  loop_body:
    - name: "Check_Status"
      type: "STANDARD"
      function: "steps.check_status"
```

**ITERATE** — body function receives the current item as a kwarg:
```python
async def process_user(state: MyState, context: StepContext, current_user_id: str = "", **_) -> dict:
    result = process_single_user(current_user_id)
    return {"processed_count": state.processed_count + 1}
```

**WHILE** — body function sets the condition field to `False` to stop the loop:
```python
async def check_status(state: MyState, context: StepContext, **_) -> dict:
    status = check_external_service()
    return {
        "keep_polling": status != "ready",
        "service_status": status,
    }
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
initial_state_model_path: "models.OrderState"

steps:
  - name: "Validate_Order"
    type: "STANDARD"
    function: "steps.validate_order"
    automate_next: true

  - name: "Reserve_Inventory"
    type: "LOOP"
    mode: "ITERATE"
    iterate_over: "order_items"
    item_var_name: "item"
    max_iterations: 50
    automate_next: true
    loop_body:
      - name: "Reserve_Item"
        type: "STANDARD"
        function: "steps.reserve_item"

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
    -- Added in migration b2c3d4e5f6a7 (v0.7.3) ──────────────────────────────
    sdk_version VARCHAR(50),             -- rufus-sdk version string from __version__
    pending_command_count INTEGER DEFAULT 0,  -- bumped on insert, decremented on execute
    last_command_at TIMESTAMPTZ,         -- when last command was queued for this worker
    -- ─────────────────────────────────────────────────────────────────────────
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE worker_commands (
    command_id VARCHAR(100) PRIMARY KEY,
    worker_id VARCHAR(100) REFERENCES worker_nodes(worker_id) ON DELETE CASCADE,
    target_filter TEXT,          -- JSON: {region, zone, ...} for broadcast targeting; NULL = all
    command_type VARCHAR(50) NOT NULL,
    command_data TEXT DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'pending',  -- pending→delivered→executing→completed|failed|cancelled
    priority VARCHAR(20) DEFAULT 'normal', -- critical | high | normal | low
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(100),
    delivered_at TIMESTAMPTZ,
    executed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    result TEXT,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 0
);

CREATE INDEX ix_worker_cmd_worker_status  ON worker_commands (worker_id, status);
CREATE INDEX ix_worker_cmd_status_created ON worker_commands (status, created_at);
CREATE INDEX ix_worker_cmd_expires        ON worker_commands (expires_at);

-- Active workers query
SELECT worker_id, hostname, region, sdk_version, pending_command_count, last_heartbeat
FROM worker_nodes
WHERE status = 'online'
  AND last_heartbeat > NOW() - INTERVAL '2 minutes';

-- Workers by region
SELECT region, COUNT(*) as worker_count
FROM worker_nodes WHERE status = 'online'
GROUP BY region;
```

### Worker Fleet Commands

Introduced in **v0.7.3**. The control plane sends commands to Celery workers via the `worker_commands`
PostgreSQL table. Workers poll on every heartbeat (default 30 s) using `SELECT ... FOR UPDATE SKIP LOCKED`
to atomically claim up to 10 pending commands per tick and execute them in daemon threads.

```
Control Plane API  ─→  INSERT worker_commands  ─→  PostgreSQL
                                                        │  (poll every 30s)
                                               Worker heartbeat loop
                                                        │
                                             _execute_command(type, data)
                                                        │
                                          ┌─────────────┴────────────┐
                                          │ SIGTERM / pool_restart   │
                                          │ pip install / celery ctl │
                                          │ UPDATE capabilities      │
                                          └──────────────────────────┘
```

**Supported command types (9):**

| `command_type` | Key `command_data` fields | Mechanism | Latency |
|----------------|--------------------------|-----------|---------|
| `check_health` | _(none)_ | Collect platform + Celery stats; write to `result` | ≤30s |
| `restart` | `delay_seconds` (default 5) | `os.kill(pid, SIGTERM)` after delay | ≤30s |
| `pool_restart` | _(none)_ | `celery_app.control.pool_restart(reload=True)` — hot module reload | ≤30s |
| `drain` | `queue`, `wait_seconds` | Cancel consumer → wait → SIGTERM | ≤30s + wait |
| `update_code` | `package`, `version`, `index_url` | `pip install package==version` then SIGTERM | ≤30s + pip |
| `update_code` | `wheel_url` | `pip install <URL>` then SIGTERM | ≤30s + pip |
| `update_config` | `capabilities: {key: value}` | Merge into in-memory capabilities + persist to DB | ≤30s |
| `pause_queue` | `queue` | `celery_app.control.cancel_consumer(queue)` | ≤30s |
| `resume_queue` | `queue` | `celery_app.control.add_consumer(queue)` | ≤30s |
| `set_concurrency` | `direction` (`grow`/`shrink`), `n` | `pool_grow` / `pool_shrink` | ≤30s |

**API endpoints (v0.7.3):**

```bash
# List workers
curl http://localhost:8000/api/v1/workers

# Get a single worker
curl http://localhost:8000/api/v1/workers/worker-hostname-001

# Send a health-check command to one worker
curl -X POST http://localhost:8000/api/v1/workers/worker-hostname-001/commands \
  -H "Content-Type: application/json" \
  -d '{"command_type": "check_health"}'

# Restart a worker after 10 s
curl -X POST http://localhost:8000/api/v1/workers/worker-hostname-001/commands \
  -d '{"command_type": "restart", "command_data": {"delay_seconds": 10}}'

# Update rufus-sdk from TestPyPI to 0.7.3
curl -X POST http://localhost:8000/api/v1/workers/worker-hostname-001/commands \
  -d '{"command_type": "update_code", "command_data": {
        "package": "rufus-sdk", "version": "0.7.3",
        "index_url": "https://test.pypi.org/simple/"}}'

# Update code from a wheel URL (air-gapped / edge)
curl -X POST http://localhost:8000/api/v1/workers/worker-hostname-001/commands \
  -d '{"command_type": "update_code", "command_data": {
        "wheel_url": "https://cdn.example.com/rufus_sdk-0.7.3-py3-none-any.whl"}}'

# Broadcast restart to all workers in region "us-east"
curl -X POST http://localhost:8000/api/v1/workers/broadcast \
  -d '{"command_type": "restart", "target_filter": {"region": "us-east"},
       "command_data": {"delay_seconds": 5}}'

# List commands for a worker
curl "http://localhost:8000/api/v1/workers/worker-hostname-001/commands?status=pending"

# Cancel a pending command
curl -X DELETE http://localhost:8000/api/v1/workers/commands/<command_id>
```

**Limitations:**

- **≤30 s latency** — commands are delivered on the next heartbeat tick; there is no instant push channel.
- **No zero-downtime updates** — `update_code` + restart causes a brief worker gap; Celery re-queues
  in-flight tasks via the broker.
- **Broadcast targeting** — the `target_filter` is evaluated client-side in the worker (region, zone,
  capabilities keys); there is no server-side pre-filtering before insert.
- **PEX as future path** — packaging workflows as PEX archives would allow atomic, zero-downtime code
  swaps without pip and are planned as a post-beta enhancement.

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

### Direct `Workflow()` Instantiation in Tests

`Workflow.__init__` requires **all 6 providers** — it raises `ValueError` if any is `None`:
`persistence_provider`, `execution_provider`, `workflow_observer`, `workflow_builder`, `expression_evaluator_cls`, `template_engine_cls`.

The recommended approach is `WorkflowBuilder.create_workflow()` which handles wiring. For tests that need direct `Workflow` access:

```python
from unittest.mock import MagicMock
from rufus.workflow import Workflow
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

wf = Workflow(
    workflow_id="test-wf",
    workflow_steps=[step],
    initial_state_model=MyState(),
    workflow_type="MyType",
    persistence_provider=InMemoryPersistence(),
    execution_provider=SyncExecutor(),
    workflow_observer=observer,            # MagicMock() if not under test
    workflow_builder=MagicMock(),          # MagicMock() is fine for most tests
    expression_evaluator_cls=SimpleExpressionEvaluator,
    template_engine_cls=Jinja2TemplateEngine,
)
```

### SAFTransaction Required Fields

When writing test data that exercises the `SyncManager._get_pending_transactions()` path, the `task_data` stored in the tasks table **must** contain a `"transaction"` key with all required `SAFTransaction` fields:

```python
task_data = {
    "transaction": {
        "transaction_id": "txn-001",
        "idempotency_key": "key-001",
        "device_id": "device-001",       # required
        "merchant_id": "merch-001",      # required
        "amount": "9.99",                # required (Decimal-compatible string)
        "currency": "USD",               # optional, defaults to "USD"
        "card_token": "tok_test",        # required
        "card_last_four": "4242",        # required
    }
}
```

Malformed transactions are silently skipped (logged as WARNING), so tests that assert on pending transaction counts will silently get 0 if required fields are missing.

### `get_edge_sync_state` Return Value

`get_edge_sync_state(key: str) -> Optional[str]` returns a **plain string** (or `None`), not a `SyncStateRecord`. Access the result directly:

```python
stored = await persistence.get_edge_sync_state("api_key")
if stored:
    api_key = stored  # already a str, no .value attribute
```

### FastAPI Import Guard in Test Files

The dev venv has a `pydantic`/`fastapi` version mismatch (`annotated_types.Not` AttributeError). Any test file that imports FastAPI at module level must be guarded:

```python
try:
    from fastapi.testclient import TestClient
    from rufus_server.main import app
    _FASTAPI_AVAILABLE = True
except Exception:
    TestClient = None
    app = None
    _FASTAPI_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _FASTAPI_AVAILABLE,
    reason="FastAPI/server dependencies not available in this environment",
)
```

### `AsyncWorkflowStep` Hierarchy

`AsyncWorkflowStep` **inherits** from `WorkflowStep` — `isinstance(step, WorkflowStep)` is `True` for it. Whether a step uses sync timing in `workflow.py` is determined by:

```python
is_sync_step = not isinstance(step, (
    AsyncWorkflowStep, HttpWorkflowStep, ParallelWorkflowStep,
    FireAndForgetWorkflowStep, LoopStep, CronScheduleWorkflowStep, WasmWorkflowStep
))
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
initial_state_model_path: "my_app.models.OrderState"
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
| PostgreSQL — all 35 cloud tables | **Alembic** (`alembic upgrade head`) | PostgreSQL only | See inventory below |
| PostgreSQL — extensions bootstrap | `docker/init-db.sql` (init script) | PostgreSQL only | N/A — extensions only |
| Edge SQLite — core workflow (7) | `sqlite.py` `SQLITE_SCHEMA` | SQLite only | workflow_executions, workflow_audit_log, workflow_execution_logs, workflow_metrics, workflow_heartbeats, tasks, compensation_log |
| Edge SQLite — edge-specific (3) | `sqlite.py` `SQLITE_SCHEMA` (appended) | SQLite only | saf_pending_transactions, device_config_cache, edge_sync_state |

`database.py` is the **single source of truth** for all 35 PostgreSQL tables.
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

#### Workers (4) — PostgreSQL only
| Table | Notes |
|-------|-------|
| `worker_nodes` | Celery fleet registry; added in migration `d08b401e4c86`; 3 new columns (`sdk_version`, `pending_command_count`, `last_command_at`) added in migration `b2c3d4e5f6a7` (v0.7.3) |
| `worker_commands` | DB-delivery channel for control-plane → worker commands; 9 command types; poll-based (30 s); added in migration `b2c3d4e5f6a7` (v0.7.3) |
| `workflow_definitions` | Versioned YAML for hot-reload via `WorkflowBuilder.reload_workflow_type()`; DB row overrides disk YAML; added in migration `c1d2e3f4a5b6` (v0.7.4) |
| `server_commands` | Control-plane command queue (reload_workflows, gc_caches, update_code, restart); polled every 30 s by `_definition_poller_loop`; added in migration `c1d2e3f4a5b6` (v0.7.4) |

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

---

## §17 — Live Workflow Updates (v0.7.4)

Hot-deploy workflow YAML definitions to running servers and edge devices without restarting containers.

### Architecture Overview

```
Dashboard Admin "Server" tab
        │  POST /api/v1/admin/workflow-definitions
        ▼
workflow_definitions table (PostgreSQL)
        │
        │  _definition_poller_loop() — 60 s tick
        ▼
WorkflowBuilder.reload_workflow_type(type, yaml_content)
  ├── evicts _workflow_config_cache[type]
  ├── evicts _import_cache entries for this type
  └── inserts registry[type]["_yaml_content"] = yaml_content

  On next create_workflow(type):
    ├── get_workflow_config() detects _yaml_content key
    └── parses YAML from DB row (not disk file)
```

### `workflow_definitions` Table

```sql
CREATE TABLE IF NOT EXISTS workflow_definitions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_type   VARCHAR(255) NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    yaml_content    TEXT NOT NULL,
    description     TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_by      VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(workflow_type, version)
);
CREATE INDEX IF NOT EXISTS ix_workflow_definitions_type
    ON workflow_definitions(workflow_type);
CREATE INDEX IF NOT EXISTS ix_workflow_definitions_active
    ON workflow_definitions(workflow_type, is_active);
```

**Loading priority:** DB row (if `is_active=true`) → disk YAML file fallback. Startup pre-loads all active DB definitions before serving the first request.

### `WorkflowBuilder.reload_workflow_type()` (builder.py)

```python
def reload_workflow_type(self, workflow_type: str, yaml_content: str) -> dict:
    """Hot-reload a workflow definition from YAML string (called by server poller)."""
    # 1. Evict cached config + import cache for this type
    self._workflow_config_cache.pop(workflow_type, None)
    for key in list(self._import_cache.keys()):
        if key.startswith(workflow_type):
            del self._import_cache[key]
    # 2. Inject the raw YAML into the registry
    import yaml
    config = yaml.safe_load(yaml_content)
    config["_yaml_content"] = yaml_content   # marker: tells get_workflow_config to use this
    self._workflow_registry[workflow_type] = config
    return config
```

In `get_workflow_config()`, the `_yaml_content` branch is checked first:
```python
if "_yaml_content" in registry_entry:
    return yaml.safe_load(registry_entry["_yaml_content"])
```

### `_definition_poller_loop()` (main.py)

Background asyncio task started at server startup, cancelled on shutdown:

```python
async def _definition_poller_loop(app: FastAPI) -> None:
    tick = 0
    while True:
        await asyncio.sleep(30)
        tick += 1
        # Every tick (30 s): process pending server commands
        await _process_server_commands(app)
        # Every 2 ticks (60 s): reload active workflow definitions
        if tick % 2 == 0:
            await _reload_workflow_definitions(app)
```

### `server_commands` Table

```sql
CREATE TABLE IF NOT EXISTS server_commands (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    command      VARCHAR(100) NOT NULL,
    payload      JSONB,
    status       VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    executed_at  TIMESTAMPTZ,
    result       JSONB
);
CREATE INDEX IF NOT EXISTS ix_server_commands_status
    ON server_commands(status, created_at);
```

#### Server Command Types

| Command | Mechanism |
|---------|-----------|
| `reload_workflows` | Triggers immediate `_reload_workflow_definitions()` call (skips 60 s wait) |
| `gc_caches` | Calls `builder.clear_all_caches()` — evicts `_workflow_config_cache` + `_import_cache` |
| `update_code` | Runs `pip install --upgrade rufus-sdk` in a subprocess, then triggers reload |
| `restart` | Calls `os.kill(os.getpid(), signal.SIGUSR1)` — graceful uvicorn reload |

### API Endpoints

#### Workflow Definitions (`/api/v1/admin/workflow-definitions`)

```bash
# List all definitions
curl http://localhost:8000/api/v1/admin/workflow-definitions

# Get single definition (latest active)
curl http://localhost:8000/api/v1/admin/workflow-definitions/PaymentAuthorization

# Upload / replace definition
curl -X POST http://localhost:8000/api/v1/admin/workflow-definitions \
  -H "Content-Type: application/json" \
  -d '{"workflow_type":"PaymentAuthorization","yaml_content":"workflow_type: PaymentAuthorization\n..."}'

# Update (patch yaml or description)
curl -X PATCH http://localhost:8000/api/v1/admin/workflow-definitions/PaymentAuthorization \
  -H "Content-Type: application/json" \
  -d '{"yaml_content":"..."}'

# Push definition to all edge devices via broadcast
curl -X POST \
  "http://localhost:8000/api/v1/admin/workflow-definitions/PaymentAuthorization/push-to-devices"

# Delete definition (soft-delete: sets is_active=false)
curl -X DELETE \
  http://localhost:8000/api/v1/admin/workflow-definitions/PaymentAuthorization
```

#### Server Commands (`/api/v1/admin/server/commands`)

```bash
# Dispatch a server command
curl -X POST http://localhost:8000/api/v1/admin/server/commands \
  -H "Content-Type: application/json" \
  -d '{"command":"reload_workflows","payload":{}}'

# List recent commands
curl "http://localhost:8000/api/v1/admin/server/commands?limit=10"

# Cancel a pending command
curl -X DELETE http://localhost:8000/api/v1/admin/server/commands/<id>
```

### Dashboard DAG Editor

The **Admin → Server** tab provides a full workflow definition management UI:

- **Definitions panel**: list table with type, version, active status; Upload modal (YAML paste); Edit modal with:
  - Live ReactFlow DAG preview (dagre TB layout; custom colours per step type; DECISION dashed edges with condition labels)
  - Raw YAML editor textarea
  - DECISION inline editor: structured `{lhs, op, rhs}` form with regex parser + raw textarea fallback
  - Push to Devices confirmation dialog (broadcasts `update_workflow` command to all online devices)
- **Server Commands panel**: list table of recent commands + status; Send Command modal (all 4 types); Cancel button

### Edge Agent Handler (config_manager.py)

When the control plane broadcasts `update_workflow`, the edge agent processes it via:

```python
async def handle_update_workflow_command(
    self,
    payload: dict,          # {"workflow_type": str, "yaml_content": str}
    workflow_builder,       # WorkflowBuilder instance
) -> None:
    # 1. Persist to local SQLite (survives restarts)
    await self._persist_workflow_definition(
        payload["workflow_type"], payload["yaml_content"]
    )
    # 2. Hot-reload into builder
    workflow_builder.reload_workflow_type(
        payload["workflow_type"], payload["yaml_content"]
    )
```

On startup, `load_local_workflow_definitions(workflow_builder)` reads all persisted definitions from the `tasks` table (under `step_name='EDGE_CONFIG'`) and pre-loads them into the builder before the agent accepts traffic.

---

## §18 — Edge Device Package Footprint

Full reference: [`docs/reference/configuration/edge-footprint.md`](../docs/reference/configuration/edge-footprint.md)

### Wheel composition (v0.5.4, 9.3 MB)

| Component | Size | Files | Edge-relevant |
|-----------|------|-------|---------------|
| `rufus/` core SDK | 1.9 MB | 57 | Partially (see below) |
| `rufus_edge/` agent | 232 KB | 8 | Yes |
| `rufus_cli/` CLI | 520 KB | 12 | No |
| `rufus_server/` cloud API | 10 MB | 42 | No |

### What is included vs excluded from the wheel

**Included:**

- All of `rufus/implementations/` — sqlite, postgres, sync, celery, thread_pool, onnx, tflite, etc. (716 KB)
- `rufus_edge/payment_steps.py` — reference implementation, ships with the package
- `rufus_cli/` and `rufus_server/` — shipped but never imported by edge agents

**Excluded** (via `pyproject.toml exclude`):

- `src/rufus/examples/`
- `config/*.yaml` (project root — user-supplied, not in any package)
- `tests/` (dev-only)
- **User-written step functions** — always external to the package; add to footprint based on user imports

### Installed footprint by scenario

```text
Scenario A: pip install rufus-sdk
  Disk: ~25–30 MB  |  RSS: ~50 MB
  Use: offline payment, SAF, SQLite, config polling

Scenario B: pip install 'rufus-sdk[edge]'
  Disk: ~40–45 MB  |  RSS: ~65 MB
  Adds: websockets, psutil, numpy (+14 MB)
  Use: everything above + WebSocket commands, health metrics

Scenario C: pip install 'rufus-sdk[edge]' && pip install onnxruntime
  Disk: ~100–600 MB  |  RSS: ~115–165 MB
  Adds: onnxruntime (+60 MB) + model files (10–500 MB)
  Use: on-device ML fraud scoring, anomaly detection

Scenario D: pip install 'rufus-sdk[edge]' && pip install tflite-runtime
  Disk: ~60–250 MB  |  RSS: ~85–115 MB
  Adds: tflite-runtime (+10 MB) + model files
  Use: TFLite inference (lighter than ONNX on some hardware)
```

### Core modules loaded by edge agents at runtime

```python
rufus.workflow, rufus.builder, rufus.models
rufus.providers.*  (7 interface files)
rufus.implementations.persistence.sqlite
rufus.implementations.execution.sync
rufus.implementations.observability.logging
rufus.implementations.templating.jinja2
rufus.implementations.expression_evaluator.simple
rufus.implementations.security.crypto_utils
rufus.implementations.inference.*  (only if AI enabled)
```

Modules on disk but never imported on edge: `celery_app`, `tasks`, `worker_registry`, `zombie_scanner`, `heartbeat`, `engine` (legacy), celery/postgres/redis implementations, `rufus_cli.*`, `rufus_server.*`

### Hardware minimums

| Scenario | Min RAM | Min Storage | Python |
|----------|---------|-------------|--------|
| Minimal | 128 MB | 64 MB | 3.9+ |
| `[edge]` extras | 128 MB | 100 MB | 3.9+ |
| ONNX inference | 256 MB | 200 MB+ | 3.9+ |
| TFLite | 256 MB | 100–300 MB | 3.9+ |

---

## §19 — Package Split (v0.6.0)

Three separate wheels replace the monolithic `rufus-sdk`:

| Package | Contents | PyPI install |
|---------|----------|--------------|
| `rufus-sdk` | `rufus/` core + `rufus_cli/` | `pip install rufus-sdk` |
| `rufus-sdk-edge` | `rufus_edge/` | `pip install rufus-sdk-edge` |
| `rufus-sdk-server` | `rufus_server/` | `pip install rufus-sdk-server` |

Sub-packages declare `rufus-sdk >= 0.6.0` as a required dependency.

### pyproject.toml locations

- Root: `/pyproject.toml` — `rufus-sdk` (core + CLI)
- Edge: `/packages/rufus-sdk-edge/pyproject.toml` — `rufus-sdk-edge`
- Server: `/packages/rufus-sdk-server/pyproject.toml` — `rufus-sdk-server`

Sub-packages reference source via `from = "../../src"` — no file moves required.

### Extras after split

| Extra | Package | Packages added |
|-------|---------|---------------|
| `[postgres]` | `rufus-sdk` | asyncpg |
| `[performance]` | `rufus-sdk` | uvloop |
| `[cli]` | `rufus-sdk` | rich |
| `[edge]` | `rufus-sdk-edge` | websockets, psutil, numpy |
| `[server]` | `rufus-sdk-server` | fastapi, uvicorn, starlette, slowapi |
| `[celery]` | `rufus-sdk-server` | celery, redis, psycopg2-binary, prometheus-client |
| `[auth]` | `rufus-sdk-server` | python-jose |

### Dev install (all from source)

```bash
pip install -e ".[postgres,performance,cli]"
pip install -e "packages/rufus-sdk-edge[edge]"
pip install -e "packages/rufus-sdk-server[server,celery,auth]"
```

### Build

```bash
# Core
poetry build
# Edge
cd packages/rufus-sdk-edge && poetry build
# Server
cd packages/rufus-sdk-server && poetry build
```

### Wheel size after split

| Wheel | Size |
|-------|------|
| `rufus_sdk-0.6.0-py3-none-any.whl` | ~2.5 MB |
| `rufus_sdk_edge-0.6.0-py3-none-any.whl` | ~250 KB |
| `rufus_sdk_server-0.6.0-py3-none-any.whl` | ~10 MB |

Edge devices installing `rufus-sdk-edge` save ~10.5 MB vs the old monolithic wheel.

---

## §15 WASM Execution Environment

### Overview

`WASM` is a workflow step type that executes pre-compiled WebAssembly binaries in a WASI sandbox. It enables polyglot step logic — write performance-critical code in Rust, C, or Go, compile to WASM once, run everywhere (cloud server, edge POS terminal, ATM).

**Dependency:** `pip install wasmtime` (imported lazily — only required if a workflow uses WASM steps).

**Optional extra:** `pip install 'rufus-sdk[wasm]'`

---

### WASM Module Contract

Every WASM module used as a workflow step must follow this contract:

| Requirement | Detail |
|-------------|--------|
| Read input from **stdin** | JSON object (full state or mapped subset via `state_mapping`) |
| Write result to **stdout** | JSON object — keys are merged into workflow state |
| Exit code **0** | Success |
| Exit code **non-zero** | Failure — `fallback_on_error` policy applied |
| No filesystem access | WASI sandbox — no host file access by default |
| No network access | Modules cannot make outbound connections |

---

### State Model

```python
# my_app/state_models.py
from pydantic import BaseModel
from typing import Optional

class PaymentState(BaseModel):
    transaction_amount: float
    card_bin: str
    card_country: str
    merchant_category: str
    risk_score: Optional[float] = None
    risk_label: Optional[str] = None
    approved: Optional[bool] = None
```

---

### Writing a WASM Module (Rust)

```rust
// src/main.rs
use std::io::{self, Read};
use serde::{Deserialize, Serialize};
use serde_json;

#[derive(Deserialize)]
struct Input {
    amount: f64,
    country: String,
    mcc: String,
}

#[derive(Serialize)]
struct Output {
    risk_score: f64,
    risk_label: String,
}

fn main() {
    let mut buf = String::new();
    io::stdin().read_to_string(&mut buf).unwrap();
    let input: Input = serde_json::from_str(&buf).expect("Invalid JSON on stdin");

    // Pure computation — no I/O, no side effects
    let mut score = 0.1_f64;
    if input.amount > 10_000.0 { score += 0.4; }
    if input.country == "HIGHRISK" { score += 0.3; }
    if input.mcc == "7995" { score += 0.2; }  // gambling MCC
    score = score.min(1.0);

    let label = if score > 0.7 { "HIGH" } else if score > 0.4 { "MEDIUM" } else { "LOW" };

    let out = Output { risk_score: score, risk_label: label.into() };
    print!("{}", serde_json::to_string(&out).unwrap());
}
```

```toml
# Cargo.toml
[dependencies]
serde = { version = "1", features = ["derive"] }
serde_json = "1"
```

```bash
# Build to WASI target
rustup target add wasm32-wasi
cargo build --target wasm32-wasi --release
# Output: target/wasm32-wasi/release/risk_scorer.wasm

# Compute hash for YAML wasm_hash field
sha256sum target/wasm32-wasi/release/risk_scorer.wasm
```

---

### Workflow YAML

```yaml
workflow_type: "PaymentAuthorization"
workflow_version: "2.0.0"
initial_state_model: "my_app.state_models.PaymentState"

steps:
  - name: "Validate_Input"
    type: "STANDARD"
    function: "my_app.steps.validate_payment_input"
    automate_next: true

  - name: "Score_Risk"
    type: "WASM"
    wasm_config:
      wasm_hash: "a3f5c2d1e4b6f890..."   # sha256 of risk_scorer.wasm
      entrypoint: "execute"
      state_mapping:
        transaction_amount: "amount"
        card_country: "country"
        merchant_category: "mcc"
      timeout_ms: 2000
      fallback_on_error: "default"
      default_result:
        risk_score: 0.5
        risk_label: "UNKNOWN"
    automate_next: true

  - name: "Authorize_Payment"
    type: "DECISION"
    function: "my_app.steps.authorize_payment"
    routes:
      - condition: "state.risk_score < 0.7"
        target: "Capture_Payment"
      - condition: "state.risk_score >= 0.7"
        target: "Decline_Payment"

  - name: "Capture_Payment"
    type: "ASYNC"
    function: "my_app.tasks.capture_payment"

  - name: "Decline_Payment"
    type: "STANDARD"
    function: "my_app.steps.decline_payment"
```

---

### Python — Wiring Up WasmRuntime

```python
from rufus.implementations.execution.wasm_runtime import WasmRuntime, DiskWasmBinaryResolver
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
from rufus.builder import WorkflowBuilder

# Cloud setup: DiskWasmBinaryResolver queries wasm_components table and reads disk
persistence = PostgresPersistenceProvider(db_url=DATABASE_URL)
await persistence.initialize()

wasm_resolver = DiskWasmBinaryResolver(db_pool=persistence.pool)
wasm_runtime = WasmRuntime(resolver=wasm_resolver)

# Pass wasm_runtime= when creating any workflow that contains WASM steps
workflow = await builder.create_workflow(
    workflow_type="PaymentAuthorization",
    initial_data={
        "transaction_amount": 4500.0,
        "card_bin": "424242",
        "card_country": "US",
        "merchant_category": "5411",
    },
    persistence_provider=persistence,
    execution_provider=SyncExecutor(),
    workflow_builder=builder,
    expression_evaluator_cls=SimpleExpressionEvaluator,
    template_engine_cls=Jinja2TemplateEngine,
    workflow_observer=LoggingObserver(),
    wasm_runtime=wasm_runtime,  # ← inject here; None by default
)

await workflow.next_step()
# State after Score_Risk step:
# {"risk_score": 0.1, "risk_label": "LOW", ...}
```

---

### Edge Device Setup

```python
from rufus.implementations.execution.wasm_runtime import WasmRuntime, SqliteWasmBinaryResolver
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider

# Edge persistence wraps an aiosqlite connection
persistence = SQLitePersistenceProvider(db_path="/data/edge_device.db")
await persistence.initialize()

# SqliteWasmBinaryResolver reads binary_data BLOB from device_wasm_cache
wasm_resolver = SqliteWasmBinaryResolver(conn=persistence.conn)
wasm_runtime = WasmRuntime(resolver=wasm_resolver)

# Inject into workflow as above — identical API, different resolver
```

---

### Uploading a Binary (Cloud API)

```bash
# Upload via admin API
curl -X POST https://control-plane.example.com/api/v1/admin/wasm-components \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -F "file=@risk_scorer.wasm" \
  -F "name=risk_scorer" \
  -F "version_tag=v1.0.0"

# Response
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "binary_hash": "a3f5c2d1e4b6f890...",
  "name": "risk_scorer",
  "version_tag": "v1.0.0",
  "size_bytes": 1458234,
  "created_at": "2026-03-10T12:00:00"
}

# List all registered binaries
curl https://control-plane.example.com/api/v1/wasm-components \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Download a binary (used automatically by edge sync)
curl https://control-plane.example.com/api/v1/wasm-components/a3f5c2d1.../download \
  -o risk_scorer.wasm
```

---

### Pushing WASM to Edge Fleet

```python
# Broadcast sync_wasm to all POS devices in the fleet
await broadcast_service.create_broadcast(
    command_type="sync_wasm",
    command_data={"binary_hash": "a3f5c2d1e4b6f890..."},
    target_filter={"device_type": "POS"},
)
```

Each edge device that receives the command will:
1. Check `device_wasm_cache` — skip if already cached (idempotent)
2. `GET /api/v1/wasm-components/{hash}/download`
3. Verify SHA-256 of response
4. `INSERT OR REPLACE INTO device_wasm_cache (binary_hash, binary_data, last_accessed)`

On device startup, `load_local_workflow_definitions()` also scans cached YAML for `type: WASM` steps and prefetches any missing binaries as background tasks.

---

### Testing WASM Steps

```python
# tests/sdk/test_wasm_step.py
import pytest
import hashlib
from rufus.implementations.execution.wasm_runtime import WasmRuntime
from rufus.models import WasmConfig

class MockBinaryResolver:
    def __init__(self, binary: bytes):
        self._binary = binary

    async def resolve(self, binary_hash: str) -> bytes:
        return self._binary


class FailResolver:
    async def resolve(self, binary_hash: str) -> bytes:
        raise FileNotFoundError("binary not found")


@pytest.mark.asyncio
async def test_wasm_fallback_skip():
    runtime = WasmRuntime(resolver=FailResolver())
    config = WasmConfig(wasm_hash="a" * 64, fallback_on_error="skip")
    result = await runtime.execute(config, {"amount": 100})
    assert result == {}


@pytest.mark.asyncio
async def test_wasm_fallback_default():
    runtime = WasmRuntime(resolver=FailResolver())
    config = WasmConfig(
        wasm_hash="a" * 64,
        fallback_on_error="default",
        default_result={"risk_score": 0.5},
    )
    result = await runtime.execute(config, {"amount": 100})
    assert result == {"risk_score": 0.5}


# Full integration test requires a real .wasm binary — see tests/fixtures/echo.wasm
@pytest.mark.asyncio
async def test_wasm_real_execution():
    with open("tests/fixtures/echo.wasm", "rb") as f:
        wasm_bytes = f.read()
    binary_hash = hashlib.sha256(wasm_bytes).hexdigest()

    config = WasmConfig(
        wasm_hash=binary_hash,
        entrypoint="execute",
        state_mapping={"transaction_amount": "amount"},
    )
    runtime = WasmRuntime(resolver=MockBinaryResolver(wasm_bytes))
    result = await runtime.execute(config, {"transaction_amount": 500.0, "other": "ignored"})
    assert "amount" in result
```

---

### Error Handling Matrix

| Condition | `"fail"` | `"skip"` | `"default"` |
|-----------|----------|----------|-------------|
| Binary not found | `FAILED` | `{}` | `default_result` |
| Hash mismatch | `FAILED` | `{}` | `default_result` |
| WASM runtime error | `FAILED` | `{}` | `default_result` |
| Timeout exceeded | `FAILED` | `{}` | `default_result` |
| Invalid JSON output | `FAILED` | `{}` | `default_result` |
| Non-object JSON output | `FAILED` | `{}` | `default_result` |

---

### Security Notes

- **WASI sandbox:** The module cannot access the host filesystem, network, or environment variables. Only stdin/stdout are available.
- **Integrity check:** SHA-256 is recomputed and compared at every execution. A tampered file is detected immediately.
- **Provenance:** Only binaries uploaded via the admin API (admin auth required) are registered. Edge devices download via device-level auth and verify the hash independently.
- **Memory:** wasmtime defaults apply (~4 GB addressable space). Keep edge binaries < 5 MB to stay within practical SQLite BLOB limits.

---

## §20 — Browser + WASI 0.3 Deployment (v0.8.0)

`rufus-sdk-edge` can now run in three environments without code changes:

| Environment | HTTP transport | SQLite | Metrics | Install extra |
|-------------|---------------|--------|---------|---------------|
| Native CPython | `httpx` | `aiosqlite` | `psutil` | `[edge]` |
| Browser (Pyodide + JSPI) | `js.fetch` | `wa-sqlite` | stub | `[browser]` |
| WASI 0.3 compiled | `wasi:http` | `aiosqlite` + `wasi:filesystem` | stub | `[wasi]` |

### Platform Adapter

All HTTP and metrics access is routed through `PlatformAdapter` (Protocol in `rufus_edge.platform.base`):

```python
from rufus_edge.platform import detect_platform  # auto-selects correct adapter

adapter = detect_platform()   # NativePlatformAdapter on CPython
                               # PyodidePlatformAdapter inside Pyodide
                               # WasiPlatformAdapter on wasm32

# Pass to agent for full portability
agent = RufusEdgeAgent(
    device_id="pos-001",
    cloud_url="https://control.example.com",
    platform_adapter=adapter,
)
```

Detection order: `sys.platform == 'wasm32'` → WASI; `js` importable → Pyodide; else → Native.

### Component Model WASM Steps (v0.8.0)

WASM steps now use `ComponentStepRuntime` by default. It auto-detects the binary type:

| Binary type | Detection | Execution |
|-------------|-----------|-----------|
| Component Model (WASI 0.3) | magic bytes `\x00asm\x0e\x00` | `wasmtime.component` — typed `execute(state, step_name) → result` |
| Legacy core module | magic bytes `\x00asm\x01\x00` | stdin/stdout JSON (unchanged) |

**WIT interface** (`src/rufus/wasm_component/step.wit`):
```wit
package rufus:step@0.1.0;

interface runner {
    execute: func(state-json: string, step-name: string) -> result<string, step-error>;
}

world rufus-step { export runner; }
```

**Wiring via WorkflowBuilder** (cloud or edge):
```python
from rufus.implementations.execution.wasm_runtime import SqliteWasmBinaryResolver

resolver = SqliteWasmBinaryResolver(conn)   # or DiskWasmBinaryResolver(pool)

workflow = await builder.create_workflow(
    "PaymentAuthorization",
    ...,
    wasm_binary_resolver=resolver,   # auto-creates ComponentStepRuntime
)
```

Legacy `WasmRuntime` is **not removed** — it now delegates CM binaries to `ComponentStepRuntime` automatically.

### Browser Target (Pyodide + JSPI)

**Requirements:** Chrome 126+ (JSPI on by default) or Chrome 117+ with `--enable-features=WebAssemblyJSPI`.

**Bootstrap** (`src/rufus_edge/browser_loader.js`):
```js
const worker = new Worker("/browser_loader.js", { type: "module" });
worker.postMessage({
    type: "start",
    deviceId: "browser-pos-001",
    cloudUrl: "https://control.example.com",
    apiKey: "your-key",
    wheelUrl: "https://your-cdn/rufus_sdk_edge-latest-py3-none-any.whl",
});

worker.onmessage = ({ data }) => {
    if (data.type === "ready") {
        // agent is running
        worker.postMessage({ type: "execute", workflowType: "PaymentAuthorization", inputData: {} });
    }
};
```

**SQLite in the browser:** `PyodideSQLiteProvider` wraps [wa-sqlite](https://github.com/rhashimoto/wa-sqlite) (WebAssembly SQLite, data persisted in OPFS). The host page must load wa-sqlite before Pyodide starts — `browser_loader.js` handles this automatically.

**Install:**
```bash
pip install 'rufus-sdk-edge[browser]'   # no psutil, no websockets, no httpx
```

**Constraints:**
- No `subprocess`, no raw sockets, no `/proc` filesystem
- Fetch is subject to CORS policy of the host origin
- `psutil` metrics unavailable — `SystemMetrics` returns zeros
- `asyncio` works via JSPI; all `await` points map to browser microtasks

### WASI 0.3 Native Target

**Build:**
```bash
pip install py2wasm
bash scripts/build_wasi.sh          # → dist/rufus_edge.wasm

# Optional: wrap as Component Model binary (requires wasm-tools)
wasm-tools component new dist/rufus_edge.wasm \
    --adapt wasi_snapshot_preview1.reactor.wasm \
    -o dist/rufus_edge_component.wasm
```

**Run:**
```bash
wasmtime \
  --env RUFUS_DEVICE_ID=wasi-001 \
  --env RUFUS_CLOUD_URL=https://control.example.com \
  --env RUFUS_API_KEY=your-key \
  dist/rufus_edge.wasm
```

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `RUFUS_DEVICE_ID` | `wasi-device` | Unique device identifier |
| `RUFUS_CLOUD_URL` | `""` | Cloud control plane URL |
| `RUFUS_API_KEY` | `""` | API key for authentication |
| `RUFUS_DB_PATH` | `rufus_edge.db` | SQLite database path (via `wasi:filesystem`) |
| `RUFUS_SYNC_INTERVAL` | `30` | Seconds between SAF sync attempts |
| `RUFUS_LOG_LEVEL` | `INFO` | Python logging level |

**HTTP:** routed through `wasi:http/outgoing-handler` — the host (wasmtime) must be started with `--wasi http` capability grant.

**Install:**
```bash
pip install 'rufus-sdk-edge[wasi]'    # zero extra deps
pip install 'rufus-sdk-edge[native-wasm]'  # adds wasmtime for CM on native Python
```

---

## §21 Paged Inference Runtime

Running a 2B-parameter generative LLM on a memory-constrained browser or edge device requires keeping only a **rolling window of model shards** resident in memory. This section documents the shard-paged architecture in Rufus SDK.

### Why Shard Paging?

| Platform | WASM limit | Naive model footprint | With paging |
|---|---|---|---|
| Chrome/Edge desktop | ~4 GB | ~1.2 GB (ok) | ~360 MB (3 × 120 MB window) |
| **Safari/iOS** | **~300 MB** | **1.2 GB → OOM** | **~260 MB (2 shards)** |
| Edge device 512 MB RAM | N/A (native) | 1.2 GB → OOM | ~200 MB (llama.cpp mmap) |
| Edge device 256 MB RAM | N/A (native) | OOM | ~140 MB (shard-0 fast path) |

True layer-by-layer WASM streaming does not exist yet. The pragmatic approach implemented here is **shard-level paging** (file chunks via wllama's split-GGUF support) combined with an OPFS shard cache and a JS-side prefetch controller.

### GGUF Shard Preparation

Split a GGUF model into 120 MB shards using llama.cpp:

```bash
# Install llama.cpp tools
pip install llama-cpp-python   # or build from source

# Split BitNet 2B model into 120 MB shards
llama-gguf-split --split-max-size 120M bitnet-b1.58-2B-3T-Q4_K_M.gguf shard
# Produces: shard-00001-of-00010.gguf, shard-00002-of-00010.gguf, …

# Serve shards locally with CORS headers (required — plain http.server lacks CORS)
# Save as cors_server.py and run from the directory containing your shards:
# python cors_server.py
#
# from http.server import HTTPServer, SimpleHTTPRequestHandler
# class CORSHandler(SimpleHTTPRequestHandler):
#     def end_headers(self):
#         self.send_header("Access-Control-Allow-Origin", "*")
#         super().end_headers()
# HTTPServer(("", 9090), CORSHandler).serve_forever()
```

Set `shard_urls` in `AIInferenceConfig` to point to the shard files:
```yaml
- name: PagedReasoning
  type: AI_INFERENCE
  ai_config:
    model_name: bitnet-2b
    input_source: state.prompt
    runtime: custom
    paging_strategy: shard
    max_resident_shards: 2
    prefetch_shards: 1
    shard_size_mb: 120
    logic_gate_threshold: 0.4
    max_tokens: 128
    shard_urls:
      - https://cdn.example.com/bitnet/shard-00001-of-00010.gguf
      - https://cdn.example.com/bitnet/shard-00002-of-00010.gguf
      # … remaining shards
```

### AIInferenceConfig Paging Fields

| Field | Default | Description |
|---|---|---|
| `paging_strategy` | `"none"` | `"none"` (disabled) · `"shard"` (shard-level) · `"layer"` (future) |
| `max_resident_shards` | `2` | Max shards in WASM at once (≥1). 2 = ~260 MB on Safari. |
| `prefetch_shards` | `1` | Shards to load ahead of the active window (hidden by I/O overlap). |
| `shard_urls` | `None` | Explicit CDN URLs for browser paging. |
| `shard_size_mb` | `120` | Target split size in MB (used when splitting locally). |
| `logic_gate_threshold` | `0.0` | Complexity below this → fast path (shard-0 only). 0.0 = disabled. |
| `max_tokens` | `None` | Generation cap. |

### Provider Selection

**Browser (Pyodide):** Use `PagedBrowserInferenceProvider` — delegates to `globalThis.runPagedInference` (JS FFI). The JS controller manages OPFS caching and shard scheduling.

**Native edge:** Use `LlamaCppPagedProvider` — wraps `llama-cli --mmap`. The OS pages layers automatically; no custom scheduler needed.

`WorkflowBuilder.create_workflow()` auto-selects the right provider when `paged_inference_provider=` is not supplied:

```python
# Auto-selection (platform-aware)
wf = await builder.create_workflow("PagedReasoning", ...)

# Explicit override
from rufus.implementations.inference.paged_browser import PagedBrowserInferenceProvider
wf = await builder.create_workflow("PagedReasoning", ...,
                                   paged_inference_provider=PagedBrowserInferenceProvider())
```

### Logic-Gate Fast Path

60–70% of field tech queries (error code lookups, yes/no diagnostics, simple symptom queries) are **simple** and can be resolved from shard-0 alone.

The `logic_gate_threshold` controls the cutoff:
- `complexity_score < threshold` → load only shard-0 (~120 MB, ~1.5s latency)
- `complexity_score ≥ threshold` → load all shards (full inference, ~9s Safari)

Tune the threshold based on your query distribution. The built-in heuristic classifier (token count + keyword matching) is a starting point; swap in a DistilBERT classifier for production.

### Known Limitations

- **No true layer streaming:** WASM heap is flat; shard boundaries are at the file level, not the transformer layer level.
- **Safari 2-shard hard limit:** ~260 MB peak (2 × 120 MB + runtime overhead). Avoid `max_resident_shards > 2` on Safari/iOS.
- **OPFS availability:** Requires a secure context (HTTPS or localhost) and a modern browser. Falls back to re-fetching shards on every run if OPFS is unavailable.
- **wllama dependency:** Browser path requires `wllama` NPM package. Placeholder shard URLs in the demo produce simulated output only; swap for real split-GGUF files.
- **CORS required for shard fetches:** Shards must be served with `Access-Control-Allow-Origin: *`. Plain `python -m http.server` does not set this header; use a CORS-enabled server (see GGUF Shard Preparation above).
- **Model selector (Q2_K / Q3_K_S):** Browser demo Card 6 includes a pill selector for quantisation level. `Q2_K` (~180 MB peak, faster) and `Q3_K_S` (~260 MB peak, higher quality). Both use placeholder URLs by default; update `MODEL_CONFIGS` in `worker.js` with your real CDN paths. Switching models evicts the wllama instance; OPFS-cached shards are preserved.
- **LlamaCppPagedProvider:** Requires `llama-cli` binary on PATH. Windows mmap support is limited; recommend Linux/macOS for native edge deployment.

---

## §22 — Edge Device Cloud HITL Round-Trips (v1.0.0rc5)

### Overview

An edge device can escalate a HITL decision to the cloud, receive an analyst decision, and resume execution — even after briefly going offline. The pattern uses:

1. **SAF queue** to deliver the escalation event to the cloud
2. **Cloud HITL workflow** (e.g. `FraudCaseReview`) that pauses for analyst review
3. **`resume_fraud_review` command** (CRITICAL priority) delivered back to the device via WebSocket or heartbeat poll
4. **`register_command_handler()`** on the edge agent to receive the command and resume the local workflow

### `register_command_handler()` API

```python
def register_command_handler(self, command_type: str, handler: Callable[[dict], Awaitable[None]]) -> None:
    """Register an async handler for a cloud command type.

    Args:
        command_type: The command type string (matches device_commands.command_type in DB).
        handler: Async callable receiving command_data dict.
    """
```

**Usage:**

```python
agent = RufusEdgeAgent(
    device_id="atm-001",
    cloud_url="https://control.example.com",
    db_path="/var/lib/rufus/edge.db",
    encryption_key=os.getenv("RUFUS_ENCRYPTION_KEY"),
)

async def handle_fraud_review_decision(command_data: dict):
    workflow_id = command_data["workflow_id"]
    decision = command_data["decision"]          # "approved" | "rejected"
    notes = command_data.get("notes", "")

    workflow = await agent.workflow_builder.load_workflow(workflow_id)
    await workflow.next_step(user_input={
        "decision": decision,
        "notes": notes,
        "source": "cloud_analyst",
    })

agent.register_command_handler("resume_fraud_review", handle_fraud_review_decision)
await agent.start()
```

### Full Round-Trip Sequence

```
Edge ATM (offline-capable)                 Cloud Control Plane
─────────────────────────────              ──────────────────────────────
1. Execute FraudDetection workflow
2. WASM scorer returns HIGH risk
3. Escalate:
   - SAF-queue EncryptedTransaction ──►    4. SAF sync received
   - SAF metadata: risk_score, typologies  5. FraudCaseReview workflow created
                                           6. Dashboard Approvals panel shows case
                                           7. Analyst reviews FraudReviewPanel
                                           8. Analyst clicks Approve / Reject
                                           9. POST /devices/{id}/commands
                                              {type: "resume_fraud_review",
                                               priority: "CRITICAL",
                                               data: {workflow_id, decision, notes}}
10. Agent polls heartbeat / WS        ◄─── command in response
11. register_command_handler fires
12. Local workflow resumed
13. Continue: dispense / retain card
```

### Timeout Fallback

If the cloud decision does not arrive within a configured timeout (e.g. 90 seconds), fall back to on-device handling:

```python
async def await_cloud_decision(state: FraudState, context: StepContext, **user_input) -> dict:
    # On first entry: set deadline in state and pause
    if not state.cloud_escalation_deadline:
        import time
        state.cloud_escalation_deadline = time.time() + 90
        raise WorkflowPauseDirective()

    # On resume (command received): process decision
    if user_input.get("source") == "cloud_analyst":
        return {"decision": user_input["decision"], "decided_by": "analyst"}

    # Deadline exceeded: fall back to manager PIN path
    import time
    if time.time() > state.cloud_escalation_deadline:
        raise WorkflowJumpDirective("Manager_PIN_Override")

    raise WorkflowPauseDirective()  # still waiting
```

### Priority Levels

Cloud commands support a `priority` field consumed by the edge agent's command queue:

| Priority | Delivery | Use case |
|----------|----------|----------|
| `CRITICAL` | Next heartbeat / immediate WS push | Fraud HITL decision, emergency stop |
| `HIGH` | Within 2 heartbeat cycles | Config update, workflow deploy |
| `NORMAL` | Best-effort | Telemetry requests, log flush |
