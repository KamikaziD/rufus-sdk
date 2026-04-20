"""
Worker fleet management service for the Ruvon control plane.

Sends commands to Celery workers via the worker_commands DB table.
Workers poll this table on every heartbeat (every 30s) and execute
received commands autonomously.
"""

import json
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class WorkerService:
    """Service layer for Celery worker fleet management."""

    def __init__(self, persistence):
        self.persistence = persistence

    # ─────────────────────────────────────────────────────────────────────────
    # Worker Queries
    # ─────────────────────────────────────────────────────────────────────────

    async def list_workers(
        self,
        status: Optional[str] = None,
        region: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List registered worker nodes."""
        conditions = []
        params = []

        if status:
            conditions.append(f"status = ${len(params) + 1}")
            params.append(status)
        if region:
            conditions.append(f"region = ${len(params) + 1}")
            params.append(region)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            SELECT worker_id, hostname, region, zone, capabilities, status,
                   sdk_version, last_heartbeat, pending_command_count, updated_at
            FROM worker_nodes
            {where}
            ORDER BY last_heartbeat DESC NULLS LAST
            LIMIT {limit} OFFSET {offset}
        """

        async with self.persistence.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._serialize_worker(dict(row)) for row in rows]

    async def get_worker(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """Get a single worker by ID."""
        async with self.persistence.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT worker_id, hostname, region, zone, capabilities, status,
                       sdk_version, last_heartbeat, pending_command_count, updated_at
                FROM worker_nodes
                WHERE worker_id = $1
                """,
                worker_id,
            )
            return self._serialize_worker(dict(row)) if row else None

    # ─────────────────────────────────────────────────────────────────────────
    # Command Dispatch
    # ─────────────────────────────────────────────────────────────────────────

    async def send_command(
        self,
        worker_id: str,
        command_type: str,
        command_data: Optional[Dict[str, Any]] = None,
        priority: str = 'normal',
        expires_in_seconds: Optional[int] = None,
        created_by: Optional[str] = None,
    ) -> str:
        """Queue a command for a specific worker. Returns command_id."""
        command_id = str(uuid.uuid4())
        expires_at = (
            datetime.utcnow() + timedelta(seconds=expires_in_seconds)
            if expires_in_seconds
            else None
        )

        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO worker_commands
                    (command_id, worker_id, command_type, command_data,
                     priority, expires_at, created_by)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                command_id,
                worker_id,
                command_type,
                json.dumps(command_data or {}),
                priority,
                expires_at,
                created_by,
            )
            # Bump the pending counter on the target worker
            await conn.execute(
                """
                UPDATE worker_nodes
                SET pending_command_count = pending_command_count + 1,
                    last_command_at = NOW()
                WHERE worker_id = $1
                """,
                worker_id,
            )

        logger.info(
            f"Command {command_id} ({command_type}) queued for worker {worker_id}"
        )
        return command_id

    async def broadcast_command(
        self,
        command_type: str,
        target_filter: Optional[Dict[str, Any]] = None,
        command_data: Optional[Dict[str, Any]] = None,
        priority: str = 'normal',
        expires_in_seconds: Optional[int] = None,
        created_by: Optional[str] = None,
    ) -> str:
        """
        Broadcast a command to all workers (or a subset via target_filter).
        A single row with worker_id=NULL is inserted; each matching worker
        will pick it up on their next heartbeat poll.
        Returns command_id.
        """
        command_id = str(uuid.uuid4())
        expires_at = (
            datetime.utcnow() + timedelta(seconds=expires_in_seconds)
            if expires_in_seconds
            else None
        )

        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO worker_commands
                    (command_id, worker_id, target_filter, command_type, command_data,
                     priority, expires_at, created_by)
                VALUES ($1, NULL, $2, $3, $4, $5, $6, $7)
                """,
                command_id,
                json.dumps(target_filter or {}),
                command_type,
                json.dumps(command_data or {}),
                priority,
                expires_at,
                created_by,
            )

        logger.info(
            f"Broadcast command {command_id} ({command_type}) "
            f"queued with filter {target_filter}"
        )
        return command_id

    # ─────────────────────────────────────────────────────────────────────────
    # Command Queries
    # ─────────────────────────────────────────────────────────────────────────

    async def list_commands(
        self,
        worker_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List commands, optionally filtered by worker and/or status."""
        conditions = []
        params = []

        if worker_id:
            conditions.append(f"worker_id = ${len(params) + 1}")
            params.append(worker_id)
        if status:
            conditions.append(f"status = ${len(params) + 1}")
            params.append(status)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            SELECT command_id, worker_id, command_type, command_data, status,
                   priority, created_at, delivered_at, executed_at, completed_at,
                   expires_at, result, error_message, retry_count, created_by
            FROM worker_commands
            {where}
            ORDER BY created_at DESC
            LIMIT {limit} OFFSET {offset}
        """

        async with self.persistence.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._serialize_command(dict(row)) for row in rows]

    async def get_command(self, command_id: str) -> Optional[Dict[str, Any]]:
        """Get a single command by ID."""
        async with self.persistence.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT command_id, worker_id, command_type, command_data, status,
                       priority, created_at, delivered_at, executed_at, completed_at,
                       expires_at, result, error_message, retry_count, created_by
                FROM worker_commands
                WHERE command_id = $1
                """,
                command_id,
            )
            return self._serialize_command(dict(row)) if row else None

    async def cancel_command(self, command_id: str) -> bool:
        """Cancel a pending command. Returns True if cancelled, False if already past pending."""
        async with self.persistence.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE worker_commands
                SET status = 'cancelled'
                WHERE command_id = $1 AND status = 'pending'
                """,
                command_id,
            )
            # asyncpg returns "UPDATE N"
            cancelled = result.endswith("1")
            if cancelled:
                logger.info(f"Command {command_id} cancelled.")
            return cancelled

    # ─────────────────────────────────────────────────────────────────────────
    # Serialization Helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _serialize_worker(row: dict) -> dict:
        """Normalize datetime fields and JSON strings for API responses."""
        for field in ('last_heartbeat', 'updated_at', 'last_command_at'):
            if row.get(field) and hasattr(row[field], 'isoformat'):
                row[field] = row[field].isoformat()
        if isinstance(row.get('capabilities'), str):
            try:
                row['capabilities'] = json.loads(row['capabilities'])
            except (ValueError, TypeError):
                row['capabilities'] = {}
        row.setdefault('pending_command_count', 0)
        return row

    @staticmethod
    def _serialize_command(row: dict) -> dict:
        """Normalize datetime fields and JSON strings for API responses."""
        for field in (
            'created_at', 'delivered_at', 'executed_at',
            'completed_at', 'expires_at',
        ):
            if row.get(field) and hasattr(row[field], 'isoformat'):
                row[field] = row[field].isoformat()
        for field in ('command_data', 'result'):
            if isinstance(row.get(field), str):
                try:
                    row[field] = json.loads(row[field])
                except (ValueError, TypeError):
                    row[field] = {}
        return row
