"""
Server Command Service — control-plane self-management commands.

Mirrors WorkerService but targets the FastAPI server process instead of
Celery workers.  The server polls this table every 30s in its background
task and executes pending commands.

Supported commands
------------------
reload_workflows  Force-reload all active workflow_definitions from DB immediately.
gc_caches         Clear WorkflowBuilder._import_cache + _workflow_configs entirely.
update_code       pip install <package==version> then SIGTERM (supervisor restarts).
restart           Graceful SIGTERM — k8s/compose restart policy brings it back.
"""

import json
import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

VALID_COMMANDS = frozenset(
    ["reload_workflows", "gc_caches", "update_code", "restart"]
)


class ServerCommandService:
    def __init__(self, persistence):
        self.persistence = persistence

    # ─────────────────────────────────────────────────────────────────────────
    # Dispatch
    # ─────────────────────────────────────────────────────────────────────────

    async def send_command(
        self,
        command: str,
        payload: Optional[Dict[str, Any]] = None,
        created_by: Optional[str] = None,
    ) -> str:
        """Queue a server command.  Returns the command id."""
        if command not in VALID_COMMANDS:
            raise ValueError(
                f"Unknown server command '{command}'. "
                f"Valid: {sorted(VALID_COMMANDS)}"
            )
        command_id = str(uuid.uuid4())
        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO server_commands (id, command, payload, status, created_by)
                VALUES ($1, $2, $3, 'pending', $4)
                """,
                command_id,
                command,
                json.dumps(payload or {}),
                created_by,
            )
        logger.info(f"Server command {command_id} ({command}) queued by {created_by}")
        return command_id

    # ─────────────────────────────────────────────────────────────────────────
    # Queries
    # ─────────────────────────────────────────────────────────────────────────

    async def list_commands(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        async with self.persistence.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, command, payload, status, result, created_by,
                       created_at, updated_at
                FROM server_commands
                ORDER BY created_at DESC
                LIMIT {limit} OFFSET {offset}
                """
            )
            return [self._serialize(dict(r)) for r in rows]

    async def cancel_command(self, command_id: str) -> bool:
        async with self.persistence.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE server_commands
                SET status = 'cancelled', updated_at = NOW()
                WHERE id = $1 AND status = 'pending'
                """,
                command_id,
            )
            return not result.endswith("0")

    # ─────────────────────────────────────────────────────────────────────────
    # Poller helpers (called by the background task in main.py)
    # ─────────────────────────────────────────────────────────────────────────

    async def claim_pending(self) -> List[Dict[str, Any]]:
        """
        Atomically claim all pending commands using SELECT … FOR UPDATE SKIP LOCKED.
        Marks them as 'running' and returns them for execution.
        """
        async with self.persistence.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    SELECT id, command, payload
                    FROM server_commands
                    WHERE status = 'pending'
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    """
                )
                if not rows:
                    return []
                ids = [r["id"] for r in rows]
                await conn.execute(
                    f"""
                    UPDATE server_commands
                    SET status = 'running', updated_at = NOW()
                    WHERE id = ANY($1::varchar[])
                    """,
                    ids,
                )
                return [dict(r) for r in rows]

    async def mark_done(
        self,
        command_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> None:
        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE server_commands
                SET status = $2, result = $3, updated_at = NOW()
                WHERE id = $1
                """,
                command_id,
                status,
                json.dumps(result or {}),
            )

    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _serialize(row: dict) -> dict:
        for field in ("created_at", "updated_at"):
            if row.get(field) and hasattr(row[field], "isoformat"):
                row[field] = row[field].isoformat()
        for field in ("payload", "result"):
            if isinstance(row.get(field), str):
                try:
                    row[field] = json.loads(row[field])
                except (ValueError, TypeError):
                    row[field] = {}
        return row
