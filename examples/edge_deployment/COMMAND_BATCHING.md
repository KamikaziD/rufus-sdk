# Command Batching

Atomic multi-command operations for Rufus Edge devices.

## Overview

Command Batching enables **atomic execution** of multiple commands to a single device. All commands in a batch are grouped together and executed according to a specified mode (sequential or parallel). This ensures complex multi-step operations complete as a unit.

### Key Features

- **Atomic Operations**: All commands succeed together or fail together
- **Sequential Execution**: Commands execute in order, waiting for each to complete
- **Parallel Execution**: Commands execute simultaneously for maximum speed
- **Progress Tracking**: Real-time visibility into batch execution status
- **Failure Isolation**: Individual command failures tracked separately
- **Cancellation Support**: Cancel pending batches before execution

### Use Cases

| Use Case | Execution Mode | Commands |
|----------|---------------|----------|
| **Device Maintenance** | Sequential | 1. Clear cache → 2. Sync state → 3. Restart |
| **Configuration Update** | Sequential | 1. Backup config → 2. Apply new config → 3. Validate |
| **Health Diagnostics** | Parallel | 1. Check network + 2. Check storage + 3. Check firmware |
| **Emergency Response** | Sequential | 1. Suspend transactions → 2. Lock device → 3. Alert admin |
| **Bulk Operations** | Parallel | 1. Update policy + 2. Sync data + 3. Clear cache |

---

## Architecture

### Sequential Mode

Commands execute **one at a time** in the specified order. Each command must complete before the next begins.

```
[Command 1] → Complete → [Command 2] → Complete → [Command 3]
   10s           ✓          15s           ✓          5s
```

**Sequence Validation**:
- Commands must have consecutive sequence numbers starting from 1
- No gaps allowed (1, 2, 3, ... N)
- No duplicates allowed
- Auto-assigned if not specified

**Failure Behavior**:
- Batch status becomes `failed`
- Remaining commands **not executed**
- Failed command error recorded
- Batch marked as incomplete

### Parallel Mode

Commands execute **simultaneously** for maximum speed.

```
[Command 1] ─┐
[Command 2] ─┼─→ All execute at once → Batch completes
[Command 3] ─┘
```

**Failure Behavior**:
- Batch continues executing all commands
- Batch status becomes `failed` if ANY command fails
- All failures recorded separately
- `allow_partial_success` flag could be added in future

---

## Database Schema

### `command_batches` Table

```sql
CREATE TABLE command_batches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    batch_id VARCHAR(100) UNIQUE NOT NULL,
    device_id VARCHAR(100) NOT NULL REFERENCES edge_devices(device_id),
    execution_mode VARCHAR(50) DEFAULT 'sequential',
    status VARCHAR(50) DEFAULT 'pending',
    total_commands INT DEFAULT 0,
    completed_commands INT DEFAULT 0,
    failed_commands INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT
);
```

### `device_commands` Table (Extended)

```sql
ALTER TABLE device_commands
ADD COLUMN batch_id VARCHAR(100) REFERENCES command_batches(batch_id),
ADD COLUMN batch_sequence INT DEFAULT NULL;
```

**Batch Linking**:
- Commands with non-null `batch_id` are part of a batch
- `batch_sequence` determines execution order (sequential mode)
- Cascade delete when batch is deleted

---

## API Reference

### Create Batch

**Endpoint**: `POST /api/v1/batches`

**Request Body**:
```json
{
  "device_id": "macbook-m4-001",
  "commands": [
    {
      "type": "clear_cache",
      "data": {},
      "sequence": 1
    },
    {
      "type": "sync_now",
      "data": {},
      "sequence": 2
    },
    {
      "type": "restart",
      "data": {"delay_seconds": 30},
      "sequence": 3
    }
  ],
  "execution_mode": "sequential"
}
```

**Response**:
```json
{
  "batch_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "created",
  "total_commands": 3,
  "execution_mode": "sequential",
  "message": "Batch created successfully"
}
```

### Get Batch Progress

**Endpoint**: `GET /api/v1/batches/{batch_id}`

