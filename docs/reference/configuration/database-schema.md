# Database Schema Reference

## Overview

Ruvon uses **Alembic + SQLAlchemy** for schema migrations with a hybrid approach:

- **SQLAlchemy** — schema definition (single source of truth)
- **Alembic** — migration generation and management
- **Raw SQL** — all runtime queries (45% faster than SQLAlchemy Core)

**Single Source of Truth:** `src/ruvon/db_schema/database.py`
**Edge Schema Constants:** `src/ruvon/db_schema/edge_database.py`
**Migrations:** `src/ruvon/alembic/versions/`

---

## Schema Governance

| Tier | Engine | Tables | Managed By |
|------|--------|--------|-----------|
| Cloud (PostgreSQL) | asyncpg | 34 | Alembic (autogenerate from `database.py`) |
| Edge (SQLite) | sqlite3 | 12 | `CREATE TABLE IF NOT EXISTS` in `sqlite.py` |

**Cloud schema changes:** Edit `database.py` → `alembic revision --autogenerate` → review → commit.
**Edge schema changes:** Edit `SQLITE_SCHEMA` in `sqlite.py` — no Alembic needed.

---

## Running Migrations

```bash
# Apply all pending migrations (PostgreSQL)
cd src/ruvon
alembic upgrade head

# Check current migration state
alembic current

# Generate migration after editing database.py
alembic revision --autogenerate -m "description"

# Rollback one migration
alembic downgrade -1

# Preview SQL without applying
alembic upgrade head --sql
```

---

## Cloud Table Inventory (33 tables)

### Core Workflow Tables (7)

| Table | Description |
|-------|-------------|
| `workflow_executions` | Main workflow state and metadata |
| `workflow_audit_log` | Complete audit trail of workflow events |
| `workflow_execution_logs` | Debug and monitoring logs |
| `workflow_metrics` | Performance analytics |
| `workflow_heartbeats` | Worker health tracking for zombie detection |
| `tasks` | Distributed task queue (async execution) |
| `compensation_log` | Saga pattern rollback actions |

### Scheduling (1)

| Table | Description |
|-------|-------------|
| `scheduled_workflows` | Cron-scheduled workflow definitions |

### Edge Device Management (2)

| Table | Description |
|-------|-------------|
| `edge_devices` | Device registry (POS terminals, ATMs, kiosks, etc.) |
| `device_commands` | Cloud-to-device commands with full retry/batch support |

### Workers (1)

| Table | Description |
|-------|-------------|
| `worker_nodes` | Celery worker registry and health status |

### Commands & Broadcasting (5)

| Table | Description |
|-------|-------------|
| `command_broadcasts` | Broadcast commands to device groups |
| `command_batches` | Batched command collections |
| `command_templates` | Reusable command templates |
| `command_schedules` | Scheduled command delivery |
| `schedule_executions` | Execution history for scheduled commands |

### Audit (2)

| Table | Description |
|-------|-------------|
| `command_audit_log` | Full audit trail of command execution (PCI-DSS) |
| `audit_retention_policies` | Configurable audit log retention rules |

### Authorization / RBAC (5)

| Table | Description |
|-------|-------------|
| `authorization_roles` | Role definitions (admin, operator, device, etc.) |
| `role_assignments` | User-to-role assignments |
| `authorization_policies` | Policy rules for command authorization |
| `command_approvals` | Multi-party approval requests |
| `approval_responses` | Approver decisions |

### Versioning (2)

| Table | Description |
|-------|-------------|
| `command_versions` | Versioned command definitions |
| `command_changelog` | Change history for command versions |

### Webhooks & Rate Limiting (4)

| Table | Description |
|-------|-------------|
| `webhook_registrations` | Registered webhook endpoints |
| `webhook_deliveries` | Webhook delivery history and retry state |
| `rate_limit_rules` | Rate limit policy definitions |
| `rate_limit_tracking` | Per-device/per-key rate limit counters |

### Edge Config & SAF (4)

| Table | Description |
|-------|-------------|
| `device_configs` | ETag-versioned configuration pushed to devices |
| `saf_transactions` | Store-and-Forward transaction sync records |
| `device_assignments` | Device-to-group/fleet assignments |
| `policies` | Business rules and fraud policies |

