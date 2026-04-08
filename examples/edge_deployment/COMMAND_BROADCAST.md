# Multi-Device Command Broadcast

## Overview

The Command Broadcast system enables fleet-wide command execution with progressive rollout and circuit breaker protection. Essential for managing thousands of fintech edge devices (POS terminals, ATMs, kiosks).

## Features

- **Fleet-Wide Targeting**: Send commands to devices by filters (region, type, merchant, status)
- **Progressive Rollout**: Canary deployments with configurable phases (10% → 50% → 100%)
- **Circuit Breaker**: Auto-pause if failure rate exceeds threshold
- **Broadcast Tracking**: Real-time progress monitoring
- **Cancellation**: Stop ongoing broadcasts
- **Link to Individual Commands**: Each broadcast creates individual device commands

## Use Cases

**Security Incident Response**:
```bash
# Emergency stop all devices
python cloud_admin.py broadcast-command '{"status": "online"}' emergency_stop '{"reason": "Security breach detected"}'
```

**Configuration Rollout**:
```bash
# Update floor limits for merchant with canary deployment
python cloud_admin.py broadcast-command \
  '{"merchant_id": "merchant-123", "status": "online"}' \
  update_config \
  '{"floor_limit": 100.00}' \
  '{"strategy": "canary", "phases": [0.1, 0.5, 1.0], "wait_seconds": 300, "circuit_breaker_threshold": 0.2}'
```

**Regional Maintenance**:
```bash
# Restart all devices in region during off-hours
python cloud_admin.py broadcast-command \
  '{"location": "us-east-1"}' \
  restart \
  '{"delay_seconds": 60}'
```

## Target Filters

### Simple Equality Filters

**By Device Type**:
```json
{
  "device_type": "macbook",
  "status": "online"
}
```

**By Merchant**:
```json
{
  "merchant_id": "merchant-123",
  "status": "online"
}
```

**By Location**:
```json
{
  "location": "us-east-1"
}
```

**Specific Devices**:
```json
{
  "device_id": ["device-001", "device-002", "device-003"]
}
```

### Advanced Filters

**Custom SQL WHERE Clause**:
```json
{
  "sql_where": "metadata->>'store_id' = 'store-456' AND firmware_version < '2.0.0'"
}
```

**Tags Matching**:
```json
{
  "tags": {
    "environment": "production",
    "tier": "premium"
  }
}
```

### Combined Filters

All filters are AND-combined:
```json
{
  "device_type": "macbook",
  "merchant_id": "merchant-123",
  "status": "online",
  "location": "us-west-2"
}
```

## Rollout Strategies

### All-at-Once (Default)

Send to all devices immediately:
```bash
python cloud_admin.py broadcast-command \
  '{"status": "online"}' \
  health_check
```

Rollout config (default):
```json
{
  "strategy": "all_at_once"
}
```

### Canary Deployment

Progressive rollout with phases:

**Example: 10% → 50% → 100%**
```bash
python cloud_admin.py broadcast-command \
  '{"device_type": "macbook"}' \
  restart \
  '{"delay_seconds": 10}' \
  '{
    "strategy": "canary",
    "phases": [0.1, 0.5, 1.0],
    "wait_seconds": 300,
    "circuit_breaker_threshold": 0.2,
    "auto_continue": true
  }'
```

**Rollout Phases**:
- Phase 1: 10% of devices (100 of 1000)
- Wait 5 minutes
- Phase 2: 50% of devices (500 of 1000)
- Wait 5 minutes
- Phase 3: 100% of devices (remaining 500)

**Circuit Breaker**:
- If failure rate > 20%, broadcast pauses
- Manual intervention required
- Prevents cascade failures

### Blue-Green Deployment

Deploy to groups sequentially:
```json
{
  "strategy": "blue_green",
  "wait_seconds": 600
}
```

## Broadcast Lifecycle

### 1. Creation

```
User creates broadcast
      ↓
POST /api/v1/broadcasts
      ↓
BroadcastService.create_broadcast()
      ↓
Target devices identified via filter
      ↓
Broadcast record created
      ↓
Execution starts immediately
```

### 2. Execution

**All-at-Once**:
```
Create command for each device
      ↓
Link to broadcast_id
      ↓
Devices pick up via heartbeat
      ↓
Execute commands
      ↓
Report status back
```

**Progressive Rollout**:
```
Phase 1: Send to 10% of devices
      ↓
Wait for completion or timeout
      ↓
Check circuit breaker (failure rate < threshold?)
      ↓
Phase 2: Send to next 40% of devices
      ↓
Wait for completion or timeout
      ↓
Check circuit breaker
      ↓
Phase 3: Send to remaining 50%
      ↓
Mark broadcast as completed
```

### 3. Monitoring

