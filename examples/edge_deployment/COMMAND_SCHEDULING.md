## Command Scheduling

One-time and recurring command execution with cron-style scheduling for Rufus Edge devices.

## Overview

Command Scheduling enables **time-based execution** of commands to devices or fleets. Schedule commands for specific future times or set up recurring executions using cron expressions.

### Key Features

- **One-Time Schedules**: Execute commands at a specific future time
- **Recurring Schedules**: Cron-style periodic execution
- **Maintenance Windows**: Restrict execution to specific time ranges
- **Fleet Scheduling**: Schedule commands across multiple devices
- **Execution Tracking**: View history of all schedule executions
- **Pause/Resume**: Temporarily pause and resume schedules
- **Timezone Support**: Schedule in device-local or UTC time
- **Retry Integration**: Apply retry policies to scheduled commands

### Use Cases

| Use Case | Schedule Type | Cron Expression |
|----------|--------------|-----------------|
| **Nightly Maintenance** | Recurring | `0 2 * * *` (Daily at 2 AM) |
| **Weekly Reports** | Recurring | `0 9 * * 1` (Mondays at 9 AM) |
| **Monthly Cleanup** | Recurring | `0 3 1 * *` (1st of month at 3 AM) |
| **Planned Restart** | One-Time | - (Specific datetime) |
| **Off-Peak Updates** | Recurring | `0 22 * * *` (Daily at 10 PM) |
| **Business Hours Check** | Recurring | `0 9-17 * * 1-5` (Weekdays, hourly) |

---

## Architecture

### Schedule Types

**1. One-Time Schedule**
- Executes once at a specific datetime
- Status changes to `completed` after execution
- No need for cron expression

**2. Recurring Schedule**
- Executes on cron schedule
- Continues until max_executions reached or manually cancelled
- Requires valid cron expression

### Schedule Lifecycle

```
Created → Active → [Executing] → Active (recurring) OR Completed (one-time)
   ↓         ↓                           ↓
Paused → Active                      Expired
   ↓
Cancelled
```

**Status Transitions**:
- `active` → `paused`: User pauses schedule
- `paused` → `active`: User resumes schedule
- `active` → `completed`: One-time executed OR max_executions reached
- `active` → `expired`: Past expires_at timestamp
- `active/paused` → `cancelled`: User cancels schedule

### Maintenance Windows

Restrict command execution to specific time ranges (e.g., 2 AM - 6 AM):

```
Cron: 0 * * * *  (Every hour)
Window: 02:00 - 06:00

Executions:
- 00:00 → Skipped (outside window)
- 01:00 → Skipped
- 02:00 → Execute ✓
- 03:00 → Execute ✓
- 04:00 → Execute ✓
- 05:00 → Execute ✓
- 06:00 → Execute ✓
- 07:00 → Skipped
```

If cron time falls outside window, execution moves to window start.

---

## Database Schema

### `command_schedules` Table

```sql
CREATE TABLE command_schedules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    schedule_id VARCHAR(100) UNIQUE NOT NULL,
    schedule_name VARCHAR(200),
    device_id VARCHAR(100) REFERENCES edge_devices(device_id),
    target_filter JSONB DEFAULT NULL,
    command_type VARCHAR(100) NOT NULL,
    command_data TEXT DEFAULT '{}',

    -- Scheduling configuration
    schedule_type VARCHAR(50) NOT NULL,  -- one_time, recurring
    execute_at TIMESTAMPTZ,  -- For one-time
    cron_expression VARCHAR(100),  -- For recurring
    timezone VARCHAR(50) DEFAULT 'UTC',

    -- Execution tracking
    status VARCHAR(50) DEFAULT 'active',
    next_execution_at TIMESTAMPTZ,
    last_execution_at TIMESTAMPTZ,
    execution_count INT DEFAULT 0,
    max_executions INT DEFAULT NULL,

    -- Maintenance window
    maintenance_window_start TIME,
    maintenance_window_end TIME,

    -- Metadata
    created_by VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    error_message TEXT,
    retry_policy JSONB DEFAULT NULL
);
```

### `schedule_executions` Table

Tracks individual executions of scheduled commands:

