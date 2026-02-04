-- Rufus Edge Cloud Platform - Database Initialization
-- This script runs on first startup of the PostgreSQL container

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─────────────────────────────────────────────────────────────────────────
-- Workflow Executions Table
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_type VARCHAR(200) NOT NULL,
    workflow_version VARCHAR(50),
    status VARCHAR(50) NOT NULL DEFAULT 'CREATED',
    current_step VARCHAR(200),
    state JSONB NOT NULL DEFAULT '{}',
    definition_snapshot JSONB,
    owner_id VARCHAR(100),
    org_id VARCHAR(100),
    data_region VARCHAR(50),
    parent_execution_id UUID REFERENCES workflow_executions(id),
    blocked_on_child_id UUID,
    idempotency_key VARCHAR(255),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_workflow_status ON workflow_executions(status);
CREATE INDEX IF NOT EXISTS idx_workflow_type ON workflow_executions(workflow_type);
CREATE INDEX IF NOT EXISTS idx_workflow_owner ON workflow_executions(owner_id);
CREATE INDEX IF NOT EXISTS idx_workflow_parent ON workflow_executions(parent_execution_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_workflow_idempotency ON workflow_executions(idempotency_key) WHERE idempotency_key IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────
-- Edge Devices Table (for device registry and management)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS edge_devices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id VARCHAR(100) UNIQUE NOT NULL,
    device_type VARCHAR(50) NOT NULL,
    device_name VARCHAR(200),
    merchant_id VARCHAR(100),
    location VARCHAR(200),
    api_key_hash VARCHAR(64) NOT NULL,
    public_key TEXT,
    firmware_version VARCHAR(50),
    sdk_version VARCHAR(50),
    capabilities TEXT DEFAULT '[]',
    status VARCHAR(50) DEFAULT 'online',
    metadata TEXT DEFAULT '{}',
    last_heartbeat_at TIMESTAMPTZ,
    last_sync_at TIMESTAMPTZ,
    registered_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_edge_device_merchant ON edge_devices(merchant_id);
CREATE INDEX IF NOT EXISTS idx_edge_device_status ON edge_devices(status);

-- ─────────────────────────────────────────────────────────────────────────
-- Device Commands Table (for sending commands to edge devices)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS device_commands (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    command_id VARCHAR(100) UNIQUE NOT NULL,
    device_id VARCHAR(100) NOT NULL REFERENCES edge_devices(device_id) ON DELETE CASCADE,
    command_type VARCHAR(100) NOT NULL,
    command_data TEXT DEFAULT '{}',
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    sent_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    error_message TEXT,
    -- Retry policy and tracking
    retry_policy JSONB DEFAULT NULL,
    retry_count INT DEFAULT 0,
    max_retries INT DEFAULT 0,
    next_retry_at TIMESTAMPTZ DEFAULT NULL,
    last_retry_at TIMESTAMPTZ DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_device_command_device ON device_commands(device_id);
CREATE INDEX IF NOT EXISTS idx_device_command_status ON device_commands(status);
CREATE INDEX IF NOT EXISTS idx_device_command_expires ON device_commands(expires_at);
CREATE INDEX IF NOT EXISTS idx_device_command_retry ON device_commands(next_retry_at) WHERE status = 'failed' AND next_retry_at IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────
-- Command Broadcasts Table (for fleet-wide commands)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS command_broadcasts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    broadcast_id VARCHAR(100) UNIQUE NOT NULL,
    command_type VARCHAR(100) NOT NULL,
    command_data TEXT DEFAULT '{}',
    target_filter JSONB NOT NULL,
    rollout_config JSONB DEFAULT NULL,
    created_by VARCHAR(100),
    status VARCHAR(50) DEFAULT 'pending',
    total_devices INT DEFAULT 0,
    completed_devices INT DEFAULT 0,
    failed_devices INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_broadcast_status ON command_broadcasts(status);
CREATE INDEX IF NOT EXISTS idx_broadcast_created ON command_broadcasts(created_at);

-- Link broadcasts to individual commands
ALTER TABLE device_commands
ADD COLUMN IF NOT EXISTS broadcast_id VARCHAR(100) REFERENCES command_broadcasts(broadcast_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_device_command_broadcast ON device_commands(broadcast_id);

-- ─────────────────────────────────────────────────────────────────────────
-- Command Templates Table (for reusable command sets)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS command_templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    template_name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    commands JSONB NOT NULL,
    variables JSONB DEFAULT '[]',
    created_by VARCHAR(100),
    version VARCHAR(50) DEFAULT '1.0.0',
    is_active BOOLEAN DEFAULT true,
    tags JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_template_name ON command_templates(template_name);
CREATE INDEX IF NOT EXISTS idx_template_active ON command_templates(is_active);
CREATE INDEX IF NOT EXISTS idx_template_tags ON command_templates USING GIN(tags);

-- ─────────────────────────────────────────────────────────────────────────
-- Command Batches Table (for atomic multi-command operations)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS command_batches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    batch_id VARCHAR(100) UNIQUE NOT NULL,
    device_id VARCHAR(100) NOT NULL REFERENCES edge_devices(device_id) ON DELETE CASCADE,
    execution_mode VARCHAR(50) DEFAULT 'sequential',
    status VARCHAR(50) DEFAULT 'pending',
    total_commands INT DEFAULT 0,
    completed_commands INT DEFAULT 0,
    failed_commands INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_batch_device ON command_batches(device_id);
CREATE INDEX IF NOT EXISTS idx_batch_status ON command_batches(status);

-- Link device_commands to batches
ALTER TABLE device_commands
ADD COLUMN IF NOT EXISTS batch_id VARCHAR(100) REFERENCES command_batches(batch_id) ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS batch_sequence INT DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_device_command_batch ON device_commands(batch_id, batch_sequence);

-- ─────────────────────────────────────────────────────────────────────────
-- Command Schedules Table (for scheduled and recurring commands)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS command_schedules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    schedule_id VARCHAR(100) UNIQUE NOT NULL,
    schedule_name VARCHAR(200),
    device_id VARCHAR(100) REFERENCES edge_devices(device_id) ON DELETE CASCADE,
    target_filter JSONB DEFAULT NULL,
    command_type VARCHAR(100) NOT NULL,
    command_data TEXT DEFAULT '{}',
    schedule_type VARCHAR(50) NOT NULL,
    execute_at TIMESTAMPTZ,
    cron_expression VARCHAR(100),
    timezone VARCHAR(50) DEFAULT 'UTC',
    status VARCHAR(50) DEFAULT 'active',
    next_execution_at TIMESTAMPTZ,
    last_execution_at TIMESTAMPTZ,
    execution_count INT DEFAULT 0,
    max_executions INT DEFAULT NULL,
    maintenance_window_start TIME,
    maintenance_window_end TIME,
    created_by VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    error_message TEXT,
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

CREATE TABLE IF NOT EXISTS schedule_executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    schedule_id VARCHAR(100) NOT NULL REFERENCES command_schedules(schedule_id) ON DELETE CASCADE,
    execution_number INT NOT NULL,
    scheduled_for TIMESTAMPTZ NOT NULL,
    executed_at TIMESTAMPTZ,
    status VARCHAR(50) DEFAULT 'pending',
    command_id VARCHAR(100),
    broadcast_id VARCHAR(100),
    result_summary TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_schedule_execution_schedule ON schedule_executions(schedule_id);
CREATE INDEX IF NOT EXISTS idx_schedule_execution_status ON schedule_executions(status);
CREATE INDEX IF NOT EXISTS idx_schedule_execution_scheduled_for ON schedule_executions(scheduled_for);

-- ─────────────────────────────────────────────────────────────────────────
-- Command Audit Log (for compliance tracking)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS command_audit_log (
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
    searchable_text TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english',
            COALESCE(event_type, '') || ' ' ||
            COALESCE(command_type, '') || ' ' ||
            COALESCE(device_id, '') || ' ' ||
            COALESCE(actor_id, '')
        )
    ) STORED
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON command_audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_device ON command_audit_log(device_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_command_id ON command_audit_log(command_id);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON command_audit_log(actor_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_event_type ON command_audit_log(event_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_merchant ON command_audit_log(merchant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_status ON command_audit_log(status);
CREATE INDEX IF NOT EXISTS idx_audit_search ON command_audit_log USING GIN(searchable_text);
CREATE INDEX IF NOT EXISTS idx_audit_device_event ON command_audit_log(device_id, event_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_actor_event ON command_audit_log(actor_id, event_type, timestamp DESC);

CREATE TABLE IF NOT EXISTS audit_retention_policies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    policy_name VARCHAR(100) UNIQUE NOT NULL,
    retention_days INT NOT NULL,
    event_types JSONB DEFAULT '[]',
    archive_before_delete BOOLEAN DEFAULT true,
    archive_location TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO audit_retention_policies (
    policy_name, retention_days, event_types, archive_before_delete, is_active
) VALUES (
    'pci_compliance_default',
    2555,
    '[]',
    true,
    true
) ON CONFLICT (policy_name) DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────
-- Device Configurations Table
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS device_configs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    config_id UUID DEFAULT uuid_generate_v4(),
    config_version VARCHAR(50) NOT NULL,
    config_data TEXT NOT NULL DEFAULT '{}',
    etag VARCHAR(64) NOT NULL,
    is_active BOOLEAN DEFAULT false,
    created_by VARCHAR(100),
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_config_active ON device_configs(is_active);
CREATE INDEX IF NOT EXISTS idx_config_version ON device_configs(config_version);

-- ─────────────────────────────────────────────────────────────────────────
-- SAF Transactions Table (Store-and-Forward)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS saf_transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transaction_id VARCHAR(100) NOT NULL,
    idempotency_key VARCHAR(255) UNIQUE NOT NULL,
    device_id VARCHAR(100) NOT NULL,
    merchant_id VARCHAR(100),
    amount_cents BIGINT,
    currency VARCHAR(3),
    card_token VARCHAR(255),
    card_last_four VARCHAR(4),
    encrypted_payload TEXT,
    encryption_key_id VARCHAR(100),
    status VARCHAR(50) DEFAULT 'pending',
    synced_at TIMESTAMPTZ,
    processed_at TIMESTAMPTZ,
    settlement_batch_id VARCHAR(100),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saf_device ON saf_transactions(device_id);
CREATE INDEX IF NOT EXISTS idx_saf_status ON saf_transactions(status);
CREATE INDEX IF NOT EXISTS idx_saf_idempotency ON saf_transactions(idempotency_key);

-- ─────────────────────────────────────────────────────────────────────────
-- Policy Assignments Table (for persistence - currently in-memory)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS device_assignments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id VARCHAR(100) NOT NULL,
    policy_id UUID NOT NULL,
    policy_version VARCHAR(50) NOT NULL,
    assigned_artifact VARCHAR(255) NOT NULL,
    artifact_hash VARCHAR(64),
    artifact_url TEXT,
    status VARCHAR(50) DEFAULT 'pending',
    current_artifact VARCHAR(255),
    current_hash VARCHAR(64),
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    downloaded_at TIMESTAMPTZ,
    installed_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    error_message TEXT,
    retry_count INT DEFAULT 0,
    UNIQUE(device_id, policy_id)
);

CREATE INDEX IF NOT EXISTS idx_assignment_device ON device_assignments(device_id);
CREATE INDEX IF NOT EXISTS idx_assignment_policy ON device_assignments(policy_id);
CREATE INDEX IF NOT EXISTS idx_assignment_status ON device_assignments(status);

-- ─────────────────────────────────────────────────────────────────────────
-- Policies Table (for persistence - currently in-memory)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS policies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    policy_name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    version VARCHAR(50) DEFAULT '1.0.0',
    status VARCHAR(50) DEFAULT 'draft',
    rules JSONB NOT NULL DEFAULT '[]',
    rollout JSONB DEFAULT '{}',
    created_by VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    tags JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_policy_status ON policies(status);
CREATE INDEX IF NOT EXISTS idx_policy_name ON policies(policy_name);

-- ─────────────────────────────────────────────────────────────────────────
-- Insert default configuration
-- ─────────────────────────────────────────────────────────────────────────
INSERT INTO device_configs (config_version, config_data, etag, is_active, description)
VALUES (
    '1.0.0',
    '{
        "floor_limit": 25.00,
        "max_offline_transactions": 100,
        "fraud_rules": [],
        "features": {
            "offline_mode": true,
            "ai_inference": true
        },
        "workflows": {},
        "models": {}
    }',
    'default-etag-v1',
    true,
    'Default configuration for edge devices'
) ON CONFLICT DO NOTHING;

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO rufus;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO rufus;

-- Output success message
DO $$
BEGIN
    RAISE NOTICE 'Rufus Cloud database initialized successfully!';
END $$;