**Response**:
```json
{
  "batch_id": "550e8400-e29b-41d4-a716-446655440000",
  "device_id": "macbook-m4-001",
  "status": "in_progress",
  "execution_mode": "sequential",
  "total_commands": 3,
  "completed_commands": 1,
  "failed_commands": 0,
  "pending_commands": 2,
  "success_rate": 0.333,
  "failure_rate": 0.0,
  "created_at": "2026-02-03T12:00:00Z",
  "started_at": "2026-02-03T12:00:05Z",
  "completed_at": null,
  "error_message": null,
  "command_statuses": [
    {
      "command_id": "cmd-001",
      "command_type": "clear_cache",
      "status": "completed",
      "sequence": 1,
      "created_at": "2026-02-03T12:00:00Z",
      "completed_at": "2026-02-03T12:00:10Z",
      "error": null
    },
    {
      "command_id": "cmd-002",
      "command_type": "sync_now",
      "status": "pending",
      "sequence": 2,
      "created_at": "2026-02-03T12:00:00Z",
      "completed_at": null,
      "error": null
    },
    {
      "command_id": "cmd-003",
      "command_type": "restart",
      "status": "pending",
      "sequence": 3,
      "created_at": "2026-02-03T12:00:00Z",
      "completed_at": null,
      "error": null
    }
  ]
}
```

### List Batches

**Endpoint**: `GET /api/v1/batches`

**Query Parameters**:
- `device_id` (optional): Filter by device
- `status` (optional): Filter by status (pending, in_progress, completed, failed)
- `limit` (optional): Max results (default: 50)

**Response**:
```json
{
  "batches": [
    {
      "batch_id": "550e8400-e29b-41d4-a716-446655440000",
      "device_id": "macbook-m4-001",
      "execution_mode": "sequential",
      "status": "completed",
      "total_commands": 3,
      "completed_commands": 3,
      "failed_commands": 0,
      "created_at": "2026-02-03T12:00:00Z",
      "completed_at": "2026-02-03T12:05:00Z"
    }
  ],
  "count": 1
}
```

### Cancel Batch

**Endpoint**: `DELETE /api/v1/batches/{batch_id}`

**Response**:
```json
{
  "batch_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "cancelled",
  "message": "Batch cancelled successfully"
}
```

---

## CLI Usage

### Create Sequential Batch

```bash
python cloud_admin.py create-batch macbook-m4-001 \
  '[{"type":"clear_cache","data":{},"sequence":1},{"type":"sync_now","data":{},"sequence":2},{"type":"restart","data":{"delay_seconds":30},"sequence":3}]' \
  sequential

# Output:
# ✓ Batch created successfully
#   Batch ID: 550e8400-e29b-41d4-a716-446655440000
#   Device: macbook-m4-001
#   Total Commands: 3
#   Execution Mode: sequential
#   Status: created
```

### Create Parallel Batch

```bash
python cloud_admin.py create-batch macbook-m4-001 \
  '[{"type":"health_check","data":{}},{"type":"sync_now","data":{}},{"type":"clear_cache","data":{}}]' \
  parallel

# Output:
# ✓ Batch created successfully
#   Batch ID: 660e8400-e29b-41d4-a716-446655440001
#   Device: macbook-m4-001
#   Total Commands: 3
#   Execution Mode: parallel
#   Status: created
```

### Check Batch Status

```bash
python cloud_admin.py batch-status 550e8400-e29b-41d4-a716-446655440000

# Output:
# Batch: 550e8400-e29b-41d4-a716-446655440000
#   Device: macbook-m4-001
#   Status: in_progress
#   Execution Mode: sequential
#   Total Commands: 3
#   Completed: 1
#   Failed: 0
#   Pending: 2
#   Success Rate: 33.3%
#   Created: 2026-02-03T12:00:00Z
#   Started: 2026-02-03T12:00:05Z
#
#   Commands:
#     ✓ [1] clear_cache - completed
#     ⋯ [2] sync_now - pending
#     ⋯ [3] restart - pending
```

### List Batches

```bash
# List all batches
python cloud_admin.py list-batches

# Filter by device
python cloud_admin.py list-batches macbook-m4-001

# Filter by status
python cloud_admin.py list-batches "" completed

# Output:
# Found 2 batch(es):
#
# ✓ 550e8400... (macbook-m4-001)
#   Status: completed | Mode: sequential
#   Progress: 3/3 completed, 0 failed
#   Created: 2026-02-03T12:00:00Z
#
# ✓ 660e8400... (macbook-m4-001)
#   Status: completed | Mode: parallel
#   Progress: 3/3 completed, 0 failed
#   Created: 2026-02-03T13:00:00Z
```

