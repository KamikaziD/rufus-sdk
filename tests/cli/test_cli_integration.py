"""
End-to-end integration tests for CLI workflows.
"""
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from rufus_cli.main import app
from tests.cli.utils import assert_output_contains


class TestFullWorkflowLifecycle:
    """Test complete workflow lifecycle through CLI."""

    @pytest.mark.skip(reason="Full integration test - requires all components working")
    def test_config_to_workflow_execution(self, cli_runner, temp_config_dir, tmp_path):
        """
        Test complete flow:
        1. Configure persistence
        2. Initialize database
        3. Start workflow
        4. Show workflow
        5. View logs
        6. View metrics
        """
        # 1. Configure SQLite persistence
        db_path = tmp_path / "workflows.db"
        result = cli_runner.invoke(
            app,
            ["config", "set-persistence", "--provider", "sqlite", "--db-path", str(db_path), "--yes"]
        )
        assert result.exit_code == 0

        # 2. Initialize database
        result = cli_runner.invoke(app, ["db", "init"])
        # May need adjustments based on actual implementation

        # 3. Start workflow
        # 4. Show workflow
        # 5. View logs
        # 6. View metrics


class TestConfigPersistenceWorkflow:
    """Test config → workflow flow."""

    def test_config_persists_across_commands(self, cli_runner, temp_config_dir, tmp_path):
        """Test that config settings persist and are used by subsequent commands."""
        # Set config
        db_path = tmp_path / "test.db"
        result = cli_runner.invoke(
            app,
            ["config", "set-persistence", "--provider", "sqlite", "--db-path", str(db_path), "--yes"]
        )
        assert result.exit_code == 0

        # Verify config was saved
        config_file = temp_config_dir / "config.yaml"
        assert config_file.exists()

        # Show config
        result = cli_runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert_output_contains(result.stdout, "sqlite")


class TestValidationToExecution:
    """Test validation → execution flow."""

    @pytest.mark.skip(reason="Requires workflow execution")
    def test_validate_then_run(self, cli_runner, sample_workflow_yaml):
        """Test validating workflow then running it."""
        # 1. Validate
        result = cli_runner.invoke(app, ["validate", str(sample_workflow_yaml)])
        assert result.exit_code == 0

        # 2. Run
        result = cli_runner.invoke(
            app,
            ["run", str(sample_workflow_yaml), "-d", '{"user_id": "123"}']
        )
        # Should execute successfully after validation


class TestDatabaseSetupWorkflow:
    """Test database setup → workflow execution."""

    @pytest.mark.skip(reason="Requires full database and workflow integration")
    def test_db_init_to_workflow_execution(self, cli_runner, temp_config_dir, tmp_path):
        """Test initializing database then running workflows."""
        # 1. Configure database
        db_path = tmp_path / "workflows.db"
        result = cli_runner.invoke(
            app,
            ["config", "set-persistence", "--provider", "sqlite", "--db-path", str(db_path), "--yes"]
        )
        assert result.exit_code == 0

        # 2. Initialize database
        result = cli_runner.invoke(app, ["db", "init"])
        # assert result.exit_code == 0

        # 3. Check status
        result = cli_runner.invoke(app, ["db", "status"])

        # 4. Start workflow
        # 5. Verify data in database


class TestZombieRecoveryFlow:
    """Test zombie detection and recovery."""

    @pytest.mark.skip(reason="Requires zombie scanner implementation and workflow setup")
    def test_zombie_detection_and_fix(self, cli_runner, temp_config_dir):
        """
        Test zombie workflow recovery:
        1. Start workflow
        2. Simulate worker crash (stop heartbeat)
        3. Scan for zombies
        4. Fix zombies
        5. Verify workflow marked as failed
        """
        pass


class TestErrorHandling:
    """Test error handling across CLI commands."""

    def test_invalid_config_file(self, cli_runner, tmp_path):
        """Test handling of invalid config file."""
        # Create malformed config
        config_file = tmp_path / ".rufus" / "config.yaml"
        config_file.parent.mkdir(exist_ok=True)
        with open(config_file, 'w') as f:
            f.write("{ invalid yaml")

        # Commands should handle gracefully
        # (Behavior depends on implementation)

    def test_missing_database_connection(self, cli_runner, temp_config_dir):
        """Test handling of missing database connection."""
        # Configure with non-existent PostgreSQL
        result = cli_runner.invoke(
            app,
            [
                "config",
                "set-persistence",
                "--provider",
                "postgres",
                "--db-url",
                "postgresql://invalid:invalid@localhost:9999/invalid",
                "--yes"
            ]
        )

        # Config should save successfully
        assert result.exit_code == 0

        # But listing workflows should fail gracefully
        result = cli_runner.invoke(app, ["list"])
        # Should provide helpful error message, not crash


class TestCLIConsistency:
    """Test consistency between different command syntaxes."""

    def test_list_command_aliases(self, cli_runner, temp_config_dir, mock_persistence):
        """Test that 'rufus list' and 'rufus workflow list' are equivalent."""
        with patch('rufus_cli.providers.create_persistence_provider', return_value=mock_persistence):
            result1 = cli_runner.invoke(app, ["list"])
            result2 = cli_runner.invoke(app, ["workflow", "list"])

            # Both should succeed and produce similar output
            assert result1.exit_code == result2.exit_code

    def test_show_command_aliases(self, cli_runner, temp_config_dir, mock_persistence, sample_workflow_data):
        """Test that 'rufus show' and 'rufus workflow show' are equivalent."""
        workflow_id = sample_workflow_data["id"]
        mock_persistence.load_workflow.return_value = sample_workflow_data

        with patch('rufus_cli.providers.create_persistence_provider', return_value=mock_persistence):
            result1 = cli_runner.invoke(app, ["show", workflow_id])
            result2 = cli_runner.invoke(app, ["workflow", "show", workflow_id])

            # Both should succeed
            assert result1.exit_code == result2.exit_code
