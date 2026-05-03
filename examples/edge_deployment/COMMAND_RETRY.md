# Command Retry System

## Overview

The Command Retry System provides automatic retry logic for failed device commands using configurable backoff strategies. This is critical for fintech edge devices with unreliable network connectivity.

## Features

- **Automatic Retries**: Failed commands automatically re-queued based on policy
- **Multiple Backoff Strategies**: Exponential, linear, or fixed delays
- **Jitter Support**: Random variation to prevent thundering herd
- **Configurable Limits**: Max retries, delays, and timeouts
- **Background Worker**: Daemon processes retries independently
- **Transparent to Devices**: Edge devices see retried commands as new commands

## Retry Policies

### Backoff Strategies

**Exponential Backoff** (Recommended):
- Delay doubles each retry: 10s, 20s, 40s, 80s...
- Best for transient failures
- Prevents overwhelming failed services

**Linear Backoff**:
- Delay increases linearly: 10s, 20s, 30s, 40s...
- Predictable timing
- Good for rate-limited APIs

**Fixed Backoff**:
- Same delay each time: 30s, 30s, 30s...
- Simple and predictable
- Good for periodic checks

### Predefined Policies

```python
# Default: 3 retries, exponential, 10s initial
"default": {
    "max_retries": 3,
    "initial_delay_seconds": 10,
    "backoff_strategy": "exponential",
    "backoff_multiplier": 2.0
}

# Aggressive: Fast retries for time-sensitive operations
"aggressive": {
    "max_retries": 5,
    "initial_delay_seconds": 5,
    "backoff_strategy": "exponential",
    "backoff_multiplier": 1.5
}

# Conservative: Slow retries to avoid overload
"conservative": {
    "max_retries": 2,
    "initial_delay_seconds": 30,
    "backoff_strategy": "linear"
}

# Persistent: Many retries with fixed delay
"persistent": {
    "max_retries": 10,
    "initial_delay_seconds": 60,
    "backoff_strategy": "fixed"
}

# Quick: Fast fixed retries for quick recovery
"quick": {
    "max_retries": 3,
    "initial_delay_seconds": 5,
    "backoff_strategy": "fixed"
}
```

## Usage

### Send Command with Retry Policy

```bash
# Exponential backoff (default)
python cloud_admin.py send-command macbook-m4-001 sync_now '{}' \
  '{"max_retries": 3, "initial_delay_seconds": 10, "backoff_strategy": "exponential"}'

# Fixed delay
python cloud_admin.py send-command rpi5-001 backup '{"target": "cloud"}' \
  '{"max_retries": 5, "initial_delay_seconds": 30, "backoff_strategy": "fixed"}'

# Custom exponential with longer max delay
python cloud_admin.py send-command macbook-m4-001 force_sync '{}' \
  '{"max_retries": 5, "initial_delay_seconds": 10, "backoff_strategy": "exponential", "max_delay_seconds": 600}'
```

### Retry Policy Parameters

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `max_retries` | int | 3 | 0-10 | Maximum retry attempts |
| `initial_delay_seconds` | int | 10 | 1-3600 | Delay before first retry |
| `backoff_strategy` | string | exponential | exponential, linear, fixed | Backoff calculation method |
| `backoff_multiplier` | float | 2.0 | 1.0-10.0 | Multiplier for exponential/linear |
| `max_delay_seconds` | int | 3600 | 60-86400 | Maximum delay between retries |
| `jitter` | bool | true | - | Add random variation (±20%) |

## API Examples

### REST API

**Send Command with Retry**:
```json
POST /api/v1/devices/macbook-m4-001/commands
{
  "type": "sync_now",
  "data": {},
  "retry_policy": {
    "max_retries": 3,
    "initial_delay_seconds": 10,
    "backoff_strategy": "exponential"
  }
}
```

**Response**:
```json
{
  "command_id": "cmd-abc123...",
  "device_id": "macbook-m4-001",
  "status": "queued",
  "delivery_method": "heartbeat"
}
```

### Python SDK

