# Celery Workflows Example Application

Complete example demonstrating Ruvon's Celery-based distributed execution with:
- ✅ Async task execution
- ✅ Parallel task execution
- ✅ Sub-workflow orchestration
- ✅ HTTP steps (polyglot)
- ✅ Event monitoring
- ✅ Worker fleet management

## Quick Start

**1. Start infrastructure:**
```bash
docker-compose up -d
```

**2. Install dependencies:**
```bash
pip install -e "../../.[celery]"
```

**3. Apply database migrations:**
```bash
cd ../../src/ruvon
export DATABASE_URL="postgresql://ruvon:ruvon_secret_2024@localhost:5432/ruvon_example"
alembic upgrade head
cd -
```

**4. Start Celery worker:**
```bash
# Terminal 1
./start_worker.sh
```

**5. Run example workflows:**
```bash
# Terminal 2
python run_example.py
```

**6. Monitor events (optional):**
```bash
# Terminal 3
python monitor_events.py
```

---

## What's Included

### Order Processing Workflow
Demonstrates **async execution** with automatic workflow resumption:
```
┌─────────────────┐
│ Validate Order  │ (sync)
└────────┬────────┘
         │
┌────────▼────────┐
│ Process Payment │ (async - Celery task)
└────────┬────────┘
         │
┌────────▼────────┐
│ Send Receipt    │ (async - Celery task)
└─────────────────┘
```

### Payment Workflow
Demonstrates **parallel execution** with result merging:
```
                  ┌──────────────┐
                  │ Validate Card│
                  └──────┬───────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
┌───────▼────┐   ┌───────▼────┐   ┌──────▼─────┐
│Credit Check│   │Fraud Check │   │Limit Check │
│  (parallel)│   │ (parallel) │   │ (parallel) │
└───────┬────┘   └───────┬────┘   └──────┬─────┘
        │                │                │
        └────────────────┼────────────────┘
                         │
                  ┌──────▼───────┐
                  │Charge Payment│
                  └──────────────┘
```

### Notification Workflow (Sub-workflow)
Demonstrates **sub-workflow orchestration**:
```
Parent: Order Processing
           │
           │ StartSubWorkflowDirective
           ▼
Child: Send Notification
  ├── Email Notification (async)
  ├── SMS Notification (async)
  └── Push Notification (async)
           │
           │ Results merged to parent
           ▼
Parent: Mark Order Complete
```

---

## Workflows

### 1. Order Processing (Main Workflow)
**File**: `config/order_processing.yaml`

**Features**:
- Async task execution
- Automatic workflow resumption
- Sub-workflow delegation
- State management

**Run**:
```bash
python run_example.py order
```

**Expected Output**:
```
✅ Order validated
🔄 Processing payment (async)...
⏳ Workflow paused - waiting for Celery worker
✅ Payment processed: tx_abc123
🔄 Sending receipt (async)...
✅ Receipt sent
✅ Order completed
```

### 2. Payment Workflow
**File**: `config/payment_workflow.yaml`

**Features**:
- Parallel task execution
- Result merging
- Conflict resolution
- Partial success handling

**Run**:
```bash
python run_example.py payment
```

**Expected Output**:
```
✅ Card validated
🔄 Running parallel checks (3 tasks)...
  ├── Credit check: APPROVED (750 score)
  ├── Fraud check: LOW RISK (0.05)
  └── Limit check: APPROVED ($10,000 available)
✅ All checks passed
🔄 Charging payment...
✅ Payment charged: $100.00
```

### 3. Notification Workflow (Sub-workflow)
**File**: `config/notification_workflow.yaml`

**Features**:
- Sub-workflow execution
- Parallel notifications
- Result bubbling to parent

**Run**:
```bash
python run_example.py notification
```

**Expected Output**:
```
🔔 Starting notification workflow
🔄 Sending notifications (parallel)...
  ├── Email sent to user@example.com
  ├── SMS sent to +1234567890
  └── Push notification sent
✅ All notifications sent
```

---

## Project Structure

```
examples/celery_workflows/
├── README.md                   # This file
├── docker-compose.yml          # PostgreSQL + Redis
├── requirements.txt            # Python dependencies
├── .env.example               # Environment template
├── start_worker.sh            # Worker startup script
├── run_example.py             # Main example runner
├── monitor_events.py          # Real-time event monitor
│
├── config/                    # Workflow definitions
│   ├── workflow_registry.yaml
│   ├── order_processing.yaml
│   ├── payment_workflow.yaml
│   └── notification_workflow.yaml
│
├── models/                    # State models
│   └── state_models.py
│
└── tasks/                     # Celery tasks
    ├── __init__.py
    ├── payment_tasks.py       # Payment processing
    ├── notification_tasks.py  # Notifications
    └── validation_tasks.py    # Validation checks
```

