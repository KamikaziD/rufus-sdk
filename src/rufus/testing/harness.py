from typing import Dict, Any, Optional, List, Callable, Type
from rufus.engine import WorkflowEngine
from rufus.models import BaseModel, WorkflowStep, StepContext, CompensatableStep, SagaWorkflowException
# from rufus.builder import WorkflowBuilder # Will be imported locally where needed
# Use string literal type hints for providers to avoid NameError during type hinting
# if a circular dependency arises during parsing.
# The actual types will be resolved at runtime.
# from rufus.providers.persistence import PersistenceProvider
# from rufus.providers.execution import ExecutionProvider
# from rufus.providers.observer import WorkflowObserver
# from rufus.providers.expression_evaluator import ExpressionEvaluator
# from rufus.providers.template_engine import TemplateEngine
import copy
import yaml
from pathlib import Path
import asyncio

from rufus.implementations.persistence.memory import InMemoryPersistence # Added import
from rufus.implementations.execution.sync import SyncExecutor # Added import
from rufus.implementations.observability.logging import LoggingObserver # Added import
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator # Added import
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine # Added import


class WorkflowTestHarness:
    """
    A tool for testing Rufus workflows locally and synchronously.
    It provides an isolated environment for workflow execution, allowing
    mocking of step functions and inspection of workflow state.
    """

    def __init__(self, workflow_type: str, workflow_config: Dict[str, Any], initial_data: Optional[Dict[str, Any]] = None):
        self.workflow_type = workflow_type
        self.workflow_config = workflow_config
        self.initial_data = initial_data or {}

        # Providers for the test harness (synchronous initialization)
        self.persistence = InMemoryPersistence()
        self.executor = SyncExecutor()
        self.observer = LoggingObserver() # Use a logging observer for test output
        self.expression_evaluator_cls = SimpleExpressionEvaluator
        self.template_engine_cls = Jinja2TemplateEngine

        self.engine: Optional[WorkflowEngine] = None # Will be set during _ainit
        self.workflow: Optional[WorkflowEngine] = None
        self._mocked_steps: Dict[str, Callable] = {}
        self._mocked_step_results: Dict[str, Any] = {}
        self._mocked_step_exceptions: Dict[str, Exception] = {}
        self._compensation_log: List[Dict[str, Any]] = []
        
        # Do NOT call asyncio.run here. The test function using the harness
        # should call await harness._ainit() to properly initialize.
        # asyncio.run(self._ainit())

    async def _ainit(self):
        """Asynchronously initializes the harness components."""
        # Create a minimal registry for the WorkflowEngine
        workflow_registry_for_harness = {self.workflow_type: self.workflow_config}
        
        self.engine = WorkflowEngine(
            workflow_registry=workflow_registry_for_harness,
            persistence=self.persistence,
            executor=self.executor,
            observer=self.observer,
            expression_evaluator_cls=self.expression_evaluator_cls,
            template_engine_cls=self.template_engine_cls
        )
        await self.engine.initialize() # Initialize the engine after creation
        await self._reset_workflow()

    # Removed _get_configured_engine as it's no longer needed, WorkflowEngine is built directly
    # And initialize is called on the engine instance.

    async def _reset_workflow(self):
        """Creates a fresh workflow instance for testing."""
        self.workflow = await self.engine.start_workflow(
            workflow_type=self.workflow_type,
            initial_data=self.initial_data
        )
        self._original_step_funcs = {step.name: step.func for step in self.workflow.workflow_steps}
        self._original_compensate_funcs = {}
        for step in self.workflow.workflow_steps:
            if isinstance(step, CompensatableStep):
                self._original_compensate_funcs[step.name] = step.compensate_func

    @classmethod
    def from_yaml(cls, workflow_file_path: str, initial_data: Optional[Dict[str, Any]] = None):
        """
        Creates a TestHarness for a single workflow defined in a YAML file.
        """
        workflow_file = Path(workflow_file_path)
        if not workflow_file.is_file():
            raise FileNotFoundError(f"Workflow file not found at {workflow_file_path}")

        with open(workflow_file, "r") as f:
            workflow_config = yaml.safe_load(f)
        
        if not isinstance(workflow_config, dict) or "workflow_type" not in workflow_config:
            raise ValueError(f"Invalid workflow YAML in {workflow_file_path}. Missing 'workflow_type'.")

        workflow_type = workflow_config["workflow_type"]
        
        # The Harness will directly use this workflow_config for its internal registry
        return cls(workflow_type, workflow_config, initial_data)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Cleanup any temporary resources, though for InMemoryPersistence/SyncExecutor
        # there's usually nothing to do here besides clearing state if needed.
        asyncio.run(self.persistence.close())
        asyncio.run(self.observer.close())
        asyncio.run(self.executor.close()) # SyncExecutor's close is currently a no-op

    def mock_step(self, step_name: str, returns: Any = None, raises: Optional[Exception] = None):
        """
        Mocks a specific workflow step to return a predefined value or raise an exception.
        """
        self._mocked_step_results[step_name] = returns
        self._mocked_step_exceptions[step_name] = raises

        # Check if self.workflow is initialized, as it's now async
        if not self.workflow:
            raise RuntimeError("WorkflowTestHarness must be initialized with await harness._ainit() before mocking steps.")

        for step in self.workflow.workflow_steps:
            if step.name == step_name:
                self._original_step_funcs[step_name] = step.func # Store original
                
                async def mock_func(state: BaseModel, context: StepContext): # Changed to async
                    if raises:
                        raise raises
                    if returns is not None:
                        # Merge mock return into state if it's a dict
                        # This should eventually use the merge strategies, but for mocking,
                        # a simple update is often sufficient.
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
        # Check if self.workflow is initialized, as it's now async
        if not self.workflow:
            raise RuntimeError("WorkflowTestHarness must be initialized with await harness._ainit() before mocking compensation.")

        for step in self.workflow.workflow_steps:
            if step.name == step_name and isinstance(step, CompensatableStep):
                self._original_compensate_funcs[step_name] = step.compensate_func # Store original
                
                async def mock_comp_func(state: BaseModel, context: StepContext): # Changed to async
                    self._compensation_log.append({"step_name": step_name, "action": "mocked_compensate", "result": returns, "error": str(raises)})
                    if raises:
                        raise raises
                    return returns if returns is not None else {"mock_compensated": True}
                step.compensate_func = mock_comp_func
                return
        raise ValueError(f"Compensatable step '{step_name}' not found.")

    async def run_all_steps(self, input_data_per_step: Optional[Dict[str, Any]] = None) -> WorkflowEngine:
        """
        Runs all remaining steps in the workflow until completion or failure.
        Provides input data for steps if specified.
        """
        if not self.workflow:
            raise RuntimeError("WorkflowTestHarness must be initialized with await harness._ainit() before running steps.")

        input_data_per_step = input_data_per_step or {}
        
        while self.workflow.status not in ["COMPLETED", "FAILED", "FAILED_ROLLED_BACK"]:
            current_step_name = self.workflow.current_step_name
            input_for_step = input_data_per_step.get(current_step_name, {})

            try:
                result, next_step_name = await self.workflow.next_step(user_input=input_for_step)
                if self.workflow.status == "PENDING_ASYNC":
                    # In sync executor, next_step processes the task directly
                    # The internal logic handles resumption.
                    # This branch should ideally not be hit with SyncExecutor unless the task fails internally.
                    pass
                elif self.workflow.status == "WAITING_HUMAN":
                    # For testing, we might want to automatically resume or inspect.
                    # This simple harness will just stop here.
                    print(f"Harness: Workflow waiting for human input at {current_step_name}. Stopping run_all_steps.")
                    return self.workflow

            except Exception as e:
                print(f"Harness: Workflow failed at step {current_step_name} with error: {e}")
                return self.workflow
        return self.workflow

    def reset_mocks(self):
        """Resets all mocked steps to their original implementations."""
        if not self.workflow:
            raise RuntimeError("WorkflowTestHarness must be initialized with await harness._ainit() before resetting mocks.")

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
        if not self.workflow:
            raise RuntimeError("WorkflowTestHarness must be initialized with await harness._ainit() before accessing current_state.")
        return self.workflow.state

    @property
    def current_status(self) -> str:
        """Returns the current status of the workflow."""
        if not self.workflow:
            raise RuntimeError("WorkflowTestHarness must be initialized with await harness._ainit() before accessing current_status.")
        return self.workflow.status

    @property
    def workflow_id(self) -> str:
        """Returns the ID of the workflow being tested."""
        if not self.workflow:
            raise RuntimeError("WorkflowTestHarness must be initialized with await harness._ainit() before accessing workflow_id.")
        return self.workflow.id