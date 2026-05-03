# Zombie Workflow Recovery

A "zombie workflow" is a workflow stuck in `PENDING_ASYNC` status because the worker processing it crashed before completing the task. Without recovery mechanisms, these workflows remain in limbo forever, appearing to be running but actually abandoned.

## The Problem

Consider this scenario:

```
1. Workflow dispatches async task to Celery worker
   → Status: PENDING_ASYNC
   → Worker receives task

2. Worker starts executing step function
   → Processing large file upload (5GB)
   → Memory usage: 4.5GB

3. OOM Killer terminates worker
   → Worker process killed instantly
   → No cleanup, no status update
   → Workflow remains: PENDING_ASYNC

4. Forever
   → Workflow thinks worker is still processing
   → Worker is dead, task will never complete
   → Status: PENDING_ASYNC (zombie!)
```

**Impact**:
- Workflows appear stuck in UI
- Resources not released (inventory allocations, payment holds)
- SLA violations (order promised in 24h, stuck for days)
- Manual intervention required to identify and fix

## How Zombie Detection Works

Ruvon uses a heartbeat-based approach inherited from Confucius:

### 1. Heartbeat During Execution

While processing a step, workers send periodic heartbeats:

```python
from ruvon.heartbeat import HeartbeatManager

async def long_running_step(state: MyState, context: StepContext):
    # Create heartbeat manager
    heartbeat = HeartbeatManager(
        persistence=context.persistence,
        workflow_id=context.workflow_id,
        heartbeat_interval_seconds=30  # Send heartbeat every 30s
    )

    # Start heartbeat (runs in background thread)
    async with heartbeat:
        # Long-running operation
        result = await process_large_file(state.file_url)

        # Heartbeat automatically stops when context exits

    return {"result": result}
```

**What happens**:
- Heartbeat manager sends updates every 30 seconds to `workflow_heartbeats` table
- Includes: workflow_id, worker_id, current_step, last_heartbeat timestamp
- Background thread handles sending, main thread focuses on work

### 2. Heartbeat Storage

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

**Example row**:
```
workflow_id  | worker_id      | last_heartbeat       | current_step       | step_started_at
-------------|----------------|----------------------|--------------------|------------------
550e8400-... | celery@worker1 | 2026-02-13 10:15:45  | Process_Payment    | 2026-02-13 10:15:30
```

### 3. Zombie Scanner

A separate process periodically scans for stale heartbeats:

```python
from ruvon.zombie_scanner import ZombieScanner

scanner = ZombieScanner(
    persistence=persistence_provider,
    stale_threshold_seconds=120  # Heartbeat older than 2 minutes = zombie
)

# One-shot scan
summary = await scanner.scan_and_recover(dry_run=False)
print(f"Found {summary['zombies_found']} zombies, recovered {summary['zombies_recovered']}")

# Or run as daemon
await scanner.run_daemon(
    scan_interval_seconds=60,      # Scan every 60 seconds
    stale_threshold_seconds=120    # 2-minute threshold
)
```

**Detection Query**:
```sql
-- Find workflows with stale heartbeats
SELECT we.id, we.workflow_type, we.current_step, wh.last_heartbeat
FROM workflow_executions we
JOIN workflow_heartbeats wh ON we.id = wh.workflow_id
WHERE we.status = 'PENDING_ASYNC'
  AND wh.last_heartbeat < NOW() - INTERVAL '120 seconds';
```

### 4. Automatic Recovery

When zombie detected:

```python
# Mark workflow as crashed
await persistence.update_workflow_status(
    workflow_id=zombie_id,
    new_status="FAILED_WORKER_CRASH"
)

# Log to audit trail
await persistence.log_execution(
    workflow_id=zombie_id,
    event_type="ZOMBIE_DETECTED",
    event_data={
        "last_heartbeat": last_heartbeat,
        "current_step": current_step,
        "stale_duration_seconds": stale_duration
    }
)

# Clean up heartbeat record
await persistence.delete_heartbeat(workflow_id=zombie_id)
```

## Deployment Strategies

### 1. CLI One-Shot Scan

Run manually or via cron:

```bash
# Scan for zombies (dry-run)
ruvon scan-zombies --db postgresql://localhost/ruvon

# Scan and recover
ruvon scan-zombies --db postgresql://localhost/ruvon --fix

# Custom threshold
ruvon scan-zombies --db postgresql://localhost/ruvon --fix --threshold 180

# JSON output for monitoring
ruvon scan-zombies --db postgresql://localhost/ruvon --json
```

