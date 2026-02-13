-- Migration: Add Command Audit Log
-- Date: 2026-02-04
-- Description: Adds comprehensive audit logging for compliance tracking

CREATE TABLE IF NOT EXISTS command_audit_log (
    id BIGSERIAL PRIMARY KEY,
    audit_id VARCHAR(100) UNIQUE NOT NULL,

    -- Event identification
    event_type VARCHAR(50) NOT NULL,  -- command_created, command_sent, command_completed, command_failed, etc.
    command_id VARCHAR(100),
    broadcast_id VARCHAR(100),
    batch_id VARCHAR(100),
    schedule_id VARCHAR(100),

    -- Target information
    device_id VARCHAR(100),
    device_type VARCHAR(50),
    merchant_id VARCHAR(100),

    -- Command details
    command_type VARCHAR(100),
    command_data JSONB DEFAULT '{}',

    -- Actor information
    actor_type VARCHAR(50),  -- user, system, scheduler, api
    actor_id VARCHAR(100),  -- user_id, api_key_id, system component
    actor_ip VARCHAR(45),   -- IPv4 or IPv6
    user_agent TEXT,

    -- Result information
    status VARCHAR(50),  -- pending, completed, failed, cancelled
    result_data JSONB DEFAULT '{}',
    error_message TEXT,

    -- Timing
    timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    duration_ms INT,  -- Execution duration in milliseconds

    -- Context
    session_id VARCHAR(100),
    request_id VARCHAR(100),
    parent_audit_id VARCHAR(100),  -- For linking related events

    -- Compliance fields
    data_region VARCHAR(50),
    compliance_tags JSONB DEFAULT '[]',

    -- Search optimization
    searchable_text TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english',
            COALESCE(event_type, '') || ' ' ||
            COALESCE(command_type, '') || ' ' ||
            COALESCE(device_id, '') || ' ' ||
            COALESCE(actor_id, '')
        )
    ) STORED
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON command_audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_device ON command_audit_log(device_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_command_id ON command_audit_log(command_id);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON command_audit_log(actor_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_event_type ON command_audit_log(event_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_merchant ON command_audit_log(merchant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_status ON command_audit_log(status);
CREATE INDEX IF NOT EXISTS idx_audit_search ON command_audit_log USING GIN(searchable_text);

-- Composite indexes for common queries
CREATE INDEX IF NOT EXISTS idx_audit_device_event ON command_audit_log(device_id, event_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_actor_event ON command_audit_log(actor_id, event_type, timestamp DESC);

-- Partitioning hint (for large deployments)
-- Consider partitioning by timestamp range (monthly or quarterly)
-- Example:
-- CREATE TABLE command_audit_log_2026_q1 PARTITION OF command_audit_log
--     FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');

-- Retention policy table
CREATE TABLE IF NOT EXISTS audit_retention_policies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    policy_name VARCHAR(100) UNIQUE NOT NULL,
    retention_days INT NOT NULL,
    event_types JSONB DEFAULT '[]',  -- Empty = all event types
    archive_before_delete BOOLEAN DEFAULT true,
    archive_location TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Default retention policy (7 years for PCI-DSS compliance)
INSERT INTO audit_retention_policies (
    policy_name, retention_days, event_types, archive_before_delete, is_active
) VALUES (
    'pci_compliance_default',
    2555,  -- 7 years
    '[]',  -- All event types
    true,
    true
) ON CONFLICT (policy_name) DO NOTHING;
