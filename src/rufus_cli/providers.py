"""
Provider factory for creating configured providers.

Creates persistence, execution, and observability providers based on CLI configuration.
"""

import os
from pathlib import Path
from typing import Tuple

from rufus.providers.persistence import PersistenceProvider
from rufus.providers.execution import ExecutionProvider
from rufus.providers.observer import WorkflowObserver

from rufus_cli.config import Config


async def create_persistence_provider(config: Config) -> PersistenceProvider:
    """
    Create persistence provider from configuration.

    Args:
        config: CLI configuration

    Returns:
        Initialized PersistenceProvider instance

    Raises:
        ValueError: If provider type is unknown
    """
    provider_type = config.persistence.provider

    if provider_type == "memory":
        from rufus.implementations.persistence.memory import InMemoryPersistence
        provider = InMemoryPersistence()

    elif provider_type == "sqlite":
        from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider

        # Expand ~ in db_path
        db_path = os.path.expanduser(config.persistence.sqlite.db_path)

        # Create parent directory if it doesn't exist
        db_dir = Path(db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        provider = SQLitePersistenceProvider(
            db_path=db_path,
            auto_init=config.persistence.sqlite.auto_init
        )

    elif provider_type == "postgres":
        from rufus.implementations.persistence.postgres import PostgresPersistenceProvider

        provider = PostgresPersistenceProvider(
            db_url=config.persistence.postgres.db_url,
            pool_min_size=config.persistence.postgres.pool_min_size,
            pool_max_size=config.persistence.postgres.pool_max_size
        )

    elif provider_type == "redis":
        raise ValueError(
            "Redis persistence is not yet available. Use 'sqlite' or 'postgres'."
        )

    else:
        raise ValueError(f"Unknown persistence provider: {provider_type}")

    # Initialize the provider
    await provider.initialize()

    return provider


def create_execution_provider(config: Config) -> ExecutionProvider:
    """
    Create execution provider from configuration.

    Args:
        config: CLI configuration

    Returns:
        ExecutionProvider instance

    Raises:
        ValueError: If provider type is unknown
    """
    provider_type = config.execution.provider

    if provider_type == "sync":
        from rufus.implementations.execution.sync import SyncExecutor
        return SyncExecutor()

    elif provider_type == "celery":
        raise ValueError(
            "Celery execution is not supported in the CLI. "
            "Use the rufus-server API for distributed execution."
        )

    elif provider_type == "thread_pool":
        from rufus.implementations.execution.thread_pool import ThreadPoolExecutorProvider
        return ThreadPoolExecutorProvider()

    else:
        raise ValueError(f"Unknown execution provider: {provider_type}")


async def create_observer(config: Config) -> WorkflowObserver:
    """
    Create workflow observer from configuration.

    Args:
        config: CLI configuration

    Returns:
        Initialized WorkflowObserver instance

    Raises:
        ValueError: If provider type is unknown
    """
    provider_type = config.observability.provider

    if provider_type == "logging":
        from rufus.implementations.observability.logging import LoggingObserver
        observer = LoggingObserver()

    elif provider_type == "noop":
        from rufus.implementations.observability.noop import NoOpObserver
        observer = NoOpObserver()

    else:
        raise ValueError(f"Unknown observability provider: {provider_type}")

    # Initialize the observer
    await observer.initialize()

    return observer


async def create_providers(config: Config) -> Tuple[PersistenceProvider, ExecutionProvider, WorkflowObserver]:
    """
    Create all providers from configuration.

    Args:
        config: CLI configuration

    Returns:
        Tuple of (persistence_provider, execution_provider, observer)
    """
    persistence = await create_persistence_provider(config)
    execution = create_execution_provider(config)
    observer = await create_observer(config)

    return persistence, execution, observer


async def close_providers(
    persistence: PersistenceProvider,
    execution: ExecutionProvider,
    observer: WorkflowObserver
) -> None:
    """
    Close all providers gracefully.

    Args:
        persistence: Persistence provider to close
        execution: Execution provider to close
        observer: Observer to close
    """
    # Close persistence
    if hasattr(persistence, 'close'):
        await persistence.close()

    # Close execution (might be no-op for sync executor)
    if hasattr(execution, 'close'):
        if callable(getattr(execution, 'close')):
            close_method = getattr(execution, 'close')
            # Check if it's async
            import inspect
            if inspect.iscoroutinefunction(close_method):
                await close_method()
            else:
                close_method()

    # Close observer
    if hasattr(observer, 'close'):
        await observer.close()