**Crontab example**:
```cron
# Run every 5 minutes
*/5 * * * * ruvon scan-zombies --db $DATABASE_URL --fix >> /var/log/ruvon/zombie-scanner.log 2>&1
```

### 2. Daemon Mode

Run as long-lived background process:

```bash
# Run as daemon
ruvon zombie-daemon --db postgresql://localhost/ruvon

# Custom intervals
ruvon zombie-daemon --db postgresql://localhost/ruvon --interval 60 --threshold 120
```

### 3. Systemd Service

```ini
# /etc/systemd/system/ruvon-zombie-scanner.service
[Unit]
Description=Ruvon Zombie Workflow Scanner
After=network.target postgresql.service

[Service]
Type=simple
User=ruvon
Environment=DATABASE_URL=postgresql://ruvon:password@localhost/ruvon
ExecStart=/usr/bin/ruvon zombie-daemon --db ${DATABASE_URL} --interval 60
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable ruvon-zombie-scanner
sudo systemctl start ruvon-zombie-scanner
sudo systemctl status ruvon-zombie-scanner
```

### 4. Kubernetes CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ruvon-zombie-scanner
spec:
  schedule: "*/5 * * * *"  # Every 5 minutes
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: scanner
            image: myapp/ruvon:latest
            command:
            - ruvon
            - scan-zombies
            - --db
            - postgresql://postgres/ruvon
            - --fix
            env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: ruvon-db-secret
                  key: url
          restartPolicy: OnFailure
```

## Configuration Guidelines

### Heartbeat Interval

How often workers send heartbeats:

| Workload Type | Step Duration | Heartbeat Interval | Reasoning |
|---------------|---------------|-------------------|-----------|
| **Fast steps** | < 1 minute | 15 seconds | Frequent updates, detect crashes quickly |
| **Medium steps** | 1-10 minutes | 30 seconds | Default, good balance |
| **Long steps** | 10-60 minutes | 60 seconds | Less overhead, still responsive |
| **Very long steps** | 1+ hours | 300 seconds | Minimize overhead, slower detection acceptable |

**Rule**: Heartbeat interval should be ~1/4 to 1/2 of typical step duration.

### Stale Threshold

How long before heartbeat considered stale:

| Environment | Threshold | Reasoning |
|-------------|-----------|-----------|
| **Development** | 60 seconds | Fast feedback during testing |
| **Staging** | 120 seconds | Realistic, catch real issues |
| **Production** | 120-180 seconds | Avoid false positives from GC pauses |
| **High Latency** | 300 seconds | Network delays, slow databases |

**Rule**: Stale threshold should be > 2× heartbeat interval to avoid false positives.

**Why 2x?**: Accounts for:
- Heartbeat send time (~1s)
- Database write lag (~1-2s)
- Scanner query delay (~1s)
- Network jitter (~0.5s)
- Clock skew (~1s)

### Scan Interval

How often zombie scanner runs:

| Environment | Scan Interval | Reasoning |
|-------------|--------------|-----------|
| **Development** | 30 seconds | Fast iteration, immediate feedback |
| **Staging** | 60 seconds | Realistic production simulation |
| **Production** | 60-120 seconds | Balance detection speed vs database load |
| **High Volume** | 300 seconds | Reduce database overhead |

**Trade-off**: Lower interval = faster detection, but more database queries.

## False Positives

### Causes

1. **GC pauses**: JVM/Python GC stops heartbeat thread for 30+ seconds
2. **Network partition**: Worker alive but can't reach database
3. **Database overload**: Heartbeat writes timing out
4. **Clock skew**: Database and scanner have different system times

### Prevention

**1. Increase stale threshold during high load**:
```python
# Normal: 120s threshold
scanner = ZombieScanner(persistence, stale_threshold_seconds=120)

# Black Friday (high load): 300s threshold
if is_high_traffic_period():
    scanner = ZombieScanner(persistence, stale_threshold_seconds=300)
```

**2. Use retry logic for heartbeats**:
```python
# HeartbeatManager already implements retries
heartbeat = HeartbeatManager(
    persistence=persistence,
    workflow_id=workflow_id,
    heartbeat_interval_seconds=30,
    retry_attempts=3,  # Retry 3 times on failure
    retry_delay_seconds=5
)
```

**3. Monitor false positive rate**:
```python
# Check for workflows marked as zombie but later recovered
false_positives = await persistence.query("""
    SELECT COUNT(*)
    FROM workflow_audit_log
    WHERE event_type = 'ZOMBIE_DETECTED'
      AND workflow_id IN (
          SELECT workflow_id
          FROM workflow_audit_log
          WHERE event_type = 'STEP_EXECUTED'
            AND created_at > (
                SELECT created_at
                FROM workflow_audit_log
                WHERE event_type = 'ZOMBIE_DETECTED'
                  AND workflow_id = workflow_audit_log.workflow_id
            )
      )
""")