```sql
CREATE TABLE schedule_executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    schedule_id VARCHAR(100) NOT NULL REFERENCES command_schedules(schedule_id),
    execution_number INT NOT NULL,
    scheduled_for TIMESTAMPTZ NOT NULL,
    executed_at TIMESTAMPTZ,
    status VARCHAR(50) DEFAULT 'pending',
    command_id VARCHAR(100),  -- Reference to created command
    broadcast_id VARCHAR(100),  -- Reference to broadcast (for fleet)
    result_summary TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## API Reference

### Create One-Time Schedule

**Endpoint**: `POST /api/v1/schedules`

**Request Body** (One-Time):
```json
{
  "schedule_name": "Maintenance restart",
  "device_id": "macbook-m4-001",
  "command_type": "restart",
  "command_data": {"delay_seconds": 10},
  "schedule_type": "one_time",
  "execute_at": "2026-02-05T02:00:00Z"
}
```

**Response**:
```json
{
  "schedule_id": "770e8400-e29b-41d4-a716-446655440000",
  "status": "created",
  "message": "Schedule created successfully"
}
```

### Create Recurring Schedule

**Request Body** (Recurring with Maintenance Window):
```json
{
  "schedule_name": "Daily health check",
  "device_id": "pos-terminal-042",
  "command_type": "health_check",
  "command_data": {},
  "schedule_type": "recurring",
  "cron_expression": "0 2 * * *",
  "timezone": "America/New_York",
  "maintenance_window_start": "02:00:00",
  "maintenance_window_end": "06:00:00",
  "max_executions": 365
}
```

### Create Fleet Recurring Schedule

**Request Body** (Fleet):
```json
{
  "schedule_name": "Weekly cache clear",
  "target_filter": {
    "device_type": "macbook",
    "status": "online"
  },
  "command_type": "clear_cache",
  "command_data": {},
  "schedule_type": "recurring",
  "cron_expression": "0 3 * * 0",
  "max_executions": 52
}
```

### Get Schedule Status

**Endpoint**: `GET /api/v1/schedules/{schedule_id}`

**Response**:
```json
{
  "schedule_id": "770e8400-e29b-41d4-a716-446655440000",
  "schedule_name": "Daily health check",
  "device_id": "pos-terminal-042",
  "target_filter": null,
  "command_type": "health_check",
  "schedule_type": "recurring",
  "status": "active",
  "execution_count": 15,
  "max_executions": 365,
  "next_execution_at": "2026-02-05T02:00:00Z",
  "last_execution_at": "2026-02-04T02:00:00Z",
  "cron_expression": "0 2 * * *",
  "timezone": "America/New_York",
  "created_at": "2026-01-20T10:00:00Z",
  "updated_at": "2026-02-04T02:01:00Z",
  "expires_at": null,
  "recent_executions": [
    {
      "execution_number": 15,
      "scheduled_for": "2026-02-04T02:00:00Z",
      "executed_at": "2026-02-04T02:00:05Z",
      "status": "completed",
      "command_id": "cmd-abc-123",
      "broadcast_id": null,
      "result_summary": null,
      "error_message": null
    }
  ],
  "error_message": null
}
```

### List Schedules

**Endpoint**: `GET /api/v1/schedules`

**Query Parameters**:
- `device_id` (optional): Filter by device
- `status` (optional): Filter by status (active, paused, completed, cancelled, expired)
- `schedule_type` (optional): Filter by type (one_time, recurring)
- `limit` (optional): Max results (default: 50)

**Response**:
```json
{
  "schedules": [
    {
      "schedule_id": "770e8400-e29b-41d4-a716-446655440000",
      "schedule_name": "Daily health check",
      "device_id": "pos-terminal-042",
      "command_type": "health_check",
      "schedule_type": "recurring",
      "status": "active",
      "execution_count": 15,
      "max_executions": 365,
      "next_execution_at": "2026-02-05T02:00:00Z",
      "last_execution_at": "2026-02-04T02:00:00Z",
      "created_at": "2026-01-20T10:00:00Z"
    }
  ],
  "count": 1
}
```

### Pause Schedule

**Endpoint**: `POST /api/v1/schedules/{schedule_id}/pause`

**Response**:
```json
{
  "schedule_id": "770e8400-e29b-41d4-a716-446655440000",
  "status": "paused",
  "message": "Schedule paused successfully"
}
```

### Resume Schedule

**Endpoint**: `POST /api/v1/schedules/{schedule_id}/resume`

**Response**:
```json
{
  "schedule_id": "770e8400-e29b-41d4-a716-446655440000",
  "status": "active",
  "message": "Schedule resumed successfully"
}
```

### Cancel Schedule

**Endpoint**: `DELETE /api/v1/schedules/{schedule_id}`

**Response**:
```json
{
  "schedule_id": "770e8400-e29b-41d4-a716-446655440000",
  "status": "cancelled",
  "message": "Schedule cancelled successfully"
}
```

---

## CLI Usage

### Create One-Time Schedule

```bash
python cloud_admin.py create-schedule \
  '{"schedule_name":"Restart","device_id":"macbook-m4-001","command_type":"restart","command_data":{"delay_seconds":10},"schedule_type":"one_time","execute_at":"2026-02-05T02:00:00Z"}'

