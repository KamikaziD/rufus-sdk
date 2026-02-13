# Command Templates

## Overview

Command Templates are reusable command sets for standard operating procedures (SOPs). Instead of manually triggering multiple commands, templates execute predefined workflows with a single action.

## Benefits

- **Standardization**: Enforce consistent procedures across teams
- **Efficiency**: Execute multi-step workflows with one command
- **Compliance**: Ensure regulatory procedures are followed correctly
- **Variables**: Customize templates with parameters
- **Version Control**: Track template changes over time

## Use Cases

**Security Incident Response**:
- Emergency lockdown procedure
- Fraud detection response
- System isolation protocol

**Maintenance Operations**:
- Graceful restart with cleanup
- Backup and health check
- Configuration update workflow

**Compliance**:
- End-of-day procedures
- Audit preparation workflow
- Regulatory reporting sequence

## Predefined Templates

### security-lockdown

**Description**: Emergency security lockdown procedure

**Commands**:
1. `disable_transactions` - Stop all transaction processing
2. `security_lockdown` - Enable security lockdown mode
3. `fraud_alert` - Trigger fraud alert

**Usage**:
```bash
# Single device
python cloud_admin.py apply-template security-lockdown macbook-m4-001

# Broadcast to all online devices
python cloud_admin.py apply-template-broadcast security-lockdown '{"status": "online"}'
```

### soft-restart

**Description**: Graceful restart with cleanup

**Commands**:
1. `clear_cache` - Clear local caches
2. `sync_now` - Sync pending data
3. `restart` - Restart with configurable delay

**Variables**:
- `delay_seconds` (integer, default: 30) - Delay before restart

**Usage**:
```bash
# Default delay (30s)
python cloud_admin.py apply-template soft-restart macbook-m4-001

# Custom delay (60s)
python cloud_admin.py apply-template soft-restart macbook-m4-001 '{"delay_seconds": 60}'

# Broadcast with custom delay
python cloud_admin.py apply-template-broadcast soft-restart \
  '{"device_type": "macbook"}' \
  '{"delay_seconds": 120}'
```

### maintenance-mode

**Description**: Enter maintenance mode with backup

**Commands**:
1. `disable_transactions` - Disable transactions for maintenance
2. `backup` - Perform backup to cloud
3. `health_check` - Run health diagnostics

**Usage**:
```bash
python cloud_admin.py apply-template maintenance-mode macbook-m4-001

# Broadcast to merchant
python cloud_admin.py apply-template-broadcast maintenance-mode \
  '{"merchant_id": "merchant-123"}'
```

### health-check-full

**Description**: Comprehensive health diagnostics

**Commands**:
1. `health_check` - System health check
2. `sync_now` - Force sync to verify connectivity
3. `clear_cache` - Clear caches to free resources

**Usage**:
```bash
python cloud_admin.py apply-template health-check-full macbook-m4-001
```

## Creating Custom Templates

### API

```json
POST /api/v1/templates
{
  "template_name": "my-custom-workflow",
  "description": "Custom workflow description",
  "commands": [
    {
      "type": "sync_now",
      "data": {}
    },
    {
      "type": "restart",
      "data": {
        "delay_seconds": "{{delay}}"
      }
    }
  ],
  "variables": [
    {
      "name": "delay",
      "description": "Restart delay in seconds",
      "type": "integer",
      "default": 30,
      "required": false
    }
  ],
  "tags": ["maintenance", "custom"],
  "version": "1.0.0"
}
```

### Template Structure

**Required Fields**:
- `template_name`: Unique identifier (alphanumeric, dashes, underscores)
- `description`: Human-readable description
- `commands`: Array of commands to execute

**Optional Fields**:
- `variables`: Template variables for customization
- `tags`: Tags for categorization
- `version`: Version string (default: "1.0.0")
- `is_active`: Whether template is active (default: true)

### Commands

Each command has:
- `type`: Command type (e.g., "restart", "backup")
- `data`: Command parameters (may contain variables)

**Example**:
```json
{
  "type": "restart",
  "data": {
    "delay_seconds": "{{delay}}"
  }
}
```

### Variables

Variables enable template customization:

**Variable Definition**:
```json
{
  "name": "delay",
  "description": "Restart delay in seconds",
  "type": "integer",
  "default": 30,
  "required": false
}
```

**Variable Types**:
- `string`: Text values
- `integer`: Numeric values
- `boolean`: True/false
- `object`: Complex structures

**Variable Substitution**:
- Use `{{variable_name}}` in command data
- Variables resolved before execution
- Default values used if not provided
- Required variables must be provided

## CLI Usage

### List Templates

```bash
python cloud_admin.py list-templates
```

Output:
```
  COMMAND TEMPLATES
  ══════════════════════════════════════════════════════════════════

  📋 security-lockdown (v1.0.0)
    Description:  Emergency security lockdown procedure
    Commands:     3
    Tags:         security, emergency

  📋 soft-restart (v1.0.0)
    Description:  Graceful restart with cleanup
    Commands:     3
    Tags:         maintenance
```

### Get Template Details

```bash
python cloud_admin.py get-template soft-restart
```

Output:
```
  TEMPLATE: soft-restart
  ══════════════════════════════════════════════════════════════════

  Name:         soft-restart
  Description:  Graceful restart with cleanup
  Version:      1.0.0
  Tags:         maintenance

  Commands:
    1. clear_cache
    2. sync_now
    3. restart
       Data: {"delay_seconds": "{{delay_seconds}}"}

  Variables:
    • delay_seconds: Delay before restart in seconds [default: 30]
```

