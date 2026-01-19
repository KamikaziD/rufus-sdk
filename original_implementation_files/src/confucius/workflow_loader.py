import yaml
import importlib
import inspect
from typing import Dict, Any, List, Callable
from pydantic import BaseModel

def _validate_step_function(func: Callable):
    """
    Validates that a step function has the required signature:
    - A 'state' parameter (ideally type-hinted to a BaseModel).
    - A 'context' parameter (ideally type-hinted to a StepContext).
    """
    if not func:
        return  # Nothing to validate

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

def _import_from_string(path: str):
    """Imports an object from a string path."""
    if not path:
        return None
    module_path, class_name = path.rsplit('.', 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)

def _build_steps_from_config(steps_config: List[Dict[str, Any]]):
    """Builds a list of WorkflowStep objects from its configuration."""
    from .workflow import WorkflowStep, ParallelWorkflowStep, ParallelExecutionTask, AsyncWorkflowStep, CompensatableStep, HttpWorkflowStep, FireAndForgetWorkflowStep, LoopStep, CronScheduleWorkflowStep
    steps = []
    for config in steps_config:
        step_type = config.get("type", "STANDARD")
        func_path = config.get("function")
        compensate_func_path = config.get("compensate_function")  # NEW: Support saga compensation
        input_model_path = config.get("input_model")
        automate_next = config.get("automate_next", False)

        # Resolve the input schema if provided
        input_schema = _import_from_string(input_model_path) if input_model_path else None

        if step_type == "PARALLEL":
            tasks = []
            for task_config in config.get("tasks", []):
                # For parallel tasks, we pass the path directly for Celery to use.
                tasks.append(ParallelExecutionTask(name=task_config["name"], func_path=task_config["function"]))

            merge_function_path = config.get("merge_function_path")
            step = ParallelWorkflowStep(
                name=config["name"],
                tasks=tasks,
                merge_function_path=merge_function_path,
                automate_next=automate_next
            )

        elif step_type == "ASYNC":
            # For async steps, we also pass the path directly.
            step = AsyncWorkflowStep(
                name=config["name"],
                func_path=func_path,
                required_input=config.get("required_input", []),
                input_schema=input_schema,
                automate_next=automate_next
            )
        
        elif step_type == "HTTP":
            # Extract HTTP configuration
            http_config = {
                "method": config.get("method"),
                "url": config.get("url"),
                "headers": config.get("headers"),
                "body": config.get("body"),
                "timeout": config.get("timeout"),
                "output_key": config.get("output_key"),
                "includes": config.get("includes") # NEW: Filter output
            }
            step = HttpWorkflowStep(
                name=config["name"],
                http_config=http_config,
                required_input=config.get("required_input", []),
                input_schema=input_schema,
                automate_next=automate_next
            )

        elif step_type == "FIRE_AND_FORGET":
            step = FireAndForgetWorkflowStep(
                name=config["name"],
                target_workflow_type=config["target_workflow_type"],
                initial_data_template=config.get("initial_data_template", {}),
                automate_next=automate_next
            )

        elif step_type == "LOOP":
            loop_body_config = config.get("loop_body", [])
            loop_body = _build_steps_from_config(loop_body_config)
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

        elif step_type == "CRON_SCHEDULER":
            step = CronScheduleWorkflowStep(
                name=config["name"],
                target_workflow_type=config["target_workflow_type"],
                cron_expression=config["schedule"],
                initial_data_template=config.get("initial_data_template", {}),
                schedule_name=config.get("schedule_name"),
                automate_next=automate_next
            )

        else:  # STANDARD, DECISION, HUMAN_IN_LOOP, etc.
            func = _import_from_string(func_path)
            _validate_step_function(func)  # Validate the main function
            routes = config.get("routes") # NEW: Extract routes
            
            # NEW: Check if compensation is defined
            if compensate_func_path:
                compensate_func = _import_from_string(compensate_func_path)
                _validate_step_function(compensate_func) # Also validate the compensation function
                step = CompensatableStep(
                    name=config["name"],
                    func=func,
                    compensate_func=compensate_func,
                    required_input=config.get("required_input", []),
                    input_schema=input_schema,
                    automate_next=automate_next,
                    routes=routes # Pass routes
                )
            else:
                step = WorkflowStep(
                    name=config["name"],
                    func=func,
                    required_input=config.get("required_input", []),
                    input_schema=input_schema,
                    automate_next=automate_next,
                    routes=routes # Pass routes
                )
        
        steps.append(step)
    return steps

