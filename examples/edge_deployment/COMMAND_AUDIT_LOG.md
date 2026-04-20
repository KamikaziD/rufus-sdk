# Command Audit Log

Comprehensive audit logging for compliance tracking and regulatory reporting.

## Overview

Command Audit Log provides **immutable audit trails** of all command operations for compliance with PCI-DSS, SOX, GDPR, and other regulatory frameworks.

### Key Features

- **Comprehensive Event Tracking**: Records all command lifecycle events
- **Actor Attribution**: Who, what, when, where for every operation
- **Full-Text Search**: Fast text search across all audit fields
- **Flexible Querying**: Filter by device, merchant, actor, event type, time range
- **Multiple Export Formats**: JSON, CSV, JSONL for reporting
- **Compliance Tags**: Automatic tagging for PCI, SOX, GDPR requirements
- **Long-Term Retention**: 7-year default retention for PCI-DSS
- **Performance Optimized**: Partitioned tables and GIN indexes

### Compliance Support

| Framework | Requirements | Audit Log Support |
|-----------|--------------|-------------------|
| **PCI-DSS** | 7-year retention, immutable logs | ✅ Default 7-year policy, append-only |
| **SOX** | Change tracking, access control | ✅ All changes logged with actor |
| **GDPR** | Data access logs, right to erasure | ✅ Access logs, data region tracking |
| **HIPAA** | Audit trails, access tracking | ✅ Comprehensive event logging |

---

## Architecture

### Event Types

**Command Lifecycle**:
- `command_created`: Command created by user/system
- `command_sent`: Command dispatched to device
- `command_received`: Device acknowledged command
- `command_executing`: Device executing command
- `command_completed`: Command completed successfully
- `command_failed`: Command failed with error
- `command_cancelled`: Command cancelled by user
- `command_retry_scheduled`: Retry scheduled after failure

**Broadcast Lifecycle**:
- `broadcast_created`, `broadcast_started`, `broadcast_completed`, `broadcast_failed`, `broadcast_cancelled`, `broadcast_paused`

**Batch Lifecycle**:
- `batch_created`, `batch_started`, `batch_completed`, `batch_failed`, `batch_cancelled`

**Schedule Lifecycle**:
- `schedule_created`, `schedule_executed`, `schedule_paused`, `schedule_resumed`, `schedule_cancelled`

**Device Events**:
- `device_registered`, `device_updated`, `device_heartbeat`, `device_offline`, `device_online`

**Security Events**:
- `auth_success`, `auth_failure`, `api_key_created`, `api_key_revoked`

### Actor Types

- **user**: Human user via UI/CLI
- **api**: API client with API key
- **system**: Internal system component
- **scheduler**: Scheduler daemon
- **device**: Edge device
- **automation**: Automated workflow

### Audit Event Structure

```json
{
  "audit_id": "audit-abc-123",
  "event_type": "command_created",
  "command_id": "cmd-001",
  "device_id": "macbook-m4-001",
  "merchant_id": "merchant-123",
  "command_type": "restart",
  "command_data": {"delay_seconds": 10},
  "actor_type": "user",
  "actor_id": "user-456",
  "actor_ip": "192.168.1.100",
  "user_agent": "Mozilla/5.0...",
  "status": "pending",
  "timestamp": "2026-02-04T14:30:00Z",
  "compliance_tags": ["audit_trail"]
}
```

---

## Database Schema

### `command_audit_log` Table

```sql
CREATE TABLE command_audit_log (
    id BIGSERIAL PRIMARY KEY,
    audit_id VARCHAR(100) UNIQUE NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    command_id VARCHAR(100),
    broadcast_id VARCHAR(100),
    batch_id VARCHAR(100),
    schedule_id VARCHAR(100),
    device_id VARCHAR(100),
    device_type VARCHAR(50),
    merchant_id VARCHAR(100),
    command_type VARCHAR(100),
    command_data JSONB DEFAULT '{}',
    actor_type VARCHAR(50),
    actor_id VARCHAR(100),
    actor_ip VARCHAR(45),
    user_agent TEXT,
    status VARCHAR(50),
    result_data JSONB DEFAULT '{}',
    error_message TEXT,
    timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    duration_ms INT,
    session_id VARCHAR(100),
    request_id VARCHAR(100),
    parent_audit_id VARCHAR(100),
    data_region VARCHAR(50),
    compliance_tags JSONB DEFAULT '[]',
    searchable_text TSVECTOR GENERATED ALWAYS AS (...) STORED
);
```