### WASM Component Registry (1)

| Table | Description |
|-------|-------------|
| `wasm_components` | Pre-compiled WebAssembly binaries with metadata and disk path |

### Migration Tracking (1)

| Table | Description |
|-------|-------------|
| `alembic_version` | Current migration version (managed by Alembic) |

---

## Edge Table Inventory (10 tables)

Edge devices use SQLite. Tables are created automatically by `SQLitePersistenceProvider` on first startup — no `alembic upgrade head` required.

### Core (7) — shared schema with cloud for sync

| Table | Description |
|-------|-------------|
| `workflow_executions` | Local workflow state |
| `workflow_audit_log` | Local audit trail |
| `workflow_execution_logs` | Debug logs |
| `workflow_metrics` | Performance data |
| `workflow_heartbeats` | Worker health |
| `tasks` | Local task queue |
| `compensation_log` | Saga rollback records |

### Edge-Specific (5)

| Table | Description |
|-------|-------------|
| `saf_pending_transactions` | Payment transactions queued offline, pending sync |
| `device_config_cache` | Cached configuration with ETag for change detection |
| `edge_sync_state` | Last-sync timestamps and connection state |
| `edge_workflow_cache` | Cached workflow YAML definitions (hot-deployed via `update_workflow` command) |
| `device_wasm_cache` | Cached WASM binaries, keyed by SHA-256 hash (synced via `sync_wasm` command) |

---

## Core Table Schemas

### workflow_executions

Main workflow state and metadata.

| Column | Type (PostgreSQL) | Type (SQLite) | Constraints | Description |
|--------|------------------|---------------|-------------|-------------|
| `id` | UUID | TEXT | PRIMARY KEY | Workflow identifier |
| `workflow_type` | VARCHAR(200) | TEXT | NOT NULL | Workflow type from registry |
| `workflow_version` | VARCHAR(50) | TEXT | — | Workflow definition version |
| `status` | VARCHAR(50) | TEXT | NOT NULL | Workflow status |
| `current_step_index` | INTEGER | INTEGER | NOT NULL | Current step index |
| `state` | JSONB | TEXT | NOT NULL | Workflow state (JSON) |
| `definition_snapshot` | JSONB | TEXT | — | YAML configuration snapshot |
| `owner_id` | VARCHAR(200) | TEXT | — | Owner identifier |
| `data_region` | VARCHAR(100) | TEXT | — | Data region routing key |
| `parent_workflow_id` | UUID | TEXT | FOREIGN KEY | Parent workflow (sub-workflow) |
| `metadata` | JSONB | TEXT | DEFAULT '{}' | Additional metadata |
| `created_at` | TIMESTAMPTZ | TEXT | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | TEXT | DEFAULT NOW() | Last update timestamp |

**Indexes:** `idx_workflow_type`, `idx_workflow_status`, `idx_workflow_owner`, `idx_workflow_created DESC`

---

### workflow_heartbeats

Worker health tracking for zombie detection.

| Column | Type (PostgreSQL) | Type (SQLite) | Constraints | Description |
|--------|------------------|---------------|-------------|-------------|
| `workflow_id` | UUID | TEXT | PRIMARY KEY, FK | Workflow identifier |
| `worker_id` | VARCHAR(100) | TEXT | NOT NULL | Worker identifier |
| `last_heartbeat` | TIMESTAMPTZ | TEXT | NOT NULL, DEFAULT NOW() | Last heartbeat timestamp |
| `current_step` | VARCHAR(200) | TEXT | — | Current step name |
| `step_started_at` | TIMESTAMPTZ | TEXT | — | Step start timestamp |
| `metadata` | JSONB | TEXT | DEFAULT '{}' | Additional metadata |

**Index:** `idx_heartbeat_time ASC` (used by ZombieScanner)

---

### workflow_audit_log

Complete audit trail of workflow events.

