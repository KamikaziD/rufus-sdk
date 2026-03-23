"""
Tests for auto-initialization functionality in SQLite persistence provider.
"""
import pytest
import asyncio
import tempfile
from pathlib import Path

from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider


class TestSQLiteAutoInit:
    """Tests for SQLite auto-initialization feature"""

    @pytest.mark.asyncio
    async def test_auto_init_enabled_creates_schema(self):
        """Test that auto_init=True creates schema automatically"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_auto_init.db"

            # Create provider with auto_init=True
            provider = SQLitePersistenceProvider(
                db_path=str(db_path),
                auto_init=True
            )

            # Initialize should create schema
            await provider.initialize()

            # Verify tables exist
            async with provider.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ) as cursor:
                tables = [row[0] for row in await cursor.fetchall()]

            # Check key tables exist
            assert 'workflow_executions' in tables
            assert 'tasks' in tables
            assert 'compensation_log' in tables
            assert 'workflow_audit_log' in tables
            assert 'workflow_execution_logs' in tables
            assert 'workflow_metrics' in tables
            assert 'workflow_heartbeats' in tables

            await provider.close()

    @pytest.mark.asyncio
    async def test_auto_init_disabled_warns_only(self):
        """Test that auto_init=False only warns about missing schema"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_no_auto_init.db"

            # Create provider with auto_init=False
            provider = SQLitePersistenceProvider(
                db_path=str(db_path),
                auto_init=False
            )

            # Initialize should NOT create schema
            await provider.initialize()

            # Verify tables do NOT exist
            async with provider.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ) as cursor:
                tables = [row[0] for row in await cursor.fetchall()]

            # No tables should exist
            assert 'workflow_executions' not in tables

            await provider.close()

    @pytest.mark.asyncio
    async def test_auto_init_in_memory(self):
        """Test auto-initialization works with in-memory database"""
        # Create in-memory provider with auto_init=True
        provider = SQLitePersistenceProvider(
            db_path=":memory:",
            auto_init=True
        )

        await provider.initialize()

        # Verify schema exists
        async with provider.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='workflow_executions'"
        ) as cursor:
            result = await cursor.fetchone()

        assert result is not None

        await provider.close()

    @pytest.mark.asyncio
    async def test_auto_init_idempotent(self):
        """Test that multiple initializations are idempotent"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_idempotent.db"

            provider = SQLitePersistenceProvider(
                db_path=str(db_path),
                auto_init=True
            )

            # Initialize once
            await provider.initialize()

            # Initialize again (should not error)
            await provider.initialize()

            # Verify schema still exists
            async with provider.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ) as cursor:
                tables = [row[0] for row in await cursor.fetchall()]

            assert 'workflow_executions' in tables

            await provider.close()

    @pytest.mark.asyncio
    async def test_auto_init_with_existing_schema(self):
        """Test that auto_init doesn't break if schema already exists"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_existing.db"

            # First provider creates schema
            provider1 = SQLitePersistenceProvider(
                db_path=str(db_path),
                auto_init=True
            )
            await provider1.initialize()
            await provider1.close()

            # Second provider should work fine with existing schema
            provider2 = SQLitePersistenceProvider(
                db_path=str(db_path),
                auto_init=True
            )
            await provider2.initialize()

            # Verify schema still exists and works
            async with provider2.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ) as cursor:
                tables = [row[0] for row in await cursor.fetchall()]

            assert 'workflow_executions' in tables

            await provider2.close()

    @pytest.mark.asyncio
    async def test_schema_functional_after_auto_init(self):
        """Test that schema created by auto_init is fully functional"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_functional.db"

            provider = SQLitePersistenceProvider(
                db_path=str(db_path),
                auto_init=True
            )

            await provider.initialize()

            # Try to save a workflow
            workflow_dict = {
                'id': 'test-workflow-123',
                'workflow_type': 'TestWorkflow',
                'current_step': 0,
                'status': 'RUNNING',
                'state': {'test': 'data'},
                'steps_config': [],
                'state_model_path': 'test.Model'
            }

            await provider.save_workflow('test-workflow-123', workflow_dict)

            # Load it back
            loaded = await provider.load_workflow('test-workflow-123')

            assert loaded is not None
            assert loaded.id == 'test-workflow-123'
            assert loaded.workflow_type == 'TestWorkflow'
            assert loaded.status == 'RUNNING'

            await provider.close()


class TestConfigAutoInit:
    """Tests for auto_init configuration integration"""

    def test_config_default_auto_init_true(self):
        """Test that config defaults to auto_init=True"""
        from rufus_cli.config import Config

        config = Config()
        assert config.persistence.sqlite.auto_init is True

    def test_config_set_auto_init(self):
        """Test setting auto_init via config manager"""
        from rufus_cli.config import ConfigManager
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            manager = ConfigManager(config_path)

            # Set persistence with auto_init=False
            manager.set_persistence("sqlite", db_path="/tmp/test.db", auto_init=False)

            # Load config
            config = manager.get()

            assert config.persistence.provider == "sqlite"
            assert config.persistence.sqlite.db_path == "/tmp/test.db"
            assert config.persistence.sqlite.auto_init is False

    def test_config_serialization_includes_auto_init(self):
        """Test that auto_init is serialized to YAML"""
        from rufus_cli.config import ConfigManager
        import tempfile
        import yaml

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            manager = ConfigManager(config_path)

            # Set persistence
            manager.set_persistence("sqlite", db_path="/tmp/test.db", auto_init=False)

            # Read YAML file
            with open(config_path) as f:
                yaml_data = yaml.safe_load(f)

            # Verify auto_init is in YAML
            assert yaml_data['persistence']['sqlite']['auto_init'] is False