**Indexes for Performance**:
- `idx_audit_timestamp`: Time-based queries (DESC for recent-first)
- `idx_audit_device`: Per-device audit history
- `idx_audit_command_id`: Command tracking
- `idx_audit_actor`: Per-user/actor history
- `idx_audit_search`: Full-text search (GIN index)
- Composite indexes for common query patterns

### `audit_retention_policies` Table

```sql
CREATE TABLE audit_retention_policies (
    policy_name VARCHAR(100) UNIQUE NOT NULL,
    retention_days INT NOT NULL,
    event_types JSONB DEFAULT '[]',
    archive_before_delete BOOLEAN DEFAULT true,
    archive_location TEXT,
    is_active BOOLEAN DEFAULT true
);
```

**Default Policy**: 7 years (2555 days) for PCI-DSS compliance

---

## API Reference

### Query Audit Logs

**Endpoint**: `POST /api/v1/audit/query`

**Request Body**:
```json
{
  "start_time": "2026-02-01T00:00:00Z",
  "end_time": "2026-02-04T23:59:59Z",
  "device_id": "macbook-m4-001",
  "event_types": ["command_created", "command_completed"],
  "actor_id": "user-123",
  "status": "completed",
  "limit": 100,
  "offset": 0,
  "order_by": "timestamp",
  "order_direction": "desc"
}
```

**Response**:
```json
{
  "entries": [
    {
      "audit_id": "audit-abc-123",
      "event_type": "command_created",
      "command_type": "restart",
      "device_id": "macbook-m4-001",
      "merchant_id": "merchant-123",
      "actor_type": "user",
      "actor_id": "user-456",
      "status": "pending",
      "timestamp": "2026-02-04T14:30:00Z",
      "compliance_tags": ["audit_trail"]
    }
  ],
  "total_count": 1523,
  "limit": 100,
  "offset": 0,
  "has_more": true
}
```

### Export Audit Logs

**Endpoint**: `POST /api/v1/audit/export`

**Request Body**:
```json
{
  "query": {
    "start_time": "2026-02-01T00:00:00Z",
    "end_time": "2026-02-04T23:59:59Z",
    "device_id": "macbook-m4-001"
  },
  "format": "csv"
}
```

**Response**: File download (CSV/JSON/JSONL)

**Formats**:
- `json`: JSON array (pretty-printed)
- `csv`: CSV with key fields
- `jsonl`: JSON Lines (one JSON object per line)

### Get Audit Statistics

**Endpoint**: `GET /api/v1/audit/stats`

**Query Parameters**:
- `start_time` (optional): Start of time range
- `end_time` (optional): End of time range

**Response**:
```json
{
  "period": {
    "start": "2026-01-28T00:00:00Z",
    "end": "2026-02-04T23:59:59Z"
  },
  "total_events": 15234,
  "failed_events": 142,
  "events_by_type": {
    "command_created": 4523,
    "command_completed": 4381,
    "device_heartbeat": 3245,
    "command_failed": 142
  },
  "events_by_actor": {
    "user": 2341,
    "system": 8934,
    "scheduler": 3959
  }
}
```

---

## CLI Usage

### Query Audit Logs

```bash
# Query all logs (last 7 days by default)
python cloud_admin.py audit-query

# Query with time range
python cloud_admin.py audit-query 2026-02-01T00:00:00Z 2026-02-04T23:59:59Z

# Query for specific device
python cloud_admin.py audit-query "" "" macbook-m4-001

# Query for specific event type
python cloud_admin.py audit-query "" "" "" command_failed

# Query with limit
python cloud_admin.py audit-query "" "" "" "" 50

# Output:
# Found 523 audit log(s) (showing 50):
#
# ✓ [2026-02-04T14:30:00Z] command_completed
#   Device: macbook-m4-001
#   Actor: user/user-456
#   Command: restart
#
# ✗ [2026-02-04T13:15:00Z] command_failed
#   Device: pos-terminal-042
#   Actor: system/scheduler
#   Command: health_check
#   Error: Connection timeout
#   Tags: audit_trail
```

### Export Audit Logs

```bash
# Export as JSON
python cloud_admin.py audit-export audit_logs.json json

# Export as CSV
python cloud_admin.py audit-export audit_logs.csv csv

# Export with time range
python cloud_admin.py audit-export audit_logs.json json 2026-02-01T00:00:00Z 2026-02-04T23:59:59Z

# Export for specific device
python cloud_admin.py audit-export device_audit.json json "" "" macbook-m4-001

# Output:
# ✓ Audit logs exported to audit_logs.csv
#   Format: csv
#   Size: 153420 bytes
```

### Get Audit Statistics

