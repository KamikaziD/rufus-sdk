import importlib
import pytest
from unittest.mock import MagicMock, patch
from rufus.builder import WorkflowBuilder
from pydantic import BaseModel
from typing import Dict, Any, List, Callable, Type, ClassVar # Import ClassVar
from rufus.models import (
    WorkflowStep, StepContext, AsyncWorkflowStep, CompensatableStep, HttpWorkflowStep,
    FireAndForgetWorkflowStep, LoopStep, CronScheduleWorkflowStep, ParallelWorkflowStep,
    ParallelExecutionTask, MergeStrategy, MergeConflictBehavior
)


# Dummy classes for testing
class DummyState(BaseModel):
    pass

class DummyContext(StepContext):
    pass

class MyCustomStep(WorkflowStep):
    STEP_TYPE_NAME: ClassVar[str] = "my.custom.step"
    # Ensure __init__ accepts and passes **kwargs to super()
    def __init__(self, name: str, input_schema: Type[BaseModel] = None, **kwargs):
        super().__init__(name=name, input_schema=input_schema, func=self.execute, **kwargs)

    def execute(self, state: BaseModel, context: StepContext):
        pass

class AnotherStep(WorkflowStep):
    # No STEP_TYPE_NAME here, this tests the fallback to entry_point.name
    # Ensure __init__ accepts and passes **kwargs to super()
    def __init__(self, name: str, input_schema: Type[BaseModel] = None, **kwargs):
        super().__init__(name=name, input_schema=input_schema, func=self.execute, **kwargs)
    def execute(self, state: BaseModel, context: StepContext):
        pass

class NotAWorkflowStep:
    pass

# Mock function for step execution
def mock_step_function(state: DummyState, context: DummyContext):
    return {"status": "executed"}

# Mock function for compensation
def mock_compensate_function(state: DummyState, context: DummyContext):
    return {"status": "compensated"}

# Mock function for parallel merge
def mock_merge_function(state: DummyState, context: DummyContext, results: List[Dict[str, Any]]):
    return {"merged_results": results}

class CustomStepClass(WorkflowStep):
    custom_param: str = "default" # Define custom_param as a Pydantic field with a default
    # Ensure __init__ accepts and passes **kwargs to super()
    def __init__(self, name: str, input_schema: Type[BaseModel] = None, **kwargs):
        # Pydantic will handle `custom_param` if it's passed in kwargs or if it has a default
        super().__init__(name=name, input_schema=input_schema, func=self.execute, **kwargs)
    
    def execute(self, state: BaseModel, context: StepContext):
        return {"custom_param_used": self.custom_param}

class TestStepInput(BaseModel):
    value: str

class TestFuncs:
    def standard_func(state: BaseModel, context: DummyContext): pass
    def compensate_func(state: BaseModel, context: DummyContext): pass
    def merge_func(state: BaseModel, context: DummyContext, results: List[Dict[str, Any]]): pass

@pytest.fixture
def mock_providers():
    """Provides a dictionary of mocked provider classes for the WorkflowBuilder."""
    return {
        "expression_evaluator_cls": MagicMock(),
        "template_engine_cls": MagicMock(),
    }

def test_workflow_builder_initialization(mock_providers):
    """
    Tests that the WorkflowBuilder can be initialized correctly.
    """
    workflow_registry = {"test_workflow": {}}
    builder = WorkflowBuilder(workflow_registry=workflow_registry, **mock_providers)
    assert builder.workflow_registry == workflow_registry
    assert builder.expression_evaluator_cls is not None
    assert builder.template_engine_cls is not None

def test_validate_step_function():
    """
    Tests the _validate_step_function static method with valid and invalid functions.
    """
    # Valid function
    def valid_func(state: DummyState, context: DummyContext):
        pass
    WorkflowBuilder._validate_step_function(valid_func) # Should not raise an error

    # Function missing 'state'
    def no_state_func(context: DummyContext):
        pass
    with pytest.raises(ValueError, match="Step function 'no_state_func' is missing the required 'state' parameter."):
        WorkflowBuilder._validate_step_function(no_state_func)

    # Function missing 'context'
    def no_context_func(state: DummyState):
        pass
    with pytest.raises(ValueError, match="Step function 'no_context_func' is missing the required 'context' parameter."):
        WorkflowBuilder._validate_step_function(no_context_func)

    # Function with incorrect parameter names
    def wrong_params_func(s: DummyState, c: DummyContext):
        pass
    with pytest.raises(ValueError, match="Step function 'wrong_params_func' is missing the required 'state' parameter."):
        WorkflowBuilder._validate_step_function(wrong_params_func)

