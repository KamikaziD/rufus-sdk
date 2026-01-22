import pytest
from unittest.mock import MagicMock, AsyncMock, patch, call
from rufus.workflow import Workflow
from rufus.models import WorkflowStep, CompensatableStep, StartSubWorkflowDirective
from pydantic import BaseModel
from typing import Dict, Any, Optional, List, Callable, Type


class MyStateModel(BaseModel):
    value: str = "initial"
    sub_workflow_results: Dict[str, Any] = {}


@pytest.fixture
def mock_providers():
    """Provides mocked provider instances and classes for Workflow."""
    mock_persistence_provider = AsyncMock()
    mock_execution_provider = AsyncMock()
    mock_workflow_observer = AsyncMock()
    mock_expression_evaluator_cls = MagicMock()
    mock_template_engine_cls = MagicMock()
    mock_workflow_builder = MagicMock()

    mock_expression_evaluator_cls.return_value = MagicMock()
    mock_template_engine_cls.return_value = MagicMock()

    return {
        "persistence_provider": mock_persistence_provider,
        "execution_provider": mock_execution_provider,
        "workflow_observer": mock_workflow_observer,
        "expression_evaluator_cls": mock_expression_evaluator_cls,
        "template_engine_cls": mock_template_engine_cls,
        "workflow_builder": mock_workflow_builder
    }


@pytest.mark.asyncio
async def test_workflow_initialization(mock_providers):
    """
    Tests that the Workflow can be initialized correctly with all parameters.
    """
    workflow_id = "test-workflow-id"
    workflow_type = "TestWorkflowType"
    initial_state = MyStateModel(value="start")
    workflow_steps = [WorkflowStep(name="step1"), WorkflowStep(name="step2")]
    steps_config = [{"name": "step1_config"}, {"name": "step2_config"}]
    state_model_path = "some.module.MyStateModel"
    owner_id = "test-owner"
    org_id = "test-org"
    data_region = "us-east-1"
    priority = 10
    idempotency_key = "test-idempotency-key"
    metadata = {"key": "value"}

    workflow = Workflow(
        workflow_id=workflow_id,
        workflow_steps=workflow_steps,
        initial_state_model=initial_state,
        workflow_type=workflow_type,
        steps_config=steps_config,
        state_model_path=state_model_path,
        owner_id=owner_id,
        org_id=org_id,
        data_region=data_region,
        priority=priority,
        idempotency_key=idempotency_key,
        metadata=metadata,
        **mock_providers
    )

    assert workflow.id == workflow_id
    assert workflow.workflow_steps == workflow_steps
    assert workflow.current_step == 0
    assert workflow.state == initial_state
    assert workflow.status == "ACTIVE"
    assert workflow.workflow_type == workflow_type
    assert workflow.steps_config == steps_config
    assert workflow.state_model_path == state_model_path
    assert workflow.owner_id == owner_id
    assert workflow.org_id == org_id
    assert workflow.data_region == data_region
    assert workflow.priority == priority
    assert workflow.idempotency_key == idempotency_key
    assert workflow.metadata == metadata
    assert workflow.persistence == mock_providers["persistence_provider"]
    assert workflow.execution == mock_providers["execution_provider"]
    assert workflow.builder == mock_providers["workflow_builder"]
    assert workflow.expression_evaluator_cls == mock_providers["expression_evaluator_cls"]
    assert workflow.template_engine_cls == mock_providers["template_engine_cls"]
    assert workflow.observer == mock_providers["workflow_observer"]
    assert workflow.saga_mode is False
    assert workflow.completed_steps_stack == []
    assert workflow.parent_execution_id is None
    assert workflow.blocked_on_child_id is None


