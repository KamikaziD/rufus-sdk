# CLI Commands and Webhook Retry Implementation

## Overview

Implemented comprehensive CLI commands and webhook retry mechanism to complete the Tier 4 advanced features.

**Status:** ✅ Complete Implementation

---

## Part 1: CLI Commands

### Command Versioning CLI

**File:** `examples/edge_deployment/cloud_admin.py`

#### 1. List Command Versions

```bash
# List all command versions
python cloud_admin.py list-command-versions

# List versions for specific command type
python cloud_admin.py list-command-versions restart

# List only active versions
python cloud_admin.py list-command-versions --active-only

# List active versions for specific type
python cloud_admin.py list-command-versions restart --active-only
```

**Output:**
```
======================================================================
  COMMAND VERSIONS
======================================================================

  Total versions: 4

  restart v1.0.0 ✓ Active

  health_check v1.0.0 ✓ Active

  update_firmware v1.0.0 ✓ Active

  clear_cache v1.0.0 ✓ Active
```

#### 2. Get Command Version Details

```bash
python cloud_admin.py get-command-version restart 1.0.0
```

**Output:**
```
======================================================================
  COMMAND VERSION: restart v1.0.0
======================================================================

  Command Type:  restart
  Version:       1.0.0
  Active:        Yes
  Deprecated:    No
  Changelog:     Initial version

  Schema Definition:
  {
    "type": "object",
    "properties": {
      "delay_seconds": {
        "type": "integer",
        "minimum": 0,
        "maximum": 300
      }
    },
    "required": []
  }
```

#### 3. Validate Command Data

```bash
# Valid command
python cloud_admin.py validate-command restart 1.0.0 '{"delay_seconds": 10}'

# Invalid command (delay too large)
python cloud_admin.py validate-command restart 1.0.0 '{"delay_seconds": 500}'

# Invalid command (wrong type)
python cloud_admin.py validate-command restart 1.0.0 '{"delay_seconds": "abc"}'
```

**Output (Valid):**
```
======================================================================
  VALIDATE COMMAND: restart v1.0.0
======================================================================

  ✓ Command data is valid!
```

**Output (Invalid):**
```
======================================================================
  VALIDATE COMMAND: restart v1.0.0
======================================================================

  ✗ Command data is invalid

  Errors:
    - delay_seconds: 500 is greater than the maximum of 300
```

#### 4. Get Command Changelog

```bash
# Get all changelog entries for a command
python cloud_admin.py command-changelog restart

# Get changelog between specific versions
python cloud_admin.py command-changelog restart 1.0.0 2.0.0
```

---

### Webhook Management CLI

**File:** `examples/edge_deployment/cloud_admin.py`

#### 1. List Webhooks

```bash
# List all webhooks
python cloud_admin.py list-webhooks

# List only active webhooks
python cloud_admin.py list-webhooks --active-only
```

**Output:**
```
======================================================================
  WEBHOOKS
======================================================================

  Total webhooks: 2

  my-webhook - Device Events ✓ Active
    URL:    https://example.com/webhook
    Events: device.online, device.offline

  backup-webhook - Command Notifications ✓ Active
    URL:    https://backup.example.com/webhook
    Events: command.completed, command.failed
```

#### 2. Get Webhook Details

```bash
python cloud_admin.py get-webhook my-webhook
```

**Output:**
```
======================================================================
  WEBHOOK: my-webhook
======================================================================

  Webhook ID:    my-webhook
  Name:          Device Events
  URL:           https://example.com/webhook
  Events:        device.online, device.offline
  Active:        Yes
  Secret:        Configured
  Custom Headers: {
    "Authorization": "Bearer token123"
  }
```

#### 3. Create Webhook

```bash
python cloud_admin.py create-webhook '{
  "webhook_id": "my-webhook",
  "name": "Device Events",
  "url": "https://example.com/webhook",
  "events": ["device.online", "device.offline"],
  "secret": "my-secret-key",
  "headers": {"Authorization": "Bearer token123"}
}'
```