| Column | Type (PostgreSQL) | Type (SQLite) | Constraints | Description |
|--------|------------------|---------------|-------------|-------------|
| `id` | SERIAL | INTEGER | PRIMARY KEY | Auto-increment ID |
| `workflow_id` | UUID | TEXT | FK, NOT NULL | Workflow identifier |
| `event_type` | VARCHAR(100) | TEXT | NOT NULL | Event type |
| `step_name` | VARCHAR(200) | TEXT | — | Step name |
| `event_data` | JSONB | TEXT | DEFAULT '{}' | Event details |
| `timestamp` | TIMESTAMPTZ | TEXT | DEFAULT NOW() | Event timestamp |

**Event types:** `WORKFLOW_STARTED`, `STEP_EXECUTED`, `STEP_FAILED`, `WORKFLOW_PAUSED`, `WORKFLOW_RESUMED`, `WORKFLOW_COMPLETED`, `WORKFLOW_FAILED`, `WORKFLOW_CANCELLED`, `COMPENSATION_STARTED`, `COMPENSATION_COMPLETED`

---

### tasks

Distributed task queue for async step execution.

| Column | Type (PostgreSQL) | Type (SQLite) | Constraints | Description |
|--------|------------------|---------------|-------------|-------------|
| `id` | UUID | TEXT | PRIMARY KEY | Task identifier |
| `workflow_id` | UUID | TEXT | FK, NOT NULL | Workflow identifier |
| `step_name` | VARCHAR(200) | TEXT | NOT NULL | Step name |
| `function_path` | VARCHAR(500) | TEXT | NOT NULL | Function import path |
| `state` | JSONB | TEXT | NOT NULL | Workflow state snapshot |
| `context` | JSONB | TEXT | NOT NULL | Step context |
| `status` | VARCHAR(50) | TEXT | NOT NULL, DEFAULT 'PENDING' | Task status |
| `worker_id` | VARCHAR(100) | TEXT | — | Worker that claimed task |
| `claimed_at` | TIMESTAMPTZ | TEXT | — | Claim timestamp |
| `completed_at` | TIMESTAMPTZ | TEXT | — | Completion timestamp |
| `result` | JSONB | TEXT | — | Task result |
| `error` | TEXT | TEXT | — | Error message |
| `created_at` | TIMESTAMPTZ | TEXT | DEFAULT NOW() | Creation timestamp |

**Task statuses:** `PENDING`, `CLAIMED`, `COMPLETED`, `FAILED`

---

### edge_devices

Device registry for the cloud control plane.

| Column | Type (PostgreSQL) | Type (SQLite) | Constraints | Description |
|--------|------------------|---------------|-------------|-------------|
| `device_id` | VARCHAR(100) | TEXT | PRIMARY KEY | Device identifier |
| `device_name` | VARCHAR(200) | TEXT | — | Human-readable name |
| `device_type` | VARCHAR(50) | TEXT | — | POS, ATM, KIOSK, ROBOT, etc. |
| `location` | VARCHAR(200) | TEXT | — | Physical location |
| `registration_key` | VARCHAR(200) | TEXT | — | Registration key |
| `api_key` | VARCHAR(200) | TEXT | UNIQUE | API authentication key |
| `status` | VARCHAR(50) | TEXT | DEFAULT 'OFFLINE' | Device status |
| `last_sync` | TIMESTAMPTZ | TEXT | — | Last sync timestamp |
| `metadata` | JSONB | TEXT | DEFAULT '{}' | Additional metadata |
| `created_at` | TIMESTAMPTZ | TEXT | DEFAULT NOW() | Registration timestamp |

**Device statuses:** `ONLINE`, `OFFLINE`, `SYNCING`

---

### device_commands

Cloud-to-device commands with retry and batch support.

| Column | Type (PostgreSQL) | Description |
|--------|------------------|-------------|
| `command_id` | UUID | Command identifier (PRIMARY KEY) |
| `device_id` | VARCHAR(100) | Target device (FK → edge_devices) |
| `command_type` | VARCHAR(50) | Command type |
| `payload` | JSONB | Command payload |
| `status` | VARCHAR(50) | PENDING / DELIVERED / EXECUTED / FAILED |
| `retry_count` | INTEGER | Current retry attempt |
| `max_retries` | INTEGER | Maximum allowed retries |
| `batch_id` | UUID | Link to command_batches (nullable) |
| `broadcast_id` | UUID | Link to command_broadcasts (nullable) |
| `created_at` | TIMESTAMPTZ | Creation timestamp |
| `executed_at` | TIMESTAMPTZ | Execution timestamp |