# Output:
# ✓ Schedule created successfully
#   Schedule ID: 770e8400-e29b-41d4-a716-446655440000
#   Status: created
```

### Create Recurring Schedule

```bash
python cloud_admin.py create-schedule \
  '{"schedule_name":"Daily health check","device_id":"pos-terminal-042","command_type":"health_check","command_data":{},"schedule_type":"recurring","cron_expression":"0 2 * * *","timezone":"UTC"}'

# Output:
# ✓ Schedule created successfully
#   Schedule ID: 880e8400-e29b-41d4-a716-446655440001
#   Status: created
```

### Create Fleet Recurring Schedule

```bash
python cloud_admin.py create-schedule \
  '{"schedule_name":"Weekly cache clear","target_filter":{"device_type":"macbook","status":"online"},"command_type":"clear_cache","command_data":{},"schedule_type":"recurring","cron_expression":"0 3 * * 0","max_executions":52}'

# Output:
# ✓ Schedule created successfully
#   Schedule ID: 990e8400-e29b-41d4-a716-446655440002
#   Status: created
```

### Check Schedule Status

```bash
python cloud_admin.py schedule-status 770e8400-e29b-41d4-a716-446655440000

# Output:
# Schedule: 770e8400-e29b-41d4-a716-446655440000
#   Name: Daily health check
#   Device: pos-terminal-042
#   Command: health_check
#   Type: recurring
#   Status: active
#   Execution Count: 15
#   Max Executions: 365
#   Next Execution: 2026-02-05T02:00:00Z
#   Last Execution: 2026-02-04T02:00:00Z
#   Cron: 0 2 * * *
#   Timezone: UTC
#   Created: 2026-01-20T10:00:00Z
#
#   Recent Executions:
#     ✓ #15 - completed
#        Scheduled: 2026-02-04T02:00:00Z
#        Executed: 2026-02-04T02:00:05Z
#     ✓ #14 - completed
#        Scheduled: 2026-02-03T02:00:00Z
#        Executed: 2026-02-03T02:00:03Z
```

### List Schedules

```bash
# List all schedules
python cloud_admin.py list-schedules

# Filter by device
python cloud_admin.py list-schedules macbook-m4-001

# Filter by status
python cloud_admin.py list-schedules "" active

# Filter by schedule type
python cloud_admin.py list-schedules "" "" recurring

# Output:
# Found 3 schedule(s):
#
# ✓ 770e8400... - Daily health check
#   Device: pos-terminal-042
#   Type: recurring | Status: active
#   Executions: 15/365
#   Next: 2026-02-05T02:00:00Z
#
# ⏸ 880e8400... - Weekly restart
#   Device: macbook-m4-001
#   Type: recurring | Status: paused
#   Executions: 8/∞
#   Next: 2026-02-08T03:00:00Z
```

### Pause Schedule

```bash
python cloud_admin.py pause-schedule 770e8400-e29b-41d4-a716-446655440000

# Output:
# ✓ Schedule paused
#   Schedule ID: 770e8400-e29b-41d4-a716-446655440000
#   Status: paused
```

### Resume Schedule

```bash
python cloud_admin.py resume-schedule 770e8400-e29b-41d4-a716-446655440000

# Output:
# ✓ Schedule resumed
#   Schedule ID: 770e8400-e29b-41d4-a716-446655440000
#   Status: active
```

### Cancel Schedule

```bash
python cloud_admin.py cancel-schedule 770e8400-e29b-41d4-a716-446655440000

# Output:
# ✓ Schedule cancelled
#   Schedule ID: 770e8400-e29b-41d4-a716-446655440000
#   Status: cancelled
```

---

## Cron Expression Guide

Cron expressions define recurring schedules using 5 fields:

```
┌───────────── minute (0 - 59)
│ ┌───────────── hour (0 - 23)
│ │ ┌───────────── day of month (1 - 31)
│ │ │ ┌───────────── month (1 - 12)
│ │ │ │ ┌───────────── day of week (0 - 6) (Sunday=0)
│ │ │ │ │
* * * * *
```

### Common Patterns

| Expression | Description |
|------------|-------------|
| `0 2 * * *` | Daily at 2 AM |
| `30 3 * * *` | Daily at 3:30 AM |
| `0 */6 * * *` | Every 6 hours |
| `0 9-17 * * *` | Every hour from 9 AM to 5 PM |
| `0 9 * * 1-5` | Weekdays at 9 AM |
| `0 0 * * 0` | Sundays at midnight |
| `0 0 1 * *` | First day of each month at midnight |
| `0 0 1 1 *` | January 1st at midnight |
| `*/15 * * * *` | Every 15 minutes |
| `0 22 * * 1,3,5` | Mondays, Wednesdays, Fridays at 10 PM |

### Special Characters

- `*`: Any value (every minute, hour, day, etc.)
- `,`: List separator (`1,3,5` = 1st, 3rd, 5th)
- `-`: Range (`1-5` = 1, 2, 3, 4, 5)
- `/`: Step values (`*/10` = every 10 units)

---

## Scheduler Daemon

The scheduler daemon runs in the background and processes due schedules.

### Running the Daemon

**As a Service**:
```bash
python -m rufus_server.scheduler_daemon \
  --db-url postgresql://user:pass@localhost/rufus \
  --interval 60

