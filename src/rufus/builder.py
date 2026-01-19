import yaml
import importlib
import inspect
from typing import Dict, Any, List, Callable, Type, Optional
from pydantic import BaseModel
import pkgutil # For package auto-discovery
import importlib.metadata # For entry point discovery

# Import models from the new location
from rufus.models import (
    WorkflowStep, ParallelExecutionTask, AsyncWorkflowStep, CompensatableStep, HttpWorkflowStep,
    FireAndForgetWorkflowStep, LoopStep, CronScheduleWorkflowStep, ParallelWorkflowStep, StepContext
)
from rufus.engine import WorkflowEngine # For type hinting in create_workflow

# Placeholder for injected providers
from rufus.providers.persistence import PersistenceProvider
from rufus.providers.execution import ExecutionProvider
from rufus.providers.observer import WorkflowObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator as DefaultExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine as DefaultTemplateEngine


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
    steps = []
    for config in steps_config:
        step_type = config.get("type", "STANDARD")
        func_path = config.get("function")
        compensate_func_path = config.get("compensate_function")
        input_model_path = config.get("input_model")
        automate_next = config.get("automate_next", False)
        routes = config.get("routes") # NEW: Extract routes

        input_schema = _import_from_string(input_model_path) if input_model_path else None

        if step_type == "PARALLEL":
            tasks = []
            for task_config in config.get("tasks", []):
                tasks.append(ParallelExecutionTask(name=task_config["name"], func_path=task_config["function"]))

            merge_function_path = config.get("merge_function_path")
            step = ParallelWorkflowStep(
                name=config["name"],
                tasks=tasks,
                merge_function_path=merge_function_path,
                automate_next=automate_next
            )

        elif step_type == "ASYNC":
            step = AsyncWorkflowStep(
                name=config["name"],
                func_path=func_path,
                required_input=config.get("required_input", []),
                input_schema=input_schema,
                automate_next=automate_next
            )
        
        elif step_type == "HTTP":
            http_config = {
                "method": config.get("method"),
                "url": config.get("url"),
                "headers": config.get("headers"),
                "body": config.get("body"),
                "timeout": config.get("timeout"),
                "output_key": config.get("output_key"),
                "includes": config.get("includes")
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
            loop_body = _build_steps_from_config(loop_body_config) # Recursive call
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
            _validate_step_function(func)
            
            if compensate_func_path:
                compensate_func = _import_from_string(compensate_func_path)
                _validate_step_function(compensate_func)
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

class WorkflowBuilder:
    def __init__(self, registry_path: str = "config/workflow_registry.yaml"):
        self.registry_path = registry_path
        self._registry = None
        self._workflow_configs = {}
        self._loaded_modules = set() # To track dynamically loaded modules
        self._load_registry()

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
                    **item,
                    "initial_state_model_path": item["initial_state_model"],
                    # We don't import the model class here yet, only the path.
                    # It will be imported dynamically when creating a workflow.
                }
            
            # Handle package dependencies for marketplace extensions
            self._load_package_dependencies(registry_data.get("requires", []))

    def _load_package_dependencies(self, required_packages: List[str]):
        """
        Dynamically imports modules from specified packages using entry points.
        This allows external packages to register their step definitions.
        """
        for entry_point in importlib.metadata.entry_points(group='rufus.workflow_steps'):
            try:
                # Load the entry point, which should be a module or callable
                module_or_callable = entry_point.load()
                
                # If it's a module, add its path for task discovery
                if inspect.ismodule(module_or_callable):
                    self._loaded_modules.add(module_or_callable.__name__)
                elif callable(module_or_callable):
                    # If it's a callable, get its module name
                    self._loaded_modules.add(module_or_callable.__module__)
                
                print(f"Loaded step definitions from entry point: {entry_point.name} ({entry_point.value})")
            except Exception as e:
                print(f"Warning: Could not load rufus.workflow_steps entry point {entry_point.name}: {e}")

        # Fallback to direct import for explicitly listed packages (or older style)
        for pkg_name in required_packages:
            try:
                # Attempt to import the package and look for a steps/workflows submodule
                module = importlib.import_module(pkg_name.replace('-', '_'))
                # Recursively find all submodules that might contain step functions
                for finder, name, ispkg in pkgutil.walk_packages(module.__path__, module.__name__ + '.'):
                    try:
                        importlib.import_module(name)
                        self._loaded_modules.add(name)
                    except Exception as e:
                        print(f"Warning: Could not import submodule {name} from package {pkg_name}: {e}")
                print(f"Loaded step definitions from package: {pkg_name}")
            except ImportError as e:
                print(f"Warning: Required package '{pkg_name}' not found or failed to import: {e}")


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
            
            import os
            registry_dir = os.path.dirname(self.registry_path)
            config_path = os.path.join(registry_dir, os.path.basename(config_info["config_file"]))

            with open(config_path, "r") as f:
                self._workflow_configs[workflow_type] = yaml.safe_load(f)
        
        return self._workflow_configs[workflow_type]

    def build_steps(self, workflow_type: str) -> List[WorkflowStep]:
        """Builds all step objects for a given workflow type."""
        workflow_config = self.get_workflow_config(workflow_type)
        return _build_steps_from_config(workflow_config.get("steps", []))

    def get_state_model_class(self, workflow_type: str) -> Type[BaseModel]:
        """Retrieves the Pydantic state model class for a given workflow type."""
        if workflow_type not in self._registry:
            raise ValueError(f"Workflow type '{workflow_type}' not found in registry.")
        
        state_model_path = self._registry[workflow_type]["initial_state_model_path"]
        return _import_from_string(state_model_path)

    def create_workflow(self, workflow_type: str, initial_data: Dict[str, Any] = None,
                        persistence_provider: PersistenceProvider = None,
                        execution_provider: ExecutionProvider = None,
                        workflow_builder: 'WorkflowBuilder' = None, # Self-reference for recursive calls
                        expression_evaluator_cls: Type[DefaultExpressionEvaluator] = None,
                        template_engine_cls: Type[DefaultTemplateEngine] = None,
                        workflow_observer: WorkflowObserver = None
                        ) -> WorkflowEngine:
        """Creates a new WorkflowEngine instance fully configured from YAML."""
        
        # Ensure all providers and classes are passed for the WorkflowEngine constructor
        if any(p is None for p in [persistence_provider, execution_provider, workflow_builder, 
                                   expression_evaluator_cls, template_engine_cls, workflow_observer]):
            raise ValueError("All provider and class instances must be provided to create_workflow.")

        config_info = self._registry.get(workflow_type)
        if not config_info:
            raise ValueError(f"Workflow type '{workflow_type}' not found in registry.")
            
        state_model_class = _import_from_string(config_info["initial_state_model_path"])
        state_model_path = config_info["initial_state_model_path"]
        
        initial_state = state_model_class(**initial_data) if initial_data else state_model_class()

        workflow_config = self.get_workflow_config(workflow_type)
        steps_config = workflow_config.get("steps", [])
        workflow_steps = _build_steps_from_config(steps_config)

        return WorkflowEngine(
            workflow_type=workflow_type,
            workflow_steps=workflow_steps,
            initial_state_model=initial_state,
            steps_config=steps_config,
            state_model_path=state_model_path,
            persistence_provider=persistence_provider,
            execution_provider=execution_provider,
            workflow_builder=workflow_builder,
            expression_evaluator_cls=expression_evaluator_cls,
            template_engine_cls=template_engine_cls,
            workflow_observer=workflow_observer
        )

    def get_all_task_modules(self) -> List[str]:
        """
        Scans all registered workflows and returns a list of unique module paths 
        referenced by ASYNC and PARALLEL steps.
        This is used by Celery to automatically discover tasks.
        """
        modules = set()
        
        # Add modules from loaded packages
        modules.update(self._loaded_modules)

        for workflow_type in self._registry.keys():
            config = self.get_workflow_config(workflow_type)
            steps = config.get("steps", [])
            self._collect_modules_from_steps(steps, modules)
            
        return list(modules)

    def _collect_modules_from_steps(self, steps: List[Dict[str, Any]], modules: set):
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
                    self._collect_modules_from_steps(steps_to_insert, modules)

# A default global builder instance. The application can create its own
# instance with a different registry path if needed.
# workflow_builder = WorkflowBuilder()