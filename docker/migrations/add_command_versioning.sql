-- Migration: Add Command Versioning
-- Date: 2026-02-04
-- Description: Adds version tracking for command definitions and changes

-- ─────────────────────────────────────────────────────────────────────────
-- Command Versions (Track command definition changes)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS command_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    command_type VARCHAR(100) NOT NULL,
    version VARCHAR(50) NOT NULL,
    schema_definition JSONB NOT NULL,  -- Full command schema
    changelog TEXT,  -- What changed in this version
    is_active BOOLEAN DEFAULT true,
    is_deprecated BOOLEAN DEFAULT false,
    deprecated_reason TEXT,
    created_by VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(command_type, version)
);

CREATE INDEX IF NOT EXISTS idx_command_version_type ON command_versions(command_type);
CREATE INDEX IF NOT EXISTS idx_command_version_active ON command_versions(is_active);

-- Add version to device_commands (which version was used)
ALTER TABLE device_commands
ADD COLUMN IF NOT EXISTS command_version VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_device_command_version ON device_commands(command_type, command_version);

-- ─────────────────────────────────────────────────────────────────────────
-- Command Changelog (Detailed change tracking)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS command_changelog (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    command_type VARCHAR(100) NOT NULL,
    from_version VARCHAR(50),
    to_version VARCHAR(50) NOT NULL,
    change_type VARCHAR(50) NOT NULL,  -- breaking, enhancement, bugfix, deprecated
    changes JSONB NOT NULL,  -- Structured change details
    migration_guide TEXT,  -- How to migrate from old to new
    created_by VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_changelog_command ON command_changelog(command_type);
CREATE INDEX IF NOT EXISTS idx_changelog_version ON command_changelog(to_version);

-- ─────────────────────────────────────────────────────────────────────────
-- Default command versions (examples)
-- ─────────────────────────────────────────────────────────────────────────
INSERT INTO command_versions (command_type, version, schema_definition, changelog, created_by) VALUES
    ('restart', '1.0.0', '{"type":"object","properties":{"delay_seconds":{"type":"integer","minimum":0,"maximum":300}},"required":[]}', 'Initial version', 'system'),
    ('health_check', '1.0.0', '{"type":"object","properties":{},"required":[]}', 'Initial version', 'system'),
    ('update_firmware', '1.0.0', '{"type":"object","properties":{"version":{"type":"string"},"url":{"type":"string","format":"uri"}},"required":["version"]}', 'Initial version', 'system'),
    ('clear_cache', '1.0.0', '{"type":"object","properties":{"cache_type":{"type":"string","enum":["all","temp","logs"]}},"required":[]}', 'Initial version', 'system')
ON CONFLICT (command_type, version) DO NOTHING;