# Output:
# [INFO] Starting scheduler daemon (check interval: 60s)
# [INFO] Processed 3 scheduled commands (failed: 0, skipped: 0)
```

**Run Once** (Testing):
```bash
python -m rufus_server.scheduler_daemon \
  --db-url postgresql://user:pass@localhost/rufus \
  --run-once

# Output:
# [INFO] Running scheduler once...
# [INFO] Processed 5 schedules
```

### Daemon Configuration

- `--db-url`: PostgreSQL connection URL
- `--interval`: Check interval in seconds (default: 60)
- `--run-once`: Run once and exit (for testing/cron)

### Production Deployment

**Systemd Service**:
```ini
[Unit]
Description=Rufus Command Scheduler
After=network.target postgresql.service

[Service]
Type=simple
ExecStart=/usr/bin/python -m rufus_server.scheduler_daemon \
  --db-url postgresql://localhost/rufus \
  --interval 60
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Docker Compose**:
```yaml
scheduler:
  image: myapp/rufus:latest
  command: python -m rufus_server.scheduler_daemon --db-url postgresql://postgres/rufus --interval 60
  restart: always
  depends_on:
    - postgres
```

**Kubernetes Deployment**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rufus-scheduler
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: scheduler
        image: myapp/rufus:latest
        command:
        - python
        - -m
        - rufus_server.scheduler_daemon
        - --db-url
        - postgresql://postgres/rufus
        - --interval
        - "60"
```

---

## Common Patterns

### 1. Nightly Maintenance

Schedule daily maintenance during off-peak hours:

```json
{
  "schedule_name": "Nightly maintenance",
  "device_id": "pos-terminal-042",
  "command_type": "maintenance_cycle",
  "command_data": {},
  "schedule_type": "recurring",
  "cron_expression": "0 2 * * *",
  "timezone": "America/New_York",
  "maintenance_window_start": "02:00:00",
  "maintenance_window_end": "06:00:00"
}
```

### 2. Business Hours Health Checks

Check device health every hour during business hours:

```json
{
  "schedule_name": "Business hours health check",
  "target_filter": {"device_type": "pos", "status": "online"},
  "command_type": "health_check",
  "command_data": {},
  "schedule_type": "recurring",
  "cron_expression": "0 9-17 * * 1-5",
  "timezone": "America/New_York"
}
```

### 3. Weekly Cache Clear

Clear cache on all devices every Sunday morning:

```json
{
  "schedule_name": "Weekly cache clear",
  "target_filter": {"status": "online"},
  "command_type": "clear_cache",
  "command_data": {},
  "schedule_type": "recurring",
  "cron_expression": "0 3 * * 0"
}
```

### 4. Planned Update

Schedule a one-time firmware update for next maintenance window:

```json
{
  "schedule_name": "Firmware update v2.5.0",
  "device_id": "macbook-m4-001",
  "command_type": "update_firmware",
  "command_data": {"version": "2.5.0"},
  "schedule_type": "one_time",
  "execute_at": "2026-02-15T02:00:00Z"
}
```

### 5. Monthly Report

Generate device report on the first day of each month:

```json
{
  "schedule_name": "Monthly device report",
  "target_filter": {"device_type": "pos"},
  "command_type": "generate_report",
  "command_data": {"report_type": "monthly"},
  "schedule_type": "recurring",
  "cron_expression": "0 0 1 * *"
}
```

---

## Best Practices

### Scheduling Strategy

**Use One-Time for**:
- Planned maintenance events
- Specific update rollouts
- Time-sensitive operations
- Testing new commands

**Use Recurring for**:
- Regular maintenance
- Health checks
- Cache clearing
- Backup operations
- Report generation

### Maintenance Windows

Always use maintenance windows for disruptive operations:
- Restarts
- Firmware updates
- Database migrations
- Cache clearing
- Configuration changes

**Example Window Times** (2 AM - 6 AM local time):
```json
{
  "maintenance_window_start": "02:00:00",
  "maintenance_window_end": "06:00:00",
  "timezone": "America/New_York"
}
```

### Execution Limits

Set `max_executions` for:
- Limited-time campaigns
- Trial periods
- Testing new schedules
- Preventing runaway schedules

```json
{
  "max_executions": 30,  // Run for 30 days
  "cron_expression": "0 2 * * *"
}
```

### Timezone Considerations

**Use UTC for**:
- Global fleets (consistent timing)
- Server-side operations
- Avoiding DST issues

**Use Local Timezone for**:
- Business hours operations
- User-facing actions
- Region-specific schedules

### Error Handling

Combine schedules with retry policies:

```json
{
  "command_type": "health_check",
  "schedule_type": "recurring",
  "cron_expression": "0 * * * *",
  "retry_policy": {
    "max_retries": 3,
    "initial_delay_seconds": 60,
    "backoff_strategy": "exponential"
  }
}
```

### Monitoring

Track these metrics:
- **Schedule success rate**: Successful executions / total executions
- **Execution latency**: Time between scheduled_for and executed_at
- **Failed schedules**: Schedules with recent failures
- **Paused schedules**: Schedules manually paused (may be forgotten)

---

## Troubleshooting

### Schedule Not Executing

**1. Check scheduler daemon is running**:
```bash
# Check if daemon is processing schedules
tail -f /var/log/rufus/scheduler.log
```

**2. Verify schedule status**:
```bash
python cloud_admin.py schedule-status <schedule-id>

