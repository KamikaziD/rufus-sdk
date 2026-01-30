"""
Tests for the SQLite task manager example.
"""
import pytest


class TestSQLiteTaskManagerExample:
    """Tests for examples/sqlite_task_manager/."""

    def test_simple_demo_runs_successfully(self):
        """Test that simple_demo.py runs without errors."""
        import subprocess
        import sys
        from pathlib import Path

        sqlite_dir = Path(__file__).parent.parent.parent / "examples" / "sqlite_task_manager"
        assert sqlite_dir.exists(), f"SQLite example directory not found: {sqlite_dir}"

        result = subprocess.run(
            [sys.executable, "simple_demo.py"],
            cwd=sqlite_dir,
            capture_output=True,
            text=True,
            timeout=30
        )

        assert result.returncode == 0, f"Simple demo failed with error:\n{result.stderr}"
        assert "DEMO COMPLETED SUCCESSFULLY" in result.stdout
        assert "✅ SQLite persistence is working perfectly!" in result.stdout
        assert "Workflows: 1" in result.stdout
        assert "Logs: 3" in result.stdout
        assert "Metrics: 2" in result.stdout

    @pytest.mark.skip(reason="Main demo needs verification - implement after simple_demo fixed")
    def test_main_demo_runs_successfully(self):
        """Test that main.py runs without errors."""
        # Would test: python examples/sqlite_task_manager/main.py
        pass

    @pytest.mark.skip(reason="Example needs fixing")
    def test_sqlite_database_created(self):
        """Test that SQLite database is created."""
        # Would verify: Database file created or in-memory DB works
        pass

    @pytest.mark.skip(reason="Example needs fixing")
    def test_sqlite_schema_valid(self):
        """Test that SQLite schema matches expected structure."""
        # Would verify: Schema has required tables and columns
        pass

    def test_sqlite_example_files_exist(self):
        """Test that all required SQLite example files exist."""
        from pathlib import Path

        sqlite_dir = Path(__file__).parent.parent.parent / "examples" / "sqlite_task_manager"

        required_files = [
            "simple_demo.py",
            "README.md"
        ]

        for filename in required_files:
            file_path = sqlite_dir / filename
            assert file_path.exists(), f"Required file missing: {filename}"
