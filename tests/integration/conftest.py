"""Shared fixtures for integration tests.

Two operating modes:
  1. Postgres available  → full integration client with real DB via LifespanManager
  2. Postgres not available → tests that need it are skipped cleanly

Any test that needs Postgres should request the `postgres_client` fixture.
Tests that work with in-memory persistence use the `client` fixture.
"""

import os
import sys
import pytest
import asyncio
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
os.environ.setdefault("WORKFLOW_STORAGE", "memory")
os.environ.setdefault("RUVON_WORKFLOW_REGISTRY_PATH", "tests/fixtures/test_registry.yaml")
os.environ.setdefault("RUVON_CONFIG_DIR", "tests/fixtures")

try:
    import httpx
    from asgi_lifespan import LifespanManager
    from ruvon_server.main import app
    _DEPS_AVAILABLE = True
except Exception:
    _DEPS_AVAILABLE = False


def _make_mock_redis():
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


def _postgres_available() -> bool:
    """Return True if DATABASE_URL is set and Postgres is reachable."""
    url = os.getenv("DATABASE_URL", "")
    if not url or "postgres" not in url:
        return False
    try:
        import asyncpg

        async def _check():
            conn = await asyncpg.connect(url, timeout=3)
            await conn.close()

        asyncio.get_event_loop().run_until_complete(_check())
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_available(),
    reason="PostgreSQL not available (set DATABASE_URL to a reachable Postgres instance)",
)


@pytest.fixture
async def client() -> AsyncGenerator["httpx.AsyncClient", None]:
    """In-process async client with ASGI lifespan — no live server required."""
    if not _DEPS_AVAILABLE:
        pytest.skip("Server dependencies not available")
    mock_redis = _make_mock_redis()
    with patch("redis.asyncio.from_url", return_value=mock_redis):
        async with LifespanManager(app, startup_timeout=30, shutdown_timeout=10) as manager:
            transport = httpx.ASGITransport(app=manager.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                yield c
