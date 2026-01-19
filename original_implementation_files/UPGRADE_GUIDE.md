# Confucius Workflow Engine - Upgrade Guide

## Overview

This upgrade transforms Confucius into a production-ready "Planetary Nervous System" with enterprise-grade features:

- ✅ **PostgreSQL Persistence** - ACID-compliant, durable workflow state
- ✅ **Saga Pattern** - Automatic rollback with compensation functions
- ✅ **Sub-Workflows** - Hierarchical workflow composition
- ✅ **Audit Logging** - Compliance-ready event trails
- ✅ **Performance Metrics** - Built-in observability
- ✅ **Idempotency Keys** - Protection against duplicate execution
- ✅ **Regional Data Sovereignty** - Data locality support

## What's New

### 1. PostgreSQL Backend (Phase 1)

**Why**: Redis is great for development but lacks ACID guarantees and audit trails needed for production.

**Migration**:
```bash
# Install dependencies
pip install -r requirements.txt

# Set up PostgreSQL
docker run -d --name postgres \
  -e POSTGRES_DB=confucius \
  -e POSTGRES_USER=confucius \
  -e POSTGRES_PASSWORD=yourpassword \
  -p 5432:5432 \
  postgres:15

# Initialize schema
export DATABASE_URL="postgresql://confucius:yourpassword@localhost:5432/confucius"
python scripts/init_database.py

# Switch to PostgreSQL
export WORKFLOW_STORAGE=postgres
```

**Features**:
- SERIALIZABLE isolation for consistency
- Real-time updates via LISTEN/NOTIFY
- Audit logs for compliance
- Performance metrics
- Sub-millisecond task claiming with `FOR UPDATE SKIP LOCKED`

### 2. Saga Pattern (Phase 2)

**Why**: Distributed transactions need rollback capability. When a workflow fails after charging a credit card, you need to automatically refund it.

**Usage**:

**Step 1**: Define compensation functions in `workflow_utils.py`:
```python
def debit_account(state: PaymentState, amount: float, **kwargs):
    """Forward action: Debit the account"""
    transaction_id = payment_api.debit(state.account_id, amount)
    state.transaction_id = transaction_id
    return {"transaction_id": transaction_id}

def compensate_debit(state: PaymentState, **kwargs):
    """Compensation: Refund the debit"""
    if state.transaction_id:
        payment_api.refund(state.transaction_id)
    return {"refunded": state.transaction_id}
```

**Step 2**: Link them in YAML:
```yaml
- name: "Debit_Customer_Account"
  type: "STANDARD"
  function: "workflow_utils.debit_account"
  compensate_function: "workflow_utils.compensate_debit"  # NEW!
  required_input: ["amount"]
```

**Step 3**: Enable saga mode (auto-enabled for Payment, BankTransfer, OrderProcessing, LoanApplication):
```python
from confucius.workflow_loader import workflow_builder

workflow = workflow_builder.create_workflow("MyWorkflow", initial_data={})
workflow.enable_saga_mode()
```

**What happens on failure**:
1. Workflow executes steps: Reserve Inventory → Charge Card → Ship Order
2. Shipping fails at step 3
3. Engine automatically compensates in reverse: Refund Card → Release Inventory
4. Workflow status = `FAILED_ROLLED_BACK`

### 3. Sub-Workflows (Phase 3)

**Why**: Complex processes should be composable. A loan application might trigger a KYC sub-workflow.

**Usage**:

**Step 1**: Create parent workflow `config/loan_workflow.yaml`:
```yaml
steps:
  - name: "Collect_Application"
    type: "STANDARD"
    function: "workflow_utils.collect_application"

  - name: "Run_KYC"
    type: "STANDARD"
    function: "workflow_utils.trigger_kyc"  # This will launch child workflow
```

