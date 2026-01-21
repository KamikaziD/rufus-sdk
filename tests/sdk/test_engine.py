import pytest
import os
# Add the 'tests' directory to the Python path to allow direct imports


from rufus.testing.harness import WorkflowTestHarness
from sdk.modules.state_models import LoanApplicationState, UserProfileState
import sdk.modules.steps.loan

# --- Imports for new test ---
from rufus.engine import WorkflowEngine
from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
from rufus.models import BaseModel, WorkflowStep, CompensatableStep, SagaWorkflowException, StepContext, Any, AsyncWorkflowStep, Dict, Optional, WorkflowJumpDirective, WorkflowPauseDirective, HttpWorkflowStep, List, StartSubWorkflowDirective, FireAndForgetWorkflowStep, LoopStep, CronScheduleWorkflowStep, WorkflowFailedException
from pydantic import BaseModel, Field, ValidationError
from typing import Callable

# --- Helper Stubs for Provider Tests ---


class MockPersistence(InMemoryPersistence):
    # Override log_compensation to capture it
    def __init__(self):
        super().__init__()
        self.compensation_logs = []
        self.workflow_states = {}  # To simulate saving/loading workflow

    def save_workflow(self, workflow_id: str, data: Dict[str, Any], sync: bool = True):
        self.workflow_states[workflow_id] = data
        super().save_workflow(workflow_id, data, sync)

    def load_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        return self.workflow_states.get(workflow_id)

    def log_compensation(self, execution_id: str, step_name: str, step_index: int, action_type: str, action_result: dict, state_before: dict = None, state_after: dict = None, error_message: str = None):
        self.compensation_logs.append({
            "execution_id": execution_id,
            "step_name": step_name,
            "step_index": step_index,
            "action_type": action_type,
            "action_result": action_result,
            "error_message": error_message
        })
        super().log_compensation(execution_id, step_name, step_index, action_type,
                                 action_result, state_before, state_after, error_message)