---

## Configuration

### Environment Variables
```bash
# Database
DATABASE_URL=postgresql://ruvon:ruvon_secret_2024@localhost:5432/ruvon_example

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Worker (optional)
WORKER_ID=example-worker-01
WORKER_REGION=us-east-1
WORKER_ZONE=us-east-1a
```

### Docker Services
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379
- **Worker**: Celery worker with 4 concurrent tasks

---

## Code Examples

### Defining an Async Task
```python
# tasks/payment_tasks.py
from ruvon.celery_app import celery_app

@celery_app.task
def process_payment_task(state: dict, workflow_id: str):
    """Long-running payment processing."""
    import time
    time.sleep(3)  # Simulate API call

    return {
        "transaction_id": f"tx_{workflow_id[:8]}",
        "status": "approved",
        "amount_charged": state.get("amount", 0)
    }
```

### Using in Workflow YAML
```yaml
steps:
  - name: "Process_Payment"
    type: "ASYNC"
    function: "tasks.payment_tasks.process_payment_task"
    automate_next: true  # Auto-resume when task completes
```

### Parallel Execution
```yaml
steps:
  - name: "Run_Checks"
    type: "PARALLEL"
    tasks:
      - name: "credit_check"
        function_path: "tasks.validation_tasks.check_credit"
      - name: "fraud_check"
        function_path: "tasks.validation_tasks.check_fraud"
    merge_strategy: "SHALLOW"
    allow_partial_success: false
```

### Sub-Workflow
```python
# In step function
from ruvon.models import StartSubWorkflowDirective

def trigger_notifications(state: OrderState, context: StepContext):
    raise StartSubWorkflowDirective(
        workflow_type="SendNotifications",
        initial_data={
            "user_email": state.customer_email,
            "order_id": state.order_id
        }
    )
```

---

## Monitoring

### View Worker Status
```bash
celery -A ruvon.celery_app inspect active
celery -A ruvon.celery_app inspect stats
```

### Monitor Redis Events
```bash
# Real-time event stream
python monitor_events.py

# Or manually
redis-cli XREAD COUNT 10 STREAMS workflow:persistence 0
```

### Query Worker Registry
```bash
psql $DATABASE_URL -c "
  SELECT worker_id, hostname, region, status, last_heartbeat
  FROM worker_nodes
  WHERE status = 'online'
  ORDER BY last_heartbeat DESC;
"
```

### View Workflow History
```python
from ruvon.implementations.persistence.postgres import PostgresPersistenceProvider

persistence = PostgresPersistenceProvider(db_url)
await persistence.initialize()

workflows = await persistence.list_workflows(
    status="COMPLETED",
    limit=10
)
```

---

## Cleanup

```bash
# Stop all services
docker-compose down -v

# Or keep data
docker-compose down
```

---

## Troubleshooting

### Worker not starting
```bash
# Check logs
celery -A ruvon.celery_app worker --loglevel=debug

# Verify imports
python -c "from ruvon.celery_app import celery_app; print(celery_app)"
```

### Workflows stuck
```bash
# Check active tasks
celery -A ruvon.celery_app inspect active

# Check Redis
redis-cli PING

# Check database
psql $DATABASE_URL -c "SELECT COUNT(*) FROM workflow_executions WHERE status = 'PENDING_ASYNC';"
```

### Database connection errors
```bash
# Test connection
psql $DATABASE_URL -c "SELECT 1"

# Reset database
docker-compose down -v
docker-compose up -d
cd ../../src/ruvon && alembic upgrade head
```

---

## Advanced Usage

### Custom Merge Strategy
```python
def custom_merge(results: list) -> dict:
    """Custom merge logic for parallel task results."""
    merged = {}
    for result in results:
        if result.get("priority", 0) > merged.get("priority", 0):
            merged.update(result)
    return merged
```

### Regional Workers
```bash
# Start US worker
export WORKER_REGION=us-east-1
celery -A ruvon.celery_app worker -Q us-east-1,default

# Start EU worker
export WORKER_REGION=eu-central-1
celery -A ruvon.celery_app worker -Q eu-central-1,default
```

### Task Retry Configuration
```python
@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60
)
def risky_task(self, state: dict, workflow_id: str):
    try:
        # Risky operation
        return {"result": "success"}
    except Exception as exc:
        raise self.retry(exc=exc)
```

---

## Next Steps

1. **Modify workflows** - Edit YAML files to customize behavior
2. **Add new tasks** - Create tasks in `tasks/` directory
3. **Scale workers** - Start multiple workers for higher throughput
4. **Production deployment** - Use Docker Compose or Kubernetes

---

**For more examples, see**: `../../CELERY_IMPLEMENTATION_SUMMARY.md`
