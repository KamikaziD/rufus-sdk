# Troubleshooting guide

This guide covers common issues and solutions when working with Rufus.

## Installation issues

### Import error: "No module named 'rufus'"

**Problem:** Python can't find the Rufus module.

**Solution:** Install in editable mode:

```bash
cd /path/to/rufus-sdk
pip install -e .
```

**Verify:**

```bash
python -c "from rufus.builder import WorkflowBuilder; print('✅ Rufus installed')"
```

### Missing dependencies

**Problem:** Import errors for `aiosqlite`, `asyncpg`, etc.

**Solution:** Install all dependencies:

```bash
pip install aiosqlite orjson asyncpg uvloop
```

Or install from requirements:

```bash
pip install -r requirements.txt
```

### Module not found: "examples.quickstart.steps"

**Problem:** Python can't find example modules when running examples.

**Solution:** Run from project root with PYTHONPATH:

```bash
cd /path/to/rufus-sdk
PYTHONPATH=$PWD:$PYTHONPATH python examples/quickstart/run_quickstart.py
```

## Database issues

### PostgreSQL: "database schema missing"

**Problem:** Tables don't exist in database.

**Solution:** Apply Alembic migrations:

```bash
cd src/rufus
export DATABASE_URL="postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud"
alembic upgrade head
```

**Verify:**

```bash
alembic current
# Should show current migration version
```

### SQLite: "no such table"

**Problem:** SQLite schema not initialized.

**Solution:** Initialize schema via CLI:

```bash
rufus config set-persistence
# Choose: SQLite
# Database path: workflow.db

rufus db init
```

Or initialize programmatically:

```python
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider

persistence = SQLitePersistenceProvider(db_path="workflow.db")
await persistence.initialize()
```

### PostgreSQL connection refused

**Problem:** Can't connect to PostgreSQL.

**Solution:** Check Docker container is running:

```bash
cd docker
docker compose up postgres -d

# Verify
docker compose ps
# Expected: postgres (healthy)

# Check logs
docker compose logs postgres
```

**Test connection:**

```bash
psql "postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud"
```

### Database lock errors (SQLite)

**Problem:** "database is locked" error.

**Solution:** Increase timeout:

```python
persistence = SQLitePersistenceProvider(
    db_path="workflow.db",
    timeout=30.0  # Wait up to 30 seconds
)
```

Or switch to PostgreSQL for high concurrency.

## Workflow execution issues

### Workflow stuck in RUNNING state

**Problem:** Workflow never completes or fails.

**Solution 1:** Check for missing `automate_next`:

```yaml
steps:
  - name: "Step1"
    type: "STANDARD"
    function: "my_app.steps.step1"
    automate_next: true  # Add this
```

**Solution 2:** Check for unhandled exceptions in step function:

```python
def my_step(state, context):
    try:
        # Your logic
        return {"result": "success"}
    except Exception as e:
        # Log error
        print(f"Step failed: {e}")
        # Re-raise to fail workflow
        raise
```

**Solution 3:** Check zombie workflow scanner for crashed workers:

```bash
rufus scan-zombies --db $DATABASE_URL --fix
```

### Step function not found

**Problem:** `ImportError: No module named 'my_app.steps'`

**Solution:** Verify function path in YAML matches actual module:

```yaml
# Ensure this path is correct
function: "my_app.steps.process_order"
```

**Verify module exists:**

```bash
python -c "from my_app.steps import process_order; print('✅ Found')"
```

### State not persisting

**Problem:** State changes lost between steps.

**Solution 1:** Modify state object directly:

```python
def my_step(state: MyState, context: StepContext) -> dict:
    # ✅ Correct - modifies state
    state.status = "processed"

    # ✅ Also correct - return dict merges into state
    return {"status": "processed"}
```

**Solution 2:** Ensure state is JSON-serializable:

```python
from pydantic import BaseModel
from datetime import datetime

class MyState(BaseModel):
    # ❌ Won't serialize
    created_at: datetime

    # ✅ Will serialize
    created_at: str  # Use ISO format string
```

## Celery issues

### Celery worker not starting

**Problem:** Worker crashes or won't start.

**Solution:** Check environment variables:

```bash
export DATABASE_URL="postgresql://..."
export CELERY_BROKER_URL="redis://localhost:6379/0"
export CELERY_RESULT_BACKEND="redis://localhost:6379/0"

celery -A rufus.celery_app worker --loglevel=debug
```

**Check Redis connection:**

```bash
redis-cli -h localhost -p 6379 ping
# Expected: PONG
```

### Tasks not executing

**Problem:** Tasks queued but not executing.

**Solution:** Check worker is running:

```bash
celery -A rufus.celery_app inspect active
```

**Check queue status:**

```bash
celery -A rufus.celery_app inspect stats
```

