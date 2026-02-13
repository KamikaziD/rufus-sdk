# Device Command System

## Overview

The Rufus Edge platform uses a **hybrid command delivery system** that combines:
- **Heartbeat-based delivery** for routine commands (restart, backup, config updates)
- **WebSocket-based delivery** for critical commands (emergency stop, fraud alerts)

This architecture provides both reliability (heartbeat) and low-latency (WebSocket) command execution.

## Architecture

```
CLOUD CONTROL PLANE                      EDGE DEVICE
├── Command API                          ├── Heartbeat Loop (30s interval)
│   ├── POST /commands            ────>  │   └── Process routine commands
│   └── GET /commands/status             │
│                                        ├── WebSocket Connection
├── WebSocket Server                     │   └── Process critical commands
│   └── /devices/{id}/ws          <───>  │
│                                        └── CommandHandler
└── Command Database                         ├── Execute command
    ├── device_commands table                └── Report status
    └── command_status tracking
```

## Command Priority Levels

Commands are automatically routed based on priority:

| Priority | Delivery Method | Latency | Use Case |
|----------|----------------|---------|----------|
| **LOW** | Heartbeat | 0-30s | Maintenance, backups, cleanups |
| **NORMAL** | Heartbeat | 0-30s | Config updates, restarts |
| **HIGH** | Heartbeat | 0-30s | Force sync, workflow cancellation |
| **CRITICAL** | WebSocket | <1s | Emergency stop, fraud alerts |

## Available Commands

### Device Management

**restart** (NORMAL)
```bash
python cloud_admin.py send-command macbook-m4-001 restart '{"delay_seconds": 10}'
```
Soft restart of the edge agent. Supervisor should restart the process.

**shutdown** (NORMAL)
```bash
python cloud_admin.py send-command rpi5-001 shutdown '{"delay_seconds": 60}'
```
Graceful shutdown of the edge agent.

**reboot** (NORMAL)
```bash
python cloud_admin.py send-command macbook-m4-001 reboot '{"delay_seconds": 120}'
```
Reboot the entire system (requires root privileges).

### Configuration

**update_config** (NORMAL)
```bash
python cloud_admin.py send-command macbook-m4-001 update_config '{"config": {"key": "value"}}'
```
Update device configuration parameters.

**reload_config** (NORMAL)
```bash
python cloud_admin.py send-command rpi5-001 reload_config
```
Reload configuration from disk.

### Maintenance

**backup** (LOW)
```bash
python cloud_admin.py send-command macbook-m4-001 backup '{"target": "cloud"}'
```
Trigger immediate backup operation.

**schedule_backup** (LOW)
```bash
python cloud_admin.py send-command macbook-m4-001 schedule_backup '{"cron": "0 2 * * *"}'
```
Schedule recurring backup (default: 2am daily).

**clear_cache** (LOW)
```bash
python cloud_admin.py send-command rpi5-001 clear_cache
```
Clear local caches to free disk space.

**health_check** (NORMAL)
```bash
python cloud_admin.py send-command macbook-m4-001 health_check
```
Run comprehensive health check (CPU, memory, disk).

### Sync Operations

**sync_now** (NORMAL)
```bash
python cloud_admin.py send-command macbook-m4-001 sync_now
```
Force immediate sync of pending transactions.

**force_sync** (HIGH)
```bash
python cloud_admin.py send-command rpi5-001 force_sync
```
Force sync with retry on failure.

### Workflow Operations

**start_workflow** (NORMAL)
```bash
python cloud_admin.py send-command macbook-m4-001 start_workflow '{"workflow_type": "PaymentProcessing", "initial_data": {"amount": 100}}'
```
Start a workflow execution on the device.

**cancel_workflow** (HIGH)
```bash
python cloud_admin.py send-command macbook-m4-001 cancel_workflow '{"workflow_id": "wf-123"}'
```
Cancel a running workflow.

### Critical Operations (WebSocket)

**emergency_stop** (CRITICAL)
```bash
python cloud_admin.py send-command macbook-m4-001 emergency_stop '{"reason": "Security incident detected"}'
```
CRITICAL: Emergency stop all operations. Delivered via WebSocket for immediate execution.

**fraud_alert** (CRITICAL)
```bash
python cloud_admin.py send-command macbook-m4-001 fraud_alert '{"alert_type": "card_skimming", "details": {}}'
```
CRITICAL: Fraud alert - take immediate action.

