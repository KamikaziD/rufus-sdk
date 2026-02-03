"""
Template Service

Manages command templates - creation, storage, and application.
"""

import logging
import json
from typing import Optional, List, Dict, Any
from datetime import datetime

from .templates import (
    CommandTemplate,
    TemplateInstance,
    TemplateCommand,
    TemplateVariable,
    resolve_variables
)

logger = logging.getLogger(__name__)


class TemplateService:
    """Service for managing command templates."""

    def __init__(self, persistence, device_service):
        self.persistence = persistence
        self.device_service = device_service

    async def create_template(self, template: CommandTemplate) -> str:
        """
        Create a new command template.

        Args:
            template: Template definition

        Returns:
            template_name: Unique template identifier
        """
        async with self.persistence.pool.acquire() as conn:
            # Check if template already exists
            existing = await conn.fetchrow(
                "SELECT template_name FROM command_templates WHERE template_name = $1",
                template.template_name
            )

            if existing:
                raise ValueError(f"Template '{template.template_name}' already exists")

            # Insert template
            await conn.execute(
                """
                INSERT INTO command_templates (
                    template_name, description, commands, variables,
                    version, tags, created_by, is_active
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                template.template_name,
                template.description,
                json.dumps([cmd.dict() for cmd in template.commands]),
                json.dumps([var.dict() for var in template.variables]),
                template.version,
                json.dumps(template.tags),
                template.created_by,
                template.is_active
            )

        logger.info(f"Created template: {template.template_name}")
        return template.template_name

    async def get_template(self, template_name: str) -> Optional[CommandTemplate]:
        """Get template by name."""
        async with self.persistence.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT template_name, description, commands, variables,
                       version, tags, created_by, is_active
                FROM command_templates
                WHERE template_name = $1
                """,
                template_name
            )

            if not row:
                return None

            commands = [TemplateCommand(**cmd) for cmd in json.loads(row["commands"])]
            variables = [TemplateVariable(**var) for var in json.loads(row["variables"])] if row["variables"] else []
            tags = json.loads(row["tags"]) if row["tags"] else []

            return CommandTemplate(
                template_name=row["template_name"],
                description=row["description"],
                commands=commands,
                variables=variables,
                version=row["version"],
                tags=tags,
                created_by=row["created_by"],
                is_active=row["is_active"]
            )

    async def list_templates(
        self,
        active_only: bool = True,
        tags: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """List available templates."""
        async with self.persistence.pool.acquire() as conn:
            conditions = []
            params = []
            param_count = 0

            if active_only:
                conditions.append("is_active = true")

            if tags:
                for tag in tags:
                    param_count += 1
                    conditions.append(f"tags @> ${param_count}::jsonb")
                    params.append(json.dumps([tag]))

            where_clause = " AND ".join(conditions) if conditions else "1=1"

            rows = await conn.fetch(
                f"""
                SELECT template_name, description, version, tags,
                       created_by, created_at, is_active,
                       jsonb_array_length(commands) as command_count
                FROM command_templates
                WHERE {where_clause}
                ORDER BY template_name
                """,
                *params
            )

            return [
                {
                    "template_name": row["template_name"],
                    "description": row["description"],
                    "version": row["version"],
                    "tags": json.loads(row["tags"]) if row["tags"] else [],
                    "command_count": row["command_count"],
                    "created_by": row["created_by"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "is_active": row["is_active"]
                }
                for row in rows
            ]

    async def delete_template(self, template_name: str) -> bool:
        """Delete a template (soft delete - mark as inactive)."""
        async with self.persistence.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE command_templates
                SET is_active = false, updated_at = $1
                WHERE template_name = $2 AND is_active = true
                """,
                datetime.utcnow(),
                template_name
            )

            if result == "UPDATE 0":
                return False

            logger.info(f"Deleted template: {template_name}")
            return True

    async def apply_template_to_device(
        self,
        template_name: str,
        device_id: str,
        variables: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Apply template to a single device.

        Args:
            template_name: Template to apply
            device_id: Target device
            variables: Variable values (optional)

        Returns:
            List of command IDs created
        """
        # Get template
        template = await self.get_template(template_name)
        if not template:
            raise ValueError(f"Template '{template_name}' not found")

        # Merge default variables with provided variables
        final_variables = {}
        for var in template.variables:
            if var.default is not None:
                final_variables[var.name] = var.default

        if variables:
            final_variables.update(variables)

        # Validate required variables
        for var in template.variables:
            if var.required and var.name not in final_variables:
                raise ValueError(f"Required variable '{var.name}' not provided")

        # Resolve variables in commands
        resolved_commands = resolve_variables(template.commands, final_variables)

        # Create individual commands
        command_ids = []
        for cmd in resolved_commands:
            command_id = await self.device_service.send_command(
                device_id=device_id,
                command_type=cmd["type"],
                command_data=cmd["data"]
            )
            command_ids.append(command_id)

        logger.info(
            f"Applied template '{template_name}' to device {device_id}: "
            f"{len(command_ids)} commands created"
        )

        return command_ids

    async def apply_template_broadcast(
        self,
        template_name: str,
        target_filter: Dict[str, Any],
        variables: Optional[Dict[str, Any]] = None,
        rollout_config: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Apply template as broadcast to multiple devices.

        Args:
            template_name: Template to apply
            target_filter: Device filter
            variables: Variable values (optional)
            rollout_config: Rollout configuration (optional)

        Returns:
            broadcast_id: Broadcast identifier
        """
        # Get template
        template = await self.get_template(template_name)
        if not template:
            raise ValueError(f"Template '{template_name}' not found")

        # Merge default variables
        final_variables = {}
        for var in template.variables:
            if var.default is not None:
                final_variables[var.name] = var.default

        if variables:
            final_variables.update(variables)

        # Validate required variables
        for var in template.variables:
            if var.required and var.name not in final_variables:
                raise ValueError(f"Required variable '{var.name}' not provided")

        # Resolve variables
        resolved_commands = resolve_variables(template.commands, final_variables)

        # For broadcast, we'll create multiple broadcasts (one per command)
        # In a production system, you might want to create a "batch" concept
        # For now, we'll just execute the first command as broadcast
        # and log a warning about multiple commands

        if len(resolved_commands) > 1:
            logger.warning(
                f"Template '{template_name}' has {len(resolved_commands)} commands. "
                f"Only first command will be broadcast. Consider using batch commands."
            )

        first_command = resolved_commands[0]

        # Create broadcast using broadcast service
        from .broadcast_service import BroadcastService
        from .broadcast import CommandBroadcast, TargetFilter, RolloutConfig

        broadcast_service = BroadcastService(self.persistence, self.device_service)

        target = TargetFilter(**target_filter)
        rollout = RolloutConfig(**rollout_config) if rollout_config else None

        broadcast = CommandBroadcast(
            command_type=first_command["type"],
            command_data=first_command["data"],
            target_filter=target,
            rollout_config=rollout
        )

        broadcast_id = await broadcast_service.create_broadcast(broadcast)

        logger.info(
            f"Applied template '{template_name}' as broadcast: {broadcast_id}"
        )

        return broadcast_id