**Output:**
```
======================================================================
  CREATE WEBHOOK
======================================================================

  ✓ Webhook created successfully!
  Webhook ID: my-webhook
  Status:     registered
  Events:     device.online, device.offline
```

#### 4. Update Webhook

```bash
# Deactivate webhook
python cloud_admin.py update-webhook my-webhook '{"is_active": false}'

# Update events
python cloud_admin.py update-webhook my-webhook '{
  "events": ["device.online", "device.offline", "device.error"]
}'

# Update URL
python cloud_admin.py update-webhook my-webhook '{
  "url": "https://new-endpoint.example.com/webhook"
}'
```

#### 5. Delete Webhook

```bash
python cloud_admin.py delete-webhook my-webhook
```

**Output:**
```
======================================================================
  DELETE WEBHOOK: my-webhook
======================================================================

  ✓ Webhook deleted successfully!
  Webhook ID: my-webhook
```

#### 6. Get Webhook Deliveries

```bash
# Get all deliveries
python cloud_admin.py webhook-deliveries my-webhook

# Get only failed deliveries
python cloud_admin.py webhook-deliveries my-webhook failed

# Get last 50 failed deliveries
python cloud_admin.py webhook-deliveries my-webhook failed 50
```

**Output:**
```
======================================================================
  WEBHOOK DELIVERIES: my-webhook
======================================================================

  Total deliveries: 25

  ✓ device.online - delivered
    ID:         abc123
    Created:    2026-02-06T12:00:00Z
    HTTP:       200
    Attempts:   1

  ✗ device.offline - failed
    ID:         def456
    Created:    2026-02-06T12:05:00Z
    Error:      Connection timeout
    Attempts:   2
```

#### 7. Test Webhook

```bash
# Test webhook without saving
python cloud_admin.py test-webhook \
  "https://example.com/webhook" \
  "device.online" \
  '{"device_id": "test-123"}' \
  "optional-secret"
```

**Output:**
```
======================================================================
  TEST WEBHOOK: https://example.com/webhook
======================================================================

  ✓ Webhook test successful!
  Status:     sent
  URL:        https://example.com/webhook
  Event Type: device.online
```

---

## Part 2: Webhook Retry Mechanism

### Overview

Automatic background worker that retries failed webhook deliveries based on configurable retry policies.

**File:** `src/ruvon_server/webhook_retry_worker.py`

### Features

- **Automatic Retry**: Scans for failed deliveries periodically
- **Retry Policies**: Respects per-webhook retry configuration
- **Backoff Strategies**: Exponential or fixed delay
- **Concurrency Limit**: Prevents overwhelming webhook endpoints
- **Graceful Shutdown**: Handles SIGTERM/SIGINT for clean shutdown

### Retry Policy Configuration

When creating a webhook, specify a retry policy:

```json
{
  "retry_policy": {
    "max_retries": 5,
    "initial_delay_seconds": 60,
    "backoff_strategy": "exponential",
    "backoff_multiplier": 2.0,
    "max_delay_seconds": 3600
  }
}
```

**Parameters:**

- `max_retries`: Maximum number of retry attempts (default: 3)
- `initial_delay_seconds`: Initial delay before first retry (default: 60)
- `backoff_strategy`: "exponential" or "fixed" (default: "exponential")
- `backoff_multiplier`: Multiplier for exponential backoff (default: 2.0)
- `max_delay_seconds`: Maximum delay cap (default: 3600)

### Backoff Strategies

#### Exponential Backoff

```
Attempt 1: 60 seconds
Attempt 2: 120 seconds (60 × 2)
Attempt 3: 240 seconds (120 × 2)
Attempt 4: 480 seconds (240 × 2)
Attempt 5: 960 seconds (480 × 2)
```

Capped at `max_delay_seconds` (3600s = 1 hour by default).

#### Fixed Delay

```
Attempt 1: 60 seconds
Attempt 2: 60 seconds
Attempt 3: 60 seconds
Attempt 4: 60 seconds
Attempt 5: 60 seconds
```

Constant delay between retries.

### Running the Retry Worker

#### Standalone Script

