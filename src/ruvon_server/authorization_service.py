"""
Authorization Service

Manages RBAC and approval workflows for command authorization.
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from uuid import uuid4

from .authorization import (
    AuthorizationRole,
    RoleAssignment,
    AuthorizationPolicy,
    ApprovalRequest,
    ApprovalInfo,
    AuthorizationResult,
    ApprovalStatus,
    ApprovalResponse,
    RiskLevel,
    check_permission,
    get_user_permissions
)

logger = logging.getLogger(__name__)


class AuthorizationService:
    """Service for command authorization and approval workflows."""

    def __init__(self, persistence):
        self.persistence = persistence

    async def get_user_roles(self, user_id: str) -> List[AuthorizationRole]:
        """Get all roles assigned to a user."""
        async with self.persistence.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT r.role_name, r.description, r.permissions, r.is_system_role
                FROM authorization_roles r
                JOIN role_assignments ra ON r.role_name = ra.role_name
                WHERE ra.user_id = $1
                  AND (ra.expires_at IS NULL OR ra.expires_at > NOW())
                """,
                user_id
            )

            return [
                AuthorizationRole(
                    role_name=row["role_name"],
                    description=row["description"],
                    permissions=json.loads(row["permissions"]),
                    is_system_role=row["is_system_role"]
                )
                for row in rows
            ]

    async def get_policy(
        self,
        command_type: str,
        device_type: Optional[str] = None
    ) -> Optional[AuthorizationPolicy]:
        """Get authorization policy for a command."""
        async with self.persistence.pool.acquire() as conn:
            # Try exact match first
            row = await conn.fetchrow(
                """
                SELECT
                    policy_name, command_type, device_type, required_roles,
                    requires_approval, approvers_required, approval_timeout_seconds,
                    allowed_during_maintenance_only, risk_level, is_active
                FROM authorization_policies
                WHERE command_type = $1
                  AND (device_type = $2 OR device_type IS NULL)
                  AND is_active = true
                ORDER BY device_type NULLS LAST
                LIMIT 1
                """,
                command_type,
                device_type
            )

            if not row:
                # Try wildcard policy (NULL command_type)
                row = await conn.fetchrow(
                    """
                    SELECT
                        policy_name, command_type, device_type, required_roles,
                        requires_approval, approvers_required, approval_timeout_seconds,
                        allowed_during_maintenance_only, risk_level, is_active
                    FROM authorization_policies
                    WHERE command_type IS NULL
                      AND (device_type = $1 OR device_type IS NULL)
                      AND is_active = true
                    LIMIT 1
                    """,
                    device_type
                )

            if not row:
                return None

            return AuthorizationPolicy(
                policy_name=row["policy_name"],
                command_type=row["command_type"],
                device_type=row["device_type"],
                required_roles=json.loads(row["required_roles"]),
                requires_approval=row["requires_approval"],
                approvers_required=row["approvers_required"],
                approval_timeout_seconds=row["approval_timeout_seconds"],
                allowed_during_maintenance_only=row["allowed_during_maintenance_only"],
                risk_level=RiskLevel(row["risk_level"]),
                is_active=row["is_active"]
            )

    async def check_authorization(
        self,
        user_id: str,
        command_type: str,
        device_type: Optional[str] = None
    ) -> AuthorizationResult:
        """
        Check if user is authorized to execute a command.

        Args:
            user_id: User ID
            command_type: Command type
            device_type: Device type (optional)

        Returns:
            Authorization result with decision and details
        """
        # Get user roles
        roles = await self.get_user_roles(user_id)
        user_role_names = [role.role_name for role in roles]

        # Get applicable policy
        policy = await self.get_policy(command_type, device_type)

        # If no policy, default to deny
        if not policy:
            return AuthorizationResult(
                authorized=False,
                requires_approval=False,
                user_roles=user_role_names,
                missing_roles=[],
                policy=None,
                reason="No authorization policy found for this command"
            )

        # Check if user has required roles
        required_roles = set(policy.required_roles)
        user_roles_set = set(user_role_names)

        # Check for admin wildcard or role match
        has_required_role = (
            "admin" in user_roles_set or  # Admin has access to everything
            bool(required_roles & user_roles_set)  # User has at least one required role
        )

        if not has_required_role:
            missing = list(required_roles - user_roles_set)
            return AuthorizationResult(
                authorized=False,
                requires_approval=policy.requires_approval,
                user_roles=user_role_names,
                missing_roles=missing,
                policy=policy,
                reason=f"User lacks required roles: {', '.join(missing)}"
            )

        # User has required role
        return AuthorizationResult(
            authorized=True,
            requires_approval=policy.requires_approval,
            user_roles=user_role_names,
            missing_roles=[],
            policy=policy,
            reason="Authorized" + (" (approval required)" if policy.requires_approval else "")
        )

    async def request_approval(self, request: ApprovalRequest) -> str:
        """
        Request approval for a command.

        Args:
            request: Approval request

        Returns:
            approval_id: Unique approval request identifier
        """
        approval_id = str(uuid4())
        expires_at = datetime.utcnow() + timedelta(seconds=request.approval_timeout_seconds)

        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO command_approvals (
                    approval_id, command_type, command_data, device_id, target_filter,
                    requested_by, approvers_required, expires_at, risk_level, reason
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                approval_id,
                request.command_type,
                json.dumps(request.command_data),
                request.device_id,
                json.dumps(request.target_filter) if request.target_filter else None,
                request.requested_by,
                request.approvers_required,
                expires_at,
                request.risk_level.value,
                request.reason
            )

        logger.info(
            f"Created approval request {approval_id}: {request.command_type} "
            f"(requested_by={request.requested_by}, risk={request.risk_level.value})"
        )

        return approval_id

    async def get_approval(self, approval_id: str) -> Optional[ApprovalInfo]:
        """Get approval request details."""
        async with self.persistence.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    approval_id, command_type, command_data, device_id, target_filter,
                    requested_by, requested_at, status, approvers_required, approvers_count,
                    expires_at, completed_at, reason, command_id, risk_level
                FROM command_approvals
                WHERE approval_id = $1
                """,
                approval_id
            )

            if not row:
                return None

            # Get approval responses
            response_rows = await conn.fetch(
                """
                SELECT approver_id, response, comment, responded_at
                FROM approval_responses
                WHERE approval_id = $1
                ORDER BY responded_at ASC
                """,
                approval_id
            )

            responses = [
                {
                    "approver_id": r["approver_id"],
                    "response": r["response"],
                    "comment": r["comment"],
                    "responded_at": r["responded_at"].isoformat()
                }
                for r in response_rows
            ]

            return ApprovalInfo(
                approval_id=row["approval_id"],
                command_type=row["command_type"],
                command_data=json.loads(row["command_data"]),
                device_id=row["device_id"],
                target_filter=json.loads(row["target_filter"]) if row["target_filter"] else None,
                requested_by=row["requested_by"],
                requested_at=row["requested_at"],
                status=ApprovalStatus(row["status"]),
                approvers_required=row["approvers_required"],
                approvers_count=row["approvers_count"],
                expires_at=row["expires_at"],
                completed_at=row["completed_at"],
                reason=row["reason"],
                command_id=row["command_id"],
                risk_level=RiskLevel(row["risk_level"]),
                responses=responses
            )

    async def respond_to_approval(
        self,
        approval_id: str,
        approver_id: str,
        response: ApprovalResponse,
        comment: Optional[str] = None
    ) -> bool:
        """
        Respond to an approval request.

        Args:
            approval_id: Approval request ID
            approver_id: Approver user ID
            response: Approval or rejection
            comment: Optional comment

        Returns:
            True if response recorded successfully
        """
        async with self.persistence.pool.acquire() as conn:
            # Check if approval is still pending
            approval = await conn.fetchrow(
                """
                SELECT status, approvers_required, approvers_count, expires_at
                FROM command_approvals
                WHERE approval_id = $1
                """,
                approval_id
            )

            if not approval:
                logger.warning(f"Approval {approval_id} not found")
                return False

            if approval["status"] != "pending":
                logger.warning(f"Approval {approval_id} is not pending (status={approval['status']})")
                return False

            if datetime.utcnow() > approval["expires_at"]:
                # Mark as expired
                await conn.execute(
                    """
                    UPDATE command_approvals
                    SET status = 'expired', completed_at = NOW()
                    WHERE approval_id = $1
                    """,
                    approval_id
                )
                logger.warning(f"Approval {approval_id} has expired")
                return False

            # Record response
            try:
                await conn.execute(
                    """
                    INSERT INTO approval_responses (approval_id, approver_id, response, comment)
                    VALUES ($1, $2, $3, $4)
                    """,
                    approval_id,
                    approver_id,
                    response.value,
                    comment
                )
            except Exception as e:
                # Approver already responded
                logger.warning(f"Approver {approver_id} already responded to {approval_id}")
                return False

            # Update approval count and status
            if response == ApprovalResponse.REJECTED:
                # Immediate rejection
                await conn.execute(
                    """
                    UPDATE command_approvals
                    SET status = 'rejected', completed_at = NOW()
                    WHERE approval_id = $1
                    """,
                    approval_id
                )
                logger.info(f"Approval {approval_id} rejected by {approver_id}")
            else:
                # Count approvals
                new_count = approval["approvers_count"] + 1

                if new_count >= approval["approvers_required"]:
                    # Approval threshold met
                    await conn.execute(
                        """
                        UPDATE command_approvals
                        SET status = 'approved', approvers_count = $1, completed_at = NOW()
                        WHERE approval_id = $2
                        """,
                        new_count,
                        approval_id
                    )
                    logger.info(
                        f"Approval {approval_id} approved ({new_count}/{approval['approvers_required']})"
                    )
                else:
                    # Still need more approvals
                    await conn.execute(
                        """
                        UPDATE command_approvals
                        SET approvers_count = $1
                        WHERE approval_id = $2
                        """,
                        new_count,
                        approval_id
                    )
                    logger.info(
                        f"Approval {approval_id} progress: {new_count}/{approval['approvers_required']}"
                    )

            return True

    async def list_approvals(
        self,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List approval requests."""
        async with self.persistence.pool.acquire() as conn:
            conditions = []
            params = []
            param_count = 0

            if user_id:
                param_count += 1
                conditions.append(f"requested_by = ${param_count}")
                params.append(user_id)

            if status:
                param_count += 1
                conditions.append(f"status = ${param_count}")
                params.append(status)

            where_clause = " AND ".join(conditions) if conditions else "1=1"

            param_count += 1
            params.append(limit)

            rows = await conn.fetch(
                f"""
                SELECT
                    approval_id, command_type, device_id, requested_by,
                    requested_at, status, approvers_required, approvers_count,
                    expires_at, risk_level, reason
                FROM command_approvals
                WHERE {where_clause}
                ORDER BY requested_at DESC
                LIMIT ${param_count}
                """,
                *params
            )

            return [
                {
                    "approval_id": row["approval_id"],
                    "command_type": row["command_type"],
                    "device_id": row["device_id"],
                    "requested_by": row["requested_by"],
                    "requested_at": row["requested_at"].isoformat(),
                    "status": row["status"],
                    "approvers_required": row["approvers_required"],
                    "approvers_count": row["approvers_count"],
                    "expires_at": row["expires_at"].isoformat(),
                    "risk_level": row["risk_level"],
                    "reason": row["reason"]
                }
                for row in rows
            ]

    async def cancel_approval(self, approval_id: str, user_id: str) -> bool:
        """Cancel a pending approval request."""
        async with self.persistence.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE command_approvals
                SET status = 'cancelled', completed_at = NOW()
                WHERE approval_id = $1 AND requested_by = $2 AND status = 'pending'
                """,
                approval_id,
                user_id
            )

            success = result == "UPDATE 1"
            if success:
                logger.info(f"Cancelled approval {approval_id} by {user_id}")

            return success

    async def link_approval_to_command(self, approval_id: str, command_id: str) -> bool:
        """Link approval to executed command."""
        async with self.persistence.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE command_approvals
                SET command_id = $1
                WHERE approval_id = $2 AND status = 'approved'
                """,
                command_id,
                approval_id
            )

            return result == "UPDATE 1"
