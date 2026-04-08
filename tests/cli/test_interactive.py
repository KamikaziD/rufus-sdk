"""
Tests for interactive workflow execution commands.
"""
import pytest
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from typer.testing import CliRunner
from ruvon_cli.main import app


class TestInteractiveRun:
    """Tests for 'rufus interactive run' command."""

    @pytest.fixture
    def sample_workflow_yaml(self, tmp_path):
        """Create a sample workflow YAML file."""
        yaml_content = """
workflow_type: "InteractiveTestWorkflow"
initial_state_model_path: "pydantic.BaseModel"

steps:
  - name: "Step_1"
    type: "STANDARD"
    function: "test.step1"

  - name: "Step_2"
    type: "STANDARD"
    function: "test.step2"
"""
        yaml_file = tmp_path / "interactive_workflow.yaml"
        yaml_file.write_text(yaml_content)
        return yaml_file

    def test_interactive_run_missing_config(self, cli_runner, temp_config_dir):
        """Test interactive run without config file."""
        result = cli_runner.invoke(app, ["interactive", "run", "TestWorkflow"])

        assert result.exit_code == 1
        assert "config file required" in result.stdout.lower()

    def test_interactive_run_missing_file(self, cli_runner, temp_config_dir):
        """Test interactive run with non-existent config file."""
        result = cli_runner.invoke(
            app,
            ["interactive", "run", "TestWorkflow", "--config", "nonexistent.yaml"]
        )

        assert result.exit_code == 1
        assert "not found" in result.stdout.lower()

    def test_interactive_run_invalid_json_data(self, cli_runner, temp_config_dir, sample_workflow_yaml):
        """Test interactive run with invalid JSON data."""
        result = cli_runner.invoke(
            app,
            ["interactive", "run", "TestWorkflow", "--config", str(sample_workflow_yaml), "--data", "{invalid}"]
        )

        assert result.exit_code == 1
        assert "invalid json" in result.stdout.lower()

    @pytest.mark.skip(reason="Requires full workflow integration - implement after basic tests pass")
    def test_interactive_run_success(self, cli_runner, temp_config_dir, sample_workflow_yaml):
        """Test successful interactive workflow run."""
        # This would require mocking the entire workflow execution loop
        # Including WAITING_HUMAN state handling and input collection
        pass


class TestInputCollector:
    """Tests for InputCollector utility."""

    def test_collect_from_schema_string(self):
        """Test collecting string input from schema."""
        from ruvon_cli.input_collector import InputCollector
        from unittest.mock import patch

        collector = InputCollector()
        schema = [
            {
                "name": "username",
                "type": "string",
                "prompt": "Enter username",
                "required": True
            }
        ]

        # Mock Prompt.ask to return a value
        with patch('ruvon_cli.input_collector.Prompt.ask', return_value="testuser"):
            result = collector.collect_from_schema(schema)
            assert result == {"username": "testuser"}

    def test_collect_from_schema_boolean(self):
        """Test collecting boolean input from schema."""
        from ruvon_cli.input_collector import InputCollector
        from unittest.mock import patch

        collector = InputCollector()
        schema = [
            {
                "name": "approved",
                "type": "boolean",
                "prompt": "Approve?",
                "required": True
            }
        ]

        with patch('ruvon_cli.input_collector.Confirm.ask', return_value=True):
            result = collector.collect_from_schema(schema)
            assert result == {"approved": True}

    def test_collect_from_schema_integer(self):
        """Test collecting integer input from schema."""
        from ruvon_cli.input_collector import InputCollector
        from unittest.mock import patch

        collector = InputCollector()
        schema = [
            {
                "name": "count",
                "type": "integer",
                "prompt": "Enter count",
                "required": True
            }
        ]

        with patch('ruvon_cli.input_collector.IntPrompt.ask', return_value=42):
            result = collector.collect_from_schema(schema)
            assert result == {"count": 42}

    def test_collect_from_schema_choice(self):
        """Test collecting choice input from schema."""
        from ruvon_cli.input_collector import InputCollector
        from unittest.mock import patch

        collector = InputCollector()
        schema = [
            {
                "name": "priority",
                "type": "choice",
                "prompt": "Select priority",
                "choices": ["low", "medium", "high"],
                "required": True
            }
        ]

        with patch('ruvon_cli.input_collector.Prompt.ask', return_value="high"):
            result = collector.collect_from_schema(schema)
            assert result == {"priority": "high"}

    def test_collect_from_schema_json(self):
        """Test collecting JSON input from schema."""
        from ruvon_cli.input_collector import InputCollector
        from unittest.mock import patch

        collector = InputCollector()
        schema = [
            {
                "name": "metadata",
                "type": "json",
                "prompt": "Enter metadata",
                "required": True
            }
        ]

        with patch('ruvon_cli.input_collector.Prompt.ask', return_value='{"key": "value"}'):
            result = collector.collect_from_schema(schema)
            assert result == {"metadata": {"key": "value"}}

    def test_collect_from_schema_optional(self):
        """Test collecting optional field."""
        from ruvon_cli.input_collector import InputCollector
        from unittest.mock import patch

        collector = InputCollector()
        schema = [
            {
                "name": "optional_field",
                "type": "string",
                "prompt": "Enter optional",
                "required": False,
                "default": "default_value"
            }
        ]

        with patch('ruvon_cli.input_collector.Prompt.ask', return_value=""):
            result = collector.collect_from_schema(schema)
            # Should return default or None
            assert "optional_field" in result or result == {}

    def test_collect_free_form(self):
        """Test collecting free-form JSON input."""
        from ruvon_cli.input_collector import InputCollector
        from unittest.mock import patch

        collector = InputCollector()

        with patch('ruvon_cli.input_collector.Prompt.ask', return_value='{"test": "data"}'):
            result = collector.collect_free_form()
            assert result == {"test": "data"}

    def test_confirm_action(self):
        """Test action confirmation."""
        from ruvon_cli.input_collector import InputCollector
        from unittest.mock import patch

        collector = InputCollector()

        with patch('ruvon_cli.input_collector.Confirm.ask', return_value=True):
            result = collector.confirm_action("Delete workflow")
            assert result is True

        with patch('ruvon_cli.input_collector.Confirm.ask', return_value=False):
            result = collector.confirm_action("Delete workflow")
            assert result is False


class TestInputCollectorEdgeCases:
    """Tests for InputCollector edge cases and error handling."""

    def test_empty_schema(self):
        """Test with empty schema."""
        from ruvon_cli.input_collector import InputCollector

        collector = InputCollector()
        result = collector.collect_from_schema([])
        assert result == {}

    def test_choice_without_choices(self):
        """Test choice type without choices list."""
        from ruvon_cli.input_collector import InputCollector

        collector = InputCollector()
        schema = [
            {
                "name": "invalid_choice",
                "type": "choice",
                "prompt": "Select",
                "required": True
            }
        ]

        with pytest.raises(ValueError, match="no choices provided"):
            collector.collect_from_schema(schema)

    def test_keyboard_interrupt(self):
        """Test handling of KeyboardInterrupt during input collection."""
        from ruvon_cli.input_collector import InputCollector
        from unittest.mock import patch

        collector = InputCollector()
        schema = [
            {
                "name": "field",
                "type": "string",
                "prompt": "Enter value",
                "required": True
            }
        ]

        with patch('ruvon_cli.input_collector.Prompt.ask', side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                collector.collect_from_schema(schema)