```bash
# Start retry worker
DATABASE_URL=postgresql://localhost/ruvon_edge \
python examples/edge_deployment/webhook_retry_daemon.py

# Custom scan interval (30 seconds)
python webhook_retry_daemon.py --scan-interval 30

# Custom concurrency (20 concurrent retries)
python webhook_retry_daemon.py --max-concurrent 20

# Both custom settings
python webhook_retry_daemon.py --scan-interval 30 --max-concurrent 20
```

**Output:**
```
======================================================================
  Webhook Retry Daemon
======================================================================

  Database:        postgresql://localhost/ruvon_edge
  Scan interval:   60s
  Max concurrent:  10

  Status: RUNNING
  Press Ctrl+C to stop

======================================================================

2026-02-06 12:00:00 - Webhook retry worker started (scan interval: 60s)
2026-02-06 12:00:00 - Scanning for failed webhook deliveries...
2026-02-06 12:00:00 - Found 3 failed deliveries
2026-02-06 12:00:00 - Retrying 3 deliveries...
2026-02-06 12:00:01 - Successfully retried delivery abc123
2026-02-06 12:00:01 - Successfully retried delivery def456
2026-02-06 12:00:02 - Failed to retry delivery ghi789: Connection timeout
2026-02-06 12:00:02 - Completed 3 retry attempts
```

#### Environment Variables

```bash
export DATABASE_URL=postgresql://localhost/ruvon_edge
export WEBHOOK_RETRY_SCAN_INTERVAL=60        # Scan every 60 seconds
export WEBHOOK_RETRY_MAX_CONCURRENT=10       # Max 10 concurrent retries

python webhook_retry_daemon.py
```

#### Systemd Service

**File:** `/etc/systemd/system/webhook-retry-daemon.service`

```ini
[Unit]
Description=Ruvon Webhook Retry Daemon
After=network.target postgresql.service

[Service]
Type=simple
User=ruvon
Environment="DATABASE_URL=postgresql://localhost/ruvon_edge"
Environment="WEBHOOK_RETRY_SCAN_INTERVAL=60"
Environment="WEBHOOK_RETRY_MAX_CONCURRENT=10"
ExecStart=/usr/bin/python3 /opt/ruvon/webhook_retry_daemon.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Commands:**
```bash
# Enable and start service
sudo systemctl enable webhook-retry-daemon
sudo systemctl start webhook-retry-daemon

# Check status
sudo systemctl status webhook-retry-daemon

# View logs
sudo journalctl -u webhook-retry-daemon -f

# Stop service
sudo systemctl stop webhook-retry-daemon
```

#### Docker Container

**Dockerfile:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/ src/
COPY examples/ examples/

CMD ["python", "examples/edge_deployment/webhook_retry_daemon.py"]
```

**Run:**
```bash
docker build -t webhook-retry-daemon .

docker run -d \
  --name webhook-retry-daemon \
  -e DATABASE_URL=postgresql://postgres:password@db:5432/ruvon_edge \
  -e WEBHOOK_RETRY_SCAN_INTERVAL=60 \
  -e WEBHOOK_RETRY_MAX_CONCURRENT=10 \
  --restart unless-stopped \
  webhook-retry-daemon
```

#### Docker Compose

```yaml
services:
  webhook-retry-daemon:
    build: .
    image: webhook-retry-daemon
    environment:
      - DATABASE_URL=postgresql://postgres:password@db:5432/ruvon_edge
      - WEBHOOK_RETRY_SCAN_INTERVAL=60
      - WEBHOOK_RETRY_MAX_CONCURRENT=10
    depends_on:
      - db
    restart: unless-stopped

  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=ruvon_edge
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

---

## Configuration Reference

### Worker Configuration

| Parameter | Environment Variable | Default | Description |
|-----------|---------------------|---------|-------------|
| Database URL | `DATABASE_URL` | Required | PostgreSQL or SQLite connection string |
| Scan Interval | `WEBHOOK_RETRY_SCAN_INTERVAL` | 60 | Seconds between scans for failed deliveries |
| Max Concurrent | `WEBHOOK_RETRY_MAX_CONCURRENT` | 10 | Maximum concurrent retry attempts |

### Retry Policy (Per-Webhook)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_retries` | 3 | Maximum retry attempts |
| `initial_delay_seconds` | 60 | Initial delay before first retry |
| `backoff_strategy` | exponential | "exponential" or "fixed" |
| `backoff_multiplier` | 2.0 | Multiplier for exponential backoff |
| `max_delay_seconds` | 3600 | Maximum delay cap (1 hour) |

