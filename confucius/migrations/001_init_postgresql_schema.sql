-- Confucius Workflow Engine - PostgreSQL Schema
-- Phase 1: Core Tables with Idempotency, Audit, and Metrics

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- CORE WORKFLOW EXECUTIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS workflow_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_type VARCHAR(100) NOT NULL,
    current_step INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(50) NOT NULL,
    state JSONB NOT NULL DEFAULT '{}',
    steps_config JSONB NOT NULL DEFAULT '[]',
    state_model_path VARCHAR(500) NOT NULL,

    -- Saga support
    saga_mode BOOLEAN DEFAULT FALSE,
    completed_steps_stack JSONB DEFAULT '[]',

    -- Sub-workflow support
    parent_execution_id UUID REFERENCES workflow_executions(id) ON DELETE CASCADE,
    blocked_on_child_id UUID,

    -- Regional data sovereignty
    data_region VARCHAR(50) DEFAULT 'us-east-1',

    -- Priority for task queue
    priority INTEGER DEFAULT 5,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    -- Idempotency key for restart protection
    idempotency_key VARCHAR(255) UNIQUE,

    -- Metadata
    metadata JSONB DEFAULT '{}'
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_workflow_status ON workflow_executions(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_type ON workflow_executions(workflow_type);
CREATE INDEX IF NOT EXISTS idx_workflow_parent ON workflow_executions(parent_execution_id) WHERE parent_execution_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_workflow_region ON workflow_executions(data_region);
CREATE INDEX IF NOT EXISTS idx_workflow_priority ON workflow_executions(priority, created_at) WHERE status = 'PENDING';

-- ============================================================================
-- TASK QUEUE TABLE (for distributed worker claiming)
-- ============================================================================
CREATE TABLE IF NOT EXISTS tasks (
    task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID NOT NULL REFERENCES workflow_executions(id) ON DELETE CASCADE,
    step_name VARCHAR(200) NOT NULL,
    step_index INTEGER NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',

    -- Worker assignment
    worker_id VARCHAR(100),
    claimed_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- Retry logic
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    last_error TEXT,

    -- Task data
    task_data JSONB,
    result JSONB,

    -- Idempotency
    idempotency_key VARCHAR(255) UNIQUE,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Partial index for fast task claiming
CREATE INDEX IF NOT EXISTS idx_tasks_claim
ON tasks (status, created_at)
WHERE status = 'PENDING';

CREATE INDEX IF NOT EXISTS idx_tasks_execution
ON tasks (execution_id, step_index);

-- ============================================================================
-- COMPENSATION LOG (Saga Pattern)
-- ============================================================================
CREATE TABLE IF NOT EXISTS compensation_log (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID NOT NULL REFERENCES workflow_executions(id) ON DELETE CASCADE,
    step_name VARCHAR(200) NOT NULL,
    step_index INTEGER NOT NULL,

    action_type VARCHAR(50) NOT NULL,  -- 'FORWARD', 'COMPENSATE', 'COMPENSATE_FAILED'
    action_result JSONB,
    error_message TEXT,

    executed_at TIMESTAMPTZ DEFAULT NOW(),
    executed_by VARCHAR(100),  -- worker_id

    -- State snapshots for debugging
    state_before JSONB,
    state_after JSONB
);

CREATE INDEX IF NOT EXISTS idx_compensation_execution
ON compensation_log (execution_id, executed_at DESC);

-- ============================================================================
-- AUDIT LOG (Compliance & Debugging)
-- ============================================================================
CREATE TABLE IF NOT EXISTS workflow_audit_log (
    audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID NOT NULL,  -- Not FK to preserve history even after deletion
    execution_id UUID,

    event_type VARCHAR(50) NOT NULL,  -- 'CREATED', 'STEP_COMPLETED', 'FAILED', 'ROLLED_BACK', etc.
    step_name VARCHAR(200),

    -- Who/What/When
    user_id VARCHAR(100),
    worker_id VARCHAR(100),
    recorded_at TIMESTAMPTZ DEFAULT NOW(),

    -- State changes
    old_state JSONB,
    new_state JSONB,
    state_diff JSONB,  -- Computed difference

    -- Decision rationale (for human-in-loop steps)
    decision_rationale TEXT,

    -- Metadata
    metadata JSONB DEFAULT '{}',
    ip_address INET,
    user_agent TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_workflow
ON workflow_audit_log (workflow_id, recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_event_type
ON workflow_audit_log (event_type, recorded_at DESC);

-- ============================================================================
-- EXECUTION LOGS (Operational Debugging)
-- ============================================================================
CREATE TABLE IF NOT EXISTS workflow_execution_logs (
    log_id BIGSERIAL PRIMARY KEY,
    workflow_id UUID NOT NULL,
    execution_id UUID,
    step_name VARCHAR(200),

    log_level VARCHAR(20) NOT NULL,  -- 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'
    message TEXT NOT NULL,

    logged_at TIMESTAMPTZ DEFAULT NOW(),
    worker_id VARCHAR(100),

    -- Structured data
    metadata JSONB DEFAULT '{}',

    -- Trace context
    trace_id VARCHAR(100),
    span_id VARCHAR(100)
);

-- Partitioning hint: In production, partition this table by logged_at
CREATE INDEX IF NOT EXISTS idx_execution_logs_workflow
ON workflow_execution_logs (workflow_id, logged_at DESC);

CREATE INDEX IF NOT EXISTS idx_execution_logs_level
ON workflow_execution_logs (log_level, logged_at DESC)
WHERE log_level IN ('ERROR', 'CRITICAL');

-- ============================================================================
-- METRICS (Performance Monitoring)
-- ============================================================================
CREATE TABLE IF NOT EXISTS workflow_metrics (
    metric_id BIGSERIAL PRIMARY KEY,
    workflow_id UUID NOT NULL,
    workflow_type VARCHAR(100),
    execution_id UUID,
    step_name VARCHAR(200),

    metric_name VARCHAR(100) NOT NULL,  -- 'step_duration_ms', 'retry_count', 'queue_time_ms', etc.
    metric_value NUMERIC NOT NULL,
    unit VARCHAR(20),  -- 'ms', 'count', 'bytes', etc.

    recorded_at TIMESTAMPTZ DEFAULT NOW(),

    -- Dimensions for aggregation
    tags JSONB DEFAULT '{}'
);

-- Time-series optimized indexes
CREATE INDEX IF NOT EXISTS idx_metrics_workflow_type
ON workflow_metrics (workflow_type, metric_name, recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_metrics_step
ON workflow_metrics (step_name, metric_name, recorded_at DESC);

-- ============================================================================
-- TRIGGERS
-- ============================================================================

-- Trigger: Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER workflow_executions_updated_at
BEFORE UPDATE ON workflow_executions
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER tasks_updated_at
BEFORE UPDATE ON tasks
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- Trigger: Emit workflow status change notifications via LISTEN/NOTIFY
CREATE OR REPLACE FUNCTION notify_workflow_update()
RETURNS TRIGGER AS $$
DECLARE
    payload JSON;
BEGIN
    -- Only notify on status changes
    IF OLD.status IS DISTINCT FROM NEW.status THEN
        payload = json_build_object(
            'id', NEW.id,
            'workflow_type', NEW.workflow_type,
            'status', NEW.status,
            'current_step', NEW.current_step,
            'updated_at', NEW.updated_at,
            'event', 'status_changed',
            'old_status', OLD.status
        );

        PERFORM pg_notify('workflow_update', payload::text);
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER workflow_update_trigger
AFTER UPDATE ON workflow_executions
FOR EACH ROW
EXECUTE FUNCTION notify_workflow_update();

-- Trigger: Auto-populate completed_at
CREATE OR REPLACE FUNCTION set_completed_at()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status IN ('COMPLETED', 'FAILED', 'FAILED_ROLLED_BACK') AND OLD.completed_at IS NULL THEN
        NEW.completed_at = NOW();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER workflow_completed_at
BEFORE UPDATE ON workflow_executions
FOR EACH ROW
EXECUTE FUNCTION set_completed_at();

-- ============================================================================
-- HELPER VIEWS
-- ============================================================================

-- View: Active workflows with current step info
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
    (updated_at - created_at) AS duration,
    parent_execution_id IS NOT NULL AS is_sub_workflow
FROM workflow_executions
WHERE status NOT IN ('COMPLETED', 'FAILED', 'FAILED_ROLLED_BACK')
ORDER BY priority ASC, created_at ASC;

-- View: Workflow execution summary
CREATE OR REPLACE VIEW workflow_execution_summary AS
SELECT
    workflow_type,
    status,
    COUNT(*) AS execution_count,
    AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) AS avg_duration_seconds,
    MAX(updated_at) AS last_execution
FROM workflow_executions
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY workflow_type, status;

-- ============================================================================
-- GRANTS (Adjust based on your user roles)
-- ============================================================================

-- For application user
-- GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO confucius_app;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO confucius_app;

-- For read-only monitoring user
-- GRANT SELECT ON ALL TABLES IN SCHEMA public TO confucius_readonly;
-- GRANT SELECT ON active_workflows, workflow_execution_summary TO confucius_readonly;

-- ============================================================================
-- INDEXES FOR COMMON QUERIES
-- ============================================================================

-- Query: Get all sub-workflows of a parent
CREATE INDEX IF NOT EXISTS idx_sub_workflows
ON workflow_executions (parent_execution_id, created_at)
WHERE parent_execution_id IS NOT NULL;

-- Query: Find workflows by idempotency key
CREATE INDEX IF NOT EXISTS idx_workflow_idempotency
ON workflow_executions (idempotency_key)
WHERE idempotency_key IS NOT NULL;

-- Query: Get recent failed workflows for alerting
CREATE INDEX IF NOT EXISTS idx_failed_workflows
ON workflow_executions (status, updated_at DESC)
WHERE status IN ('FAILED', 'FAILED_ROLLED_BACK');

-- Query: Saga rollback tracking
CREATE INDEX IF NOT EXISTS idx_saga_workflows
ON workflow_executions (saga_mode, status)
WHERE saga_mode = TRUE;

COMMENT ON TABLE workflow_executions IS 'Core workflow execution state and metadata';
COMMENT ON TABLE compensation_log IS 'Saga pattern compensation actions for rollback capability';
COMMENT ON TABLE workflow_audit_log IS 'Compliance and audit trail for all workflow events';
COMMENT ON TABLE workflow_execution_logs IS 'Operational logs for debugging workflow execution';
COMMENT ON TABLE workflow_metrics IS 'Performance metrics and monitoring data';
COMMENT ON TABLE tasks IS 'Task queue for distributed worker claiming with idempotency';

-- Add retention policy hint (implement with pg_cron or external job)
COMMENT ON TABLE workflow_execution_logs IS 'Retention: 30 days. Partition by logged_at for performance.';
COMMENT ON TABLE workflow_metrics IS 'Retention: 90 days. Consider TimescaleDB for time-series optimization.';