# Alert if > 5% false positive rate
if false_positives / total_zombies > 0.05:
    alert("High false positive rate in zombie detection")
```

## Recovery Workflow

When a zombie is detected and marked `FAILED_WORKER_CRASH`, what next?

### Option 1: Manual Retry

Ops team reviews and retries:

```bash
# List crashed workflows
ruvon list --status FAILED_WORKER_CRASH

# Review specific workflow
ruvon show <workflow-id> --logs --state

# Retry from failed step
ruvon retry <workflow-id> --from-step Process_Payment
```

### Option 2: Automatic Retry

Implement automatic retry with exponential backoff:

```python
# Custom zombie recovery with retry
async def recover_zombie_with_retry(workflow_id, persistence):
    workflow = await persistence.load_workflow(workflow_id)

    # Mark as crashed
    await persistence.update_workflow_status(workflow_id, "FAILED_WORKER_CRASH")

    # Check retry count
    retry_count = workflow.get('zombie_retry_count', 0)

    if retry_count < 3:  # Max 3 retries
        # Increment retry count
        await persistence.update_workflow(
            workflow_id,
            {'zombie_retry_count': retry_count + 1}
        )

        # Retry after delay
        delay = 2 ** retry_count * 60  # 1min, 2min, 4min
        await asyncio.sleep(delay)

        # Retry workflow
        await persistence.update_workflow_status(workflow_id, "ACTIVE")
        await persistence.reset_to_step(workflow_id, workflow['current_step'])
    else:
        # Max retries exceeded, alert ops team
        alert_ops_team(f"Zombie workflow {workflow_id} failed after 3 retries")
```

### Option 3: Saga Rollback

If workflow has saga enabled:

```python
# Custom zombie recovery with saga
async def recover_zombie_with_saga(workflow_id, persistence):
    workflow = await persistence.load_workflow(workflow_id)

    if workflow.get('saga_enabled'):
        # Trigger saga compensation
        await persistence.update_workflow_status(workflow_id, "FAILED")
        await execute_saga_compensation(workflow_id, persistence)
        # Final status: FAILED_ROLLED_BACK
    else:
        # No saga, just mark as crashed
        await persistence.update_workflow_status(workflow_id, "FAILED_WORKER_CRASH")
```

## Monitoring and Alerting

### Metrics to Track

```python
# Zombie detection rate
zombies_per_hour = count_zombies_last_hour()
if zombies_per_hour > 10:
    alert("High zombie detection rate")

# Average time to detection
avg_detection_time = avg_time_from_crash_to_detection()
if avg_detection_time > 300:  # > 5 minutes
    alert("Slow zombie detection")

# Recovery success rate
recovery_rate = recovered_zombies / total_zombies
if recovery_rate < 0.9:  # < 90%
    alert("Low zombie recovery rate")
```

### Prometheus Metrics

```python
from prometheus_client import Counter, Histogram

zombies_detected = Counter('ruvon_zombies_detected_total', 'Total zombies detected')
zombies_recovered = Counter('ruvon_zombies_recovered_total', 'Total zombies recovered')
zombie_detection_time = Histogram('ruvon_zombie_detection_seconds', 'Time from crash to detection')

# In scanner
zombies_detected.inc()
zombie_detection_time.observe(time_since_last_heartbeat)

# After recovery
zombies_recovered.inc()
```

### Grafana Dashboard

```
Panel 1: Zombie Detection Rate
- Query: rate(ruvon_zombies_detected_total[5m])
- Alert: > 0.1 zombies/second

Panel 2: Average Detection Time
- Query: rate(ruvon_zombie_detection_seconds_sum[5m]) / rate(ruvon_zombie_detection_seconds_count[5m])
- Alert: > 300 seconds

Panel 3: Recovery Success Rate
- Query: rate(ruvon_zombies_recovered_total[5m]) / rate(ruvon_zombies_detected_total[5m])
- Alert: < 0.9
```

## What's Next

Now that you understand zombie recovery:
- [Workflow Lifecycle](workflow-lifecycle.md) - FAILED_WORKER_CRASH state
- [Workflow Versioning](workflow-versioning.md) - Another reliability feature
- [Architecture](architecture.md) - How heartbeats fit into the system
