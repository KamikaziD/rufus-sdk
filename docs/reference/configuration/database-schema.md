# Database Schema Reference

## Overview

Rufus uses Alembic + SQLAlchemy for schema migrations with PostgreSQL and SQLite support.

**Schema Location:** `src/rufus/db_schema/database.py`

**Migrations:** `src/rufus/alembic/versions/`

---

## Core Tables

### workflow_executions

Main workflow state and metadata.

| Column | Type (PostgreSQL) | Type (SQLite) | Constraints | Description |
|--------|------------------|---------------|-------------|-------------|
| `id` | UUID | TEXT | PRIMARY KEY | Workflow identifier |
| `workflow_type` | VARCHAR(200) | TEXT | NOT NULL | Workflow type from registry |
| `workflow_version` | VARCHAR(50) | TEXT | - | Workflow definition version |
| `status` | VARCHAR(50) | TEXT | NOT NULL | Workflow status |
| `current_step_index` | INTEGER | INTEGER | NOT NULL | Current step index |
| `state` | JSONB | TEXT | NOT NULL | Workflow state (JSON) |
| `definition_snapshot` | JSONB | TEXT | - | YAML configuration snapshot |
| `owner_id` | VARCHAR(200) | TEXT | - | Owner identifier |
| `data_region` | VARCHAR(100) | TEXT | - | Data region |
| `parent_workflow_id` | UUID | TEXT | FOREIGN KEY | Parent workflow (if sub-workflow) |
| `metadata` | JSONB | TEXT | DEFAULT '{}' | Additional metadata |
| `created_at` | TIMESTAMPTZ | TEXT | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | TEXT | DEFAULT NOW() | Last update timestamp |

**Indexes:**

- `idx_workflow_type` - On `workflow_type`
- `idx_workflow_status` - On `status`
- `idx_workflow_owner` - On `owner_id`
- `idx_workflow_created` - On `created_at DESC`

**Triggers:**

- `update_workflow_timestamp` (PostgreSQL) - Auto-update `updated_at`

---

### workflow_heartbeats

Worker health tracking for zombie detection.

| Column | Type (PostgreSQL) | Type (SQLite) | Constraints | Description |
|--------|------------------|---------------|-------------|-------------|
| `workflow_id` | UUID | TEXT | PRIMARY KEY, FOREIGN KEY | Workflow identifier |
| `worker_id` | VARCHAR(100) | TEXT | NOT NULL | Worker identifier |
| `last_heartbeat` | TIMESTAMPTZ | TEXT | NOT NULL, DEFAULT NOW() | Last heartbeat timestamp |
| `current_step` | VARCHAR(200) | TEXT | - | Current step name |
| `step_started_at` | TIMESTAMPTZ | TEXT | - | Step start timestamp |
| `metadata` | JSONB | TEXT | DEFAULT '{}' | Additional metadata |

**Indexes:**

- `idx_heartbeat_time` - On `last_heartbeat ASC`

**Foreign Keys:**

- `workflow_id` → `workflow_executions(id)` ON DELETE CASCADE

---

### workflow_audit_log

Complete audit trail of workflow events.

| Column | Type (PostgreSQL) | Type (SQLite) | Constraints | Description |
|--------|------------------|---------------|-------------|-------------|
| `id` | SERIAL | INTEGER | PRIMARY KEY | Auto-increment ID |
| `workflow_id` | UUID | TEXT | FOREIGN KEY, NOT NULL | Workflow identifier |
| `event_type` | VARCHAR(100) | TEXT | NOT NULL | Event type |
| `step_name` | VARCHAR(200) | TEXT | - | Step name |
| `event_data` | JSONB | TEXT | DEFAULT '{}' | Event details |
| `timestamp` | TIMESTAMPTZ | TEXT | DEFAULT NOW() | Event timestamp |

**Indexes:**

- `idx_audit_workflow` - On `workflow_id`
- `idx_audit_timestamp` - On `timestamp DESC`

**Foreign Keys:**

- `workflow_id` → `workflow_executions(id)` ON DELETE CASCADE

**Event Types:**

- `WORKFLOW_STARTED`
- `STEP_EXECUTED`
- `STEP_FAILED`
- `WORKFLOW_PAUSED`
- `WORKFLOW_RESUMED`
- `WORKFLOW_COMPLETED`
- `WORKFLOW_FAILED`
- `WORKFLOW_CANCELLED`
- `COMPENSATION_STARTED`
- `COMPENSATION_COMPLETED`

---

### workflow_execution_logs

Debug and monitoring logs.

| Column | Type (PostgreSQL) | Type (SQLite) | Constraints | Description |
|--------|------------------|---------------|-------------|-------------|
| `id` | SERIAL | INTEGER | PRIMARY KEY | Auto-increment ID |
| `workflow_id` | UUID | TEXT | FOREIGN KEY, NOT NULL | Workflow identifier |
| `step_name` | VARCHAR(200) | TEXT | NOT NULL | Step name |
| `level` | VARCHAR(20) | TEXT | NOT NULL | Log level |
| `message` | TEXT | TEXT | NOT NULL | Log message |
| `metadata` | JSONB | TEXT | DEFAULT '{}' | Additional metadata |
| `timestamp` | TIMESTAMPTZ | TEXT | DEFAULT NOW() | Log timestamp |

