from celery import Celery
import os
from celery.signals import worker_process_init, worker_ready, worker_shutdown
from celery.schedules import crontab
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

# Create global workflow builder for task discovery and beat schedule population
# This allows Celery workers to auto-discover user task modules
_workflow_config_dir = os.environ.get("WORKFLOW_CONFIG_DIR", "config")
_workflow_registry_file = os.environ.get("WORKFLOW_REGISTRY_FILE", "workflow_registry.yaml")

workflow_builder = None
discovered_task_modules = []

try:
    # Attempt to create workflow builder for automatic task/schedule discovery
    import yaml
    from rufus.builder import WorkflowBuilder
    from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
    from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

    registry_path = os.path.join(_workflow_config_dir, _workflow_registry_file)

    # Check if registry file exists before attempting to load
    if os.path.exists(registry_path):
        # Load registry YAML file
        with open(registry_path, 'r') as f:
            registry_data = yaml.safe_load(f)

        # Convert list format to dict format
        workflow_registry = {}
        for item in registry_data.get("workflows", []):
            workflow_registry[item["type"]] = item

        # Create WorkflowBuilder with loaded registry
        workflow_builder = WorkflowBuilder(
            workflow_registry=workflow_registry,
            config_dir=_workflow_config_dir,
            expression_evaluator_cls=SimpleExpressionEvaluator,
            template_engine_cls=Jinja2TemplateEngine
        )

        # Discover all task modules from registered workflows
        discovered_task_modules = workflow_builder.get_all_task_modules()
        logger.info(f"Loaded workflow registry from {registry_path}")
        logger.info(f"Discovered task modules: {discovered_task_modules}")
    else:
        logger.warning(f"Workflow registry not found at {registry_path}. Task discovery disabled.")
        logger.warning(f"Set WORKFLOW_CONFIG_DIR and WORKFLOW_REGISTRY_FILE environment variables to enable.")
except Exception as e:
    logger.warning(f"Could not load workflow registry: {e}. Task discovery disabled.")
    workflow_builder = None
    discovered_task_modules = []

# Combine and deduplicate includes
all_includes = list(set(base_includes + discovered_task_modules))

celery_app.conf.update(
    broker_url=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    result_backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
    include=all_includes,
    beat_schedule={},  # Placeholder, will be populated dynamically
    # Regional Queues - allow dynamic queue creation
    # To enforce strict routing, workers must be started with -Q <region>
    task_create_missing_queues=True,
    # Use 'default' as the default queue name instead of 'celery'
    task_default_queue='default',
    task_default_exchange='default',
    task_default_routing_key='default'
)

# Add system-wide polling task (for scheduled workflows)
# This is a fallback for workflows that use dynamic scheduling
celery_app.conf.beat_schedule['poll-dynamic-schedules'] = {
    'task': 'rufus.tasks.poll_scheduled_workflows',
    'schedule': 60.0,  # Run every minute
}

# Populate beat schedule from workflow registry
# This auto-registers CRON_SCHEDULE workflows with Celery Beat
if workflow_builder:
    try:
        scheduled_workflows = workflow_builder.get_scheduled_workflows()

        for workflow_type, config in scheduled_workflows.items():
            schedule_config = config.get('schedule')

            if isinstance(schedule_config, str):
                # Parse cron string: "minute hour day_of_month month day_of_week"
                parts = schedule_config.split()
                if len(parts) == 5:
                    schedule = crontab(
                        minute=parts[0],
                        hour=parts[1],
                        day_of_month=parts[2],
                        month_of_year=parts[3],
                        day_of_week=parts[4]
                    )

                    # Register scheduled workflow with Celery Beat
                    celery_app.conf.beat_schedule[f'trigger-{workflow_type}'] = {
                        'task': 'rufus.tasks.trigger_scheduled_workflow',
                        'schedule': schedule,
                        'args': (workflow_type, config.get('initial_data', {}))
                    }
                    logger.info(f"Registered scheduled workflow: {workflow_type} with cron '{schedule_config}'")
                else:
                    logger.warning(f"Invalid cron schedule for {workflow_type}: {schedule_config} (expected 5 parts)")
            elif isinstance(schedule_config, dict):
                # Support dict-based schedule configuration (e.g., {"crontab": {...}} or {"interval": {...}})
                if 'crontab' in schedule_config:
                    schedule = crontab(**schedule_config['crontab'])
                elif 'interval' in schedule_config:
                    from celery.schedules import schedule as celery_schedule
                    schedule = celery_schedule(run_every=schedule_config['interval'])
                else:
                    logger.warning(f"Unsupported schedule format for {workflow_type}: {schedule_config}")
                    continue

                celery_app.conf.beat_schedule[f'trigger-{workflow_type}'] = {
                    'task': 'rufus.tasks.trigger_scheduled_workflow',
                    'schedule': schedule,
                    'args': (workflow_type, config.get('initial_data', {}))
                }
                logger.info(f"Registered scheduled workflow: {workflow_type} with schedule {schedule_config}")
    except Exception as e:
        logger.error(f"Failed to populate beat schedule from registry: {e}")


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

                # Create other required providers for workflow reconstruction
                from rufus.implementations.execution.celery import CeleryExecutionProvider
                from rufus.implementations.observability.events import EventPublisherObserver
                from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
                from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
                from rufus.builder import WorkflowBuilder

                execution_provider = CeleryExecutionProvider()
                observer = EventPublisherObserver(persistence_provider=provider)
                # Initialize observer for real-time event publishing
                pg_executor.run_coroutine_sync(observer.initialize())

                # Create workflow builder with actual registry if available
                # This allows scheduled workflows and other tasks to create new workflows
                import yaml
                config_dir = os.environ.get("WORKFLOW_CONFIG_DIR", "config")
                registry_file = os.environ.get("WORKFLOW_REGISTRY_FILE", "workflow_registry.yaml")
                registry_path = os.path.join(config_dir, registry_file)

                if os.path.exists(registry_path):
                    # Load registry YAML file
                    with open(registry_path, 'r') as f:
                        registry_data = yaml.safe_load(f)

                    # Convert list format to dict format
                    workflow_registry = {}
                    for item in registry_data.get("workflows", []):
                        workflow_registry[item["type"]] = item

                    workflow_builder = WorkflowBuilder(
                        workflow_registry=workflow_registry,
                        config_dir=config_dir,
                        expression_evaluator_cls=SimpleExpressionEvaluator,
                        template_engine_cls=Jinja2TemplateEngine
                    )
                    logger.info(f"Worker loaded workflow registry from {registry_path}")
                else:
                    # Fallback: empty registry - tasks will use definition_snapshot from DB
                    workflow_builder = WorkflowBuilder(
                        workflow_registry={},
                        config_dir=config_dir,
                        expression_evaluator_cls=SimpleExpressionEvaluator,
                        template_engine_cls=Jinja2TemplateEngine
                    )
                    logger.warning(f"Worker: Registry not found at {registry_path}, using empty registry")

                # Give execution_provider direct access to workflow_builder so it can
                # resolve task function paths in dispatch_async_task / dispatch_parallel_tasks
                # without needing a WorkflowEngine reference (worker context has no engine)
                execution_provider._workflow_builder = workflow_builder

                # Inject all providers into tasks module
                from rufus import tasks
                tasks.set_providers(
                    persistence=provider,
                    execution=execution_provider,
                    workflow_builder=workflow_builder,
                    expression_evaluator_cls=SimpleExpressionEvaluator,
                    template_engine_cls=Jinja2TemplateEngine,
                    observer=observer
                )

                logger.info(f"Initialized all providers for worker")
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
