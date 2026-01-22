import yaml
import importlib
import inspect
from typing import Dict, Any, List, Callable, Type, Optional
from pydantic import BaseModel
import pkgutil
import importlib.metadata

from rufus.models import (
    WorkflowStep, ParallelExecutionTask, AsyncWorkflowStep, CompensatableStep, HttpWorkflowStep,
    FireAndForgetWorkflowStep, LoopStep, CronScheduleWorkflowStep, ParallelWorkflowStep, StepContext
)
from rufus.workflow import Workflow
from rufus.providers.persistence import PersistenceProvider
from rufus.providers.execution import ExecutionProvider
from rufus.providers.observer import WorkflowObserver
from rufus.providers.expression_evaluator import ExpressionEvaluator
from rufus.providers.template_engine import TemplateEngine


class WorkflowBuilder:
    def __init__(self,
                 workflow_registry: Dict[str, Any],
                 expression_evaluator_cls: Type[ExpressionEvaluator],
                 template_engine_cls: Type[TemplateEngine]
                 ):
        self.workflow_registry = workflow_registry
        self.expression_evaluator_cls = expression_evaluator_cls
        self.template_engine_cls = template_engine_cls
        self._workflow_configs = {}
        self._loaded_modules = set()

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

    @staticmethod
    def _import_from_string(path: str):
        if not path:
            return None
        module_path, class_name = path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)

    @classmethod
    def _build_steps_from_config(cls, steps_config: List[Dict[str, Any]]) -> List[WorkflowStep]:
        steps = []
        for config in steps_config:
            step_type = config.get("type", "STANDARD")
            func_path = config.get("function")
            compensate_func_path = config.get("compensate_function")
            input_model_path = config.get("input_model")
            automate_next = config.get("automate_next", False)
            routes = config.get("routes")

            input_schema = cls._import_from_string(
                input_model_path) if input_model_path else None

            if step_type == "PARALLEL":
                tasks = []
                for task_config in config.get("tasks", []):
                    tasks.append(ParallelExecutionTask(
                        name=task_config["name"], func_path=task_config["function"]))

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
                    initial_data_template=config.get(
                        "initial_data_template", {}),
                    automate_next=automate_next
                )

            elif step_type == "LOOP":
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

            elif step_type == "CRON_SCHEDULER":
                step = CronScheduleWorkflowStep(
                    name=config["name"],
                    target_workflow_type=config["target_workflow_type"],
                    cron_expression=config["schedule"],
                    initial_data_template=config.get(
                        "initial_data_template", {}),
                    schedule_name=config.get("schedule_name"),
                    automate_next=automate_next
                )

            else:
                func = cls._import_from_string(func_path)
                cls._validate_step_function(func)

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

    def get_scheduled_workflows(self) -> Dict[str, Dict[str, Any]]:
        scheduled = {}
        for wf_type, config in self.workflow_registry.items():
            if config.get("schedule"):
                scheduled[wf_type] = config
        return scheduled

    def get_workflow_config(self, workflow_type: str) -> Dict[str, Any]:
        config_info = self.workflow_registry.get(workflow_type)
        if not config_info:
            raise ValueError(
                f"Workflow type '{workflow_type}' not found in registry.")

        return config_info

    def get_state_model_class(self, workflow_type: str) -> Type[BaseModel]:
        if workflow_type not in self.workflow_registry:
            raise ValueError(
                f"Workflow type '{workflow_type}' not found in registry.")

        state_model_path = self.workflow_registry[workflow_type]["initial_state_model_path"]
        return self._import_from_string(state_model_path)

    def create_workflow(self, workflow_type: str,
                        persistence_provider: PersistenceProvider,
                        execution_provider: ExecutionProvider,
                        workflow_builder_instance: 'WorkflowBuilder',
                        expression_evaluator_cls: Type[ExpressionEvaluator],
                        template_engine_cls: Type[TemplateEngine],
                        workflow_observer: WorkflowObserver,
                        initial_data: Dict[str, Any] = None,
                        owner_id: Optional[str] = None,
                        org_id: Optional[str] = None,
                        data_region: Optional[str] = None,
                        priority: Optional[int] = None,
                        idempotency_key: Optional[str] = None,
                        metadata: Optional[Dict[str, Any]] = None
                        ) -> Workflow:

        if any(p is None for p in [persistence_provider, execution_provider, workflow_builder_instance,
                                   expression_evaluator_cls, template_engine_cls, workflow_observer]):
            raise ValueError(
                "All provider and class instances must be provided to create_workflow.")

        config_info = self.workflow_registry.get(workflow_type)
        if not config_info:
            raise ValueError(
                f"Workflow type '{workflow_type}' not found in registry.")

        state_model_class = self._import_from_string(
            config_info["initial_state_model_path"])

        initial_state = state_model_class(
            **initial_data) if initial_data else state_model_class()

        workflow_config = self.get_workflow_config(workflow_type)
        steps_config = workflow_config.get("steps", [])
        workflow_steps = self._build_steps_from_config(steps_config)

        return Workflow(
            workflow_type=workflow_type,
            workflow_steps=workflow_steps,
            initial_state_model=initial_state,
            steps_config=steps_config,
            state_model_path=config_info["initial_state_model_path"],
            owner_id=owner_id,
            org_id=org_id,
            data_region=data_region,
            priority=priority,
            idempotency_key=idempotency_key,
            metadata=metadata,
            persistence_provider=persistence_provider,
            execution_provider=execution_provider,
            workflow_builder=workflow_builder_instance,
            expression_evaluator_cls=expression_evaluator_cls,
            template_engine_cls=template_engine_cls,
            workflow_observer=workflow_observer
        )

    def get_all_task_modules(self) -> List[str]:
        modules = set()

        for workflow_type in self.workflow_registry.keys():
            config = self.get_workflow_config(workflow_type)
            steps = config.get("steps", [])
            self._collect_modules_from_steps(steps, modules)

        return list(modules)

    @classmethod
    def _collect_modules_from_steps(cls, steps: List[Dict[str, Any]], modules: set):
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