"""
Enhanced validation for Rufus workflows.
Provides strict validation beyond basic YAML syntax checking.
"""

import importlib
import json
from pathlib import Path
from typing import Dict, Any, List, Tuple
import yaml

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


class WorkflowValidator:
    """
    Comprehensive workflow validator.

    Performs multiple levels of validation:
    1. JSON Schema validation (if jsonschema available)
    2. Step dependency validation
    3. Function path import validation
    4. State model validation
    5. Route target validation
    """

    def __init__(self, strict: bool = False):
        """
        Args:
            strict: If True, performs comprehensive validation including imports
        """
        self.strict = strict
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def validate_workflow(self, workflow_config: Dict[str, Any], workflow_file: Path) -> Tuple[bool, List[str], List[str]]:
        """
        Validate a workflow configuration.

        Returns:
            Tuple of (is_valid, errors, warnings)
        """
        self.errors = []
        self.warnings = []

        # Basic structure validation
        self._validate_basic_structure(workflow_config, workflow_file)

        # JSON Schema validation
        if HAS_JSONSCHEMA:
            self._validate_against_schema(workflow_config, workflow_file)
        elif self.strict:
            self.warnings.append(
                "jsonschema not installed. Run 'pip install jsonschema' for schema validation."
            )

        # Step-specific validations
        if "steps" in workflow_config:
            steps = workflow_config["steps"]
            step_names = {step["name"] for step in steps if "name" in step}

            for step in steps:
                self._validate_step(step, step_names, workflow_config)

        # State model validation (strict mode only)
        if self.strict and "initial_state_model" in workflow_config:
            self._validate_state_model(workflow_config["initial_state_model"])

        return (len(self.errors) == 0, self.errors, self.warnings)

    def _validate_basic_structure(self, config: Dict[str, Any], workflow_file: Path):
        """Validate basic required fields."""
        required_fields = ["workflow_type", "steps", "initial_state_model"]

        for field in required_fields:
            if field not in config:
                self.errors.append(f"Missing required field: '{field}'")

        if "steps" in config:
            if not isinstance(config["steps"], list):
                self.errors.append("'steps' must be a list")
            elif len(config["steps"]) == 0:
                self.errors.append("'steps' list is empty")

        if "workflow_type" in config:
            wf_type = config["workflow_type"]
            if not isinstance(wf_type, str) or not wf_type:
                self.errors.append("'workflow_type' must be a non-empty string")

    def _validate_against_schema(self, config: Dict[str, Any], workflow_file: Path):
        """Validate workflow against JSON Schema."""
        schema_path = Path(__file__).parent.parent.parent / "schema" / "workflow_schema.json"

        if not schema_path.exists():
            self.warnings.append(f"JSON Schema not found at {schema_path}")
            return

        try:
            with open(schema_path, "r") as f:
                schema = json.load(f)

            jsonschema.validate(instance=config, schema=schema)
        except jsonschema.ValidationError as e:
            # Make error message more readable
            error_path = " -> ".join(str(p) for p in e.path) if e.path else "root"
            self.errors.append(f"Schema validation failed at {error_path}: {e.message}")
        except Exception as e:
            self.warnings.append(f"Could not validate against schema: {e}")

    def _validate_step(self, step: Dict[str, Any], all_step_names: set, workflow_config: Dict[str, Any]):
        """Validate a single step."""
        if "name" not in step:
            self.errors.append("Step missing required field: 'name'")
            return

        step_name = step["name"]
        step_type = step.get("type", "STANDARD")

        # Validate step name format
        if not step_name or not isinstance(step_name, str):
            self.errors.append(f"Step name must be a non-empty string")
        elif not step_name[0].isupper():
            self.warnings.append(
                f"Step '{step_name}': Consider using PascalCase (e.g., 'Process_Payment')"
            )

        # Validate dependencies exist
        if "dependencies" in step:
            for dep in step["dependencies"]:
                if dep not in all_step_names:
                    self.errors.append(
                        f"Step '{step_name}': dependency '{dep}' does not exist in workflow"
                    )

        # Validate routes target existing steps
        if "routes" in step:
            for route in step["routes"]:
                if "target" in route:
                    target = route["target"]
                    if target not in all_step_names:
                        self.errors.append(
                            f"Step '{step_name}': route target '{target}' does not exist in workflow"
                        )

        # Validate function path exists (strict mode only)
        if self.strict and "function" in step:
            self._validate_function_path(step["function"], step_name)

        # Validate compensate function (strict mode only)
        if self.strict and "compensate_function" in step:
            self._validate_function_path(step["compensate_function"], step_name, is_compensation=True)

        # Validate parallel tasks
        if step_type == "PARALLEL":
            if "tasks" not in step:
                self.errors.append(f"Step '{step_name}': PARALLEL step must have 'tasks' field")
            else:
                for task in step["tasks"]:
                    if "name" not in task:
                        self.errors.append(f"Step '{step_name}': parallel task missing 'name'")
                    if "function" not in task:
                        self.errors.append(
                            f"Step '{step_name}': parallel task '{task.get('name', '?')}' missing 'function'"
                        )
                    elif self.strict:
                        self._validate_function_path(
                            task["function"],
                            f"{step_name}.{task.get('name', '?')}"
                        )

        # Validate required fields by step type
        required_by_type = {
            "HTTP": ["http_config"],
            "FIRE_AND_FORGET": ["target_workflow_type", "initial_data_template"],
            "CRON_SCHEDULER": ["target_workflow_type", "initial_data_template", "cron_expression"],
            "LOOP": ["loop_body", "mode"],
        }

        if step_type in required_by_type:
            for required_field in required_by_type[step_type]:
                if required_field not in step:
                    self.errors.append(
                        f"Step '{step_name}': {step_type} step must have '{required_field}' field"
                    )

        # Validate dynamic injection (add warning)
        if "dynamic_injection" in step:
            self.warnings.append(
                f"Step '{step_name}': Uses dynamic_injection. "
                "This makes workflows non-deterministic and harder to debug. "
                "Use with extreme caution."
            )

    def _validate_function_path(self, func_path: str, context: str, is_compensation: bool = False):
        """
        Validate that a function path can be imported.

        Args:
            func_path: Python import path (e.g., "module.function")
            context: Step name or context for error messages
            is_compensation: True if this is a compensation function
        """
        if not func_path:
            return

        try:
            # Split into module path and function name
            parts = func_path.rsplit(".", 1)
            if len(parts) != 2:
                self.errors.append(
                    f"{context}: Invalid function path '{func_path}'. "
                    "Expected format: 'module.submodule.function_name'"
                )
                return

            module_path, func_name = parts

            # Try to import the module
            try:
                module = importlib.import_module(module_path)
            except ModuleNotFoundError as e:
                func_type = "compensation function" if is_compensation else "function"
                self.errors.append(
                    f"{context}: Cannot import {func_type} module '{module_path}': {e}"
                )
                return
            except Exception as e:
                func_type = "compensation function" if is_compensation else "function"
                self.warnings.append(
                    f"{context}: Warning importing {func_type} module '{module_path}': {e}"
                )
                return

            # Check if function exists in module
            if not hasattr(module, func_name):
                func_type = "compensation function" if is_compensation else "function"
                self.errors.append(
                    f"{context}: {func_type} '{func_name}' not found in module '{module_path}'"
                )
                return

            # Verify it's callable
            func = getattr(module, func_name)
            if not callable(func):
                func_type = "compensation function" if is_compensation else "function"
                self.errors.append(
                    f"{context}: '{func_path}' is not callable ({type(func).__name__})"
                )

        except Exception as e:
            self.warnings.append(f"{context}: Could not validate function path '{func_path}': {e}")

    def _validate_state_model(self, state_model_path: str):
        """Validate that state model can be imported and is a Pydantic model."""
        if not state_model_path:
            return

        try:
            parts = state_model_path.rsplit(".", 1)
            if len(parts) != 2:
                self.errors.append(
                    f"Invalid state model path '{state_model_path}'. "
                    "Expected format: 'module.submodule.ClassName'"
                )
                return

            module_path, class_name = parts

            try:
                module = importlib.import_module(module_path)
            except ModuleNotFoundError as e:
                self.errors.append(f"Cannot import state model module '{module_path}': {e}")
                return
            except Exception as e:
                self.warnings.append(f"Warning importing state model module '{module_path}': {e}")
                return

            if not hasattr(module, class_name):
                self.errors.append(
                    f"State model class '{class_name}' not found in module '{module_path}'"
                )
                return

            model_class = getattr(module, class_name)

            # Check if it's a Pydantic model (has model_fields or __fields__)
            if not (hasattr(model_class, 'model_fields') or hasattr(model_class, '__fields__')):
                self.warnings.append(
                    f"State model '{state_model_path}' does not appear to be a Pydantic model"
                )

        except Exception as e:
            self.warnings.append(f"Could not validate state model '{state_model_path}': {e}")


def validate_workflow_file(workflow_file: Path, strict: bool = False) -> Tuple[bool, List[str], List[str]]:
    """
    Validate a workflow YAML file.

    Args:
        workflow_file: Path to workflow YAML file
        strict: If True, performs comprehensive validation including imports

    Returns:
        Tuple of (is_valid, errors, warnings)
    """
    if not workflow_file.exists():
        return (False, [f"File not found: {workflow_file}"], [])

    try:
        with open(workflow_file, "r") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return (False, [f"Invalid YAML syntax: {e}"], [])
    except Exception as e:
        return (False, [f"Could not read file: {e}"], [])

    if not isinstance(config, dict):
        return (False, ["Workflow file must contain a YAML dictionary"], [])

    validator = WorkflowValidator(strict=strict)
    return validator.validate_workflow(config, workflow_file)
