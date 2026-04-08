"""JSON Schema validation utilities for command versioning."""

import jsonschema
from jsonschema import Draft7Validator, ValidationError
from typing import Dict, List, Any, Optional
from pydantic import BaseModel


class ValidationResult(BaseModel):
    """Result of schema validation."""
    valid: bool
    errors: List[str] = []
    warnings: List[str] = []


def validate_against_schema(data: Dict[str, Any], schema: Dict[str, Any]) -> ValidationResult:
    """
    Validate data against JSON Schema.

    Args:
        data: Data to validate
        schema: JSON Schema definition

    Returns:
        ValidationResult with validation status and errors
    """
    validator = Draft7Validator(schema)
    errors = []
    warnings = []

    for error in validator.iter_errors(data):
        # Build error path
        path = ".".join(str(p) for p in error.path) if error.path else "root"
        errors.append(f"{path}: {error.message}")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings
    )


def generate_example_from_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate example data from JSON Schema.

    Args:
        schema: JSON Schema definition

    Returns:
        Example data matching the schema
    """
    example = {}

    if "properties" in schema:
        for prop, prop_schema in schema["properties"].items():
            prop_type = prop_schema.get("type")

            # Use default if provided
            if "default" in prop_schema:
                example[prop] = prop_schema["default"]
                continue

            # Generate based on type
            if prop_type == "string":
                if "enum" in prop_schema:
                    example[prop] = prop_schema["enum"][0]
                else:
                    example[prop] = "example"
            elif prop_type == "integer":
                minimum = prop_schema.get("minimum", 0)
                example[prop] = minimum
            elif prop_type == "number":
                minimum = prop_schema.get("minimum", 0.0)
                example[prop] = minimum
            elif prop_type == "boolean":
                example[prop] = False
            elif prop_type == "array":
                example[prop] = []
            elif prop_type == "object":
                example[prop] = {}

    return example


def compare_schemas(old_schema: Dict[str, Any], new_schema: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Compare two schemas and identify breaking changes.

    Args:
        old_schema: Previous schema version
        new_schema: New schema version

    Returns:
        Dict with 'breaking_changes' and 'enhancements' lists
    """
    breaking_changes = []
    enhancements = []

    # Check for required field changes
    old_required = set(old_schema.get("required", []))
    new_required = set(new_schema.get("required", []))

    removed_required = old_required - new_required
    added_required = new_required - old_required

    if added_required:
        breaking_changes.append(f"New required fields: {', '.join(sorted(added_required))}")

    if removed_required:
        enhancements.append(f"Fields now optional: {', '.join(sorted(removed_required))}")

    # Check for property changes
    old_props = old_schema.get("properties", {})
    new_props = new_schema.get("properties", {})

    # Check for removed properties
    removed_props = set(old_props.keys()) - set(new_props.keys())
    if removed_props:
        breaking_changes.append(f"Removed properties: {', '.join(sorted(removed_props))}")

    # Check for added properties
    added_props = set(new_props.keys()) - set(old_props.keys())
    if added_props:
        enhancements.append(f"New properties: {', '.join(sorted(added_props))}")

    # Check for type changes in common properties
    for prop in set(old_props.keys()) & set(new_props.keys()):
        old_type = old_props[prop].get("type")
        new_type = new_props[prop].get("type")

        if old_type != new_type:
            breaking_changes.append(f"Field '{prop}' type changed: {old_type} → {new_type}")

        # Check for enum changes
        old_enum = set(old_props[prop].get("enum", []))
        new_enum = set(new_props[prop].get("enum", []))

        if old_enum and new_enum:
            removed_enum = old_enum - new_enum
            if removed_enum:
                breaking_changes.append(
                    f"Field '{prop}' removed enum values: {', '.join(map(str, sorted(removed_enum)))}"
                )

        # Check for constraint changes
        old_min = old_props[prop].get("minimum")
        new_min = new_props[prop].get("minimum")
        if old_min is not None and new_min is not None and new_min > old_min:
            breaking_changes.append(f"Field '{prop}' minimum increased: {old_min} → {new_min}")

        old_max = old_props[prop].get("maximum")
        new_max = new_props[prop].get("maximum")
        if old_max is not None and new_max is not None and new_max < old_max:
            breaking_changes.append(f"Field '{prop}' maximum decreased: {old_max} → {new_max}")

    return {
        "breaking_changes": breaking_changes,
        "enhancements": enhancements
    }


def is_schema_compatible(old_schema: Dict[str, Any], new_schema: Dict[str, Any]) -> bool:
    """
    Check if new schema is backward compatible with old schema.

    Args:
        old_schema: Previous schema version
        new_schema: New schema version

    Returns:
        True if backward compatible (no breaking changes)
    """
    comparison = compare_schemas(old_schema, new_schema)
    return len(comparison["breaking_changes"]) == 0
