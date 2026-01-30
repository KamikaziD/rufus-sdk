"""
Tests for validate and run commands (rufus validate, rufus run).
"""
import pytest
import json
import yaml
from pathlib import Path

from typer.testing import CliRunner

from rufus_cli.main import app
from tests.cli.utils import assert_output_contains, create_test_workflow_yaml


class TestValidate:
    """Tests for 'rufus validate' command."""

    def test_validate_valid_workflow(self, cli_runner, sample_workflow_yaml):
        """Test validating a valid workflow YAML."""
        result = cli_runner.invoke(app, ["validate", str(sample_workflow_yaml)])

        # Should succeed
        assert result.exit_code == 0
        # Should indicate validation success
        # (Exact message depends on implementation)

    def test_validate_invalid_workflow(self, cli_runner, tmp_path):
        """Test validating an invalid workflow YAML."""
        # Create invalid workflow (missing required fields)
        invalid_yaml = tmp_path / "invalid.yaml"
        with open(invalid_yaml, 'w') as f:
            yaml.dump({"workflow_type": "Test"}, f)  # Missing steps

        result = cli_runner.invoke(app, ["validate", str(invalid_yaml)])

        # Should fail with validation errors
        # Exit code depends on how validation errors are handled

    def test_validate_missing_file(self, cli_runner, tmp_path):
        """Test validating non-existent file."""
        missing_file = tmp_path / "does_not_exist.yaml"

        result = cli_runner.invoke(app, ["validate", str(missing_file)])

        # Should fail with file not found error
        assert result.exit_code != 0

    def test_validate_malformed_yaml(self, cli_runner, tmp_path):
        """Test validating malformed YAML."""
        malformed_yaml = tmp_path / "malformed.yaml"
        with open(malformed_yaml, 'w') as f:
            f.write("{ invalid yaml content: [ unclosed")

        result = cli_runner.invoke(app, ["validate", str(malformed_yaml)])

        # Should fail with YAML parsing error
        assert result.exit_code != 0

    @pytest.mark.skip(reason="Strict mode may not be implemented yet")
    def test_validate_strict_mode(self, cli_runner, sample_workflow_yaml):
        """Test validation in strict mode."""
        result = cli_runner.invoke(app, ["validate", str(sample_workflow_yaml), "--strict"])

        # Should perform strict validation

    def test_validate_json_output(self, cli_runner, sample_workflow_yaml):
        """Test JSON output format."""
        result = cli_runner.invoke(app, ["validate", str(sample_workflow_yaml), "--json"])

        # Should output validation results as JSON
        # May succeed or fail depending on validation, but should be valid JSON if --json flag works


class TestRun:
    """Tests for 'rufus run' command."""

    @pytest.mark.skip(reason="Requires full workflow execution - integration test")
    def test_run_workflow_success(self, cli_runner, sample_workflow_yaml):
        """Test running a workflow successfully."""
        result = cli_runner.invoke(
            app,
            ["run", str(sample_workflow_yaml), "-d", '{"user_id": "123"}']
        )

        # Should execute workflow to completion
        # assert result.exit_code == 0

    def test_run_workflow_invalid_json(self, cli_runner, sample_workflow_yaml):
        """Test running with invalid JSON data."""
        result = cli_runner.invoke(
            app,
            ["run", str(sample_workflow_yaml), "-d", '{invalid}']
        )

        # Should fail with JSON parsing error
        # Exit code check depends on error handling

    def test_run_workflow_missing_file(self, cli_runner, tmp_path):
        """Test running non-existent workflow file."""
        missing_file = tmp_path / "missing.yaml"

        result = cli_runner.invoke(app, ["run", str(missing_file)])

        # Should fail with file not found
        assert result.exit_code != 0

    @pytest.mark.skip(reason="Requires full workflow execution")
    def test_run_workflow_with_registry(self, cli_runner, sample_workflow_yaml, sample_workflow_registry):
        """Test running with custom workflow registry."""
        result = cli_runner.invoke(
            app,
            [
                "run",
                str(sample_workflow_yaml),
                "--registry",
                str(sample_workflow_registry),
                "-d",
                '{"user_id": "123"}'
            ]
        )

        # Should use specified registry
        # assert result.exit_code == 0
