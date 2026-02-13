-- Migration: Add Command Broadcast Support
-- Date: 2026-02-03
-- Description: Adds tables and columns for multi-device command broadcasts

-- Create command broadcasts table
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

-- Add indexes
CREATE INDEX IF NOT EXISTS idx_broadcast_status ON command_broadcasts(status);
CREATE INDEX IF NOT EXISTS idx_broadcast_created ON command_broadcasts(created_at);

-- Link device_commands to broadcasts
ALTER TABLE device_commands
ADD COLUMN IF NOT EXISTS broadcast_id VARCHAR(100) REFERENCES command_broadcasts(broadcast_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_device_command_broadcast ON device_commands(broadcast_id);
