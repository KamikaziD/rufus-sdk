"""
Command Scheduling

One-time and recurring command execution with cron-style scheduling.
"""

from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime, time
from pydantic import BaseModel, Field, validator
from croniter import croniter


class ScheduleType(str, Enum):
    """Schedule type."""
    ONE_TIME = "one_time"      # Execute once at specific time
    RECURRING = "recurring"    # Execute on cron schedule


class ScheduleStatus(str, Enum):
    """Schedule status."""
    ACTIVE = "active"          # Currently active
    PAUSED = "paused"          # Temporarily paused
    COMPLETED = "completed"    # All executions complete
    CANCELLED = "cancelled"    # Cancelled by user
    EXPIRED = "expired"        # Expired (past expires_at)


class ExecutionStatus(str, Enum):
    """Schedule execution status."""
    PENDING = "pending"        # Scheduled but not yet executed
    DISPATCHED = "dispatched"  # Command/broadcast dispatched
    COMPLETED = "completed"    # Execution completed successfully
    FAILED = "failed"          # Execution failed
    SKIPPED = "skipped"        # Skipped (e.g., outside maintenance window)


class CommandSchedule(BaseModel):
    """
    Command schedule definition.

    Examples:

    One-time schedule:
    ```python
    schedule = CommandSchedule(
        schedule_name="Maintenance restart",
        device_id="macbook-m4-001",
        command_type="restart",
        command_data={"delay_seconds": 10},
        schedule_type="one_time",
        execute_at=datetime(2026, 2, 5, 2, 0, 0),  # 2 AM tomorrow
        timezone="America/New_York"
    )
    ```

    Recurring schedule with maintenance window:
    ```python
    schedule = CommandSchedule(
        schedule_name="Daily health check",
        device_id="pos-terminal-042",
        command_type="health_check",
        command_data={},
        schedule_type="recurring",
        cron_expression="0 2 * * *",  # Daily at 2 AM
        timezone="UTC",
        maintenance_window_start=time(2, 0, 0),
        maintenance_window_end=time(6, 0, 0)
    )
    ```

    Fleet recurring schedule:
    ```python
    schedule = CommandSchedule(
        schedule_name="Weekly cache clear",
        target_filter={"device_type": "macbook", "status": "online"},
        command_type="clear_cache",
        schedule_type="recurring",
        cron_expression="0 3 * * 0",  # Every Sunday at 3 AM
        max_executions=52  # Run for 1 year
    )
    ```
    """
    schedule_name: Optional[str] = Field(None, description="Human-readable schedule name")

    # Target (either single device or fleet)
    device_id: Optional[str] = Field(None, description="Target device ID (for single device)")
    target_filter: Optional[Dict[str, Any]] = Field(None, description="Target filter (for fleet)")

    # Command configuration
    command_type: str = Field(description="Command type to execute")
    command_data: Dict[str, Any] = Field(default={}, description="Command parameters")

    # Schedule configuration
    schedule_type: ScheduleType = Field(description="Schedule type (one_time or recurring)")
    execute_at: Optional[datetime] = Field(None, description="Execution time (for one_time)")
    cron_expression: Optional[str] = Field(None, description="Cron expression (for recurring)")
    timezone: str = Field(default="UTC", description="Timezone for scheduling")

    # Execution limits
    max_executions: Optional[int] = Field(None, ge=1, description="Max number of executions (NULL = unlimited)")
    expires_at: Optional[datetime] = Field(None, description="Schedule expiration time")

    # Maintenance window (optional)
    maintenance_window_start: Optional[time] = Field(None, description="Maintenance window start time")
    maintenance_window_end: Optional[time] = Field(None, description="Maintenance window end time")

    # Retry configuration (optional)
    retry_policy: Optional[Dict[str, Any]] = Field(None, description="Retry policy for failed executions")

    # Metadata
    created_by: Optional[str] = Field(None, description="User who created schedule")

    @validator("target_filter", "device_id")
    def validate_target(cls, v, values):
        """Ensure either device_id or target_filter is set, not both."""
        device_id = values.get("device_id")
        target_filter = values.get("target_filter")

        # This validator runs for both fields, so check both
        if "target_filter" in values:
            if device_id and target_filter:
                raise ValueError("Cannot specify both device_id and target_filter")
            if not device_id and not target_filter:
                raise ValueError("Must specify either device_id or target_filter")

        return v

    @validator("execute_at")
    def validate_one_time_schedule(cls, v, values):
        """Validate one-time schedule has execute_at."""
        if values.get("schedule_type") == ScheduleType.ONE_TIME:
            if not v:
                raise ValueError("one_time schedule requires execute_at")
            if v <= datetime.utcnow():
                raise ValueError("execute_at must be in the future")
        return v

    @validator("cron_expression")
    def validate_recurring_schedule(cls, v, values):
        """Validate recurring schedule has valid cron expression."""
        if values.get("schedule_type") == ScheduleType.RECURRING:
            if not v:
                raise ValueError("recurring schedule requires cron_expression")

            # Validate cron expression
            try:
                croniter(v)
            except Exception as e:
                raise ValueError(f"Invalid cron expression: {e}")

        return v

    @validator("maintenance_window_end")
    def validate_maintenance_window(cls, v, values):
        """Validate maintenance window."""
        start = values.get("maintenance_window_start")
        if start and v:
            # Both start and end provided - this is valid
            pass
        elif start or v:
            raise ValueError("Must specify both maintenance_window_start and maintenance_window_end")

        return v


