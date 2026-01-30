"""
Shared fixtures and utilities for CLI tests.
"""
import pytest
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any
from unittest.mock import AsyncMock, Mock
import yaml
import asyncio

from typer.testing import CliRunner
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver


@pytest.fixture
def cli_runner():
    """Provides a CliRunner for invoking CLI commands."""
    return CliRunner()


@pytest.fixture
def temp_config_dir(tmp_path):
    """Creates a temporary config directory for tests."""
    config_dir = tmp_path / ".rufus"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def temp_db(tmp_path):
    """Creates a temporary SQLite database path."""
    db_path = tmp_path / "test_workflows.db"
    return db_path


@pytest.fixture
async def initialized_db(temp_db):
    """Creates and initializes a SQLite database with schema."""
    from pathlib import Path

    persistence = SQLitePersistenceProvider(db_path=str(temp_db))
    await persistence.initialize()

    # Apply simplified demo schema (compatible with persistence provider)
    schema_path = Path(__file__).parent.parent.parent / "examples" / "sqlite_task_manager" / "demo_schema.sql"

    with open(schema_path, 'r') as f:
        schema_sql = f.read()

    await persistence.conn.executescript(schema_sql)

    yield temp_db
    await persistence.close()


@pytest.fixture
def sample_workflow_yaml(tmp_path) -> Path:
    """Creates a sample workflow YAML file for testing."""
    workflow_content = {
        "workflow_type": "TestWorkflow",
        "workflow_version": "1.0.0",
        "initial_state_model": "tests.cli.test_utils.TestState",
        "description": "Test workflow for CLI testing",
        "steps": [
            {
                "name": "Step_1",
                "type": "STANDARD",
                "function": "tests.cli.test_utils.step_1",
                "automate_next": True
            },
            {
                "name": "Step_2",
                "type": "STANDARD",
                "function": "tests.cli.test_utils.step_2",
                "dependencies": ["Step_1"]
            }
        ]
    }

    workflow_file = tmp_path / "test_workflow.yaml"
    with open(workflow_file, 'w') as f:
        yaml.dump(workflow_content, f)

    return workflow_file


@pytest.fixture
def sample_workflow_registry(tmp_path, sample_workflow_yaml) -> Path:
    """Creates a sample workflow registry file."""
    registry_content = {
        "workflows": [
            {
                "type": "TestWorkflow",
                "description": "Test workflow",
                "config_file": str(sample_workflow_yaml),
                "initial_state_model": "tests.cli.test_utils.TestState"
            }
        ]
    }

    registry_file = tmp_path / "workflow_registry.yaml"
    with open(registry_file, 'w') as f:
        yaml.dump(registry_content, f)

    return registry_file


@pytest.fixture
def sample_config(temp_config_dir) -> Path:
    """Creates a sample config file."""
    config_content = {
        "persistence": {
            "provider": "sqlite",
            "db_path": ":memory:"
        },
        "execution": {
            "provider": "sync"
        },
        "defaults": {
            "auto_execute_next": True
        }
    }

    config_file = temp_config_dir / "config.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(config_content, f)

    return config_file


@pytest.fixture
def mock_persistence():
    """Creates a mock persistence provider."""
    mock = AsyncMock()

    # Default return values
    mock.list_workflows.return_value = []
    mock.load_workflow.return_value = {
        'id': 'test-workflow-id',
        'workflow_type': 'TestWorkflow',
        'status': 'RUNNING',
        'state': {'test': 'data'},
        'current_step': 'Step_1',
        'created_at': '2026-01-30T00:00:00Z',
        'updated_at': '2026-01-30T00:00:00Z'
    }
    mock.save_workflow.return_value = None
    mock.get_execution_logs.return_value = []
    mock.get_workflow_metrics.return_value = []

    return mock


@pytest.fixture
def mock_execution():
    """Creates a mock execution provider."""
    mock = Mock()
    mock.execute_sync_step_function.return_value = {"result": "success"}
    return mock


@pytest.fixture
def mock_observer():
    """Creates a mock observer."""
    mock = Mock()
    return mock


@pytest.fixture
def sample_workflow_data() -> Dict[str, Any]:
    """Returns sample workflow data for testing."""
    return {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "workflow_type": "TestWorkflow",
        "status": "RUNNING",
        "state": {
            "user_id": "123",
            "status": "processing"
        },
        "current_step": "Step_1",
        "created_at": "2026-01-30T00:00:00Z",
        "updated_at": "2026-01-30T00:00:00Z"
    }


@pytest.fixture(autouse=True)
def set_test_config_path(temp_config_dir, monkeypatch):
    """Automatically sets the config path to temporary directory for all tests."""
    monkeypatch.setenv("RUFUS_CONFIG_DIR", str(temp_config_dir))