---

## Monitoring and Logging

### Log Levels

```bash
# Set log level
export LOG_LEVEL=DEBUG  # DEBUG, INFO, WARNING, ERROR
```

### Log Output

```
2026-02-06 12:00:00 - Webhook retry worker started (scan interval: 60s)
2026-02-06 12:00:00 - Scanning for failed webhook deliveries...
2026-02-06 12:00:00 - Found 3 failed deliveries
2026-02-06 12:00:00 - Retrying delivery abc123 to https://example.com/webhook
2026-02-06 12:00:01 - Successfully retried delivery abc123
2026-02-06 12:00:01 - Delivery def456 not ready for retry (delay: 120s, attempt: 1)
2026-02-06 12:00:01 - Delivery ghi789 exceeded max retries (3)
```

### Metrics to Monitor

1. **Success Rate**: Percentage of successful retries
2. **Retry Queue Size**: Number of failed deliveries pending retry
3. **Average Retry Time**: Time from failure to successful delivery
4. **Exceeded Max Retries**: Count of deliveries that gave up

### Health Checks

```bash
# Check if worker is running
ps aux | grep webhook_retry_daemon

# Check last log entry
tail -n 1 /var/log/ruvon/webhook-retry-daemon.log

# Check failed deliveries count
psql -d ruvon_edge -c "SELECT COUNT(*) FROM webhook_deliveries WHERE status = 'failed'"
```

---

## Testing

### Test CLI Commands

```bash
# Start server
uvicorn ruvon_server.main:app --reload

# Test command versioning
python cloud_admin.py list-command-versions
python cloud_admin.py get-command-version restart 1.0.0
python cloud_admin.py validate-command restart 1.0.0 '{"delay_seconds": 10}'

# Test webhook management
python cloud_admin.py create-webhook '{
  "webhook_id": "test-webhook",
  "name": "Test",
  "url": "https://webhook.site/your-unique-url",
  "events": ["device.online"]
}'

python cloud_admin.py list-webhooks
python cloud_admin.py get-webhook test-webhook
python cloud_admin.py delete-webhook test-webhook
```

### Test Retry Worker

```bash
# Terminal 1: Start server
uvicorn ruvon_server.main:app --reload

# Terminal 2: Create webhook with unreachable URL (will fail)
curl -X POST http://localhost:8000/api/v1/webhooks \
  -H "Content-Type: application/json" \
  -d '{
    "webhook_id": "fail-test",
    "name": "Fail Test",
    "url": "http://localhost:9999/webhook",
    "events": ["device.online"],
    "retry_policy": {"max_retries": 3, "initial_delay_seconds": 10}
  }'

# Trigger event (will fail to deliver)
curl -X POST http://localhost:8000/api/v1/devices \
  -H "Content-Type: application/json" \
  -d '{"device_id": "test-123", ...}'

# Terminal 3: Start retry worker
DATABASE_URL=postgresql://localhost/ruvon_edge \
python webhook_retry_daemon.py --scan-interval 15

# Watch retry attempts in logs
```

---

## Troubleshooting

### Worker Not Starting

**Problem:** Worker fails to start

**Solution:**
```bash
# Check database connection
psql $DATABASE_URL -c "SELECT 1"

# Check Python dependencies
pip install -r requirements.txt

# Run with debug logging
LOG_LEVEL=DEBUG python webhook_retry_daemon.py
```

### No Retries Happening

**Problem:** Failed deliveries not being retried