**Command types:** `UPDATE_CONFIG`, `SYNC_TRANSACTIONS`, `UPDATE_WORKFLOW`, `REBOOT`, `DIAGNOSTIC`

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
| `TSVECTOR` | N/A | PostgreSQL full-text search only |

---

## Extending the Schema

Add custom tables by importing the shared `metadata` object from `database.py`:

```python
from ruvon.db_schema.database import metadata
from sqlalchemy import Table, Column, String, DateTime, func

my_events = Table(
    "my_custom_events", metadata,
    Column("id", String(36), primary_key=True),
    Column("event_type", String(100), nullable=False),
    Column("occurred_at", DateTime(timezone=True), server_default=func.now()),
)
```

Then generate and apply the migration:

```bash
cd src/ruvon
alembic revision --autogenerate -m "add_my_custom_events"
# Review the generated file in alembic/versions/
alembic upgrade head
```

For custom API routes that query your new tables, see `RUVON_CUSTOM_ROUTERS` in [Configuration](configuration.md).

---

## Schema Management Reference

```bash
# Initialize schema (applies all migrations)
ruvon db init

# Check migration status
alembic current
alembic history

# Validate schema matches SQLAlchemy definitions
ruvon db validate

# Show database statistics
ruvon db stats
```

---

### wasm_components

Cloud registry for pre-compiled WebAssembly binaries. Managed by Alembic (migration `e1f2a3b4c5d6`).

| Column | Type (PostgreSQL) | Constraints | Description |
|--------|------------------|-------------|-------------|
| `id` | VARCHAR(36) | PRIMARY KEY | UUID |
| `name` | VARCHAR(200) | NOT NULL | Human-readable component name |
| `version_tag` | VARCHAR(50) | NOT NULL | Semantic version tag (e.g. `v1.2.0`) |
| `binary_hash` | VARCHAR(64) | NOT NULL, UNIQUE | SHA-256 hex digest of the `.wasm` file |
| `blob_storage_path` | TEXT | NOT NULL | Absolute path to the `.wasm` file on disk |
| `input_schema` | TEXT | — | JSON schema string documenting expected input |
| `output_schema` | TEXT | — | JSON schema string documenting expected output |
| `created_at` | TIMESTAMP | DEFAULT NOW() | Upload timestamp |
| `updated_at` | TIMESTAMP | DEFAULT NOW() | Last update timestamp |

**Indexes:** `ix_wasm_components_name`, `uq_wasm_components_binary_hash` (unique), `ix_wasm_components_hash`

**Storage directory:** configured via `WASM_STORAGE_DIR` env var (default: `./wasm_storage`).

---

### device_wasm_cache (edge only)

SQLite cache of WASM binaries on edge devices. Created at startup via `CREATE TABLE IF NOT EXISTS`. No Alembic required.

| Column | Type (SQLite) | Constraints | Description |
|--------|--------------|-------------|-------------|
| `binary_hash` | TEXT | PRIMARY KEY | SHA-256 hex digest (matches cloud `wasm_components.binary_hash`) |
| `binary_data` | BLOB | NOT NULL | Raw `.wasm` file bytes |
| `last_accessed` | TEXT | DEFAULT CURRENT_TIMESTAMP | ISO-8601 timestamp of last use |

**Populated by:** `sync_wasm` cloud command → `ConfigManager.handle_sync_wasm_command()`

---

## Foreign Key Cascade Behavior

| Parent deleted | Children affected |
|----------------|-------------------|
| `workflow_executions` | Cascade-delete: `workflow_audit_log`, `workflow_execution_logs`, `workflow_metrics`, `workflow_heartbeats`, `tasks`, `compensation_log` |
| `edge_devices` | Cascade-delete: `device_commands` |

Both PostgreSQL and SQLite enforce foreign keys (SQLite via `PRAGMA foreign_keys = ON`).

---

## See Also

- [Configuration](configuration.md) — Environment variables including `RUVON_ENCRYPTION_KEY`
- [Extending Ruvon](../advanced/extending-ruvon.md) — Custom tables and custom API routes
- [Providers](../api/providers.md) — PersistenceProvider interface