@pytest.mark.asyncio
async def test_workflow_initialization_defaults(mock_providers):
    """
    Tests that Workflow initializes with default values when optional parameters are not provided.
    """
    workflow_type = "DefaultWorkflow"
    initial_state = MyStateModel()

    workflow = Workflow(
        workflow_type=workflow_type,
        initial_state_model=initial_state,
        **mock_providers
    )

    assert isinstance(workflow.id, str)
    assert workflow.workflow_steps == []
    assert workflow.current_step == 0
    assert workflow.state == initial_state
    assert workflow.status == "ACTIVE"
    assert workflow.workflow_type == workflow_type
    assert workflow.steps_config == []
    assert workflow.state_model_path is None
    assert workflow.owner_id is None
    assert workflow.org_id is None
    assert workflow.data_region is None
    assert workflow.priority == 5  # Default value
    assert workflow.idempotency_key is None
    assert workflow.metadata == {}  # Default empty dict
    assert workflow.persistence == mock_providers["persistence_provider"]
    assert workflow.execution == mock_providers["execution_provider"]
    assert workflow.builder == mock_providers["workflow_builder"]
    assert workflow.expression_evaluator_cls == mock_providers["expression_evaluator_cls"]
    assert workflow.template_engine_cls == mock_providers["template_engine_cls"]
    assert workflow.observer == mock_providers["workflow_observer"]
    assert workflow.saga_mode is False
    assert workflow.completed_steps_stack == []
    assert workflow.parent_execution_id is None
    assert workflow.blocked_on_child_id is None


@pytest.mark.asyncio
async def test_workflow_initialization_missing_providers():
    """
    Tests that Workflow raises ValueError if any required provider is missing.
    """
    workflow_type = "MissingProviderWorkflow"
    initial_state = MyStateModel()
    workflow_steps = [WorkflowStep(name="step1")]

    # Test missing persistence_provider
    with pytest.raises(ValueError, match="PersistenceProvider must be injected into Workflow"):
        Workflow(workflow_type=workflow_type, initial_state_model=initial_state,
                 execution_provider=MagicMock(), workflow_observer=MagicMock(),
                 expression_evaluator_cls=MagicMock(), template_engine_cls=MagicMock(),
                 workflow_builder=MagicMock())

    # Test missing execution_provider
    with pytest.raises(ValueError, match="ExecutionProvider must be injected into Workflow"):
        Workflow(workflow_type=workflow_type, initial_state_model=initial_state,
                 persistence_provider=MagicMock(), workflow_observer=MagicMock(),
                 expression_evaluator_cls=MagicMock(), template_engine_cls=MagicMock(),
                 workflow_builder=MagicMock())

    # Test missing workflow_observer
    with pytest.raises(ValueError, match="WorkflowObserver must be injected into Workflow"):
        Workflow(workflow_type=workflow_type, initial_state_model=initial_state,
                 persistence_provider=MagicMock(), execution_provider=MagicMock(),
                 expression_evaluator_cls=MagicMock(), template_engine_cls=MagicMock(),
                 workflow_builder=MagicMock())

    # Test missing workflow_builder
    with pytest.raises(ValueError, match="WorkflowBuilder must be injected into Workflow"):
        Workflow(workflow_type=workflow_type, initial_state_model=initial_state,
                 persistence_provider=MagicMock(), execution_provider=MagicMock(),
                 workflow_observer=MagicMock(), expression_evaluator_cls=MagicMock(),
                 template_engine_cls=MagicMock())

    # Test missing expression_evaluator_cls
    with pytest.raises(ValueError, match="ExpressionEvaluator class must be injected into Workflow"):
        Workflow(workflow_type=workflow_type, initial_state_model=initial_state,
                 persistence_provider=MagicMock(), execution_provider=MagicMock(),
                 workflow_observer=MagicMock(), template_engine_cls=MagicMock(),
                 workflow_builder=MagicMock())

    # Test missing template_engine_cls
    with pytest.raises(ValueError, match="TemplateEngine class must be injected into Workflow"):
        Workflow(workflow_type=workflow_type, initial_state_model=initial_state,
                 persistence_provider=MagicMock(), execution_provider=MagicMock(),
                 workflow_observer=MagicMock(), expression_evaluator_cls=MagicMock(),
                 workflow_builder=MagicMock())


