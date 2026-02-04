# Command Authorization

Role-Based Access Control (RBAC) and approval workflows for secure command execution.

## Overview

Command Authorization provides **security controls** and **approval workflows** to ensure only authorized users can execute sensitive commands, with multi-level approval for high-risk operations.

### Key Features

- **Role-Based Access Control (RBAC)**: Define roles with granular permissions
- **Authorization Policies**: Rules for who can execute which commands
- **Approval Workflows**: Multi-level approval for sensitive operations
- **Risk Levels**: Classify commands by risk (low, medium, high, critical)
- **Separation of Duties**: Prevent single-person execution of critical commands
- **Audit Integration**: All authorization decisions logged
- **Timeout Enforcement**: Approval requests expire after configured time

### Security Benefits

| Feature | Benefit |
|---------|---------|
| **RBAC** | Least privilege access control |
| **Approval Workflows** | Prevent unauthorized changes |
| **Risk Classification** | Appropriate controls per risk level |
| **Audit Trail** | Complete history of who did what |
| **Timeout Enforcement** | Prevent stale approvals |
| **Separation of Duties** | SOX/PCI-DSS compliance |

---

## Architecture

### Roles

**System Roles** (pre-defined, cannot be deleted):
- **admin**: Full system access (`*` permission)
- **operator**: Standard operations (create commands, view devices)
- **viewer**: Read-only access (view commands, devices, audit logs)
- **approver**: Can approve/reject commands

**Custom Roles**: Organizations can define additional roles

### Permissions

Permission format: `<resource>:<action>`

Examples:
- `command:create` - Can create commands
- `command:view` - Can view commands
- `device:update` - Can update devices
- `approval:approve` - Can approve commands
- `*` - Wildcard (all permissions)

### Risk Levels

| Level | Examples | Approval | Roles |
|-------|----------|----------|-------|
| **low** | Health check, view logs | No | operator, admin |
| **medium** | Config update, restart | No | operator, admin |
| **high** | Delete device, factory reset | Yes (1 approver) | admin |
| **critical** | Firmware update, system wipe | Yes (2 approvers) | admin |

### Authorization Flow

```
User Request → Check Authorization → Has Role? → Needs Approval?
                                         ↓              ↓
                                       Deny         Request Approval
                                                         ↓
                                                    Approvers Review
                                                         ↓
                                                    Approved? → Execute
                                                         ↓
                                                    Rejected → Deny
```

---

## Database Schema

### `authorization_roles` Table

```sql
CREATE TABLE authorization_roles (
    role_name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    permissions JSONB DEFAULT '[]',
    is_system_role BOOLEAN DEFAULT false
);
```

**Default Roles**:
```sql
INSERT INTO authorization_roles VALUES
    ('admin', 'Full system access', '["*"]', true),
    ('operator', 'Standard operations', '["command:create", "command:view", "device:view"]', true),
    ('viewer', 'Read-only access', '["command:view", "device:view", "audit:view"]', true),
    ('approver', 'Can approve commands', '["approval:approve", "approval:reject"]', true);
```

### `role_assignments` Table

```sql
CREATE TABLE role_assignments (
    user_id VARCHAR(100) NOT NULL,
    role_name VARCHAR(100) NOT NULL REFERENCES authorization_roles(role_name),
    assigned_by VARCHAR(100),
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    UNIQUE(user_id, role_name)
);
```

### `authorization_policies` Table

```sql
CREATE TABLE authorization_policies (
    policy_name VARCHAR(100) UNIQUE NOT NULL,
    command_type VARCHAR(100),
    device_type VARCHAR(50),
    required_roles JSONB DEFAULT '[]',
    requires_approval BOOLEAN DEFAULT false,
    approvers_required INT DEFAULT 1,
    approval_timeout_seconds INT DEFAULT 3600,
    risk_level VARCHAR(20) DEFAULT 'low',
    is_active BOOLEAN DEFAULT true
);
```

**Default Policies**:
```sql
INSERT INTO authorization_policies VALUES
    ('firmware_update_policy', 'update_firmware', NULL, '["admin"]', true, 2, 3600, 'critical', true),
    ('device_delete_policy', 'delete_device', NULL, '["admin"]', true, 1, 3600, 'high', true),
    ('config_update_policy', 'update_config', NULL, '["admin", "operator"]', false, 0, 0, 'medium', true),
    ('restart_policy', 'restart', NULL, '["admin", "operator"]', false, 0, 0, 'low', true);
```

### `command_approvals` Table

