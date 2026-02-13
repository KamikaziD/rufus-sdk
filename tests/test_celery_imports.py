"""
Test that all Celery-related imports work correctly.
"""
import pytest


def test_celery_app_import():
    """Test that celery_app can be imported."""
    try:
        from rufus.celery_app import celery_app
        assert celery_app is not None
        assert celery_app.main == 'rufus'
    except ImportError as e:
        pytest.skip(f"Celery not installed: {e}")


def test_worker_registry_import():
    """Test that WorkerRegistry can be imported."""
    try:
        from rufus.worker_registry import WorkerRegistry
        assert WorkerRegistry is not None
    except ImportError as e:
        pytest.skip(f"psycopg2 not installed: {e}")


def test_postgres_executor_import():
    """Test that postgres_executor can be imported."""
    from rufus.utils.postgres_executor import pg_executor, get_executor
    assert pg_executor is not None
    assert get_executor is not None


def test_events_import():
    """Test that EventPublisher can be imported."""
    try:
        from rufus.events import EventPublisher, event_publisher
        assert EventPublisher is not None
        assert event_publisher is not None
    except ImportError as e:
        pytest.skip(f"Redis not installed: {e}")


def test_tasks_import():
    """Test that Celery tasks can be imported."""
    try:
        from rufus import tasks
        # Check that key tasks exist
        assert hasattr(tasks, 'execute_http_request')
        assert hasattr(tasks, 'resume_from_async_task')
        assert hasattr(tasks, 'merge_and_resume_parallel_tasks')
        assert hasattr(tasks, 'execute_sub_workflow')
        assert hasattr(tasks, 'execute_independent_workflow')
        assert hasattr(tasks, 'resume_parent_from_child')
    except ImportError as e:
        pytest.skip(f"Celery not installed: {e}")


def test_celery_execution_provider_import():
    """Test that CeleryExecutionProvider can be imported."""
    try:
        from rufus.implementations.execution.celery import CeleryExecutionProvider
        provider = CeleryExecutionProvider()
        assert provider is not None
    except ImportError as e:
        pytest.skip(f"Celery not installed: {e}")


def test_all_celery_imports():
    """Test that all Celery components can be imported together."""
    try:
        from rufus.celery_app import celery_app
        from rufus.worker_registry import WorkerRegistry
        from rufus.utils.postgres_executor import pg_executor
        from rufus.events import event_publisher
        from rufus.tasks import resume_from_async_task
        from rufus.implementations.execution.celery import CeleryExecutionProvider

        # Verify all imports successful
        assert celery_app is not None
        assert WorkerRegistry is not None
        assert pg_executor is not None
        assert event_publisher is not None
        assert resume_from_async_task is not None
        assert CeleryExecutionProvider is not None

    except ImportError as e:
        pytest.skip(f"Some Celery dependencies not installed: {e}")
