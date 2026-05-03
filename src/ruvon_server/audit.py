"""
Command Audit Log

Comprehensive audit logging for compliance tracking and regulatory reporting.
"""

from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Audit event types."""
    # Command lifecycle
    COMMAND_CREATED = "command_created"
    COMMAND_SENT = "command_sent"
    COMMAND_RECEIVED = "command_received"
    COMMAND_EXECUTING = "command_executing"
    COMMAND_COMPLETED = "command_completed"
    COMMAND_FAILED = "command_failed"
    COMMAND_CANCELLED = "command_cancelled"
    COMMAND_EXPIRED = "command_expired"
    COMMAND_RETRY_SCHEDULED = "command_retry_scheduled"
    COMMAND_RETRIED = "command_retried"

    # Broadcast lifecycle
    BROADCAST_CREATED = "broadcast_created"
    BROADCAST_STARTED = "broadcast_started"
    BROADCAST_COMPLETED = "broadcast_completed"
    BROADCAST_FAILED = "broadcast_failed"
    BROADCAST_CANCELLED = "broadcast_cancelled"
    BROADCAST_PAUSED = "broadcast_paused"

    # Batch lifecycle
    BATCH_CREATED = "batch_created"
    BATCH_STARTED = "batch_started"
    BATCH_COMPLETED = "batch_completed"
    BATCH_FAILED = "batch_failed"
    BATCH_CANCELLED = "batch_cancelled"

    # Schedule lifecycle
    SCHEDULE_CREATED = "schedule_created"
    SCHEDULE_EXECUTED = "schedule_executed"
    SCHEDULE_PAUSED = "schedule_paused"
    SCHEDULE_RESUMED = "schedule_resumed"
    SCHEDULE_CANCELLED = "schedule_cancelled"

    # Template operations
    TEMPLATE_CREATED = "template_created"
    TEMPLATE_UPDATED = "template_updated"
    TEMPLATE_DELETED = "template_deleted"
    TEMPLATE_APPLIED = "template_applied"

    # Device events
    DEVICE_REGISTERED = "device_registered"
    DEVICE_UPDATED = "device_updated"
    DEVICE_DELETED = "device_deleted"
    DEVICE_HEARTBEAT = "device_heartbeat"
    DEVICE_OFFLINE = "device_offline"
    DEVICE_ONLINE = "device_online"

    # Policy events
    POLICY_CREATED = "policy_created"
    POLICY_UPDATED = "policy_updated"
    POLICY_DEPLOYED = "policy_deployed"
    POLICY_DELETED = "policy_deleted"

    # Security events
    AUTH_SUCCESS = "auth_success"
    AUTH_FAILURE = "auth_failure"
    AUTH_LOGOUT = "auth_logout"
    API_KEY_CREATED = "api_key_created"
    API_KEY_REVOKED = "api_key_revoked"

    # System events
    SYSTEM_STARTUP = "system_startup"
    SYSTEM_SHUTDOWN = "system_shutdown"
    SYSTEM_ERROR = "system_error"


class ActorType(str, Enum):
    """Type of entity that performed the action."""
    USER = "user"               # Human user via UI/CLI
    API = "api"                 # API client with API key
    SYSTEM = "system"           # Internal system component
    SCHEDULER = "scheduler"     # Scheduler daemon
    DEVICE = "device"           # Edge device
    WEBHOOK = "webhook"         # External webhook
    AUTOMATION = "automation"   # Automated workflow


class AuditEvent(BaseModel):
    """
    Audit event for command operations.

    Example:
    ```python
    event = AuditEvent(
        event_type=EventType.COMMAND_CREATED,
        command_id="cmd-abc-123",
        device_id="macbook-m4-001",
        command_type="restart",
        command_data={"delay_seconds": 10},
        actor_type=ActorType.USER,
        actor_id="user-123",
        actor_ip="192.168.1.100",
        status="pending"
    )
    ```
    """
    # Event identification
    event_type: EventType = Field(description="Type of audit event")
    command_id: Optional[str] = Field(None, description="Command ID (if applicable)")
    broadcast_id: Optional[str] = Field(None, description="Broadcast ID (if applicable)")
    batch_id: Optional[str] = Field(None, description="Batch ID (if applicable)")
    schedule_id: Optional[str] = Field(None, description="Schedule ID (if applicable)")

    # Target information
    device_id: Optional[str] = Field(None, description="Target device ID")
    device_type: Optional[str] = Field(None, description="Device type")
    merchant_id: Optional[str] = Field(None, description="Merchant ID")

    # Command details
    command_type: Optional[str] = Field(None, description="Command type")
    command_data: Dict[str, Any] = Field(default={}, description="Command parameters")

    # Actor information
    actor_type: ActorType = Field(description="Type of actor")
    actor_id: str = Field(description="Actor identifier")
    actor_ip: Optional[str] = Field(None, description="Actor IP address")
    user_agent: Optional[str] = Field(None, description="User agent string")

    # Result information
    status: Optional[str] = Field(None, description="Operation status")
    result_data: Dict[str, Any] = Field(default={}, description="Result data")
    error_message: Optional[str] = Field(None, description="Error message (if failed)")

    # Timing
    duration_ms: Optional[int] = Field(None, description="Execution duration in milliseconds")

    # Context
    session_id: Optional[str] = Field(None, description="Session ID")
    request_id: Optional[str] = Field(None, description="Request ID (for tracing)")
    parent_audit_id: Optional[str] = Field(None, description="Parent audit event ID")

    # Compliance
    data_region: Optional[str] = Field(None, description="Data region (for data residency)")
    compliance_tags: List[str] = Field(default=[], description="Compliance tags (e.g., ['pci', 'sox'])")


class AuditQuery(BaseModel):
    """Query parameters for audit log search."""
    # Time range
    start_time: Optional[datetime] = Field(None, description="Start of time range")
    end_time: Optional[datetime] = Field(None, description="End of time range")

    # Entity filters
    device_id: Optional[str] = None
    merchant_id: Optional[str] = None
    command_id: Optional[str] = None
    broadcast_id: Optional[str] = None
    batch_id: Optional[str] = None
    schedule_id: Optional[str] = None

    # Event filters
    event_types: Optional[List[str]] = Field(None, description="Filter by event types")
    command_types: Optional[List[str]] = Field(None, description="Filter by command types")
    actor_type: Optional[str] = None
    actor_id: Optional[str] = None

    # Status filter
    status: Optional[str] = None

    # Full-text search
    search_text: Optional[str] = Field(None, description="Full-text search query")

    # Pagination
    limit: int = Field(default=100, ge=1, le=1000, description="Max results")
    offset: int = Field(default=0, ge=0, description="Result offset")

    # Sorting
    order_by: str = Field(default="timestamp", description="Sort field")
    order_direction: str = Field(default="desc", description="Sort direction (asc/desc)")


class AuditLogEntry(BaseModel):
    """Audit log entry (database record)."""
    audit_id: str
    event_type: str
    command_id: Optional[str]
    broadcast_id: Optional[str]
    batch_id: Optional[str]
    schedule_id: Optional[str]
    device_id: Optional[str]
    device_type: Optional[str]
    merchant_id: Optional[str]
    command_type: Optional[str]
    command_data: Dict[str, Any]
    actor_type: str
    actor_id: str
    actor_ip: Optional[str]
    user_agent: Optional[str]
    status: Optional[str]
    result_data: Dict[str, Any]
    error_message: Optional[str]
    timestamp: datetime
    duration_ms: Optional[int]
    session_id: Optional[str]
    request_id: Optional[str]
    parent_audit_id: Optional[str]
    data_region: Optional[str]
    compliance_tags: List[str]


class AuditQueryResult(BaseModel):
    """Result of audit log query."""
    entries: List[AuditLogEntry]
    total_count: int
    limit: int
    offset: int
    has_more: bool


class AuditExportFormat(str, Enum):
    """Export format for audit logs."""
    JSON = "json"
    CSV = "csv"
    JSONL = "jsonl"  # JSON Lines (one JSON object per line)


class AuditRetentionPolicy(BaseModel):
    """Audit log retention policy."""
    policy_name: str = Field(description="Policy name")
    retention_days: int = Field(ge=1, description="Number of days to retain logs")
    event_types: List[str] = Field(default=[], description="Event types (empty = all)")
    archive_before_delete: bool = Field(default=True, description="Archive logs before deletion")
    archive_location: Optional[str] = Field(None, description="Archive storage location (S3, etc.)")
    is_active: bool = Field(default=True, description="Whether policy is active")


def get_compliance_tags(event_type: EventType, command_type: Optional[str] = None) -> List[str]:
    """
    Get compliance tags for an audit event.

    Returns tags like ['pci', 'sox', 'gdpr'] based on event type and context.
    """
    tags = []

    # PCI-DSS compliance (payment operations)
    payment_commands = ["process_payment", "refund", "void", "authorize"]
    if command_type in payment_commands:
        tags.append("pci")

    # All command operations are compliance-relevant
    if "command" in event_type.value or "broadcast" in event_type.value:
        tags.append("audit_trail")

    # Security events
    if "auth" in event_type.value or "api_key" in event_type.value:
        tags.append("security")

    # Device lifecycle events
    if "device" in event_type.value:
        tags.append("device_management")

    return tags