**Indexes:**

- `idx_logs_workflow` - On `workflow_id`
- `idx_logs_level` - On `level`
- `idx_logs_timestamp` - On `timestamp DESC`

**Foreign Keys:**

- `workflow_id` → `workflow_executions(id)` ON DELETE CASCADE

**Log Levels:**

- `DEBUG`
- `INFO`
- `WARNING`
- `ERROR`

---

### workflow_metrics

Performance analytics.

| Column | Type (PostgreSQL) | Type (SQLite) | Constraints | Description |
|--------|------------------|---------------|-------------|-------------|
| `id` | SERIAL | INTEGER | PRIMARY KEY | Auto-increment ID |
| `workflow_id` | UUID | TEXT | FOREIGN KEY, NOT NULL | Workflow identifier |
| `step_name` | VARCHAR(200) | TEXT | NOT NULL | Step name |
| `metric_name` | VARCHAR(100) | TEXT | NOT NULL | Metric name |
| `metric_value` | FLOAT | REAL | NOT NULL | Metric value |
| `metadata` | JSONB | TEXT | DEFAULT '{}' | Additional metadata |
| `timestamp` | TIMESTAMPTZ | TEXT | DEFAULT NOW() | Metric timestamp |

**Indexes:**

- `idx_metrics_workflow` - On `workflow_id`
- `idx_metrics_name` - On `metric_name`
- `idx_metrics_timestamp` - On `timestamp DESC`

**Foreign Keys:**

- `workflow_id` → `workflow_executions(id)` ON DELETE CASCADE

**Common Metrics:**

- `duration_ms` - Step execution duration
- `retry_count` - Number of retries
- `memory_mb` - Memory usage
- Custom application metrics

---

### tasks

Distributed task queue (for async execution).

| Column | Type (PostgreSQL) | Type (SQLite) | Constraints | Description |
|--------|------------------|---------------|-------------|-------------|
| `id` | UUID | TEXT | PRIMARY KEY | Task identifier |
| `workflow_id` | UUID | TEXT | FOREIGN KEY, NOT NULL | Workflow identifier |
| `step_name` | VARCHAR(200) | TEXT | NOT NULL | Step name |
| `function_path` | VARCHAR(500) | TEXT | NOT NULL | Function import path |
| `state` | JSONB | TEXT | NOT NULL | Workflow state snapshot |
| `context` | JSONB | TEXT | NOT NULL | Step context |
| `status` | VARCHAR(50) | TEXT | NOT NULL, DEFAULT 'PENDING' | Task status |
| `worker_id` | VARCHAR(100) | TEXT | - | Worker that claimed task |
| `claimed_at` | TIMESTAMPTZ | TEXT | - | Claim timestamp |
| `completed_at` | TIMESTAMPTZ | TEXT | - | Completion timestamp |
| `result` | JSONB | TEXT | - | Task result |
| `error` | TEXT | TEXT | - | Error message |
| `created_at` | TIMESTAMPTZ | TEXT | DEFAULT NOW() | Creation timestamp |

**Indexes:**

- `idx_tasks_workflow` - On `workflow_id`
- `idx_tasks_status` - On `status`
- `idx_tasks_created` - On `created_at DESC`

**Foreign Keys:**

- `workflow_id` → `workflow_executions(id)` ON DELETE CASCADE

**Task Statuses:**

- `PENDING` - Waiting to be claimed
- `CLAIMED` - Claimed by worker
- `COMPLETED` - Successfully completed
- `FAILED` - Failed with error

---

### compensation_log

Saga pattern rollback actions.

| Column | Type (PostgreSQL) | Type (SQLite) | Constraints | Description |
|--------|------------------|---------------|-------------|-------------|
| `id` | SERIAL | INTEGER | PRIMARY KEY | Auto-increment ID |
| `workflow_id` | UUID | TEXT | FOREIGN KEY, NOT NULL | Workflow identifier |
| `step_name` | VARCHAR(200) | TEXT | NOT NULL | Original step name |
| `compensation_function` | VARCHAR(500) | TEXT | NOT NULL | Compensation function path |
| `status` | VARCHAR(50) | TEXT | NOT NULL | Compensation status |
| `result` | JSONB | TEXT | - | Compensation result |
| `error` | TEXT | TEXT | - | Error message |
| `executed_at` | TIMESTAMPTZ | TEXT | DEFAULT NOW() | Execution timestamp |

**Indexes:**

- `idx_compensation_workflow` - On `workflow_id`

**Foreign Keys:**

- `workflow_id` → `workflow_executions(id)` ON DELETE CASCADE