@pytest.mark.asyncio
async def test_current_step_name(mock_providers):
    """
    Tests the current_step_name property.
    """
    workflow_steps = [WorkflowStep(name="StepA"), WorkflowStep(name="StepB")]

    workflow = Workflow(
        workflow_type="TestWorkflow",
        initial_state_model=MyStateModel(),
        workflow_steps=workflow_steps,
        **mock_providers
    )

    # Test when current_step is within bounds
    assert workflow.current_step_name == "StepA"

    # Test when current_step moves to the next step
    workflow.current_step = 1
    assert workflow.current_step_name == "StepB"

    # Test when current_step is out of bounds (beyond last step)
    workflow.current_step = 2
    assert workflow.current_step_name is None

    # Test with no workflow steps
    workflow_no_steps = Workflow(
        workflow_type="TestWorkflow",
        initial_state_model=MyStateModel(),
        workflow_steps=[],
        **mock_providers
    )
    assert workflow_no_steps.current_step_name is None


@pytest.mark.asyncio
async def test_to_dict_method(mock_providers):
    """
    Tests the to_dict method of the Workflow.
    """
    workflow_id = "to-dict-wf-id"
    workflow_type = "ToDictWorkflow"
    initial_state = MyStateModel(value="to_dict_initial")
    steps_config = [{"name": "step_a"}, {"name": "step_b"}]
    state_model_path = "path.to.MyStateModel"
    owner_id = "owner123"
    org_id = "orgABC"
    data_region = "eu-west-1"
    priority = 7
    idempotency_key = "idemp-key-xyz"
    metadata = {"source": "test"}

    workflow = Workflow(
        workflow_id=workflow_id,
        workflow_type=workflow_type,
        initial_state_model=initial_state,
        steps_config=steps_config,
        state_model_path=state_model_path,
        owner_id=owner_id,
        org_id=org_id,
        data_region=data_region,
        priority=priority,
        idempotency_key=idempotency_key,
        metadata=metadata,
        **mock_providers
    )
    workflow.saga_mode = True
    workflow.completed_steps_stack = [{"step": "prev"}]
    workflow.parent_execution_id = "parent-wf"
    workflow.blocked_on_child_id = "child-wf"
    workflow.current_step = 1
    workflow.status = "PAUSED"

    as_dict = workflow.to_dict()

    assert as_dict["id"] == workflow_id
    assert as_dict["workflow_type"] == workflow_type
    assert as_dict["current_step"] == 1
    assert as_dict["status"] == "PAUSED"
    assert as_dict["state"] == {
        "value": "to_dict_initial", "sub_workflow_results": {}}
    assert as_dict["steps_config"] == steps_config
    assert as_dict["state_model_path"] == state_model_path
    assert as_dict["owner_id"] == owner_id
    assert as_dict["org_id"] == org_id
    assert as_dict["data_region"] == data_region
    assert as_dict["priority"] == priority
    assert as_dict["idempotency_key"] == idempotency_key
    assert as_dict["metadata"] == metadata
    assert as_dict["saga_mode"] is True
    assert as_dict["completed_steps_stack"] == [{"step": "prev"}]
    assert as_dict["parent_execution_id"] == "parent-wf"
    assert as_dict["blocked_on_child_id"] == "child-wf"


