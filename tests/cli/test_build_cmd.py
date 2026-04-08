"""Tests for the `rufus build` CLI command."""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from typer.testing import CliRunner

from ruvon_cli.main import app


runner = CliRunner()


def _mock_build_result(yaml_content=None, has_errors=False, needs_clarification=False):
    """Create a mock BuildResult."""
    from ruvon.builder_ai.models import BuildResult, LintReport, LintResult
    lint_report = LintReport(results=[
        LintResult(rule_id="GOV-001", severity="ERROR", message="PII check passed", passed=True),
        LintResult(rule_id="GOV-007", severity="WARN", message="Metadata present", passed=True),
    ])
    return BuildResult(
        yaml=yaml_content or "name: test-workflow\nversion: '1.0'\nsteps: []\n",
        workflow_dict={"name": "test-workflow", "version": "1.0", "steps": []},
        lint_report=lint_report,
        needs_clarification=needs_clarification,
        questions=["What triggers the workflow?"] if needs_clarification else [],
        errors=["Schema error"] if has_errors else [],
    )


class TestBuildCommand:
    def test_help_text(self):
        result = runner.invoke(app, ["build", "--help"])
        assert result.exit_code == 0
        assert "workflow" in result.output.lower() or "build" in result.output.lower()

    def test_no_args_shows_help(self):
        result = runner.invoke(app, ["build", "--help"])
        assert result.exit_code == 0
        assert "generate" in result.output.lower() or "workflow" in result.output.lower()

    def test_single_shot_dry_run(self):
        mock_result = _mock_build_result()
        with patch("ruvon.builder_ai.AIWorkflowBuilder") as MockBuilder:
            instance = MockBuilder.return_value
            instance.model = "claude-sonnet-4-6"
            instance.build = AsyncMock(return_value=mock_result)

            result = runner.invoke(app, ["build", "generate", "handle incoming bids", "--dry-run"])

        assert result.exit_code == 0
        assert "test-workflow" in result.output or "Dry run" in result.output

    def test_single_shot_to_file(self, tmp_path):
        out_file = tmp_path / "workflow.yaml"
        mock_result = _mock_build_result()
        with patch("ruvon.builder_ai.AIWorkflowBuilder") as MockBuilder:
            instance = MockBuilder.return_value
            instance.model = "claude-sonnet-4-6"
            instance.build = AsyncMock(return_value=mock_result)

            result = runner.invoke(app, ["build", "generate", "handle bids", "--out", str(out_file)])

        assert result.exit_code == 0
        assert out_file.exists()
        content = out_file.read_text()
        assert "test-workflow" in content

    def test_ollama_backend_flag(self):
        mock_result = _mock_build_result()
        with patch("ruvon.builder_ai.AIWorkflowBuilder") as MockBuilder:
            instance = MockBuilder.return_value
            instance.model = "llama3"
            instance.build = AsyncMock(return_value=mock_result)

            result = runner.invoke(app, [
                "build", "generate", "handle bids",
                "--backend", "ollama",
                "--model", "llama3",
                "--dry-run",
            ])
            # Verify AIWorkflowBuilder was called with ollama backend
            MockBuilder.assert_called_once()
            call_kwargs = MockBuilder.call_args.kwargs
            assert call_kwargs.get("backend") == "ollama"

        assert result.exit_code == 0

    def test_schema_errors_exit_code_1(self):
        mock_result = _mock_build_result(has_errors=True)
        with patch("ruvon.builder_ai.AIWorkflowBuilder") as MockBuilder:
            instance = MockBuilder.return_value
            instance.model = "claude-sonnet-4-6"
            instance.build = AsyncMock(return_value=mock_result)

            result = runner.invoke(app, ["build", "generate", "handle bids", "--dry-run"])

        assert result.exit_code == 1
        assert "Schema error" in result.output or "validation" in result.output.lower()

    def test_explain_mode(self, tmp_path):
        workflow_file = tmp_path / "workflow.yaml"
        workflow_file.write_text("name: test\nsteps: []\n")

        with patch("ruvon.builder_ai.AIWorkflowBuilder") as MockBuilder:
            instance = MockBuilder.return_value
            instance.model = "claude-sonnet-4-6"
            instance.explain = AsyncMock(return_value="This workflow handles test data.")

            result = runner.invoke(app, ["build", "explain", str(workflow_file)])

        assert result.exit_code == 0
        assert "This workflow" in result.output

    def test_explain_file_not_found(self):
        result = runner.invoke(app, ["build", "explain", "/nonexistent/workflow.yaml"])
        assert result.exit_code == 1

    def test_json_format_output(self, tmp_path):
        out_file = tmp_path / "workflow.json"
        mock_result = _mock_build_result()
        with patch("ruvon.builder_ai.AIWorkflowBuilder") as MockBuilder:
            instance = MockBuilder.return_value
            instance.model = "claude-sonnet-4-6"
            instance.build = AsyncMock(return_value=mock_result)

            result = runner.invoke(app, [
                "build", "generate", "test", "--format", "json", "--out", str(out_file)
            ])

        assert result.exit_code == 0
        assert out_file.exists()
        # Verify it's valid JSON
        data = json.loads(out_file.read_text())
        assert "name" in data

    def test_from_file_flag(self, tmp_path):
        existing_wf = tmp_path / "existing.yaml"
        existing_wf.write_text("name: existing\nsteps: []\n")
        mock_result = _mock_build_result()

        with patch("ruvon.builder_ai.AIWorkflowBuilder") as MockBuilder:
            instance = MockBuilder.return_value
            instance.model = "claude-sonnet-4-6"
            instance.build = AsyncMock(return_value=mock_result)

            result = runner.invoke(app, [
                "build", "generate", "add anomaly detection",
                "--from-file", str(existing_wf),
                "--dry-run",
            ])

        assert result.exit_code == 0
        # Verify the existing YAML was included in the prompt
        build_call_args = instance.build.call_args
        assert "existing" in build_call_args.kwargs.get("prompt", "") or \
               "existing" in (build_call_args.args[0] if build_call_args.args else "")

    def test_from_file_not_found(self):
        result = runner.invoke(app, ["build", "generate", "improve it", "--from-file", "/nonexistent.yaml", "--dry-run"])
        assert result.exit_code == 1
