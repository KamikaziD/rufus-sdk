"""
PostgresExecutor

Runs all asyncpg (Postgres) related coroutines on a dedicated background
thread + asyncio event loop. This avoids mixing asyncio event loops across
threads which is the root cause of "another operation is in progress" errors
when the library is used from multiple asyncio contexts.

Usage:
    from rufus.utils.postgres_executor import pg_executor
    result = pg_executor.run_coroutine_sync(some_async_coroutine(...))

The executor exposes:
- run_coroutine_sync(coro): schedule coro on the background loop and wait for result.
- run_coroutine_future(coro): return a concurrent.futures.Future (non-blocking).
- start() / stop(): lifecycle control (start called on import).
"""
from __future__ import annotations

import asyncio
import threading
import concurrent.futures
import time
import atexit
from typing import Any, Callable, Optional
import os


class _PostgresExecutor:
    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._started = threading.Event()
        self._stopping = threading.Event()
        self._shutdown_timeout = 5.0

    def start(self):
        if self._thread and self._thread.is_alive():
            return

        def _run_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._started.set()
            try:
                loop.run_forever()
            finally:
                # Drain and close the loop cleanly
                pending = asyncio.all_tasks(loop=loop)
                for task in pending:
                    task.cancel()
                try:
                    loop.run_until_complete(asyncio.gather(
                        *pending, return_exceptions=True))
                except Exception:
                    pass
                loop.close()
                self._loop = None

        self._thread = threading.Thread(
            target=_run_loop, name="rufus-postgres-executor", daemon=True)
        self._thread.start()
        # Wait briefly for the loop to be established
        if not self._started.wait(timeout=3.0):
            raise RuntimeError(
                "PostgresExecutor failed to start event loop in time")

    def stop(self):
        if not self._thread or not self._thread.is_alive():
            return
        self._stopping.set()
        loop = self._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        # Wait for thread to finish
        self._thread.join(timeout=self._shutdown_timeout)
        self._thread = None
        self._started.clear()
        self._stopping.clear()

    def run_coroutine_sync(self, coro_or_callable, timeout: Optional[float] = None) -> Any:
        """
        Schedule the coroutine on the background loop and wait synchronously
        for the result.

        Accept either:
         - a coroutine object, or
         - a zero-arg callable that RETURNS a fresh coroutine when called.

        Passing a callable is recommended when the coroutine creation may have
        dependencies on the caller's context (avoids "Future attached to a
        different loop" errors that occur when a coroutine object was already
        created/scheduled in another loop).
        """
        if not self._loop or not self._thread or not self._thread.is_alive():
            # Start the executor on demand
            self.start()

        # If a callable was provided, call it here to get a fresh coroutine.
        if callable(coro_or_callable):
            coro = coro_or_callable()
        else:
            coro = coro_or_callable

        future: concurrent.futures.Future = asyncio.run_coroutine_threadsafe(
            coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as te:
            raise TimeoutError(
                f"PostgresExecutor timed out after {timeout}s") from te

    def run_coroutine_future(self, coro_or_callable) -> concurrent.futures.Future:
        """
        Schedule the coroutine and return a concurrent.futures.Future that can
        be waited on by callers.

        Accepts either a coroutine object or a zero-arg callable that RETURNS a
        fresh coroutine when called (to avoid cross-loop coroutine creation).
        """
        if not self._loop or not self._thread or not self._thread.is_alive():
            self.start()
        # If a callable was provided, call it here to get a fresh coroutine.
        if callable(coro_or_callable):
            coro = coro_or_callable()
        else:
            coro = coro_or_callable
        return asyncio.run_coroutine_threadsafe(coro, self._loop)


# Singleton executor instance used by the codebase
_pg_executor: Optional[_PostgresExecutor] = None
_pg_executor_pid: Optional[int] = None


def get_executor() -> _PostgresExecutor:
    global _pg_executor, _pg_executor_pid
    current_pid = os.getpid()
    if _pg_executor is None or _pg_executor_pid != current_pid:
        if _pg_executor is not None:
            _pg_executor.stop()
        _pg_executor = _PostgresExecutor()
        _pg_executor.start()
        _pg_executor_pid = current_pid
        # Ensure it is shut down at process exit
        atexit.register(lambda: _pg_executor.stop())
    return _pg_executor


# Convenience alias for callers
pg_executor = get_executor()