```sql
CREATE TABLE command_approvals (
    approval_id VARCHAR(100) UNIQUE NOT NULL,
    command_type VARCHAR(100) NOT NULL,
    command_data JSONB DEFAULT '{}',
    device_id VARCHAR(100),
    requested_by VARCHAR(100) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    approvers_required INT NOT NULL,
    approvers_count INT DEFAULT 0,
    expires_at TIMESTAMPTZ,
    risk_level VARCHAR(20)
);
```

### `approval_responses` Table

```sql
CREATE TABLE approval_responses (
    approval_id VARCHAR(100) NOT NULL REFERENCES command_approvals(approval_id),
    approver_id VARCHAR(100) NOT NULL,
    response VARCHAR(20) NOT NULL,  -- approved, rejected
    comment TEXT,
    responded_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(approval_id, approver_id)
);
```

---

## API Reference

### Check Authorization

**Endpoint**: `POST /api/v1/authorization/check`

**Request Body**:
```json
{
  "user_id": "user-123",
  "command_type": "update_firmware",
  "device_type": "macbook"
}
```

**Response**:
```json
{
  "authorized": false,
  "requires_approval": true,
  "user_roles": ["operator"],
  "missing_roles": ["admin"],
  "reason": "User lacks required roles: admin",
  "policy": {
    "policy_name": "firmware_update_policy",
    "risk_level": "critical",
    "approvers_required": 2
  }
}
```

### Request Approval

**Endpoint**: `POST /api/v1/approvals`

**Request Body**:
```json
{
  "command_type": "update_firmware",
  "command_data": {"version": "2.5.0"},
  "device_id": "macbook-m4-001",
  "requested_by": "user-123",
  "approvers_required": 2,
  "approval_timeout_seconds": 3600,
  "risk_level": "critical",
  "reason": "Critical security patch for CVE-2026-1234"
}
```

**Response**:
```json
{
  "approval_id": "approval-abc-123",
  "status": "pending",
  "message": "Approval request created"
}
```

### Get Approval Status

**Endpoint**: `GET /api/v1/approvals/{approval_id}`

**Response**:
```json
{
  "approval_id": "approval-abc-123",
  "command_type": "update_firmware",
  "command_data": {"version": "2.5.0"},
  "device_id": "macbook-m4-001",
  "requested_by": "user-123",
  "requested_at": "2026-02-04T14:00:00Z",
  "status": "approved",
  "approvers_required": 2,
  "approvers_count": 2,
  "expires_at": "2026-02-04T15:00:00Z",
  "completed_at": "2026-02-04T14:30:00Z",
  "reason": "Critical security patch for CVE-2026-1234",
  "command_id": "cmd-001",
  "risk_level": "critical",
  "responses": [
    {
      "approver_id": "approver-456",
      "response": "approved",
      "comment": "Security patch is critical - approved",
      "responded_at": "2026-02-04T14:15:00Z"
    },
    {
      "approver_id": "approver-789",
      "response": "approved",
      "comment": "Verified patch contents - approved",
      "responded_at": "2026-02-04T14:30:00Z"
    }
  ]
}
```

### List Approvals

**Endpoint**: `GET /api/v1/approvals`

**Query Parameters**:
- `user_id` (optional): Filter by requester
- `status` (optional): Filter by status (pending, approved, rejected, expired)
- `limit` (optional): Max results (default: 50)

**Response**:
```json
{
  "approvals": [
    {
      "approval_id": "approval-abc-123",
      "command_type": "update_firmware",
      "device_id": "macbook-m4-001",
      "requested_by": "user-123",
      "requested_at": "2026-02-04T14:00:00Z",
      "status": "pending",
      "approvers_required": 2,
      "approvers_count": 1,
      "expires_at": "2026-02-04T15:00:00Z",
      "risk_level": "critical",
      "reason": "Critical security patch"
    }
  ],
  "count": 1
}
```

### Approve Command

**Endpoint**: `POST /api/v1/approvals/{approval_id}/approve`

**Request Body**:
```json
{
  "approver_id": "approver-456",
  "comment": "Verified patch contents - approved"
}
```

**Response**:
```json
{
  "approval_id": "approval-abc-123",
  "status": "approved",
  "message": "Approval recorded"
}
```

### Reject Command

**Endpoint**: `POST /api/v1/approvals/{approval_id}/reject`

**Request Body**:
```json
{
  "approver_id": "approver-456",
  "comment": "Need more testing before deploying to production"
}
```

**Response**:
```json
{
  "approval_id": "approval-abc-123",
  "status": "rejected",
  "message": "Rejection recorded"
}
```

### Cancel Approval

**Endpoint**: `DELETE /api/v1/approvals/{approval_id}`