@pytest.mark.asyncio
async def test_from_dict_method(mock_providers):
    """
    Tests the from_dict class method of the Workflow.
    """
    workflow_id = "from-dict-wf-id"
    workflow_type = "FromDictWorkflow"
    # Point to local model for simplicity
    state_model_path = "tests.sdk.test_workflow.MyStateModel"
    steps_config = [{"name": "step_c"}]
    workflow_data = {
        "id": workflow_id,
        "workflow_type": workflow_type,
        "current_step": 0,
        "status": "ACTIVE",
        "state": {"value": "from_dict_initial", "sub_workflow_results": {}},
        "steps_config": steps_config,
        "state_model_path": state_model_path,
        "owner_id": "owner-from-dict",
        "org_id": "org-from-dict",
        "data_region": "us-east-2",
        "priority": 3,
        "idempotency_key": "from-dict-idemp",
        "metadata": {"custom": "data"},
        "saga_mode": False,
        "completed_steps_stack": [],
        "parent_execution_id": None,
        "blocked_on_child_id": None
    }

    # Mock WorkflowBuilder's static methods
    with patch('rufus.builder.WorkflowBuilder._import_from_string', return_value=MyStateModel) as mock_import_from_string, \
            patch('rufus.builder.WorkflowBuilder._build_steps_from_config', return_value=[WorkflowStep(name="step_c")]) as mock_build_steps_from_config:

        workflow = Workflow.from_dict(workflow_data, **mock_providers)

        mock_import_from_string.assert_called_once_with(state_model_path)
        mock_build_steps_from_config.assert_called_once_with(steps_config)

        assert workflow.id == workflow_id
        assert workflow.workflow_type == workflow_type
        assert workflow.current_step == 0
        assert workflow.status == "ACTIVE"
        assert workflow.state.value == "from_dict_initial"
        assert workflow.state.sub_workflow_results == {}
        assert workflow.steps_config == steps_config
        assert workflow.state_model_path == state_model_path
        assert workflow.owner_id == "owner-from-dict"
        assert workflow.org_id == "org-from-dict"
        assert workflow.data_region == "us-east-2"
        assert workflow.priority == 3
        assert workflow.idempotency_key == "from-dict-idemp"
        assert workflow.metadata == {"custom": "data"}
        assert workflow.saga_mode is False
        assert workflow.completed_steps_stack == []
        assert workflow.parent_execution_id is None
        assert workflow.blocked_on_child_id is None
        assert workflow.persistence == mock_providers["persistence_provider"]
        assert workflow.execution == mock_providers["execution_provider"]
        assert workflow.builder == mock_providers["workflow_builder"]
        assert workflow.expression_evaluator_cls == mock_providers["expression_evaluator_cls"]
        assert workflow.template_engine_cls == mock_providers["template_engine_cls"]
        assert workflow.observer == mock_providers["workflow_observer"]


@pytest.mark.asyncio
async def test_from_dict_missing_data(mock_providers):
    """
    Tests that from_dict raises ValueError if workflow_type or state_model_path is missing.
    """
    # Missing workflow_type
    with pytest.raises(ValueError, match="Missing workflow_type or state_model_path in data."):
        Workflow.from_dict(
            {"id": "some-id", "state_model_path": "path"}, **mock_providers)

    # Missing state_model_path
    with pytest.raises(ValueError, match="Missing workflow_type or state_model_path in data."):
        Workflow.from_dict(
            {"id": "some-id", "workflow_type": "type"}, **mock_providers)


@pytest.mark.asyncio
async def test_from_dict_state_instantiation_without_state_in_data(mock_providers):
    """
    Tests that from_dict instantiates a default state model if 'state' is missing or empty in data.
    """
    workflow_id = "default-state-wf"
    workflow_type = "DefaultStateWorkflow"
    state_model_path = "tests.sdk.test_workflow.MyStateModel"

    workflow_data = {
        "id": workflow_id,
        "workflow_type": workflow_type,
        "current_step": 0,
        "status": "ACTIVE",
        "steps_config": [],
        "state_model_path": state_model_path,
        # 'state' key is missing
    }

    with patch('rufus.builder.WorkflowBuilder._import_from_string', return_value=MyStateModel) as mock_import_from_string, \
            patch('rufus.builder.WorkflowBuilder._build_steps_from_config', return_value=[]):

        workflow = Workflow.from_dict(workflow_data, **mock_providers)
        assert isinstance(workflow.state, MyStateModel)
        assert workflow.state.value == "initial"  # Check default value

    workflow_data_empty_state = {
        "id": workflow_id,
        "workflow_type": workflow_type,
        "current_step": 0,
        "status": "ACTIVE",
        "state": {},
        "steps_config": [],
        "state_model_path": state_model_path,
    }
    with patch('rufus.builder.WorkflowBuilder._import_from_string', return_value=MyStateModel) as mock_import_from_string, \
            patch('rufus.builder.WorkflowBuilder._build_steps_from_config', return_value=[]):

        workflow = Workflow.from_dict(
            workflow_data_empty_state, **mock_providers)
        assert isinstance(workflow.state, MyStateModel)
        assert workflow.state.value == "initial"  # Check default value


