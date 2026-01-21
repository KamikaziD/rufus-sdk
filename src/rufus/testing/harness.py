from typing import Dict, Any, Optional, List, Callable, Type
from rufus.engine import WorkflowEngine
from rufus.models import BaseModel, WorkflowStep, StepContext, CompensatableStep, SagaWorkflowException
from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
import copy

class WorkflowTestHarness:
    """
    A tool for testing Rufus workflows locally and synchronously.
    It provides an isolated environment for workflow execution, allowing
    mocking of step functions and inspection of workflow state.
    """

    def __init__(self, workflow_type: str, initial_data: Optional[Dict[str, Any]] = None,
                 registry_path: str = "config/workflow_registry.yaml"):
        self.workflow_type = workflow_type
        self.initial_data = initial_data or {}
        self.registry_path = registry_path

        self.persistence = InMemoryPersistence()
        self.executor = SyncExecutor()
        self.observer = LoggingObserver() # Use a logging observer for test output
        self.builder = WorkflowBuilder(registry_path=self.registry_path)
        self.expression_evaluator_cls = SimpleExpressionEvaluator
        self.template_engine_cls = Jinja2TemplateEngine

        self._reset_workflow()
        self._mocked_steps: Dict[str, Callable] = {}
        self._mocked_step_results: Dict[str, Any] = {}
        self._mocked_step_exceptions: Dict[str, Exception] = {}
        self._compensation_log: List[Dict[str, Any]] = []

    def _reset_workflow(self):
        """Creates a fresh workflow instance for testing."""
        self.workflow = self.builder.create_workflow(
            workflow_type=self.workflow_type,
            initial_data=self.initial_data,
            persistence_provider=self.persistence,
            execution_provider=self.executor,
            workflow_builder=self.builder,
            expression_evaluator_cls=self.expression_evaluator_cls,
            template_engine_cls=self.template_engine_cls,
            workflow_observer=self.observer
        )
        self._original_step_funcs = {step.name: step.func for step in self.workflow.workflow_steps}
        self._original_compensate_funcs = {}
        for step in self.workflow.workflow_steps:
            if isinstance(step, CompensatableStep):
                self._original_compensate_funcs[step.name] = step.compensate_func

    @classmethod
    def from_yaml(cls, workflow_file_path: str, initial_data: Optional[Dict[str, Any]] = None):
        """
        Creates a TestHarness for a single workflow defined in a YAML file,
        bypassing the need for a full registry.
        """
        # Create a temporary registry for this single file
        import tempfile
        import shutil
        temp_dir = Path(tempfile.mkdtemp())
        temp_config_dir = temp_dir / "config"
        temp_config_dir.mkdir()

        workflow_file = Path(workflow_file_path)
        shutil.copy(workflow_file, temp_config_dir / workflow_file.name)

        workflow_name = workflow_file.stem.replace('-', '_').title().replace('_', '') + "Workflow"
        
        # We need to infer the state model path or use a dummy. For testing, a dummy is fine.
        # In a real scenario, the test writer would provide the actual state model.
        dummy_state_model_path = "pydantic.BaseModel" # Fallback if not specified
        try:
            with open(workflow_file, "r") as f:
                workflow_config = yaml.safe_load(f)
                if workflow_config and "initial_state_model" in workflow_config:
                    dummy_state_model_path = workflow_config["initial_state_model"]
        except Exception:
            pass # Use default

        temp_registry_content = {
            "workflows": [
                {
                    "type": workflow_name,
                    "description": f"Temporary workflow for {workflow_file.name}",
                    "config_file": workflow_file.name,
                    "initial_state_model": dummy_state_model_path
                }
            ]
        }
        temp_registry_path = temp_config_dir / "temp_cli_registry.yaml"
        with open(temp_registry_path, "w") as f:
            yaml.dump(temp_registry_content, f)

        harness = cls(workflow_name, initial_data, registry_path=str(temp_registry_path))
        harness._temp_dir = temp_dir # Store for cleanup
        return harness

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Clean up temporary directory if created by from_yaml
        if hasattr(self, '_temp_dir') and self._temp_dir.exists():
            import shutil
            shutil.rmtree(self._temp_dir)

    def mock_step(self, step_name: str, returns: Any = None, raises: Optional[Exception] = None):
        """
        Mocks a specific workflow step to return a predefined value or raise an exception.
        """
        self._mocked_step_results[step_name] = returns
        self._mocked_step_exceptions[step_name] = raises

        for step in self.workflow.workflow_steps:
            if step.name == step_name:
                self._original_step_funcs[step_name] = step.func # Store original
                
                def mock_func(state: BaseModel, context: StepContext):
                    if raises:
                        raise raises
                    if returns is not None:
                        # Merge mock return into state if it's a dict
                        if isinstance(returns, dict):
                            for key, value in returns.items():
                                if hasattr(state, key):
                                    setattr(state, key, value)
                        return returns
                    return {} # Default return
                step.func = mock_func
                return
        raise ValueError(f"Step '{step_name}' not found in workflow.")

    def mock_compensation(self, step_name: str, returns: Any = None, raises: Optional[Exception] = None):
        """
        Mocks the compensation function for a specific compensatable step.
        """
        for step in self.workflow.workflow_steps:
            if step.name == step_name and isinstance(step, CompensatableStep):
                self._original_compensate_funcs[step_name] = step.compensate_func # Store original
                
                def mock_comp_func(state: BaseModel, context: StepContext):
                    self._compensation_log.append({"step_name": step_name, "action": "mocked_compensate", "result": returns, "error": str(raises)})
                    if raises:
                        raise raises
                    return returns if returns is not None else {"mock_compensated": True}
                step.compensate_func = mock_comp_func
                return
        raise ValueError(f"Compensatable step '{step_name}' not found.")

    def run_all_steps(self, input_data_per_step: Optional[Dict[str, Any]] = None) -> WorkflowEngine:
        """
        Runs all remaining steps in the workflow until completion or failure.
        Provides input data for steps if specified.
        """
        input_data_per_step = input_data_per_step or {}
        
        while self.workflow.status not in ["COMPLETED", "FAILED", "FAILED_ROLLED_BACK"]:
            current_step_name = self.workflow.current_step_name
            input_for_step = input_data_per_step.get(current_step_name, {})

            try:
                result, next_step_name = self.workflow.next_step(user_input=input_for_step)
                if self.workflow.status == "PENDING_ASYNC":
                    # In sync executor, next_step processes the task directly
                    # The internal logic handles resumption.
                    # This branch should ideally not be hit with SyncExecutor unless the task fails internally.
                    pass
                elif self.workflow.status == "WAITING_HUMAN":
                    # For testing, we might want to automatically resume or inspect.
                    # This simple harness will just stop here.
                    return self.workflow

            except Exception as e:
                return self.workflow
        return self.workflow

    def reset_mocks(self):
        """Resets all mocked steps to their original implementations."""
        for step in self.workflow.workflow_steps:
            if step.name in self._original_step_funcs:
                step.func = self._original_step_funcs[step.name]
            if isinstance(step, CompensatableStep) and step.name in self._original_compensate_funcs:
                step.compensate_func = self._original_compensate_funcs[step.name]
        self._mocked_steps = {}
        self._mocked_step_results = {}
        self._mocked_step_exceptions = {}
        self._compensation_log = []

    def get_compensation_log(self) -> List[Dict[str, Any]]:
        """Returns the log of executed compensation actions during the test."""
        return copy.deepcopy(self._compensation_log)

    @property
    def current_state(self) -> BaseModel:
        """Returns the current state of the workflow."""
        return self.workflow.state

    @property
    def current_status(self) -> str:
        """Returns the current status of the workflow."""
        return self.workflow.status

    @property
    def workflow_id(self) -> str:
        """Returns the ID of the workflow being tested."""
        return self.workflow.id