# Look for:
# - Status should be "active" (not paused/cancelled)
# - next_execution_at should be in the future
# - No error_message
```

**3. Check maintenance window**:
- If execution time falls outside maintenance window, it will be moved
- Verify maintenance_window_start and maintenance_window_end

**4. Verify cron expression**:
```python
from croniter import croniter
from datetime import datetime

cron = croniter("0 2 * * *", datetime.utcnow())
print(cron.get_next(datetime))  # Next execution time
```

### Executions Failing

**1. Check execution history**:
```bash
python cloud_admin.py schedule-status <schedule-id>

# Look for error_message in recent_executions
```

**2. Verify command validity**:
- Test command manually first
- Check command_data is valid JSON
- Verify device_id or target_filter

**3. Check retry policy**:
- Add retry policy for transient failures
- Increase max_retries for flaky commands

### Timezone Issues

**1. Verify timezone string**:
- Use standard IANA timezone names (e.g., "America/New_York")
- Not abbreviations (EST/PST)

**2. Check DST transitions**:
- Schedules may execute at different UTC times during DST
- Use UTC for consistent timing

---

## Integration with Other Features

### With Command Retries

Scheduled commands automatically use retry policies:

```json
{
  "command_type": "sync_now",
  "schedule_type": "recurring",
  "cron_expression": "0 * * * *",
  "retry_policy": {
    "max_retries": 5,
    "initial_delay_seconds": 60,
    "backoff_strategy": "exponential"
  }
}
```

### With Broadcasts

Schedule fleet-wide commands:

```json
{
  "schedule_name": "Weekly fleet health check",
  "target_filter": {"status": "online"},
  "command_type": "health_check",
  "schedule_type": "recurring",
  "cron_expression": "0 3 * * 0"
}
```

### With Templates

Coming soon: Schedule template execution:

```bash
# Future enhancement
python cloud_admin.py schedule-template \
  maintenance-cycle \
  --device-id macbook-m4-001 \
  --cron "0 2 * * *"
```

---

## Related Documentation

- [COMMAND_SYSTEM.md](./COMMAND_SYSTEM.md) - Command architecture overview
- [COMMAND_RETRIES.md](./COMMAND_RETRIES.md) - Retry policies for failed commands
- [COMMAND_BROADCASTS.md](./COMMAND_BROADCASTS.md) - Multi-device fleet commands
- [COMMAND_BATCHING.md](./COMMAND_BATCHING.md) - Atomic multi-command operations

---

## Summary

Command Scheduling provides **time-based command execution** with flexible scheduling options:

- ✅ One-time schedules for planned events
- ✅ Recurring schedules with cron expressions
- ✅ Maintenance windows for off-peak execution
- ✅ Fleet scheduling for multi-device operations
- ✅ Execution history and tracking
- ✅ Pause/resume/cancel controls
- ✅ Timezone support
- ✅ Integration with retries and broadcasts
- ✅ Background scheduler daemon

Next: Implement Command Audit Log for compliance tracking.