**Response**:
```json
{
  "approval_id": "approval-abc-123",
  "status": "cancelled",
  "message": "Approval request cancelled"
}
```

---

## CLI Usage

### Check Authorization

```bash
# Check if user can execute command
python cloud_admin.py check-authorization user-123 update_firmware macbook

# Output:
# Authorization Check: update_firmware
#   User: user-123
#   Authorized: ✗ No
#   Requires Approval: Yes
#   User Roles: operator
#   Missing Roles: admin
#   Policy: firmware_update_policy
#   Risk Level: critical
#   Approvers Required: 2
#   Reason: User lacks required roles: admin
```

### Request Approval

```bash
python cloud_admin.py request-approval \
  '{"command_type":"update_firmware","command_data":{"version":"2.5.0"},"device_id":"macbook-m4-001","requested_by":"user-123","approvers_required":2,"risk_level":"critical","reason":"Critical security patch"}'

# Output:
# ✓ Approval request created
#   Approval ID: approval-abc-123
#   Status: pending
```

### List Approvals

```bash
# List all pending approvals
python cloud_admin.py list-approvals "" pending

# List approvals for specific user
python cloud_admin.py list-approvals user-123

# Output:
# Found 2 approval request(s):
#
# ⋯ approval-abc... - update_firmware
#   Device: macbook-m4-001
#   Requested By: user-123
#   Status: pending | Risk: critical
#   Approvals: 1/2
#   Expires: 2026-02-04T15:00:00Z
#   Reason: Critical security patch
```

### Check Approval Status

```bash
python cloud_admin.py approval-status approval-abc-123

# Output:
# Approval: approval-abc-123
#   Command: update_firmware
#   Device: macbook-m4-001
#   Requested By: user-123
#   Requested At: 2026-02-04T14:00:00Z
#   Status: pending
#   Risk Level: critical
#   Approvals: 1/2
#   Expires: 2026-02-04T15:00:00Z
#   Reason: Critical security patch
#
#   Responses:
#     ✓ approver-456 - approved
#        Comment: Security patch is critical - approved
```

### Approve Command

```bash
python cloud_admin.py approve-command approval-abc-123 approver-789 "Verified patch contents - approved"

# Output:
# ✓ Approval recorded
#   Approval ID: approval-abc-123
#   Status: approved
```

### Reject Command

```bash
python cloud_admin.py reject-command approval-abc-123 approver-789 "Need more testing first"

# Output:
# ✓ Rejection recorded
#   Approval ID: approval-abc-123
#   Status: rejected
```

---

## Common Workflows

### 1. Firmware Update with Approval

**Scenario**: Operator wants to update firmware (requires admin approval)

```bash
# Step 1: Operator checks authorization
python cloud_admin.py check-authorization user-123 update_firmware
# Result: Not authorized, requires approval

# Step 2: Operator requests approval
python cloud_admin.py request-approval \
  '{"command_type":"update_firmware","command_data":{"version":"2.5.0"},"device_id":"macbook-m4-001","requested_by":"user-123","approvers_required":2,"risk_level":"critical","reason":"Security patch"}'
# Result: approval-abc-123 created

# Step 3: First admin approves
python cloud_admin.py approve-command approval-abc-123 admin-456 "Approved"

# Step 4: Check status (need 2 approvals)
python cloud_admin.py approval-status approval-abc-123
# Result: 1/2 approvals

# Step 5: Second admin approves
python cloud_admin.py approve-command approval-abc-123 admin-789 "Approved"

# Step 6: Approval complete, execute command
python cloud_admin.py send-command macbook-m4-001 update_firmware '{"version":"2.5.0"}'
```

### 2. Emergency Access (Admin Override)

**Scenario**: Admin needs to execute command immediately

```bash
# Admin has "*" permission - no approval needed
python cloud_admin.py check-authorization admin-123 update_firmware
# Result: Authorized (no approval required due to admin role)

# Execute immediately
python cloud_admin.py send-command macbook-m4-001 update_firmware '{"version":"2.5.0"}'
```

### 3. Approval Timeout/Expiration

**Scenario**: Approval request not acted upon within timeout

```bash
# Request approval with 1-hour timeout
python cloud_admin.py request-approval \
  '{"command_type":"update_firmware",...,"approval_timeout_seconds":3600}'

# ... 1 hour passes ...

# Check status
python cloud_admin.py approval-status approval-abc-123
# Result: status = "expired"

# Must create new approval request
```

### 4. Rejection Workflow

**Scenario**: Approver rejects command