**Compensation Statuses:**

- `PENDING` - Queued for execution
- `EXECUTED` - Successfully executed
- `FAILED` - Failed with error

---

## Edge-Specific Tables

### edge_devices

Device registry for edge deployment.

| Column | Type (PostgreSQL) | Type (SQLite) | Constraints | Description |
|--------|------------------|---------------|-------------|-------------|
| `device_id` | VARCHAR(100) | TEXT | PRIMARY KEY | Device identifier |
| `device_name` | VARCHAR(200) | TEXT | - | Human-readable name |
| `device_type` | VARCHAR(50) | TEXT | - | Device type (POS, ATM, etc.) |
| `location` | VARCHAR(200) | TEXT | - | Physical location |
| `registration_key` | VARCHAR(200) | TEXT | - | Registration key |
| `api_key` | VARCHAR(200) | TEXT | UNIQUE | API authentication key |
| `status` | VARCHAR(50) | TEXT | DEFAULT 'OFFLINE' | Device status |
| `last_sync` | TIMESTAMPTZ | TEXT | - | Last sync timestamp |
| `metadata` | JSONB | TEXT | DEFAULT '{}' | Additional metadata |
| `created_at` | TIMESTAMPTZ | TEXT | DEFAULT NOW() | Creation timestamp |

**Indexes:**

- `idx_device_status` - On `status`
- `idx_device_api_key` - On `api_key`

**Device Statuses:**

- `ONLINE` - Connected
- `OFFLINE` - Disconnected
- `SYNCING` - Synchronizing data

---

### device_commands

Cloud-to-device commands.

| Column | Type (PostgreSQL) | Type (SQLite) | Constraints | Description |
|--------|------------------|---------------|-------------|-------------|
| `command_id` | UUID | TEXT | PRIMARY KEY | Command identifier |
| `device_id` | VARCHAR(100) | TEXT | FOREIGN KEY, NOT NULL | Target device |
| `command_type` | VARCHAR(50) | TEXT | NOT NULL | Command type |
| `payload` | JSONB | TEXT | DEFAULT '{}' | Command payload |
| `status` | VARCHAR(50) | TEXT | DEFAULT 'PENDING' | Command status |
| `created_at` | TIMESTAMPTZ | TEXT | DEFAULT NOW() | Creation timestamp |
| `executed_at` | TIMESTAMPTZ | TEXT | - | Execution timestamp |

**Indexes:**

- `idx_commands_device` - On `device_id`
- `idx_commands_status` - On `status`

**Foreign Keys:**

- `device_id` → `edge_devices(device_id)` ON DELETE CASCADE

**Command Types:**

- `UPDATE_CONFIG` - Push new configuration
- `SYNC_TRANSACTIONS` - Trigger transaction sync
- `UPDATE_WORKFLOW` - Deploy workflow update

**Command Statuses:**

- `PENDING` - Awaiting device pickup
- `DELIVERED` - Sent to device
- `EXECUTED` - Successfully executed
- `FAILED` - Failed with error

---

## Migration Tracking

### alembic_version

Alembic migration version tracking.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `version_num` | VARCHAR(32) | PRIMARY KEY | Current migration version |

**Note:** Managed automatically by Alembic.

---

## Type Mappings

### PostgreSQL → SQLite

| PostgreSQL | SQLite | Notes |
|------------|--------|-------|
| `UUID` | `TEXT` | Hex format |
| `JSONB` | `TEXT` | JSON strings |
| `TIMESTAMPTZ` | `TEXT` | ISO8601 format |
| `BOOLEAN` | `INTEGER` | 0/1 |
| `SERIAL` | `INTEGER` | Auto-increment |

---

## Schema Management

### Initialize Schema

```bash
rufus db init
```

Applies all migrations to create schema.

### Apply Migrations

```bash
alembic upgrade head
```

Applies pending migrations.

### Generate Migration

```bash
cd src/rufus
alembic revision --autogenerate -m "description"
```

Auto-generates migration from SQLAlchemy model changes.

### Rollback Migration

```bash
alembic downgrade -1
```

Rolls back one migration.

---

## Performance Indexes

All indexes created automatically during `rufus db init`.

**Query Optimization:**

- Workflow lookups by type/status: `idx_workflow_type`, `idx_workflow_status`
- Audit log queries: `idx_audit_workflow`, `idx_audit_timestamp`
- Log searches: `idx_logs_workflow`, `idx_logs_level`
- Metric analysis: `idx_metrics_workflow`, `idx_metrics_name`
- Zombie detection: `idx_heartbeat_time`

---

## Foreign Key Constraints

All foreign keys enforced in both PostgreSQL and SQLite.

**CASCADE Behavior:**

- Deleting workflow deletes all related records (logs, metrics, heartbeats, etc.)
- Deleting device deletes all commands
- Orphan records prevented

---

## See Also

- [CLI Commands](cli-commands.md)
- [Configuration](configuration.md)
- [Providers](../api/providers.md)
