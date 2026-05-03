# Heartbeat & Offline Detection System

## Overview

The Ruvon Edge platform uses a heartbeat system to monitor device health and connectivity. Devices send periodic heartbeats to report their status, and the server automatically marks devices as offline if heartbeats stop.

## Heartbeat Configuration

### Edge Device Side

**Heartbeat Interval**: 30 seconds
- Location: `run_edge_macbook.py`, `run_edge_rpi.py`
- Devices send heartbeat every 30 seconds during continuous mode
- Includes: device status, active workflows, pending sync count, metrics

```python
# Heartbeat payload
{
    "device_status": "online",  # online, busy, error
    "active_workflows": 0,
    "pending_sync": 0,
    "metrics": {}  # CPU, memory, disk, etc.
}
```

### Server Side

**Offline Detection Threshold**: 120 seconds (2 minutes)
- Location: `main.py` - `/api/v1/devices` endpoint
- If no heartbeat received for 2 minutes → device marked as `offline`
- Checked automatically when listing devices

## Status Lifecycle

```
┌─────────┐  Registration   ┌────────┐  Heartbeat   ┌────────┐
│  NEW    │ ──────────────> │ ONLINE │ ───────────> │ ONLINE │
└─────────┘                 └────────┘              └────────┘
                                 │                        │
                                 │ No heartbeat           │
                                 │ for 120s               │
                                 ▼                        ▼
                            ┌─────────┐            ┌─────────┐
                            │ OFFLINE │ <────────  │ OFFLINE │
                            └─────────┘            └─────────┘
                                 │                        ▲
                                 │ Heartbeat              │
                                 │ received               │
                                 ▼                        │
                            ┌────────┐                    │
                            │ ONLINE │ ───────────────────┘
                            └────────┘
```

## Configuration Recommendations

| Deployment | Heartbeat Interval | Offline Threshold | Notes |
|------------|-------------------|-------------------|-------|
| **Development** | 30s | 120s (2 min) | Quick detection for testing |
| **Production - Stable Network** | 30s | 120s (2 min) | Standard configuration |
| **Production - Unstable Network** | 60s | 300s (5 min) | Reduce false positives |
| **IoT/Low Power** | 300s (5 min) | 900s (15 min) | Conserve battery/bandwidth |

**Rule of Thumb**: `Offline Threshold ≥ 4 × Heartbeat Interval` to avoid false positives.

## Current Configuration

**Default Settings**:
- Heartbeat Interval: **30 seconds**
- Offline Threshold: **120 seconds** (2 minutes)
- Ratio: 4:1 (recommended minimum)

## Offline Detection Behavior

### Automatic Detection

When you call `GET /api/v1/devices`, the server:
1. Retrieves all devices from database
2. Checks `last_heartbeat_at` timestamp for each device
3. Compares against current time
4. If `now - last_heartbeat_at > 120 seconds`:
   - Sets `status = 'offline'` in response
   - Logs the status change

### Manual Check

```bash
# Check device status
python examples/edge_deployment/cloud_admin.py list-devices

# Devices that stopped sending heartbeats will show:
Device: macbook-m4-001
  Status:       offline  ← Automatically detected
  Last Seen:    2026-02-03T18:49:30.731714+00:00
```

## Testing Offline Detection

### Test Scenario 1: Stop Edge Agent

```bash
# Terminal 1: Start edge agent
python examples/edge_deployment/run_edge_macbook.py

# Wait 1 minute, then check status
python examples/edge_deployment/cloud_admin.py list-devices
# Status: online, Last Seen: recent timestamp

# Stop the edge agent (Ctrl+C)

# Wait 2+ minutes, then check again
python examples/edge_deployment/cloud_admin.py list-devices
# Status: offline, Last Seen: >2 minutes ago
```

### Test Scenario 2: Network Disconnect

```bash
# Start edge agent
python examples/edge_deployment/run_edge_macbook.py

# Disconnect network (turn off WiFi)
# Wait 2+ minutes

# Check status from another machine
python examples/edge_deployment/cloud_admin.py list-devices
# Status: offline
```

## Monitoring & Alerts

### Production Recommendations

1. **Set up monitoring** for offline devices:
```python
# Check for offline devices
devices = await device_service.list_devices()
offline_devices = [d for d in devices if d['status'] == 'offline']

if len(offline_devices) > threshold:
    send_alert(f"{len(offline_devices)} devices offline")
```

2. **Track offline duration**:
```python
from datetime import datetime, timedelta

offline_threshold = timedelta(minutes=30)  # Alert if offline > 30 min
for device in offline_devices:
    last_seen = device['last_heartbeat_at']
    if datetime.utcnow() - last_seen > offline_threshold:
        send_critical_alert(f"Device {device['device_id']} offline for {duration}")
```

3. **Heartbeat failure logs**:
```python
# Edge device logs heartbeat failures
logger.warning(f"Heartbeat failed: {e}")
# Monitor logs for repeated failures
```

## Troubleshooting

### Device shows "Last Seen: None"

**Cause**: Device registered but never sent a heartbeat.

**Solutions**:
1. Check if edge script has heartbeat code (see `run_edge_macbook.py` for example)
2. Verify device has network connectivity to cloud
3. Check cloud logs for heartbeat endpoint errors

### Device stuck in "online" state after stopping

**Cause**: Heartbeat threshold not reached yet, or offline detection not running.

**Solutions**:
1. Wait 2+ minutes after stopping edge agent
2. Call `GET /api/v1/devices` endpoint to trigger offline detection
3. Verify offline threshold configuration

### False offline detections

**Cause**: Network latency or heartbeat interval too short.

**Solutions**:
1. Increase offline threshold: `offline_threshold = timedelta(seconds=300)`
2. Increase heartbeat interval on edge devices
3. Check network stability

## API Endpoints

### Send Heartbeat
```
POST /api/v1/devices/{device_id}/heartbeat
```

**Request**:
```json
{
  "device_status": "online",
  "active_workflows": 0,
  "pending_sync": 0,
  "metrics": {
    "cpu": 25,
    "memory": 8192,
    "disk": 50000
  }
}
```

**Response**:
```json
{
  "ack": true,
  "commands": []
}
```

### List Devices (with offline detection)
```
GET /api/v1/devices?status=online
GET /api/v1/devices?status=offline
```

**Response**:
```json
{
  "total": 2,
  "devices": [
    {
      "device_id": "macbook-m4-001",
      "status": "online",
      "last_heartbeat_at": "2026-02-03T18:49:30.731714+00:00"
    },
    {
      "device_id": "rpi5-001",
      "status": "offline",
      "last_heartbeat_at": "2026-02-03T18:45:00.000000+00:00"
    }
  ]
}
```

## Environment Variables

```bash
# Edge Device
export HEARTBEAT_INTERVAL=30  # seconds

# Cloud Server
export OFFLINE_THRESHOLD=120  # seconds
export HEARTBEAT_GRACE_PERIOD=60  # additional grace period
```

## Future Enhancements

- [ ] Background job to mark devices offline (instead of on-demand)
- [ ] Configurable thresholds per device or device type
- [ ] Heartbeat statistics (average interval, jitter)
- [ ] Webhook notifications for status changes
- [ ] Device reconnect tracking (time to recovery)
