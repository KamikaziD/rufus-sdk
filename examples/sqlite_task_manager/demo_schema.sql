-- Simplified SQLite Schema for Demo
-- Based on migrations/002_sqlite_initial.sql but simplified for demo purposes

-- Core workflow execution state
CREATE TABLE IF NOT EXISTS workflow_executions (
    id TEXT PRIMARY KEY,
    workflow_type VARCHAR(100) NOT NULL,
    workflow_version VARCHAR(50),
    definition_snapshot TEXT,
    current_step INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(50) NOT NULL,
    state TEXT NOT NULL DEFAULT '{}',
    steps_config TEXT NOT NULL DEFAULT '[]',
    state_model_path VARCHAR(500) NOT NULL,
    saga_mode INTEGER DEFAULT 0,
    completed_steps_stack TEXT DEFAULT '[]',
    parent_execution_id TEXT,
    blocked_on_child_id TEXT,
    data_region VARCHAR(50) DEFAULT 'us-east-1',
    priority INTEGER DEFAULT 5,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    idempotency_key VARCHAR(255) UNIQUE,
    metadata TEXT DEFAULT '{}'
);

-- Operational logs for debugging
CREATE TABLE IF NOT EXISTS workflow_execution_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    execution_id TEXT,
    step_name VARCHAR(200),
    log_level VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    logged_at TEXT DEFAULT CURRENT_TIMESTAMP,
    worker_id VARCHAR(100),
    metadata TEXT DEFAULT '{}'
);

-- Performance metrics
CREATE TABLE IF NOT EXISTS workflow_metrics (
    metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    workflow_type VARCHAR(100),
    execution_id TEXT,
    step_name VARCHAR(200),
    metric_name VARCHAR(100) NOT NULL,
    metric_value REAL NOT NULL,
    unit VARCHAR(20),
    recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
    tags TEXT DEFAULT '{}'
);

-- Basic indexes
CREATE INDEX IF NOT EXISTS idx_workflow_status ON workflow_executions (status);
CREATE INDEX IF NOT EXISTS idx_workflow_type ON workflow_executions (workflow_type);
CREATE INDEX IF NOT EXISTS idx_execution_logs_workflow ON workflow_execution_logs (workflow_id);
CREATE INDEX IF NOT EXISTS idx_metrics_workflow_type ON workflow_metrics (workflow_type, metric_name);