class MockExecutor(SyncExecutor):
    def __init__(self):
        super().__init__()
        self._mock_sync_step_exception = None
        self._mock_sync_step_name = None
        self._mock_async_dispatch_result = None
        self.reported_child_statuses = []  # New list to capture reported statuses
        self.mock_step_functions = {}

    def mock_step_function(self, step_name: str, func: Callable):
        self.mock_step_functions[step_name] = func

    def set_mock_sync_step_exception(self, step_name: str, exception: Exception):
        self._mock_sync_step_exception = exception
        self._mock_sync_step_name = step_name

    def execute_sync_step_function(self, func, state: BaseModel, context: StepContext) -> Any:
        
        if context.step_name in self.mock_step_functions:
            return self.mock_step_functions[context.step_name](state=state, context=context)

        if context.step_name == self._mock_sync_step_name and self._mock_sync_step_exception:
            raise self._mock_sync_step_exception

        try:
            result = func(state=state, context=context)
            return result
        except Exception as e:
            raise e  # Re-raise it!

    def dispatch_async_task(self, func_path: str, state_data: Dict[str, Any], workflow_id: str, current_step_index: int, data_region: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        if self._mock_async_dispatch_result:
            return self._mock_async_dispatch_result
        return super().dispatch_async_task(func_path, state_data, workflow_id, current_step_index, data_region, **kwargs)

    def report_child_status_to_parent(self, child_id: str, parent_id: str, child_new_status: str, child_current_step_name: Optional[str] = None, child_result: Optional[Dict[str, Any]] = None):
        self.reported_child_statuses.append({
            "child_id": child_id,
            "parent_id": parent_id,
            "child_new_status": child_new_status,
            "child_current_step_name": child_current_step_name,
            "child_result": child_result
        })


class MockObserver(LoggingObserver):
    def __init__(self):
        super().__init__()
        self.workflow_rolled_back_calls = []
        self.workflow_failed_calls = []
        self.workflow_status_changed_calls = []

    def on_workflow_rolled_back(self, workflow_id: str, workflow_type: str, reason: str, final_state: BaseModel, completed_steps_stack: list):
        self.workflow_rolled_back_calls.append({
            "workflow_id": workflow_id,
            "workflow_type": workflow_type,
            "reason": reason,
            "final_state": final_state.model_dump() if final_state else None
        })
        super().on_workflow_rolled_back(workflow_id, workflow_type,
                                        reason, final_state, completed_steps_stack)

    def on_workflow_failed(self, workflow_id: str, workflow_type: str, reason: str, final_state: BaseModel):
        self.workflow_failed_calls.append({
            "workflow_id": workflow_id,
            "workflow_type": workflow_type,
            "reason": reason,
            "final_state": final_state.model_dump() if final_state else None
        })
        super().on_workflow_failed(workflow_id, workflow_type, reason, final_state)

    def on_workflow_status_changed(self, workflow_id: str, old_status: str, new_status: str, step_name: Optional[str] = None):
        self.workflow_status_changed_calls.append({
            "workflow_id": workflow_id,
            "old_status": old_status,
            "new_status": new_status,
            "step_name": step_name
        })
        super().on_workflow_status_changed(workflow_id, old_status, new_status, step_name)


class MockBuilder(WorkflowBuilder):
    def __init__(self):
        pass  # Override init to avoid loading registry

    def build_steps_from_config(self, steps_config: list):
        # Mock step building for from_dict to work, and for dynamic injection
        built_steps = []
        for config in steps_config:
            # Assume all injected steps are standard for this test
            if config.get("compensate_function"):
                built_steps.append(MockCompensatableStep(name=config["name"], func=lambda state, context: {
                }, compensate_func=lambda state, context: {}))
            elif config.get("type") == "ASYNC":
                built_steps.append(AsyncWorkflowStep(
                    name=config["name"], func_path="some.func", required_input=[], input_schema=None))
            elif config.get("type") == "HTTP":
                built_steps.append(HttpWorkflowStep(
                    name=config["name"], http_config={}, required_input=[], input_schema=None))
            else:
                built_steps.append(WorkflowStep(
                    name=config["name"], func=lambda state, context: {}))
        return built_steps


class MockExpressionEvaluator(SimpleExpressionEvaluator):
    def __init__(self, state: dict):
        super().__init__(state)
        self._mock_evaluate_result = True

    def evaluate(self, expression: str) -> bool:
        return self._mock_evaluate_result

    def set_mock_evaluate_result(self, result: bool):
        self._mock_evaluate_result = result


class MockTemplateEngine(Jinja2TemplateEngine):
    def __init__(self, context: dict):
        super().__init__(context)


class DummyState(BaseModel):
    value: str = "default_value"


class DynamicState(BaseModel):
    condition_value: str = "default"


class SagaState(BaseModel):
    step1_done: bool = False
    step2_done: bool = False
    compensation_called: int = 0


def mock_compensate_func(state: SagaState, context: StepContext):
    state.compensation_called += 1
    return {"compensated": context.step_name}


class MockCompensatableStep(CompensatableStep):
    def __init__(self, name: str, func, compensate_func):
        super().__init__(name=name, func=func, compensate_func=compensate_func)
        self.compensated_count = 0

    def compensate(self, state: BaseModel, context: StepContext):
        self.compensated_count += 1
        return self.compensate_func(state, context)


def test_workflow_creation_and_first_step(monkeypatch):
    # Mock the functions directly using monkeypatch
    monkeypatch.setattr(sdk.modules.steps.loan, "run_credit_check_agent", lambda state: {
                        "credit_check": {"score": 750, "report_id": "CR750", "risk_level": "low"}})
    monkeypatch.setattr(sdk.modules.steps.loan, "run_fraud_detection_agent", lambda state: {
                        "fraud_check": {"status": "CLEAN", "score": 0.1}})
    monkeypatch.setattr(sdk.modules.steps.loan, "run_kyc_workflow", lambda state, context: {
                        "kyc_results": {"kyc_overall_status": "APPROVED"}})
    monkeypatch.setattr(sdk.modules.steps.loan, "run_full_underwriting_agent", lambda state: {
                        "underwriting_result": {"risk_score": 0.004, "recommendation": "APPROVE"}})
    monkeypatch.setattr(sdk.modules.steps.loan, "run_simplified_underwriting_agent", lambda state: {
                        "underwriting_result": {"risk_score": 0.002, "recommendation": "APPROVE"}})

    harness = WorkflowTestHarness(
        workflow_type="LoanApplication",
        initial_data={
            "requested_amount": 10000.0,
            "applicant_profile": {
                "user_id": "U123",
                "name": "Test User",
                "email": "test@example.com",
                "country": "US",
                "age": 30,
                "id_document_url": "http://example.com/id.jpg"
            }
        },
        registry_path="tests/sdk/config/workflow_registry.yaml"
    )

    # Check initial state
    assert harness.workflow_id is not None
    assert harness.current_status == "ACTIVE"
    assert harness.current_state.applicant_profile.name == "Test User"

    # Run the workflow
    harness.run_all_steps(input_data_per_step={
        "Process_Human_Decision": {
            "decision": "APPROVED",
            "reviewer_id": "test-reviewer"
        }
    })

    # After all steps, the workflow should be completed.
    assert harness.current_status == "COMPLETED"
    assert harness.current_state.final_loan_status == "APPROVED"


def test_workflow_engine_init_provider_validation():
    # Prepare valid mock providers
    mock_persistence = MockPersistence()
    mock_executor = MockExecutor()
    mock_observer = MockObserver()
    mock_builder = MockBuilder()
    mock_expression_evaluator_cls = MockExpressionEvaluator
    mock_template_engine_cls = MockTemplateEngine

    # Test case 1: All providers present (should not raise error)
    try:
        engine = WorkflowEngine(
            workflow_type="TestWorkflow",
            persistence_provider=mock_persistence,
            execution_provider=mock_executor,
            workflow_builder=mock_builder,
            expression_evaluator_cls=mock_expression_evaluator_cls,
            template_engine_cls=mock_template_engine_cls,
            workflow_observer=mock_observer,
            initial_state_model=DummyState()
        )
        assert engine is not None
    except ValueError as e:
        pytest.fail(
            f"WorkflowEngine.__init__ raised ValueError unexpectedly: {e}")

    # Test cases for missing each provider
    with pytest.raises(ValueError, match="PersistenceProvider must be injected"):
        WorkflowEngine(
            workflow_type="TestWorkflow",
            execution_provider=mock_executor,
            workflow_builder=mock_builder,
            expression_evaluator_cls=mock_expression_evaluator_cls,
            template_engine_cls=mock_template_engine_cls,
            workflow_observer=mock_observer,
            initial_state_model=DummyState()
        )

    with pytest.raises(ValueError, match="ExecutionProvider must be injected"):
        WorkflowEngine(
            workflow_type="TestWorkflow",
            persistence_provider=mock_persistence,
            workflow_builder=mock_builder,
            expression_evaluator_cls=mock_expression_evaluator_cls,
            template_engine_cls=mock_template_engine_cls,
            workflow_observer=mock_observer,
            initial_state_model=DummyState()
        )

    with pytest.raises(ValueError, match="WorkflowBuilder must be injected"):
        WorkflowEngine(
            workflow_type="TestWorkflow",
            persistence_provider=mock_persistence,
            execution_provider=mock_executor,
            expression_evaluator_cls=mock_expression_evaluator_cls,
            template_engine_cls=mock_template_engine_cls,
            workflow_observer=mock_observer,
            initial_state_model=DummyState()
        )

    with pytest.raises(ValueError, match="ExpressionEvaluator class must be injected"):
        WorkflowEngine(
            workflow_type="TestWorkflow",
            persistence_provider=mock_persistence,
            execution_provider=mock_executor,
            workflow_builder=mock_builder,
            template_engine_cls=mock_template_engine_cls,
            workflow_observer=mock_observer,
            initial_state_model=DummyState()
        )

    with pytest.raises(ValueError, match="TemplateEngine class must be injected"):
        WorkflowEngine(
            workflow_type="TestWorkflow",
            persistence_provider=mock_persistence,
            execution_provider=mock_executor,
            workflow_builder=mock_builder,
            expression_evaluator_cls=mock_expression_evaluator_cls,
            workflow_observer=mock_observer,
            initial_state_model=DummyState()
        )

    with pytest.raises(ValueError, match="WorkflowObserver must be injected"):
        WorkflowEngine(
            workflow_type="TestWorkflow",
            persistence_provider=mock_persistence,
            execution_provider=mock_executor,
            workflow_builder=mock_builder,
            expression_evaluator_cls=mock_expression_evaluator_cls,
            template_engine_cls=mock_template_engine_cls,
            initial_state_model=DummyState()
        )


def test_workflow_engine_from_dict_reconstruction():
    # Prepare valid mock providers
    mock_persistence = MockPersistence()
    mock_executor = MockExecutor()
    mock_observer = MockObserver()
    mock_builder = MockBuilder()
    mock_expression_evaluator_cls = MockExpressionEvaluator
    mock_template_engine_cls = MockTemplateEngine

    original_engine = WorkflowEngine(
        workflow_id="test-123",
        workflow_type="TestWorkflow",
        initial_state_model=DummyState(value="original_value"),
        # Provide dummy workflow steps
        workflow_steps=[WorkflowStep(
            name="Step1", func=lambda state, context: {})],
        steps_config=[{"name": "Step1", "type": "STANDARD"}],
        state_model_path="tests.sdk.test_engine.DummyState",
        owner_id="owner-456",
        org_id="org-789",
        persistence_provider=mock_persistence,
        execution_provider=mock_executor,
        workflow_builder=mock_builder,
        expression_evaluator_cls=mock_expression_evaluator_cls,
        template_engine_cls=mock_template_engine_cls,
        workflow_observer=mock_observer
    )
    original_engine.current_step = 1
    original_engine.status = "PAUSED"
    original_engine.saga_mode = True
    original_engine.completed_steps_stack = [
        {"step_name": "PrevStep", "step_index": 0}]
    original_engine.parent_execution_id = "parent-000"
    original_engine.blocked_on_child_id = "child-111"
    original_engine.data_region = "US-EAST"
    original_engine.priority = 10
    original_engine.idempotency_key = "key-abc"
    original_engine.metadata = {"custom": "data"}

    # Convert to dict
    engine_dict = original_engine.to_dict()

    # Reconstruct from dict
    reconstructed_engine = WorkflowEngine.from_dict(
        engine_dict,
        persistence_provider=mock_persistence,
        execution_provider=mock_executor,
        workflow_builder=mock_builder,
        expression_evaluator_cls=mock_expression_evaluator_cls,
        template_engine_cls=mock_template_engine_cls,
        workflow_observer=mock_observer
    )

    # Assert properties match
    assert reconstructed_engine.id == original_engine.id
    assert reconstructed_engine.workflow_type == original_engine.workflow_type
    assert reconstructed_engine.current_step == original_engine.current_step
    assert reconstructed_engine.status == original_engine.status
    assert reconstructed_engine.state.value == original_engine.state.value
    assert len(reconstructed_engine.workflow_steps) == len(
        original_engine.workflow_steps)
    assert reconstructed_engine.state_model_path == original_engine.state_model_path
    assert reconstructed_engine.owner_id == original_engine.owner_id
    assert reconstructed_engine.org_id == original_engine.org_id
    assert reconstructed_engine.saga_mode == original_engine.saga_mode
    assert reconstructed_engine.completed_steps_stack == original_engine.completed_steps_stack
    assert reconstructed_engine.parent_execution_id == original_engine.parent_execution_id
    assert reconstructed_engine.blocked_on_child_id == original_engine.blocked_on_child_id
    assert reconstructed_engine.data_region == original_engine.data_region
    assert reconstructed_engine.priority == original_engine.priority
    assert reconstructed_engine.idempotency_key == original_engine.idempotency_key
    assert reconstructed_engine.metadata == original_engine.metadata

    # Test error case: missing workflow_type or state_model_path
    invalid_dict = engine_dict.copy()
    del invalid_dict["workflow_type"]
    with pytest.raises(ValueError, match="Missing workflow_type or state_model_path in data."):
        WorkflowEngine.from_dict(
            invalid_dict,
            persistence_provider=mock_persistence,
            execution_provider=mock_executor,
            workflow_builder=mock_builder,
            expression_evaluator_cls=mock_expression_evaluator_cls,
            template_engine_cls=mock_template_engine_cls,
            workflow_observer=mock_observer
        )


def test_process_dynamic_injection():
    class DynamicState(BaseModel):
        condition_value: str = "default"

    mock_persistence = MockPersistence()
    mock_executor = MockExecutor()
    mock_observer = MockObserver()
    mock_builder = MockBuilder()  # This will need to be updated
    mock_expression_evaluator_cls = MockExpressionEvaluator
    mock_template_engine_cls = MockTemplateEngine

    # Initial setup without dynamic injection
    initial_steps_config = [
        {"name": "StepA", "type": "STANDARD"},
        {
            "name": "StepB",
            "type": "STANDARD",
            "dynamic_injection": {
                "rules": [
                    {
                        "condition_key": "condition_value",
                        "value_match": "inject_me",
                        "action": "INSERT_AFTER_CURRENT",
                        "steps_to_insert": [
                            {"name": "InjectedStep1", "type": "STANDARD"},
                            {"name": "InjectedStep2", "type": "STANDARD"}
                        ]
                    }
                ]
            }
        },
        {"name": "StepC", "type": "STANDARD"}
    ]

    # Build initial workflow steps using the mock builder
    initial_workflow_steps = mock_builder.build_steps_from_config(
        initial_steps_config)

    engine = WorkflowEngine(
        workflow_id="dynamic-test",
        workflow_type="DynamicWorkflow",
        initial_state_model=DynamicState(condition_value="default"),
        workflow_steps=initial_workflow_steps,  # Pass the built steps here
        steps_config=initial_steps_config,
        # This needs to be a valid path
        state_model_path="tests.sdk.test_engine.DynamicState",
        persistence_provider=mock_persistence,
        execution_provider=mock_executor,
        workflow_builder=mock_builder,
        expression_evaluator_cls=mock_expression_evaluator_cls,
        template_engine_cls=mock_template_engine_cls,
        workflow_observer=mock_observer
    )

    # Before injection, check steps
    assert len(engine.workflow_steps) == 3
    assert engine.workflow_steps[1].name == "StepB"

    # Set state to trigger injection
    engine.state.condition_value = "inject_me"
    engine.current_step = 1  # Point to StepB

    # Call dynamic injection processor
    injection_occurred = engine._process_dynamic_injection()

    assert injection_occurred is True
    assert len(engine.workflow_steps) == 5
    assert engine.workflow_steps[2].name == "InjectedStep1"
    assert engine.workflow_steps[3].name == "InjectedStep2"
    assert engine.workflow_steps[4].name == "StepC"

    # Test case where condition is not met
    engine.state.condition_value = "no_injection"
    engine.current_step = 1  # Point to StepB again
    original_len = len(engine.workflow_steps)
    injection_occurred_2 = engine._process_dynamic_injection()
    assert injection_occurred_2 is False
    assert len(engine.workflow_steps) == original_len


def test_next_step_workflow_jump_directive(monkeypatch):
    mock_persistence = MockPersistence()
    mock_executor = MockExecutor()
    mock_observer = MockObserver()
    mock_builder = MockBuilder()

    mock_template_engine_cls = MockTemplateEngine

    workflow_steps = [
        WorkflowStep(name="Step0", func=lambda state, context: {}),
        WorkflowStep(name="DecisionStep", func=lambda state, context: {}, routes=[
            {"condition": "true", "next_step": "TargetStep"},
            {"default": "Step2"}
        ]),
        WorkflowStep(name="Step2", func=lambda state, context: {}),
        WorkflowStep(name="TargetStep", func=lambda state, context: {})
    ]
    initial_state = DummyState(value="test")

    # --- Test Case 1: Jump Condition is True ---
    engine_true_jump = WorkflowEngine(
        workflow_id="jump-test-true",
        workflow_type="JumpWorkflow",
        initial_state_model=initial_state,
        workflow_steps=workflow_steps,
        steps_config=[],
        state_model_path="tests.sdk.test_engine.DummyState",
        persistence_provider=mock_persistence,
        execution_provider=mock_executor,
        workflow_builder=mock_builder,
        # Use the actual class, but we'll mock evaluate_routes
        expression_evaluator_cls=MockExpressionEvaluator,
        template_engine_cls=mock_template_engine_cls,
        workflow_observer=mock_observer
    )
    # Directly mock evaluate_routes for this engine instance
    monkeypatch.setattr(engine_true_jump, 'evaluate_routes',
                        lambda routes: "TargetStep")

    engine_true_jump.current_step = 1  # Point to DecisionStep
    assert engine_true_jump.current_step_name == "DecisionStep"

    result_true, next_step_name_true = engine_true_jump.next_step(
        user_input={})

    assert result_true == {"message": "Jumped to step TargetStep"}
    assert next_step_name_true == "TargetStep"
    assert engine_true_jump.current_step == 3  # Index of TargetStep
    assert engine_true_jump.status == "ACTIVE"

    # --- Test Case 2: Jump Condition is False (falls through) ---
    engine_false_jump = WorkflowEngine(
        workflow_id="jump-test-false",
        workflow_type="JumpWorkflow",
        initial_state_model=initial_state,
        workflow_steps=workflow_steps,
        steps_config=[],
        state_model_path="tests.sdk.test_engine.DummyState",
        persistence_provider=mock_persistence,
        execution_provider=mock_executor,
        workflow_builder=mock_builder,
        expression_evaluator_cls=MockExpressionEvaluator,  # Use the actual class
        template_engine_cls=mock_template_engine_cls,
        workflow_observer=mock_observer
    )
    # Directly mock evaluate_routes for this engine instance
    monkeypatch.setattr(engine_false_jump, 'evaluate_routes',
                        lambda routes: "Step2")

    engine_false_jump.current_step = 1  # Point to DecisionStep
    assert engine_false_jump.current_step_name == "DecisionStep"

    result_false, next_step_name_false = engine_false_jump.next_step(
        user_input={})
    assert result_false == {"message": "Jumped to step Step2"}
    assert next_step_name_false == "Step2"
    assert engine_false_jump.current_step == 2  # Index of Step2

    assert engine_false_jump.current_step == 2  # Index of Step2


def test_evaluate_routes_default_branch(common_providers, monkeypatch):
    # Monkeypatch the evaluate method of the MockExpressionEvaluator class
    # so that all instances created by evaluate_routes will use this mock
    monkeypatch.setattr(MockExpressionEvaluator, 'evaluate',
                        lambda inst, expression: False)

    engine = WorkflowEngine(
        workflow_id="default-route-test",
        workflow_type="DefaultRouteWorkflow",
        initial_state_model=DummyState(value="test"),
        persistence_provider=common_providers["persistence_provider"],
        execution_provider=common_providers["execution_provider"],
        workflow_builder=common_providers["workflow_builder"],
        expression_evaluator_cls=MockExpressionEvaluator,  # Pass the class itself
        template_engine_cls=common_providers["template_engine_cls"],
        workflow_observer=common_providers["workflow_observer"]
    )
    # The engine's expression_evaluator will be an instance of MockExpressionEvaluator
    # and its evaluate method will be the monkeypatched one.

    routes = [
        {"condition": "state.risk_score > 700", "next_step": "HighRiskStep"},
        {"condition": "state.risk_score > 600", "next_step": "MediumRiskStep"},
        {"default": "LowRiskStep"}
    ]

    # All conditions will be false due to monkeypatch, so default should be chosen
    next_step_name = engine.evaluate_routes(routes)
    assert next_step_name == "LowRiskStep"

    routes = [
        {"condition": "state.risk_score > 700", "next_step": "HighRiskStep"},
        {"condition": "state.risk_score > 600", "next_step": "MediumRiskStep"},
        {"default": "LowRiskStep"}
    ]

    # All conditions will be false, so default should be chosen
    next_step_name = engine.evaluate_routes(routes)
    assert next_step_name == "LowRiskStep"

    # Test with no matching conditions and no default
    routes_no_default = [
        {"condition": "state.risk_score > 700", "next_step": "HighRiskStep"},
        {"condition": "state.risk_score > 600", "next_step": "MediumRiskStep"}
    ]
    next_step_name_no_default = engine.evaluate_routes(routes_no_default)
    assert next_step_name_no_default is None


def test_next_step_http_workflow_step(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    mock_persistence = MockPersistence()
    mock_executor = MockExecutor()
    mock_observer = MockObserver()
    mock_builder = MockBuilder()
    mock_expression_evaluator_cls = MockExpressionEvaluator
    mock_template_engine_cls = MockTemplateEngine

    class HttpTestState(BaseModel):
        url: str = "http://example.com"
        method: str = "GET"
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        body: Optional[Dict[str, Any]] = None

    workflow_steps = [
        WorkflowStep(name="Step0", func=lambda state, context: {}),
        HttpWorkflowStep(
            name="MakeHttpRequest",
            http_config={
                "url": "{state.url}",
                "method": "{state.method}",
                "headers": "{state.headers}",
                "body": "{state.body}"
            },
            required_input=[],
            input_schema=None
        ),
        WorkflowStep(name="Step2", func=lambda state, context: {})
    ]
    initial_state = HttpTestState()

    engine = WorkflowEngine(
        workflow_id="http-test",
        workflow_type="HttpWorkflow",
        initial_state_model=initial_state,
        workflow_steps=workflow_steps,
        steps_config=[],
        state_model_path="tests.sdk.test_engine.HttpTestState",
        persistence_provider=mock_persistence,
        execution_provider=mock_executor,
        workflow_builder=mock_builder,
        expression_evaluator_cls=mock_expression_evaluator_cls,
        template_engine_cls=mock_template_engine_cls,
        workflow_observer=mock_observer
    )

    # Mock dispatch_async_task to simulate async execution
    mock_executor._mock_async_dispatch_result = {
        "_async_dispatch": True, "task_id": "mock_task_id"}
    monkeypatch.setattr(mock_executor, 'dispatch_async_task', lambda func_path, state_data, workflow_id, current_step_index,
                        data_region, _previous_step_result=None, http_config=None, **kwargs: {"_async_dispatch": True, "task_id": "mock_task_id"})

    # Move to the HttpWorkflowStep
    engine.current_step = 1
    assert engine.current_step_name == "MakeHttpRequest"

    # Execute the HttpWorkflowStep
    result, next_step_name = engine.next_step(user_input={})

    # Assert that the workflow status is PENDING_ASYNC
    assert engine.status == "PENDING_ASYNC"
    assert result == {"_async_dispatch": True, "task_id": "mock_task_id"}
    assert next_step_name is None

    # Assert that workflow status change was logged
    assert any(call['new_status'] ==
               "PENDING_ASYNC" for call in mock_observer.workflow_status_changed_calls)

    assert any(call['new_status'] ==
               "PENDING_ASYNC" for call in mock_observer.workflow_status_changed_calls)


def test_next_step_async_workflow_step(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    mock_persistence = MockPersistence()
    mock_executor = MockExecutor()
    mock_observer = MockObserver()
    mock_builder = MockBuilder()
    mock_expression_evaluator_cls = MockExpressionEvaluator
    mock_template_engine_cls = MockTemplateEngine

    class AsyncTestState(BaseModel):
        data: str = "some_data"

    workflow_steps = [
        WorkflowStep(name="Step0", func=lambda state, context: {}),
        AsyncWorkflowStep(
            name="RunAsyncTask",
            func_path="my_app.tasks.perform_async_job",
            required_input=[],
            input_schema=None
        ),
        WorkflowStep(name="Step2", func=lambda state, context: {})
    ]
    initial_state = AsyncTestState()

    engine = WorkflowEngine(
        workflow_id="async-test",
        workflow_type="AsyncWorkflow",
        initial_state_model=initial_state,
        workflow_steps=workflow_steps,
        steps_config=[],
        state_model_path="tests.sdk.test_engine.AsyncTestState",
        persistence_provider=mock_persistence,
        execution_provider=mock_executor,
        workflow_builder=mock_builder,
        expression_evaluator_cls=mock_expression_evaluator_cls,
        template_engine_cls=mock_template_engine_cls,
        workflow_observer=mock_observer
    )

    # Mock dispatch_async_task to simulate async execution
    mock_executor._mock_async_dispatch_result = {
        "_async_dispatch": True, "task_id": "mock_async_task_id"}
    monkeypatch.setattr(mock_executor, 'dispatch_async_task', lambda func_path, state_data, workflow_id, current_step_index,
                        data_region, _previous_step_result=None, **kwargs: {"_async_dispatch": True, "task_id": "mock_async_task_id"})

    # Move to the AsyncWorkflowStep
    engine.current_step = 1
    assert engine.current_step_name == "RunAsyncTask"

    # Execute the AsyncWorkflowStep
    result, next_step_name = engine.next_step(user_input={})

    # Assert that the workflow status is PENDING_ASYNC
    assert engine.status == "PENDING_ASYNC"
    assert result == {"_async_dispatch": True, "task_id": "mock_async_task_id"}
    assert next_step_name is None

    # Assert that workflow status change was logged
    assert any(call['new_status'] ==
               "PENDING_ASYNC" for call in mock_observer.workflow_status_changed_calls)

    assert any(call['new_status'] ==
               "PENDING_ASYNC" for call in mock_observer.workflow_status_changed_calls)


def test_next_step_fire_and_forget_workflow_step(monkeypatch):
    mock_persistence = MockPersistence()
    mock_executor = MockExecutor()
    mock_observer = MockObserver()
    mock_builder = MockBuilder()
    mock_expression_evaluator_cls = MockExpressionEvaluator
    # Will use real template engine for template rendering
    mock_template_engine_cls = MockTemplateEngine

    class ParentStateWithSpawned(BaseModel):
        user_id: str = "U123"
        spawned_workflows: Optional[List[Dict[str, Any]]] = None

    workflow_steps = [
        WorkflowStep(name="Step0", func=lambda state, context: {}),
        FireAndForgetWorkflowStep(
            name="SpawnNotificationWorkflow",
            target_workflow_type="NotificationWorkflow",
            initial_data_template={
                "target_user_id": "{state.user_id}", "message": "Welcome!"}
        ),
        WorkflowStep(name="Step2", func=lambda state, context: {})
    ]
    initial_state = ParentStateWithSpawned()

    # Create a mock for the spawned child workflow instance
    mock_spawned_child = WorkflowEngine(
        workflow_id="spawned-child-id",
        workflow_type="NotificationWorkflow",
        initial_state_model=DummyState(),  # Dummy state for child
        persistence_provider=mock_persistence,
        execution_provider=mock_executor,
        workflow_builder=mock_builder,
        expression_evaluator_cls=mock_expression_evaluator_cls,
        template_engine_cls=mock_template_engine_cls,
        workflow_observer=mock_observer
    )

    # Mock the builder's create_workflow to return our mock spawned child
    monkeypatch.setattr(mock_builder, 'create_workflow',
                        lambda workflow_type, initial_data, **kwargs: mock_spawned_child)

    # Mock dispatch_independent_workflow
    mock_dispatch_independent_workflow_calls = []
    monkeypatch.setattr(mock_executor, 'dispatch_independent_workflow',
                        lambda workflow_id: mock_dispatch_independent_workflow_calls.append(workflow_id))

    engine = WorkflowEngine(
        workflow_id="fire-and-forget-test",
        workflow_type="ParentWorkflow",
        initial_state_model=initial_state,
        workflow_steps=workflow_steps,
        steps_config=[],  # Not needed for this test as steps are direct objects
        state_model_path="tests.sdk.test_engine.ParentStateWithSpawned",
        persistence_provider=mock_persistence,
        execution_provider=mock_executor,
        workflow_builder=mock_builder,
        expression_evaluator_cls=mock_expression_evaluator_cls,
        # Use real Jinja2 for template rendering
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=mock_observer
    )

    # Move to the FireAndForgetWorkflowStep
    engine.current_step = 1
    assert engine.current_step_name == "SpawnNotificationWorkflow"

    # Execute the FireAndForgetWorkflowStep
    result, next_step_name = engine.next_step(user_input={})

    # Assert that the parent workflow status remains ACTIVE
    assert engine.status == "ACTIVE"
    # Assert that a message indicating spawned workflow is returned
    assert "spawned_workflow_id" in result
    assert result["spawned_workflow_id"] == "spawned-child-id"
    assert "Independent workflow NotificationWorkflow spawned." in result["message"]
    # Assert that parent continues to the next step
    assert next_step_name == "Step2"

    # Assert that create_workflow was called for the child
    assert mock_spawned_child.workflow_type == "NotificationWorkflow"
    # Default value from DummyState
    assert mock_spawned_child.state.value == "default_value"
    # Assert initial data was correctly templated and passed
    assert mock_spawned_child.metadata["spawned_by"] == "fire-and-forget-test"
    assert mock_spawned_child.metadata["spawn_reason"] == "SpawnNotificationWorkflow"

    # Assert that dispatch_independent_workflow was called
    assert len(mock_dispatch_independent_workflow_calls) == 1
    assert mock_dispatch_independent_workflow_calls[0] == "spawned-child-id"

    # Assert that parent state updated with spawned workflow info
    assert engine.state.spawned_workflows is not None
    assert len(engine.state.spawned_workflows) == 1
    assert engine.state.spawned_workflows[0]["workflow_id"] == "spawned-child-id"
    assert engine.state.spawned_workflows[0]["workflow_type"] == "NotificationWorkflow"
    assert engine.state.spawned_workflows[0]["spawned_by_step"] == "SpawnNotificationWorkflow"

    assert engine.state.spawned_workflows[0]["spawned_by_step"] == "SpawnNotificationWorkflow"


def test_next_step_loop_workflow_step(monkeypatch):
    mock_persistence = MockPersistence()
    mock_executor = MockExecutor()
    mock_observer = MockObserver()
    mock_builder = MockBuilder()
    mock_expression_evaluator_cls = MockExpressionEvaluator
    mock_template_engine_cls = MockTemplateEngine

    class LoopTestState(BaseModel):
        items: List[str] = ["item1", "item2"]
        processed_items: List[str] = []

    workflow_steps = [
        WorkflowStep(name="Step0", func=lambda state, context: {}),
        LoopStep(
            name="ProcessLoop",
            mode="ITERATE",
            iterate_over="state.items",
            item_var_name="current_item",
            loop_body=[]  # Empty for this test, as we only verify call to _execute_loop_step
        ),
        WorkflowStep(name="Step2", func=lambda state, context: {})
    ]
    initial_state = LoopTestState()

    engine = WorkflowEngine(
        workflow_id="loop-test",
        workflow_type="LoopWorkflow",
        initial_state_model=initial_state,
        workflow_steps=workflow_steps,
        steps_config=[],
        state_model_path="tests.sdk.test_engine.LoopTestState",
        persistence_provider=mock_persistence,
        execution_provider=mock_executor,
        workflow_builder=mock_builder,
        expression_evaluator_cls=mock_expression_evaluator_cls,
        template_engine_cls=mock_template_engine_cls,
        workflow_observer=mock_observer
    )

    # Mock _execute_loop_step to verify it's called
    mock_execute_loop_step_calls = []

    def mock_execute_loop_step(step_instance, state, context):
        mock_execute_loop_step_calls.append((step_instance, state, context))
        return {"loop_processed": True}

    monkeypatch.setattr(engine, '_execute_loop_step', mock_execute_loop_step)

    # Move to the LoopStep
    engine.current_step = 1
    assert engine.current_step_name == "ProcessLoop"

    # Execute the LoopStep
    result, next_step_name = engine.next_step(user_input={})

    # Assert that _execute_loop_step was called
    assert len(mock_execute_loop_step_calls) == 1
    assert mock_execute_loop_step_calls[0][0].name == "ProcessLoop"
    assert mock_execute_loop_step_calls[0][1] == engine.state

    # Assert result and next step
    assert result == {"loop_processed": True}
    assert next_step_name == "Step2"
    assert engine.status == "ACTIVE"
    assert engine.current_step == 2

    assert engine.current_step == 2


def test_jinja2_template_engine_render_functionality():
    context = {"user_id": "test_user", "report_type": "daily"}
    template_engine = Jinja2TemplateEngine(context=context)

    # Test simple variable rendering
    rendered_string = template_engine.render("Hello {{user_id}}!")
    assert rendered_string == "Hello test_user!"

    # Test multiple variables
    rendered_string = template_engine.render(
        "Report for {{user_id}} is {{report_type}}.")
    assert rendered_string == "Report for test_user is daily."

    # Test missing variable
    rendered_string = template_engine.render("Hello {{missing_var}}!")
    # Should keep unrendered if not found
    assert rendered_string == "Hello {{missing_var}}!"

    # Test with complex path (should not render if context is flat)
    rendered_string = template_engine.render("User: {{state.user_id}}")
    assert rendered_string == "User: {{state.user_id}}"

    # Test with template in a list/dict
    rendered_list = template_engine.render(
        ["Value is {{user_id}}", {"key": "{{report_type}}"}])
    assert rendered_list == ["Value is test_user", {"key": "daily"}]


def test_saga_compensation_on_single_step_failure():
    mock_persistence = MockPersistence()
    mock_executor = MockExecutor()
    mock_observer = MockObserver()
    mock_builder = MockBuilder()
    mock_expression_evaluator_cls = MockExpressionEvaluator
    mock_template_engine_cls = MockTemplateEngine

    # Define a compensatable step that succeeds
    def succeeding_func(state: SagaState, context: StepContext):
        state.step1_done = True
        return {"result": "step1 success"}

    succeeding_step = MockCompensatableStep(
        name="SucceedingCompensatableStep",
        func=succeeding_func,
        compensate_func=mock_compensate_func
    )

    # Define a compensatable step that will fail
    def failing_func(state: SagaState, context: StepContext):
        raise ValueError("Step failed unexpectedly!")

    failing_step = MockCompensatableStep(
        name="FailingCompensatableStep",
        func=failing_func,
        compensate_func=mock_compensate_func
    )

    workflow_steps = [
        succeeding_step,  # This step will succeed
        failing_step,    # This step will fail
        # This step should not be reached
        WorkflowStep(name="NextStep", func=lambda state, context: {})
    ]

    initial_state = SagaState()

    engine = WorkflowEngine(
        workflow_id="saga-single-fail-test",
        workflow_type="SagaWorkflow",
        initial_state_model=initial_state,
        workflow_steps=workflow_steps,
        steps_config=[
            {"name": "SucceedingCompensatableStep",
                "compensate_function": "some.func"},
            {"name": "FailingCompensatableStep",
                "compensate_function": "some.func"}
        ],  # Needed for builder
        state_model_path="tests.sdk.test_engine.SagaState",
        persistence_provider=mock_persistence,
        execution_provider=mock_executor,
        workflow_builder=mock_builder,
        expression_evaluator_cls=mock_expression_evaluator_cls,
        template_engine_cls=mock_template_engine_cls,
        workflow_observer=mock_observer
    )
    engine.enable_saga_mode()  # Enable saga mode after initialization

    # First, run the succeeding step
    result_succeeding, next_step_name = engine.next_step(user_input={})
    assert result_succeeding == {"result": "step1 success"}
    assert engine.state.step1_done == True
    assert engine.completed_steps_stack[0]["step_name"] == "SucceedingCompensatableStep"
    assert engine.current_step == 1  # Move to the next step

    # Make the executor raise an exception when executing "FailingCompensatableStep"
    mock_executor.set_mock_sync_step_exception(
        failing_step.name, ValueError("Step failed unexpectedly!"))

    # Execute the failing step
    with pytest.raises(SagaWorkflowException) as excinfo:
        engine.next_step(user_input={})

    assert "Saga failed at FailingCompensatableStep: Step failed unexpectedly!" in str(
        excinfo.value)

    # Assert that compensation was called for the succeeding step
    # Only succeeding step is compensated
    assert succeeding_step.compensated_count == 1
    assert engine.state.compensation_called == 1

    # Assert that workflow status is FAILED_ROLLED_BACK
    assert engine.status == "FAILED_ROLLED_BACK"

    # Assert on_workflow_rolled_back was called
    assert len(mock_observer.workflow_rolled_back_calls) == 1
    assert mock_observer.workflow_rolled_back_calls[0]["workflow_id"] == "saga-single-fail-test"
    assert mock_observer.workflow_rolled_back_calls[0]["reason"].startswith(
        "Saga rollback completed")

    # Assert compensation was logged in persistence
    assert len(mock_persistence.compensation_logs) == 1
    assert mock_persistence.compensation_logs[0]["step_name"] == succeeding_step.name
    assert mock_persistence.compensation_logs[0]["action_type"] == "COMPENSATE"
    assert "compensated" in mock_persistence.compensation_logs[0]["action_result"]


def test_saga_compensation_on_later_step_failure():
    mock_persistence = MockPersistence()
    mock_executor = MockExecutor()
    mock_observer = MockObserver()
    mock_builder = MockBuilder()
    mock_expression_evaluator_cls = MockExpressionEvaluator
    mock_template_engine_cls = MockTemplateEngine

    # Define a first compensatable step that succeeds
    def first_succeeding_func(state: SagaState, context: StepContext):
        state.step1_done = True
        return {"result": "step1 success"}

    first_succeeding_step = MockCompensatableStep(
        name="FirstSucceedingCompensatableStep",
        func=first_succeeding_func,
        compensate_func=mock_compensate_func
    )

    # Define a second compensatable step that also succeeds initially
    def second_succeeding_func(state: SagaState, context: StepContext):
        state.step2_done = True
        return {"result": "step2 success"}

    second_succeeding_step = MockCompensatableStep(
        name="SecondSucceedingCompensatableStep",
        func=second_succeeding_func,
        compensate_func=mock_compensate_func
    )

    # Define a third step that will fail, triggering rollback
    def failing_func(state: SagaState, context: StepContext):
        raise ValueError("Third step failed unexpectedly!")

    failing_step = WorkflowStep(  # This can be a regular step or compensatable, doesn't matter for this test
        name="ThirdFailingStep",
        func=failing_func
    )

    workflow_steps = [
        first_succeeding_step,
        second_succeeding_step,
        failing_step,
        # This step should not be reached
        WorkflowStep(name="NextStep", func=lambda state, context: {})
    ]

    initial_state = SagaState()

    engine = WorkflowEngine(
        workflow_id="saga-later-fail-test",
        workflow_type="SagaWorkflow",
        initial_state_model=initial_state,
        workflow_steps=workflow_steps,
        steps_config=[
            {"name": "FirstSucceedingCompensatableStep",
                "compensate_function": "some.func"},
            {"name": "SecondSucceedingCompensatableStep",
                "compensate_function": "some.func"},
            {"name": "ThirdFailingStep"}
        ],
        state_model_path="tests.sdk.test_engine.SagaState",
        persistence_provider=mock_persistence,
        execution_provider=mock_executor,
        workflow_builder=mock_builder,
        expression_evaluator_cls=mock_expression_evaluator_cls,
        template_engine_cls=mock_template_engine_cls,
        workflow_observer=mock_observer
    )
    engine.enable_saga_mode()

    # Run the first succeeding step
    result1, _ = engine.next_step(user_input={})
    assert result1 == {"result": "step1 success"}
    assert engine.state.step1_done == True
    assert engine.current_step == 1
    assert len(engine.completed_steps_stack) == 1
    assert engine.completed_steps_stack[0]["step_name"] == "FirstSucceedingCompensatableStep"

    # Run the second succeeding step
    result2, _ = engine.next_step(user_input={})
    assert result2 == {"result": "step2 success"}
    assert engine.state.step2_done == True
    assert engine.current_step == 2
    assert len(engine.completed_steps_stack) == 2
    assert engine.completed_steps_stack[1]["step_name"] == "SecondSucceedingCompensatableStep"

    # Make the executor raise an exception when executing the third (failing) step
    mock_executor.set_mock_sync_step_exception(
        failing_step.name, ValueError("Third step failed unexpectedly!"))

    # Execute the failing step, which should trigger rollback
    with pytest.raises(SagaWorkflowException) as excinfo:
        engine.next_step(user_input={})

    assert "Saga failed at ThirdFailingStep: Third step failed unexpectedly!" in str(
        excinfo.value)

    # Assert that compensation was called for both preceding compensatable steps
    assert first_succeeding_step.compensated_count == 1
    assert second_succeeding_step.compensated_count == 1
    assert engine.state.compensation_called == 2  # Total compensation calls

    # Assert that workflow status is FAILED_ROLLED_BACK
    assert engine.status == "FAILED_ROLLED_BACK"

    # Assert on_workflow_rolled_back was called
    assert len(mock_observer.workflow_rolled_back_calls) == 1
    assert mock_observer.workflow_rolled_back_calls[0]["workflow_id"] == "saga-later-fail-test"
    assert mock_observer.workflow_rolled_back_calls[0]["reason"].startswith(
        "Saga rollback completed")

    # Assert compensation was logged for both steps in reverse order
    assert len(mock_persistence.compensation_logs) == 2
    # Last completed, first compensated
    assert mock_persistence.compensation_logs[0]["step_name"] == second_succeeding_step.name
    assert mock_persistence.compensation_logs[1]["step_name"] == first_succeeding_step.name


# Function that will fail when called as a compensation
def failing_compensate_func(state: SagaState, context: StepContext):
    raise ValueError("Compensation failed!")


def test_saga_compensation_failure_on_compensation_function():
    mock_persistence = MockPersistence()
    mock_executor = MockExecutor()
    mock_observer = MockObserver()
    mock_builder = MockBuilder()
    mock_expression_evaluator_cls = MockExpressionEvaluator
    mock_template_engine_cls = MockTemplateEngine

    # Define a succeeding compensatable step with a normal compensation
    def first_succeeding_func(state: SagaState, context: StepContext):
        state.step1_done = True
        return {"result": "step1 success"}

    first_succeeding_step = MockCompensatableStep(
        name="FirstSucceedingCompensatableStep",
        func=first_succeeding_func,
        compensate_func=mock_compensate_func  # This one succeeds compensation
    )

    # Define a second compensatable step with a FAILING compensation function
    def second_succeeding_func_with_failing_compensate(state: SagaState, context: StepContext):
        state.step2_done = True
        return {"result": "step2 success with failing compensate"}

    second_succeeding_step_failing_compensate = MockCompensatableStep(
        name="SecondSucceedingFailingCompensateStep",
        func=second_succeeding_func_with_failing_compensate,
        compensate_func=failing_compensate_func  # This one FAILS compensation
    )

    # Define a third step that will fail, triggering rollback
    def failing_func(state: SagaState, context: StepContext):
        raise ValueError("Third step failed, triggering compensation!")

    failing_step_to_trigger_rollback = WorkflowStep(
        name="ThirdFailingStepToTriggerRollback",
        func=failing_func
    )

    workflow_steps = [
        first_succeeding_step,
        second_succeeding_step_failing_compensate,
        failing_step_to_trigger_rollback,
        # This step should not be reached
        WorkflowStep(name="NextStep", func=lambda state, context: {})
    ]

    initial_state = SagaState()

    engine = WorkflowEngine(
        workflow_id="saga-compensation-fail-test",
        workflow_type="SagaWorkflow",
        initial_state_model=initial_state,
        workflow_steps=workflow_steps,
        steps_config=[
            {"name": "FirstSucceedingCompensatableStep",
                "compensate_function": "some.func"},
            {"name": "SecondSucceedingFailingCompensateStep",
                "compensate_function": "some.func"},
            {"name": "ThirdFailingStepToTriggerRollback"}
        ],
        state_model_path="tests.sdk.test_engine.SagaState",
        persistence_provider=mock_persistence,
        execution_provider=mock_executor,
        workflow_builder=mock_builder,
        expression_evaluator_cls=mock_expression_evaluator_cls,
        template_engine_cls=mock_template_engine_cls,
        workflow_observer=mock_observer
    )
    engine.enable_saga_mode()

    # Run the first succeeding step
    engine.next_step(user_input={})
    assert engine.state.step1_done == True
    assert engine.current_step == 1

    # Run the second succeeding step (with failing compensate func)
    engine.next_step(user_input={})
    assert engine.state.step2_done == True
    assert engine.current_step == 2
    assert len(engine.completed_steps_stack) == 2

    # Make the executor raise an exception when executing the third step
    mock_executor.set_mock_sync_step_exception(
        failing_step_to_trigger_rollback.name, ValueError("Third step failed!"))

    # Execute the failing step, which should trigger rollback and compensation failure
    with pytest.raises(SagaWorkflowException) as excinfo:
        engine.next_step(user_input={})

    assert "Saga failed at ThirdFailingStepToTriggerRollback: Third step failed!" in str(
        excinfo.value)

    # Assert that compensation was attempted for both preceding compensatable steps
    # This compensation should succeed
    assert first_succeeding_step.compensated_count == 1
    # This compensation should be *attempted* and fail internally
    assert second_succeeding_step_failing_compensate.compensated_count == 1

    # The mock_compensate_func was called once by first_succeeding_step
    # Only the successful compensation increments this
    assert engine.state.compensation_called == 1

    # Assert that workflow status is FAILED_ROLLED_BACK
    assert engine.status == "FAILED_ROLLED_BACK"

    # Assert on_workflow_rolled_back was called
    assert len(mock_observer.workflow_rolled_back_calls) == 1
    assert mock_observer.workflow_rolled_back_calls[0]["workflow_id"] == "saga-compensation-fail-test"
    assert "Saga rollback completed" in mock_observer.workflow_rolled_back_calls[
        0]["reason"]

    # Assert compensation was logged in persistence, including the failure
    assert len(mock_persistence.compensation_logs) == 2
    # The failing compensation is logged first (reverse order)
    assert mock_persistence.compensation_logs[0]["step_name"] == second_succeeding_step_failing_compensate.name
    assert mock_persistence.compensation_logs[0]["action_type"] == "COMPENSATE_FAILED"
    assert "Compensation failed!" in mock_persistence.compensation_logs[0]["error_message"]
    # The successful compensation is logged second
    assert mock_persistence.compensation_logs[1]["step_name"] == first_succeeding_step.name
    assert mock_persistence.compensation_logs[1]["action_type"] == "COMPENSATE"


# --- Sub-workflow Parent Status Tests ---

class ChildWorkflowState(BaseModel):
    message: str = "Initial Child Message"
    counter: int = 0
    final_result_data: Optional[Dict[str, Any]] = None


class ParentWorkflowState(BaseModel):
    child_status: Optional[str] = None
    child_id: Optional[str] = None
    child_current_step: Optional[str] = None
    sub_workflow_results: Dict[str, Any] = {}

# Child workflow step functions


def mock_child_failing_step_func(state: ChildWorkflowState, context: StepContext):
    raise ValueError("Child workflow intentional failure!")


def mock_child_pausing_step_func(state: ChildWorkflowState, context: StepContext):
    state.counter += 1
    raise WorkflowPauseDirective(
        result={"reason": "Human input needed for child"})


def mock_child_succeeding_step_func(state: ChildWorkflowState, context: StepContext):
    state.counter += 1
    state.message = "Child completed successfully!"
    return {"child_step_output": "success"}


def mock_child_final_result_step_func(state: ChildWorkflowState, context: StepContext):
    state.final_result_data = {"key": "value"}
    return state.final_result_data

# Parent workflow step function to launch child


def mock_parent_launch_child_step_func(state: ParentWorkflowState, context: StepContext, child_workflow_type: str):
    raise StartSubWorkflowDirective(
        workflow_type=child_workflow_type,
        initial_data={"message": "Data from parent"}
    )


@pytest.fixture
def common_providers():
    return {
        "persistence_provider": MockPersistence(),
        "execution_provider": MockExecutor(),
        "workflow_builder": MockBuilder(),
        "expression_evaluator_cls": SimpleExpressionEvaluator,
        "template_engine_cls": Jinja2TemplateEngine,
        "workflow_observer": MockObserver()
    }


def create_mock_child_workflow_engine(workflow_id: str, workflow_type: str, step_func: Callable, providers: dict):
    child_engine = WorkflowEngine(
        workflow_id=workflow_id,
        workflow_type=workflow_type,
        initial_state_model=ChildWorkflowState(),
        workflow_steps=[WorkflowStep(name="ChildStep", func=step_func)],
        steps_config=[{"name": "ChildStep", "type": "STANDARD"}],
        state_model_path="tests.sdk.test_engine.ChildWorkflowState",
        **providers
    )
    child_engine.parent_execution_id = "parent-123"  # Set after initialization
    return child_engine


def test_parent_workflow_receives_child_failure_status(common_providers, monkeypatch):
    parent_id = "parent-failure-test"
    child_id = "child-failure-test"

    # Mock the builder's create_workflow to return our specific child workflow
    def mock_builder_create_workflow(workflow_type: str, initial_data: Dict[str, Any], **kwargs):
        if workflow_type == "FailingChildWorkflow":
            return create_mock_child_workflow_engine(child_id, workflow_type, mock_child_failing_step_func, kwargs)
        raise ValueError("Unexpected workflow type")

    monkeypatch.setattr(
        common_providers["workflow_builder"], 'create_workflow', mock_builder_create_workflow)
    common_providers["execution_provider"].mock_step_function(
        "ChildStep", mock_child_failing_step_func)

    parent_engine = WorkflowEngine(
        workflow_id=parent_id,
        workflow_type="ParentWorkflow",
        initial_state_model=ParentWorkflowState(),
        workflow_steps=[WorkflowStep(name="LaunchChild", func=lambda state, context: mock_parent_launch_child_step_func(
            state, context, "FailingChildWorkflow"))],
        steps_config=[{"name": "LaunchChild", "type": "STANDARD"}],
        state_model_path="tests.sdk.test_engine.ParentWorkflowState",
        **common_providers
    )

    # 1. Launch child workflow from parent
    parent_engine.next_step(user_input={})

    # At this point, the parent's executor will dispatch the sub-workflow, but not report child status *from the child* yet.
    # The child's engine is created and its initial status is PENDING_SUB_WORKFLOW.
    # The MockExecutor of the child (which is common_providers["execution_provider"]) would have received a PENDING_SUB_WORKFLOW status for the child itself.
    # No status reported from child yet
    assert len(
        common_providers["execution_provider"].reported_child_statuses) == 0

    # Simulate the child workflow being executed and failing
    child_engine = common_providers["persistence_provider"].load_workflow(
        child_id)  # Load child to simulate execution
    assert child_engine is not None
    child_engine = WorkflowEngine.from_dict(child_engine, **common_providers)
    child_engine.parent_execution_id = parent_id  # Ensure child knows its parent

    try:
        child_engine.next_step(user_input={})
        pytest.fail("WorkflowFailedException was not raised")
    except WorkflowFailedException as e:
        assert "Child workflow intentional failure!" in str(
            e.original_exception)
        # Check that the child engine's status was correctly set to FAILED before the exception was raised
        assert child_engine.status == "FAILED"

    # After the exception, the status should be FAILED
    # Final assertion that status remains FAILED
    assert child_engine.status == "FAILED"

    # After child fails, it reports status to parent via _notify_status_change, which calls report_child_status_to_parent
    # The MockExecutor captures this report. Now there should be 1 report.
    assert len(
        common_providers["execution_provider"].reported_child_statuses) == 1
    failure_report = common_providers["execution_provider"].reported_child_statuses[0]
    assert failure_report["child_id"] == child_id
    assert failure_report["child_new_status"] == "FAILED"
    # Simulate parent loading the workflow and processing the reported status (this happens via Celery task in real setup)
    # For sync test, we directly update parent status as if it received the report
    parent_engine.status = "FAILED_CHILD_WORKFLOW"
    parent_engine.metadata["failed_child_id"] = child_id
    parent_engine.metadata["failed_child_status"] = "FAILED"
    parent_engine.blocked_on_child_id = None  # Child is no longer blocking

    assert parent_engine.status == "FAILED_CHILD_WORKFLOW"
    assert parent_engine.metadata["failed_child_id"] == child_id


def test_parent_workflow_receives_child_pause_status(common_providers, monkeypatch):
    parent_id = "parent-pause-test"
    child_id = "child-pause-test"

    # Mock the builder's create_workflow to return our specific child workflow
    def mock_builder_create_workflow(workflow_type: str, initial_data: Dict[str, Any], **kwargs):
        if workflow_type == "PausingChildWorkflow":
            return create_mock_child_workflow_engine(child_id, workflow_type, mock_child_pausing_step_func, kwargs)
        raise ValueError("Unexpected workflow type")

    monkeypatch.setattr(
        common_providers["workflow_builder"], 'create_workflow', mock_builder_create_workflow)
    common_providers["execution_provider"].mock_step_function(
        "ChildStep", mock_child_pausing_step_func)

    parent_engine = WorkflowEngine(
        workflow_id=parent_id,
        workflow_type="ParentWorkflow",
        initial_state_model=ParentWorkflowState(),
        workflow_steps=[WorkflowStep(name="LaunchChild", func=lambda state, context: mock_parent_launch_child_step_func(
            state, context, "PausingChildWorkflow"))],
        steps_config=[{"name": "LaunchChild", "type": "STANDARD"}],
        state_model_path="tests.sdk.test_engine.ParentWorkflowState",
        **common_providers
    )

    # 1. Launch child workflow from parent
    parent_engine.next_step(user_input={})

    # Assert initial dispatch
    # No status reported from child yet
    assert len(
        common_providers["execution_provider"].reported_child_statuses) == 0

    # Simulate the child workflow being executed and pausing
    child_engine = common_providers["persistence_provider"].load_workflow(
        child_id)
    assert child_engine is not None
    child_engine = WorkflowEngine.from_dict(child_engine, **common_providers)
    child_engine.parent_execution_id = parent_id  # Ensure child knows its parent

    try:
        result, next_step_child = child_engine.next_step(user_input={})
        pytest.fail("WorkflowPauseDirective was not raised")
    except WorkflowPauseDirective as e:
        result = e.result
        # Pause directive returns current step name
        next_step_child = child_engine.current_step_name

    assert child_engine.status == "WAITING_HUMAN"
    assert result == {"reason": "Human input needed for child"}
    # Pause directive returns current step name
    assert next_step_child == "ChildStep"

    # After child pauses, it reports status to parent
    assert len(
        common_providers["execution_provider"].reported_child_statuses) == 1
    pause_report = common_providers["execution_provider"].reported_child_statuses[0]
    assert pause_report["child_id"] == child_id
    assert pause_report["child_new_status"] == "WAITING_HUMAN"
    assert pause_report["child_current_step_name"] == "ChildStep"

    # Simulate parent loading the workflow and processing the reported status
    parent_engine.status = "WAITING_CHILD_HUMAN_INPUT"
    parent_engine.metadata["waiting_child_id"] = child_id
    parent_engine.metadata["waiting_child_step"] = "ChildStep"

    assert parent_engine.status == "WAITING_CHILD_HUMAN_INPUT"
    assert parent_engine.metadata["waiting_child_id"] == child_id
    assert parent_engine.metadata["waiting_child_step"] == "ChildStep"


def test_parent_workflow_receives_child_completion_status_and_merges_result(common_providers, monkeypatch):
    parent_id = "parent-completion-test"
    child_id = "child-completion-test"
    child_workflow_type = "SucceedingChildWorkflow"

    def mock_builder_create_workflow(workflow_type: str, initial_data: Dict[str, Any], **kwargs):
        if workflow_type == child_workflow_type:
            return create_mock_child_workflow_engine(child_id, workflow_type, mock_child_succeeding_step_func, kwargs)
        raise ValueError("Unexpected workflow type")

    monkeypatch.setattr(
        common_providers["workflow_builder"], 'create_workflow', mock_builder_create_workflow)
    common_providers["execution_provider"].mock_step_function(
        "ChildStep", mock_child_succeeding_step_func)

    parent_engine = WorkflowEngine(
        workflow_id=parent_id,
        workflow_type="ParentWorkflow",
        initial_state_model=ParentWorkflowState(),
        workflow_steps=[WorkflowStep(name="LaunchChild", func=lambda state, context: mock_parent_launch_child_step_func(
            state, context, child_workflow_type))],
        steps_config=[{"name": "LaunchChild", "type": "STANDARD"}],
        state_model_path="tests.sdk.test_engine.ParentWorkflowState",
        **common_providers
    )

    # 1. Launch child workflow from parent
    parent_engine.next_step(user_input={})

    # Assert initial dispatch
    # No status reported from child yet
    assert len(
        common_providers["execution_provider"].reported_child_statuses) == 0

    # Simulate the child workflow being executed and completing
    child_engine = common_providers["persistence_provider"].load_workflow(
        child_id)
    assert child_engine is not None
    child_engine = WorkflowEngine.from_dict(child_engine, **common_providers)
    child_engine.parent_execution_id = parent_id  # Ensure child knows its parent

    result_child, next_step_child = child_engine.next_step(user_input={})

    assert child_engine.status == "COMPLETED"
    assert result_child == {"child_step_output": "success"}

    # After child completes, it reports status to parent
    assert len(
        common_providers["execution_provider"].reported_child_statuses) == 1
    completion_report = common_providers["execution_provider"].reported_child_statuses[0]
    assert completion_report["child_id"] == child_id
    assert completion_report["child_new_status"] == "COMPLETED"
    # Simulate the parent processing the completion report
    assert completion_report["child_result"] == result_child
    # In a real system, this would happen via the Celery task that resumes the parent.
    # For this sync test, we directly simulate the update and resumption.

    # The actual resumption logic would be in execution_provider.report_child_status_to_parent
    # which would eventually call a method on the parent engine to unblock and resume.
    # For now, we manually set parent's state as if it resumed and merged.

    # Parent state should now be updated to include child's result
    parent_engine.state.sub_workflow_results[child_id] = {
        "workflow_type": child_workflow_type,
        "status": "COMPLETED",
        "state": child_engine.state.model_dump(),
        "final_result": result_child
    }
    parent_engine.blocked_on_child_id = None
    parent_engine.status = "ACTIVE"  # Parent resumes to ACTIVE, ready for next step

    assert parent_engine.status == "ACTIVE"
    assert parent_engine.blocked_on_child_id is None
    assert child_id in parent_engine.state.sub_workflow_results
    assert parent_engine.state.sub_workflow_results[child_id]["status"] == "COMPLETED"
    assert parent_engine.state.sub_workflow_results[child_id]["final_result"] == {
        "child_step_output": "success"}
    assert parent_engine.state.sub_workflow_results[child_id][
        "state"]["message"] == "Child completed successfully!"

    assert parent_engine.state.sub_workflow_results[child_id][
        "state"]["message"] == "Child completed successfully!"


def test_handle_sub_workflow_creation_error(common_providers, monkeypatch):
    parent_id = "parent-sub-create-error-test"

    # Mock the builder's create_workflow to raise an exception
    def mock_builder_create_workflow_fails(workflow_type: str, initial_data: Dict[str, Any], **kwargs):
        raise ValueError("Simulated child workflow creation error!")

    monkeypatch.setattr(common_providers["workflow_builder"],
                        'create_workflow', mock_builder_create_workflow_fails)

    parent_engine = WorkflowEngine(
        workflow_id=parent_id,
        workflow_type="ParentWorkflow",
        initial_state_model=ParentWorkflowState(),
        workflow_steps=[WorkflowStep(name="LaunchChild", func=lambda state, context: mock_parent_launch_child_step_func(
            state, context, "AnyChildWorkflowType"))],
        steps_config=[{"name": "LaunchChild", "type": "STANDARD"}],
        state_model_path="tests.sdk.test_engine.ParentWorkflowState",
        **common_providers
    )

    with pytest.raises(ValueError, match="Simulated child workflow creation error!"):
        parent_engine.next_step(user_input={})

    # Assert that parent status remains ACTIVE (no PENDING_SUB_WORKFLOW was set)
    assert parent_engine.status == "ACTIVE"
    assert parent_engine.blocked_on_child_id is None
    # No child status should have been reported
    assert len(
        common_providers["execution_provider"].reported_child_statuses) == 0

    assert len(
        common_providers["execution_provider"].reported_child_statuses) == 0


def test_next_step_input_validation_error(common_providers):
    class StepInput(BaseModel):
        age: int = Field(..., gt=18)  # Age must be greater than 18

    # Define a step that requires StepInput
    test_step = WorkflowStep(
        name="ValidateAgeStep",
        func=lambda state, context: {
            "processed_age": context.validated_input.age},
        input_schema=StepInput  # Directly pass the Pydantic model class
    )

    engine = WorkflowEngine(
        workflow_id="validation-error-test",
        workflow_type="ValidationWorkflow",
        initial_state_model=DummyState(),
        workflow_steps=[test_step],
        steps_config=[{"name": "ValidateAgeStep", "type": "STANDARD"}],
        state_model_path="tests.sdk.test_engine.DummyState",
        **common_providers
    )

    # Attempt to call next_step with invalid input (age <= 18)
    with pytest.raises(ValueError, match="Invalid input for step 'ValidateAgeStep':"):
        engine.next_step(user_input={"age": 18})  # This should fail validation

    # Attempt to call next_step with valid input
    result, next_step_name = engine.next_step(user_input={"age": 20})
    assert engine.status == "COMPLETED"
    assert result == {"processed_age": 20}
    assert next_step_name is None

    assert next_step_name is None


def test_process_dynamic_injection_condition_met(common_providers, monkeypatch):
    class DynamicInjectionState(BaseModel):
        inject_control: str = "default"

    mock_builder = common_providers["workflow_builder"]

    initial_steps_config = [
        {"name": "StepA", "type": "STANDARD"},
        {
            "name": "StepB",
            "type": "STANDARD",
            "dynamic_injection": {
                "rules": [
                    {
                        "condition_key": "inject_control",
                        "value_match": "inject_me",  # Condition met
                        "action": "INSERT_AFTER_CURRENT",
                        "steps_to_insert": [
                            {"name": "InjectedStep1", "type": "STANDARD"}
                        ]
                    }
                ]
            }
        },
        {"name": "StepC", "type": "STANDARD"}
    ]

    initial_workflow_steps = mock_builder.build_steps_from_config(
        initial_steps_config)

    engine = WorkflowEngine(
        workflow_id="dynamic-inject-test-met",
        workflow_type="DynamicWorkflow",
        initial_state_model=DynamicInjectionState(inject_control="inject_me"),
        workflow_steps=initial_workflow_steps,
        steps_config=initial_steps_config,
        state_model_path="tests.sdk.test_engine.DynamicInjectionState",
        **common_providers
    )

    assert len(engine.workflow_steps) == 3
    engine.current_step = 1  # Point to StepB

    injection_occurred = engine._process_dynamic_injection()

    assert injection_occurred is True
    assert len(engine.workflow_steps) == 4
    assert engine.workflow_steps[2].name == "InjectedStep1"
    assert engine.workflow_steps[3].name == "StepC"


def test_process_dynamic_injection_condition_not_met(common_providers, monkeypatch):
    class DynamicInjectionState(BaseModel):
        inject_control: str = "default"

    mock_builder = common_providers["workflow_builder"]

    initial_steps_config = [
        {"name": "StepA", "type": "STANDARD"},
        {
            "name": "StepB",
            "type": "STANDARD",
            "dynamic_injection": {
                "rules": [
                    {
                        "condition_key": "inject_control",
                        "value_match": "donot_inject",  # Condition NOT met
                        "action": "INSERT_AFTER_CURRENT",
                        "steps_to_insert": [
                            {"name": "InjectedStep1", "type": "STANDARD"}
                        ]
                    }
                ]
            }
        },
        {"name": "StepC", "type": "STANDARD"}
    ]

    initial_workflow_steps = mock_builder.build_steps_from_config(
        initial_steps_config)

    engine = WorkflowEngine(
        workflow_id="dynamic-inject-test-not-met",
        workflow_type="DynamicWorkflow",
        initial_state_model=DynamicInjectionState(
            inject_control="trigger_injection"),  # State will not match "donot_inject"
        workflow_steps=initial_workflow_steps,
        steps_config=initial_steps_config,
        state_model_path="tests.sdk.test_engine.DynamicInjectionState",
        **common_providers
    )

    assert len(engine.workflow_steps) == 3
    engine.current_step = 1  # Point to StepB

    injection_occurred = engine._process_dynamic_injection()

    assert injection_occurred is False
    # Should remain original number of steps
    assert len(engine.workflow_steps) == 3


def test_process_dynamic_injection_value_is_not_condition(common_providers, monkeypatch):
    class DynamicInjectionState(BaseModel):
        inject_control: str = "default"

    mock_builder = common_providers["workflow_builder"]

    initial_steps_config = [
        {"name": "StepA", "type": "STANDARD"},
        {
            "name": "StepB",
            "type": "STANDARD",
            "dynamic_injection": {
                "rules": [
                    {
                        "condition_key": "inject_control",
                        "value_is_not": ["donot_inject", "another_excluded_value"],
                        "action": "INSERT_AFTER_CURRENT",
                        "steps_to_insert": [
                            {"name": "InjectedStepNot", "type": "STANDARD"}
                        ]
                    }
                ]
            }
        },
        {"name": "StepC", "type": "STANDARD"}
    ]

    initial_workflow_steps = mock_builder.build_steps_from_config(
        initial_steps_config)

    # Test case where condition is NOT met (value IS in excluded_values)
    engine_no_inject = WorkflowEngine(
        workflow_id="dynamic-value-is-not-test-no-inject",
        workflow_type="DynamicWorkflow",
        initial_state_model=DynamicInjectionState(
            inject_control="donot_inject"),  # Condition NOT met
        workflow_steps=initial_workflow_steps[:],  # Use a copy for fresh steps
        steps_config=initial_steps_config,
        state_model_path="tests.sdk.test_engine.DynamicInjectionState",
        **common_providers
    )

    # Original number of steps
    assert len(engine_no_inject.workflow_steps) == 3
    engine_no_inject.current_step = 1  # Point to StepB

    injection_occurred_2 = engine_no_inject._process_dynamic_injection()
    assert injection_occurred_2 is False
    # Should remain original number of steps
    assert len(engine_no_inject.workflow_steps) == 3

    # Test case where condition IS met (value is NOT in excluded_values)
    engine_inject = WorkflowEngine(
        workflow_id="dynamic-value-is-not-test-inject",
        workflow_type="DynamicWorkflow",
        initial_state_model=DynamicInjectionState(
            inject_control="trigger_injection"),  # Condition IS met
        workflow_steps=initial_workflow_steps[:],  # Use a copy for fresh steps
        steps_config=initial_steps_config,
        state_model_path="tests.sdk.test_engine.DynamicInjectionState",
        **common_providers
    )

    assert len(engine_inject.workflow_steps) == 3  # Original number of steps
    engine_inject.current_step = 1  # Point to StepB

    injection_occurred_3 = engine_inject._process_dynamic_injection()
    assert injection_occurred_3 is True
    assert len(engine_inject.workflow_steps) == 4
    assert engine_inject.workflow_steps[2].name == "InjectedStepNot"
    assert engine_inject.workflow_steps[3].name == "StepC"


def test_workflow_engine_init_parameter_defaults(common_providers):
    # This test focuses on the default values when optional parameters are NOT provided
    mock_persistence = common_providers["persistence_provider"]
    mock_executor = common_providers["execution_provider"]
    mock_builder = common_providers["workflow_builder"]
    mock_expression_evaluator_cls = common_providers["expression_evaluator_cls"]
    mock_template_engine_cls = common_providers["template_engine_cls"]
    mock_observer = common_providers["workflow_observer"]

    # Only provide required parameters
    engine = WorkflowEngine(
        persistence_provider=mock_persistence,
        execution_provider=mock_executor,
        workflow_builder=mock_builder,
        expression_evaluator_cls=mock_expression_evaluator_cls,
        template_engine_cls=mock_template_engine_cls,
        workflow_observer=mock_observer
    )

    assert engine.id is not None
    assert isinstance(engine.id, str)
    assert len(engine.id) > 0  # Should be a UUID string
    assert engine.workflow_steps == []
    assert engine.current_step == 0
    assert engine.state is None  # No initial_state_model provided
    assert engine.status == "ACTIVE"
    assert engine.workflow_type is None
    assert engine.steps_config == []
    assert engine.state_model_path is None
    assert engine.owner_id is None
    assert engine.org_id is None
    assert engine.saga_mode == False
    assert engine.completed_steps_stack == []
    assert engine.parent_execution_id is None
    assert engine.blocked_on_child_id is None
    assert engine.data_region is None
    assert engine.priority == 5
    assert engine.idempotency_key is None
    assert engine.metadata == {}


def test_workflow_engine_init_sub_workflow_defaults():
    mock_persistence = MockPersistence()
    mock_executor = MockExecutor()
    mock_observer = MockObserver()
    mock_builder = MockBuilder()
    mock_expression_evaluator_cls = MockExpressionEvaluator
    mock_template_engine_cls = MockTemplateEngine

    engine = WorkflowEngine(
        workflow_id="test-defaults",
        workflow_type="DefaultWorkflow",
        initial_state_model=DummyState(),
        persistence_provider=mock_persistence,
        execution_provider=mock_executor,
        workflow_builder=mock_builder,
        expression_evaluator_cls=mock_expression_evaluator_cls,
        template_engine_cls=mock_template_engine_cls,
        workflow_observer=mock_observer
    )

    assert engine.parent_execution_id is None
    assert engine.blocked_on_child_id is None


def test_workflow_engine_init_with_empty_lists():
    mock_persistence = MockPersistence()
    mock_executor = MockExecutor()
    mock_observer = MockObserver()
    mock_builder = MockBuilder()
    mock_expression_evaluator_cls = MockExpressionEvaluator
    mock_template_engine_cls = MockTemplateEngine

    engine = WorkflowEngine(
        workflow_id="test-empty-lists",
        workflow_type="EmptyListWorkflow",
        initial_state_model=DummyState(),
        workflow_steps=[],  # Explicitly pass empty list
        steps_config=[],    # Explicitly pass empty list
        persistence_provider=mock_persistence,
        execution_provider=mock_executor,
        workflow_builder=mock_builder,
        expression_evaluator_cls=mock_expression_evaluator_cls,
        template_engine_cls=mock_template_engine_cls,
        workflow_observer=mock_observer
    )

    assert engine.workflow_steps == []
    assert engine.steps_config == []
    assert engine.metadata == {}


def test_workflow_engine_from_dict_invalid_state_model_path():
    mock_persistence = MockPersistence()
    mock_executor = MockExecutor()
    mock_observer = MockObserver()
    mock_builder = MockBuilder()
    mock_expression_evaluator_cls = MockExpressionEvaluator
    mock_template_engine_cls = MockTemplateEngine

    engine_dict = {
        "id": "test-invalid-path",
        "workflow_type": "InvalidPathWorkflow",
        "current_step": 0,
        "status": "ACTIVE",
        "state": {},
        "steps_config": [],
        "state_model_path": "non.existent.module.InvalidState",  # Invalid path
        "owner_id": None,
        "org_id": None,
        "saga_mode": False,
        "completed_steps_stack": [],
        "parent_execution_id": None,
        "blocked_on_child_id": None,
        "data_region": None,
        "priority": 5,
        "idempotency_key": None,
        "metadata": {}
    }

    with pytest.raises(ValueError, match="Could not load workflow configuration for type 'InvalidPathWorkflow'"):
        WorkflowEngine.from_dict(
            engine_dict,
            persistence_provider=mock_persistence,
            execution_provider=mock_executor,
            workflow_builder=mock_builder,
            expression_evaluator_cls=mock_expression_evaluator_cls,
            template_engine_cls=mock_template_engine_cls,
            workflow_observer=mock_observer
        )


def test_workflow_engine_from_dict_builder_failure(monkeypatch):
    mock_persistence = MockPersistence()
    mock_executor = MockExecutor()
    mock_observer = MockObserver()
    mock_builder = MockBuilder()
    mock_expression_evaluator_cls = MockExpressionEvaluator
    mock_template_engine_cls = MockTemplateEngine

    # Mock build_steps_from_config to raise a ValueError
    def mock_build_steps_from_config(steps_config):
        raise ValueError("Builder failed to build steps")

    monkeypatch.setattr(mock_builder, 'build_steps_from_config',
                        mock_build_steps_from_config)

    engine_dict = {
        "id": "test-builder-failure",
        "workflow_type": "BuilderFailureWorkflow",
        "current_step": 0,
        "status": "ACTIVE",
        "state": {},
        "steps_config": [{"name": "Step1", "type": "STANDARD"}],
        "state_model_path": "tests.sdk.test_engine.DummyState",  # Valid path
        "owner_id": None,
        "org_id": None,
        "saga_mode": False,
        "completed_steps_stack": [],
        "parent_execution_id": None,
        "blocked_on_child_id": None,
        "data_region": None,
        "priority": 5,
        "idempotency_key": None,
        "metadata": {}
    }

    with pytest.raises(ValueError, match="Could not load workflow configuration for type 'BuilderFailureWorkflow': Builder failed to build steps"):
        WorkflowEngine.from_dict(
            engine_dict,
            persistence_provider=mock_persistence,
            execution_provider=mock_executor,
            workflow_builder=mock_builder,
            expression_evaluator_cls=mock_expression_evaluator_cls,
            template_engine_cls=mock_template_engine_cls,
            workflow_observer=mock_observer
        )


def test_workflow_engine_from_dict_with_empty_or_missing_state(common_providers):
    mock_persistence = common_providers["persistence_provider"]
    mock_executor = common_providers["execution_provider"]
    mock_observer = common_providers["workflow_observer"]
    mock_builder = common_providers["workflow_builder"]
    mock_expression_evaluator_cls = common_providers["expression_evaluator_cls"]
    mock_template_engine_cls = common_providers["template_engine_cls"]

    base_dict = {
        "id": "test-no-state",
        "workflow_type": "NoStateWorkflow",
        "current_step": 0,
        "status": "ACTIVE",
        "steps_config": [],
        "state_model_path": "tests.sdk.test_engine.DummyState",  # Valid path
        "owner_id": None, "org_id": None, "saga_mode": False,
        "completed_steps_stack": [], "parent_execution_id": None,
        "blocked_on_child_id": None, "data_region": None, "priority": 5,
        "idempotency_key": None, "metadata": {}
    }

    # Scenario 1: 'state' key is completely missing
    data_missing_state = base_dict.copy()
    reconstructed_engine = WorkflowEngine.from_dict(
        data_missing_state,
        persistence_provider=mock_persistence, execution_provider=mock_executor,
        workflow_builder=mock_builder, expression_evaluator_cls=mock_expression_evaluator_cls,
        template_engine_cls=mock_template_engine_cls, workflow_observer=mock_observer
    )
    # If state is missing, it should instantiate the state model with defaults
    # We should assert against the dynamically loaded class, not the global DummyState
    assert isinstance(reconstructed_engine.state, WorkflowEngine.from_dict(
        data_missing_state, **common_providers).state.__class__)
    assert reconstructed_engine.state.value == "default_value"

    # Scenario 2: 'state' key is present but its value is an empty dictionary
    data_empty_state = base_dict.copy()
    data_empty_state["state"] = {}
    reconstructed_engine_empty_state = WorkflowEngine.from_dict(
        data_empty_state,
        persistence_provider=mock_persistence, execution_provider=mock_executor,
        workflow_builder=mock_builder, expression_evaluator_cls=mock_expression_evaluator_cls,
        template_engine_cls=mock_template_engine_cls, workflow_observer=mock_observer
    )
    # If state is empty dict, it should instantiate the state model with defaults
    assert isinstance(reconstructed_engine_empty_state.state, WorkflowEngine.from_dict(
        data_empty_state, **common_providers).state.__class__)
    assert reconstructed_engine_empty_state.state.value == "default_value"

    # Scenario 3: 'state' key is present with some data
    data_with_state = base_dict.copy()
    data_with_state["state"] = {"value": "some_value"}
    reconstructed_engine_with_state = WorkflowEngine.from_dict(
        data_with_state,
        persistence_provider=mock_persistence, execution_provider=mock_executor,
        workflow_builder=mock_builder, expression_evaluator_cls=mock_expression_evaluator_cls,
        template_engine_cls=mock_template_engine_cls, workflow_observer=mock_observer
    )
    assert isinstance(reconstructed_engine_with_state.state, WorkflowEngine.from_dict(
        data_with_state, **common_providers).state.__class__)
    assert reconstructed_engine_with_state.state.value == "some_value"
