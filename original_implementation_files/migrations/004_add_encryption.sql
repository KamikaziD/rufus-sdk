-- Migration: 004_add_encryption.sql
-- Description: Add columns for encryption at rest.

ALTER TABLE workflow_executions
ADD COLUMN IF NOT EXISTS encrypted_state BYTEA,
ADD COLUMN IF NOT EXISTS encryption_key_id VARCHAR(255);

-- We might want to index encryption_key_id for key rotation purposes
CREATE INDEX IF NOT EXISTS idx_encryption_key ON workflow_executions(encryption_key_id);