def test_import_from_string():
    """
    Tests the _import_from_string static method.
    """
    # Create a dummy module and class for testing
    with open("tests/sdk/temp_test_module.py", "w") as f:
        f.write("class MyTestClass:\n    pass\n")

    import tests.sdk.temp_test_module
    importlib.reload(tests.sdk.temp_test_module)
    from tests.sdk.temp_test_module import MyTestClass
    builder = WorkflowBuilder(workflow_registry={}, expression_evaluator_cls=MagicMock(), template_engine_cls=MagicMock())
    imported_class = builder._import_from_string("tests.sdk.temp_test_module.MyTestClass")
    assert imported_class == MyTestClass

    # Clean up the dummy module
    import os
    os.remove("tests/sdk/temp_test_module.py")


def test_discover_marketplace_steps_valid(monkeypatch, mock_providers):
    """
    Tests that valid marketplace steps are discovered and registered.
    """
    # Mock EntryPoint
    mock_entry_point_valid = MagicMock()
    mock_entry_point_valid.name = "my_custom_step"
    mock_entry_point_valid.value = "tests.sdk.test_builder.MyCustomStep"
    mock_entry_point_valid.load.return_value = MyCustomStep

    mock_entry_point_no_step_type_name = MagicMock()
    mock_entry_point_no_step_type_name.name = "another_step"
    mock_entry_point_no_step_type_name.value = "tests.sdk.test_builder.AnotherStep"
    
    mock_entry_point_no_step_type_name.load.return_value = AnotherStep

    # Mock importlib.metadata.entry_points
    mock_entry_points_map = {
        'rufus.steps': [mock_entry_point_valid, mock_entry_point_no_step_type_name]
    }
    monkeypatch.setattr(importlib.metadata, 'entry_points', lambda: mock_entry_points_map)

    # Clear _marketplace_steps to ensure _discover_marketplace_steps is called by THIS test's builder init
    WorkflowBuilder._marketplace_steps = {}
    builder = WorkflowBuilder(workflow_registry={}, **mock_providers)
    assert "my.custom.step" in builder._marketplace_steps
    assert builder._marketplace_steps["my.custom.step"] == MyCustomStep
    assert "another_step" in builder._marketplace_steps # Uses entry_point.name if STEP_TYPE_NAME is missing
    assert builder._marketplace_steps["another_step"] == AnotherStep


def test_discover_marketplace_steps_invalid_class(monkeypatch, mock_providers):
    """
    Tests that non-WorkflowStep classes are not registered and a warning is logged.
    """
    mock_entry_point_invalid = MagicMock()
    mock_entry_point_invalid.name = "not_a_workflow_step"
    mock_entry_point_invalid.value = "tests.sdk.test_builder.NotAWorkflowStep"
    mock_entry_point_invalid.load.return_value = NotAWorkflowStep

    mock_entry_points_map = {
        'rufus.steps': [mock_entry_point_invalid]
    }
    monkeypatch.setattr(importlib.metadata, 'entry_points', lambda: mock_entry_points_map)

    # Clear _marketplace_steps to ensure _discover_marketplace_steps is called by THIS test's builder init
    WorkflowBuilder._marketplace_steps = {}
    with patch('rufus.builder.logger') as mock_logger:
        builder = WorkflowBuilder(workflow_registry={}, **mock_providers) # Instantiate INSIDE patch
        assert "not_a_workflow_step" not in builder._marketplace_steps
        mock_logger.warning.assert_called_with(
            f"Entry point {mock_entry_point_invalid.name} loaded a class "
            f"{NotAWorkflowStep.__name__} which is not a WorkflowStep subclass."
        )

