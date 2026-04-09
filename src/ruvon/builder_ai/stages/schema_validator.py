"""Stage 5 — Schema Validator: deterministic validation of a generated workflow dict."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# Step types that require a specific config key
_STEP_TYPE_CONFIG_KEYS: Dict[str, str] = {
    "AI_LLM_INFERENCE": "llm_config",
    "HUMAN_APPROVAL": "approval_config",
    "AUDIT_EMIT": "audit_config",
    "COMPLIANCE_CHECK": "compliance_config",
    "EDGE_MODEL_CALL": "edge_config",
    "WORKFLOW_BUILDER_META": "meta_config",
}

_KNOWN_TYPES = {
    "STANDARD", "ASYNC", "HTTP", "PARALLEL", "LOOP", "HUMAN_IN_LOOP", "COMPENSATABLE",
    "AI_INFERENCE", "WASM", "FIRE_AND_FORGET", "CRON_SCHEDULE",
    "AI_LLM_INFERENCE", "HUMAN_APPROVAL", "AUDIT_EMIT", "COMPLIANCE_CHECK",
    "EDGE_MODEL_CALL", "WORKFLOW_BUILDER_META",
}

_REQUIRED_LLM_CONFIG = {"model", "system_prompt", "user_prompt"}
_REQUIRED_APPROVAL_CONFIG = {"title"}
_REQUIRED_AUDIT_CONFIG = {"event_type"}
_REQUIRED_COMPLIANCE_CONFIG = {"ruleset"}
_REQUIRED_EDGE_CONFIG = {"model_id", "prompt"}


class SchemaValidator:
    """Stage 5: Deterministic validation of a workflow dict against the Ruvon schema."""

    def validate(self, workflow: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """
        Validate a workflow dict.

        Returns:
            (workflow, errors) — errors is empty on success.
            Auto-repairs trivial issues (missing version, missing automate_next).
        """
        errors: List[str] = []

        if not isinstance(workflow, dict):
            return workflow, ["Workflow must be a dict, got: " + type(workflow).__name__]

        # --- Top-level required fields ---
        if "steps" not in workflow:
            errors.append("Missing required field: 'steps'")
            return workflow, errors

        if not workflow.get("name"):
            workflow["name"] = "generated-workflow"

        if not workflow.get("version"):
            workflow["version"] = "1.0"

        steps = workflow.get("steps", [])
        if not isinstance(steps, list):
            errors.append("'steps' must be a list")
            return workflow, errors

        if len(steps) == 0:
            errors.append("Workflow must have at least one step")
            return workflow, errors

        step_names = set()
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append(f"Step {i} is not a dict")
                continue

            step_label = step.get("name", f"step[{i}]")

            # name is required
            if not step.get("name"):
                errors.append(f"Step {i} is missing 'name'")

            # type defaults to STANDARD
            step_type = step.get("type", "STANDARD").upper()
            step["type"] = step_type  # normalise to uppercase

            if step_type not in _KNOWN_TYPES:
                errors.append(f"Step '{step_label}': unknown type '{step_type}'")

            # Check for duplicate names
            if step.get("name") in step_names:
                errors.append(f"Duplicate step name: '{step.get('name')}'")
            step_names.add(step.get("name"))

            # Type-specific config key presence
            if step_type in _STEP_TYPE_CONFIG_KEYS:
                config_key = _STEP_TYPE_CONFIG_KEYS[step_type]
                if config_key not in step:
                    errors.append(f"Step '{step_label}' (type {step_type}) missing required key '{config_key}'")
                else:
                    cfg_errors = self._validate_step_config(step_type, step[config_key], step_label)
                    errors.extend(cfg_errors)

            # STANDARD steps need a function path
            if step_type == "STANDARD" and not step.get("function"):
                # Auto-repair with a placeholder
                step["function"] = "ruvon_workflows.steps.identity"
                logger.debug("[Stage 5] Auto-repaired missing function for step '%s'", step_label)

        return workflow, errors

    def _validate_step_config(self, step_type: str, config: Any, step_label: str) -> List[str]:
        errors = []
        if not isinstance(config, dict):
            errors.append(f"Step '{step_label}': config must be a dict, got {type(config).__name__}")
            return errors

        required_map = {
            "AI_LLM_INFERENCE": _REQUIRED_LLM_CONFIG,
            "HUMAN_APPROVAL": _REQUIRED_APPROVAL_CONFIG,
            "AUDIT_EMIT": _REQUIRED_AUDIT_CONFIG,
            "COMPLIANCE_CHECK": _REQUIRED_COMPLIANCE_CONFIG,
            "EDGE_MODEL_CALL": _REQUIRED_EDGE_CONFIG,
        }
        required = required_map.get(step_type, set())
        for field in required:
            if field not in config:
                errors.append(f"Step '{step_label}' {step_type} config missing required field '{field}'")
        return errors