class ScheduleProgress(BaseModel):
    """Schedule execution progress and statistics."""
    schedule_id: str
    schedule_name: Optional[str]
    device_id: Optional[str]
    target_filter: Optional[Dict[str, Any]]
    command_type: str
    schedule_type: ScheduleType
    status: ScheduleStatus

    # Execution tracking
    execution_count: int
    max_executions: Optional[int]
    next_execution_at: Optional[datetime]
    last_execution_at: Optional[datetime]

    # Timestamps
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime]

    # Cron config (for recurring)
    cron_expression: Optional[str] = None
    timezone: str = "UTC"

    # Recent executions
    recent_executions: List[Dict[str, Any]] = []

    # Error tracking
    error_message: Optional[str] = None


class ScheduleExecution(BaseModel):
    """Individual execution of a schedule."""
    schedule_id: str
    execution_number: int
    scheduled_for: datetime
    status: ExecutionStatus
    command_id: Optional[str] = None  # For single device
    broadcast_id: Optional[str] = None  # For fleet
    result_summary: Optional[str] = None
    error_message: Optional[str] = None
    executed_at: Optional[datetime] = None


def calculate_next_execution(
    schedule_type: ScheduleType,
    execute_at: Optional[datetime] = None,
    cron_expression: Optional[str] = None,
    timezone: str = "UTC",
    maintenance_window_start: Optional[time] = None,
    maintenance_window_end: Optional[time] = None
) -> Optional[datetime]:
    """
    Calculate next execution time for a schedule.

    Args:
        schedule_type: Schedule type (one_time or recurring)
        execute_at: Execution time for one-time schedules
        cron_expression: Cron expression for recurring schedules
        timezone: Timezone for scheduling
        maintenance_window_start: Optional maintenance window start
        maintenance_window_end: Optional maintenance window end

    Returns:
        Next execution time, or None if schedule is complete
    """
    if schedule_type == ScheduleType.ONE_TIME:
        # One-time schedule: return execute_at if in future
        if execute_at and execute_at > datetime.utcnow():
            return execute_at
        return None

    elif schedule_type == ScheduleType.RECURRING:
        if not cron_expression:
            return None

        # Calculate next cron execution
        cron = croniter(cron_expression, datetime.utcnow())
        next_time = cron.get_next(datetime)

        # If maintenance window specified, adjust to fit window
        if maintenance_window_start and maintenance_window_end:
            next_time = _adjust_to_maintenance_window(
                next_time,
                maintenance_window_start,
                maintenance_window_end
            )

        return next_time

    return None


def _adjust_to_maintenance_window(
    next_time: datetime,
    window_start: time,
    window_end: time
) -> datetime:
    """
    Adjust execution time to fit within maintenance window.

    If next_time falls outside the window, move it to the start of the window.
    """
    execution_time = next_time.time()

    # Check if execution time is within window
    if window_start <= window_end:
        # Normal window (e.g., 02:00 - 06:00)
        if not (window_start <= execution_time <= window_end):
            # Move to start of window
            next_time = next_time.replace(
                hour=window_start.hour,
                minute=window_start.minute,
                second=window_start.second
            )
    else:
        # Window crosses midnight (e.g., 22:00 - 02:00)
        if not (execution_time >= window_start or execution_time <= window_end):
            # Move to start of window
            next_time = next_time.replace(
                hour=window_start.hour,
                minute=window_start.minute,
                second=window_start.second
            )

    return next_time


def validate_schedule(schedule: CommandSchedule) -> None:
    """
    Validate schedule configuration.

    Raises:
        ValueError: If schedule is invalid
    """
    # Validation handled by Pydantic validators
    pass