```bash
# Get stats for last 7 days (default)
python cloud_admin.py audit-stats

# Get stats for specific time range
python cloud_admin.py audit-stats 2026-02-01T00:00:00Z 2026-02-04T23:59:59Z

# Output:
# Audit Log Statistics
#   Period: 2026-01-28T00:00:00Z to 2026-02-04T23:59:59Z
#   Total Events: 15234
#   Failed Events: 142
#
#   Top Event Types:
#     command_created: 4523
#     command_completed: 4381
#     device_heartbeat: 3245
#     command_failed: 142
#
#   Events by Actor Type:
#     user: 2341
#     system: 8934
#     scheduler: 3959
```

---

## Query Patterns

### 1. Device Activity Report

Find all activity for a specific device:

```bash
python cloud_admin.py audit-query "" "" macbook-m4-001 "" 500
```

**Use Case**: Investigate device behavior, troubleshoot issues

### 2. Failed Operations

Find all failed commands in the last 24 hours:

```bash
python cloud_admin.py audit-query \
  $(date -u -d '1 day ago' +%Y-%m-%dT%H:%M:%SZ) \
  $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  "" \
  command_failed
```

**Use Case**: Error monitoring, reliability analysis

### 3. User Activity Tracking

Find all operations by a specific user:

```json
{
  "actor_type": "user",
  "actor_id": "user-123",
  "start_time": "2026-02-01T00:00:00Z",
  "limit": 1000
}
```

**Use Case**: Security audits, access control review

### 4. Compliance Reporting

Export all PCI-tagged events for quarterly audit:

```json
{
  "start_time": "2026-01-01T00:00:00Z",
  "end_time": "2026-03-31T23:59:59Z",
  "search_text": "pci",
  "limit": 10000
}
```

**Use Case**: Regulatory compliance, audit reports

### 5. Security Investigation

Find authentication failures and API key operations:

```json
{
  "event_types": ["auth_failure", "api_key_created", "api_key_revoked"],
  "start_time": "2026-02-01T00:00:00Z"
}
```

**Use Case**: Security incident investigation

---

## Compliance Workflows

### PCI-DSS Compliance

**Requirements**:
- 10.1: Track access to cardholder data
- 10.2: Implement automated audit trails
- 10.3: Record audit trail entries
- 10.5: Secure audit trails
- 10.7: Retain audit trail history for at least one year

**Ruvon Implementation**:
```bash
# 1. Verify 7-year retention policy is active
SELECT * FROM audit_retention_policies WHERE policy_name = 'pci_compliance_default';

# 2. Export quarterly compliance report
python cloud_admin.py audit-export \
  pci_audit_q1_2026.csv \
  csv \
  2026-01-01T00:00:00Z \
  2026-03-31T23:59:59Z

# 3. Generate access statistics
python cloud_admin.py audit-stats \
  2026-01-01T00:00:00Z \
  2026-03-31T23:59:59Z
```

### SOX Compliance

**Requirements**:
- Track all changes to financial systems
- Document who made changes and when
- Retain evidence of control effectiveness

**Ruvon Implementation**:
```bash
# 1. Query all configuration changes
python cloud_admin.py audit-query \
  2026-01-01T00:00:00Z \
  "" \
  "" \
  policy_updated

# 2. Export change history
python cloud_admin.py audit-export \
  sox_changes_2026.json \
  json \
  2026-01-01T00:00:00Z \
  2026-12-31T23:59:59Z
```

### GDPR Data Access Tracking

**Requirements**:
- Log all data access (Article 30)
- Track data processing activities
- Support right to access (Article 15)

**Ruvon Implementation**:
```json
{
  "event_types": ["device_registered", "device_updated", "device_deleted"],
  "data_region": "eu-west-1",
  "start_time": "2026-01-01T00:00:00Z"
}
```

---

## Performance Optimization

### Partitioning Strategy

For large deployments (>10M events/year), partition by time:

```sql
-- Monthly partitioning
CREATE TABLE command_audit_log_2026_02 PARTITION OF command_audit_log
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');

CREATE TABLE command_audit_log_2026_03 PARTITION OF command_audit_log
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
```

**Benefits**:
- Faster queries on recent data
- Easier archival of old data
- Better vacuum/maintenance performance

### Query Optimization

**1. Always use time range filters**:
```sql
-- Good: Uses idx_audit_timestamp
WHERE timestamp >= '2026-02-01' AND timestamp <= '2026-02-04'

-- Bad: Full table scan
WHERE device_id = 'macbook-m4-001'
```

**2. Use composite indexes for common patterns**:
```sql
-- Device + event type queries
CREATE INDEX idx_audit_device_event ON command_audit_log(device_id, event_type, timestamp DESC);
```

**3. Limit result sizes**:
```sql
-- Always use LIMIT for large result sets
LIMIT 1000 OFFSET 0
```