**Step 2**: Define KYC as separate workflow `config/kyc_workflow.yaml`:
```yaml
workflow_type: "KYC"
steps:
  - name: "Verify_ID"
    type: "ASYNC"
    function: "workflow_utils.verify_id"

  - name: "Check_Sanctions"
    type: "ASYNC"
    function: "workflow_utils.check_sanctions"
```

**Step 3**: Launch sub-workflow in parent:
```python
from confucius.workflow import StartSubWorkflowDirective

def trigger_kyc(state: LoanState, **kwargs):
    """Launch KYC as sub-workflow"""
    raise StartSubWorkflowDirective(
        workflow_type="KYC",
        initial_data={
            "user_id": state.user_id,
            "document_url": state.document_url
        }
    )

def process_kyc_results(state: LoanState, **kwargs):
    """Runs after KYC completes"""
    kyc_results = state.sub_workflow_results.get("KYC", {})

    if kyc_results.get("approved"):
        return {"message": "KYC passed, continuing loan application"}
    else:
        raise WorkflowPauseDirective(result={"message": "KYC requires manual review"})
```

**Execution flow**:
1. Parent reaches `Run_KYC` step
2. Parent status → `PENDING_SUB_WORKFLOW`
3. Child KYC workflow executes to completion
4. Child results merged into `parent.state.sub_workflow_results["KYC"]`
5. Parent resumes at next step

## Configuration Changes

### Environment Variables

Create `.env` file (see `.env.example`):
```bash
# Required
WORKFLOW_STORAGE=postgres  # or 'redis' for development
DATABASE_URL=postgresql://user:pass@localhost:5432/confucius

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Optional
ENV=production
LOG_LEVEL=INFO
```

### YAML Enhancements

**Compensatable steps**:
```yaml
- name: "Reserve_Inventory"
  type: "STANDARD"
  function: "workflow_utils.reserve_inventory"
  compensate_function: "workflow_utils.release_inventory"  # NEW!
```

**Sub-workflows**: No YAML changes needed - triggered programmatically via `StartSubWorkflowDirective`

## Breaking Changes

### None! 🎉

This upgrade is **100% backward compatible**:
- Redis backend still works (default)
- Existing workflows run unchanged
- Saga mode is opt-in
- Sub-workflows are opt-in

## Migration Checklist

### Development Environment

- [ ] Install new dependencies: `pip install -r requirements.txt`
- [ ] Start PostgreSQL: `docker run -d ... postgres:15`
- [ ] Initialize schema: `python scripts/init_database.py`
- [ ] Update `.env`: `WORKFLOW_STORAGE=postgres`
- [ ] Test existing workflows with Redis first
- [ ] Switch to PostgreSQL and test again

### Production Deployment

- [ ] Provision PostgreSQL database (AWS RDS, GCP Cloud SQL, etc.)
- [ ] Apply migration: `psql $DATABASE_URL < migrations/001_init_postgresql_schema.sql`
- [ ] Update environment variables
- [ ] Deploy with both Redis and PostgreSQL running
- [ ] Gradually migrate workflows (Redis → PostgreSQL)
- [ ] Monitor metrics and logs
- [ ] Decommission Redis once stable

## Testing

### Test Saga Rollback

```python
# tests/test_saga.py
from confucius.workflow_loader import workflow_builder

def test_saga_rollback():
    workflow = workflow_builder.create_workflow("OrderProcessing", {})
    workflow.enable_saga_mode()

    # Execute steps that will fail
    workflow.next_step({"order_id": "123"})  # Reserve inventory
    workflow.next_step({})  # Charge card

    try:
        workflow.next_step({})  # Ship order - this fails
    except SagaWorkflowException:
        pass

    # Verify rollback occurred
    assert workflow.status == "FAILED_ROLLED_BACK"
    assert workflow.state.payment_refunded == True
    assert workflow.state.inventory_released == True
```

### Test Sub-Workflows