**security_lockdown** (CRITICAL)
```bash
python cloud_admin.py send-command rpi5-001 security_lockdown
```
CRITICAL: Put device in security lockdown mode.

**disable_transactions** (CRITICAL)
```bash
python cloud_admin.py send-command macbook-m4-001 disable_transactions '{"reason": "Suspected fraud"}'
```
CRITICAL: Disable transaction processing immediately.

**enable_transactions** (CRITICAL)
```bash
python cloud_admin.py send-command macbook-m4-001 enable_transactions
```
CRITICAL: Re-enable transaction processing.

## Command Lifecycle

### 1. Command Creation

```
Admin triggers command
      ↓
Cloud validates command type
      ↓
Priority determined (LOW/NORMAL/HIGH/CRITICAL)
      ↓
Delivery method chosen (Heartbeat vs WebSocket)
      ↓
Command stored in database (status: pending)
```

### 2. Command Delivery

**Heartbeat Delivery** (LOW/NORMAL/HIGH):
```
Device sends heartbeat (every 30s)
      ↓
Cloud responds with pending commands
      ↓
Device receives commands in heartbeat response
      ↓
Device marks commands as "delivered"
```

**WebSocket Delivery** (CRITICAL):
```
Cloud checks if device has WebSocket connection
      ↓
If connected: Send immediately via WebSocket
      ↓
If not connected: Queue for heartbeat delivery (fallback)
      ↓
Device receives command in real-time (<1s latency)
```

### 3. Command Execution

```
Device receives command
      ↓
CommandHandler.process_commands() called
      ↓
Validate command_type
      ↓
Execute command function (e.g., _cmd_restart())
      ↓
Return result or error
```

### 4. Status Reporting

```
Command execution completes
      ↓
Device reports status to cloud:
  - POST /devices/{id}/commands/{cmd_id}/status
      ↓
Cloud updates command record:
  - status: completed (or failed)
  - result: execution output
  - error: error message (if failed)
      ↓
Admin can check status:
  - python cloud_admin.py command-status <device-id> <command-id>
```

## Command Status States

| Status | Description |
|--------|-------------|
| **pending** | Command created, waiting for delivery |
| **delivered** | Device received command, not yet executed |
| **completed** | Command executed successfully |
| **failed** | Command execution failed |

## Usage Examples

### Send a Command

```bash
# Simple command (no parameters)
python cloud_admin.py send-command macbook-m4-001 health_check

# Command with parameters
python cloud_admin.py send-command macbook-m4-001 restart '{"delay_seconds": 30}'

# Critical command (delivered via WebSocket)
python cloud_admin.py send-command macbook-m4-001 emergency_stop '{"reason": "Test"}'
```

### List Commands

```bash
# All commands for a device
python cloud_admin.py list-commands macbook-m4-001

# Filter by status
python cloud_admin.py list-commands macbook-m4-001 pending
python cloud_admin.py list-commands macbook-m4-001 completed
```

### Check Command Status

```bash
python cloud_admin.py command-status macbook-m4-001 <command-id>
```

Example output:
```
  COMMAND STATUS: cmd-abc123...
  ══════════════════════════════════════════════════════════════════

  Command Type:     restart
  Status:           completed
  Device ID:        macbook-m4-001
  Created:          2026-02-03T21:00:00Z
  Delivered:        2026-02-03T21:00:15Z
  Completed:        2026-02-03T21:00:20Z

  Result:
    {
        "status": "restarting",
        "delay_seconds": 30,
        "message": "Edge agent will restart in 30 seconds"
    }
```

## Edge Device Integration

### Heartbeat-Based Commands

Edge scripts automatically check for commands in the heartbeat response:

```python
# Send heartbeat
response = await client.post(
    f"{CLOUD_URL}/api/v1/devices/{DEVICE_ID}/heartbeat",
    json={
        "device_status": "online",
        "active_workflows": 0,
        "pending_sync": 0,
        "metrics": {}
    }
)

# Process commands from response
if response.status_code == 200:
    heartbeat_data = response.json()
    commands = heartbeat_data.get('commands', [])
    if commands:
        await command_handler.process_commands(commands)
```

### WebSocket-Based Commands

Edge scripts maintain a persistent WebSocket connection:

```python
async def websocket_handler():
    """Maintain WebSocket connection for critical commands."""
    import websockets
    while True:
        try:
            ws_url = f"ws://{CLOUD_URL}/api/v1/devices/{DEVICE_ID}/ws"
            async with websockets.connect(ws_url) as websocket:
                while True:
                    message = await websocket.recv()
                    data = json.loads(message)

                    if data.get('type') == 'command':
                        command = data.get('command')
                        await command_handler.process_commands([command])
        except Exception as e:
            logger.warning(f"WebSocket connection lost: {e}, reconnecting...")
            await asyncio.sleep(10)
```