### Full-Text Search

Use `searchable_text` TSVECTOR for fast text search:

```sql
-- Fast: Uses GIN index
WHERE searchable_text @@ plainto_tsquery('english', 'restart failed')

-- Slow: Sequential scan
WHERE error_message LIKE '%timeout%'
```

---

## Retention and Archival

### Retention Policies

Default policy (PCI-DSS):
```sql
INSERT INTO audit_retention_policies (
    policy_name,
    retention_days,
    event_types,
    archive_before_delete
) VALUES (
    'pci_compliance_default',
    2555,  -- 7 years
    '[]',  -- All event types
    true
);
```

Custom policy example:
```sql
INSERT INTO audit_retention_policies (
    policy_name,
    retention_days,
    event_types,
    archive_before_delete,
    archive_location
) VALUES (
    'security_events_10_years',
    3650,
    '["auth_failure", "api_key_created", "api_key_revoked"]',
    true,
    's3://compliance-archive/audit-logs/'
);
```

### Manual Cleanup

```python
from ruvon_server.audit_service import AuditService

audit_service = AuditService(persistence)

# Clean up logs older than retention period
stats = await audit_service.cleanup_old_logs(policy_name="pci_compliance_default")

print(f"Deleted: {stats['deleted']}, Archived: {stats['archived']}")
```

### Automated Cleanup (Cron)

```bash
# Run monthly cleanup
0 0 1 * * python -c "
from ruvon_server.audit_service import AuditService
import asyncio
audit_service = AuditService(persistence)
asyncio.run(audit_service.cleanup_old_logs())
"
```

---

## Best Practices

### 1. Event Logging

**Always log these events**:
- Command creation (who requested it)
- Command execution (what happened)
- Configuration changes (before/after)
- Authentication events (success/failure)
- Data access (who accessed what)

**Include context**:
```python
event = AuditEvent(
    event_type=EventType.COMMAND_CREATED,
    command_id=command_id,
    device_id=device_id,
    actor_type=ActorType.USER,
    actor_id=user_id,
    actor_ip=request.client.host,  # Always log IP
    user_agent=request.headers.get("user-agent"),  # Always log user agent
    session_id=session_id,  # Link related events
    request_id=request_id  # Distributed tracing
)
```

### 2. Query Performance

- Always include time range filters
- Use specific event type filters
- Limit result sizes (max 1000 per query)
- Use pagination for large result sets
- Create custom indexes for frequent queries

### 3. Compliance

- Export logs quarterly for audits
- Verify retention policies annually
- Test archival process monthly
- Review access logs weekly
- Monitor failed events daily

### 4. Security

- Audit logs are append-only (no updates/deletes)
- Restrict access to audit query API
- Use HTTPS for audit exports
- Encrypt exports at rest
- Rotate archive encryption keys

---

## Troubleshooting

### Slow Queries

**Problem**: Audit queries taking >5 seconds

**Solutions**:
1. Add time range filter
2. Create custom composite index
3. Increase `work_mem` for PostgreSQL
4. Enable query plan caching

```sql
-- Check query plan
EXPLAIN ANALYZE
SELECT * FROM command_audit_log
WHERE device_id = 'macbook-m4-001'
AND timestamp >= '2026-02-01';
```

### Disk Space Growth

**Problem**: Audit log table growing too large

**Solutions**:
1. Enable time-based partitioning
2. Run retention cleanup
3. Archive old logs to S3
4. Compress historical partitions

```sql
-- Check table size
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename))
FROM pg_tables
WHERE tablename = 'command_audit_log';
```

### Missing Events

**Problem**: Expected events not appearing in audit log

**Solutions**:
1. Check `AuditService.log_event()` is called
2. Verify event type is valid
3. Check database connection
4. Review application logs for errors

---

## Related Documentation

- [COMMAND_SYSTEM.md](./COMMAND_SYSTEM.md) - Command architecture overview
- [COMMAND_RETRIES.md](./COMMAND_RETRIES.md) - Retry policies
- [COMMAND_BROADCASTS.md](./COMMAND_BROADCASTS.md) - Fleet commands
- [COMMAND_SCHEDULING.md](./COMMAND_SCHEDULING.md) - Time-based execution

---

## Summary

Command Audit Log provides **comprehensive compliance tracking** for Ruvon Edge:

- ✅ PCI-DSS, SOX, GDPR, HIPAA compliant
- ✅ Immutable audit trails
- ✅ Full-text search
- ✅ Flexible querying
- ✅ Multiple export formats
- ✅ 7-year default retention
- ✅ Performance optimized
- ✅ Automated compliance reporting

All command operations are automatically logged with full context for regulatory compliance.