@pytest.mark.asyncio
async def test_notify_status_change_no_parent(mock_providers):
    """
    Tests _notify_status_change when there is no parent workflow.
    """
    workflow = Workflow(
        workflow_id="wf-1",
        workflow_type="TestWorkflow",
        initial_state_model=MyStateModel(),
        **mock_providers
    )
    old_status = "ACTIVE"
    new_status = "COMPLETED"
    current_step_name = "final_step"

    await workflow._notify_status_change(old_status, new_status, current_step_name)

    mock_providers["workflow_observer"].on_workflow_status_changed.assert_called_once_with(
        workflow.id, old_status, new_status, current_step_name)
    mock_providers["execution_provider"].report_child_status_to_parent.assert_not_called()


@pytest.mark.asyncio
async def test_notify_status_change_with_parent(mock_providers):
    """
    Tests _notify_status_change when there is a parent workflow.
    """
    workflow = Workflow(
        workflow_id="wf-2",
        workflow_type="TestWorkflow",
        initial_state_model=MyStateModel(),
        **mock_providers
    )
    workflow.parent_execution_id = "parent-wf-id"
    old_status = "PENDING_SUB_WORKFLOW"
    new_status = "ACTIVE"
    current_step_name = "sub_workflow_resumed"
    final_result = {"output": "child_done"}

    await workflow._notify_status_change(old_status, new_status, current_step_name, final_result)

    mock_providers["workflow_observer"].on_workflow_status_changed.assert_called_once_with(
        workflow.id, old_status, new_status, current_step_name)
    mock_providers["execution_provider"].report_child_status_to_parent.assert_called_once_with(
        child_id=workflow.id,
        parent_id=workflow.parent_execution_id,
        child_new_status=new_status,
        child_current_step_name=current_step_name,
        child_result=final_result
    )

@pytest.mark.asyncio
async def test_enable_saga_mode(mock_providers):
    """
    Tests that enable_saga_mode sets saga_mode to True.
    """
    workflow = Workflow(
        workflow_id="wf-saga",
        workflow_type="TestWorkflow",
        initial_state_model=MyStateModel(),
        **mock_providers
    )
    assert workflow.saga_mode is False
    await workflow.enable_saga_mode()
    assert workflow.saga_mode is True


@pytest.mark.asyncio
async def test_log_execution(mock_providers):
    """
    Tests that _log_execution calls persistence.log_execution with correct arguments.
    """
    workflow_id = "wf-log"
    workflow = Workflow(
        workflow_id=workflow_id,
        workflow_type="TestWorkflow",
        initial_state_model=MyStateModel(),
        **mock_providers
    )
    
    log_level = "INFO"
    message = "Test message"
    step_name = "test_step"
    metadata = {"key": "value"}

    await workflow._log_execution(log_level, message, step_name, metadata)

    mock_providers["persistence_provider"].log_execution.assert_called_once_with(
        workflow_id=workflow_id,
        log_level=log_level,
        message=message,
        step_name=step_name,
        metadata=metadata
    )