```
GET /api/v1/broadcasts/{id}
      ↓
Returns BroadcastProgress:
  - total_devices
  - completed_devices
  - failed_devices
  - success_rate
  - failure_rate
  - current_phase
```

### 4. Completion

**Success**:
```
All devices completed
      ↓
status = "completed"
      ↓
completed_at = NOW()
```

**Circuit Breaker Triggered**:
```
Failure rate > threshold
      ↓
status = "paused"
      ↓
error_message = "Circuit breaker triggered"
      ↓
Manual intervention required
```

**Cancelled**:
```
User cancels broadcast
      ↓
status = "cancelled"
      ↓
Pending commands marked as cancelled
```

## API Reference

### Create Broadcast

```
POST /api/v1/broadcasts
```

**Request**:
```json
{
  "command_type": "update_config",
  "command_data": {
    "floor_limit": 50.00
  },
  "target_filter": {
    "merchant_id": "merchant-123",
    "status": "online"
  },
  "rollout_config": {
    "strategy": "canary",
    "phases": [0.1, 0.5, 1.0],
    "wait_seconds": 300,
    "circuit_breaker_threshold": 0.2
  }
}
```

**Response**:
```json
{
  "broadcast_id": "broadcast-abc123...",
  "status": "created",
  "message": "Broadcast created and execution started"
}
```

### Get Broadcast Status

```
GET /api/v1/broadcasts/{broadcast_id}
```

**Response**:
```json
{
  "broadcast_id": "broadcast-abc123...",
  "status": "in_progress",
  "command_type": "update_config",
  "total_devices": 1000,
  "pending_devices": 400,
  "in_progress_devices": 100,
  "completed_devices": 450,
  "failed_devices": 50,
  "current_phase": 2,
  "total_phases": 3,
  "failure_rate": 0.05,
  "success_rate": 0.45,
  "created_at": "2026-02-03T20:00:00Z",
  "started_at": "2026-02-03T20:00:05Z",
  "next_phase_at": "2026-02-03T20:10:00Z"
}
```

### List Broadcasts

```
GET /api/v1/broadcasts?status=in_progress&limit=50
```

**Response**:
```json
{
  "total": 3,
  "broadcasts": [
    {
      "broadcast_id": "broadcast-abc123...",
      "command_type": "update_config",
      "status": "in_progress",
      "total_devices": 1000,
      "completed_devices": 450,
      "failed_devices": 50,
      "created_at": "2026-02-03T20:00:00Z"
    }
  ]
}
```

### Cancel Broadcast

```
DELETE /api/v1/broadcasts/{broadcast_id}
```

**Response**:
```json
{
  "broadcast_id": "broadcast-abc123...",
  "status": "cancelled",
  "message": "Broadcast cancelled successfully"
}
```

## CLI Usage

### Basic Broadcast

```bash
# All online devices
python cloud_admin.py broadcast-command '{"status": "online"}' health_check

# All devices in merchant
python cloud_admin.py broadcast-command '{"merchant_id": "merchant-123"}' sync_now

# Specific device types
python cloud_admin.py broadcast-command '{"device_type": "macbook"}' clear_cache
```

### With Data

```bash
python cloud_admin.py broadcast-command \
  '{"status": "online"}' \
  update_config \
  '{"floor_limit": 100.00, "max_offline_transactions": 200}'
```

### Progressive Rollout

```bash
python cloud_admin.py broadcast-command \
  '{"merchant_id": "merchant-123"}' \
  restart \
  '{"delay_seconds": 60}' \
  '{"strategy": "canary", "phases": [0.1, 0.5, 1.0], "wait_seconds": 600, "circuit_breaker_threshold": 0.15}'
```

### Check Status

```bash
python cloud_admin.py broadcast-status broadcast-abc123
```

### List Broadcasts

```bash
# All broadcasts
python cloud_admin.py list-broadcasts

# Filter by status
python cloud_admin.py list-broadcasts in_progress
python cloud_admin.py list-broadcasts completed
```

### Cancel Broadcast

```bash
python cloud_admin.py cancel-broadcast broadcast-abc123
```

## Monitoring

### Broadcast Progress Queries

**Active Broadcasts**:
```sql
SELECT
    broadcast_id,
    command_type,
    status,
    total_devices,
    completed_devices,
    failed_devices,
    ROUND(completed_devices::numeric / total_devices * 100, 1) as progress_pct,
    ROUND(failed_devices::numeric / total_devices * 100, 1) as failure_pct
FROM command_broadcasts
WHERE status IN ('pending', 'in_progress')
ORDER BY created_at DESC;
```

**Broadcast Success Rate**:
```sql
SELECT
    broadcast_id,
    command_type,
    total_devices,
    completed_devices,
    failed_devices,
    ROUND(completed_devices::numeric / NULLIF(completed_devices + failed_devices, 0) * 100, 1) as success_rate
FROM command_broadcasts
WHERE status = 'completed'
ORDER BY created_at DESC
LIMIT 10;
```