```python
def test_sub_workflow():
    parent = workflow_builder.create_workflow("LoanApplication", {
        "user_id": "U123"
    })

    # Advance to KYC step
    result, next_step = parent.next_step({})

    # Parent should be waiting for child
    assert parent.status == "PENDING_SUB_WORKFLOW"
    assert parent.blocked_on_child_id is not None

    # Child workflow executes automatically via Celery
    # When child completes, parent resumes
```

## Performance Considerations

### PostgreSQL vs Redis

| Metric | Redis | PostgreSQL |
|--------|-------|------------|
| **Latency** | 1-2ms | 3-5ms |
| **Throughput** | 100k ops/sec | 10k ops/sec |
| **Durability** | Periodic snapshots | ACID transactions |
| **Audit Trail** | None | Full history |
| **Queries** | Key-value only | SQL analytics |

**Recommendation**: Use Redis for development, PostgreSQL for production.

### Scaling

**Horizontal scaling**:
- Add more Celery workers for task execution
- PostgreSQL connection pooling (5-20 connections per worker)
- Use read replicas for metrics queries

**Vertical scaling**:
- PostgreSQL: 4-8 CPU cores, 16-32GB RAM
- Celery workers: 2-4 CPU cores each

## Troubleshooting

### "workflow_executions table not found"

```bash
# Run migration
psql $DATABASE_URL < migrations/001_init_postgresql_schema.sql

# Or use init script
python scripts/init_database.py
```

### "Saga rollback not triggering"

```python
# Enable saga mode explicitly
workflow.enable_saga_mode()

# Or set in environment for auto-enable
SAGA_ENABLED_WORKFLOWS=MyWorkflow,AnotherWorkflow
```

### "Sub-workflow not resuming parent"

Check Celery worker logs:
```bash
celery -A celery_setup worker --loglevel=debug
```

Look for:
- `[SUB-WORKFLOW] Child {id} completed successfully`
- `[SUB-WORKFLOW] Resuming parent {id}`

If missing, child workflow may have failed or paused.

### "Database connection pool exhausted"

Increase pool size in `persistence_postgres.py`:
```python
self.pool = await asyncpg.create_pool(
    self.db_url,
    min_size=10,   # Increase from 5
    max_size=50,   # Increase from 20
)
```

## Advanced Features

### Custom Merge Functions (Parallel Steps)

```yaml
- name: "Multi_Bureau_Credit_Check"
  type: "PARALLEL"
  tasks:
    - name: "Equifax"
      function: "workflow_utils.check_equifax"
    - name: "Experian"
      function: "workflow_utils.check_experian"
  merge_function_path: "workflow_utils.average_credit_scores"  # Custom merge
```

```python
def average_credit_scores(results: list) -> dict:
    scores = [r['score'] for r in results if 'score' in r]
    return {"average_score": sum(scores) // len(scores)}
```

### Regional Data Sovereignty

```python
# Force workflow to execute in specific region
workflow.data_region = "eu-central-1"

# Sub-workflows inherit parent's region
raise StartSubWorkflowDirective(
    workflow_type="DataProcessing",
    initial_data={...},
    data_region="eu-central-1"  # Or override
)
```

### Idempotency Keys

```python
# Prevent duplicate workflow starts
workflow.idempotency_key = f"order-{order_id}-{timestamp}"
```

PostgreSQL will reject duplicate keys, ensuring exactly-once semantics.

## Next Steps

1. **Read the upgraded CLAUDE.md** for architecture details
2. **Run `python scripts/init_database.py`** to set up PostgreSQL
3. **Test with existing workflows** using Redis first
4. **Switch to PostgreSQL** and test again
5. **Add compensation functions** to critical workflows
6. **Experiment with sub-workflows** for complex processes
7. **Monitor metrics** via PostgreSQL `workflow_metrics` table

## Support

- GitHub Issues: https://github.com/your-org/confucius/issues
- Documentation: See `docs/` folder
- Database Schema: `migrations/001_init_postgresql_schema.sql`
- Examples: `config/*.yaml` workflow definitions

---

**Welcome to the Planetary Nervous System! 🚀**
