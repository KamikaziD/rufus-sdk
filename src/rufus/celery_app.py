from celery import Celery
import os
from celery.signals import worker_process_init, worker_ready, worker_shutdown
import logging

logger = logging.getLogger(__name__)

# This is the core, unconfigured Celery app instance provided by the library.
# The user's application is responsible for configuring the broker, backend,
# and task includes.
celery_app = Celery('rufus')

# Base includes (core infrastructure tasks)
base_includes = [
    'rufus.tasks',  # Core tasks from the library
]

# Combine and deduplicate includes
# TODO: Add automatic task module discovery from workflow registry
all_includes = list(set(base_includes))

celery_app.conf.update(
    broker_url=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    result_backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
    include=all_includes,
    beat_schedule={},  # Placeholder, will be populated dynamically
    # Regional Queues - allow dynamic queue creation
    # To enforce strict routing, workers must be started with -Q <region>
    task_create_missing_queues=True
)

# Add system-wide polling task (for scheduled workflows)
celery_app.conf.beat_schedule['poll-dynamic-schedules'] = {
    'task': 'rufus.tasks.poll_scheduled_workflows',
    'schedule': 60.0,  # Run every minute
}

# TODO: Populate beat schedule from workflow registry
# This requires integration with WorkflowBuilder to discover scheduled workflows


@worker_process_init.connect
def init_worker(**kwargs):
    """
    Reset PostgreSQL connection pool in each worker process after fork.
    This is necessary because connection pools cannot be shared across processes.
    """
    logger.info("Initializing worker process...")

    # Reset the PostgreSQL store singleton if it exists
    try:
        from rufus.implementations.persistence import postgres as pg_module
        if hasattr(pg_module, '_postgres_store'):
            pg_module._postgres_store = None
            logger.info("Reset PostgreSQL store singleton")
    except ImportError:
        logger.debug("PostgreSQL persistence not available")

    # Reset EventPublisher clients
    from rufus.events import event_publisher
    event_publisher.reset()
    logger.info("Reset EventPublisher clients")

    # Initialize persistence provider for tasks
    # This is critical - tasks need access to persistence
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        try:
            # Import here to avoid circular dependencies
            if db_url.startswith("postgresql"):
                from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
                from rufus.utils.postgres_executor import pg_executor

                # Initialize persistence provider
                def _init_persistence():
                    provider = PostgresPersistenceProvider(db_url=db_url)
                    # Initialize asynchronously
                    return pg_executor.run_coroutine_sync(provider.initialize()), provider

                _, provider = _init_persistence()

                # Inject into tasks module
                from rufus import tasks
                tasks.set_persistence_provider(provider)

                logger.info(f"Initialized PostgreSQL persistence for worker")
            elif db_url.startswith("sqlite"):
                from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
                from rufus.utils.postgres_executor import pg_executor

                # Extract path from sqlite:///path
                db_path = db_url.replace("sqlite:///", "")

                # Initialize persistence provider
                def _init_persistence():
                    provider = SQLitePersistenceProvider(db_path=db_path)
                    return pg_executor.run_coroutine_sync(provider.initialize()), provider

                _, provider = _init_persistence()

                # Inject into tasks module
                from rufus import tasks
                tasks.set_persistence_provider(provider)

                logger.info(f"Initialized SQLite persistence for worker")
        except Exception as e:
            logger.error(f"Failed to initialize persistence provider: {e}")
    else:
        logger.warning("DATABASE_URL not set - tasks will not have persistence access")


# Global registry instance
_worker_registry = None


@worker_ready.connect
def on_worker_ready(**kwargs):
    """
    Register the worker with the database when it starts.
    """
    global _worker_registry
    db_url = os.environ.get("DATABASE_URL")
    if db_url and db_url.startswith("postgresql"):
        try:
            from rufus.worker_registry import WorkerRegistry
            logger.info(f"Initializing Worker Registry for database: {db_url.split('@')[-1]}")  # Log safe URL
            _worker_registry = WorkerRegistry(db_url)
            _worker_registry.register()
        except Exception as e:
            logger.error(f"Failed to initialize worker registry: {e}")
    else:
        logger.debug("Worker Registry requires PostgreSQL - DATABASE_URL not set or not PostgreSQL")


@worker_shutdown.connect
def on_worker_shutdown(**kwargs):
    """
    Deregister the worker (mark offline) when it shuts down.
    """
    global _worker_registry
    if _worker_registry:
        logger.info("Deregistering worker...")
        _worker_registry.deregister()
