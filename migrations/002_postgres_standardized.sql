-- Rufus SDK - POSTGRES Schema
-- Generated from migrations/schema.yaml v1.1.0
-- DO NOT EDIT MANUALLY - Use tools/compile_schema.py

-- ============================================================================
-- EXTENSIONS
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- TABLES
-- ============================================================================

-- Core workflow execution state and metadata
CREATE TABLE IF NOT EXISTS workflow_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_type VARCHAR(100) NOT NULL,
    workflow_version VARCHAR(50),
    definition_snapshot JSONB,
    current_step INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(50) NOT NULL,
    state JSONB NOT NULL DEFAULT '{}'::jsonb,
    steps_config JSONB NOT NULL DEFAULT '[]'::jsonb,
    state_model_path VARCHAR(500) NOT NULL,
    saga_mode BOOLEAN DEFAULT FALSE,
    completed_steps_stack JSONB DEFAULT '[]'::jsonb,
    parent_execution_id UUID,
    blocked_on_child_id UUID,
    data_region VARCHAR(50) DEFAULT 'us-east-1',
    priority INTEGER DEFAULT 5,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    idempotency_key VARCHAR(255) UNIQUE,
    metadata JSONB DEFAULT '{}'::jsonb,
    FOREIGN KEY (parent_execution_id) REFERENCES workflow_executions(id) ON DELETE CASCADE
);

-- Worker heartbeat tracking for detecting crashed/zombie workflows
CREATE TABLE IF NOT EXISTS workflow_heartbeats (
    workflow_id UUID PRIMARY KEY,
    worker_id VARCHAR(100) NOT NULL,
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    current_step VARCHAR(200),
    step_started_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'::jsonb,
    FOREIGN KEY (workflow_id) REFERENCES workflow_executions(id) ON DELETE CASCADE
);

-- Task queue for distributed worker claiming with idempotency
CREATE TABLE IF NOT EXISTS tasks (
    task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID NOT NULL,
    step_name VARCHAR(200) NOT NULL,
    step_index INTEGER NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    worker_id VARCHAR(100),
    claimed_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    last_error TEXT,
    task_data JSONB,
    result JSONB,
    idempotency_key VARCHAR(255) UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    FOREIGN KEY (execution_id) REFERENCES workflow_executions(id) ON DELETE CASCADE
);

-- Saga pattern compensation actions for rollback capability
CREATE TABLE IF NOT EXISTS compensation_log (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID NOT NULL,
    step_name VARCHAR(200) NOT NULL,
    step_index INTEGER NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    action_result JSONB,
    error_message TEXT,
    executed_at TIMESTAMPTZ DEFAULT NOW(),
    executed_by VARCHAR(100),
    state_before JSONB,
    state_after JSONB,
    FOREIGN KEY (execution_id) REFERENCES workflow_executions(id) ON DELETE CASCADE
);

-- Compliance and audit trail for all workflow events
CREATE TABLE IF NOT EXISTS workflow_audit_log (
    audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID NOT NULL,
    execution_id UUID,
    event_type VARCHAR(50) NOT NULL,
    step_name VARCHAR(200),
    user_id VARCHAR(100),
    worker_id VARCHAR(100),
    recorded_at TIMESTAMPTZ DEFAULT NOW(),
    old_state JSONB,
    new_state JSONB,
    state_diff JSONB,
    decision_rationale TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    ip_address INET,
    user_agent TEXT
);

-- Operational logs for debugging workflow execution. Retention: 30 days. Partition by logged_at for performance.
CREATE TABLE IF NOT EXISTS workflow_execution_logs (
    log_id BIGSERIAL,
    workflow_id UUID NOT NULL,
    execution_id UUID,
    step_name VARCHAR(200),
    log_level VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    logged_at TIMESTAMPTZ DEFAULT NOW(),
    worker_id VARCHAR(100),
    metadata JSONB DEFAULT '{}'::jsonb,
    trace_id VARCHAR(100),
    span_id VARCHAR(100),
    PRIMARY KEY (log_id)
);

-- Performance metrics and monitoring data. Retention: 90 days. Consider TimescaleDB for time-series optimization.
CREATE TABLE IF NOT EXISTS workflow_metrics (
    metric_id BIGSERIAL,
    workflow_id UUID NOT NULL,
    workflow_type VARCHAR(100),
    execution_id UUID,
    step_name VARCHAR(200),
    metric_name VARCHAR(100) NOT NULL,
    metric_value NUMERIC NOT NULL,
    unit VARCHAR(20),
    recorded_at TIMESTAMPTZ DEFAULT NOW(),
    tags JSONB DEFAULT '{}'::jsonb,
    PRIMARY KEY (metric_id)
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
CREATE INDEX IF NOT EXISTS idx_saga_workflows ON workflow_executions (saga_mode, status) WHERE saga_mode = TRUE;

-- Indexes for workflow_heartbeats
CREATE INDEX IF NOT EXISTS idx_heartbeat_time ON workflow_heartbeats (last_heartbeat ASC);
CREATE INDEX IF NOT EXISTS idx_heartbeat_worker ON workflow_heartbeats (worker_id, last_heartbeat);

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

CREATE OR REPLACE FUNCTION notify_workflow_update()
RETURNS TRIGGER AS $$
DECLARE
    payload JSON;
BEGIN
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
    (updated_at - created_at) AS duration,
    parent_execution_id IS NOT NULL AS is_sub_workflow
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
    AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) AS avg_duration_seconds,
    MAX(updated_at) AS last_execution
FROM workflow_executions
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY workflow_type, status
;

-- ============================================================================
-- TABLE COMMENTS
-- ============================================================================

COMMENT ON TABLE workflow_executions IS 'Core workflow execution state and metadata';
COMMENT ON TABLE workflow_heartbeats IS 'Worker heartbeat tracking for detecting crashed/zombie workflows';
COMMENT ON TABLE tasks IS 'Task queue for distributed worker claiming with idempotency';
COMMENT ON TABLE compensation_log IS 'Saga pattern compensation actions for rollback capability';
COMMENT ON TABLE workflow_audit_log IS 'Compliance and audit trail for all workflow events';
COMMENT ON TABLE workflow_execution_logs IS 'Operational logs for debugging workflow execution. Retention: 30 days. Partition by logged_at for performance.';
COMMENT ON TABLE workflow_metrics IS 'Performance metrics and monitoring data. Retention: 90 days. Consider TimescaleDB for time-series optimization.';