```python
from ruvon_server.device_service import DeviceService
from ruvon_server.retry_policy import RetryPolicy

# Create retry policy
retry_policy = RetryPolicy(
    max_retries=3,
    initial_delay_seconds=10,
    backoff_strategy="exponential"
)

# Send command with retry
command_id = await device_service.send_command(
    device_id="macbook-m4-001",
    command_type="sync_now",
    command_data={},
    retry_policy=retry_policy.to_dict()
)
```

## Retry Lifecycle

### 1. Command Fails

```
Device executes command
      ↓
Command execution fails
      ↓
Device reports status="failed", error="Network timeout"
      ↓
POST /devices/{id}/commands/{cmd_id}/status
```

### 2. Retry Scheduled

```
DeviceService.update_command_status() called
      ↓
Check if command has retry_policy
      ↓
Check if retry_count < max_retries
      ↓
Calculate next_retry_at based on backoff strategy
      ↓
Update command:
  - status = "failed"
  - retry_count += 1
  - next_retry_at = calculated_time
```

### 3. Retry Processed

```
Retry worker runs (every 60 seconds)
      ↓
Query for failed commands where next_retry_at <= NOW()
      ↓
Reset command to status="pending"
      ↓
Device picks up command in next heartbeat
      ↓
Command executed again
```

### 4. Final Outcome

**Success**:
```
Retry succeeds
      ↓
status = "completed"
      ↓
next_retry_at = NULL (no more retries needed)
```

**Permanent Failure**:
```
All retries exhausted
      ↓
status = "failed"
      ↓
next_retry_at = NULL
      ↓
retry_count = max_retries
```

## Retry Worker

### Running the Worker

**As Daemon** (runs continuously):
```bash
python -m ruvon_server.retry_worker \
  --db-url postgresql://ruvon:ruvon@localhost:5433/ruvon \
  --interval 60
```

**One-Shot** (process once and exit):
```bash
python -m ruvon_server.retry_worker --once
```

**Custom Interval**:
```bash
# Check every 30 seconds
python -m ruvon_server.retry_worker --interval 30

# Check every 5 minutes
python -m ruvon_server.retry_worker --interval 300
```

### Systemd Service

```ini
[Unit]
Description=Ruvon Command Retry Worker
After=network.target postgresql.service

[Service]
Type=simple
User=ruvon
WorkingDirectory=/opt/ruvon
Environment="DATABASE_URL=postgresql://ruvon:ruvon@localhost/ruvon"
ExecStart=/usr/bin/python3 -m ruvon_server.retry_worker --interval 60
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable ruvon-retry-worker
sudo systemctl start ruvon-retry-worker
sudo systemctl status ruvon-retry-worker
```

### Docker Compose

```yaml
services:
  retry-worker:
    build: .
    command: python -m ruvon_server.retry_worker --interval 60
    environment:
      DATABASE_URL: postgresql://ruvon:ruvon@postgres:5432/ruvon
    depends_on:
      - postgres
    restart: unless-stopped
```

## Monitoring

### Retry Metrics

**Database Queries**:

```sql
-- Count commands by retry status
SELECT
    status,
    COUNT(*) as count,
    AVG(retry_count) as avg_retries
FROM device_commands
WHERE retry_policy IS NOT NULL
GROUP BY status;

-- Find commands with many retries
SELECT
    command_id,
    device_id,
    command_type,
    retry_count,
    max_retries,
    next_retry_at,
    error_message
FROM device_commands
WHERE retry_count > 2
ORDER BY retry_count DESC;

-- Retry backlog (pending retries)
SELECT
    COUNT(*) as pending_retries,
    MIN(next_retry_at) as next_retry,
    MAX(retry_count) as max_retry_count
FROM device_commands
WHERE status = 'failed'
  AND next_retry_at IS NOT NULL
  AND retry_count < max_retries;
```

**Key Metrics**:
- Retry success rate: `completed / (completed + failed)`
- Average retries to success: `AVG(retry_count) WHERE status='completed'`
- Permanent failures: `COUNT(*) WHERE retry_count = max_retries`
- Retry backlog size: `COUNT(*) WHERE next_retry_at IS NOT NULL`

### Alerts

