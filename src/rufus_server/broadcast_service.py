"""
Broadcast Service

Handles multi-device command broadcasts with progressive rollout.
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from uuid import uuid4

from .broadcast import (
    CommandBroadcast,
    BroadcastProgress,
    BroadcastStatus,
    RolloutStrategy,
    TargetFilter
)

logger = logging.getLogger(__name__)


class BroadcastService:
    """Service for managing command broadcasts."""

    def __init__(self, persistence, device_service):
        self.persistence = persistence
        self.device_service = device_service

    async def create_broadcast(
        self,
        broadcast: CommandBroadcast
    ) -> str:
        """
        Create a new command broadcast.

        Args:
            broadcast: Broadcast configuration

        Returns:
            broadcast_id: Unique broadcast identifier
        """
        broadcast_id = str(uuid4())

        # Get target devices
        target_devices = await self._get_target_devices(broadcast.target_filter)

        if not target_devices:
            raise ValueError("No devices match target filter")

        total_devices = len(target_devices)

        # Store broadcast record
        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO command_broadcasts (
                    broadcast_id, command_type, command_data,
                    target_filter, rollout_config,
                    created_by, total_devices
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                broadcast_id,
                broadcast.command_type,
                json.dumps(broadcast.command_data),
                json.dumps(broadcast.target_filter.dict()),
                json.dumps(broadcast.rollout_config.dict()) if broadcast.rollout_config else None,
                broadcast.created_by,
                total_devices
            )

        logger.info(
            f"Created broadcast {broadcast_id} for {total_devices} devices: {broadcast.command_type}"
        )

        # Start broadcast execution
        await self._execute_broadcast(broadcast_id, target_devices, broadcast)

        return broadcast_id

    async def _get_target_devices(self, target_filter: TargetFilter) -> List[Dict[str, Any]]:
        """Get devices matching target filter."""
        where_clause = target_filter.to_sql_where()

        async with self.persistence.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT device_id, device_type, merchant_id, status
                FROM edge_devices
                WHERE {where_clause}
                ORDER BY device_id
                """
            )

            return [dict(row) for row in rows]

    async def _execute_broadcast(
        self,
        broadcast_id: str,
        target_devices: List[Dict[str, Any]],
        broadcast: CommandBroadcast
    ):
        """Execute broadcast with rollout strategy."""
        rollout_config = broadcast.rollout_config

        if not rollout_config or rollout_config.strategy == RolloutStrategy.ALL_AT_ONCE:
            # Send to all devices immediately
            await self._send_to_devices(broadcast_id, target_devices, broadcast)
        else:
            # Progressive rollout
            await self._progressive_rollout(broadcast_id, target_devices, broadcast, rollout_config)

    async def _send_to_devices(
        self,
        broadcast_id: str,
        devices: List[Dict[str, Any]],
        broadcast: CommandBroadcast
    ):
        """Send command to list of devices."""
        success_count = 0
        failed_count = 0

        for device in devices:
            try:
                # Create individual command linked to broadcast
                command_id = await self._create_broadcast_command(
                    broadcast_id=broadcast_id,
                    device_id=device["device_id"],
                    command_type=broadcast.command_type,
                    command_data=broadcast.command_data
                )
                success_count += 1

            except Exception as e:
                logger.error(f"Failed to create command for device {device['device_id']}: {e}")
                failed_count += 1

        # Update broadcast progress
        await self._update_broadcast_progress(broadcast_id)

        logger.info(
            f"Broadcast {broadcast_id}: Sent to {success_count} devices, "
            f"{failed_count} failed"
        )

    async def _create_broadcast_command(
        self,
        broadcast_id: str,
        device_id: str,
        command_type: str,
        command_data: Dict[str, Any]
    ) -> str:
        """Create individual command linked to broadcast."""
        command_id = str(uuid4())

        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO device_commands (
                    command_id, device_id, command_type, command_data,
                    broadcast_id
                ) VALUES ($1, $2, $3, $4, $5)
                """,
                command_id,
                device_id,
                command_type,
                json.dumps(command_data),
                broadcast_id
            )

        return command_id

    async def _progressive_rollout(
        self,
        broadcast_id: str,
        target_devices: List[Dict[str, Any]],
        broadcast: CommandBroadcast,
        rollout_config
    ):
        """Execute progressive rollout with phases."""
        total_devices = len(target_devices)
        phases = rollout_config.phases

        # Update broadcast status
        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE command_broadcasts
                SET status = 'in_progress', started_at = $1
                WHERE broadcast_id = $2
                """,
                datetime.utcnow(),
                broadcast_id
            )

        # Execute each phase
        current_index = 0
        for phase_num, phase_pct in enumerate(phases, start=1):
            # Calculate devices for this phase
            phase_device_count = int(total_devices * phase_pct) - current_index
            phase_devices = target_devices[current_index:current_index + phase_device_count]

            logger.info(
                f"Broadcast {broadcast_id}: Phase {phase_num}/{len(phases)} - "
                f"{len(phase_devices)} devices ({phase_pct * 100:.1f}%)"
            )

            # Send to devices in this phase
            await self._send_to_devices(broadcast_id, phase_devices, broadcast)

            current_index += phase_device_count

            # Check circuit breaker
            progress = await self.get_broadcast_progress(broadcast_id)
            if progress.failure_rate > rollout_config.circuit_breaker_threshold:
                logger.warning(
                    f"Broadcast {broadcast_id}: Circuit breaker triggered - "
                    f"failure rate {progress.failure_rate:.2%} > threshold "
                    f"{rollout_config.circuit_breaker_threshold:.2%}"
                )

                # Pause broadcast
                await self._pause_broadcast(broadcast_id, "Circuit breaker triggered")
                return

            # Wait before next phase (except last phase)
            if phase_num < len(phases) and rollout_config.wait_seconds > 0:
                logger.info(
                    f"Broadcast {broadcast_id}: Waiting {rollout_config.wait_seconds}s "
                    f"before next phase"
                )
                # In production, this would schedule a background job
                # For now, we execute all phases immediately
                # await asyncio.sleep(rollout_config.wait_seconds)

        # Mark broadcast as completed
        await self._complete_broadcast(broadcast_id)

    async def _update_broadcast_progress(self, broadcast_id: str):
        """Update broadcast progress counters."""
        async with self.persistence.pool.acquire() as conn:
            # Count command statuses
            stats = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status = 'completed') as completed,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed
                FROM device_commands
                WHERE broadcast_id = $1
                """,
                broadcast_id
            )

            await conn.execute(
                """
                UPDATE command_broadcasts
                SET completed_devices = $1, failed_devices = $2
                WHERE broadcast_id = $3
                """,
                stats["completed"],
                stats["failed"],
                broadcast_id
            )

    async def _pause_broadcast(self, broadcast_id: str, reason: str):
        """Pause broadcast due to circuit breaker."""
        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE command_broadcasts
                SET status = 'paused', error_message = $1
                WHERE broadcast_id = $2
                """,
                reason,
                broadcast_id
            )

    async def _complete_broadcast(self, broadcast_id: str):
        """Mark broadcast as completed."""
        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE command_broadcasts
                SET status = 'completed', completed_at = $1
                WHERE broadcast_id = $2
                """,
                datetime.utcnow(),
                broadcast_id
            )

    async def get_broadcast_progress(self, broadcast_id: str) -> Optional[BroadcastProgress]:
        """Get broadcast execution progress."""
        async with self.persistence.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    broadcast_id,
                    command_type,
                    status,
                    total_devices,
                    completed_devices,
                    failed_devices,
                    created_at,
                    started_at,
                    completed_at,
                    error_message
                FROM command_broadcasts
                WHERE broadcast_id = $1
                """,
                broadcast_id
            )

            if not row:
                return None

            # Calculate stats
            total = row["total_devices"]
            completed = row["completed_devices"]
            failed = row["failed_devices"]
            in_progress = total - completed - failed

            failure_rate = failed / total if total > 0 else 0.0
            success_rate = completed / total if total > 0 else 0.0

            return BroadcastProgress(
                broadcast_id=row["broadcast_id"],
                status=BroadcastStatus(row["status"]),
                command_type=row["command_type"],
                total_devices=total,
                pending_devices=max(0, total - completed - failed - in_progress),
                in_progress_devices=in_progress,
                completed_devices=completed,
                failed_devices=failed,
                failure_rate=failure_rate,
                success_rate=success_rate,
                created_at=row["created_at"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                error_message=row["error_message"]
            )

    async def cancel_broadcast(self, broadcast_id: str) -> bool:
        """Cancel ongoing broadcast."""
        async with self.persistence.pool.acquire() as conn:
            # Update broadcast status
            result = await conn.execute(
                """
                UPDATE command_broadcasts
                SET status = 'cancelled', cancelled_at = $1
                WHERE broadcast_id = $2 AND status IN ('pending', 'in_progress', 'paused')
                """,
                datetime.utcnow(),
                broadcast_id
            )

            if result == "UPDATE 0":
                return False

            # Cancel pending commands
            await conn.execute(
                """
                UPDATE device_commands
                SET status = 'cancelled'
                WHERE broadcast_id = $1 AND status = 'pending'
                """,
                broadcast_id
            )

            logger.info(f"Cancelled broadcast {broadcast_id}")
            return True

    async def list_broadcasts(
        self,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List recent broadcasts."""
        async with self.persistence.pool.acquire() as conn:
            if status:
                rows = await conn.fetch(
                    """
                    SELECT * FROM command_broadcasts
                    WHERE status = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    status,
                    limit
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM command_broadcasts
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    limit
                )

            return [dict(row) for row in rows]