@pytest.mark.asyncio
async def test_execute_saga_rollback_with_completed_steps(mock_providers):
    """
    Tests _execute_saga_rollback when there are completed steps to roll back.
    """
    workflow_id = "wf-saga-rollback"
    workflow_type = "TestSagaWorkflow"
    
    # Create a mock CompensatableStep
    mock_compensatable_step = MagicMock(spec=CompensatableStep)
    mock_compensatable_step.name = "step_to_compensate"
    mock_compensatable_step.compensate = AsyncMock(return_value={"compensation_status": "success"})

    workflow = Workflow(
        workflow_id=workflow_id,
        workflow_type=workflow_type,
        initial_state_model=MyStateModel(value="after_step"),
        workflow_steps=[mock_compensatable_step],
        **mock_providers
    )
    workflow.saga_mode = True
    workflow.status = "FAILED" # Simulate a failed workflow
    
    # Populate completed_steps_stack
    workflow.completed_steps_stack = [
        {
            'step_index': 0,
            'step_name': "step_to_compensate",
            'state_snapshot': MyStateModel(value="before_step").model_dump()
        }
    ]

    initial_status = workflow.status
    initial_completed_steps_stack = list(workflow.completed_steps_stack) # Copy for assertion

    with patch.object(workflow, '_notify_status_change', AsyncMock()) as mock_notify_status_change:
        await workflow._execute_saga_rollback()

        assert workflow.status == "FAILED_ROLLED_BACK"
        
        # Verify persistence.save_workflow is called twice (before and after rollback)
        assert mock_providers["persistence_provider"].save_workflow.call_count == 2
        
        # Verify on_workflow_rolled_back is called
        mock_providers["workflow_observer"].on_workflow_rolled_back.assert_called_once_with(
            workflow.id,
            workflow.workflow_type,
            "Saga rollback completed",
            workflow.state,
            initial_completed_steps_stack
        )
        
        # Verify _notify_status_change is called with correct statuses
        mock_notify_status_change.assert_called_once_with(
            initial_status, "FAILED_ROLLED_BACK", workflow.current_step_name
        )

        # Verify compensate method was called
        mock_compensatable_step.compensate.assert_called_once()
        
        # Verify log_compensation is called for successful compensation
        mock_providers["persistence_provider"].log_compensation.assert_called_once()
        args, kwargs = mock_providers["persistence_provider"].log_compensation.call_args
        assert kwargs['action_type'] == 'COMPENSATE'
        assert kwargs['execution_id'] == workflow_id
        assert kwargs['step_name'] == "step_to_compensate"
        assert kwargs['step_index'] == 0
        assert kwargs['action_result'] == {"compensation_status": "success"}


@pytest.mark.asyncio
async def test_execute_saga_rollback_compensation_failure(mock_providers):
    """
    Tests _execute_saga_rollback when a compensation function fails.
    """
    workflow_id = "wf-saga-comp-fail"
    workflow_type = "TestSagaWorkflow"
    
    # Create a mock CompensatableStep that raises an exception
    mock_compensatable_step = MagicMock(spec=CompensatableStep)
    mock_compensatable_step.name = "step_to_compensate"
    mock_compensatable_step.compensate = AsyncMock(side_effect=Exception("Compensation failed!"))

    workflow = Workflow(
        workflow_id=workflow_id,
        workflow_type=workflow_type,
        initial_state_model=MyStateModel(value="after_step"),
        workflow_steps=[mock_compensatable_step],
        **mock_providers
    )
    workflow.saga_mode = True
    workflow.status = "FAILED" # Simulate a failed workflow
    
    # Populate completed_steps_stack
    workflow.completed_steps_stack = [
        {
            'step_index': 0,
            'step_name': "step_to_compensate",
            'state_snapshot': MyStateModel(value="before_step").model_dump()
        }
    ]

    initial_status = workflow.status
    initial_completed_steps_stack = list(workflow.completed_steps_stack)

    with patch.object(workflow, '_notify_status_change', AsyncMock()) as mock_notify_status_change:
        await workflow._execute_saga_rollback()

        assert workflow.status == "FAILED_ROLLED_BACK"
        
        # Verify persistence.save_workflow is called twice
        assert mock_providers["persistence_provider"].save_workflow.call_count == 2
        
        # Verify on_workflow_rolled_back is called
        mock_providers["workflow_observer"].on_workflow_rolled_back.assert_called_once_with(
            workflow.id,
            workflow.workflow_type,
            "Saga rollback completed",
            workflow.state,
            initial_completed_steps_stack
        )
        
        # Verify _notify_status_change is called
        mock_notify_status_change.assert_called_once_with(
            initial_status, "FAILED_ROLLED_BACK", workflow.current_step_name
        )

        # Verify compensate method was called
        mock_compensatable_step.compensate.assert_called_once()
        
        # Verify log_compensation is called for failed compensation
        mock_providers["persistence_provider"].log_compensation.assert_called_once()
        args, kwargs = mock_providers["persistence_provider"].log_compensation.call_args
        assert kwargs['action_type'] == 'COMPENSATE_FAILED'
        assert kwargs['execution_id'] == workflow_id
        assert kwargs['step_name'] == "step_to_compensate"
        assert kwargs['step_index'] == 0
        assert "Compensation failed!" in kwargs['error_message']


