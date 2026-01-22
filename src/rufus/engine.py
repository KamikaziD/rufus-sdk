from typing import Dict, Any, Optional, List, Type

from rufus.models import (
    WorkflowStep, CompensatableStep, AsyncWorkflowStep, HttpWorkflowStep,
    FireAndForgetWorkflowStep, LoopStep, CronScheduleWorkflowStep, ParallelExecutionTask,
    ParallelWorkflowStep, WorkflowJumpDirective, WorkflowNextStepDirective,
    WorkflowPauseDirective, SagaWorkflowException, StartSubWorkflowDirective, StepContext, WorkflowFailedException
)

from rufus.providers.persistence import PersistenceProvider
from rufus.providers.execution import ExecutionProvider
from rufus.providers.observer import WorkflowObserver
from rufus.providers.expression_evaluator import ExpressionEvaluator
from rufus.providers.template_engine import TemplateEngine
from rufus.workflow import Workflow # Import Workflow from its new location
from rufus.builder import WorkflowBuilder # For builder._import_from_string

class WorkflowEngine:
    def __init__(self,
                 persistence: PersistenceProvider,
                 executor: ExecutionProvider,
                 observer: Optional[WorkflowObserver] = None,
                 workflow_registry: Optional[Dict[str, Any]] = None,
                 # Will be WorkflowBuilder
                 workflow_builder: Optional[Any] = None,
                 expression_evaluator_cls: Type[ExpressionEvaluator] = None,
                 template_engine_cls: Type[TemplateEngine] = None
                 ):
        self.persistence = persistence
        self.executor = executor
        self.observer = observer
        # type: Dict[str, Dict[str, Any]] # Stores raw YAML/dict definitions
        self.workflow_registry = workflow_registry or {}
        self.expression_evaluator_cls = expression_evaluator_cls
        self.template_engine_cls = template_engine_cls

        if self.observer is None:
            from rufus.implementations.observability.noop import NoopWorkflowObserver
            self.observer = NoopWorkflowObserver()

        if self.expression_evaluator_cls is None:
            from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
            self.expression_evaluator_cls = SimpleExpressionEvaluator
        
        if self.template_engine_cls is None:
            from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
            self.template_engine_cls = Jinja2TemplateEngine

        if self.workflow_builder is None:
            # Lazy import to avoid circular dependency, now that Workflow is in its own file
            from rufus.builder import WorkflowBuilder
            self.workflow_builder = WorkflowBuilder(
                expression_evaluator_cls=self.expression_evaluator_cls,
                template_engine_cls=self.template_engine_cls,
                workflow_registry=self.workflow_registry  # Pass registry for definition lookup
            )


    def register_workflow(self, workflow_definition: Dict[str, Any]):
        workflow_type = workflow_definition.get("workflow_type")
        if not workflow_type:
            raise ValueError(
                "Workflow definition must have a 'workflow_type'.")
        self.workflow_registry[workflow_type] = workflow_definition

    def start_workflow(self, workflow_type: str, initial_data: Dict[str, Any], **kwargs) -> Workflow:
        workflow_definition = self.workflow_registry.get(workflow_type)
        if not workflow_definition:
            raise ValueError(
                f"Workflow type '{workflow_type}' not registered.")

        # The actual workflow object is created here
        workflow = self.workflow_builder.create_workflow(
            workflow_type=workflow_type,
            initial_data=initial_data,
            persistence_provider=self.persistence,
            execution_provider=self.executor,
            workflow_builder=self.workflow_builder,  # Pass self for child workflows
            expression_evaluator_cls=self.expression_evaluator_cls,
            template_engine_cls=self.template_engine_cls,
            workflow_observer=self.observer,
            **kwargs
        )
        self.persistence.save_workflow(workflow.id, workflow.to_dict())
        return workflow

    def get_workflow(self, workflow_id: str) -> Workflow:
        workflow_data = self.persistence.load_workflow(workflow_id)
        if not workflow_data:
            raise ValueError(f"Workflow with ID '{workflow_id}' not found.")

        # Reconstruct workflow object from persisted data
        return Workflow.from_dict(
            workflow_data,
            persistence_provider=self.persistence,
            execution_provider=self.executor,
            workflow_builder=self.workflow_builder,
            expression_evaluator_cls=self.expression_evaluator_cls,
            template_engine_cls=self.template_engine_cls,
            workflow_observer=self.observer
        )

    def list_workflows(self, **filters) -> List[Workflow]:
        workflow_data_list = self.persistence.list_workflows(**filters)
        return [
            Workflow.from_dict(
                data,
                persistence_provider=self.persistence,
                execution_provider=self.executor,
                workflow_builder=self.workflow_builder,
                expression_evaluator_cls=self.expression_evaluator_cls,
                template_engine_cls=self.template_engine_cls,
                workflow_observer=self.observer
            ) for data in workflow_data_list
        ]