"""
Tests for the quickstart example.
"""
import pytest
import subprocess
import sys
from pathlib import Path

pytestmark = pytest.mark.skip(reason="quickstart example files not yet created")


class TestQuickstartExample:
    """Tests for examples/quickstart/."""

    def test_quickstart_runs_successfully(self):
        """Test that quickstart example runs without errors."""
        quickstart_dir = Path(__file__).parent.parent.parent / "examples" / "quickstart"
        assert quickstart_dir.exists(), f"Quickstart directory not found: {quickstart_dir}"

        run_script = quickstart_dir / "run_quickstart.py"
        assert run_script.exists(), f"Run script not found: {run_script}"

        # Run the quickstart example
        result = subprocess.run(
            [sys.executable, "run_quickstart.py"],
            cwd=quickstart_dir,
            capture_output=True,
            text=True,
            timeout=30
        )

        # Check exit code
        assert result.returncode == 0, f"Quickstart failed with error:\n{result.stderr}"

        # Check expected output
        assert "Ruvon SDK Quickstart Example" in result.stdout
        assert "Workflow Complete!" in result.stdout
        assert ">>> Hello, World! <<<" in result.stdout
        assert "✅ Quickstart example completed successfully!" in result.stdout

    def test_quickstart_generates_greeting(self):
        """Test that quickstart generates the expected greeting."""
        quickstart_dir = Path(__file__).parent.parent.parent / "examples" / "quickstart"

        result = subprocess.run(
            [sys.executable, "run_quickstart.py"],
            cwd=quickstart_dir,
            capture_output=True,
            text=True,
            timeout=30
        )

        assert result.returncode == 0

        # Verify workflow execution details
        assert "Generate_Greeting" in result.stdout
        assert "Format_Output" in result.stdout
        assert "Hello, World!" in result.stdout

    def test_quickstart_workflow_completes(self):
        """Test that quickstart workflow reaches COMPLETED status."""
        quickstart_dir = Path(__file__).parent.parent.parent / "examples" / "quickstart"

        result = subprocess.run(
            [sys.executable, "run_quickstart.py"],
            cwd=quickstart_dir,
            capture_output=True,
            text=True,
            timeout=30
        )

        assert result.returncode == 0
        assert "Final Status: COMPLETED" in result.stdout

    def test_quickstart_files_exist(self):
        """Test that all required quickstart files exist."""
        quickstart_dir = Path(__file__).parent.parent.parent / "examples" / "quickstart"

        required_files = [
            "run_quickstart.py",
            "state_models.py",
            "steps.py",
            "greeting_workflow.yaml",
            "workflow_registry.yaml",
            "README.md"
        ]

        for filename in required_files:
            file_path = quickstart_dir / filename
            assert file_path.exists(), f"Required file missing: {filename}"

    def test_quickstart_yaml_valid(self):
        """Test that quickstart YAML files are valid."""
        import yaml

        quickstart_dir = Path(__file__).parent.parent.parent / "examples" / "quickstart"

        # Load and validate workflow YAML
        workflow_yaml = quickstart_dir / "greeting_workflow.yaml"
        with open(workflow_yaml) as f:
            workflow_config = yaml.safe_load(f)

        assert "workflow_type" in workflow_config
        assert workflow_config["workflow_type"] == "GreetingWorkflow"
        assert "steps" in workflow_config
        assert len(workflow_config["steps"]) > 0

        # Load and validate registry YAML
        registry_yaml = quickstart_dir / "workflow_registry.yaml"
        with open(registry_yaml) as f:
            registry_config = yaml.safe_load(f)

        assert "workflows" in registry_config
        assert len(registry_config["workflows"]) > 0