**Solution:**
```bash
# Check if worker is running
ps aux | grep webhook_retry_daemon

# Check failed deliveries exist
psql -c "SELECT * FROM webhook_deliveries WHERE status = 'failed'"

# Check retry policy configured
psql -c "SELECT webhook_id, retry_policy FROM webhook_registrations"

# Verify webhook is active
psql -c "SELECT webhook_id, is_active FROM webhook_registrations"
```

### High Retry Latency

**Problem:** Retries taking too long

**Solution:**
```bash
# Reduce scan interval
python webhook_retry_daemon.py --scan-interval 30

# Increase concurrency
python webhook_retry_daemon.py --max-concurrent 20

# Reduce initial delay in retry policy
# Update webhook with shorter delay
```

---

## Performance Tuning

### Scan Interval Recommendations

| Workload | Scan Interval | Reason |
|----------|--------------|--------|
| **Low volume** (< 100 webhooks/hour) | 60s | Default, low overhead |
| **Medium volume** (100-1000/hour) | 30s | Balance responsiveness and load |
| **High volume** (> 1000/hour) | 15s | Fast retry for high throughput |
| **Critical alerts** | 10s | Minimize retry latency |

### Concurrency Recommendations

| Webhook Count | Max Concurrent | Reason |
|--------------|----------------|--------|
| **< 10 webhooks** | 5 | Low overhead |
| **10-50 webhooks** | 10 | Default, moderate load |
| **50-200 webhooks** | 20 | Higher throughput |
| **> 200 webhooks** | 50 | Maximum throughput |

### Database Optimization

```sql
-- Index for faster failed delivery queries
CREATE INDEX IF NOT EXISTS idx_webhook_delivery_failed
ON webhook_deliveries(status, created_at)
WHERE status = 'failed';

-- Index for webhook lookups
CREATE INDEX IF NOT EXISTS idx_webhook_active
ON webhook_registrations(is_active, webhook_id)
WHERE is_active = true;
```

---

## Best Practices

1. **Start Conservative**: Begin with default settings (60s scan, 10 concurrent)
2. **Monitor First**: Collect metrics for 24-48 hours before tuning
3. **Tune Gradually**: Adjust one parameter at a time
4. **Test Retry Policies**: Verify retry behavior with test webhooks
5. **Set Max Retries**: Don't retry forever (3-5 attempts recommended)
6. **Use Exponential Backoff**: Prevents thundering herd on webhook endpoints
7. **Monitor Logs**: Watch for patterns in failures
8. **Set Alerts**: Alert when retry queue grows beyond threshold
9. **Graceful Degradation**: Disable problematic webhooks instead of deleting

---

## Security Considerations

1. **Secure Database URL**: Use connection pooling, SSL/TLS
2. **Resource Limits**: Set max concurrent to prevent DoS
3. **Webhook Secrets**: Always configure HMAC secrets
4. **Endpoint Validation**: Verify webhook URLs before registration
5. **Rate Limiting**: Implement rate limits on webhook endpoints
6. **Audit Logging**: Log all retry attempts
7. **Graceful Shutdown**: Handle SIGTERM for clean worker shutdown

---

## Files Created/Modified

### Created
1. `src/ruvon_server/webhook_retry_worker.py` (~300 lines)
2. `examples/edge_deployment/webhook_retry_daemon.py` (~120 lines)
3. `CLI_AND_RETRY.md` (this file)

### Modified
1. `examples/edge_deployment/cloud_admin.py` (~600 lines added)
   - 4 command versioning CLI functions
   - 7 webhook management CLI functions
   - Command dispatch logic

---

## Summary

✅ **CLI Commands Implemented:** 11 total
- Command Versioning: 4 commands
- Webhook Management: 7 commands

✅ **Retry Mechanism Implemented:**
- Background worker with configurable scan interval
- Exponential and fixed backoff strategies
- Graceful shutdown
- Systemd and Docker deployment ready

✅ **Testing:**
- All CLI commands tested
- Retry worker tested with failed deliveries
- Documentation includes test procedures

✅ **Production Ready:**
- Systemd service configuration
- Docker deployment guide
- Performance tuning recommendations
- Security best practices
