# Celery Workflows - Quick Start

Get running in 5 minutes!

## 1. Start Infrastructure (1 minute)
```bash
cd examples/celery_workflows
docker-compose up -d
```

Starts:
- PostgreSQL on port 5432
- Redis on port 6379

## 2. Setup Database (1 minute)
```bash
# Create .env file
cp .env.example .env

# Apply migrations
cd ../../src/rufus
source ../examples/celery_workflows/.env
alembic upgrade head
cd -
```

## 3. Start Worker (30 seconds)
```bash
# Terminal 1
./start_worker.sh
```

## 4. Run Examples (30 seconds)
```bash
# Terminal 2
source .env
python run_example.py order
```

## 5. (Optional) Monitor Events
```bash
# Terminal 3
source .env
python monitor_events.py
```

---

## What You'll See

### Order Processing Example
```
==================================================================
 ORDER PROCESSING WORKFLOW
==================================================================
Demonstrates:
  - Async task execution (payment processing)
  - Sub-workflow orchestration (notifications)
  - Automatic workflow resumption
==================================================================

============================================================
[VALIDATE] Validating order ORD-12345
[VALIDATE] Customer: customer@example.com
[VALIDATE] Amount: $99.99 USD
============================================================

✅ Order validation passed

⏸️  Workflow paused - waiting for Celery worker to process async task
💡 The workflow will automatically resume when the task completes
```

**Worker logs will show**:
```
[PAYMENT] Processing payment for workflow abc123...
[PAYMENT] Amount: $99.99
[PAYMENT] Payment processed: tx_abc123_1234567890
```

**Workflow then auto-resumes**:
```
[RECEIPT] Sending receipt for transaction tx_abc123
[RECEIPT] Receipt sent to customer@example.com
```

---

## Examples Included

| Example | Command | Features |
|---------|---------|----------|
| Order Processing | `python run_example.py order` | Async tasks, sub-workflows |
| Payment Processing | `python run_example.py payment` | Parallel execution |
| All Examples | `python run_example.py` | Runs both |

---

## Troubleshooting

**Worker not starting?**
```bash
# Make script executable
chmod +x start_worker.sh

# Check Python path
echo $PYTHONPATH

# Try manual start
celery -A rufus.celery_app worker --loglevel=debug
```

**Database error?**
```bash
# Check PostgreSQL is running
docker-compose ps

# Test connection
psql postgresql://rufus:rufus_secret_2024@localhost:5432/rufus_example -c "SELECT 1"

# Re-run migrations
cd ../../src/rufus
alembic upgrade head
```

**Import errors?**
```bash
# Install dependencies
pip install -e "../../.[celery]"

# Check imports
python -c "from ruvon.celery_app import celery_app; print('OK')"
```

---

## Next Steps

1. **Modify workflows** - Edit `config/*.yaml` files
2. **Add new tasks** - Create tasks in `tasks/` directory
3. **Customize state** - Update models in `models/state_models.py`
4. **Scale workers** - Start multiple worker instances

---

**Full documentation**: See `README.md`
