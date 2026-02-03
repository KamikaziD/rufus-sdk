-- Migration: Add Command Batching
-- Date: 2026-02-03
-- Description: Adds command batching for atomic multi-command operations

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