class WorkflowBuilder:
    def __init__(self, registry_path: str = "config/workflow_registry.yaml"):
        self.registry_path = registry_path
        self._registry = None
        self._workflow_configs = {}
        self._load_registry() # Load registry on initialization

    def _load_registry(self):
        """Loads and caches the master workflow registry from the provided path."""
        if self._registry is None:
            try:
                with open(self.registry_path, "r") as f:
                    registry_data = yaml.safe_load(f)
            except FileNotFoundError:
                raise FileNotFoundError(f"Workflow registry file not found at: {self.registry_path}")
            
            self._registry = {}
            for item in registry_data.get("workflows", []):
                self._registry[item["type"]] = {
                    **item, # Store all registry fields (schedule, description, etc.)
                    "initial_state_model_path": item["initial_state_model"],
                    "initial_state_model": _import_from_string(item["initial_state_model"])
                }

    def get_scheduled_workflows(self) -> Dict[str, Dict[str, Any]]:
        """Returns a dictionary of workflows that have a configured schedule."""
        scheduled = {}
        for wf_type, config in self._registry.items():
            if config.get("schedule"):
                scheduled[wf_type] = config
        return scheduled

    def get_workflow_config(self, workflow_type: str) -> Dict[str, Any]:
        """Loads and caches a specific workflow's configuration."""
        if workflow_type not in self._workflow_configs:
            config_info = self._registry.get(workflow_type)
            if not config_info:
                raise ValueError(f"Workflow type '{workflow_type}' not found in registry.")
            
            # Allow config file paths to be relative to the registry file.
            import os
            registry_dir = os.path.dirname(self.registry_path)
            config_path = os.path.join(registry_dir, os.path.basename(config_info["config_file"]))

            with open(config_path, "r") as f:
                self._workflow_configs[workflow_type] = yaml.safe_load(f)
        
        return self._workflow_configs[workflow_type]

    def build_steps(self, workflow_type: str):
        """Builds all step objects for a given workflow type."""
        workflow_config = self.get_workflow_config(workflow_type)
        return _build_steps_from_config(workflow_config.get("steps", []))

    def get_state_model_class(self, workflow_type: str) -> BaseModel:
        """Retrieves the Pydantic state model class for a given workflow type."""
        if workflow_type not in self._registry:
            raise ValueError(f"Workflow type '{workflow_type}' not found in registry.")
        return self._registry[workflow_type]["initial_state_model"]

    def create_workflow(self, workflow_type: str, initial_data: Dict[str, Any] = None):
        """Creates a new Workflow instance fully configured from YAML."""
        from .workflow import Workflow
        
        # Get the necessary configuration from the registry
        config_info = self._registry.get(workflow_type)
        if not config_info:
            raise ValueError(f"Workflow type '{workflow_type}' not found in registry.")
            
        state_model_class = config_info["initial_state_model"]
        state_model_path = config_info["initial_state_model_path"]
        
        # Initialize the state
        initial_state = state_model_class(**initial_data) if initial_data else state_model_class()

        # Get and build the steps
        workflow_config = self.get_workflow_config(workflow_type)
        steps_config = workflow_config.get("steps", [])
        workflow_steps = _build_steps_from_config(steps_config)

        # Create the workflow instance, now including the state model path
        return Workflow(
            workflow_type=workflow_type,
            workflow_steps=workflow_steps,
            initial_state_model=initial_state,
            steps_config=steps_config,
            state_model_path=state_model_path
        )

    def get_all_task_modules(self) -> List[str]:
        """
        Scans all registered workflows and returns a list of unique module paths 
        referenced by ASYNC and PARALLEL steps.
        This is used by Celery to automatically discover tasks.
        """
        modules = set()
        
        for workflow_type in self._registry.keys():
            config = self.get_workflow_config(workflow_type)
            steps = config.get("steps", [])
            self._collect_modules_from_steps(steps, modules)
            
        return list(modules)

    def _collect_modules_from_steps(self, steps: List[Dict[str, Any]], modules: set):
        for step in steps:
            step_type = step.get("type", "STANDARD")
            
            # Check function paths
            if "function" in step:
                func_path = step["function"]
                if func_path and "." in func_path:
                    module_path, _ = func_path.rsplit('.', 1)
                    modules.add(module_path)
            
            # Check compensation function paths
            if "compensate_function" in step:
                comp_func_path = step["compensate_function"]
                if comp_func_path and "." in comp_func_path:
                    module_path, _ = comp_func_path.rsplit('.', 1)
                    modules.add(module_path)
            
            # Check parallel tasks
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

            # Check dynamic injection rules
            if "dynamic_injection" in step:
                for rule in step["dynamic_injection"].get("rules", []):
                    steps_to_insert = rule.get("steps_to_insert", [])
                    self._collect_modules_from_steps(steps_to_insert, modules)

# A default global builder instance. The application can create its own
# instance with a different registry path if needed.
workflow_builder = WorkflowBuilder()
