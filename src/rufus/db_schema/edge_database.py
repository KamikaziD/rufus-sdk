"""
Edge Device SQLite Schema for Rufus Edge Agent.

This module documents the schema used by edge devices running SQLite. It is
intentionally separate from database.py (PostgreSQL / Alembic) because:

1. Edge devices are embedded and do not run Alembic migration tooling.
2. The edge schema is managed via CREATE TABLE IF NOT EXISTS statements in
   sqlite.py — the SQLITE_SCHEMA constant is applied at startup.
3. Edge devices only need the core workflow tables, not cloud-only tables
   (commands, RBAC, webhooks, etc.).

--- Architecture ---

  CLOUD (PostgreSQL + Alembic)          EDGE (SQLite + sqlite.py)
  ────────────────────────────          ──────────────────────────
  33 tables, fully Alembic-managed      11 tables, CREATE IF NOT EXISTS
  database.py = single source of truth  sqlite.py SQLITE_SCHEMA = source of truth
  Migrations: alembic upgrade head      Migrations: re-create or restart device

--- Compatibility Notes ---

* SyncManager uses the tasks table with step_name='SAF_Sync' to queue SAF
  transactions for cloud sync. This is a deliberate hack documented here.
  Future: migrate to saf_pending_transactions table.

* ConfigManager (v0.7.7+): fully migrated off the tasks table.
  - _cache_config / _load_cached_config → device_config_cache table
  - handle_update_workflow_command / load_local_workflow_definitions →
    edge_workflow_cache table (added in v0.7.7)
  No more FOREIGN KEY constraint violations from sentinel execution_id values.

* The four edge-specific tables (saf_pending_transactions, device_config_cache,
  edge_sync_state, edge_workflow_cache) are appended to SQLITE_SCHEMA in
  sqlite.py. New edge deployments will have them; existing deployments can
  add them via: sqlite3 device.db < edge_tables.sql

* scheduled_workflows exists in postgres.py but sqlite.py has only a stub
  (logs a warning). The table is not in SQLITE_SCHEMA yet.
"""

# Tables from SQLITE_SCHEMA that exist on every edge device
EDGE_CORE_TABLES = [
    "workflow_executions",
    "workflow_audit_log",
    "workflow_execution_logs",
    "workflow_metrics",
    "workflow_heartbeats",
    "tasks",
    "compensation_log",
]

# New edge-specific tables appended to SQLITE_SCHEMA (sqlite.py)
EDGE_SPECIFIC_TABLES = [
    "saf_pending_transactions",  # Proper SAF queue (future: replace tasks hack)
    "device_config_cache",       # Device config cache (ConfigManager, v0.7.7+)
    "edge_sync_state",           # Sync cursor / progress tracking
    "edge_workflow_cache",       # Workflow YAML cache (ConfigManager, v0.7.7+)
]

# All edge tables
ALL_EDGE_TABLES = EDGE_CORE_TABLES + EDGE_SPECIFIC_TABLES

# SQL for the 3 new edge-specific tables (reference copy; canonical copy is in sqlite.py)
EDGE_SCHEMA_SQL = """
-- ===================================================================
-- Edge-Specific Tables
-- SyncManager still uses the tasks table (legacy; future: migrate).
-- ConfigManager was fully migrated to these tables in v0.7.7.
-- ===================================================================

CREATE TABLE IF NOT EXISTS saf_pending_transactions (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL,
    idempotency_key TEXT UNIQUE NOT NULL,
    workflow_id TEXT,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    card_token TEXT NOT NULL,
    card_last_four TEXT,
    encrypted_payload TEXT,
    encryption_key_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending_sync',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    queued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    synced_at TEXT,
    sync_attempts INTEGER NOT NULL DEFAULT 0,
    last_sync_error TEXT,
    metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_saf_status ON saf_pending_transactions(status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_saf_idempotency ON saf_pending_transactions(idempotency_key);

CREATE TABLE IF NOT EXISTS device_config_cache (
    device_id TEXT PRIMARY KEY,
    config_version TEXT NOT NULL,
    config_data TEXT NOT NULL,
    etag TEXT,
    cached_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_poll_at TEXT
);

CREATE TABLE IF NOT EXISTS edge_sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS edge_workflow_cache (
    workflow_type TEXT PRIMARY KEY,
    yaml_content  TEXT NOT NULL,
    version       TEXT,
    updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
