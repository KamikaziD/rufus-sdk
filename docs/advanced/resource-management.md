# Advanced: Resource Management

Best practices for managing memory, connections, and system resources in production Rufus deployments.

---

## Connection Pooling

### PostgreSQL Connection Pool Configuration

```python
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider


# Default configuration (suitable for most deployments)
persistence = PostgresPersistenceProvider(
    db_url="postgresql://user:pass@localhost:5432/rufus",
    pool_min_size=10,   # Minimum connections
    pool_max_size=50,   # Maximum connections
)


# Low concurrency (< 10 concurrent workflows)
persistence = PostgresPersistenceProvider(
    db_url=db_url,
    pool_min_size=5,
    pool_max_size=20,
)


# High concurrency (> 100 concurrent workflows)
persistence = PostgresPersistenceProvider(
    db_url=db_url,
    pool_min_size=20,
    pool_max_size=100,
)
```

**Environment Variables:**

```bash
export POSTGRES_POOL_MIN_SIZE=10
export POSTGRES_POOL_MAX_SIZE=50
export POSTGRES_POOL_COMMAND_TIMEOUT=10
export POSTGRES_POOL_MAX_QUERIES=50000
export POSTGRES_POOL_MAX_INACTIVE_LIFETIME=300
```

---

### Connection Leak Detection

```python
import asyncio
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider


async def monitor_connection_pool(persistence: PostgresPersistenceProvider):
    """Monitor connection pool for leaks"""
    while True:
        pool_size = persistence.pool.get_size()
        pool_free = persistence.pool.get_idle_size()
        pool_used = pool_size - pool_free

        print(f"Connection Pool: {pool_used}/{pool_size} in use, {pool_free} idle")

        # Alert if pool exhausted
        if pool_free == 0 and pool_size >= persistence.pool._max_size:
            print("⚠️  WARNING: Connection pool exhausted!")
            # Send alert to monitoring system
            alert_ops_team("PostgreSQL connection pool exhausted")

        await asyncio.sleep(60)  # Check every minute


# Run in background
asyncio.create_task(monitor_connection_pool(persistence))
```

---

### Proper Connection Cleanup

```python
# ❌ Wrong: Connection leak
async def bad_workflow_execution():
    persistence = PostgresPersistenceProvider(db_url)
    await persistence.initialize()

    workflow = builder.create_workflow("MyWorkflow", data)
    await workflow.next_step()

    # Forgot to close!


# ✅ Correct: Always close
async def good_workflow_execution():
    persistence = PostgresPersistenceProvider(db_url)
    await persistence.initialize()

    try:
        workflow = builder.create_workflow("MyWorkflow", data)
        await workflow.next_step()
    finally:
        await persistence.close()


# ✅ Best: Use context manager
async def best_workflow_execution():
    async with PostgresPersistenceProvider(db_url) as persistence:
        await persistence.initialize()
        workflow = builder.create_workflow("MyWorkflow", data)
        await workflow.next_step()
    # Automatically closed
```

---

## Memory Management

### Workflow State Size Limits

```python
from pydantic import BaseModel, validator


class LimitedWorkflowState(BaseModel):
    """Workflow state with size limits"""

    user_id: str
    transaction_data: dict

    @validator('transaction_data')
    def limit_transaction_data_size(cls, v):
        """Prevent huge state objects"""
        import sys

        size_bytes = sys.getsizeof(str(v))
        max_size = 1024 * 1024  # 1 MB

        if size_bytes > max_size:
            raise ValueError(
                f"transaction_data too large: {size_bytes} bytes "
                f"(max: {max_size} bytes)"
            )

        return v
```

---

### Large Data Handling

**❌ Don't store large data in workflow state:**

```python
# BAD: State becomes huge
class BadState(BaseModel):
    file_contents: str  # Could be 100 MB!
    image_data: bytes   # Could be 50 MB!
```

**✅ Store large data externally:**

```python
# GOOD: Store references, not data
class GoodState(BaseModel):
    file_s3_key: str        # Reference to S3 object
    image_url: str          # Reference to image URL
    large_data_id: str      # Reference to database blob


def process_large_file(state: GoodState, context: StepContext):
    """Process large file from S3"""
    # Download only when needed
    file_data = s3.get_object(Bucket='my-bucket', Key=state.file_s3_key)

    # Process file
    result = process_file(file_data['Body'].read())

    # Store result in S3, not state
    result_key = f"results/{context.workflow_id}/result.json"
    s3.put_object(Bucket='my-bucket', Key=result_key, Body=result)

    return {"result_s3_key": result_key}
```

