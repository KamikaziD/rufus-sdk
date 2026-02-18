"""Rate limiting service for API endpoints."""

import asyncio
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class RateLimitRule:
    """Rate limit rule from database."""
    rule_name: str
    resource_pattern: str
    scope: str  # 'user' or 'ip'
    limit_per_window: int
    window_seconds: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class RateLimitResult:
    """Result of rate limit check."""
    allowed: bool
    limit: int
    remaining: int
    reset_at: datetime
    retry_after: int  # seconds


@dataclass
class LimitStatus:
    """Current status for a specific limit."""
    rule_name: str
    resource_pattern: str
    limit: int
    used: int
    remaining: int
    window_seconds: int
    resets_at: datetime


class RateLimitService:
    """Service for managing API rate limits with in-memory tracking."""

    def __init__(self, persistence):
        """
        Initialize rate limit service.

        Args:
            persistence: PersistenceProvider for database operations
        """
        self.persistence = persistence
        self._rules_cache: Dict[str, RateLimitRule] = {}
        self._cache_expiry: Optional[float] = None
        self._cache_ttl = 60  # Refresh rules every 60 seconds
        self._counters: Dict[str, Dict[str, Tuple[int, float]]] = defaultdict(dict)
        # Structure: {identifier: {resource_pattern: (count, window_start_time)}}
        self._cleanup_interval = 300  # Cleanup expired records every 5 minutes
        self._last_cleanup = time.time()

    async def check_rate_limit(
        self,
        identifier: str,
        resource_pattern: str,
        scope: str
    ) -> RateLimitResult:
        """
        Check if request is within rate limit.

        Args:
            identifier: User ID (user:xxx) or IP address (ip:xxx)
            resource_pattern: Resource pattern to match (e.g., '/api/v1/commands')
            scope: 'user' or 'ip'

        Returns:
            RateLimitResult with allowed status and metadata
        """
        # Load rules from cache or DB
        await self._ensure_rules_loaded()

        # Find matching rule
        rule = self._find_matching_rule(resource_pattern, scope)
        if not rule:
            # No rule matched - allow request
            return RateLimitResult(
                allowed=True,
                limit=0,
                remaining=0,
                reset_at=datetime.utcnow(),
                retry_after=0
            )

        # Get current usage
        now = time.time()
        window_start = now - (now % rule.window_seconds)

        # Check in-memory counter
        if identifier in self._counters and resource_pattern in self._counters[identifier]:
            count, counter_window_start = self._counters[identifier][resource_pattern]

            # Check if counter is still valid (same window)
            if counter_window_start == window_start:
                used = count
            else:
                # Window expired, reset counter
                used = 0
        else:
            used = 0

        # Calculate remaining and reset time
        remaining = max(0, rule.limit_per_window - used)
        reset_at = datetime.utcfromtimestamp(window_start + rule.window_seconds)
        retry_after = int(window_start + rule.window_seconds - now)

        # Check if limit exceeded
        allowed = used < rule.limit_per_window

        return RateLimitResult(
            allowed=allowed,
            limit=rule.limit_per_window,
            remaining=remaining,
            reset_at=reset_at,
            retry_after=retry_after if not allowed else 0
        )

    async def record_request(
        self,
        identifier: str,
        resource_pattern: str,
        scope: str
    ) -> None:
        """
        Record a request for rate limiting.

        Args:
            identifier: User ID or IP address
            resource_pattern: Resource pattern
            scope: 'user' or 'ip'
        """
        # Find matching rule
        rule = self._find_matching_rule(resource_pattern, scope)
        if not rule:
            return  # No rate limiting for this resource

        # Update in-memory counter
        now = time.time()
        window_start = now - (now % rule.window_seconds)

        if identifier in self._counters and resource_pattern in self._counters[identifier]:
            count, counter_window_start = self._counters[identifier][resource_pattern]

            if counter_window_start == window_start:
                # Same window, increment
                self._counters[identifier][resource_pattern] = (count + 1, window_start)
            else:
                # New window, reset
                self._counters[identifier][resource_pattern] = (1, window_start)
        else:
            # First request
            self._counters[identifier][resource_pattern] = (1, window_start)

        # Optionally persist to database for durability
        await self._persist_tracking_record(
            identifier,
            rule.rule_name,
            window_start,
            rule.window_seconds
        )

        # Periodic cleanup
        if time.time() - self._last_cleanup > self._cleanup_interval:
            await self._cleanup_expired_counters()

    async def get_rules(self, is_active: Optional[bool] = None) -> List[RateLimitRule]:
        """
        Get all rate limit rules.

        Args:
            is_active: Filter by active status (None = all rules)

        Returns:
            List of rate limit rules
        """
        query = "SELECT * FROM rate_limit_rules"
        params = []

        if is_active is not None:
            query += " WHERE is_active = $1"
            params.append(is_active)

        query += " ORDER BY rule_name"

        async with self.persistence.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._row_to_rule(row) for row in rows]

    async def get_rule(self, rule_name: str) -> Optional[RateLimitRule]:
        """
        Get a specific rate limit rule by name.

        Args:
            rule_name: Name of the rule

        Returns:
            RateLimitRule or None if not found
        """
        query = "SELECT * FROM rate_limit_rules WHERE rule_name = $1"

        async with self.persistence.pool.acquire() as conn:
            row = await conn.fetchrow(query, rule_name)

            if row:
                return self._row_to_rule(row)
            return None

    async def update_rule(
        self,
        rule_name: str,
        limit_per_window: Optional[int] = None,
        window_seconds: Optional[int] = None,
        is_active: Optional[bool] = None
    ) -> bool:
        """
        Update an existing rate limit rule.

        Args:
            rule_name: Name of the rule to update
            limit_per_window: New limit (optional)
            window_seconds: New window size (optional)
            is_active: New active status (optional)

        Returns:
            True if rule was updated, False if not found
        """
        # Build dynamic update query
        updates = []
        params = []
        param_idx = 1

        if limit_per_window is not None:
            updates.append(f"limit_per_window = ${param_idx}")
            params.append(limit_per_window)
            param_idx += 1

        if window_seconds is not None:
            updates.append(f"window_seconds = ${param_idx}")
            params.append(window_seconds)
            param_idx += 1

        if is_active is not None:
            updates.append(f"is_active = ${param_idx}")
            params.append(is_active)
            param_idx += 1

        if not updates:
            return False  # Nothing to update

        updates.append("updated_at = NOW()")
        params.append(rule_name)

        query = f"""
            UPDATE rate_limit_rules
            SET {', '.join(updates)}
            WHERE rule_name = ${param_idx}
        """

        async with self.persistence.pool.acquire() as conn:
            result = await conn.execute(query, *params)

        # Invalidate cache
        self._cache_expiry = None

        return result != "UPDATE 0"

    async def create_rule(
        self,
        rule_name: str,
        resource_pattern: str,
        scope: str,
        limit_per_window: int,
        window_seconds: int,
        is_active: bool = True
    ) -> bool:
        """
        Create a new rate limit rule.

        Args:
            rule_name: Unique name for the rule
            resource_pattern: Resource pattern to match
            scope: 'user' or 'ip'
            limit_per_window: Max requests per window
            window_seconds: Window size in seconds
            is_active: Whether rule is active

        Returns:
            True if created, False if already exists
        """
        try:
            query = """
                INSERT INTO rate_limit_rules
                (rule_name, resource_pattern, scope, limit_per_window, window_seconds, is_active)
                VALUES ($1, $2, $3, $4, $5, $6)
            """
            async with self.persistence.pool.acquire() as conn:
                await conn.execute(
                    query,
                    rule_name,
                    resource_pattern,
                    scope,
                    limit_per_window,
                    window_seconds,
                    is_active
                )

            # Invalidate cache
            self._cache_expiry = None
            return True
        except Exception:
            return False  # Rule already exists or DB error

    async def delete_rule(self, rule_name: str) -> bool:
        """
        Deactivate a rate limit rule (soft delete).

        Args:
            rule_name: Name of the rule to deactivate

        Returns:
            True if deactivated, False if not found
        """
        return await self.update_rule(rule_name, is_active=False)

    async def get_limit_status(
        self,
        identifier: str,
        resource_pattern: Optional[str] = None
    ) -> Dict[str, LimitStatus]:
        """
        Get current rate limit status for an identifier.

        Args:
            identifier: User ID or IP address
            resource_pattern: Optional filter for specific resource

        Returns:
            Dict mapping resource patterns to LimitStatus
        """
        await self._ensure_rules_loaded()

        result = {}
        now = time.time()

        # Check all rules or filtered rule
        for rule in self._rules_cache.values():
            if resource_pattern and rule.resource_pattern != resource_pattern:
                continue

            window_start = now - (now % rule.window_seconds)

            # Get current usage
            if identifier in self._counters and rule.resource_pattern in self._counters[identifier]:
                count, counter_window_start = self._counters[identifier][rule.resource_pattern]
                used = count if counter_window_start == window_start else 0
            else:
                used = 0

            result[rule.resource_pattern] = LimitStatus(
                rule_name=rule.rule_name,
                resource_pattern=rule.resource_pattern,
                limit=rule.limit_per_window,
                used=used,
                remaining=max(0, rule.limit_per_window - used),
                window_seconds=rule.window_seconds,
                resets_at=datetime.utcfromtimestamp(window_start + rule.window_seconds)
            )

        return result

    async def cleanup_expired_records(self) -> int:
        """
        Cleanup expired tracking records from database.

        Returns:
            Number of records deleted
        """
        query = """
            DELETE FROM rate_limit_tracking
            WHERE window_start < NOW() - INTERVAL '1 hour'
        """

        async with self.persistence.pool.acquire() as conn:
            result = await conn.execute(query)

        # Extract count from result like "DELETE 5"
        if result.startswith("DELETE "):
            return int(result.split()[1])
        return 0

    # Private helper methods

    async def _ensure_rules_loaded(self) -> None:
        """Load rules from database if cache expired."""
        now = time.time()

        if self._cache_expiry is None or now > self._cache_expiry:
            rules = await self.get_rules(is_active=True)
            self._rules_cache = {rule.rule_name: rule for rule in rules}
            self._cache_expiry = now + self._cache_ttl

    def _find_matching_rule(
        self,
        resource_pattern: str,
        scope: str
    ) -> Optional[RateLimitRule]:
        """
        Find matching rate limit rule for resource.

        Args:
            resource_pattern: Resource pattern to match
            scope: 'user' or 'ip'

        Returns:
            Matching RateLimitRule or None
        """
        # First try exact match
        for rule in self._rules_cache.values():
            if rule.scope == scope and rule.resource_pattern == resource_pattern:
                return rule

        # Then try wildcard match (e.g., '/api/v1/*')
        for rule in self._rules_cache.values():
            if rule.scope == scope and '*' in rule.resource_pattern:
                pattern = rule.resource_pattern.replace('*', '')
                if resource_pattern.startswith(pattern):
                    return rule

        return None

    async def _persist_tracking_record(
        self,
        identifier: str,
        rule_name: str,
        window_start: float,
        window_seconds: int
    ) -> None:
        """Persist tracking record to database for durability."""
        try:
            query = """
                INSERT INTO rate_limit_tracking
                (identifier, resource, window_start, window_end, request_count)
                VALUES ($1, $2, TO_TIMESTAMP($3), TO_TIMESTAMP($3) + INTERVAL '1 second' * $4, 1)
                ON CONFLICT (identifier, resource, window_start)
                DO UPDATE SET
                    request_count = rate_limit_tracking.request_count + 1,
                    last_request = NOW()
            """
            async with self.persistence.pool.acquire() as conn:
                await conn.execute(
                    query,
                    identifier,
                    rule_name,
                    window_start,
                    window_seconds
                )
        except Exception:
            pass  # Fail silently, in-memory tracking is primary

    async def _cleanup_expired_counters(self) -> None:
        """Remove expired counters from memory."""
        now = time.time()

        for identifier in list(self._counters.keys()):
            for resource_pattern in list(self._counters[identifier].keys()):
                _, window_start = self._counters[identifier][resource_pattern]

                # Remove if older than 1 hour
                if now - window_start > 3600:
                    del self._counters[identifier][resource_pattern]

            # Remove empty identifiers
            if not self._counters[identifier]:
                del self._counters[identifier]

        self._last_cleanup = now

    def _row_to_rule(self, row) -> RateLimitRule:
        """Convert database row to RateLimitRule."""
        return RateLimitRule(
            rule_name=row['rule_name'],
            resource_pattern=row['resource_pattern'],
            scope=row['scope'],
            limit_per_window=row['limit_per_window'],
            window_seconds=row['window_seconds'],
            is_active=row['is_active'],
            created_at=row['created_at'],
            updated_at=row['updated_at']
        )
