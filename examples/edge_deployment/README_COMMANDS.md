# Remote Command System - Quick Start

## Overview

The Ruvon Edge platform now supports **remote command execution** for device management. Commands are delivered using a hybrid approach:

- **Routine commands** (restart, backup, config) → Heartbeat delivery (0-30s latency)
- **Critical commands** (emergency stop, fraud alert) → WebSocket delivery (<1s latency)

## Quick Start

### 1. Start the Cloud Platform

```bash
cd docker
docker compose up -d
```

### 2. Start an Edge Device

```bash
# MacBook
python examples/edge_deployment/run_edge_macbook.py

# or Raspberry Pi
python examples/edge_deployment/run_edge_rpi.py --continuous --cloud-url http://YOUR_MAC_IP:8000
```

The edge device will:
- Send heartbeats every 30 seconds
- Check for commands in each heartbeat response
- Maintain a WebSocket connection for critical commands

### 3. Send Commands

```bash
# Health check (routine command)
python examples/edge_deployment/cloud_admin.py send-command macbook-m4-001 health_check

# Restart with delay (routine command)
python examples/edge_deployment/cloud_admin.py send-command macbook-m4-001 restart '{"delay_seconds": 30}'

# Emergency stop (critical command - delivered via WebSocket)
python examples/edge_deployment/cloud_admin.py send-command macbook-m4-001 emergency_stop '{"reason": "Test"}'

# Backup to cloud (maintenance command)
python examples/edge_deployment/cloud_admin.py send-command macbook-m4-001 backup '{"target": "cloud"}'
```

### 4. Check Command Status

```bash
# List all commands for a device
python examples/edge_deployment/cloud_admin.py list-commands macbook-m4-001

# Check specific command status
python examples/edge_deployment/cloud_admin.py command-status macbook-m4-001 <command-id>
```

### 5. Run Tests

```bash
python examples/edge_deployment/test_commands.py
```

This will automatically:
1. Test routine command delivery (health_check)
2. Test critical command delivery (disable/enable transactions)
3. Test commands with parameters (backup)
4. Display recent command history

## Available Commands

### Device Management
- `restart` - Soft restart of edge agent
- `shutdown` - Graceful shutdown
- `reboot` - System reboot (requires root)

### Configuration
- `update_config` - Update device configuration
- `reload_config` - Reload config from disk

### Maintenance
- `backup` - Trigger backup operation
- `schedule_backup` - Schedule recurring backup
- `clear_cache` - Clear local caches
- `health_check` - Run system health check

### Sync Operations
- `sync_now` - Force sync pending transactions
- `force_sync` - Force sync with retry

### Workflow Operations
- `start_workflow` - Start workflow execution
- `cancel_workflow` - Cancel running workflow

### Critical Operations (WebSocket)
- `emergency_stop` - Emergency stop all operations
- `fraud_alert` - Fraud alert with immediate action
- `security_lockdown` - Security lockdown mode
- `disable_transactions` - Disable transaction processing
- `enable_transactions` - Re-enable transaction processing

## Architecture

```
Cloud Control Plane                     Edge Device
─────────────────────                   ────────────

Command API                             Heartbeat Loop (30s)
  ├─ POST /commands            ─────>    ├─ Check for commands
  └─ GET /commands/status                └─ Process via CommandHandler

WebSocket Server                        WebSocket Client
  └─ /devices/{id}/ws          <────>    └─ Receive critical commands
```

## Command Delivery Flow

### Routine Commands (Heartbeat)

1. Admin sends command via `cloud_admin.py send-command`
2. Cloud stores command in database (status: pending)
3. Device sends heartbeat (every 30 seconds)
4. Cloud includes pending commands in heartbeat response
5. Device processes commands and reports status

**Latency**: 0-30 seconds (depends on heartbeat timing)

### Critical Commands (WebSocket)

1. Admin sends command via `cloud_admin.py send-command`
2. Cloud detects CRITICAL priority
3. Cloud sends immediately via WebSocket (if connected)
4. Device receives and processes command in real-time
5. Device reports status back via API

**Latency**: <1 second (near real-time)

## Command Status Lifecycle

```
pending → delivered → completed
                  └→ failed
```

- **pending**: Command queued, waiting for device
- **delivered**: Device received command, executing
- **completed**: Command executed successfully
- **failed**: Command execution failed

## Dependencies

All required dependencies are in `requirements.txt`:

```bash
pip install -r requirements.txt
```

Key additions for command system:
- `websockets>=12.0` - WebSocket client for critical commands
- `psutil>=5.9.0` - System monitoring for health checks

## Documentation

- **COMMAND_SYSTEM.md** - Complete documentation with all command types
- **HEARTBEAT_SYSTEM.md** - Heartbeat and offline detection documentation
- **command_handler.py** - Edge-side command execution logic
- **command_types.py** - Command definitions and priority routing

## Examples

### Example 1: Scheduled Restart

```bash
# Schedule restart in 5 minutes
python cloud_admin.py send-command macbook-m4-001 restart '{"delay_seconds": 300}'

# Check status
python cloud_admin.py list-commands macbook-m4-001 pending
```

### Example 2: Emergency Stop

```bash
# Immediately stop all operations
python cloud_admin.py send-command macbook-m4-001 emergency_stop '{"reason": "Security incident"}'

# Verify via WebSocket (< 1 second delivery)
python cloud_admin.py command-status macbook-m4-001 <command-id>
```

### Example 3: System Health Check

```bash
# Run comprehensive health check
python cloud_admin.py send-command macbook-m4-001 health_check

# View detailed results
python cloud_admin.py command-status macbook-m4-001 <command-id>

# Output includes:
# - CPU usage and count
# - Memory total/available/percent
# - Disk total/free/percent
# - Platform and hostname
```

### Example 4: Backup Operations

```bash
# Immediate backup
python cloud_admin.py send-command macbook-m4-001 backup '{"target": "cloud"}'

# Schedule daily backup at 2am
python cloud_admin.py send-command macbook-m4-001 schedule_backup '{"cron": "0 2 * * *"}'
```

## Troubleshooting

### Command Stuck in "pending"

**Cause**: Device not sending heartbeats or offline.

**Solution**:
```bash
# Check device status
python cloud_admin.py device-info macbook-m4-001

# If offline, start the edge device
python run_edge_macbook.py
```

### WebSocket Not Connected

**Cause**: WebSocket URL incorrect or firewall blocking.

**Solution**:
- Check edge device logs for WebSocket connection errors
- Verify cloud URL is accessible
- Check for firewall rules blocking WebSocket connections

### Command Failed to Execute

**Cause**: Invalid parameters or insufficient permissions.

**Solution**:
```bash
# Check command status for error details
python cloud_admin.py command-status macbook-m4-001 <command-id>

# Review edge device logs for execution errors
```

## Next Steps

1. Read **COMMAND_SYSTEM.md** for complete documentation
2. Run **test_commands.py** to verify your setup
3. Integrate commands into your device management workflows
4. Set up monitoring for command execution metrics
5. Configure alerts for critical command failures

## Support

For issues or questions:
- Review logs on edge device: Check console output
- Review logs on cloud: `docker compose logs -f ruvon-server`
- Check database: Command records in `device_commands` table
