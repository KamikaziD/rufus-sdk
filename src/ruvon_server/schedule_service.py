"""
Schedule Service

Manages command schedules and executions.
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from uuid import uuid4

from .scheduling import (
    CommandSchedule,
    ScheduleProgress,
    ScheduleExecution,
    ScheduleType,
    ScheduleStatus,
    ExecutionStatus,
    calculate_next_execution,
    validate_schedule
)

logger = logging.getLogger(__name__)


class ScheduleService:
    """Service for managing command schedules."""

    def __init__(self, persistence, device_service, broadcast_service=None):
        self.persistence = persistence
        self.device_service = device_service
        self.broadcast_service = broadcast_service

    async def create_schedule(self, schedule: CommandSchedule) -> str:
        """
        Create a new command schedule.

        Args:
            schedule: Schedule configuration

        Returns:
            schedule_id: Unique schedule identifier
        """
        # Validate schedule
        validate_schedule(schedule)

        schedule_id = str(uuid4())

        # Calculate next execution time
        next_execution = calculate_next_execution(
            schedule_type=schedule.schedule_type,
            execute_at=schedule.execute_at,
            cron_expression=schedule.cron_expression,
            timezone=schedule.timezone,
            maintenance_window_start=schedule.maintenance_window_start,
            maintenance_window_end=schedule.maintenance_window_end
        )

        # Create schedule record
        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO command_schedules (
                    schedule_id, schedule_name, device_id, target_filter,
                    command_type, command_data, schedule_type,
                    execute_at, cron_expression, timezone,
                    next_execution_at, max_executions,
                    maintenance_window_start, maintenance_window_end,
                    retry_policy, expires_at, created_by
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
                """,
                schedule_id,
                schedule.schedule_name,
                schedule.device_id,
                json.dumps(schedule.target_filter) if schedule.target_filter else None,
                schedule.command_type,
                json.dumps(schedule.command_data),
                schedule.schedule_type.value,
                schedule.execute_at,
                schedule.cron_expression,
                schedule.timezone,
                next_execution,
                schedule.max_executions,
                schedule.maintenance_window_start,
                schedule.maintenance_window_end,
                json.dumps(schedule.retry_policy) if schedule.retry_policy else None,
                schedule.expires_at,
                schedule.created_by
            )

        logger.info(
            f"Created schedule {schedule_id}: {schedule.command_type} "
            f"({schedule.schedule_type.value}), next execution: {next_execution}"
        )

        return schedule_id

    async def get_schedule(self, schedule_id: str) -> Optional[ScheduleProgress]:
        """Get schedule details and progress."""
        async with self.persistence.pool.acquire() as conn:
            # Get schedule record
            schedule_row = await conn.fetchrow(
                """
                SELECT
                    schedule_id, schedule_name, device_id, target_filter,
                    command_type, schedule_type, status, execution_count,
                    max_executions, next_execution_at, last_execution_at,
                    cron_expression, timezone, created_at, updated_at,
                    expires_at, error_message
                FROM command_schedules
                WHERE schedule_id = $1
                """,
                schedule_id
            )

            if not schedule_row:
                return None

            # Get recent executions
            execution_rows = await conn.fetch(
                """
                SELECT
                    execution_number, scheduled_for, executed_at,
                    status, command_id, broadcast_id, result_summary,
                    error_message
                FROM schedule_executions
                WHERE schedule_id = $1
                ORDER BY scheduled_for DESC
                LIMIT 10
                """,
                schedule_id
            )

            recent_executions = [
                {
                    "execution_number": row["execution_number"],
                    "scheduled_for": row["scheduled_for"].isoformat(),
                    "executed_at": row["executed_at"].isoformat() if row["executed_at"] else None,
                    "status": row["status"],
                    "command_id": row["command_id"],
                    "broadcast_id": row["broadcast_id"],
                    "result_summary": row["result_summary"],
                    "error_message": row["error_message"]
                }
                for row in execution_rows
            ]

            return ScheduleProgress(
                schedule_id=schedule_row["schedule_id"],
                schedule_name=schedule_row["schedule_name"],
                device_id=schedule_row["device_id"],
                target_filter=json.loads(schedule_row["target_filter"]) if schedule_row["target_filter"] else None,
                command_type=schedule_row["command_type"],
                schedule_type=ScheduleType(schedule_row["schedule_type"]),
                status=ScheduleStatus(schedule_row["status"]),
                execution_count=schedule_row["execution_count"],
                max_executions=schedule_row["max_executions"],
                next_execution_at=schedule_row["next_execution_at"],
                last_execution_at=schedule_row["last_execution_at"],
                cron_expression=schedule_row["cron_expression"],
                timezone=schedule_row["timezone"],
                created_at=schedule_row["created_at"],
                updated_at=schedule_row["updated_at"],
                expires_at=schedule_row["expires_at"],
                recent_executions=recent_executions,
                error_message=schedule_row["error_message"]
            )

    async def list_schedules(
        self,
        device_id: Optional[str] = None,
        status: Optional[str] = None,
        schedule_type: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List schedules with optional filters."""
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

            if schedule_type:
                param_count += 1
                conditions.append(f"schedule_type = ${param_count}")
                params.append(schedule_type)

            where_clause = " AND ".join(conditions) if conditions else "1=1"

            param_count += 1
            params.append(limit)

            rows = await conn.fetch(
                f"""
                SELECT
                    schedule_id, schedule_name, device_id, command_type,
                    schedule_type, status, execution_count, max_executions,
                    next_execution_at, last_execution_at, created_at
                FROM command_schedules
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ${param_count}
                """,
                *params
            )

            return [
                {
                    "schedule_id": row["schedule_id"],
                    "schedule_name": row["schedule_name"],
                    "device_id": row["device_id"],
                    "command_type": row["command_type"],
                    "schedule_type": row["schedule_type"],
                    "status": row["status"],
                    "execution_count": row["execution_count"],
                    "max_executions": row["max_executions"],
                    "next_execution_at": row["next_execution_at"].isoformat() if row["next_execution_at"] else None,
                    "last_execution_at": row["last_execution_at"].isoformat() if row["last_execution_at"] else None,
                    "created_at": row["created_at"].isoformat()
                }
                for row in rows
            ]

    async def pause_schedule(self, schedule_id: str) -> bool:
        """Pause an active schedule."""
        async with self.persistence.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE command_schedules
                SET status = 'paused', updated_at = $1
                WHERE schedule_id = $2 AND status = 'active'
                """,
                datetime.utcnow(),
                schedule_id
            )

            success = result == "UPDATE 1"
            if success:
                logger.info(f"Paused schedule {schedule_id}")

            return success

    async def resume_schedule(self, schedule_id: str) -> bool:
        """Resume a paused schedule."""
        async with self.persistence.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE command_schedules
                SET status = 'active', updated_at = $1
                WHERE schedule_id = $2 AND status = 'paused'
                """,
                datetime.utcnow(),
                schedule_id
            )

            success = result == "UPDATE 1"
            if success:
                logger.info(f"Resumed schedule {schedule_id}")

            return success

    async def cancel_schedule(self, schedule_id: str) -> bool:
        """Cancel a schedule."""
        async with self.persistence.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE command_schedules
                SET status = 'cancelled', updated_at = $1
                WHERE schedule_id = $2 AND status IN ('active', 'paused')
                """,
                datetime.utcnow(),
                schedule_id
            )

            success = result == "UPDATE 1"
            if success:
                logger.info(f"Cancelled schedule {schedule_id}")

            return success

    async def process_due_schedules(self) -> Dict[str, int]:
        """
        Process schedules that are due for execution.

        Returns:
            Statistics about processed schedules
        """
        async with self.persistence.pool.acquire() as conn:
            # Find schedules due for execution
            due_schedules = await conn.fetch(
                """
                SELECT
                    schedule_id, schedule_name, device_id, target_filter,
                    command_type, command_data, schedule_type,
                    cron_expression, timezone, execution_count,
                    max_executions, maintenance_window_start,
                    maintenance_window_end, retry_policy, expires_at
                FROM command_schedules
                WHERE status = 'active'
                  AND next_execution_at <= $1
                ORDER BY next_execution_at ASC
                LIMIT 100
                """,
                datetime.utcnow()
            )

            processed = 0
            failed = 0
            skipped = 0

            for schedule in due_schedules:
                try:
                    await self._execute_schedule(schedule)
                    processed += 1
                except Exception as e:
                    logger.error(f"Failed to execute schedule {schedule['schedule_id']}: {e}")
                    failed += 1

            return {
                "processed": processed,
                "failed": failed,
                "skipped": skipped
            }

    async def _execute_schedule(self, schedule_row):
        """Execute a single schedule."""
        schedule_id = schedule_row["schedule_id"]
        execution_number = schedule_row["execution_count"] + 1

        logger.info(
            f"Executing schedule {schedule_id} (execution #{execution_number}): "
            f"{schedule_row['command_type']}"
        )

        # Create execution record
        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO schedule_executions (
                    schedule_id, execution_number, scheduled_for, status
                ) VALUES ($1, $2, $3, $4)
                """,
                schedule_id,
                execution_number,
                datetime.utcnow(),
                ExecutionStatus.PENDING.value
            )

        # Dispatch command (single device) or broadcast (fleet)
        try:
            if schedule_row["device_id"]:
                # Single device command
                command_id = await self.device_service.send_command(
                    device_id=schedule_row["device_id"],
                    command_type=schedule_row["command_type"],
                    command_data=json.loads(schedule_row["command_data"]),
                    retry_policy=json.loads(schedule_row["retry_policy"]) if schedule_row["retry_policy"] else None
                )

                # Update execution record
                async with self.persistence.pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE schedule_executions
                        SET status = $1, command_id = $2, executed_at = $3
                        WHERE schedule_id = $4 AND execution_number = $5
                        """,
                        ExecutionStatus.DISPATCHED.value,
                        command_id,
                        datetime.utcnow(),
                        schedule_id,
                        execution_number
                    )

                logger.info(f"Schedule {schedule_id} dispatched command {command_id}")

            elif schedule_row["target_filter"] and self.broadcast_service:
                # Fleet broadcast
                from .broadcast import CommandBroadcast, TargetFilter

                target_filter = TargetFilter(**json.loads(schedule_row["target_filter"]))
                broadcast = CommandBroadcast(
                    command_type=schedule_row["command_type"],
                    command_data=json.loads(schedule_row["command_data"]),
                    target_filter=target_filter
                )

                broadcast_id = await self.broadcast_service.create_broadcast(broadcast)

                # Update execution record
                async with self.persistence.pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE schedule_executions
                        SET status = $1, broadcast_id = $2, executed_at = $3
                        WHERE schedule_id = $4 AND execution_number = $5
                        """,
                        ExecutionStatus.DISPATCHED.value,
                        broadcast_id,
                        datetime.utcnow(),
                        schedule_id,
                        execution_number
                    )

                logger.info(f"Schedule {schedule_id} dispatched broadcast {broadcast_id}")

            # Update schedule: increment execution count, calculate next execution
            await self._update_schedule_after_execution(schedule_row)

        except Exception as e:
            logger.error(f"Failed to dispatch schedule {schedule_id}: {e}")

            # Mark execution as failed
            async with self.persistence.pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE schedule_executions
                    SET status = $1, error_message = $2
                    WHERE schedule_id = $3 AND execution_number = $4
                    """,
                    ExecutionStatus.FAILED.value,
                    str(e),
                    schedule_id,
                    execution_number
                )

            raise

    async def _update_schedule_after_execution(self, schedule_row):
        """Update schedule after execution."""
        schedule_id = schedule_row["schedule_id"]
        execution_count = schedule_row["execution_count"] + 1
        max_executions = schedule_row["max_executions"]

        # Calculate next execution time
        next_execution = calculate_next_execution(
            schedule_type=ScheduleType(schedule_row["schedule_type"]),
            execute_at=None,  # Already executed
            cron_expression=schedule_row["cron_expression"],
            timezone=schedule_row["timezone"],
            maintenance_window_start=schedule_row["maintenance_window_start"],
            maintenance_window_end=schedule_row["maintenance_window_end"]
        )

        # Check if schedule is complete
        status = "active"
        if max_executions and execution_count >= max_executions:
            status = "completed"
            next_execution = None
        elif schedule_row["schedule_type"] == "one_time":
            status = "completed"
            next_execution = None
        elif schedule_row["expires_at"] and datetime.utcnow() >= schedule_row["expires_at"]:
            status = "expired"
            next_execution = None

        # Update schedule
        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE command_schedules
                SET execution_count = $1,
                    last_execution_at = $2,
                    next_execution_at = $3,
                    status = $4,
                    updated_at = $5
                WHERE schedule_id = $6
                """,
                execution_count,
                datetime.utcnow(),
                next_execution,
                status,
                datetime.utcnow(),
                schedule_id
            )

        logger.debug(
            f"Updated schedule {schedule_id}: execution_count={execution_count}, "
            f"next_execution={next_execution}, status={status}"
        )
