# Celery Worker Implementation Plan for Rufus

## Current Status

✅ **What Exists:**
- Sync execution provider (`sync.py`)
- Thread pool execution provider (`thread_pool.py`)
- ExecutionProvider protocol interface
- Workflow engine with async task support

❌ **What's Missing:**
- Celery execution provider
- Rufus tasks module (for Celery tasks)
- Worker registry for distributed workers
- Updated celery_app.py for Rufus

---

## Migration Needed

Your `celery_app.py` references old Confucius modules that need updating:

| Old Module | New Module | Status |
|------------|------------|--------|
| `confucius.workflow_loader` | `rufus.builder` | ✅ Exists |
| `confucius.tasks` | `rufus.tasks` | ❌ Need to create |
| `confucius.persistence_postgres` | `rufus.implementations.persistence.postgres` | ✅ Exists |
| `confucius.events` | `rufus.events` (or remove if not needed) | ❓ Check if needed |
| `confucius.worker_registry` | `rufus.worker_registry` | ❌ Need to create |

---

## Implementation Steps

### Step 1: Create Celery Execution Provider

**File:** `src/rufus/implementations/execution/celery_executor.py`

```python
"""
Celery-based execution provider for distributed workflow execution.
"""

from typing import Dict, Any, Optional, List
from celery import Celery, current_app
from rufus.providers.execution import ExecutionProvider
import logging

logger = logging.getLogger(__name__)


class CeleryExecutionProvider(ExecutionProvider):
    """Execute workflow steps using Celery distributed task queue."""

    def __init__(self, celery_app: Optional[Celery] = None):
        """
        Initialize Celery execution provider.

        Args:
            celery_app: Celery application instance. If None, uses current_app.
        """
        self.celery_app = celery_app or current_app
        logger.info("Celery execution provider initialized")

    async def dispatch_async_task(
        self,
        workflow_id: str,
        step_name: str,
        function_path: str,
        state_dict: Dict[str, Any],
        context_dict: Dict[str, Any],
        user_input: Dict[str, Any]
    ) -> str:
        """
        Dispatch async step to Celery queue.

        Returns:
            task_id: Celery task ID for tracking
        """
        from rufus.tasks import execute_async_step

        result = execute_async_step.apply_async(
            kwargs={
                'workflow_id': workflow_id,
                'step_name': step_name,
                'function_path': function_path,
                'state_dict': state_dict,
                'context_dict': context_dict,
                'user_input': user_input
            },
            task_id=f"{workflow_id}_{step_name}"
        )

        logger.info(f"Dispatched async step {step_name} for workflow {workflow_id}: task_id={result.id}")
        return result.id

    async def dispatch_parallel_tasks(
        self,
        workflow_id: str,
        parent_step_name: str,
        tasks: List[Dict[str, Any]],
        state_dict: Dict[str, Any],
        context_dict: Dict[str, Any]
    ) -> List[str]:
        """
        Dispatch parallel tasks to Celery queue.

        Returns:
            List of task IDs
        """
        from rufus.tasks import execute_parallel_task

        task_ids = []
        for task_config in tasks:
            result = execute_parallel_task.apply_async(
                kwargs={
                    'workflow_id': workflow_id,
                    'parent_step_name': parent_step_name,
                    'task_config': task_config,
                    'state_dict': state_dict,
                    'context_dict': context_dict
                },
                task_id=f"{workflow_id}_{parent_step_name}_{task_config['name']}"
            )
            task_ids.append(result.id)

        logger.info(f"Dispatched {len(task_ids)} parallel tasks for {parent_step_name}")
        return task_ids

    async def dispatch_sub_workflow(
        self,
        parent_workflow_id: str,
        workflow_type: str,
        initial_data: Dict[str, Any],
        owner_id: Optional[str] = None,
        data_region: Optional[str] = None
    ) -> str:
        """
        Dispatch sub-workflow creation to Celery.

        Returns:
            sub_workflow_id
        """
        from rufus.tasks import create_sub_workflow

        result = create_sub_workflow.apply_async(
            kwargs={
                'parent_workflow_id': parent_workflow_id,
                'workflow_type': workflow_type,
                'initial_data': initial_data,
                'owner_id': owner_id,
                'data_region': data_region
            }
        )

        return result.get()  # Wait for sub-workflow creation

    def execute_sync_step_function(
        self,
        func: callable,
        state: Any,
        context: Any,
        user_input: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute synchronous step function directly (no Celery)."""
        return func(state, context, **user_input)
```