```bash
# Approver rejects
python cloud_admin.py reject-command approval-abc-123 approver-456 "Need more testing"
# Result: Immediate rejection (single rejection = denied)

# Requester can create new request after addressing concerns
```

---

## Best Practices

### Role Design

**1. Principle of Least Privilege**:
- Grant minimum permissions needed
- Use specific permissions (`command:create`) over wildcards (`*`)
- Regular audit of role assignments

**2. Role Hierarchy**:
```
admin (*)
  └─ operator (command:*, device:view)
      └─ viewer (command:view, device:view)
```

**3. Separation of Duties**:
- Requester cannot approve own requests
- Different roles for execution vs approval
- Multi-person approval for critical operations

### Policy Configuration

**Risk-Based Policies**:
```sql
-- Low risk: No approval needed
INSERT INTO authorization_policies VALUES
    ('health_check_policy', 'health_check', NULL, '["operator"]', false, 0, 0, 'low', true);

-- Medium risk: Role-based only
INSERT INTO authorization_policies VALUES
    ('restart_policy', 'restart', NULL, '["operator", "admin"]', false, 0, 0, 'medium', true);

-- High risk: 1 approval required
INSERT INTO authorization_policies VALUES
    ('delete_device_policy', 'delete_device', NULL, '["admin"]', true, 1, 3600, 'high', true);

-- Critical risk: 2 approvals required
INSERT INTO authorization_policies VALUES
    ('firmware_update_policy', 'update_firmware', NULL, '["admin"]', true, 2, 3600, 'critical', true);
```

### Approval Timeouts

| Risk Level | Timeout | Rationale |
|------------|---------|-----------|
| **critical** | 1-4 hours | Urgent but requires thorough review |
| **high** | 4-24 hours | Important but not urgent |
| **medium** | 1-7 days | Standard review cycle |

### Audit Integration

All authorization events are automatically logged:
- Authorization checks (approved/denied)
- Approval requests created
- Approval responses (approved/rejected)
- Approval expirations
- Policy changes

Query authorization events:
```bash
python cloud_admin.py audit-query "" "" "" "auth_*"
```

---

## Compliance

### SOX Compliance

**Separation of Duties**: Command Authorization ensures no single person can execute critical operations without oversight.

**Controls**:
- Requester ≠ Approver (enforced by approval system)
- Admin access requires 2 approvals for critical operations
- All authorization decisions audited

### PCI-DSS Compliance

**Access Control** (Requirement 7.1): Limit access to cardholder data by business need-to-know.

**Controls**:
- Role-based access control
- Least privilege principle
- Regular access reviews via audit logs

### GDPR Compliance

**Data Access Tracking**: All data access operations logged for GDPR Article 30 compliance.

**Controls**:
- Authorization checks logged
- User roles documented
- Audit trail for access requests

---

## Troubleshooting

### Authorization Denied

**Problem**: User cannot execute command

**Solutions**:
1. Check user roles: `python cloud_admin.py check-authorization user-id command-type`
2. Verify policy: Check `authorization_policies` table
3. Assign missing roles via `role_assignments` table
4. If approval required, create approval request

### Approval Stuck

**Problem**: Approval request not progressing

**Solutions**:
1. Check approval status: `python cloud_admin.py approval-status approval-id`
2. Verify approvers have `approval:approve` permission
3. Check expiration time - may have expired
4. Review approval responses - may have been rejected

### Permission Issues

**Problem**: User has role but still denied

**Solutions**:
1. Check role permissions: `SELECT * FROM authorization_roles WHERE role_name = 'role-name'`
2. Verify role assignment hasn't expired: `SELECT * FROM role_assignments WHERE user_id = 'user-id'`
3. Check policy required_roles matches user roles
4. Ensure policy is active: `is_active = true`

---

## Related Documentation

- [COMMAND_SYSTEM.md](./COMMAND_SYSTEM.md) - Command architecture overview
- [COMMAND_AUDIT_LOG.md](./COMMAND_AUDIT_LOG.md) - Audit logging for compliance
- [COMMAND_SCHEDULING.md](./COMMAND_SCHEDULING.md) - Time-based execution

---

## Summary

Command Authorization provides **production-grade security** for Rufus Edge:

- ✅ Role-Based Access Control (RBAC)
- ✅ Multi-level approval workflows
- ✅ Risk-based policies (low/medium/high/critical)
- ✅ Separation of duties (SOX/PCI-DSS)
- ✅ Timeout enforcement
- ✅ Complete audit trail
- ✅ Flexible policy configuration

All sensitive commands are protected by authorization checks and approval workflows, ensuring secure operations in production environments.
