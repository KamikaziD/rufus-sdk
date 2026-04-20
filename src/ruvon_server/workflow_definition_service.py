"""
Workflow Definition Service — DB-backed YAML definitions with hot-reload.

Stores versioned YAML workflow definitions in PostgreSQL so the server can
hot-reload them without a restart (via WorkflowBuilder.reload_workflow_type).
"""

import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class WorkflowDefinitionService:
    """
    CRUD service for the workflow_definitions table.

    Each upload creates a new version row.  The server background poller calls
    get_all_active() every 60s and calls WorkflowBuilder.reload_workflow_type()
    for any type whose version has increased since last check.
    """

    def __init__(self, persistence):
        self.persistence = persistence

    # ─────────────────────────────────────────────────────────────────────────
    # Reads
    # ─────────────────────────────────────────────────────────────────────────

    async def get_all_active(self) -> List[Dict[str, Any]]:
        """Return the latest active version for every workflow type."""
        async with self.persistence.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (workflow_type)
                    id, workflow_type, version, yaml_content,
                    is_active, description, uploaded_by, created_at
                FROM workflow_definitions
                WHERE is_active = TRUE
                ORDER BY workflow_type, version DESC
                """
            )
            return [self._serialize(dict(r)) for r in rows]

    async def list_definitions(self) -> List[Dict[str, Any]]:
        """Return summary rows (no yaml_content) for the list endpoint."""
        async with self.persistence.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (workflow_type)
                    id, workflow_type, version, is_active,
                    description, uploaded_by, created_at
                FROM workflow_definitions
                ORDER BY workflow_type, version DESC
                """
            )
            return [self._serialize(dict(r)) for r in rows]

    async def get_definition(self, workflow_type: str) -> Optional[Dict[str, Any]]:
        """Return the current active YAML for a workflow type."""
        async with self.persistence.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, workflow_type, version, yaml_content,
                       is_active, description, uploaded_by, created_at
                FROM workflow_definitions
                WHERE workflow_type = $1 AND is_active = TRUE
                ORDER BY version DESC
                LIMIT 1
                """,
                workflow_type,
            )
            return self._serialize(dict(row)) if row else None

    async def get_history(self, workflow_type: str) -> List[Dict[str, Any]]:
        """Return all versions for a workflow type, newest first."""
        async with self.persistence.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, workflow_type, version, is_active,
                       description, uploaded_by, created_at
                FROM workflow_definitions
                WHERE workflow_type = $1
                ORDER BY version DESC
                """,
                workflow_type,
            )
            return [self._serialize(dict(r)) for r in rows]

    # ─────────────────────────────────────────────────────────────────────────
    # Writes
    # ─────────────────────────────────────────────────────────────────────────

    async def create_definition(
        self,
        workflow_type: str,
        yaml_content: str,
        description: Optional[str] = None,
        uploaded_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert a new version row; returns the new row."""
        async with self.persistence.pool.acquire() as conn:
            # Get next version number
            row = await conn.fetchrow(
                """
                SELECT COALESCE(MAX(version), 0) + 1 AS next_ver
                FROM workflow_definitions
                WHERE workflow_type = $1
                """,
                workflow_type,
            )
            next_ver = row["next_ver"]

            new_row = await conn.fetchrow(
                """
                INSERT INTO workflow_definitions
                    (workflow_type, version, yaml_content, is_active,
                     description, uploaded_by)
                VALUES ($1, $2, $3, TRUE, $4, $5)
                RETURNING id, workflow_type, version, yaml_content,
                          is_active, description, uploaded_by, created_at
                """,
                workflow_type, next_ver, yaml_content, description, uploaded_by,
            )
            logger.info(
                f"Stored workflow definition '{workflow_type}' v{next_ver}"
                f" by {uploaded_by}"
            )
            return self._serialize(dict(new_row))

    async def update_definition(
        self,
        workflow_type: str,
        yaml_content: str,
        uploaded_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upsert: inserts a new version (same as create_definition for now)."""
        return await self.create_definition(
            workflow_type=workflow_type,
            yaml_content=yaml_content,
            uploaded_by=uploaded_by,
        )

    async def deactivate_definition(self, workflow_type: str) -> bool:
        """Mark all versions of a workflow type as inactive (soft-delete)."""
        async with self.persistence.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE workflow_definitions
                SET is_active = FALSE
                WHERE workflow_type = $1 AND is_active = TRUE
                """,
                workflow_type,
            )
            deactivated = not result.endswith("0")
            if deactivated:
                logger.info(f"Deactivated workflow definition '{workflow_type}'")
            return deactivated

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _serialize(row: dict) -> dict:
        if row.get("created_at") and hasattr(row["created_at"], "isoformat"):
            row["created_at"] = row["created_at"].isoformat()
        return row
