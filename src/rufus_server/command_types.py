"""
Device Command Types and Priorities

Defines command types and their routing (heartbeat vs websocket).
"""

from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel


class CommandPriority(str, Enum):
    """Command priority levels."""
    LOW = "low"           # Can wait, no rush
    NORMAL = "normal"     # Standard priority
    HIGH = "high"         # Important but not critical
    CRITICAL = "critical" # Urgent, use WebSocket


class CommandType(str, Enum):
    """Available command types."""

    # Device Management (NORMAL - heartbeat)
    RESTART = "restart"
    SHUTDOWN = "shutdown"
    REBOOT = "reboot"

    # Configuration (NORMAL - heartbeat)
    UPDATE_CONFIG = "update_config"
    RELOAD_CONFIG = "reload_config"

    # Maintenance (LOW - heartbeat)
    BACKUP = "backup"
    SCHEDULE_BACKUP = "schedule_backup"
    CLEAR_CACHE = "clear_cache"
    CLEANUP = "cleanup"
    HEALTH_CHECK = "health_check"

    # Sync Operations (NORMAL - heartbeat)
    SYNC_NOW = "sync_now"
    FORCE_SYNC = "force_sync"

    # Workflow Operations (NORMAL - heartbeat)
    START_WORKFLOW = "start_workflow"
    CANCEL_WORKFLOW = "cancel_workflow"
    RETRY_WORKFLOW = "retry_workflow"

    # Artifact Management (NORMAL - heartbeat)
    UPDATE_ARTIFACT = "update_artifact"
    ROLLBACK_ARTIFACT = "rollback_artifact"

    # Critical Operations (CRITICAL - websocket)
    EMERGENCY_STOP = "emergency_stop"
    FRAUD_ALERT = "fraud_alert"
    SECURITY_LOCKDOWN = "security_lockdown"
    DISABLE_TRANSACTIONS = "disable_transactions"
    ENABLE_TRANSACTIONS = "enable_transactions"


# Command routing configuration
COMMAND_ROUTING: Dict[CommandType, CommandPriority] = {
    # Device Management
    CommandType.RESTART: CommandPriority.NORMAL,
    CommandType.SHUTDOWN: CommandPriority.NORMAL,
    CommandType.REBOOT: CommandPriority.NORMAL,

    # Configuration
    CommandType.UPDATE_CONFIG: CommandPriority.NORMAL,
    CommandType.RELOAD_CONFIG: CommandPriority.NORMAL,

    # Maintenance
    CommandType.BACKUP: CommandPriority.LOW,
    CommandType.SCHEDULE_BACKUP: CommandPriority.LOW,
    CommandType.CLEAR_CACHE: CommandPriority.LOW,
    CommandType.CLEANUP: CommandPriority.LOW,
    CommandType.HEALTH_CHECK: CommandPriority.NORMAL,

    # Sync Operations
    CommandType.SYNC_NOW: CommandPriority.NORMAL,
    CommandType.FORCE_SYNC: CommandPriority.HIGH,

    # Workflow Operations
    CommandType.START_WORKFLOW: CommandPriority.NORMAL,
    CommandType.CANCEL_WORKFLOW: CommandPriority.HIGH,
    CommandType.RETRY_WORKFLOW: CommandPriority.NORMAL,

    # Artifact Management
    CommandType.UPDATE_ARTIFACT: CommandPriority.NORMAL,
    CommandType.ROLLBACK_ARTIFACT: CommandPriority.HIGH,

    # Critical Operations (WebSocket)
    CommandType.EMERGENCY_STOP: CommandPriority.CRITICAL,
    CommandType.FRAUD_ALERT: CommandPriority.CRITICAL,
    CommandType.SECURITY_LOCKDOWN: CommandPriority.CRITICAL,
    CommandType.DISABLE_TRANSACTIONS: CommandPriority.CRITICAL,
    CommandType.ENABLE_TRANSACTIONS: CommandPriority.CRITICAL,
}


def get_command_priority(command_type: str) -> CommandPriority:
    """Get priority for a command type."""
    try:
        cmd_type = CommandType(command_type)
        return COMMAND_ROUTING.get(cmd_type, CommandPriority.NORMAL)
    except ValueError:
        return CommandPriority.NORMAL


def should_use_websocket(command_type: str) -> bool:
    """Determine if command should use WebSocket (critical) or heartbeat."""
    priority = get_command_priority(command_type)
    return priority == CommandPriority.CRITICAL


class DeviceCommand(BaseModel):
    """
    Device command model.

    Example with retry policy:
    ```json
    {
      "type": "restart",
      "data": {"delay_seconds": 10},
      "priority": "normal",
      "timeout_seconds": 300,
      "retry_policy": {
        "max_retries": 3,
        "initial_delay_seconds": 10,
        "backoff_strategy": "exponential",
        "backoff_multiplier": 2.0,
        "max_delay_seconds": 300
      }
    }
    ```
    """
    type: str
    data: Dict[str, Any] = {}
    version: Optional[str] = None  # Command schema version
    priority: CommandPriority = CommandPriority.NORMAL
    timeout_seconds: int = 300
    retry_policy: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "type": self.type,
            "data": self.data,
            "priority": self.priority,
            "timeout_seconds": self.timeout_seconds,
            "retry_policy": self.retry_policy
        }