**Verify worker sees tasks:**

```bash
celery -A rufus.celery_app worker --loglevel=debug
# Watch for task received messages
```

### Workflow stuck in PENDING_SUB_WORKFLOW or PENDING_ASYNC with silent workers

**Problem:** Workflow never completes a parallel or sub-workflow step; workers appear idle; no errors logged.

**Cause:** `data_region` is set on a `StartSubWorkflowDirective` or step, routing tasks to a named queue (e.g. `onsite-london`) that no worker is consuming.

**Diagnose:**

```bash
# Check Redis for unexpected queue names
docker exec <redis-container> redis-cli keys "*"
# Look for queue names other than "default", "high_priority", "low_priority"

# Check queue depths
docker exec <redis-container> redis-cli llen onsite-london
# Non-zero = tasks stuck there
```

**Solution:** Either remove `data_region` (routes to `default`) or start a worker listening to that queue:

```bash
celery -A rufus.celery_app worker -Q onsite-london
```

Flush the orphaned queue before retrying:

```bash
docker exec <redis-container> redis-cli del onsite-london
```

### Parallel task function raises TypeError before queuing

**Problem:** Celery raises `TypeError: missing required argument: 'context'` when dispatching a PARALLEL step, before any task executes.

**Cause:** Parallel task functions passed to Celery must use a plain signature matching `func.s(state=..., workflow_id=...)`. Celery calls `check_arguments` eagerly when building chord signatures — if `context` is a required positional parameter, it fails immediately.

**Wrong:**

```python
async def my_parallel_task(state, context: StepContext, *args, **kwargs):
    ...
```

**Correct:**

```python
def my_parallel_task(state: dict, workflow_id: str):
    ...
```

**Verification:** Worker logs show "task received" and "task succeeded"; no `TypeError` before queuing.

## Performance issues

### Slow workflow execution

**Problem:** Workflows taking too long to complete.

**Solution 1:** Enable performance optimizations:

```bash
export RUFUS_USE_UVLOOP=true
export RUFUS_USE_ORJSON=true
```

**Solution 2:** Increase PostgreSQL connection pool:

```bash
export POSTGRES_POOL_MIN_SIZE=20
export POSTGRES_POOL_MAX_SIZE=100
```

**Solution 3:** Use thread pool or Celery for parallel execution:

```python
from rufus.implementations.execution.thread_pool import ThreadPoolExecutionProvider

execution = ThreadPoolExecutionProvider(max_workers=20)
```

### High memory usage

**Problem:** Application consuming too much memory.

**Solution 1:** Reduce connection pool size:

```bash
export POSTGRES_POOL_MAX_SIZE=50
```

**Solution 2:** Limit workflow state size:

- Store large data externally (S3, file system)
- Only store references in state
- Clean up completed workflows

**Solution 3:** Restart workers periodically:

```bash
# Celery: Restart worker after N tasks
celery -A rufus.celery_app worker --max-tasks-per-child=1000
```

### Database connection pool exhausted

**Problem:** "pool exhausted" errors.

**Solution:** Increase pool size:

```python
persistence = PostgresPersistenceProvider(
    db_url=db_url,
    pool_max_size=200  # Increase from default 50
)
```

Or reduce concurrent workflows.

## Configuration issues

### Config file not found

**Problem:** Workflow YAML not loading.

**Solution:** Check `config_dir` path:

```python
builder = WorkflowBuilder(
    config_dir="config/",  # Relative to working directory
    # Or use absolute path
    config_dir="/absolute/path/to/config/",
    ...
)
```

**Verify files exist:**

```bash
ls config/
# Should show workflow YAML files and workflow_registry.yaml
```

### Environment variables not loaded

**Problem:** `DATABASE_URL` not being used.

**Solution:** Export before running:

```bash
export DATABASE_URL="postgresql://..."
python app.py
```

Or load from `.env` file:

```python
from dotenv import load_dotenv
load_dotenv()

# Now environment variables available
import os
db_url = os.getenv("DATABASE_URL")
```

## Testing issues

### Tests failing with "database locked"

**Problem:** SQLite concurrent access in tests.

**Solution:** Use in-memory database:

```python
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider

@pytest.fixture
async def persistence():
    provider = SQLitePersistenceProvider(db_path=":memory:")
    await provider.initialize()
    yield provider
    await provider.close()
```

### Celery tests hanging

**Problem:** Integration tests with Celery never complete.

**Solution:** Use synchronous executor for tests:

```python
from rufus.implementations.execution.sync import SyncExecutionProvider

# In tests, use sync executor
execution = SyncExecutionProvider()
```

Or set test mode for Celery:

```bash
export TESTING=true
# Parallel tasks run synchronously in test mode
```

## Deployment issues

### Template variables not rendering in FIRE_AND_FORGET steps

