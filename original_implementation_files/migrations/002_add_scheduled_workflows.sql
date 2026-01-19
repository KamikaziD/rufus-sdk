-- Migration: 002_add_scheduled_workflows.sql
-- Description: Add support for dynamic cron-based workflow scheduling.

CREATE TABLE IF NOT EXISTS scheduled_workflows (
    id SERIAL PRIMARY KEY,
    schedule_name VARCHAR(255) UNIQUE NOT NULL,
    workflow_type VARCHAR(255) NOT NULL,
    schedule_type VARCHAR(50) DEFAULT 'cron',  -- 'cron', 'interval'
    cron_expression VARCHAR(100),
    interval_seconds INTEGER,
    timezone VARCHAR(50) DEFAULT 'UTC',
    initial_data JSONB DEFAULT '{}',
    enabled BOOLEAN DEFAULT TRUE,
    last_run_at TIMESTAMPTZ,
    next_run_at TIMESTAMPTZ,
    run_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scheduled_next_run ON scheduled_workflows(next_run_at) WHERE enabled = TRUE;

CREATE TABLE IF NOT EXISTS scheduled_workflow_runs (
    id SERIAL PRIMARY KEY,
    schedule_id INTEGER REFERENCES scheduled_workflows(id) ON DELETE CASCADE,
    workflow_execution_id UUID REFERENCES workflow_executions(id),
    scheduled_time TIMESTAMPTZ,
    actual_start_time TIMESTAMPTZ DEFAULT NOW(),
    status VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_scheduled_runs_id ON scheduled_workflow_runs(schedule_id);

-- Trigger for updated_at
CREATE TRIGGER scheduled_workflows_updated_at
BEFORE UPDATE ON scheduled_workflows
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();