---

### Memory Leak Detection

```python
import tracemalloc
import asyncio


async def monitor_memory_usage():
    """Monitor memory usage for leaks"""
    tracemalloc.start()

    snapshot1 = tracemalloc.take_snapshot()

    # Run workflows
    await asyncio.sleep(3600)  # 1 hour

    snapshot2 = tracemalloc.take_snapshot()

    # Compare snapshots
    top_stats = snapshot2.compare_to(snapshot1, 'lineno')

    print("Top 10 memory increases:")
    for stat in top_stats[:10]:
        print(stat)

    # Alert if significant leak
    total_increase = sum(stat.size_diff for stat in top_stats)
    if total_increase > 100 * 1024 * 1024:  # 100 MB
        alert_ops_team(f"Memory leak detected: {total_increase} bytes")
```

---

## Workflow Cleanup

### Delete Completed Workflows

```python
async def cleanup_old_workflows(
    persistence: PersistenceProvider,
    days_old: int = 90,
    batch_size: int = 100
):
    """Delete workflows older than X days"""
    from datetime import datetime, timedelta

    cutoff_date = datetime.utcnow() - timedelta(days=days_old)

    print(f"Deleting workflows older than {cutoff_date.isoformat()}")

    deleted_count = 0

    while True:
        # Find old completed workflows
        workflows = await persistence.list_workflows(
            status="COMPLETED",
            limit=batch_size
        )

        # Filter by date
        old_workflows = [
            w for w in workflows
            if w.get('completed_at') and
            datetime.fromisoformat(w['completed_at']) < cutoff_date
        ]

        if not old_workflows:
            break

        # Delete batch
        for workflow in old_workflows:
            await persistence.delete_workflow(workflow['id'])
            deleted_count += 1

        print(f"Deleted {len(old_workflows)} workflows (total: {deleted_count})")

        # Small delay between batches
        await asyncio.sleep(1)

    print(f"✓ Cleanup complete: {deleted_count} workflows deleted")


# Run as cron job
# 0 2 * * * python cleanup_workflows.py
```

---

### Archive Instead of Delete

```python
async def archive_old_workflows(
    persistence: PersistenceProvider,
    s3_bucket: str,
    days_old: int = 90
):
    """Archive workflows to S3, then delete from database"""
    import json

    workflows = await persistence.list_workflows(status="COMPLETED", limit=1000)

    for workflow in workflows:
        if is_old_enough(workflow, days_old):
            # Export to JSON
            workflow_json = json.dumps(workflow, indent=2)

            # Upload to S3
            s3_key = f"archive/{workflow['id']}/workflow.json"
            s3.put_object(
                Bucket=s3_bucket,
                Key=s3_key,
                Body=workflow_json
            )

            # Delete from database
            await persistence.delete_workflow(workflow['id'])

            print(f"Archived {workflow['id']} to s3://{s3_bucket}/{s3_key}")
```

---

## Task Queue Management

### Celery Worker Configuration

```python
# celeryconfig.py

# Worker concurrency
worker_concurrency = 10  # Number of worker processes

# Task time limits
task_soft_time_limit = 300   # 5 minutes (warning)
task_time_limit = 600         # 10 minutes (hard kill)

# Memory limits
worker_max_memory_per_child = 200000  # 200 MB, restart worker after

# Prefetch limits
worker_prefetch_multiplier = 4  # Tasks to prefetch per worker

# Task rejection
task_reject_on_worker_lost = True  # Re-queue if worker dies

# Results backend
result_expires = 3600  # 1 hour (clean up results)
```

---

### Monitor Queue Depth

```python
from celery import Celery

app = Celery('rufus')


async def monitor_queue_depth():
    """Monitor Celery queue depth"""
    inspect = app.control.inspect()

    while True:
        # Get queue stats
        stats = inspect.stats()

        for worker, worker_stats in (stats or {}).items():
            queue_depth = worker_stats.get('total', 0)

            print(f"Worker {worker}: {queue_depth} tasks queued")

            # Alert if queue too deep
            if queue_depth > 1000:
                alert_ops_team(f"Queue depth high: {queue_depth} tasks")

        await asyncio.sleep(60)
```

