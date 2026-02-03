-- Migration: Add Command Templates
-- Date: 2026-02-03
-- Description: Adds command templates for reusable command sets

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

-- Insert default templates
INSERT INTO command_templates (template_name, description, commands, tags, version) VALUES
(
    'security-lockdown',
    'Emergency security lockdown procedure',
    '[
        {"type": "disable_transactions", "data": {"reason": "Security lockdown"}},
        {"type": "security_lockdown", "data": {}},
        {"type": "fraud_alert", "data": {"alert_type": "manual_lockdown"}}
    ]'::jsonb,
    '["security", "emergency"]'::jsonb,
    '1.0.0'
),
(
    'soft-restart',
    'Graceful restart with cleanup',
    '[
        {"type": "clear_cache", "data": {}},
        {"type": "sync_now", "data": {}},
        {"type": "restart", "data": {"delay_seconds": 30}}
    ]'::jsonb,
    '["maintenance"]'::jsonb,
    '1.0.0'
),
(
    'maintenance-mode',
    'Enter maintenance mode with backup',
    '[
        {"type": "disable_transactions", "data": {"reason": "Scheduled maintenance"}},
        {"type": "backup", "data": {"target": "cloud"}},
        {"type": "health_check", "data": {}}
    ]'::jsonb,
    '["maintenance"]'::jsonb,
    '1.0.0'
),
(
    'health-check-full',
    'Comprehensive health diagnostics',
    '[
        {"type": "health_check", "data": {}},
        {"type": "sync_now", "data": {}},
        {"type": "clear_cache", "data": {}}
    ]'::jsonb,
    '["diagnostics"]'::jsonb,
    '1.0.0'
)
ON CONFLICT (template_name) DO NOTHING;
