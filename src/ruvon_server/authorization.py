"""
Command Authorization

Role-based access control (RBAC) and approval workflows for commands.
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """Command risk level."""
    LOW = "low"           # Standard operations
    MEDIUM = "medium"     # Moderately risky
    HIGH = "high"         # High-risk operations
    CRITICAL = "critical" # Critical system changes


class ApprovalStatus(str, Enum):
    """Approval request status."""
    PENDING = "pending"       # Awaiting approval
    APPROVED = "approved"     # Approved and ready to execute
    REJECTED = "rejected"     # Rejected by approver
    EXPIRED = "expired"       # Approval timeout reached
    CANCELLED = "cancelled"   # Cancelled by requester


class ApprovalResponse(str, Enum):
    """Approver response."""
    APPROVED = "approved"
    REJECTED = "rejected"


class AuthorizationRole(BaseModel):
    """
    Authorization role definition.

    Example:
    ```python
    role = AuthorizationRole(
        role_name="operator",
        description="Standard device operations",
        permissions=["command:create", "command:view", "device:view"]
    )
    ```
    """
    role_name: str = Field(description="Unique role name")
    description: Optional[str] = Field(None, description="Role description")
    permissions: List[str] = Field(default=[], description="List of permissions")
    is_system_role: bool = Field(default=False, description="System role (cannot be deleted)")


class RoleAssignment(BaseModel):
    """User to role assignment."""
    user_id: str = Field(description="User ID")
    role_name: str = Field(description="Role name")
    assigned_by: Optional[str] = Field(None, description="Who assigned the role")
    assigned_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = Field(None, description="Expiration time (optional)")


class AuthorizationPolicy(BaseModel):
    """
    Command authorization policy.

    Example - Firmware Update (requires approval):
    ```python
    policy = AuthorizationPolicy(
        policy_name="firmware_update_policy",
        command_type="update_firmware",
        required_roles=["admin"],
        requires_approval=True,
        approvers_required=2,
        approval_timeout_seconds=3600,
        risk_level=RiskLevel.CRITICAL
    )
    ```

    Example - Restart (no approval needed):
    ```python
    policy = AuthorizationPolicy(
        policy_name="restart_policy",
        command_type="restart",
        required_roles=["admin", "operator"],
        requires_approval=False,
        risk_level=RiskLevel.LOW
    )
    ```
    """
    policy_name: str = Field(description="Unique policy name")
    command_type: Optional[str] = Field(None, description="Command type (NULL = all commands)")
    device_type: Optional[str] = Field(None, description="Device type filter (NULL = all)")
    required_roles: List[str] = Field(default=[], description="Roles that can execute")
    requires_approval: bool = Field(default=False, description="Whether approval is required")
    approvers_required: int = Field(default=1, ge=1, description="Number of approvals needed")
    approval_timeout_seconds: int = Field(default=3600, description="Approval timeout")
    allowed_during_maintenance_only: bool = Field(default=False, description="Maintenance window only")
    risk_level: RiskLevel = Field(default=RiskLevel.LOW, description="Risk level")
    is_active: bool = Field(default=True, description="Whether policy is active")


class ApprovalRequest(BaseModel):
    """
    Command approval request.

    Example:
    ```python
    request = ApprovalRequest(
        command_type="update_firmware",
        command_data={"version": "2.5.0"},
        device_id="macbook-m4-001",
        requested_by="user-123",
        approvers_required=2,
        approval_timeout_seconds=3600,
        risk_level=RiskLevel.CRITICAL,
        reason="Critical security patch"
    )
    ```
    """
    command_type: str = Field(description="Command type")
    command_data: Dict[str, Any] = Field(default={}, description="Command parameters")
    device_id: Optional[str] = Field(None, description="Target device")
    target_filter: Optional[Dict[str, Any]] = Field(None, description="Fleet filter")
    requested_by: str = Field(description="Requester user ID")
    approvers_required: int = Field(ge=1, description="Number of approvals needed")
    approval_timeout_seconds: int = Field(default=3600, description="Timeout in seconds")
    risk_level: RiskLevel = Field(default=RiskLevel.MEDIUM, description="Risk level")
    reason: Optional[str] = Field(None, description="Reason for request")


class ApprovalInfo(BaseModel):
    """Approval request information."""
    approval_id: str
    command_type: str
    command_data: Dict[str, Any]
    device_id: Optional[str]
    target_filter: Optional[Dict[str, Any]]
    requested_by: str
    requested_at: datetime
    status: ApprovalStatus
    approvers_required: int
    approvers_count: int
    expires_at: datetime
    completed_at: Optional[datetime]
    reason: Optional[str]
    command_id: Optional[str]
    risk_level: RiskLevel
    responses: List[Dict[str, Any]] = []


class AuthorizationResult(BaseModel):
    """Result of authorization check."""
    authorized: bool = Field(description="Whether action is authorized")
    requires_approval: bool = Field(default=False, description="Whether approval is required")
    user_roles: List[str] = Field(default=[], description="User's roles")
    missing_roles: List[str] = Field(default=[], description="Required roles user doesn't have")
    policy: Optional[AuthorizationPolicy] = Field(None, description="Applied policy")
    reason: Optional[str] = Field(None, description="Authorization decision reason")


def check_permission(user_permissions: List[str], required_permission: str) -> bool:
    """
    Check if user has required permission.

    Supports wildcard permissions:
    - "*" matches everything
    - "command:*" matches all command permissions
    - "command:create" matches exact permission

    Args:
        user_permissions: List of user's permissions
        required_permission: Required permission

    Returns:
        True if user has permission
    """
    # Check for wildcard admin permission
    if "*" in user_permissions:
        return True

    # Check exact match
    if required_permission in user_permissions:
        return True

    # Check wildcard match (e.g., "command:*" matches "command:create")
    parts = required_permission.split(":")
    if len(parts) == 2:
        wildcard = f"{parts[0]}:*"
        if wildcard in user_permissions:
            return True

    return False


def get_user_permissions(roles: List[AuthorizationRole]) -> List[str]:
    """
    Get all permissions for a list of roles.

    Args:
        roles: List of roles

    Returns:
        Deduplicated list of all permissions
    """
    permissions = set()
    for role in roles:
        permissions.update(role.permissions)
    return list(permissions)
