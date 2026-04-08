"""Command version management service."""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import uuid4
from enum import Enum

from pydantic import BaseModel

from ruvon_server.schema_validator import (
    validate_against_schema,
    compare_schemas,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class ChangeType(str, Enum):
    """Type of changelog entry."""
    BREAKING = "breaking"
    ENHANCEMENT = "enhancement"
    BUGFIX = "bugfix"
    DEPRECATED = "deprecated"


class CommandVersion(BaseModel):
    """Command version model."""
    id: Optional[str] = None
    command_type: str
    version: str  # Semver format (1.0.0)
    schema_definition: Dict[str, Any]
    changelog: Optional[str] = None
    is_active: bool = True
    is_deprecated: bool = False
    deprecated_reason: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None


class ChangelogEntry(BaseModel):
    """Changelog entry model."""
    id: Optional[str] = None
    command_type: str
    from_version: Optional[str] = None  # None for initial version
    to_version: str
    change_type: ChangeType
    changes: Dict[str, Any]  # Structured changes
    migration_guide: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None


class CompatibilityResult(BaseModel):
    """Result of compatibility check."""
    compatible: bool
    breaking_changes: List[str] = []
    migration_required: bool = False


class VersionService:
    """Service for managing command versions and validation."""

    def __init__(self, persistence):
        """
        Initialize version service.

        Args:
            persistence: Database persistence provider
        """
        self.persistence = persistence
        self._schema_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_expiry: Optional[datetime] = None
        self._cache_ttl = 300  # 5 minutes

        # Detect database type
        self._is_postgres = hasattr(persistence, 'pool')
        self._is_sqlite = hasattr(persistence, 'conn')

    async def _execute(self, query: str, *args):
        """Execute query on appropriate database."""
        if self._is_postgres:
            async with self.persistence.pool.acquire() as conn:
                return await conn.execute(query, *args)
        else:  # SQLite
            async with self.persistence.conn.execute(query, args):
                pass
            await self.persistence.conn.commit()

    async def _fetchrow(self, query: str, *args):
        """Fetch single row from appropriate database."""
        if self._is_postgres:
            async with self.persistence.pool.acquire() as conn:
                return await conn.fetchrow(query, *args)
        else:  # SQLite
            async with self.persistence.conn.execute(query, args) as cursor:
                row = await cursor.fetchone()
                if row:
                    # Convert to dict with column names
                    columns = [desc[0] for desc in cursor.description]
                    return dict(zip(columns, row))
                return None

    async def _fetch(self, query: str, *args):
        """Fetch multiple rows from appropriate database."""
        if self._is_postgres:
            async with self.persistence.pool.acquire() as conn:
                return await conn.fetch(query, *args)
        else:  # SQLite
            async with self.persistence.conn.execute(query, args) as cursor:
                rows = await cursor.fetchall()
                if rows:
                    columns = [desc[0] for desc in cursor.description]
                    return [dict(zip(columns, row)) for row in rows]
                return []

    async def get_version(self, version_id: str) -> Optional[CommandVersion]:
        """
        Get specific command version by ID.

        Args:
            version_id: Version ID

        Returns:
            CommandVersion or None if not found
        """
        query = """
            SELECT id, command_type, version, schema_definition, changelog,
                   is_active, is_deprecated, deprecated_reason,
                   created_by, created_at
            FROM command_versions
            WHERE id = ?
        """ if self._is_sqlite else """
            SELECT id, command_type, version, schema_definition, changelog,
                   is_active, is_deprecated, deprecated_reason,
                   created_by, created_at
            FROM command_versions
            WHERE id = $1
        """

        row = await self._fetchrow(query, version_id)

        if not row:
            return None

        # Parse schema_definition from JSON string (handles both SQLite and PostgreSQL)
        schema_def = row['schema_definition']
        if isinstance(schema_def, str):
            schema_def = json.loads(schema_def)

        # Convert boolean values for SQLite
        is_active = bool(row['is_active']) if self._is_sqlite else row['is_active']
        is_deprecated = bool(row['is_deprecated']) if self._is_sqlite else row['is_deprecated']

        return CommandVersion(
            id=str(row['id']),
            command_type=row['command_type'],
            version=row['version'],
            schema_definition=schema_def,
            changelog=row['changelog'],
            is_active=is_active,
            is_deprecated=is_deprecated,
            deprecated_reason=row['deprecated_reason'],
            created_by=row['created_by'],
            created_at=row['created_at']
        )

    async def get_latest_version(self, command_type: str) -> Optional[CommandVersion]:
        """
        Get latest active version for command type.

        Args:
            command_type: Command type

        Returns:
            Latest CommandVersion or None if not found
        """
        query = """
            SELECT id, command_type, version, schema_definition, changelog,
                   is_active, is_deprecated, deprecated_reason,
                   created_by, created_at
            FROM command_versions
            WHERE command_type = ? AND is_active = 1
            ORDER BY created_at DESC
            LIMIT 1
        """ if self._is_sqlite else """
            SELECT id, command_type, version, schema_definition, changelog,
                   is_active, is_deprecated, deprecated_reason,
                   created_by, created_at
            FROM command_versions
            WHERE command_type = $1 AND is_active = true
            ORDER BY created_at DESC
            LIMIT 1
        """

        row = await self._fetchrow(query, command_type)

        if not row:
            return None

        # Parse schema_definition from JSON string (handles both SQLite and PostgreSQL)
        schema_def = row['schema_definition']
        if isinstance(schema_def, str):
            schema_def = json.loads(schema_def)

        # Convert boolean values for SQLite
        is_active = bool(row['is_active']) if self._is_sqlite else row['is_active']
        is_deprecated = bool(row['is_deprecated']) if self._is_sqlite else row['is_deprecated']

        return CommandVersion(
            id=str(row['id']),
            command_type=row['command_type'],
            version=row['version'],
            schema_definition=schema_def,
            changelog=row['changelog'],
            is_active=is_active,
            is_deprecated=is_deprecated,
            deprecated_reason=row['deprecated_reason'],
            created_by=row['created_by'],
            created_at=row['created_at']
        )

    async def list_versions(
        self,
        command_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List command versions.

        Args:
            command_type: Filter by command type
            is_active: Filter by active status
            limit: Maximum results

        Returns:
            List of version dictionaries
        """
        conditions = []
        params = []
        param_idx = 1

        if command_type:
            conditions.append(f"command_type = ${param_idx}")
            params.append(command_type)
            param_idx += 1

        if is_active is not None:
            conditions.append(f"is_active = ${param_idx}")
            params.append(is_active)
            param_idx += 1

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        async with self.persistence.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, command_type, version, changelog,
                       is_active, is_deprecated, deprecated_reason,
                       created_by, created_at
                FROM command_versions
                {where_clause}
                ORDER BY command_type, created_at DESC
                LIMIT ${param_idx}
                """,
                *params,
                limit
            )

            return [dict(row) for row in rows]

    async def create_version(self, version: CommandVersion) -> str:
        """
        Create new command version.

        Args:
            version: CommandVersion to create

        Returns:
            Version ID
        """
        version_id = str(uuid4())

        if self._is_sqlite:
            query = """
                INSERT INTO command_versions (
                    id, command_type, version, schema_definition, changelog,
                    is_active, is_deprecated, deprecated_reason,
                    created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """
            params = (
                version_id,
                version.command_type,
                version.version,
                json.dumps(version.schema_definition),
                version.changelog,
                1 if version.is_active else 0,
                1 if version.is_deprecated else 0,
                version.deprecated_reason,
                version.created_by
            )
        else:  # PostgreSQL
            query = """
                INSERT INTO command_versions (
                    id, command_type, version, schema_definition, changelog,
                    is_active, is_deprecated, deprecated_reason,
                    created_by, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
            """
            params = (
                version_id,
                version.command_type,
                version.version,
                json.dumps(version.schema_definition),
                version.changelog,
                version.is_active,
                version.is_deprecated,
                version.deprecated_reason,
                version.created_by
            )

        await self._execute(query, *params)

        # Clear cache
        self._schema_cache.clear()

        logger.info(f"Created command version: {version.command_type}@{version.version}")
        return version_id

    async def update_version(self, version_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update command version.

        Args:
            version_id: Version ID
            updates: Fields to update

        Returns:
            True if updated
        """
        allowed_fields = ["is_active", "is_deprecated", "deprecated_reason", "changelog"]
        update_fields = {k: v for k, v in updates.items() if k in allowed_fields}

        if not update_fields:
            return False

        set_clauses = []
        params = []
        param_idx = 1

        for field, value in update_fields.items():
            set_clauses.append(f"{field} = ${param_idx}")
            params.append(value)
            param_idx += 1

        params.append(version_id)

        async with self.persistence.pool.acquire() as conn:
            result = await conn.execute(
                f"""
                UPDATE command_versions
                SET {', '.join(set_clauses)}
                WHERE id = ${param_idx}
                """,
                *params
            )

        # Clear cache
        self._schema_cache.clear()

        return result != "UPDATE 0"

    async def deprecate_version(self, version_id: str, reason: str) -> bool:
        """
        Deprecate command version.

        Args:
            version_id: Version ID
            reason: Deprecation reason

        Returns:
            True if deprecated
        """
        return await self.update_version(
            version_id,
            {
                "is_deprecated": True,
                "deprecated_reason": reason
            }
        )

    async def validate_command_data(
        self,
        command_type: str,
        version: str,
        data: Dict[str, Any]
    ) -> ValidationResult:
        """
        Validate command data against schema.

        Args:
            command_type: Command type
            version: Version string
            data: Command data to validate

        Returns:
            ValidationResult
        """
        schema = await self.get_schema(command_type, version)

        if not schema:
            return ValidationResult(
                valid=False,
                errors=[f"No schema found for {command_type}@{version}"]
            )

        result = validate_against_schema(data, schema)

        # Check if version is deprecated and add warning
        async with self.persistence.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT is_deprecated, deprecated_reason
                FROM command_versions
                WHERE command_type = $1 AND version = $2
                """,
                command_type,
                version
            )

            if row and row['is_deprecated']:
                reason = row['deprecated_reason'] or "No reason provided"
                result.warnings.append(f"Version {version} is deprecated: {reason}")

        return result

    async def get_schema(self, command_type: str, version: str) -> Optional[Dict[str, Any]]:
        """
        Get schema for command type and version (cached).

        Args:
            command_type: Command type
            version: Version string

        Returns:
            Schema definition or None
        """
        cache_key = f"{command_type}@{version}"

        # Check cache
        if cache_key in self._schema_cache:
            return self._schema_cache[cache_key]

        # Fetch from database
        async with self.persistence.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT schema_definition
                FROM command_versions
                WHERE command_type = $1 AND version = $2
                """,
                command_type,
                version
            )

            if not row:
                return None

            schema = row['schema_definition']

            # Parse schema if it's a string (handles both SQLite and PostgreSQL)
            if isinstance(schema, str):
                schema = json.loads(schema)

            # Cache schema
            self._schema_cache[cache_key] = schema

            return schema

    async def add_changelog_entry(self, entry: ChangelogEntry) -> str:
        """
        Add changelog entry.

        Args:
            entry: ChangelogEntry to add

        Returns:
            Entry ID
        """
        entry_id = str(uuid4())

        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO command_changelog (
                    id, command_type, from_version, to_version,
                    change_type, changes, migration_guide,
                    created_by, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                """,
                entry_id,
                entry.command_type,
                entry.from_version,
                entry.to_version,
                entry.change_type.value,
                json.dumps(entry.changes),
                entry.migration_guide,
                entry.created_by
            )

        logger.info(
            f"Added changelog entry: {entry.command_type} "
            f"{entry.from_version or 'initial'} → {entry.to_version}"
        )
        return entry_id

    async def get_changelog(
        self,
        command_type: str,
        from_version: Optional[str] = None,
        to_version: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get changelog entries.

        Args:
            command_type: Command type
            from_version: Starting version (optional)
            to_version: Ending version (optional)

        Returns:
            List of changelog entries
        """
        conditions = ["command_type = $1"]
        params = [command_type]
        param_idx = 2

        if from_version:
            conditions.append(f"from_version = ${param_idx}")
            params.append(from_version)
            param_idx += 1

        if to_version:
            conditions.append(f"to_version = ${param_idx}")
            params.append(to_version)
            param_idx += 1

        where_clause = " AND ".join(conditions)

        async with self.persistence.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, command_type, from_version, to_version,
                       change_type, changes, migration_guide,
                       created_by, created_at
                FROM command_changelog
                WHERE {where_clause}
                ORDER BY created_at DESC
                """,
                *params
            )

            return [dict(row) for row in rows]

    async def check_compatibility(
        self,
        command_type: str,
        from_version: str,
        to_version: str
    ) -> CompatibilityResult:
        """
        Check compatibility between two versions.

        Args:
            command_type: Command type
            from_version: Old version
            to_version: New version

        Returns:
            CompatibilityResult
        """
        old_schema = await self.get_schema(command_type, from_version)
        new_schema = await self.get_schema(command_type, to_version)

        if not old_schema or not new_schema:
            return CompatibilityResult(
                compatible=False,
                breaking_changes=["One or both versions not found"]
            )

        comparison = compare_schemas(old_schema, new_schema)
        breaking_changes = comparison["breaking_changes"]

        return CompatibilityResult(
            compatible=len(breaking_changes) == 0,
            breaking_changes=breaking_changes,
            migration_required=len(breaking_changes) > 0
        )
