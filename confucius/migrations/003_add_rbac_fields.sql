-- Migration: 003_add_rbac_fields.sql
-- Description: Add owner_id and org_id columns to workflow_executions for RBAC.

ALTER TABLE workflow_executions
ADD COLUMN IF NOT EXISTS owner_id VARCHAR(255),
ADD COLUMN IF NOT EXISTS org_id VARCHAR(255);

CREATE INDEX IF NOT EXISTS idx_workflow_owner ON workflow_executions(owner_id);
CREATE INDEX IF NOT EXISTS idx_workflow_org ON workflow_executions(org_id);