@pytest.mark.asyncio
async def test_handle_sub_workflow_creation_failure(mock_providers):
    """
    Tests _handle_sub_workflow when sub-workflow creation fails.
    """
    workflow_id = "parent-wf-fail"
    parent_workflow_type = "ParentWorkflow"
    sub_workflow_type = "ChildWorkflow"

    workflow = Workflow(
        workflow_id=workflow_id,
        workflow_type=parent_workflow_type,
        initial_state_model=MyStateModel(),
        data_region="us-east-1",
        **mock_providers
    )
    
    # Mock create_workflow to raise an exception
    mock_providers["workflow_builder"].create_workflow = AsyncMock(side_effect=Exception("Failed to create sub-workflow"))

    directive = StartSubWorkflowDirective(
        workflow_type=sub_workflow_type,
        initial_data={"some": "data"},
        data_region=None
    )

    with pytest.raises(Exception, match="Failed to create sub-workflow"):
        await workflow._handle_sub_workflow(directive)

    mock_providers["workflow_builder"].create_workflow.assert_called_once()
    mock_providers["persistence_provider"].save_workflow.assert_not_called()
    mock_providers["execution_provider"].dispatch_sub_workflow.assert_not_called()
    mock_providers["workflow_observer"].on_workflow_status_changed.assert_not_called()