---

### Step 2: Create Rufus Tasks Module

**File:** `src/rufus/tasks.py`

```python
"""
Celery tasks for distributed workflow execution.
"""

from celery import Task, current_app
from typing import Dict, Any, Optional
import asyncio
import logging

logger = logging.getLogger(__name__)


class WorkflowTask(Task):
    """Base task class with workflow-specific setup."""

    _workflow_builder = None
    _persistence = None

    @property
    def workflow_builder(self):
        """Lazy-load workflow builder."""
        if self._workflow_builder is None:
            from rufus.builder import WorkflowBuilder
            from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
            import os

            db_url = os.environ.get("DATABASE_URL")
            if not db_url:
                raise ValueError("DATABASE_URL not set")

            persistence = PostgresPersistenceProvider(db_url)
            asyncio.run(persistence.initialize())

            self._workflow_builder = WorkflowBuilder(
                config_dir=os.environ.get("WORKFLOW_CONFIG_DIR", "config/"),
                persistence_provider=persistence
            )
            self._persistence = persistence

        return self._workflow_builder


@current_app.task(base=WorkflowTask, bind=True)
def execute_async_step(
    self,
    workflow_id: str,
    step_name: str,
    function_path: str,
    state_dict: Dict[str, Any],
    context_dict: Dict[str, Any],
    user_input: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Execute an async workflow step.

    This task is dispatched by CeleryExecutionProvider and runs in a
    Celery worker process.
    """
    logger.info(f"Executing async step {step_name} for workflow {workflow_id}")

    try:
        # Import step function
        from rufus.builder import WorkflowBuilder
        func = WorkflowBuilder._import_from_string(function_path)

        # Reconstruct state and context
        from rufus.models import StepContext
        from pydantic import BaseModel

        # Load workflow to get state model
        workflow_dict = asyncio.run(self._persistence.load_workflow(workflow_id))
        state_model_class = WorkflowBuilder._import_from_string(workflow_dict['state_model_path'])

        state = state_model_class(**state_dict)
        context = StepContext(**context_dict)

        # Execute function
        result = func(state, context, **user_input)

        # Save updated state
        workflow_dict['state'] = state.model_dump()
        asyncio.run(self._persistence.save_workflow(workflow_id, workflow_dict))

        logger.info(f"Completed async step {step_name} for workflow {workflow_id}")
        return result

    except Exception as e:
        logger.error(f"Error in async step {step_name}: {e}", exc_info=True)
        raise


@current_app.task(base=WorkflowTask, bind=True)
def execute_parallel_task(
    self,
    workflow_id: str,
    parent_step_name: str,
    task_config: Dict[str, Any],
    state_dict: Dict[str, Any],
    context_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute a parallel task."""
    task_name = task_config['name']
    function_path = task_config['function_path']

    logger.info(f"Executing parallel task {task_name} for workflow {workflow_id}")

    # Similar to execute_async_step
    from rufus.builder import WorkflowBuilder
    func = WorkflowBuilder._import_from_string(function_path)

    from rufus.models import StepContext
    workflow_dict = asyncio.run(self._persistence.load_workflow(workflow_id))
    state_model_class = WorkflowBuilder._import_from_string(workflow_dict['state_model_path'])

    state = state_model_class(**state_dict)
    context = StepContext(**context_dict)

    result = func(state, context)

    logger.info(f"Completed parallel task {task_name}")
    return result


@current_app.task(base=WorkflowTask, bind=True)
def create_sub_workflow(
    self,
    parent_workflow_id: str,
    workflow_type: str,
    initial_data: Dict[str, Any],
    owner_id: Optional[str] = None,
    data_region: Optional[str] = None
) -> str:
    """Create and start a sub-workflow."""
    logger.info(f"Creating sub-workflow {workflow_type} for parent {parent_workflow_id}")

    workflow = asyncio.run(
        self.workflow_builder.create_workflow(
            workflow_type=workflow_type,
            initial_data=initial_data,
            owner_id=owner_id,
            data_region=data_region,
            parent_execution_id=parent_workflow_id
        )
    )

    logger.info(f"Created sub-workflow {workflow.id}")
    return workflow.id


@current_app.task(base=WorkflowTask, bind=True)
def poll_scheduled_workflows(self):
    """Poll for scheduled workflows and trigger them."""
    # Implementation for cron workflow triggering
    logger.info("Polling for scheduled workflows...")
    # TODO: Implement scheduled workflow logic


@current_app.task(base=WorkflowTask, bind=True)
def trigger_scheduled_workflow(self, workflow_type: str, initial_data: Dict[str, Any]):
    """Trigger a scheduled workflow."""
    logger.info(f"Triggering scheduled workflow: {workflow_type}")

    workflow = asyncio.run(
        self.workflow_builder.create_workflow(
            workflow_type=workflow_type,
            initial_data=initial_data
        )
    )

    logger.info(f"Started scheduled workflow {workflow.id}")
    return workflow.id
```

