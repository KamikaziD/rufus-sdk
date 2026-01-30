import yaml
import importlib
import inspect
import os
from typing import Dict, Any, List, Callable, Type, Optional, ClassVar # Import ClassVar
from pydantic import BaseModel
import pkgutil
import importlib.metadata
import re
import logging
import copy

# Import providers as string literals to avoid NameError during type hinting
# if a circular dependency arises during parsing.
# The actual types will be resolved at runtime.
# from rufus.providers.expression_evaluator import ExpressionEvaluator
# from rufus.providers.template_engine import TemplateEngine

logger = logging.getLogger(__name__)

class WorkflowBuilder:
    _marketplace_steps: ClassVar[Dict[str, Type['WorkflowStep']]] = {} # Make it a class attribute and use ClassVar
    _import_cache: ClassVar[Dict[str, Any]] = {}  # Class-level cache for imported functions/classes

    def __init__(self,
                 workflow_registry: Dict[str, Any],
                 expression_evaluator_cls: Type['ExpressionEvaluator'], # Use string literal
                 template_engine_cls: Type['TemplateEngine'] # Use string literal
                 ):
        self.workflow_registry = workflow_registry
        self.expression_evaluator_cls = expression_evaluator_cls
        self.template_engine_cls = template_engine_cls
        self._workflow_configs = {} # Cache for parsed workflow YAMLs if needed
        self._loaded_modules = set() # Cache for loaded step modules
        # self._marketplace_steps: Dict[str, Type['WorkflowStep']] = {} # Remove this line
        if not WorkflowBuilder._marketplace_steps: # Ensure it's only discovered once per class load
            self._discover_marketplace_steps()

    @staticmethod
    def _validate_step_function(func: Callable):
        if not func:
            return

        sig = inspect.signature(func)
        params = sig.parameters

        if "state" not in params:
            raise ValueError(
                f"Step function '{func.__name__}' is missing the required 'state' parameter."
            )
        if "context" not in params:
            raise ValueError(
                f"Step function '{func.__name__}' is missing the required 'context' parameter. "
                f"All step functions must now accept `(state: BaseModel, context: StepContext)`."
            )

    @classmethod
    def _import_from_string(cls, path: str):
        """
        Import a function/class from a string path with caching.

        This avoids redundant importlib calls for frequently-used step functions,
        reducing overhead by 5-10ms per step execution.

        Args:
            path: Dotted path to function/class (e.g., "my_app.steps.process_data")

        Returns:
            Imported function or class
        """
        if not path:
            return None

        # Check cache first
        if path in cls._import_cache:
            return cls._import_cache[path]

        # Cache miss - import the function/class
        module_path, class_name = path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        imported_obj = getattr(module, class_name)

        # Cache for future use
        cls._import_cache[path] = imported_obj

        logger.debug(f"Imported and cached: {path}")
        return imported_obj

    @classmethod # Change to classmethod
    def _discover_marketplace_steps(cls):
        """
        Discovers workflow steps provided by installed `rufus-*` marketplace packages
        using Python's entry points.
        """
        logger.info("Discovering marketplace steps...")
        # Scan for entry points defined in setup.py/pyproject.toml under a custom group
        # e.g., entry_points={'rufus.steps': ['my_step = rufus_package.steps:MyStep']}

        # Use importlib.metadata for Python 3.8+
        try:
            # Handle both old and new importlib.metadata APIs
            eps = importlib.metadata.entry_points()
            if hasattr(eps, 'select'):
                # Python 3.10+ API
                rufus_steps = eps.select(group='rufus.steps')
            elif hasattr(eps, 'get'):
                # Python 3.9 API
                rufus_steps = eps.get('rufus.steps', [])
            else:
                # Fallback: try accessing as dict
                rufus_steps = eps.get('rufus.steps', []) if isinstance(eps, dict) else []

            for entry_point in rufus_steps:
                try:
                    step_cls = entry_point.load()
                    # Check if step_cls is a subclass of WorkflowStep,
                    # but import WorkflowStep locally to avoid circular import if needed at top level.
                    # For now, assuming WorkflowStep is available at top-level models.py
                    from rufus.models import WorkflowStep
                    if issubclass(step_cls, WorkflowStep):
                        # Use the entry point name or a defined attribute in the class as the step type
                        step_type_name = entry_point.name # e.g., "stripe.charge_card"
                        if hasattr(step_cls, 'STEP_TYPE_NAME'):
                            step_type_name = step_cls.STEP_TYPE_NAME
                        cls._marketplace_steps[step_type_name] = step_cls # Populate class attribute
                        logger.info(f"Discovered marketplace step: {step_type_name} from {entry_point.value}")
                    else:
                        logger.warning(f"Entry point {entry_point.name} loaded a class "
                                       f"{step_cls.__name__} which is not a WorkflowStep subclass.")
                except Exception as e:
                    logger.error(f"Failed to load rufus.steps entry point {entry_point.name}: {e}")
        except Exception as e:
            logger.warning(f"Could not load entry points for rufus.steps (perhaps no packages installed?): {e}")


    @staticmethod
    def _get_merge_strategy_from_str(value: str) -> 'MergeStrategy':
        from rufus.models import MergeStrategy # Import locally to ensure correct enum definition
        for ms in MergeStrategy:
            if ms.value == value:
                return ms
        return MergeStrategy.SHALLOW # Default

    @staticmethod
    def _get_merge_conflict_behavior_from_str(value: str) -> 'MergeConflictBehavior':
        from rufus.models import MergeConflictBehavior # Import locally to ensure correct enum definition
        for mcb in MergeConflictBehavior:
            if mcb.value == value:
                return mcb
        return MergeConflictBehavior.PREFER_NEW # Default

    @classmethod
    def _build_steps_from_config(cls, steps_config: List[Dict[str, Any]]) -> List['WorkflowStep']:
        # Import WorkflowStep and related models locally to avoid circular dependency
        from rufus.models import (
            WorkflowStep, ParallelExecutionTask, AsyncWorkflowStep, CompensatableStep, HttpWorkflowStep,
            FireAndForgetWorkflowStep, LoopStep, CronScheduleWorkflowStep, ParallelWorkflowStep,
            MergeStrategy, MergeConflictBehavior, JavaScriptWorkflowStep, JavaScriptConfig
        )

        steps = []
        for config in steps_config:
            step_type_str = config.get("type", "STANDARD")
            func_path = config.get("function") # Common func_path or function key
            compensate_func_path = config.get("compensate_function")
            input_model_path = config.get("input_model")
            automate_next = config.get("automate_next", False)
            routes = config.get("routes")
            
            merge_strategy = MergeStrategy.SHALLOW
            merge_strategy_value = config.get("merge_strategy")
            if merge_strategy_value:
                for strategy_enum in MergeStrategy:
                    if strategy_enum.value == merge_strategy_value:
                        merge_strategy = strategy_enum
                        break

            merge_conflict_behavior = MergeConflictBehavior.PREFER_NEW
            merge_conflict_behavior_value = config.get("merge_conflict_behavior")
            if merge_conflict_behavior_value:
                for conflict_enum in MergeConflictBehavior:
                    if conflict_enum.value == merge_conflict_behavior_value:
                        merge_conflict_behavior = conflict_enum
                        break

            input_schema = cls._import_from_string(
                input_model_path) if input_model_path else None

            # Check if it's a marketplace step
            if step_type_str in cls._marketplace_steps: # Access _marketplace_steps from class method context
                step_cls = cls._marketplace_steps[step_type_str]
                step_kwargs = config.copy()
                step_name = step_kwargs.pop("name") # Extract 'name'
                step = step_cls(name=step_name, input_schema=input_schema, **step_kwargs)
            elif "." in step_type_str: # Assume it's a custom step class defined in a module
                step_cls = cls._import_from_string(step_type_str)
                if not issubclass(step_cls, WorkflowStep):
                    raise ValueError(f"Custom step type '{step_type_str}' is not a subclass of WorkflowStep.")
                
                step_kwargs = config.copy()
                step_name = step_kwargs.pop("name") # Extract 'name'
                step = step_cls(name=step_name, input_schema=input_schema, **step_kwargs)
            elif step_type_str == "PARALLEL":
                tasks = []
                for task_config in config.get("tasks", []):
                    tasks.append(ParallelExecutionTask(
                        name=task_config["name"], func_path=task_config["function"]))
                
                merge_function_path = config.get("merge_function_path")
                step = ParallelWorkflowStep(
                    name=config["name"],
                    tasks=tasks,
                    merge_function_path=merge_function_path, # Pass the path string directly
                    automate_next=automate_next,
                    merge_strategy=merge_strategy,
                    merge_conflict_behavior=merge_conflict_behavior
                )

            elif step_type_str == "ASYNC":
                step = AsyncWorkflowStep(
                    name=config["name"],
                    func_path=func_path,
                    required_input=config.get("required_input", []),
                    input_schema=input_schema,
                    automate_next=automate_next,
                    merge_strategy=merge_strategy,
                    merge_conflict_behavior=merge_conflict_behavior
                )

            elif step_type_str == "HTTP":
                # Get the entire http_config dictionary from the step configuration
                http_config_param = config.get("http_config", {})
                step = HttpWorkflowStep(
                    name=config["name"],
                    # HttpWorkflowStep does not have func_path. Remove this line.
                    # func_path=func_path,
                    http_config=http_config_param, # Pass the dictionary as is
                    required_input=config.get("required_input", []),
                    input_schema=input_schema,
                    automate_next=automate_next,
                    merge_strategy=merge_strategy,
                    merge_conflict_behavior=merge_conflict_behavior
                )

            elif step_type_str == "JAVASCRIPT":
                # Get the JavaScript configuration dictionary from the step configuration
                js_config_dict = config.get("js_config", {})
                js_config = JavaScriptConfig(**js_config_dict)
                step = JavaScriptWorkflowStep(
                    name=config["name"],
                    js_config=js_config,
                    required_input=config.get("required_input", []),
                    input_schema=input_schema,
                    automate_next=automate_next,
                    merge_strategy=merge_strategy,
                    merge_conflict_behavior=merge_conflict_behavior
                )

            elif step_type_str == "FIRE_AND_FORGET":
                step = FireAndForgetWorkflowStep(
                    name=config["name"],
                    target_workflow_type=config["target_workflow_type"],
                    initial_data_template=config.get(
                        "initial_data_template", {}),
                    automate_next=automate_next
                )

            elif step_type_str == "LOOP":
                loop_body_config = config.get("loop_body", [])
                loop_body = cls._build_steps_from_config(
                    loop_body_config)  # Recursive call
                step = LoopStep(
                    name=config["name"],
                    loop_body=loop_body,
                    mode=config.get("mode", "ITERATE"),
                    iterate_over=config.get("iterate_over"),
                    item_var_name=config.get("item_var_name", "item"),
                    while_condition=config.get("while_condition"),
                    max_iterations=config.get("max_iterations", 1000),
                    automate_next=automate_next
                )

            elif step_type_str == "CRON_SCHEDULER":
                step = CronScheduleWorkflowStep(
                    name=config["name"],
                    target_workflow_type=config["target_workflow_type"],
                    cron_expression=config["schedule"],
                    initial_data_template=config.get(
                        "initial_data_template", {}),
                    schedule_name=config.get("schedule_name"),
                    automate_next=automate_next
                )

            else: # Standard step type or implicit
                # If func_path is None here, it means no 'function' was provided
                # for a STANDARD step, which is an error unless it's a specific step type
                # that doesn't require a function (e.g., a custom step class that
                # defines its own execute method).
                # For an unknown step type, we should raise an error immediately.

                # First, check if step_type_str is a known standard type (like STANDARD or is a custom class path)
                # If it's not a custom class path (checked by '.' in name), and not a standard type, then it's truly unknown.
                if step_type_str not in ["STANDARD", "COMPENSATABLE", "ASYNC", "HTTP", "JAVASCRIPT", "FIRE_AND_FORGET", "LOOP", "CRON_SCHEDULER", "PARALLEL"] and \
                   "." not in step_type_str and step_type_str not in cls._marketplace_steps:
                    raise ValueError(f"Unknown step type: '{step_type_str}'")

                func = cls._import_from_string(func_path) # func_path could still be None for STANDARD if not provided
                cls._validate_step_function(func) # This will catch func is None for STANDARD steps

                if compensate_func_path:
                    compensate_func = cls._import_from_string(
                        compensate_func_path)
                    cls._validate_step_function(compensate_func)
                    step = CompensatableStep(
                        name=config["name"],
                        func=func,
                        compensate_func=compensate_func,
                        required_input=config.get("required_input", []),
                        input_schema=input_schema,
                        automate_next=automate_next,
                        routes=routes
                    )
                else:
                    step = WorkflowStep(
                        name=config["name"],
                        func=func,
                        required_input=config.get("required_input", []),
                        input_schema=input_schema,
                        automate_next=automate_next,
                        routes=routes
                    )

            steps.append(step)
        return steps
    
    @staticmethod
    def _apply_env_variables_to_dict(data: Any) -> Any:
        """Recursively applies environment variable substitution to string values in a dictionary."""
        if isinstance(data, dict):
            return {k: WorkflowBuilder._apply_env_variables_to_dict(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [WorkflowBuilder._apply_env_variables_to_dict(elem) for elem in data]
        elif isinstance(data, str):
            def replace_env_var(match):
                var_name = match.group(1)
                default_value = match.group(3) # Group 2 is the ':-' part
                
                env_value = os.getenv(var_name)
                
                if env_value is not None:
                    return env_value
                elif default_value is not None:
                    return default_value
                else:
                    return match.group(0) 

            # Match ${VAR_NAME} or ${VAR_NAME:-default}
            return re.sub(r'\$\{(\w+)(:-([^}]*))?\}', replace_env_var, data)
        return data

    @staticmethod
    def _apply_parameters_to_dict(data: Any, parameters: Dict[str, Any], template_engine: 'TemplateEngine') -> Any: # Use string literal
        """Recursively applies template parameterization to string values in a dictionary."""
        if isinstance(data, dict):
            return {k: WorkflowBuilder._apply_parameters_to_dict(v, parameters, template_engine) for k, v in data.items()}
        elif isinstance(data, list):
            return [WorkflowBuilder._apply_parameters_to_dict(elem, parameters, template_engine) for elem in data]
        elif isinstance(data, str):
            # Render the string using the template engine with 'parameters' as context
            context = {"parameters": parameters}
            return template_engine.render_string_template(data, context) # Changed render_string to render_string_template
        return data


    def get_scheduled_workflows(self) -> Dict[str, Dict[str, Any]]:
        scheduled = {}
        for wf_type in self.workflow_registry.keys():
            config = self.get_workflow_config(wf_type) # Use processed config
            if config.get("schedule"): # Assuming "schedule" indicates a scheduled workflow
                scheduled[wf_type] = config
        return scheduled

    def get_workflow_config(self, workflow_type: str) -> Dict[str, Any]:
        config_info = self.workflow_registry.get(workflow_type)
        if not config_info:
            raise ValueError(
                f"Workflow type '{workflow_type}' not found in registry.")

        # Make a deep copy to avoid modifying the original registry entry
        cloned_config_info = copy.deepcopy(config_info)

        # Process environment variables
        processed_config_info = self._apply_env_variables_to_dict(cloned_config_info)
        
        # Process parameters using the template engine
        # Instantiate a temporary template engine with workflow-level parameters as context
        # Provide an empty context if no parameters are found, as Jinja2TemplateEngine requires one
        temp_engine = self.template_engine_cls({}) # Changed to pass empty dict as context
        template_params = processed_config_info.get("parameters", {})
        processed_config_info = self._apply_parameters_to_dict(processed_config_info, template_params, temp_engine)

        return processed_config_info

    def get_state_model_class(self, workflow_type: str) -> Type[BaseModel]:
        if workflow_type not in self.workflow_registry:
            raise ValueError(
                f"Workflow type '{workflow_type}' not found in registry.")

        # Get processed config to ensure state_model_path is resolved
        workflow_config = self.get_workflow_config(workflow_type)
        state_model_path = workflow_config["initial_state_model_path"]
        return self._import_from_string(state_model_path)

    async def create_workflow(self, workflow_type: str,
                        persistence_provider: 'PersistenceProvider', # Use string literal
                        execution_provider: 'ExecutionProvider', # Use string literal
                        workflow_builder: 'WorkflowBuilder',
                        expression_evaluator_cls: Type['ExpressionEvaluator'], # Use string literal
                        template_engine_cls: Type['TemplateEngine'], # Use string literal
                        workflow_observer: 'WorkflowObserver', # Use string literal
                        initial_data: Dict[str, Any] = None,
                        owner_id: Optional[str] = None,
                        org_id: Optional[str] = None,
                        data_region: Optional[str] = None,
                        priority: Optional[int] = None,
                        idempotency_key: Optional[str] = None,
                        metadata: Optional[Dict[str, Any]] = None
                        ) -> 'Workflow': # Changed return type hint to string literal

        if any(p is None for p in [persistence_provider, execution_provider, workflow_builder,
                                   expression_evaluator_cls, template_engine_cls, workflow_observer]):
            raise ValueError(
                "All provider and class instances must be provided to create_workflow.")

        # Use get_workflow_config to ensure env vars and parameters are processed
        workflow_config = self.get_workflow_config(workflow_type)

        state_model_class = self._import_from_string(
            workflow_config["initial_state_model_path"])

        initial_state = state_model_class(
            **initial_data) if initial_data else state_model_class()

        steps_config = workflow_config.get("steps", [])
        workflow_steps = self._build_steps_from_config(steps_config)

        # Extract workflow version (if present in YAML)
        workflow_version = workflow_config.get("workflow_version")

        # Create definition snapshot to protect running workflows from YAML changes
        # This is part of the Tier 2 workflow versioning enhancement
        definition_snapshot = copy.deepcopy(workflow_config)

        # Import Workflow locally to avoid circular import at the top level
        from rufus.workflow import Workflow

        return Workflow(
            workflow_type=workflow_type,
            workflow_version=workflow_version,
            definition_snapshot=definition_snapshot,
            workflow_steps=workflow_steps,
            initial_state_model=initial_state,
            steps_config=steps_config,
            state_model_path=workflow_config["initial_state_model_path"],
            owner_id=owner_id,
            org_id=org_id,
            data_region=data_region,
            priority=priority,
            idempotency_key=idempotency_key,
            metadata=metadata,
            persistence_provider=persistence_provider,
            execution_provider=execution_provider,
            workflow_builder=workflow_builder,
            expression_evaluator_cls=expression_evaluator_cls,
            template_engine_cls=template_engine_cls,
            workflow_observer=workflow_observer
        )

    def get_all_task_modules(self) -> List[str]:
        modules = set()

        for workflow_type in self.workflow_registry.keys():
            config = self.get_workflow_config(workflow_type) # Use processed config
            steps = config.get("steps", [])
            self._collect_modules_from_steps(steps, modules)

        return list(modules)

    @classmethod
    def _collect_modules_from_steps(cls, steps: List[Dict[str, Any]], modules: set):
        from rufus.models import WorkflowStep # Import locally if not already imported

        for step in steps:
            step_type = step.get("type", "STANDARD")

            if "function" in step:
                func_path = step["function"]
                if func_path and "." in func_path:
                    module_path, _ = func_path.rsplit('.', 1)
                    modules.add(module_path)

            if "compensate_function" in step:
                comp_func_path = step["compensate_function"]
                if comp_func_path and "." in comp_func_path:
                    module_path, _ = comp_func_path.rsplit('.', 1)
                    modules.add(module_path)

            if step_type == "PARALLEL":
                for task in step.get("tasks", []):
                    func_path = task.get("function")
                    if func_path and "." in func_path:
                        module_path, _ = func_path.rsplit('.', 1)
                        modules.add(module_path)

                merge_func = step.get("merge_function_path")
                if merge_func and "." in merge_func:
                    module_path, _ = merge_func.rsplit('.', 1)
                    modules.add(module_path)

            if "dynamic_injection" in step:
                for rule in step["dynamic_injection"].get("rules", []):
                    steps_to_insert = rule.get("steps_to_insert", [])
                    cls._collect_modules_from_steps(steps_to_insert, modules)