### Cancel Pending Batch

```bash
python cloud_admin.py cancel-batch 550e8400-e29b-41d4-a716-446655440000

# Output:
# ✓ Batch cancelled
#   Batch ID: 550e8400-e29b-41d4-a716-446655440000
#   Status: cancelled
```

---

## Common Patterns

### 1. Maintenance Window Workflow

**Sequential execution** ensures proper shutdown/restart sequence:

```json
{
  "device_id": "pos-terminal-042",
  "execution_mode": "sequential",
  "commands": [
    {
      "type": "suspend_transactions",
      "data": {},
      "sequence": 1
    },
    {
      "type": "clear_cache",
      "data": {},
      "sequence": 2
    },
    {
      "type": "sync_now",
      "data": {},
      "sequence": 3
    },
    {
      "type": "restart",
      "data": {"delay_seconds": 10},
      "sequence": 4
    }
  ]
}
```

### 2. Health Check Batch

**Parallel execution** for fast diagnostics:

```json
{
  "device_id": "atm-012",
  "execution_mode": "parallel",
  "commands": [
    {"type": "check_network", "data": {}},
    {"type": "check_storage", "data": {}},
    {"type": "check_firmware", "data": {}},
    {"type": "check_peripherals", "data": {}}
  ]
}
```

### 3. Configuration Rollback

**Sequential rollback** after failed update:

```json
{
  "device_id": "kiosk-007",
  "execution_mode": "sequential",
  "commands": [
    {
      "type": "restore_config",
      "data": {"backup_id": "backup-20260203"},
      "sequence": 1
    },
    {
      "type": "validate_config",
      "data": {},
      "sequence": 2
    },
    {
      "type": "restart",
      "data": {"delay_seconds": 5},
      "sequence": 3
    }
  ]
}
```

### 4. Emergency Lockdown

**Sequential lockdown** for security incident:

```json
{
  "device_id": "pos-terminal-042",
  "execution_mode": "sequential",
  "commands": [
    {
      "type": "suspend_transactions",
      "data": {},
      "sequence": 1
    },
    {
      "type": "lock_device",
      "data": {"reason": "suspected fraud"},
      "sequence": 2
    },
    {
      "type": "alert_admin",
      "data": {"severity": "critical"},
      "sequence": 3
    }
  ]
}
```

---

## Integration with Templates

Command Batching **solves the template broadcast limitation**. Templates can now:

1. **Define multi-command workflows** as templates
2. **Apply templates as atomic batches** to single devices
3. **Broadcast templates as batches** to fleets (future enhancement)

### Example: Maintenance Template as Batch

```json
{
  "template_name": "maintenance-cycle",
  "commands": [
    {"type": "suspend_transactions", "data": {}},
    {"type": "clear_cache", "data": {}},
    {"type": "sync_now", "data": {}},
    {"type": "restart", "data": {"delay_seconds": 10}}
  ],
  "variables": []
}
```

**Apply as batch**:
```bash
# Future enhancement: Template → Batch conversion
python cloud_admin.py apply-template-as-batch maintenance-cycle macbook-m4-001 sequential
```

---

## Edge Device Integration

Edge devices process batches through the **command handler**:

### Sequential Batch Processing

```python
async def process_batch_sequential(batch):
    """Process batch commands sequentially."""
    for cmd in sorted(batch.commands, key=lambda c: c.sequence):
        try:
            result = await execute_command(cmd)
            await update_command_status(cmd.id, "completed", result)
        except Exception as e:
            await update_command_status(cmd.id, "failed", error=str(e))
            # Stop processing remaining commands
            break

    await update_batch_progress(batch.id)
```

### Parallel Batch Processing

```python
async def process_batch_parallel(batch):
    """Process batch commands in parallel."""
    tasks = [execute_command(cmd) for cmd in batch.commands]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for cmd, result in zip(batch.commands, results):
        if isinstance(result, Exception):
            await update_command_status(cmd.id, "failed", error=str(result))
        else:
            await update_command_status(cmd.id, "completed", result)

    await update_batch_progress(batch.id)
```

