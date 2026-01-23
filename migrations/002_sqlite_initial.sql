-- Rufus SDK - SQLITE Schema
-- Generated from migrations/schema.yaml v1.0.0
-- DO NOT EDIT MANUALLY - Use tools/compile_schema.py

-- ============================================================================
-- TABLES
-- ============================================================================

-- Core workflow execution state and metadata
CREATE TABLE IF NOT EXISTS workflow_executions (
    id TEXT PRIMARY KEY DEFAULT lower(hex(randomblob(16))),
    workflow_type VARCHAR(100) NOT NULL,
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
    metadata TEXT DEFAULT '{}',
    FOREIGN KEY (parent_execution_id) REFERENCES workflow_executions(id) ON DELETE CASCADE
);

-- Task queue for distributed worker claiming with idempotency
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY DEFAULT lower(hex(randomblob(16))),
    execution_id TEXT NOT NULL,
    step_name VARCHAR(200) NOT NULL,
    step_index INTEGER NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    worker_id VARCHAR(100),
    claimed_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    last_error TEXT,
    task_data TEXT,
    result TEXT,
    idempotency_key VARCHAR(255) UNIQUE,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (execution_id) REFERENCES workflow_executions(id) ON DELETE CASCADE
);

-- Saga pattern compensation actions for rollback capability
CREATE TABLE IF NOT EXISTS compensation_log (
    log_id TEXT PRIMARY KEY DEFAULT lower(hex(randomblob(16))),
    execution_id TEXT NOT NULL,
    step_name VARCHAR(200) NOT NULL,
    step_index INTEGER NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    action_result TEXT,
    error_message TEXT,
    executed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    executed_by VARCHAR(100),
    state_before TEXT,
    state_after TEXT,
    FOREIGN KEY (execution_id) REFERENCES workflow_executions(id) ON DELETE CASCADE
);

-- Compliance and audit trail for all workflow events
CREATE TABLE IF NOT EXISTS workflow_audit_log (
    audit_id TEXT PRIMARY KEY DEFAULT lower(hex(randomblob(16))),
    workflow_id TEXT NOT NULL,
    execution_id TEXT,
    event_type VARCHAR(50) NOT NULL,
    step_name VARCHAR(200),
    user_id VARCHAR(100),
    worker_id VARCHAR(100),
    recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
    old_state TEXT,
    new_state TEXT,
    state_diff TEXT,
    decision_rationale TEXT,
    metadata TEXT DEFAULT '{}',
    ip_address TEXT,
    user_agent TEXT
);

-- Operational logs for debugging workflow execution. Retention: 30 days. Partition by logged_at for performance.
CREATE TABLE IF NOT EXISTS workflow_execution_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    execution_id TEXT,
    step_name VARCHAR(200),
    log_level VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    logged_at TEXT DEFAULT CURRENT_TIMESTAMP,
    worker_id VARCHAR(100),
    metadata TEXT DEFAULT '{}',
    trace_id VARCHAR(100),
    span_id VARCHAR(100)
);

-- Performance metrics and monitoring data. Retention: 90 days. Consider TimescaleDB for time-series optimization.
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

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Indexes for workflow_executions
CREATE INDEX IF NOT EXISTS idx_workflow_status ON workflow_executions (status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_type ON workflow_executions (workflow_type);
CREATE INDEX IF NOT EXISTS idx_workflow_parent ON workflow_executions (parent_execution_id) WHERE parent_execution_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_workflow_region ON workflow_executions (data_region);
CREATE INDEX IF NOT EXISTS idx_workflow_priority ON workflow_executions (priority, created_at) WHERE status = 'PENDING';
CREATE INDEX IF NOT EXISTS idx_sub_workflows ON workflow_executions (parent_execution_id, created_at) WHERE parent_execution_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_workflow_idempotency ON workflow_executions (idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_failed_workflows ON workflow_executions (status, updated_at DESC) WHERE status IN ('FAILED', 'FAILED_ROLLED_BACK');
CREATE INDEX IF NOT EXISTS idx_saga_workflows ON workflow_executions (saga_mode, status) WHERE saga_mode = 1;

-- Indexes for tasks
CREATE INDEX IF NOT EXISTS idx_tasks_claim ON tasks (status, created_at) WHERE status = 'PENDING';
CREATE INDEX IF NOT EXISTS idx_tasks_execution ON tasks (execution_id, step_index);

-- Indexes for compensation_log
CREATE INDEX IF NOT EXISTS idx_compensation_execution ON compensation_log (execution_id, executed_at DESC);

-- Indexes for workflow_audit_log
CREATE INDEX IF NOT EXISTS idx_audit_workflow ON workflow_audit_log (workflow_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_event_type ON workflow_audit_log (event_type, recorded_at DESC);

-- Indexes for workflow_execution_logs
CREATE INDEX IF NOT EXISTS idx_execution_logs_workflow ON workflow_execution_logs (workflow_id, logged_at DESC);
CREATE INDEX IF NOT EXISTS idx_execution_logs_level ON workflow_execution_logs (log_level, logged_at DESC) WHERE log_level IN ('ERROR', 'CRITICAL');

-- Indexes for workflow_metrics
CREATE INDEX IF NOT EXISTS idx_metrics_workflow_type ON workflow_metrics (workflow_type, metric_name, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_metrics_step ON workflow_metrics (step_name, metric_name, recorded_at DESC);

-- ============================================================================
-- TRIGGERS
-- ============================================================================

CREATE TRIGGER IF NOT EXISTS workflow_executions_updated_at
AFTER UPDATE ON workflow_executions
FOR EACH ROW
WHEN OLD.updated_at = NEW.updated_at
BEGIN
    UPDATE workflow_executions
SET updated_at = CURRENT_TIMESTAMP
WHERE id = NEW.id;

END;

CREATE TRIGGER IF NOT EXISTS tasks_updated_at
AFTER UPDATE ON tasks
FOR EACH ROW
WHEN OLD.updated_at = NEW.updated_at
BEGIN
    UPDATE tasks
SET updated_at = CURRENT_TIMESTAMP
WHERE task_id = NEW.task_id;

END;

CREATE TRIGGER IF NOT EXISTS workflow_completed_at
AFTER UPDATE ON workflow_executions
FOR EACH ROW
WHEN NEW.status IN ('COMPLETED', 'FAILED', 'FAILED_ROLLED_BACK') AND NEW.completed_at IS NULL
BEGIN
    UPDATE workflow_executions
SET completed_at = CURRENT_TIMESTAMP
WHERE id = NEW.id;

END;

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Active workflows with current step info
CREATE OR REPLACE VIEW active_workflows AS
SELECT
    id,
    workflow_type,
    status,
    current_step,
    state_model_path,
    data_region,
    priority,
    created_at,
    updated_at,
    (julianday(updated_at) - julianday(created_at)) * 86400 AS duration,
    CASE WHEN parent_execution_id IS NOT NULL THEN 1 ELSE 0 END AS is_sub_workflow
FROM workflow_executions
WHERE status NOT IN ('COMPLETED', 'FAILED', 'FAILED_ROLLED_BACK')
ORDER BY priority ASC, created_at ASC
;

-- Workflow execution summary for last 24 hours
CREATE OR REPLACE VIEW workflow_execution_summary AS
SELECT
    workflow_type,
    status,
    COUNT(*) AS execution_count,
    AVG((julianday(completed_at) - julianday(created_at)) * 86400) AS avg_duration_seconds,
    MAX(updated_at) AS last_execution
FROM workflow_executions
WHERE created_at > datetime('now', '-24 hours')
GROUP BY workflow_type, status
;