## API Endpoints

### Trigger Command

```
POST /api/v1/devices/{device_id}/commands
```

**Request**:
```json
{
  "type": "restart",
  "data": {
    "delay_seconds": 30
  }
}
```

**Response**:
```json
{
  "command_id": "cmd-abc123...",
  "status": "pending",
  "delivery_method": "heartbeat",
  "created_at": "2026-02-03T21:00:00Z"
}
```

### Check Command Status

```
GET /api/v1/devices/{device_id}/commands/{command_id}/status
```

**Response**:
```json
{
  "command_id": "cmd-abc123...",
  "device_id": "macbook-m4-001",
  "command_type": "restart",
  "status": "completed",
  "result": {
    "status": "restarting",
    "delay_seconds": 30
  },
  "created_at": "2026-02-03T21:00:00Z",
  "completed_at": "2026-02-03T21:00:30Z"
}
```

### List Commands

```
GET /api/v1/devices/{device_id}/commands?status=pending
```

**Response**:
```json
[
  {
    "command_id": "cmd-abc123...",
    "command_type": "restart",
    "status": "pending",
    "created_at": "2026-02-03T21:00:00Z"
  }
]
```

### WebSocket Connection

```
WS /api/v1/devices/{device_id}/ws
```

**Message Types**:

Device → Cloud (heartbeat):
```json
{
  "type": "heartbeat",
  "status": "online",
  "metrics": {}
}
```

Cloud → Device (command):
```json
{
  "type": "command",
  "command": {
    "command_id": "cmd-abc123...",
    "command_type": "emergency_stop",
    "command_data": {"reason": "Security incident"}
  }
}
```

Device → Cloud (command result):
```json
{
  "type": "command_result",
  "command_id": "cmd-abc123...",
  "status": "completed",
  "result": {"status": "emergency_stop_activated"}
}
```

## Production Considerations

### Heartbeat Configuration

| Environment | Heartbeat Interval | Command Latency | Notes |
|-------------|-------------------|-----------------|-------|
| **Development** | 30s | 0-30s | Fast feedback |
| **Production** | 30s | 0-30s | Standard |
| **Low Power** | 300s (5 min) | 0-5 min | Battery conservation |

### WebSocket Reliability

- **Auto-reconnect**: Edge devices automatically reconnect on connection loss
- **Fallback**: Critical commands fall back to heartbeat if WebSocket unavailable
- **Keep-alive**: Ping/pong messages maintain connection

### Security

- **Authentication**: All commands require API key or JWT token
- **Authorization**: Role-based access control for critical commands
- **Audit Logging**: All commands logged to database
- **Idempotency**: Commands can be retried safely

### Monitoring

**Metrics to track**:
- Command delivery latency (p50, p95, p99)
- Command success rate
- WebSocket connection uptime
- Failed command count

**Alerts**:
- WebSocket disconnection > 5 minutes
- Command failure rate > 5%
- Critical command delivery failure

## Troubleshooting

### Command Stuck in "pending"

**Cause**: Device not sending heartbeats, or heartbeat response not being processed.

**Solutions**:
1. Check device is online: `python cloud_admin.py device-info <device-id>`
2. Verify heartbeat logs on edge device
3. Check command processing code in edge script
4. For critical commands: Check WebSocket connection status

### WebSocket Connection Fails

**Cause**: Network firewall, incorrect URL, or cloud not running.

**Solutions**:
1. Check WebSocket URL format: `ws://host:port/api/v1/devices/{id}/ws`
2. Verify cloud WebSocket endpoint is running
3. Check firewall rules (allow WebSocket connections)
4. Review edge device logs for connection errors

### Command Executed Multiple Times

**Cause**: Non-idempotent command without proper tracking.

**Solutions**:
1. Ensure commands check execution status before running
2. Use command_id to track execution
3. Report status immediately after execution
4. Implement idempotency checks in command handlers

## Future Enhancements

- [ ] Command scheduling (run at specific time)
- [ ] Command batching (group multiple commands)
- [ ] Command templates (predefined command sets)
- [ ] Conditional commands (execute if condition met)
- [ ] Command retries with exponential backoff
- [ ] Command prioritization queue
- [ ] Multi-device command broadcast
