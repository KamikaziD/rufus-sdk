"""
Command Batching

Atomic multi-command operations with sequential or parallel execution.
"""

from enum import Enum
from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class ExecutionMode(str, Enum):
    """Batch execution mode."""
    SEQUENTIAL = "sequential"  # Execute commands in order, wait for each
    PARALLEL = "parallel"      # Execute all commands simultaneously


class BatchStatus(str, Enum):
    """Batch execution status."""
    PENDING = "pending"          # Created, not started
    IN_PROGRESS = "in_progress"  # Currently executing
    COMPLETED = "completed"      # All commands completed successfully
    FAILED = "failed"            # One or more commands failed
    CANCELLED = "cancelled"      # Batch cancelled


class BatchCommand(BaseModel):
    """
    Command within a batch.

    Example:
    ```python
    BatchCommand(
        type="clear_cache",
        data={},
        sequence=1
    )
    ```
    """
    type: str = Field(description="Command type")
    data: Dict[str, Any] = Field(default={}, description="Command parameters")
    sequence: Optional[int] = Field(default=None, description="Execution sequence (for sequential mode)")


class CommandBatch(BaseModel):
    """
    Command batch definition.

    Example - Sequential:
    ```python
    batch = CommandBatch(
        device_id="macbook-m4-001",
        commands=[
            BatchCommand(type="clear_cache", data={}, sequence=1),
            BatchCommand(type="sync_now", data={}, sequence=2),
            BatchCommand(type="restart", data={"delay_seconds": 30}, sequence=3)
        ],
        execution_mode="sequential"
    )
    ```

    Example - Parallel:
    ```python
    batch = CommandBatch(
        device_id="macbook-m4-001",
        commands=[
            BatchCommand(type="health_check", data={}),
            BatchCommand(type="sync_now", data={}),
            BatchCommand(type="clear_cache", data={})
        ],
        execution_mode="parallel"
    )
    ```
    """
    device_id: str = Field(description="Target device ID")
    commands: List[BatchCommand] = Field(
        min_items=1,
        description="Commands to execute (minimum 1)"
    )
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.SEQUENTIAL,
        description="Execution mode (sequential or parallel)"
    )


class BatchProgress(BaseModel):
    """Batch execution progress."""
    batch_id: str
    device_id: str
    status: BatchStatus
    execution_mode: ExecutionMode

    total_commands: int
    completed_commands: int
    failed_commands: int
    pending_commands: int

    success_rate: float
    failure_rate: float

    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    error_message: Optional[str] = None

    # Individual command statuses
    command_statuses: List[Dict[str, Any]] = []


def validate_batch(batch: CommandBatch) -> None:
    """
    Validate batch configuration.

    Raises:
        ValueError: If batch is invalid
    """
    if not batch.commands:
        raise ValueError("Batch must have at least one command")

    if batch.execution_mode == ExecutionMode.SEQUENTIAL:
        # Validate sequence numbers for sequential mode
        sequences = [cmd.sequence for cmd in batch.commands if cmd.sequence is not None]
        if sequences:
            # Check for duplicates
            if len(sequences) != len(set(sequences)):
                raise ValueError("Duplicate sequence numbers in sequential batch")

            # Check for gaps
            sorted_sequences = sorted(sequences)
            expected = list(range(1, len(sequences) + 1))
            if sorted_sequences != expected:
                raise ValueError("Sequential batch must have consecutive sequence numbers starting from 1")
        else:
            # Auto-assign sequences
            for idx, cmd in enumerate(batch.commands, start=1):
                cmd.sequence = idx