**High Retry Rate**:
```sql
-- Alert if > 30% of commands require retries
SELECT
    COUNT(*) FILTER (WHERE retry_count > 0) * 100.0 / COUNT(*) as retry_rate
FROM device_commands
WHERE created_at > NOW() - INTERVAL '1 hour';
```

**Retry Worker Down**:
```sql
-- Alert if retry backlog growing
SELECT COUNT(*)
FROM device_commands
WHERE next_retry_at < NOW() - INTERVAL '5 minutes';
-- Should be 0 if worker is running
```

## Best Practices

### Choosing Retry Policies

**Transient Network Errors** (recommended):
```json
{
  "max_retries": 3,
  "initial_delay_seconds": 10,
  "backoff_strategy": "exponential"
}
```
- Quick initial retry (10s)
- Exponential backoff prevents overwhelming failed connections
- 3 retries covers most transient issues

**Rate-Limited APIs**:
```json
{
  "max_retries": 5,
  "initial_delay_seconds": 60,
  "backoff_strategy": "fixed"
}
```
- Longer initial delay to respect rate limits
- Fixed backoff for predictable timing
- More retries for persistent rate limiting

**Critical Operations**:
```json
{
  "max_retries": 10,
  "initial_delay_seconds": 30,
  "backoff_strategy": "exponential",
  "max_delay_seconds": 600
}
```
- Many retries for important operations
- Capped max delay prevents excessive waits

### When NOT to Use Retries

- **Idempotency issues**: If command execution is not idempotent
- **User-facing errors**: If user needs immediate feedback
- **Invalid data**: If command data is malformed
- **Permission errors**: If device lacks permissions

## Troubleshooting

### Commands Not Retrying

**Check retry policy**:
```sql
SELECT command_id, retry_policy, retry_count, max_retries, next_retry_at
FROM device_commands
WHERE command_id = 'cmd-abc123...';
```

**Verify retry worker is running**:
```bash
ps aux | grep retry_worker
```

**Check retry worker logs**:
```bash
journalctl -u ruvon-retry-worker -f
```

### Retry Storm (Too Many Retries)

**Identify culprit**:
```sql
SELECT command_type, COUNT(*) as retry_count
FROM device_commands
WHERE status = 'failed' AND next_retry_at IS NOT NULL
GROUP BY command_type
ORDER BY retry_count DESC;
```

**Disable retries for specific command type** (emergency):
```sql
UPDATE device_commands
SET next_retry_at = NULL
WHERE command_type = 'problematic_command';
```

### Permanent Failures Not Logged

**Check if hitting max retries**:
```sql
SELECT command_id, retry_count, max_retries, error_message
FROM device_commands
WHERE retry_count = max_retries;
```

**Review error messages**:
```sql
SELECT error_message, COUNT(*) as count
FROM device_commands
WHERE status = 'failed' AND retry_count = max_retries
GROUP BY error_message
ORDER BY count DESC;
```

## Database Schema

```sql
ALTER TABLE device_commands
ADD COLUMN retry_policy JSONB DEFAULT NULL,
ADD COLUMN retry_count INT DEFAULT 0,
ADD COLUMN max_retries INT DEFAULT 0,
ADD COLUMN next_retry_at TIMESTAMPTZ DEFAULT NULL,
ADD COLUMN last_retry_at TIMESTAMPTZ DEFAULT NULL;

CREATE INDEX idx_device_command_retry
ON device_commands(next_retry_at)
WHERE status = 'failed' AND next_retry_at IS NOT NULL;
```

## Migration

For existing deployments:

```bash
# Apply migration
psql -U ruvon -d ruvon < docker/migrations/add_command_retry_support.sql

# Verify
psql -U ruvon -d ruvon -c "\d device_commands"
```

## Performance Considerations

- **Retry worker interval**: 60s is optimal for most deployments
- **Batch size**: Processes 100 retries per iteration
- **Index**: `idx_device_command_retry` ensures fast retry queries
- **Jitter**: Prevents thundering herd on retry spikes

## Security Considerations

- Retry policies stored in database (not client-controlled at runtime)
- Max retries capped at 10 to prevent abuse
- Max delay capped at 24 hours
- Retry worker should run with limited database permissions
