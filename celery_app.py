from celery import Celery
import os
from celery.signals import worker_process_init
from confucius.workflow_loader import workflow_builder

# This is the core, unconfigured Celery app instance provided by the library.
# The user's application is responsible for configuring the broker, backend,
# and task includes.
celery_app = Celery('confucius')

# Automatically discover task modules referenced in registered workflows
discovered_task_modules = workflow_builder.get_all_task_modules()

# Define base includes (core infrastructure tasks)
base_includes = [
    'confucius.tasks',      # Core tasks from the library
    'workflow_utils',           # Application-specific tasks (kept for safety/backward compat)
    'celery_worker'             # Other application-specific tasks
]

# Combine and deduplicate includes
all_includes = list(set(base_includes + discovered_task_modules))

celery_app.conf.update(
    broker_url=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    result_backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
    include=all_includes,
    beat_schedule={}, # Placeholder, will be populated dynamically
    # Phase 9: Regional Queues
    # We allow dynamic queue creation, but defaults can be set here.
    # To enforce strict routing, workers must be started with -Q <region>
    task_create_missing_queues=True
)

# Add system-wide polling task
celery_app.conf.beat_schedule['poll-dynamic-schedules'] = {
    'task': 'confucius.tasks.poll_scheduled_workflows',
    'schedule': 60.0, # Run every minute
}

# Populate beat schedule from registry
# Note: This runs on module import, so workflow_builder must be ready.
for workflow_type, config in workflow_builder.get_scheduled_workflows().items():
    schedule_config = config['schedule']
    # Parse schedule (cron vs interval) - simplified for now, assumes crontab if string
    # or we can support a dict structure in YAML for more options.
    # For now, let's assume the task is 'confucius.tasks.trigger_scheduled_workflow'
    
    # We need a task to trigger the workflow. I'll add that task next.
    
    from celery.schedules import crontab
    
    # Simple CRON string parsing (space separated)
    # "0 0 * * *"
    parts = schedule_config.split()
    if len(parts) == 5:
        schedule = crontab(
            minute=parts[0],
            hour=parts[1],
            day_of_month=parts[2],
            month_of_year=parts[3],
            day_of_week=parts[4]
        )
        
        celery_app.conf.beat_schedule[f'trigger-{workflow_type}'] = {
            'task': 'confucius.tasks.trigger_scheduled_workflow',
            'schedule': schedule,
            'args': (workflow_type, config.get('initial_data', {}))
        }

@worker_process_init.connect
def init_worker(**kwargs):
    """
    Reset PostgreSQL connection pool in each worker process after fork.
    This is necessary because connection pools cannot be shared across processes.
    """
    # Reset the PostgreSQL store singleton
    import confucius.persistence_postgres as pg_module
    pg_module._postgres_store = None
    
    # Reset EventPublisher clients
    from confucius.events import event_publisher
    event_publisher.reset()

from celery.signals import worker_ready, worker_shutdown
from confucius.worker_registry import WorkerRegistry

# Global registry instance
_worker_registry = None

@worker_ready.connect
def on_worker_ready(**kwargs):
    """
    Register the worker with the database when it starts.
    """
    global _worker_registry
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        print(f"Initializing Worker Registry for database: {db_url.split('@')[-1]}") # Log safe URL
        _worker_registry = WorkerRegistry(db_url)
        _worker_registry.register()
    else:
        print("WARNING: DATABASE_URL not set, skipping Worker Registry initialization.")

@worker_shutdown.connect
def on_worker_shutdown(**kwargs):
    """
    Deregister the worker (mark offline) when it shuts down.
    """
    global _worker_registry
    if _worker_registry:
        print("Deregistering worker...")
        _worker_registry.deregister()


from celery.signals import worker_ready, worker_shutdown
from confucius.worker_registry import WorkerRegistry

# Global registry instance
_worker_registry = None

@worker_ready.connect
def on_worker_ready(**kwargs):
    """
    Register the worker with the database when it starts.
    """
    global _worker_registry
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        print(f"Initializing Worker Registry for database: {db_url}")
        _worker_registry = WorkerRegistry(db_url)
        _worker_registry.register()
    else:
        print("WARNING: DATABASE_URL not set, skipping Worker Registry initialization.")

@worker_shutdown.connect
def on_worker_shutdown(**kwargs):
    """
    Deregister the worker (mark offline) when it shuts down.
    """
    global _worker_registry
    if _worker_registry:
        print("Deregistering worker...")
        _worker_registry.deregister()