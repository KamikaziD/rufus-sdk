"""
Command Broadcast System

Multi-device command distribution with progressive rollout and circuit breaker.
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class BroadcastStatus(str, Enum):
    """Broadcast execution status."""
    PENDING = "pending"        # Created, not started
    IN_PROGRESS = "in_progress"  # Currently rolling out
    PAUSED = "paused"          # Paused due to circuit breaker
    COMPLETED = "completed"    # All devices processed
    FAILED = "failed"          # Broadcast failed
    CANCELLED = "cancelled"    # Manually cancelled


class RolloutStrategy(str, Enum):
    """Rollout deployment strategy."""
    ALL_AT_ONCE = "all_at_once"  # Send to all devices immediately
    CANARY = "canary"              # Progressive rollout with phases
    BLUE_GREEN = "blue_green"      # Deploy to groups sequentially


class TargetFilter(BaseModel):
    """
    Device targeting filter for broadcasts.

    Examples:
        # All devices in a region
        TargetFilter(region="us-east-1")

        # All online MacBook devices
        TargetFilter(device_type="macbook", status="online")

        # Specific merchant's devices
        TargetFilter(merchant_id="merchant-123")

        # Custom filter expression
        TargetFilter(sql_where="metadata->>'store_id' = 'store-456'")
    """

    # Simple equality filters
    device_id: Optional[List[str]] = Field(
        default=None,
        description="Specific device IDs"
    )
    device_type: Optional[str] = Field(
        default=None,
        description="Device type filter"
    )
    merchant_id: Optional[str] = Field(
        default=None,
        description="Merchant ID filter"
    )
    status: Optional[str] = Field(
        default="online",
        description="Device status filter (default: online)"
    )
    location: Optional[str] = Field(
        default=None,
        description="Location filter"
    )

    # Advanced filtering
    sql_where: Optional[str] = Field(
        default=None,
        description="Custom SQL WHERE clause"
    )
    tags: Optional[Dict[str, str]] = Field(
        default=None,
        description="Device tags to match"
    )

    def to_sql_where(self) -> str:
        """Convert filter to SQL WHERE clause."""
        conditions = []

        if self.device_id:
            ids = "', '".join(self.device_id)
            conditions.append(f"device_id IN ('{ids}')")

        if self.device_type:
            conditions.append(f"device_type = '{self.device_type}'")

        if self.merchant_id:
            conditions.append(f"merchant_id = '{self.merchant_id}'")

        if self.status:
            conditions.append(f"status = '{self.status}'")

        if self.location:
            conditions.append(f"location = '{self.location}'")

        if self.sql_where:
            conditions.append(f"({self.sql_where})")

        if self.tags:
            for key, value in self.tags.items():
                conditions.append(f"metadata->>'{key}' = '{value}'")

        return " AND ".join(conditions) if conditions else "1=1"


class RolloutConfig(BaseModel):
    """
    Progressive rollout configuration.

    Examples:
        # Canary: 10%, 50%, 100%
        RolloutConfig(
            strategy="canary",
            phases=[0.1, 0.5, 1.0],
            wait_seconds=300
        )

        # Blue-Green: Deploy to groups sequentially
        RolloutConfig(
            strategy="blue_green",
            wait_seconds=600
        )
    """

    strategy: RolloutStrategy = Field(
        default=RolloutStrategy.ALL_AT_ONCE,
        description="Rollout strategy"
    )

    phases: List[float] = Field(
        default=[1.0],
        description="Rollout phases (percentages: 0.0-1.0)"
    )

    wait_seconds: int = Field(
        default=0,
        ge=0,
        le=86400,
        description="Wait time between phases (0-24 hours)"
    )

    circuit_breaker_threshold: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Pause if failure rate > threshold (0.0-1.0)"
    )

    auto_continue: bool = Field(
        default=True,
        description="Auto-continue to next phase or require approval"
    )


class CommandBroadcast(BaseModel):
    """
    Command broadcast model.

    Example:
    ```python
    broadcast = CommandBroadcast(
        command_type="update_config",
        command_data={"floor_limit": 50.00},
        target_filter=TargetFilter(region="us-east-1", status="online"),
        rollout_config=RolloutConfig(
            strategy="canary",
            phases=[0.1, 0.5, 1.0],
            wait_seconds=300
        )
    )
    ```
    """

    command_type: str = Field(
        description="Type of command to broadcast"
    )

    command_data: Dict[str, Any] = Field(
        default={},
        description="Command parameters"
    )

    target_filter: TargetFilter = Field(
        description="Device targeting filter"
    )

    rollout_config: Optional[RolloutConfig] = Field(
        default=None,
        description="Progressive rollout configuration"
    )

    created_by: Optional[str] = Field(
        default=None,
        description="User who created broadcast"
    )


class BroadcastProgress(BaseModel):
    """Broadcast execution progress."""

    broadcast_id: str
    status: BroadcastStatus
    command_type: str

    total_devices: int
    pending_devices: int
    in_progress_devices: int
    completed_devices: int
    failed_devices: int

    current_phase: Optional[int] = None
    total_phases: Optional[int] = None

    failure_rate: float
    success_rate: float

    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    estimated_completion: Optional[datetime] = None
    next_phase_at: Optional[datetime] = None

    error_message: Optional[str] = None