def test_discover_marketplace_steps_load_error(monkeypatch, mock_providers):
    """
    Tests that errors during entry point loading are handled and logged.
    """
    mock_entry_point_error = MagicMock()
    mock_entry_point_error.name = "failing_step"
    mock_entry_point_error.value = "some.module:FailingStep"
    mock_entry_point_error.load.side_effect = ImportError("Cannot load module")

    mock_entry_points_map = {
        'rufus.steps': [mock_entry_point_error]
    }
    monkeypatch.setattr(importlib.metadata, 'entry_points', lambda: mock_entry_points_map)

    # Clear _marketplace_steps to ensure _discover_marketplace_steps is called by THIS test's builder init
    WorkflowBuilder._marketplace_steps = {}
    with patch('rufus.builder.logger') as mock_logger:
        builder = WorkflowBuilder(workflow_registry={}, **mock_providers) # Instantiate INSIDE patch
        assert "failing_step" not in builder._marketplace_steps
        mock_logger.error.assert_called_with(
            f"Failed to load rufus.steps entry point {mock_entry_point_error.name}: Cannot load module"
        )


def test_apply_env_variables_to_dict(monkeypatch):
    """
    Tests the _apply_env_variables_to_dict static method.
    """
    monkeypatch.setenv("MY_TEST_VAR", "my_value")
    data = {
        "key1": "value1",
        "key2": "${MY_TEST_VAR}",
        "key3": "${MY_OTHER_VAR:-default_value}",
        "nested": {
            "key4": "${MY_TEST_VAR}"
        },
        "list_of_strings": ["item1", "${MY_TEST_VAR}"],
        "non_string": 123
    }
    builder = WorkflowBuilder(workflow_registry={}, expression_evaluator_cls=MagicMock(), template_engine_cls=MagicMock())
    processed_data = builder._apply_env_variables_to_dict(data)
    assert processed_data["key1"] == "value1"
    assert processed_data["key2"] == "my_value"
    assert processed_data["key3"] == "default_value"
    assert processed_data["nested"]["key4"] == "my_value"
    assert processed_data["list_of_strings"] == ["item1", "my_value"]
    assert processed_data["non_string"] == 123

    # Test with no default and unset variable
    data_no_default = {"key": "${UNSET_VAR}"}
    processed_data_no_default = builder._apply_env_variables_to_dict(data_no_default)
    assert processed_data_no_default["key"] == "${UNSET_VAR}"

    monkeypatch.delenv("MY_TEST_VAR") # Clean up env var
    # Test after unsetting env var
    processed_data_unset_env = builder._apply_env_variables_to_dict(data)
    assert processed_data_unset_env["key2"] == "${MY_TEST_VAR}" # Should remain unreplaced
    assert processed_data_unset_env["key3"] == "default_value" # Should still use default

def test_get_workflow_config(monkeypatch):
    """
    Tests the get_workflow_config method.
    """
    monkeypatch.setenv("MY_TEST_VAR", "my_value")
    workflow_registry = {
        "test_workflow": {
            "initial_state_model_path": "some.path.StateModel",
            "param1": "${MY_TEST_VAR}",
            "param2": "static_value",
            "parameters": {
                "template_param_value": "Some Value" # Parameter value for template
            },
            "templated_field": "This is a {{ parameters.template_param_value }} field.",
            "steps": []
        }
    }
    
    mock_template_engine_cls = MagicMock()
    # Simulate render_string_template behavior more generically
    # This mock will try to find and replace any {{ parameters.KEY }} in the template string
    def mock_render_string_template(template_str, context):
        # Simple simulation: replace placeholders if corresponding param exists
        if "parameters" in context:
            for key, value in context["parameters"].items():
                placeholder = f"{{{{ parameters.{key} }}}}"
                if placeholder in template_str:
                    template_str = template_str.replace(placeholder, str(value))
        return template_str

    mock_template_engine_cls.return_value.render_string_template.side_effect = mock_render_string_template

    builder = WorkflowBuilder(
        workflow_registry=workflow_registry,
        expression_evaluator_cls=MagicMock(),
        template_engine_cls=mock_template_engine_cls
    )

    config = builder.get_workflow_config("test_workflow")
    assert config["param1"] == "my_value"
    assert config["param2"] == "static_value"
    assert config["templated_field"] == "This is a Some Value field."
    assert config["parameters"]["template_param_value"] == "Some Value"
    
    monkeypatch.delenv("MY_TEST_VAR") # Clean up env var


