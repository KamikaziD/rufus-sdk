-- Migration: Add Command Authorization
-- Date: 2026-02-04
-- Description: Adds RBAC and approval workflows for command authorization

-- ─────────────────────────────────────────────────────────────────────────
-- Authorization Roles
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS authorization_roles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    role_name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    permissions JSONB DEFAULT '[]',  -- List of permission strings
    is_system_role BOOLEAN DEFAULT false,  -- System roles cannot be deleted
    created_by VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_role_name ON authorization_roles(role_name);

-- Default system roles
INSERT INTO authorization_roles (role_name, description, permissions, is_system_role) VALUES
    ('admin', 'Full system access', '["*"]', true),
    ('operator', 'Standard operations', '["command:create", "command:view", "device:view", "broadcast:create"]', true),
    ('viewer', 'Read-only access', '["command:view", "device:view", "audit:view"]', true),
    ('approver', 'Can approve commands', '["approval:approve", "approval:reject", "approval:view"]', true)
ON CONFLICT (role_name) DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────
-- Role Assignments (User to Role mapping)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS role_assignments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(100) NOT NULL,
    role_name VARCHAR(100) NOT NULL REFERENCES authorization_roles(role_name) ON DELETE CASCADE,
    assigned_by VARCHAR(100),
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    UNIQUE(user_id, role_name)
);

CREATE INDEX IF NOT EXISTS idx_role_assignment_user ON role_assignments(user_id);
CREATE INDEX IF NOT EXISTS idx_role_assignment_role ON role_assignments(role_name);

-- ─────────────────────────────────────────────────────────────────────────
-- Authorization Policies (Command-level permissions)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS authorization_policies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    policy_name VARCHAR(100) UNIQUE NOT NULL,
    command_type VARCHAR(100),  -- NULL = applies to all commands
    device_type VARCHAR(50),    -- NULL = applies to all device types
    required_roles JSONB DEFAULT '[]',  -- List of role names
    requires_approval BOOLEAN DEFAULT false,
    approvers_required INT DEFAULT 1,
    approval_timeout_seconds INT DEFAULT 3600,
    allowed_during_maintenance_only BOOLEAN DEFAULT false,
    risk_level VARCHAR(20) DEFAULT 'low',  -- low, medium, high, critical
    is_active BOOLEAN DEFAULT true,
    created_by VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_policy_command_type ON authorization_policies(command_type);
CREATE INDEX IF NOT EXISTS idx_policy_active ON authorization_policies(is_active);

-- Default policies for high-risk commands
INSERT INTO authorization_policies (
    policy_name, command_type, required_roles, requires_approval,
    approvers_required, risk_level
) VALUES
    ('firmware_update_policy', 'update_firmware', '["admin"]', true, 2, 'critical'),
    ('device_delete_policy', 'delete_device', '["admin"]', true, 1, 'high'),
    ('config_update_policy', 'update_config', '["admin", "operator"]', false, 0, 'medium'),
    ('restart_policy', 'restart', '["admin", "operator"]', false, 0, 'low')
ON CONFLICT (policy_name) DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────
-- Command Approvals (Approval workflow tracking)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS command_approvals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    approval_id VARCHAR(100) UNIQUE NOT NULL,
    command_type VARCHAR(100) NOT NULL,
    command_data JSONB DEFAULT '{}',
    device_id VARCHAR(100),
    target_filter JSONB,
    requested_by VARCHAR(100) NOT NULL,
    requested_at TIMESTAMPTZ DEFAULT NOW(),
    status VARCHAR(50) DEFAULT 'pending',  -- pending, approved, rejected, expired, cancelled
    approvers_required INT NOT NULL,
    approvers_count INT DEFAULT 0,
    expires_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    reason TEXT,
    command_id VARCHAR(100),  -- Set when command is executed after approval
    risk_level VARCHAR(20),
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_approval_status ON command_approvals(status);
CREATE INDEX IF NOT EXISTS idx_approval_requested_by ON command_approvals(requested_by);
CREATE INDEX IF NOT EXISTS idx_approval_expires ON command_approvals(expires_at) WHERE status = 'pending';

-- ─────────────────────────────────────────────────────────────────────────
-- Approval Responses (Individual approver responses)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS approval_responses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    approval_id VARCHAR(100) NOT NULL REFERENCES command_approvals(approval_id) ON DELETE CASCADE,
    approver_id VARCHAR(100) NOT NULL,
    response VARCHAR(20) NOT NULL,  -- approved, rejected
    comment TEXT,
    responded_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(approval_id, approver_id)
);

CREATE INDEX IF NOT EXISTS idx_approval_response_approval ON approval_responses(approval_id);
CREATE INDEX IF NOT EXISTS idx_approval_response_approver ON approval_responses(approver_id);
