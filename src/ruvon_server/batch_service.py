"""
Batch Service

Manages atomic multi-command batch operations.
"""

import logging
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import uuid4

from .batching import (
    CommandBatch,
    BatchProgress,
    BatchStatus,
    ExecutionMode,
    validate_batch
)

logger = logging.getLogger(__name__)


class BatchService:
    """Service for managing command batches."""

    def __init__(self, persistence, device_service):
        self.persistence = persistence
        self.device_service = device_service

    async def create_batch(self, batch: CommandBatch) -> str:
        """
        Create a new command batch.

        Args:
            batch: Batch configuration

        Returns:
            batch_id: Unique batch identifier
        """
        # Validate batch
        validate_batch(batch)

        batch_id = str(uuid4())
        total_commands = len(batch.commands)

        # Create batch record
        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO command_batches (
                    batch_id, device_id, execution_mode, total_commands
                ) VALUES ($1, $2, $3, $4)
                """,
                batch_id,
                batch.device_id,
                batch.execution_mode.value,
                total_commands
            )

            # Create individual commands linked to batch
            for cmd in batch.commands:
                command_id = str(uuid4())

                await conn.execute(
                    """
                    INSERT INTO device_commands (
                        command_id, device_id, command_type, command_data,
                        batch_id, batch_sequence, status
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    command_id,
                    batch.device_id,
                    cmd.type,
                    json.dumps(cmd.data),
                    batch_id,
                    cmd.sequence,
                    'pending'
                )

        logger.info(
            f"Created batch {batch_id} for device {batch.device_id}: "
            f"{total_commands} commands, {batch.execution_mode.value} mode"
        )

        return batch_id

    async def get_batch_progress(self, batch_id: str) -> Optional[BatchProgress]:
        """Get batch execution progress."""
        async with self.persistence.pool.acquire() as conn:
            # Get batch record
            batch_row = await conn.fetchrow(
                """
                SELECT
                    batch_id, device_id, execution_mode, status,
                    total_commands, completed_commands, failed_commands,
                    created_at, started_at, completed_at, error_message
                FROM command_batches
                WHERE batch_id = $1
                """,
                batch_id
            )

            if not batch_row:
                return None

            # Get individual command statuses
            command_rows = await conn.fetch(
                """
                SELECT
                    command_id, command_type, status, batch_sequence,
                    created_at, completed_at, error_message
                FROM device_commands
                WHERE batch_id = $1
                ORDER BY batch_sequence ASC
                """,
                batch_id
            )

            command_statuses = [
                {
                    "command_id": row["command_id"],
                    "command_type": row["command_type"],
                    "status": row["status"],
                    "sequence": row["batch_sequence"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
                    "error": row["error_message"]
                }
                for row in command_rows
            ]

            # Calculate stats
            total = batch_row["total_commands"]
            completed = batch_row["completed_commands"]
            failed = batch_row["failed_commands"]
            pending = total - completed - failed

            success_rate = completed / total if total > 0 else 0.0
            failure_rate = failed / total if total > 0 else 0.0

            return BatchProgress(
                batch_id=batch_row["batch_id"],
                device_id=batch_row["device_id"],
                status=BatchStatus(batch_row["status"]),
                execution_mode=ExecutionMode(batch_row["execution_mode"]),
                total_commands=total,
                completed_commands=completed,
                failed_commands=failed,
                pending_commands=pending,
                success_rate=success_rate,
                failure_rate=failure_rate,
                created_at=batch_row["created_at"],
                started_at=batch_row["started_at"],
                completed_at=batch_row["completed_at"],
                error_message=batch_row["error_message"],
                command_statuses=command_statuses
            )

    async def update_batch_progress(self, batch_id: str):
        """Update batch progress based on command statuses."""
        async with self.persistence.pool.acquire() as conn:
            # Count command statuses
            stats = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status = 'completed') as completed,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed,
                    COUNT(*) as total
                FROM device_commands
                WHERE batch_id = $1
                """,
                batch_id
            )

            completed = stats["completed"]
            failed = stats["failed"]
            total = stats["total"]

            # Determine batch status
            if completed + failed == total:
                if failed > 0:
                    batch_status = "failed"
                else:
                    batch_status = "completed"

                # Update with completion time
                await conn.execute(
                    """
                    UPDATE command_batches
                    SET status = $1, completed_commands = $2, failed_commands = $3,
                        completed_at = $4
                    WHERE batch_id = $5
                    """,
                    batch_status,
                    completed,
                    failed,
                    datetime.utcnow(),
                    batch_id
                )
            elif completed > 0 or failed > 0:
                batch_status = "in_progress"

                # Update progress
                await conn.execute(
                    """
                    UPDATE command_batches
                    SET status = $1, completed_commands = $2, failed_commands = $3,
                        started_at = COALESCE(started_at, $4)
                    WHERE batch_id = $5
                    """,
                    batch_status,
                    completed,
                    failed,
                    datetime.utcnow(),
                    batch_id
                )

            logger.debug(
                f"Batch {batch_id} progress: {completed}/{total} completed, "
                f"{failed} failed, status={batch_status}"
            )

    async def cancel_batch(self, batch_id: str) -> bool:
        """Cancel pending batch."""
        async with self.persistence.pool.acquire() as conn:
            # Update batch status
            result = await conn.execute(
                """
                UPDATE command_batches
                SET status = 'cancelled'
                WHERE batch_id = $1 AND status = 'pending'
                """,
                batch_id
            )

            if result == "UPDATE 0":
                return False

            # Cancel pending commands
            await conn.execute(
                """
                UPDATE device_commands
                SET status = 'cancelled'
                WHERE batch_id = $1 AND status = 'pending'
                """,
                batch_id
            )

            logger.info(f"Cancelled batch {batch_id}")
            return True

    async def list_batches(
        self,
        device_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List batches."""
        async with self.persistence.pool.acquire() as conn:
            conditions = []
            params = []
            param_count = 0

            if device_id:
                param_count += 1
                conditions.append(f"device_id = ${param_count}")
                params.append(device_id)

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
                    batch_id, device_id, execution_mode, status,
                    total_commands, completed_commands, failed_commands,
                    created_at, completed_at
                FROM command_batches
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ${param_count}
                """,
                *params
            )

            return [
                {
                    "batch_id": row["batch_id"],
                    "device_id": row["device_id"],
                    "execution_mode": row["execution_mode"],
                    "status": row["status"],
                    "total_commands": row["total_commands"],
                    "completed_commands": row["completed_commands"],
                    "failed_commands": row["failed_commands"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None
                }
                for row in rows
            ]