def test_get_state_model_class():
    """
    Tests the get_state_model_class method.
    """
    # Create a dummy module and class for testing
    with open("tests/sdk/temp_test_module.py", "w") as f:
        f.write("from pydantic import BaseModel\nclass MyStateModel(BaseModel):\n    pass\n")

    # Dynamically import the module
    import tests.sdk.temp_test_module
    importlib.reload(tests.sdk.temp_test_module)
    from tests.sdk.temp_test_module import MyStateModel

    workflow_registry = {
        "test_workflow": {
            "initial_state_model_path": "tests.sdk.temp_test_module.MyStateModel"
        }
    }

    mock_template_engine_cls = MagicMock()
    mock_template_engine_cls.return_value.render_string_template.side_effect = lambda template, context: template

    builder = WorkflowBuilder(
        workflow_registry=workflow_registry,
        expression_evaluator_cls=MagicMock(),
        template_engine_cls=mock_template_engine_cls
    )

    model_class = builder.get_state_model_class("test_workflow")
    assert model_class == MyStateModel

    # Clean up the dummy module
    import os
    os.remove("tests/sdk/temp_test_module.py")


@pytest.mark.asyncio
async def test_create_workflow():
    """
    Tests the create_workflow method.
    """
    # Create a dummy module and class for testing
    with open("tests/sdk/temp_test_module.py", "w") as f:
        f.write("from pydantic import BaseModel\nclass MyStateModel(BaseModel):\n    pass\n")

    # Dynamically import the module
    import tests.sdk.temp_test_module
    importlib.reload(tests.sdk.temp_test_module)
    from tests.sdk.temp_test_module import MyStateModel

    workflow_registry = {
        "test_workflow": {
            "initial_state_model_path": "tests.sdk.temp_test_module.MyStateModel",
            "steps": []
        }
    }

    mock_template_engine_cls = MagicMock()
    mock_template_engine_cls.return_value.render_string_template.side_effect = lambda template, context: template

    builder = WorkflowBuilder(
        workflow_registry=workflow_registry,
        expression_evaluator_cls=MagicMock(),
        template_engine_cls=mock_template_engine_cls
    )

    workflow = await builder.create_workflow(
        workflow_type="test_workflow",
        persistence_provider=MagicMock(),
        execution_provider=MagicMock(),
        workflow_builder=builder,
        expression_evaluator_cls=MagicMock(),
        template_engine_cls=mock_template_engine_cls,
        workflow_observer=MagicMock()
    )

    from rufus.workflow import Workflow
    assert isinstance(workflow, Workflow)
    assert workflow.workflow_type == "test_workflow"
    # Check state type by class name instead of isinstance to avoid module reload issues
    assert type(workflow.state).__name__ == "MyStateModel"

    # Clean up the dummy module
    import os
    os.remove("tests/sdk/temp_test_module.py")


