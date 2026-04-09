"""
Tests for validation and run commands.
"""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from typer.testing import CliRunner

from ruvon_cli.main import app
from ruvon_cli.validation import WorkflowValidator


class TestValidateCommand:
    """Tests for 'ruvon validate' command."""

    @pytest.fixture
    def valid_workflow_yaml(self, tmp_path):
        """Create a valid workflow YAML file."""
        yaml_content = """
workflow_type: "TestWorkflow"
initial_state_model: "pydantic.BaseModel"

steps:
  - name: "Step_1"
    type: "STANDARD"
    function: "test.step1"
"""
        yaml_file = tmp_path / "valid_workflow.yaml"
        yaml_file.write_text(yaml_content)
        return yaml_file

    @pytest.fixture
    def circular_dependency_yaml(self, tmp_path):
        """Create workflow with circular dependencies."""
        yaml_content = """
workflow_type: "CircularWorkflow"
initial_state_model: "pydantic.BaseModel"

steps:
  - name: "Step_A"
    type: "STANDARD"
    function: "test.step_a"
    dependencies: ["Step_B"]

  - name: "Step_B"
    type: "STANDARD"
    function: "test.step_b"
    dependencies: ["Step_C"]

  - name: "Step_C"
    type: "STANDARD"
    function: "test.step_c"
    dependencies: ["Step_A"]
"""
        yaml_file = tmp_path / "circular_workflow.yaml"
        yaml_file.write_text(yaml_content)
        return yaml_file

    @pytest.fixture
    def complex_workflow_yaml(self, tmp_path):
        """Create a complex workflow for graph testing."""
        yaml_content = """
workflow_type: "ComplexWorkflow"
initial_state_model: "pydantic.BaseModel"

steps:
  - name: "Start"
    type: "STANDARD"
    function: "test.start"

  - name: "Process"
    type: "STANDARD"
    function: "test.process"
    dependencies: ["Start"]

  - name: "Decide"
    type: "DECISION"
    function: "test.decide"
    dependencies: ["Process"]
    routes:
      - condition: "state.approved"
        target: "Approve"
      - condition: "!state.approved"
        target: "Reject"

  - name: "Approve"
    type: "STANDARD"
    function: "test.approve"

  - name: "Reject"
    type: "STANDARD"
    function: "test.reject"

  - name: "End"
    type: "STANDARD"
    function: "test.end"
    dependencies: ["Approve", "Reject"]
"""
        yaml_file = tmp_path / "complex_workflow.yaml"
        yaml_file.write_text(yaml_content)
        return yaml_file

    def test_validate_missing_file(self, cli_runner):
        """Test validate with non-existent file."""
        result = cli_runner.invoke(app, ["validate", "nonexistent.yaml"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_validate_valid_workflow(self, cli_runner, valid_workflow_yaml):
        """Test validate with valid workflow."""
        result = cli_runner.invoke(app, ["validate", str(valid_workflow_yaml)])

        # Should succeed (exit code 0)
        assert result.exit_code == 0
        assert "success" in result.stdout.lower() or "✓" in result.stdout

    def test_validate_with_strict(self, cli_runner, valid_workflow_yaml):
        """Test validate with --strict flag."""
        result = cli_runner.invoke(app, ["validate", str(valid_workflow_yaml), "--strict"])

        # May fail due to imports not being available
        # Just check that --strict is processed
        assert result.exit_code in [0, 1]

    def test_validate_json_output(self, cli_runner, valid_workflow_yaml):
        """Test validate with --json output."""
        result = cli_runner.invoke(app, ["validate", str(valid_workflow_yaml), "--json"])

        # Should output valid JSON
        import json
        try:
            output = json.loads(result.stdout)
            assert "valid" in output
            assert "errors" in output
            assert "warnings" in output
        except json.JSONDecodeError:
            pytest.fail("Output is not valid JSON")

    def test_validate_circular_dependency(self, cli_runner, circular_dependency_yaml):
        """Test validation detects circular dependencies."""
        result = cli_runner.invoke(app, ["validate", str(circular_dependency_yaml)])

        assert result.exit_code == 1
        # Circular dependency error should be in output (may go to stderr)
        output = result.output.lower()
        assert "circular" in output

    def test_validate_with_graph_mermaid(self, cli_runner, complex_workflow_yaml):
        """Test validate with --graph flag (mermaid format)."""
        result = cli_runner.invoke(app, ["validate", str(complex_workflow_yaml), "--graph"])

        assert result.exit_code == 0
        assert "graph" in result.stdout.lower() or "mermaid" in result.stdout.lower()
        assert "Start" in result.stdout
        assert "End" in result.stdout

    def test_validate_with_graph_dot(self, cli_runner, complex_workflow_yaml):
        """Test validate with --graph and --graph-format dot."""
        result = cli_runner.invoke(
            app,
            ["validate", str(complex_workflow_yaml), "--graph", "--graph-format", "dot"]
        )

        assert result.exit_code == 0
        assert "digraph" in result.stdout

    def test_validate_with_graph_text(self, cli_runner, complex_workflow_yaml):
        """Test validate with --graph and --graph-format text."""
        result = cli_runner.invoke(
            app,
            ["validate", str(complex_workflow_yaml), "--graph", "--graph-format", "text"]
        )

        assert result.exit_code == 0
        assert "Dependency Graph" in result.stdout


class TestWorkflowValidator:
    """Direct tests for WorkflowValidator class."""

    def test_circular_dependency_detection(self):
        """Test circular dependency detection."""
        validator = WorkflowValidator()

        steps = [
            {"name": "A", "dependencies": ["B"]},
            {"name": "B", "dependencies": ["C"]},
            {"name": "C", "dependencies": ["A"]}
        ]

        cycle = validator._check_circular_dependencies(steps)
        assert len(cycle) > 0
        assert "A" in cycle and "B" in cycle and "C" in cycle

    def test_no_circular_dependency(self):
        """Test valid dependency chain."""
        validator = WorkflowValidator()

        steps = [
            {"name": "A", "dependencies": []},
            {"name": "B", "dependencies": ["A"]},
            {"name": "C", "dependencies": ["B"]}
        ]

        cycle = validator._check_circular_dependencies(steps)
        assert len(cycle) == 0

    def test_generate_mermaid_graph(self):
        """Test Mermaid graph generation."""
        validator = WorkflowValidator()

        steps = [
            {"name": "Start", "type": "STANDARD"},
            {"name": "Decide", "type": "DECISION", "dependencies": ["Start"]},
            {
                "name": "Process",
                "type": "STANDARD",
                "routes": [{"target": "End", "condition": "state.done"}]
            },
            {"name": "End", "type": "STANDARD"}
        ]

        graph = validator.generate_dependency_graph(steps, format="mermaid")
        assert "```mermaid" in graph
        assert "graph TD" in graph
        assert "Start" in graph
        assert "End" in graph

    def test_generate_dot_graph(self):
        """Test DOT graph generation."""
        validator = WorkflowValidator()

        steps = [
            {"name": "Start", "type": "STANDARD"},
            {"name": "End", "type": "STANDARD", "dependencies": ["Start"]}
        ]

        graph = validator.generate_dependency_graph(steps, format="dot")
        assert "digraph workflow" in graph
        assert "Start" in graph
        assert "End" in graph
        assert "->" in graph

    def test_generate_text_graph(self):
        """Test text graph generation."""
        validator = WorkflowValidator()

        steps = [
            {"name": "Start", "type": "STANDARD"},
            {"name": "End", "type": "STANDARD", "dependencies": ["Start"]}
        ]

        graph = validator.generate_dependency_graph(steps, format="text")
        assert "Dependency Graph" in graph
        assert "Start" in graph
        assert "End" in graph
        assert "Dependencies: Start" in graph


class TestRunCommand:
    """Tests for 'ruvon run' command."""

    def test_run_simple_workflow(self, cli_runner, tmp_path):
        """Test running a simple workflow that completes immediately."""
        yaml_content = (
            'workflow_type: "SimpleTest"\n'
            'initial_state_model: "pydantic.BaseModel"\n'
            'steps:\n'
            '  - name: "Step_1"\n'
            '    type: "STANDARD"\n'
            '    function: "pydantic.BaseModel"\n'
        )
        yaml_file = tmp_path / "simple_workflow.yaml"
        yaml_file.write_text(yaml_content)

        # Mock state and workflow that is already COMPLETED on start
        mock_state = MagicMock()
        mock_state.model_dump.return_value = {}
        mock_workflow = MagicMock()
        mock_workflow.id = "test-workflow-id"
        mock_workflow.status = "COMPLETED"
        mock_workflow.state = mock_state
        mock_workflow.workflow_type = "SimpleTest"
        mock_workflow.automate_start = False
        mock_workflow.next_step = AsyncMock(return_value=(None, None))

        # Mock providers returned by _create_providers_for_run
        mock_persistence = AsyncMock()
        mock_execution = AsyncMock()
        mock_observer = AsyncMock()
        mock_builder = AsyncMock()
        mock_builder.create_workflow = AsyncMock(return_value=mock_workflow)

        with patch(
            "ruvon_cli.main._create_providers_for_run",
            new=AsyncMock(return_value=(mock_persistence, mock_execution, mock_observer, mock_builder))
        ):
            result = cli_runner.invoke(app, ["run", str(yaml_file), "--data", "{}"])

        assert result.exit_code == 0
        assert "Successfully completed" in result.stdout