---

## Database Maintenance

### Vacuum and Analyze (PostgreSQL)

```sql
-- Run weekly
VACUUM ANALYZE workflow_executions;
VACUUM ANALYZE workflow_audit_log;
VACUUM ANALYZE workflow_metrics;

-- Check table bloat
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

---

### Index Maintenance

```sql
-- Find missing indexes
SELECT
    schemaname,
    tablename,
    attname,
    n_distinct,
    correlation
FROM pg_stats
WHERE schemaname = 'public'
AND n_distinct > 100
AND correlation < 0.1
ORDER BY n_distinct DESC;

-- Rebuild indexes (if fragmented)
REINDEX TABLE workflow_executions;
```

---

## Monitoring and Alerts

### Resource Monitoring

```python
import psutil


async def monitor_system_resources():
    """Monitor CPU, memory, disk usage"""
    while True:
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=1)

        # Memory usage
        memory = psutil.virtual_memory()
        memory_percent = memory.percent

        # Disk usage
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent

        print(f"CPU: {cpu_percent}% | Memory: {memory_percent}% | Disk: {disk_percent}%")

        # Alert thresholds
        if cpu_percent > 80:
            alert_ops_team(f"High CPU usage: {cpu_percent}%")

        if memory_percent > 85:
            alert_ops_team(f"High memory usage: {memory_percent}%")

        if disk_percent > 90:
            alert_ops_team(f"High disk usage: {disk_percent}%")

        await asyncio.sleep(60)
```

---

## Performance Tuning

### Database Query Optimization

```python
# ❌ Slow: N+1 query problem
async def get_workflows_with_logs_slow(persistence):
    workflows = await persistence.list_workflows(limit=100)

    for workflow in workflows:
        # Separate query for each workflow!
        logs = await persistence.get_execution_logs(workflow['id'])
        workflow['logs'] = logs

    return workflows


# ✅ Fast: Batch query
async def get_workflows_with_logs_fast(persistence):
    workflows = await persistence.list_workflows(limit=100)
    workflow_ids = [w['id'] for w in workflows]

    # Single query for all logs
    all_logs = await persistence.get_logs_batch(workflow_ids)

    # Group logs by workflow_id
    logs_by_workflow = {}
    for log in all_logs:
        logs_by_workflow.setdefault(log['workflow_id'], []).append(log)

    # Attach logs to workflows
    for workflow in workflows:
        workflow['logs'] = logs_by_workflow.get(workflow['id'], [])

    return workflows
```

---

### Caching Frequently Accessed Data

```python
import redis
import json

redis_client = redis.Redis(host='localhost', port=6379)


async def get_workflow_with_cache(persistence, workflow_id: str):
    """Get workflow with Redis caching"""
    cache_key = f"workflow:{workflow_id}"

    # Check cache first
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    # Cache miss: load from database
    workflow = await persistence.load_workflow(workflow_id)

    # Cache for 5 minutes
    redis_client.setex(cache_key, 300, json.dumps(workflow))

    return workflow
```

---

## Summary

**Resource Management Checklist:**

- [ ] **Connection Pooling**
  - [ ] Pool size configured for workload
  - [ ] Connection leak detection
  - [ ] Proper cleanup in finally blocks

- [ ] **Memory Management**
  - [ ] State size limits enforced
  - [ ] Large data stored externally (S3)
  - [ ] Memory leak detection

- [ ] **Workflow Cleanup**
  - [ ] Old workflows archived/deleted
  - [ ] Cleanup scheduled (cron)
  - [ ] Retention policy documented

- [ ] **Database Maintenance**
  - [ ] Regular VACUUM (PostgreSQL)
  - [ ] Index optimization
  - [ ] Query performance monitoring

- [ ] **Monitoring**
  - [ ] CPU, memory, disk alerts
  - [ ] Queue depth monitoring
  - [ ] Connection pool monitoring

- [ ] **Performance**
  - [ ] Queries optimized (no N+1)
  - [ ] Caching for hot data
  - [ ] Indexes on frequently queried columns

**Regular Tasks:**
- Weekly: VACUUM ANALYZE database
- Daily: Check connection pool health
- Monthly: Archive old workflows
- Quarterly: Review and optimize indexes
