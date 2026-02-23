"""
Shared pytest fixtures for all server endpoint tests.

Note on async fixtures: pytest-asyncio 0.21.0 has a known incompatibility with
pytest 9.x + --import-mode=importlib that prevents async fixtures defined in
conftest.py from working (AttributeError: 'FixtureDef' has no attribute 'unittest').
All fixtures here are therefore sync; async setup is avoided by choosing
implementations that need no async initialization (InMemoryPersistence.initialize()
is a no-op, SyncExecutor can be wired up synchronously).
"""

import pytest
import os
import sys
import concurrent.futures
from unittest.mock import AsyncMock, patch

# Set environment variables before importing the app.
# conftest.py is loaded by pytest before any test module, so these take effect
# before the first import of rufus_server.main.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("WORKFLOW_STORAGE", "memory")
os.environ.setdefault("RUFUS_WORKFLOW_REGISTRY_PATH", "tests/fixtures/test_registry.yaml")
os.environ.setdefault("RUFUS_CONFIG_DIR", "tests/fixtures")

from fastapi.testclient import TestClient

from rufus_server.main import app
from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
from rufus.engine import WorkflowEngine


def _make_mock_redis():
    """Return a mock Redis client that accepts ping/close without a real connection."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.close = AsyncMock()
    mock_redis.xadd = AsyncMock()
    mock_redis.publish = AsyncMock()
    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_redis.pubsub.return_value = mock_pubsub
    return mock_redis


@pytest.fixture
def test_client():
    """Create a test client for the FastAPI app with Redis mocked out."""
    mock_redis = _make_mock_redis()
    with patch("redis.asyncio.from_url", return_value=mock_redis):
        with TestClient(app) as client:
            yield client


@pytest.fixture
def setup_test_workflow():
    """
    Inject a fresh in-memory workflow engine into the app for each test.

    Returns (engine, persistence) for tests that need direct persistence access.

    Sync fixture (not async) to work around a pytest-asyncio 0.21 / pytest 9.x
    incompatibility with async conftest fixtures under --import-mode=importlib.
    InMemoryPersistence.initialize() is a no-op so skipping await is safe.
    """
    persistence = InMemoryPersistence()
    # InMemoryPersistence.initialize() is a no-op — safe to skip the await

    execution = SyncExecutor()
    observer = LoggingObserver()

    engine = WorkflowEngine(
        persistence=persistence,
        executor=execution,
        observer=observer,
        workflow_registry={
            "TestWorkflow": {
                "type": "TestWorkflow",
                "config_file": "test_workflow.yaml",
                "initial_state_model_path": "tests.fixtures.test_state.TestState",
            }
        },
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        config_dir="tests/fixtures",
    )

    # Wire up executor synchronously (skipping async initialize which only stores
    # the engine ref and creates a thread pool — both safe to do directly)
    execution._engine = engine
    execution._thread_pool_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    import rufus_server.main as main_module

    main_module.workflow_engine = engine
    main_module.persistence_provider = persistence
    main_module.execution_provider = execution
    # Disable rate limiting in tests: rate_limit_check returns early when service is None,
    # avoiding the `request.client.host` crash that occurs in TestClient (no client IP).
    main_module.rate_limit_service = None

    return engine, persistence
