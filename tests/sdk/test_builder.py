import importlib
import pytest
from unittest.mock import MagicMock, patch
from rufus.builder import WorkflowBuilder

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
        }
    }
    builder = WorkflowBuilder(workflow_registry={}, expression_evaluator_cls=MagicMock(), template_engine_cls=MagicMock())
    processed_data = builder._apply_env_variables_to_dict(data)
    assert processed_data["key1"] == "value1"
    assert processed_data["key2"] == "my_value"
    assert processed_data["key3"] == "default_value"
    assert processed_data["nested"]["key4"] == "my_value"
    monkeypatch.delenv("MY_TEST_VAR")
    processed_data = builder._apply_env_variables_to_dict(data)
    assert processed_data["key2"] == "${MY_TEST_VAR}"

def test_get_workflow_config(monkeypatch):
    """
    Tests the get_workflow_config method.
    """
    monkeypatch.setenv("MY_TEST_VAR", "my_value")
    workflow_registry = {
        "test_workflow": {
            "param1": "${MY_TEST_VAR}",
            "param2": "static_value"
        }
    }
    mock_template_engine_cls = MagicMock()
    mock_template_engine_cls.return_value.render_string_template.side_effect = lambda template, context: template

    builder = WorkflowBuilder(
        workflow_registry=workflow_registry,
        expression_evaluator_cls=MagicMock(),
        template_engine_cls=mock_template_engine_cls
    )

    # First, process environment variables
    builder.workflow_registry = builder._apply_env_variables_to_dict(builder.workflow_registry)

    config = builder.get_workflow_config("test_workflow")
    assert config["param1"] == "my_value"
    assert config["param2"] == "static_value"



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
    assert isinstance(workflow.state, MyStateModel)

    # Clean up the dummy module
    import os
    os.remove("tests/sdk/temp_test_module.py")
