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
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_device_command_device ON device_commands(device_id);
CREATE INDEX IF NOT EXISTS idx_device_command_status ON device_commands(status);
CREATE INDEX IF NOT EXISTS idx_device_command_expires ON device_commands(expires_at);

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