### Apply to Single Device

```bash
# Default variables
python cloud_admin.py apply-template soft-restart macbook-m4-001

# Custom variables
python cloud_admin.py apply-template soft-restart macbook-m4-001 \
  '{"delay_seconds": 60}'
```

### Apply as Broadcast

```bash
# All devices in merchant
python cloud_admin.py apply-template-broadcast maintenance-mode \
  '{"merchant_id": "merchant-123"}'

# With variables
python cloud_admin.py apply-template-broadcast soft-restart \
  '{"device_type": "macbook"}' \
  '{"delay_seconds": 120}'

# With rollout configuration
python cloud_admin.py apply-template-broadcast soft-restart \
  '{"status": "online"}' \
  '{"delay_seconds": 90}' \
  '{"strategy": "canary", "phases": [0.1, 0.5, 1.0], "wait_seconds": 300}'
```

## API Reference

### Create Template

```
POST /api/v1/templates
```

**Request**: See "Creating Custom Templates" section above

**Response**:
```json
{
  "template_name": "my-custom-workflow",
  "status": "created",
  "message": "Template 'my-custom-workflow' created successfully"
}
```

### Get Template

```
GET /api/v1/templates/{template_name}
```

**Response**:
```json
{
  "template_name": "soft-restart",
  "description": "Graceful restart with cleanup",
  "commands": [...],
  "variables": [...],
  "version": "1.0.0",
  "tags": ["maintenance"],
  "is_active": true
}
```

### List Templates

```
GET /api/v1/templates?active_only=true&tag=maintenance
```

**Response**:
```json
{
  "total": 2,
  "templates": [
    {
      "template_name": "soft-restart",
      "description": "Graceful restart with cleanup",
      "version": "1.0.0",
      "tags": ["maintenance"],
      "command_count": 3,
      "created_by": "admin",
      "created_at": "2026-02-03T20:00:00Z",
      "is_active": true
    }
  ]
}
```

### Delete Template

```
DELETE /api/v1/templates/{template_name}
```

**Response**:
```json
{
  "template_name": "my-custom-workflow",
  "status": "deleted",
  "message": "Template 'my-custom-workflow' deleted successfully"
}
```

**Note**: Templates are soft-deleted (marked inactive), not physically removed.

### Apply Template

```
POST /api/v1/templates/{template_name}/apply
```

**Single Device**:
```json
{
  "device_id": "macbook-m4-001",
  "variables": {"delay": 60}
}
```

**Broadcast**:
```json
{
  "target_filter": {"merchant_id": "merchant-123"},
  "variables": {"delay": 60},
  "rollout_config": {
    "strategy": "canary",
    "phases": [0.1, 0.5, 1.0],
    "wait_seconds": 300
  }
}
```

## Examples

### Emergency Security Response

```bash
# Immediate lockdown of all devices
python cloud_admin.py apply-template-broadcast security-lockdown \
  '{"status": "online"}'
```

### Scheduled Maintenance

```bash
# Gradual rollout with 10-minute wait between phases
python cloud_admin.py apply-template-broadcast maintenance-mode \
  '{"merchant_id": "merchant-123"}' \
  '{}' \
  '{"strategy": "canary", "phases": [0.25, 0.75, 1.0], "wait_seconds": 600}'
```

### Fleet Health Check

```bash
# All devices - immediate execution
python cloud_admin.py apply-template-broadcast health-check-full \
  '{"status": "online"}'
```

### Custom Restart Delay

```bash
# Restart with 2-minute delay
python cloud_admin.py apply-template soft-restart macbook-m4-001 \
  '{"delay_seconds": 120}'
```

## Best Practices

### Template Design

**Keep templates focused**:
- 3-5 commands per template
- Single purpose (restart, backup, lockdown)
- Clear, descriptive names

**Use variables sparingly**:
- Only for values that frequently change
- Provide sensible defaults
- Document variable purpose clearly

**Version your templates**:
- Increment version on breaking changes
- Keep old versions for rollback
- Document changes

### Naming Conventions

**Template names**:
- Lowercase with hyphens: `soft-restart`
- Descriptive: `maintenance-mode` not `mode1`
- Prefix for organization: `security-*`, `maint-*`

**Variables**:
- snake_case: `delay_seconds`
- Descriptive: `backup_target` not `target`
- Include units: `delay_seconds` not `delay`

### Security

**Critical operations**:
- Require approval for security templates
- Audit all template executions
- Restrict who can create templates

**Variable validation**:
- Validate variable types
- Check ranges (e.g., delay 0-3600)
- Sanitize inputs

## Troubleshooting

### Template Not Found

**Error**: `Template 'my-template' not found`

**Solutions**:
- Check template name (case-sensitive)
- List templates to verify it exists
- Check if template is active

### Variable Substitution Failed

**Error**: `Required variable 'delay' not provided`

**Solutions**:
- Provide all required variables
- Check variable names match template definition
- Use correct JSON format

### Multiple Commands in Broadcast

**Warning**: `Template has 3 commands. Only first command will be broadcast.`

**Explanation**: Current broadcast system sends one command type at a time. Templates with multiple commands create individual commands for single devices, but only broadcast the first for multi-device operations.

**Workaround**: Apply template to individual devices or wait for command batching feature.

## Database Schema

```sql
CREATE TABLE command_templates (
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
```

## Migration

```bash
psql -U rufus -d rufus < docker/migrations/add_command_templates.sql
```

This also creates default templates (security-lockdown, soft-restart, etc.).
