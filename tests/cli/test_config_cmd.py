"""
Tests for config commands (rufus config *).
"""
import pytest
import json
import yaml
from pathlib import Path
from typer.testing import CliRunner

from rufus_cli.main import app
from tests.cli.utils import assert_output_contains


class TestConfigShow:
    """Tests for 'rufus config show' command."""

    def test_config_show_default(self, cli_runner, temp_config_dir):
        """Test showing default configuration when no config file exists."""
        result = cli_runner.invoke(app, ["config", "show"])

        assert result.exit_code == 0
        assert_output_contains(result.stdout, "persistence")
        assert_output_contains(result.stdout, "execution")

    def test_config_show_with_file(self, cli_runner, sample_config):
        """Test showing saved configuration."""
        result = cli_runner.invoke(app, ["config", "show"])

        assert result.exit_code == 0
        assert_output_contains(result.stdout, "sqlite")
        assert_output_contains(result.stdout, "sync")

    def test_config_show_json_output(self, cli_runner, sample_config):
        """Test JSON output format."""
        result = cli_runner.invoke(app, ["config", "show", "--json"])

        assert result.exit_code == 0
        # Should be valid JSON
        config_data = json.loads(result.stdout)
        assert "persistence" in config_data
        assert "execution" in config_data


class TestConfigSetPersistence:
    """Tests for 'rufus config set-persistence' command."""

    def test_set_persistence_sqlite_memory(self, cli_runner, temp_config_dir):
        """Test setting SQLite in-memory persistence."""
        # Provide input to interactive prompts: provider=2 (sqlite)
        result = cli_runner.invoke(
            app,
            ["config", "set-persistence", "--db-path", ":memory:"],
            input="2\n"  # Select SQLite (option 2)
        )

        assert result.exit_code == 0
        assert_output_contains(result.stdout, "Persistence provider set to: sqlite")
        assert_output_contains(result.stdout, ":memory:")

    def test_set_persistence_sqlite_file(self, cli_runner, temp_config_dir, tmp_path):
        """Test setting SQLite file-based persistence."""
        db_path = tmp_path / "workflows.db"

        result = cli_runner.invoke(
            app,
            ["config", "set-persistence", "--db-path", str(db_path)],
            input="2\n"  # Select SQLite (option 2)
        )

        assert result.exit_code == 0
        assert_output_contains(result.stdout, "Persistence provider set to: sqlite")
        assert_output_contains(result.stdout, "workflows.db")  # Check filename instead of full path (output may wrap)

    def test_set_persistence_postgres(self, cli_runner, temp_config_dir):
        """Test setting PostgreSQL persistence."""
        db_url = "postgresql://user:pass@localhost/rufus"

        result = cli_runner.invoke(
            app,
            ["config", "set-persistence", "--db-url", db_url, "--pool-min", "10", "--pool-max", "50"],
            input="3\n"  # Select PostgreSQL (option 3)
        )

        assert result.exit_code == 0
        assert_output_contains(result.stdout, "Persistence provider set to: postgres")
        assert_output_contains(result.stdout, db_url)

    def test_set_persistence_memory(self, cli_runner, temp_config_dir):
        """Test setting in-memory persistence."""
        result = cli_runner.invoke(
            app,
            ["config", "set-persistence"],
            input="1\n"  # Select memory (option 1)
        )

        assert result.exit_code == 0
        assert_output_contains(result.stdout, "Persistence provider set to: memory")


class TestConfigSetExecution:
    """Tests for 'rufus config set-execution' command."""

    def test_set_execution_sync(self, cli_runner, temp_config_dir):
        """Test setting sync executor."""
        result = cli_runner.invoke(
            app,
            ["config", "set-execution"],
            input="1\n"  # Select sync (option 1)
        )

        assert result.exit_code == 0
        assert_output_contains(result.stdout, "Execution provider set to: sync")

    def test_set_execution_thread_pool(self, cli_runner, temp_config_dir):
        """Test setting thread pool executor."""
        result = cli_runner.invoke(
            app,
            ["config", "set-execution"],
            input="2\n"  # Select thread_pool (option 2)
        )

        assert result.exit_code == 0
        assert_output_contains(result.stdout, "Execution provider set to: thread_pool")

    @pytest.mark.skip(reason="Celery not in execution provider options")
    def test_set_execution_celery(self, cli_runner, temp_config_dir):
        """Test setting Celery executor."""
        # Celery is not in the execution provider options (only sync and thread_pool)
        pass


class TestConfigSetDefault:
    """Tests for 'rufus config set-default' command."""

    def test_set_default_auto_execute(self, cli_runner, temp_config_dir):
        """Test setting auto_execute default."""
        result = cli_runner.invoke(
            app,
            ["config", "set-default"],
            input="1\ny\n"  # Select auto_execute (option 1), confirm yes
        )

        assert result.exit_code == 0
        assert_output_contains(result.stdout, "Default 'auto_execute' set to: True")

    def test_set_default_disable_auto_execute(self, cli_runner, temp_config_dir):
        """Test disabling auto_execute default."""
        result = cli_runner.invoke(
            app,
            ["config", "set-default"],
            input="1\nn\n"  # Select auto_execute (option 1), confirm no
        )

        assert result.exit_code == 0
        assert_output_contains(result.stdout, "Default 'auto_execute' set to: False")


class TestConfigReset:
    """Tests for 'rufus config reset' command."""

    def test_config_reset_with_yes_flag(self, cli_runner, sample_config):
        """Test resetting config with --yes flag."""
        # Verify config exists
        assert sample_config.exists()

        result = cli_runner.invoke(app, ["config", "reset", "--yes"])

        assert result.exit_code == 0
        assert_output_contains(result.stdout, "reset")

        # Config file should be deleted or reset to defaults
        # (Actual behavior depends on implementation)

    def test_config_reset_no_config_file(self, cli_runner, temp_config_dir):
        """Test resetting when no config file exists."""
        config_file = temp_config_dir / "config.yaml"
        assert not config_file.exists()

        result = cli_runner.invoke(app, ["config", "reset", "--yes"])

        # Should succeed (no-op or informational message)
        assert result.exit_code == 0


class TestConfigPath:
    """Tests for 'rufus config path' command."""

    def test_config_path_shows_location(self, cli_runner, temp_config_dir):
        """Test showing config path."""
        result = cli_runner.invoke(app, ["config", "path"])

        assert result.exit_code == 0
        # Should contain path to config directory
        assert str(temp_config_dir) in result.stdout or ".rufus" in result.stdout

    def test_config_path_with_file(self, cli_runner, sample_config):
        """Test showing config path when file exists."""
        result = cli_runner.invoke(app, ["config", "path"])

        assert result.exit_code == 0
        assert "config.yaml" in result.stdout.lower() or ".rufus" in result.stdout
