"""
Command Templates

Reusable command sets for standard operating procedures.
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, validator


class TemplateVariable(BaseModel):
    """
    Template variable definition.

    Example:
    ```python
    TemplateVariable(
        name="delay_seconds",
        description="Delay before restart",
        type="integer",
        default=30,
        required=False
    )
    ```
    """
    name: str = Field(description="Variable name")
    description: str = Field(description="Variable description")
    type: str = Field(description="Variable type (string, integer, boolean, object)")
    default: Optional[Any] = Field(default=None, description="Default value")
    required: bool = Field(default=False, description="Whether variable is required")


class TemplateCommand(BaseModel):
    """
    Command within a template.

    Example:
    ```python
    TemplateCommand(
        type="restart",
        data={"delay_seconds": "{{delay_seconds}}"}
    )
    ```
    """
    type: str = Field(description="Command type")
    data: Dict[str, Any] = Field(default={}, description="Command data (may contain variables)")


class CommandTemplate(BaseModel):
    """
    Command template definition.

    Example:
    ```python
    template = CommandTemplate(
        template_name="soft-restart",
        description="Graceful restart with cleanup",
        commands=[
            TemplateCommand(type="clear_cache", data={}),
            TemplateCommand(type="sync_now", data={}),
            TemplateCommand(type="restart", data={"delay_seconds": "{{delay_seconds}}"})
        ],
        variables=[
            TemplateVariable(name="delay_seconds", type="integer", default=30)
        ],
        tags=["maintenance"]
    )
    ```
    """
    template_name: str = Field(description="Unique template name")
    description: str = Field(description="Template description")
    commands: List[TemplateCommand] = Field(description="List of commands in template")
    variables: List[TemplateVariable] = Field(
        default=[],
        description="Template variables"
    )
    version: str = Field(default="1.0.0", description="Template version")
    tags: List[str] = Field(default=[], description="Template tags")
    created_by: Optional[str] = Field(default=None, description="Creator")
    is_active: bool = Field(default=True, description="Whether template is active")

    @validator('template_name')
    def validate_name(cls, v):
        """Validate template name."""
        if not v or len(v) < 3:
            raise ValueError("Template name must be at least 3 characters")
        if not v.replace('-', '').replace('_', '').isalnum():
            raise ValueError("Template name must be alphanumeric (with - or _)")
        return v.lower()

    @validator('commands')
    def validate_commands(cls, v):
        """Validate commands list."""
        if not v or len(v) == 0:
            raise ValueError("Template must have at least one command")
        return v


class TemplateInstance(BaseModel):
    """
    Template instance with resolved variables.

    Used when applying template to device(s).
    """
    template_name: str
    variables: Dict[str, Any] = {}
    device_id: Optional[str] = None  # For single device
    target_filter: Optional[Dict[str, Any]] = None  # For broadcast


def resolve_variables(
    commands: List[TemplateCommand],
    variables: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Resolve template variables in commands.

    Args:
        commands: List of template commands
        variables: Variable values

    Returns:
        List of resolved commands ready for execution

    Example:
    ```python
    commands = [
        TemplateCommand(type="restart", data={"delay_seconds": "{{delay}}"})
    ]
    variables = {"delay": 60}
    resolved = resolve_variables(commands, variables)
    # Returns: [{"type": "restart", "data": {"delay_seconds": 60}}]
    ```
    """
    import json
    import re

    resolved_commands = []

    for cmd in commands:
        # Convert to dict
        cmd_dict = {"type": cmd.type, "data": cmd.data.copy()}

        # Convert to JSON string for regex replacement
        cmd_str = json.dumps(cmd_dict)

        # Replace all {{variable}} with actual values
        for var_name, var_value in variables.items():
            pattern = f'"{{{{{var_name}}}}}"'  # Match "{{var_name}}"

            # Convert value to JSON representation
            if isinstance(var_value, str):
                replacement = json.dumps(var_value)
            elif isinstance(var_value, (int, float, bool)):
                replacement = json.dumps(var_value)
            elif var_value is None:
                replacement = "null"
            else:
                replacement = json.dumps(var_value)

            cmd_str = cmd_str.replace(pattern, replacement)

        # Parse back to dict
        resolved_cmd = json.loads(cmd_str)
        resolved_commands.append(resolved_cmd)

    return resolved_commands


# Predefined templates
PREDEFINED_TEMPLATES = {
    "security-lockdown": CommandTemplate(
        template_name="security-lockdown",
        description="Emergency security lockdown procedure",
        commands=[
            TemplateCommand(type="disable_transactions", data={"reason": "Security lockdown"}),
            TemplateCommand(type="security_lockdown", data={}),
            TemplateCommand(type="fraud_alert", data={"alert_type": "manual_lockdown"})
        ],
        tags=["security", "emergency"],
        version="1.0.0"
    ),

    "soft-restart": CommandTemplate(
        template_name="soft-restart",
        description="Graceful restart with cleanup",
        commands=[
            TemplateCommand(type="clear_cache", data={}),
            TemplateCommand(type="sync_now", data={}),
            TemplateCommand(type="restart", data={"delay_seconds": "{{delay_seconds}}"})
        ],
        variables=[
            TemplateVariable(
                name="delay_seconds",
                description="Delay before restart in seconds",
                type="integer",
                default=30,
                required=False
            )
        ],
        tags=["maintenance"],
        version="1.0.0"
    ),

    "maintenance-mode": CommandTemplate(
        template_name="maintenance-mode",
        description="Enter maintenance mode with backup",
        commands=[
            TemplateCommand(type="disable_transactions", data={"reason": "Scheduled maintenance"}),
            TemplateCommand(type="backup", data={"target": "cloud"}),
            TemplateCommand(type="health_check", data={})
        ],
        tags=["maintenance"],
        version="1.0.0"
    ),

    "health-check-full": CommandTemplate(
        template_name="health-check-full",
        description="Comprehensive health diagnostics",
        commands=[
            TemplateCommand(type="health_check", data={}),
            TemplateCommand(type="sync_now", data={}),
            TemplateCommand(type="clear_cache", data={})
        ],
        tags=["diagnostics"],
        version="1.0.0"
    )
}
