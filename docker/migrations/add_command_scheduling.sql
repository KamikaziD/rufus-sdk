-- Migration: Add Command Scheduling
-- Date: 2026-02-04
-- Description: Adds command scheduling for one-time and recurring execution

CREATE TABLE IF NOT EXISTS command_schedules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    schedule_id VARCHAR(100) UNIQUE NOT NULL,
    schedule_name VARCHAR(200),
    device_id VARCHAR(100) REFERENCES edge_devices(device_id) ON DELETE CASCADE,
    target_filter JSONB DEFAULT NULL,  -- For fleet scheduling
    command_type VARCHAR(100) NOT NULL,
    command_data TEXT DEFAULT '{}',

    -- Scheduling configuration
    schedule_type VARCHAR(50) NOT NULL,  -- one_time, recurring
    execute_at TIMESTAMPTZ,  -- For one-time schedules
    cron_expression VARCHAR(100),  -- For recurring schedules
    timezone VARCHAR(50) DEFAULT 'UTC',

    -- Execution tracking
    status VARCHAR(50) DEFAULT 'active',  -- active, paused, completed, cancelled
    next_execution_at TIMESTAMPTZ,
    last_execution_at TIMESTAMPTZ,
    execution_count INT DEFAULT 0,
    max_executions INT DEFAULT NULL,  -- NULL = unlimited

    -- Maintenance window
    maintenance_window_start TIME,  -- e.g., 02:00:00
    maintenance_window_end TIME,    -- e.g., 06:00:00

    -- Metadata
    created_by VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    error_message TEXT,

    -- Retry configuration
    retry_policy JSONB DEFAULT NULL,

    CONSTRAINT valid_schedule_type CHECK (schedule_type IN ('one_time', 'recurring')),
    CONSTRAINT one_time_requires_execute_at CHECK (
        (schedule_type = 'one_time' AND execute_at IS NOT NULL) OR
        (schedule_type != 'one_time')
    ),
    CONSTRAINT recurring_requires_cron CHECK (
        (schedule_type = 'recurring' AND cron_expression IS NOT NULL) OR
        (schedule_type != 'recurring')
    ),
    CONSTRAINT device_or_filter CHECK (
        (device_id IS NOT NULL AND target_filter IS NULL) OR
        (device_id IS NULL AND target_filter IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_schedule_next_execution ON command_schedules(next_execution_at) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_schedule_device ON command_schedules(device_id);
CREATE INDEX IF NOT EXISTS idx_schedule_status ON command_schedules(status);
CREATE INDEX IF NOT EXISTS idx_schedule_type ON command_schedules(schedule_type);

-- Track individual executions of scheduled commands
CREATE TABLE IF NOT EXISTS schedule_executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    schedule_id VARCHAR(100) NOT NULL REFERENCES command_schedules(schedule_id) ON DELETE CASCADE,
    execution_number INT NOT NULL,
    scheduled_for TIMESTAMPTZ NOT NULL,
    executed_at TIMESTAMPTZ,
    status VARCHAR(50) DEFAULT 'pending',  -- pending, dispatched, completed, failed, skipped
    command_id VARCHAR(100),  -- Reference to created command (if single device)
    broadcast_id VARCHAR(100),  -- Reference to broadcast (if fleet)
    result_summary TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_schedule_execution_schedule ON schedule_executions(schedule_id);
CREATE INDEX IF NOT EXISTS idx_schedule_execution_status ON schedule_executions(status);
CREATE INDEX IF NOT EXISTS idx_schedule_execution_scheduled_for ON schedule_executions(scheduled_for);
