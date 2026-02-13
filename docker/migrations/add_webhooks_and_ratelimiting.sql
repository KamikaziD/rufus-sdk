-- Migration: Add Webhooks and Rate Limiting
-- Date: 2026-02-04
-- Description: Adds webhook notifications and rate limiting

-- ─────────────────────────────────────────────────────────────────────────
-- Webhook Registrations
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS webhook_registrations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    webhook_id VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    url TEXT NOT NULL,
    events JSONB NOT NULL,  -- List of event types to subscribe to
    secret VARCHAR(100),  -- HMAC secret for signature verification
    headers JSONB DEFAULT '{}',  -- Custom headers
    retry_policy JSONB DEFAULT NULL,
    is_active BOOLEAN DEFAULT true,
    created_by VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhook_active ON webhook_registrations(is_active);

-- ─────────────────────────────────────────────────────────────────────────
-- Webhook Deliveries (Track webhook calls)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    webhook_id VARCHAR(100) NOT NULL REFERENCES webhook_registrations(webhook_id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    event_data JSONB NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',  -- pending, delivered, failed
    http_status INT,
    response_body TEXT,
    error_message TEXT,
    attempt_count INT DEFAULT 0,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhook_delivery_webhook ON webhook_deliveries(webhook_id);
CREATE INDEX IF NOT EXISTS idx_webhook_delivery_status ON webhook_deliveries(status);
CREATE INDEX IF NOT EXISTS idx_webhook_delivery_created ON webhook_deliveries(created_at);

-- ─────────────────────────────────────────────────────────────────────────
-- Rate Limits (Per-user/per-IP rate limiting)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rate_limit_rules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rule_name VARCHAR(100) UNIQUE NOT NULL,
    resource_pattern VARCHAR(200) NOT NULL,  -- e.g., "/api/v1/commands*", "*"
    limit_per_window INT NOT NULL,  -- Max requests
    window_seconds INT NOT NULL,  -- Time window
    scope VARCHAR(50) NOT NULL,  -- user, ip, api_key, global
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_active ON rate_limit_rules(is_active);

-- Default rate limit rules
INSERT INTO rate_limit_rules (rule_name, resource_pattern, limit_per_window, window_seconds, scope) VALUES
    ('global_api_limit', '/api/v1/*', 1000, 60, 'ip'),  -- 1000 req/min per IP
    ('command_creation_limit', '/api/v1/commands', 100, 60, 'user'),  -- 100 commands/min per user
    ('approval_limit', '/api/v1/approvals', 50, 60, 'user')  -- 50 approval requests/min per user
ON CONFLICT (rule_name) DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────
-- Rate Limit Tracking (In-memory cache preferred, this is fallback)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rate_limit_tracking (
    id BIGSERIAL PRIMARY KEY,
    identifier VARCHAR(200) NOT NULL,  -- user_id, ip_address, api_key
    resource VARCHAR(200) NOT NULL,
    request_count INT DEFAULT 1,
    window_start TIMESTAMPTZ DEFAULT NOW(),
    window_end TIMESTAMPTZ NOT NULL,
    last_request TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_identifier ON rate_limit_tracking(identifier, resource, window_end);

-- Auto-cleanup old tracking records
CREATE INDEX IF NOT EXISTS idx_rate_limit_cleanup ON rate_limit_tracking(window_end) WHERE window_end < NOW();
