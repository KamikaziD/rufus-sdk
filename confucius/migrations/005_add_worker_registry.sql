-- Migration: 005_add_worker_registry.sql
-- Description: Add worker_nodes table for worker registration and health tracking.

CREATE TABLE IF NOT EXISTS worker_nodes (
    worker_id VARCHAR(255) PRIMARY KEY,
    hostname VARCHAR(255),
    region VARCHAR(50) NOT NULL,
    zone VARCHAR(50),
    capabilities JSONB DEFAULT '{}',
    status VARCHAR(50) DEFAULT 'online', -- 'online', 'offline', 'draining'
    last_heartbeat TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_worker_region ON worker_nodes(region);
CREATE INDEX IF NOT EXISTS idx_worker_status ON worker_nodes(status);

-- Trigger for updated_at
CREATE TRIGGER worker_nodes_updated_at
BEFORE UPDATE ON worker_nodes
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();
