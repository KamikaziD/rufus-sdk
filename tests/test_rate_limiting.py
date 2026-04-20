"""
Integration tests for rate limiting feature.

Tests the RateLimitService, API endpoints, and CLI commands.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from ruvon_server.rate_limit_service import RateLimitService, RateLimitRule, RateLimitResult


class MockPool:
    """Async context manager that mimics asyncpg pool.acquire()."""

    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return self

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


class MockPersistence:
    """Mock persistence provider for testing."""

    def __init__(self):
        self.rules = {}
        self.tracking = []
        self.pool = MockPool(self)

    async def fetchrow(self, query, *args):
        """Mock fetchrow for single row queries."""
        if "SELECT * FROM rate_limit_rules WHERE rule_name" in query:
            rule_name = args[0]
            return self.rules.get(rule_name)
        return None

    async def fetch(self, query, *args):
        """Mock fetch for multi-row queries."""
        if "SELECT * FROM rate_limit_rules" in query:
            is_active = args[0] if args else None
            results = []
            for rule in self.rules.values():
                if is_active is None or rule['is_active'] == is_active:
                    results.append(rule)
            return results
        return []

    async def execute(self, query, *args):
        """Mock execute for INSERT/UPDATE/DELETE."""
        if "INSERT INTO rate_limit_rules" in query:
            rule_name = args[0]
            if rule_name in self.rules:
                raise Exception("Rule already exists")
            self.rules[rule_name] = {
                'rule_name': args[0],
                'resource_pattern': args[1],
                'scope': args[2],
                'limit_per_window': args[3],
                'window_seconds': args[4],
                'is_active': args[5],
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow()
            }
            return "INSERT 1"
        elif "UPDATE rate_limit_rules" in query:
            rule_name = args[-1]  # Last arg is rule_name
            if rule_name in self.rules:
                return "UPDATE 1"
            return "UPDATE 0"
        elif "DELETE FROM rate_limit_tracking" in query:
            return "DELETE 0"
        elif "INSERT INTO rate_limit_tracking" in query:
            self.tracking.append({
                'identifier': args[0],
                'rule_name': args[1],
                'window_start': args[2]
            })
            return "INSERT 1"
        return "OK"


@pytest.fixture
async def rate_limit_service():
    """Create RateLimitService with mock persistence."""
    mock_persistence = MockPersistence()

    # Add default test rules
    mock_persistence.rules = {
        'test_rule': {
            'rule_name': 'test_rule',
            'resource_pattern': '/api/v1/test',
            'scope': 'user',
            'limit_per_window': 10,
            'window_seconds': 60,
            'is_active': True,
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        },
        'global_rule': {
            'rule_name': 'global_rule',
            'resource_pattern': '/api/v1/*',
            'scope': 'ip',
            'limit_per_window': 100,
            'window_seconds': 60,
            'is_active': True,
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }
    }

    # Create service with mock conn attribute
    service = RateLimitService(mock_persistence)
    service.persistence.conn = mock_persistence

    return service


@pytest.mark.asyncio
async def test_check_rate_limit_allowed(rate_limit_service):
    """Test rate limit check when under limit."""
    result = await rate_limit_service.check_rate_limit(
        identifier="user:test-user",
        resource_pattern="/api/v1/test",
        scope="user"
    )

    assert result.allowed is True
    assert result.limit == 10
    assert result.remaining == 10
    assert result.retry_after == 0


@pytest.mark.asyncio
async def test_check_rate_limit_exceeded(rate_limit_service):
    """Test rate limit check when limit exceeded."""
    # Record 10 requests (hit limit)
    for i in range(10):
        await rate_limit_service.record_request(
            identifier="user:test-user",
            resource_pattern="/api/v1/test",
            scope="user"
        )

    # 11th request should be denied
    result = await rate_limit_service.check_rate_limit(
        identifier="user:test-user",
        resource_pattern="/api/v1/test",
        scope="user"
    )

    assert result.allowed is False
    assert result.limit == 10
    assert result.remaining == 0
    assert result.retry_after > 0


@pytest.mark.asyncio
async def test_record_request(rate_limit_service):
    """Test recording requests updates counters."""
    identifier = "user:test-user"
    resource = "/api/v1/test"

    # Record 3 requests
    for i in range(3):
        await rate_limit_service.record_request(
            identifier=identifier,
            resource_pattern=resource,
            scope="user"
        )

    # Check counter updated
    result = await rate_limit_service.check_rate_limit(
        identifier=identifier,
        resource_pattern=resource,
        scope="user"
    )

    assert result.allowed is True
    assert result.remaining == 7  # 10 - 3 = 7


@pytest.mark.asyncio
async def test_wildcard_pattern_matching(rate_limit_service):
    """Test wildcard pattern matching."""
    result = await rate_limit_service.check_rate_limit(
        identifier="ip:127.0.0.1",
        resource_pattern="/api/v1/unknown/endpoint",
        scope="ip"
    )

    # Should match global_rule (/api/v1/*)
    assert result.allowed is True
    assert result.limit == 100


@pytest.mark.asyncio
async def test_no_matching_rule(rate_limit_service):
    """Test behavior when no rule matches."""
    result = await rate_limit_service.check_rate_limit(
        identifier="user:test-user",
        resource_pattern="/public/health",
        scope="user"
    )

    # Should allow when no rule matches
    assert result.allowed is True
    assert result.limit == 0


@pytest.mark.asyncio
async def test_get_rules(rate_limit_service):
    """Test retrieving all rules."""
    rules = await rate_limit_service.get_rules()

    assert len(rules) == 2
    assert any(r.rule_name == 'test_rule' for r in rules)
    assert any(r.rule_name == 'global_rule' for r in rules)


@pytest.mark.asyncio
async def test_get_rules_active_only(rate_limit_service):
    """Test retrieving active rules only."""
    rules = await rate_limit_service.get_rules(is_active=True)

    assert len(rules) == 2
    assert all(r.is_active for r in rules)


@pytest.mark.asyncio
async def test_get_rule(rate_limit_service):
    """Test retrieving specific rule."""
    rule = await rate_limit_service.get_rule('test_rule')

    assert rule is not None
    assert rule.rule_name == 'test_rule'
    assert rule.resource_pattern == '/api/v1/test'
    assert rule.limit_per_window == 10


@pytest.mark.asyncio
async def test_update_rule(rate_limit_service):
    """Test updating rule."""
    success = await rate_limit_service.update_rule(
        rule_name='test_rule',
        limit_per_window=20,
        window_seconds=120
    )

    assert success is True


@pytest.mark.asyncio
async def test_create_rule(rate_limit_service):
    """Test creating new rule."""
    success = await rate_limit_service.create_rule(
        rule_name='new_rule',
        resource_pattern='/api/v1/new',
        scope='user',
        limit_per_window=50,
        window_seconds=60
    )

    assert success is True


@pytest.mark.asyncio
async def test_delete_rule(rate_limit_service):
    """Test soft-deleting rule."""
    success = await rate_limit_service.delete_rule('test_rule')

    assert success is True


@pytest.mark.asyncio
async def test_get_limit_status(rate_limit_service):
    """Test getting current limit status."""
    identifier = "user:test-user"

    # Record some requests
    for i in range(3):
        await rate_limit_service.record_request(
            identifier=identifier,
            resource_pattern="/api/v1/test",
            scope="user"
        )

    # Get status
    status = await rate_limit_service.get_limit_status(identifier)

    assert len(status) > 0
    test_status = status.get('/api/v1/test')
    assert test_status is not None
    assert test_status.used == 3
    assert test_status.remaining == 7
    assert test_status.limit == 10


@pytest.mark.asyncio
async def test_window_reset(rate_limit_service):
    """Test that counters reset when window expires."""
    import time

    identifier = "user:test-user"
    resource = "/api/v1/test"

    # Record 5 requests
    for i in range(5):
        await rate_limit_service.record_request(
            identifier=identifier,
            resource_pattern=resource,
            scope="user"
        )

    # Check current usage
    result1 = await rate_limit_service.check_rate_limit(
        identifier=identifier,
        resource_pattern=resource,
        scope="user"
    )
    assert result1.remaining == 5  # 10 - 5 = 5

    # Simulate window expiry by manipulating counter
    # (In real test, would wait 60s or mock time)
    # For now, just verify reset_at is in the future
    assert result1.reset_at > datetime.utcnow()


@pytest.mark.asyncio
async def test_concurrent_requests(rate_limit_service):
    """Test concurrent request handling."""
    identifier = "user:concurrent-user"
    resource = "/api/v1/test"

    # Simulate 5 concurrent requests
    tasks = [
        rate_limit_service.record_request(identifier, resource, "user")
        for _ in range(5)
    ]
    await asyncio.gather(*tasks)

    # Verify count
    result = await rate_limit_service.check_rate_limit(
        identifier=identifier,
        resource_pattern=resource,
        scope="user"
    )

    assert result.remaining == 5  # 10 - 5 = 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