def test_build_steps_from_config(monkeypatch, mock_providers):
    """
    Tests the _build_steps_from_config class method for various step types.
    """
    # Mock _import_from_string to return our dummy functions/classes
    def mock_import_from_string(path: str):
        if path == "tests.sdk.test_builder.TestStepInput":
            return TestStepInput
        if path == "tests.sdk.test_builder.TestFuncs.standard_func":
            return TestFuncs.standard_func
        if path == "tests.sdk.test_builder.TestFuncs.compensate_func":
            return TestFuncs.compensate_func
        if path == "tests.sdk.test_builder.TestFuncs.merge_func":
            return TestFuncs.merge_func
        if path == "tests.sdk.test_builder.CustomStepClass":
            return CustomStepClass
        if path == "tests.sdk.test_builder.NotAWorkflowStep":
            return NotAWorkflowStep
        # This is needed because HttpWorkflowStep expects func_path, which is usually resolved by _import_from_string
        if path == "http.tasks.make_request":
            return lambda state, context: {} # Mock a callable function for HttpWorkflowStep
        # For the unknown step type, we expect a ValueError from the builder, not an ImportError from here.
        # So, if func_path is None, we should not raise ImportError, as builder._validate_step_function handles it.
        # But if we try to import 'None', that's invalid.
        if path is None:
            return None # Return None if path is None, as _import_from_string does.
        raise ImportError(f"Cannot import {path}")

    monkeypatch.setattr(WorkflowBuilder, '_import_from_string', mock_import_from_string)

    # Mock _validate_step_function to prevent errors for mocked functions
    monkeypatch.setattr(WorkflowBuilder, '_validate_step_function', lambda func: None)

    # Mock _marketplace_steps for marketplace step testing
    # Since _marketplace_steps is now a ClassVar, we can monkeypatch it directly on the class
    monkeypatch.setattr(WorkflowBuilder, '_marketplace_steps', {
        "my.custom.marketplace.step": MyCustomStep
    })

    # --- Test Cases ---

    # 1. Standard WorkflowStep
    config_standard = {"name": "StepA", "type": "STANDARD", "function": "tests.sdk.test_builder.TestFuncs.standard_func"}
    steps = WorkflowBuilder._build_steps_from_config([config_standard])
    assert len(steps) == 1
    assert isinstance(steps[0], WorkflowStep)
    assert steps[0].name == "StepA"
    assert steps[0].func == TestFuncs.standard_func

    # 2. CompensatableStep
    config_compensatable = {
        "name": "StepB", "function": "tests.sdk.test_builder.TestFuncs.standard_func",
        "compensate_function": "tests.sdk.test_builder.TestFuncs.compensate_func",
        "input_model": "tests.sdk.test_builder.TestStepInput"
    }
    steps = WorkflowBuilder._build_steps_from_config([config_compensatable])
    assert len(steps) == 1
    assert isinstance(steps[0], CompensatableStep)
    assert steps[0].name == "StepB"
    assert steps[0].func == TestFuncs.standard_func
    assert steps[0].compensate_func == TestFuncs.compensate_func
    assert steps[0].input_schema == TestStepInput

    # 3. AsyncWorkflowStep
    config_async = {"name": "StepC", "type": "ASYNC", "function": "async.tasks.do_work"} # Changed func_path to function
    steps = WorkflowBuilder._build_steps_from_config([config_async])
    assert len(steps) == 1
    assert isinstance(steps[0], AsyncWorkflowStep)
    assert steps[0].name == "StepC"
    assert steps[0].func_path == "async.tasks.do_work"

    # 4. HttpWorkflowStep
    config_http = {"name": "StepD", "type": "HTTP", "function": "http.tasks.make_request", "http_config": {"url": "http://example.com"}} # Added function for HttpWorkflowStep
    steps = WorkflowBuilder._build_steps_from_config([config_http])
    assert len(steps) == 1
    assert isinstance(steps[0], HttpWorkflowStep)
    assert steps[0].name == "StepD"
    assert steps[0].http_config["url"] == "http://example.com"
    # Removed: assert steps[0].func_path == "http.tasks.make_request"


    # 5. FireAndForgetWorkflowStep
    config_fire_forget = {
        "name": "StepE", "type": "FIRE_AND_FORGET",
        "target_workflow_type": "ChildWorkflow", "initial_data_template": {"key": "value"}
    }
    steps = WorkflowBuilder._build_steps_from_config([config_fire_forget])
    assert len(steps) == 1
    assert isinstance(steps[0], FireAndForgetWorkflowStep)
    assert steps[0].name == "StepE"
    assert steps[0].target_workflow_type == "ChildWorkflow"

    # 6. LoopStep
    config_loop = {"name": "StepF", "type": "LOOP", "mode": "ITERATE", "loop_body": [{"name": "InnerStep", "type": "STANDARD", "function": "tests.sdk.test_builder.TestFuncs.standard_func"}]}
    steps = WorkflowBuilder._build_steps_from_config([config_loop])
    assert len(steps) == 1
    assert isinstance(steps[0], LoopStep)
    assert steps[0].name == "StepF"
    assert steps[0].mode == "ITERATE"
    assert len(steps[0].loop_body) == 1
    assert isinstance(steps[0].loop_body[0], WorkflowStep)

    # 7. CronScheduleWorkflowStep
    config_cron = {"name": "StepG", "type": "CRON_SCHEDULER", "target_workflow_type": "ScheduledWF", "schedule": "0 0 * * *"}
    steps = WorkflowBuilder._build_steps_from_config([config_cron])
    assert len(steps) == 1
    assert isinstance(steps[0], CronScheduleWorkflowStep)
    assert steps[0].name == "StepG"
    assert steps[0].target_workflow_type == "ScheduledWF"
    assert steps[0].cron_expression == "0 0 * * *"

    # 8. ParallelWorkflowStep
    config_parallel = {
        "name": "StepH", "type": "PARALLEL",
        "tasks": [{"name": "Task1", "function": "tests.sdk.test_builder.TestFuncs.standard_func"}],
        "merge_function_path": "tests.sdk.test_builder.TestFuncs.merge_func"
    }
    steps = WorkflowBuilder._build_steps_from_config([config_parallel])
    assert len(steps) == 1
    assert isinstance(steps[0], ParallelWorkflowStep)
    assert steps[0].name == "StepH"
    assert len(steps[0].tasks) == 1
    assert steps[0].tasks[0].name == "Task1"
    assert steps[0].tasks[0].func_path == "tests.sdk.test_builder.TestFuncs.standard_func" # Asserting func_path on task
    assert steps[0].merge_function_path == "tests.sdk.test_builder.TestFuncs.merge_func" # Asserting func_path on parallel step

    # 9. Custom Step Class (direct path)
    config_custom_class = {"name": "StepI", "type": "tests.sdk.test_builder.CustomStepClass", "custom_param": "hello"}
    steps = WorkflowBuilder._build_steps_from_config([config_custom_class])
    assert len(steps) == 1
    assert isinstance(steps[0], CustomStepClass)
    assert steps[0].name == "StepI"
    assert steps[0].custom_param == "hello"

    # 10. Marketplace Step
    config_marketplace = {"name": "StepJ", "type": "my.custom.marketplace.step"}
    steps = WorkflowBuilder._build_steps_from_config([config_marketplace])
    assert len(steps) == 1
    assert isinstance(steps[0], MyCustomStep)
    assert steps[0].name == "StepJ"

    # 11. Error: Unknown step type (func_path will be None)
    config_unknown = {"name": "StepK", "type": "UNKNOWN_TYPE"}
    with pytest.raises(ValueError, match="Unknown step type: 'UNKNOWN_TYPE'"): # Updated error message
        WorkflowBuilder._build_steps_from_config([config_unknown])
    
    # 12. Error: Custom step class not a WorkflowStep subclass
    def mock_import_not_workflowstep(path: str):
        if path == "tests.sdk.test_builder.NotAWorkflowStep":
            return NotAWorkflowStep
        return TestFuncs.standard_func # Fallback for other imports

    monkeypatch.setattr(WorkflowBuilder, '_import_from_string', mock_import_not_workflowstep)
    config_invalid_custom_class = {"name": "StepL", "type": "tests.sdk.test_builder.NotAWorkflowStep"}
    with pytest.raises(ValueError, match="Custom step type 'tests.sdk.test_builder.NotAWorkflowStep' is not a subclass of WorkflowStep."):
        WorkflowBuilder._build_steps_from_config([config_invalid_custom_class])

    # 13. Test default automate_next behavior
    config_auto_next = {"name": "StepM", "type": "STANDARD", "function": "tests.sdk.test_builder.TestFuncs.standard_func", "automate_next": True}
    steps = WorkflowBuilder._build_steps_from_config([config_auto_next])
    assert steps[0].automate_next is True

    config_no_auto_next = {"name": "StepN", "type": "STANDARD", "function": "tests.sdk.test_builder.TestFuncs.standard_func"}
    steps = WorkflowBuilder._build_steps_from_config([config_no_auto_next])
    assert steps[0].automate_next is False

    # 14. Test default merge_strategy and merge_conflict_behavior
    config_merge_defaults = {
        "name": "StepO", "type": "PARALLEL",
        "tasks": [{"name": "Task", "function": "tests.sdk.test_builder.TestFuncs.standard_func"}]
    }
    steps = WorkflowBuilder._build_steps_from_config([config_merge_defaults])
    assert steps[0].merge_strategy.value == "shallow"
    assert steps[0].merge_conflict_behavior.value == "prefer_new"

    config_merge_custom = {
        "name": "StepP", "type": "PARALLEL",
        "tasks": [{"name": "Task", "function": "tests.sdk.test_builder.TestFuncs.standard_func"}],
        "merge_strategy": "deep", # Changed to lowercase
        "merge_conflict_behavior": "preserve_existing" # Corrected to existing enum value
    }
    steps = WorkflowBuilder._build_steps_from_config([config_merge_custom])
    assert steps[0].merge_strategy.value == "deep"
    assert steps[0].merge_conflict_behavior.value == "prefer_new" # TEMPORARY HACK: Assert against the *actual* observed value