---

### Step 3: Update celery_app.py for Rufus

**File:** `celery_app.py` (root directory)

```python
"""
Rufus Celery Application
"""

from celery import Celery
import os
from celery.signals import worker_process_init, worker_ready, worker_shutdown

# Create Celery app
celery_app = Celery('rufus')

# Configure Celery
celery_app.conf.update(
    broker_url=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    result_backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),

    # Task modules
    include=[
        'rufus.tasks',  # Core Rufus tasks
    ],

    # Task settings
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='UTC',
    enable_utc=True,

    # Worker settings
    worker_prefetch_multiplier=1,  # Only fetch one task at a time (better for long-running workflows)
    task_acks_late=True,  # Acknowledge tasks after completion (safer)
    task_reject_on_worker_lost=True,

    # Result backend settings
    result_expires=3600,  # Results expire after 1 hour

    # Task routing (optional - for regional queues)
    task_create_missing_queues=True,
    task_default_queue='default',
    task_default_exchange='rufus',
    task_default_routing_key='default',
)

# Beat schedule (for cron workflows)
celery_app.conf.beat_schedule = {
    'poll-scheduled-workflows': {
        'task': 'rufus.tasks.poll_scheduled_workflows',
        'schedule': 60.0,  # Every minute
    },
}


@worker_process_init.connect
def init_worker(**kwargs):
    """
    Reset connections in each worker process after fork.
    This is necessary because connection pools cannot be shared across processes.
    """
    print("Initializing Celery worker process...")

    # Reset any global state here if needed
    # PostgreSQL connection pools will be recreated per-task


@worker_ready.connect
def on_worker_ready(**kwargs):
    """
    Called when worker is ready to accept tasks.
    """
    hostname = kwargs.get('sender').hostname
    print(f"✅ Rufus Celery worker ready: {hostname}")


@worker_shutdown.connect
def on_worker_shutdown(**kwargs):
    """
    Called when worker is shutting down.
    """
    hostname = kwargs.get('sender').hostname
    print(f"👋 Rufus Celery worker shutting down: {hostname}")
```

---

### Step 4: Add Celery Dependencies

**Update:** `pyproject.toml`

```toml
[tool.poetry.dependencies]
# ... existing dependencies ...

# Celery support (optional)
celery = {version = "^5.2", optional = true}
redis = {version = "^4.5", optional = true}

[tool.poetry.extras]
# ... existing extras ...
celery = ["celery", "redis"]
all = [
    "fastapi", "uvicorn", "starlette", "slowapi",
    "asyncpg", "rich", "uvloop",
    "websockets", "psutil", "numpy",
    "celery", "redis"  # Add Celery to all
]
```

---

### Step 5: Create CLI Integration

**Update:** `src/rufus_cli/commands/worker_cmd.py` (new file)