**Circuit Breaker Triggers**:
```sql
SELECT
    broadcast_id,
    command_type,
    total_devices,
    failed_devices,
    error_message,
    created_at
FROM command_broadcasts
WHERE status = 'paused'
ORDER BY created_at DESC;
```

### Device Command Distribution

**Commands by Broadcast**:
```sql
SELECT
    broadcast_id,
    COUNT(*) as total_commands,
    COUNT(*) FILTER (WHERE status = 'completed') as completed,
    COUNT(*) FILTER (WHERE status = 'failed') as failed,
    COUNT(*) FILTER (WHERE status = 'pending') as pending
FROM device_commands
WHERE broadcast_id IS NOT NULL
GROUP BY broadcast_id
ORDER BY broadcast_id DESC;
```

## Best Practices

### Target Filtering

**Always filter by status**:
```json
{
  "merchant_id": "merchant-123",
  "status": "online"  // Ensures only active devices receive commands
}
```

**Test on small subset first**:
```json
{
  "device_id": ["test-device-001", "test-device-002"]
}
```

### Rollout Configuration

**Start conservative**:
- Phase 1: 5-10% (canary)
- Phase 2: 25-50% (validation)
- Phase 3: 100% (full rollout)

**Circuit breaker thresholds**:
- **Conservative**: 0.05 (5% failure rate)
- **Standard**: 0.10 (10% failure rate)
- **Aggressive**: 0.20 (20% failure rate)

**Wait times**:
- **Quick operations** (health_check): 60-120 seconds
- **Config updates**: 300-600 seconds (5-10 minutes)
- **Restarts**: 600-1800 seconds (10-30 minutes)

### Safety

**Critical commands**:
- Use progressive rollout
- Set low circuit breaker threshold
- Monitor actively
- Have rollback plan

**Emergency broadcasts**:
```bash
# Security lockdown - all-at-once is acceptable
python cloud_admin.py broadcast-command \
  '{"status": "online"}' \
  security_lockdown \
  '{"reason": "Security incident"}'
```

## Troubleshooting

### Broadcast Stuck in "pending"

**Check target filter**:
```sql
SELECT COUNT(*) FROM edge_devices WHERE status = 'online';
```

**Verify devices match filter**:
```sql
-- Example for merchant filter
SELECT device_id FROM edge_devices
WHERE merchant_id = 'merchant-123' AND status = 'online';
```

### High Failure Rate

**Identify failed devices**:
```sql
SELECT
    device_id,
    command_type,
    error_message
FROM device_commands
WHERE broadcast_id = 'broadcast-abc123'
  AND status = 'failed'
ORDER BY completed_at DESC;
```

**Common failure patterns**:
- Network timeouts → Check device connectivity
- Permission errors → Check command requires root
- Invalid data → Validate command_data schema

### Circuit Breaker Triggered

**Review failure details**:
```bash
python cloud_admin.py broadcast-status broadcast-abc123
```

**Options**:
1. **Fix issue** and create new broadcast
2. **Adjust threshold** and retry
3. **Target remaining devices** manually

### Broadcast Not Progressing

**Check BroadcastService**:
```bash
# Verify service is running
ps aux | grep broadcast

# Check logs
tail -f /var/log/ruvon/broadcast.log
```

## Database Schema

```sql
CREATE TABLE command_broadcasts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    broadcast_id VARCHAR(100) UNIQUE NOT NULL,
    command_type VARCHAR(100) NOT NULL,
    command_data TEXT DEFAULT '{}',
    target_filter JSONB NOT NULL,
    rollout_config JSONB DEFAULT NULL,
    created_by VARCHAR(100),
    status VARCHAR(50) DEFAULT 'pending',
    total_devices INT DEFAULT 0,
    completed_devices INT DEFAULT 0,
    failed_devices INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    error_message TEXT
);

-- Link device commands to broadcasts
ALTER TABLE device_commands
ADD COLUMN broadcast_id VARCHAR(100) REFERENCES command_broadcasts(broadcast_id);
```

## Migration

```bash
psql -U ruvon -d ruvon < docker/migrations/add_command_broadcast_support.sql
```

## Performance Considerations

- **Batch size**: Creates commands in batches of 1000
- **Indexes**: Ensure `idx_device_command_broadcast` exists
- **Rollout delays**: Use `wait_seconds` to avoid overwhelming network
- **Circuit breaker**: Prevents cascade failures

## Security Considerations

- **Authentication**: Broadcasts require authenticated user
- **Authorization**: Role-based access control for critical commands
- **Audit logging**: All broadcasts logged with creator
- **Target validation**: Filters validated before execution
- **Cancellation**: Only creator or admin can cancel
