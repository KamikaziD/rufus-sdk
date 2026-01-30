"""V8 context pool management for JavaScript execution."""

import logging
import time
from typing import Any, Optional
from contextlib import contextmanager
from threading import Lock

logger = logging.getLogger(__name__)

# Flag to track if py_mini_racer is available
_MINI_RACER_AVAILABLE = False
_MiniRacer = None

try:
    from py_mini_racer import MiniRacer
    _MiniRacer = MiniRacer
    _MINI_RACER_AVAILABLE = True
except ImportError:
    logger.warning(
        "py_mini_racer not installed. JavaScript steps will not be available. "
        "Install with: pip install py-mini-racer"
    )


def is_mini_racer_available() -> bool:
    """Check if PyMiniRacer is available."""
    return _MINI_RACER_AVAILABLE


class V8Context:
    """
    Wrapper around a PyMiniRacer context.

    Provides:
    - Timeout enforcement
    - Memory limit tracking
    - Error handling
    """

    def __init__(self, memory_limit_mb: int = 128):
        if not _MINI_RACER_AVAILABLE:
            raise RuntimeError(
                "py_mini_racer is not installed. "
                "Install with: pip install py-mini-racer"
            )

        self._ctx = _MiniRacer()
        self._memory_limit_mb = memory_limit_mb
        self._created_at = time.time()
        self._execution_count = 0

    def eval(self, code: str, timeout_ms: int = 5000) -> Any:
        """
        Execute JavaScript code with timeout.

        Args:
            code: JavaScript code to execute
            timeout_ms: Timeout in milliseconds

        Returns:
            Result of execution

        Raises:
            TimeoutError: If execution exceeds timeout
            RuntimeError: If execution fails
        """
        self._execution_count += 1

        try:
            # PyMiniRacer timeout is in milliseconds
            result = self._ctx.eval(code, timeout=timeout_ms)
            return result
        except Exception as e:
            error_str = str(e)
            if "timeout" in error_str.lower():
                raise TimeoutError(f"Script execution timed out after {timeout_ms}ms")
            raise

    def get_memory_usage_mb(self) -> float:
        """Get current V8 heap usage in megabytes."""
        try:
            # PyMiniRacer provides heap statistics
            stats = self._ctx.heap_stats()
            if isinstance(stats, dict):
                used_heap = stats.get("used_heap_size", 0)
                return used_heap / (1024 * 1024)
        except Exception:
            pass
        return 0.0

    @property
    def execution_count(self) -> int:
        """Number of times this context has been used."""
        return self._execution_count

    @property
    def age_seconds(self) -> float:
        """Age of this context in seconds."""
        return time.time() - self._created_at


class V8ContextPool:
    """
    Pool of V8 contexts for reuse.

    Note: PyMiniRacer contexts are NOT thread-safe, so we create
    a new context for each execution in this simple implementation.

    For high-performance scenarios, consider:
    - Thread-local context pools
    - Context reset and reuse
    - Async context management
    """

    def __init__(
        self,
        max_contexts: int = 10,
        max_context_age_seconds: int = 300,
        max_context_executions: int = 100,
    ):
        self._max_contexts = max_contexts
        self._max_age = max_context_age_seconds
        self._max_executions = max_context_executions
        self._lock = Lock()
        self._stats = {
            "contexts_created": 0,
            "contexts_reused": 0,
            "contexts_destroyed": 0,
        }

    @contextmanager
    def get_context(self, memory_limit_mb: int = 128):
        """
        Get a V8 context for execution.

        Currently creates a new context for each execution.
        Context is automatically cleaned up after use.

        Args:
            memory_limit_mb: Memory limit for the context

        Yields:
            V8Context instance
        """
        ctx = None
        try:
            ctx = V8Context(memory_limit_mb=memory_limit_mb)
            with self._lock:
                self._stats["contexts_created"] += 1
            yield ctx
        finally:
            # Clean up context
            if ctx is not None:
                with self._lock:
                    self._stats["contexts_destroyed"] += 1
                # PyMiniRacer doesn't have explicit cleanup, but we can
                # help garbage collection by removing reference
                del ctx

    def get_stats(self) -> dict:
        """Get pool statistics."""
        with self._lock:
            return self._stats.copy()


# Global default pool
_default_pool: Optional[V8ContextPool] = None
_pool_lock = Lock()


def get_default_pool() -> V8ContextPool:
    """Get the default V8 context pool."""
    global _default_pool
    with _pool_lock:
        if _default_pool is None:
            _default_pool = V8ContextPool()
        return _default_pool