**Problem:** Template like `{{ state.recipient }}` renders as empty string or raises `UndefinedError`.

**Cause:** The Jinja2 template context is the workflow state as a flat dict (`state.model_dump()`), not wrapped under a `state` key. There is no `state.` prefix available inside templates.

**Wrong:**

```yaml
message_template: "Hello {{ state.recipient }}, your amount is {{ state.amount }}"
```

**Correct:**

```yaml
message_template: "Hello {{ recipient }}, your amount is {{ amount }}"
```

### Docker image runs wrong version after version bump

**Problem:** Docker image is tagged `0.5.x` but `python -c "import rufus; print(rufus.__version__)"` inside the container prints the previous version.

**Cause:** Docker reused the cached `pip install rufus-sdk==<old>` layer because the Dockerfile was not updated before building.

**Solution:** (1) Update the version pin in all three Dockerfiles as part of the version bump step. (2) Always build with `--no-cache` after a version bump:

```bash
docker build --no-cache -f docker/Dockerfile.rufus-server-prod -t ruhfuskdev/rufus-server:0.5.x .
```

**Verify:**

```bash
docker run --rm ruhfuskdev/rufus-server:0.5.x python -c "import rufus; print(rufus.__version__)"
# Must print the new version
```

### Docker container fails to start

**Problem:** Container exits immediately.

**Solution:** Check logs:

```bash
docker logs rufus-server
```

**Common issues:**

1. Missing database migrations:

   ```bash
   # Add to docker-entrypoint.sh
   cd /app/src/rufus && alembic upgrade head
   ```

2. Database connection failed:

   ```bash
   # Check DATABASE_URL is correct
   docker run --rm rufus:latest env | grep DATABASE_URL
   ```

3. Missing dependencies:

   ```dockerfile
   # Ensure all dependencies in requirements.txt
   RUN pip install -r requirements.txt
   ```

### Kubernetes pod crash loop

**Problem:** Pods restarting constantly.

**Solution:** Check pod logs:

```bash
kubectl logs -f deployment/rufus-server
```

**Check resource limits:**

```yaml
resources:
  requests:
    memory: "512Mi"  # Increase if needed
    cpu: "500m"
  limits:
    memory: "1Gi"
    cpu: "1000m"
```

**Check health probes:**

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 60  # Increase if slow startup
  periodSeconds: 10
```

## Common error messages

### "UNIQUE constraint failed"

**Problem:** Attempting to create duplicate workflow.

**Solution:** Check for unique constraints:

```python
# Workflows have unique IDs (auto-generated)
# Don't reuse workflow IDs

# For idempotent operations, check if exists first
existing = await persistence.load_workflow(workflow_id)
if not existing:
    workflow = await builder.create_workflow(...)
```

### "Foreign key constraint failed"

**Problem:** Referencing non-existent parent workflow.

**Solution:** Ensure parent workflow exists:

```python
# When creating sub-workflow
parent_workflow = await persistence.load_workflow(parent_id)
if parent_workflow:
    # Safe to create sub-workflow
    sub_workflow = await builder.create_workflow(...)
```

### "Workflow not found"

**Problem:** Loading workflow that doesn't exist.

**Solution:** Check workflow ID is correct:

```python
try:
    workflow = await persistence.load_workflow(workflow_id)
except Exception:
    print(f"Workflow {workflow_id} not found")
```

## Getting help

### Enable debug logging

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("rufus")
logger.setLevel(logging.DEBUG)
```

### Check Rufus version

```python
import rufus
print(rufus.__version__)
```

### Diagnostic information

Collect this information when reporting issues:

```bash
# Python version
python --version

# Rufus version
python -c "import rufus; print(rufus.__version__)"

# Database version
psql --version  # or sqlite3 --version

# Environment variables
env | grep -E "(DATABASE|CELERY|RUFUS)"

# Workflow status
rufus show <workflow-id> --state --logs
```

### Workflow debugging checklist

When debugging workflow issues:

- [ ] Check workflow status (`rufus show <workflow-id>`)
- [ ] Check audit logs (`rufus logs <workflow-id>`)
- [ ] Verify step function can be imported
- [ ] Check database connection
- [ ] Verify YAML configuration is valid
- [ ] Check for unhandled exceptions in step functions
- [ ] Verify state is JSON-serializable
- [ ] Check Celery workers are running (if using Celery)
- [ ] Scan for zombie workflows (`rufus scan-zombies`)

## Next steps

- [Deploy to production](deployment.md)
- [Configure monitoring](configuration.md)
- [Optimize performance](configuration.md)

## See also

- [Installation guide](installation.md)
- [Configuration guide](configuration.md)
- [Testing guide](testing.md)
- CLAUDE.md for detailed troubleshooting
- GitHub Issues for known problems