@pytest.mark.asyncio
async def test_handle_sub_workflow_success(mock_providers):
    """
    Tests _handle_sub_workflow for successful creation and dispatch of a sub-workflow.
    """
    workflow_id = "parent-wf-success"
    parent_workflow_type = "ParentWorkflow"
    sub_workflow_type = "ChildWorkflow"
    child_workflow_id = "child-wf-123"
    child_initial_state = MyStateModel(value="child_initial")

    # Mock a child workflow instance
    mock_child_workflow = MagicMock(spec=Workflow)
    mock_child_workflow.id = child_workflow_id
    mock_child_workflow.workflow_type = sub_workflow_type # New line
    mock_child_workflow.parent_execution_id = None # Should be set by parent
    mock_child_workflow.data_region = None # Should be set by parent
    mock_child_workflow.to_dict.return_value = {"id": child_workflow_id, "status": "ACTIVE", "state": child_initial_state.model_dump()}
    
    mock_child_workflow.initial_state_model = MagicMock(spec=MyStateModel) # Mock the model itself
    mock_child_workflow.initial_state_model.model_dump.return_value = child_initial_state.model_dump() # Mock its method

    # Mock create_workflow to return the mock child workflow
    mock_providers["workflow_builder"].create_workflow = AsyncMock(return_value=mock_child_workflow)
    
    # Mock _notify_status_change
    with patch.object(Workflow, '_notify_status_change', AsyncMock()) as mock_notify_status_change:
        workflow = Workflow(
            workflow_id=workflow_id,
            workflow_type=parent_workflow_type,
            initial_state_model=MyStateModel(value="parent_initial"),
            data_region="us-west-2",
            **mock_providers
        )
        initial_parent_status = workflow.status

        directive = StartSubWorkflowDirective(
            workflow_type=sub_workflow_type,
            initial_data={"input": "data"},
            data_region="eu-central-1" # Child specifies its own region
        )

        result, next_step_name = await workflow._handle_sub_workflow(directive)

        # Assertions
        mock_providers["workflow_builder"].create_workflow.assert_called_once_with(
            workflow_type=sub_workflow_type,
            initial_data=directive.initial_data,
            persistence_provider=mock_providers["persistence_provider"],
            execution_provider=mock_providers["execution_provider"],
            workflow_builder=mock_providers["workflow_builder"],
            expression_evaluator_cls=mock_providers["expression_evaluator_cls"],
            template_engine_cls=mock_providers["template_engine_cls"],
            workflow_observer=mock_providers["workflow_observer"]
        )
        
        # Verify child workflow attributes set
        assert mock_child_workflow.parent_execution_id == workflow.id
        assert mock_child_workflow.data_region == directive.data_region # Child-specific region

        assert workflow.status == "PENDING_SUB_WORKFLOW"
        assert workflow.blocked_on_child_id == child_workflow_id

        mock_providers["persistence_provider"].save_workflow.assert_has_calls([
            call(workflow.id, workflow.to_dict()),
            call(mock_child_workflow.id, mock_child_workflow.to_dict())
        ], any_order=True)

        mock_notify_status_change.assert_called_once_with(
            initial_parent_status, "PENDING_SUB_WORKFLOW", workflow.current_step_name
        )

        mock_providers["execution_provider"].dispatch_sub_workflow.assert_called_once_with(
            child_workflow_id,
            workflow.id,
            sub_workflow_type,
            child_initial_state.model_dump()
        )

        assert result == {
            "message": f"Sub-workflow {sub_workflow_type} started",
            "child_workflow_id": child_workflow_id,
            "parent_workflow_id": workflow.id
        }
        assert next_step_name is None


@pytest.mark.asyncio
async def test_handle_sub_workflow_inherits_data_region(mock_providers):
    """
    Tests _handle_sub_workflow when the child inherits data_region from parent.
    """
    workflow_id = "parent-wf-inherit"
    parent_workflow_type = "ParentWorkflow"
    sub_workflow_type = "ChildWorkflow"
    child_workflow_id = "child-wf-inherit"
    child_initial_state = MyStateModel(value="child_initial")

    mock_child_workflow = MagicMock(spec=Workflow)
    mock_child_workflow.id = child_workflow_id
    mock_child_workflow.workflow_type = sub_workflow_type # New line
    mock_child_workflow.parent_execution_id = None
    mock_child_workflow.data_region = None
    mock_child_workflow.to_dict.return_value = {"id": child_workflow_id, "status": "ACTIVE", "state": child_initial_state.model_dump()}
    
    mock_child_workflow.initial_state_model = MagicMock(spec=MyStateModel) # Mock the model itself
    mock_child_workflow.initial_state_model.model_dump.return_value = child_initial_state.model_dump() # Mock its method

    mock_providers["workflow_builder"].create_workflow = AsyncMock(return_value=mock_child_workflow)
    
    with patch.object(Workflow, '_notify_status_change', AsyncMock()):
        workflow = Workflow(
            workflow_id=workflow_id,
            workflow_type=parent_workflow_type,
            initial_state_model=MyStateModel(value="parent_initial"),
            data_region="us-central-1", # Parent has a data region
            **mock_providers
        )

        directive = StartSubWorkflowDirective(
            workflow_type=sub_workflow_type,
            initial_data={"input": "data"},
            data_region=None # Child does NOT specify its own region
        )

        await workflow._handle_sub_workflow(directive)

        assert mock_child_workflow.data_region == workflow.data_region # Child should inherit