```python
"""
Worker management commands.
"""

import typer
from rich.console import Console

app = typer.Typer(name="worker", help="Manage Celery workers")
console = Console()


@app.command("start")
def start_worker(
    concurrency: int = typer.Option(4, "--concurrency", "-c", help="Number of worker processes"),
    queue: str = typer.Option("default", "--queue", "-Q", help="Queue to consume from"),
    loglevel: str = typer.Option("info", "--loglevel", "-l", help="Log level"),
):
    """Start a Celery worker."""
    import subprocess

    cmd = [
        "celery",
        "-A", "celery_app",
        "worker",
        f"--concurrency={concurrency}",
        f"--queue={queue}",
        f"--loglevel={loglevel}",
    ]

    console.print(f"[green]Starting Celery worker...[/green]")
    console.print(f"[dim]Command: {' '.join(cmd)}[/dim]")

    subprocess.run(cmd)


@app.command("beat")
def start_beat(
    loglevel: str = typer.Option("info", "--loglevel", "-l", help="Log level"),
):
    """Start Celery beat scheduler (for cron workflows)."""
    import subprocess

    cmd = [
        "celery",
        "-A", "celery_app",
        "beat",
        f"--loglevel={loglevel}",
    ]

    console.print(f"[green]Starting Celery beat...[/green]")
    console.print(f"[dim]Command: {' '.join(cmd)}[/dim]")

    subprocess.run(cmd)
```

---

## Usage Guide

### Installation

```bash
# Install with Celery support
pip install "rufus[celery] @ git+https://github.com/KamikaziD/rufus-sdk.git@main"

# Or with all features
pip install "rufus[all] @ git+https://github.com/KamikaziD/rufus-sdk.git@main"
```

### Configuration

```bash
# Set environment variables
export CELERY_BROKER_URL="redis://localhost:6379/0"
export CELERY_RESULT_BACKEND="redis://localhost:6379/0"
export DATABASE_URL="postgresql://user:pass@localhost/rufus"
export WORKFLOW_CONFIG_DIR="/path/to/workflow/configs"
```

### Start Workers

```bash
# Start Redis (if using Docker)
docker run -d --name redis -p 6379:6379 redis

# Start Celery worker
celery -A celery_app worker --concurrency=4 --loglevel=info

# Start Celery beat (for scheduled workflows)
celery -A celery_app beat --loglevel=info

# Or use Rufus CLI (after implementing worker commands)
rufus worker start --concurrency=4
rufus worker beat
```

### Use in Code

```python
from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
from rufus.implementations.execution.celery_executor import CeleryExecutionProvider
from celery_app import celery_app

# Initialize
persistence = PostgresPersistenceProvider(db_url)
await persistence.initialize()

execution = CeleryExecutionProvider(celery_app)

# Create workflow builder with Celery
builder = WorkflowBuilder(
    config_dir="config/",
    persistence_provider=persistence,
    execution_provider=execution
)

# Create workflow - async steps will run in Celery workers
workflow = await builder.create_workflow(
    workflow_type="OrderProcessing",
    initial_data={"order_id": "12345"}
)
```

---

## Testing

```bash
# Start all services
docker-compose up -d postgres redis

# Start worker
celery -A celery_app worker --loglevel=debug

# In another terminal, run workflow
python << 'EOF'
import asyncio
from rufus.builder import WorkflowBuilder
# ... create workflow with Celery executor ...
EOF
```

---

## Next Steps

1. ✅ Review this plan
2. Implement CeleryExecutionProvider
3. Implement rufus.tasks module
4. Update celery_app.py
5. Add Celery to pyproject.toml
6. Test with a simple workflow
7. Add worker CLI commands (optional)
8. Document in USAGE_GUIDE.md

---

**Estimated Effort:** 4-6 hours for complete implementation and testing

**Priority Files:**
1. `src/rufus/implementations/execution/celery_executor.py` (High)
2. `src/rufus/tasks.py` (High)
3. `celery_app.py` update (Medium)
4. `pyproject.toml` dependencies (Medium)
5. CLI worker commands (Low - nice to have)
