-- Migration: Add Command Retry Support
-- Date: 2026-02-03
-- Description: Adds retry policy and tracking columns to device_commands table

-- Add retry-related columns
ALTER TABLE device_commands
ADD COLUMN IF NOT EXISTS retry_policy JSONB DEFAULT NULL,
ADD COLUMN IF NOT EXISTS retry_count INT DEFAULT 0,
ADD COLUMN IF NOT EXISTS max_retries INT DEFAULT 0,
ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ DEFAULT NULL,
ADD COLUMN IF NOT EXISTS last_retry_at TIMESTAMPTZ DEFAULT NULL;

-- Add index for retry processing
CREATE INDEX IF NOT EXISTS idx_device_command_retry
ON device_commands(next_retry_at)
WHERE status = 'failed' AND next_retry_at IS NOT NULL;

-- Update existing commands to have retry_count = 0
UPDATE device_commands
SET retry_count = 0, max_retries = 0
WHERE retry_count IS NULL;