---

## Best Practices

### Sequential vs Parallel

**Use Sequential when**:
- Commands have dependencies (e.g., backup before update)
- Order matters (e.g., stop service before restart)
- Resource contention possible (e.g., database operations)
- Rollback needed on failure

**Use Parallel when**:
- Commands are independent
- Speed is critical (e.g., diagnostics)
- No shared resources
- Partial success acceptable

### Batch Size Limits

- **Recommended**: 2-10 commands per batch
- **Maximum**: 50 commands per batch (soft limit)
- Large batches increase failure risk and complexity
- Consider breaking into multiple batches

### Error Handling

- **Sequential**: Stops on first failure (fail-fast)
- **Parallel**: Completes all commands, reports all failures
- Always check `command_statuses` for detailed error info
- Use retry policies on individual commands for reliability

### Testing Batches

```bash
# Test with dry-run (future enhancement)
python cloud_admin.py create-batch macbook-m4-001 \
  '[{"type":"restart","data":{}}]' \
  sequential \
  --dry-run

# Test with small batches first
python cloud_admin.py create-batch test-device-001 \
  '[{"type":"health_check","data":{}}]' \
  parallel
```

---

## Monitoring and Observability

### Batch Metrics

Track these metrics in production:
- **Batch creation rate**: Batches created per hour
- **Completion rate**: Successful batches / total batches
- **Failure rate**: Failed batches / total batches
- **Average duration**: Time from created_at to completed_at
- **Command failure distribution**: Which commands fail most

### Logging

Batch operations are logged at multiple levels:
- **Batch creation**: Device ID, execution mode, command count
- **Batch start**: Execution begins
- **Command completion**: Each command result
- **Batch completion**: Final status, success/failure rates
- **Batch cancellation**: User cancellation events

### Alerts

Recommend alerts for:
- Batch failure rate > 10%
- Batch execution time > 5 minutes
- High cancellation rate (> 20%)
- Sequential batch stuck (no progress for 60s)

---

## Future Enhancements

### 1. Batch Timeouts

Add global batch timeout:
```json
{
  "device_id": "pos-terminal-042",
  "commands": [...],
  "execution_mode": "sequential",
  "timeout_seconds": 300
}
```

### 2. Partial Success Mode

Allow parallel batches to succeed with some failures:
```json
{
  "device_id": "atm-012",
  "commands": [...],
  "execution_mode": "parallel",
  "allow_partial_success": true,
  "min_success_rate": 0.8
}
```

### 3. Batch Dependencies

Link batches to create workflows:
```json
{
  "batch_id": "batch-002",
  "depends_on": ["batch-001"],
  "commands": [...]
}
```

### 4. Conditional Execution

Execute commands based on previous results:
```json
{
  "commands": [
    {"type": "check_version", "sequence": 1},
    {
      "type": "update_firmware",
      "sequence": 2,
      "condition": "step_1.version < '2.0.0'"
    }
  ]
}
```

### 5. Batch Rollback (Saga Pattern)

Auto-rollback on failure with compensation:
```json
{
  "commands": [
    {
      "type": "update_config",
      "compensate": "restore_config"
    }
  ],
  "enable_rollback": true
}
```

---

## Related Documentation

- [COMMAND_SYSTEM.md](./COMMAND_SYSTEM.md) - Command architecture overview
- [COMMAND_RETRIES.md](./COMMAND_RETRIES.md) - Retry policies for failed commands
- [COMMAND_BROADCASTS.md](./COMMAND_BROADCASTS.md) - Multi-device fleet commands
- [COMMAND_TEMPLATES.md](./COMMAND_TEMPLATES.md) - Reusable command workflows

---

## Summary

Command Batching provides **atomic multi-command operations** with flexible execution modes:

- ✅ Sequential execution for ordered workflows
- ✅ Parallel execution for speed
- ✅ Real-time progress tracking
- ✅ Individual command status visibility
- ✅ Cancellation support
- ✅ Integration with retry policies
- ✅ Foundation for template batching

Next: Integrate batching with templates for **fleet-wide atomic workflows**.
