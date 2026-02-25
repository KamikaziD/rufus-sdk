"""
CeleryExecutionProvider

Production-grade distributed execution provider using Celery for async
and parallel task execution.

Key features:
- Async task execution across worker pool
- Parallel task execution with result merging
- Sub-workflow orchestration
- Regional queue routing
- Automatic workflow resumption after task completion
"""
from typing import Dict, Any, List, Optional, Callable
from rufus.providers.execution import ExecutionProvider
from rufus.models import BaseModel, StepContext
from rufus.utils.postgres_executor import pg_executor
import logging

logger = logging.getLogger(__name__)


class CeleryExecutionProvider(ExecutionProvider):
    """
    Distributed execution provider using Celery task queue.

    This provider enables:
    - Asynchronous task execution across multiple workers
    - Parallel task execution with configurable merge strategies
    - Sub-workflow delegation
    - Fire-and-forget workflows
    - Regional queue routing

    Unlike SyncExecutor, CeleryExecutionProvider:
    - Pauses workflows when dispatching async tasks
    - Resumes workflows via Celery callbacks after task completion
    - Requires Redis/RabbitMQ broker and result backend
    - Distributes work across multiple worker processes

    Configuration:
        export CELERY_BROKER_URL="redis://localhost:6379/0"
        export CELERY_RESULT_BACKEND="redis://localhost:6379/0"

    Starting workers:
        celery -A rufus.celery_app worker --loglevel=info

    Regional routing:
        celery -A rufus.celery_app worker -Q us-east-1 --loglevel=info
    """

    def __init__(self, workflow_builder=None):
        from rufus.celery_app import celery_app
        self.celery_app = celery_app
        self._engine = None
        self._workflow_builder = workflow_builder  # Direct reference for worker context
        logger.info("CeleryExecutionProvider initialized")

    async def initialize(self, engine: Any):
        """Initializes the executor with a reference to the WorkflowEngine."""
        self._engine = engine
        logger.info("CeleryExecutionProvider ready")

    def _get_workflow_builder(self):
        """Returns workflow_builder from engine or direct reference (worker context)."""
        if self._engine is not None:
            return self._engine.workflow_builder
        if self._workflow_builder is not None:
            return self._workflow_builder
        raise RuntimeError(
            "CeleryExecutionProvider has no workflow_builder. "
            "Call initialize(engine) or pass workflow_builder= to constructor."
        )

    async def close(self):
        """No cleanup needed for Celery (workers are separate processes)."""
        logger.info("CeleryExecutionProvider closed")

    async def execute_sync_step_function(self, func: Callable, state: BaseModel, context: StepContext) -> Dict[str, Any]:
        """
        Executes a synchronous step function directly in the current process.

        This is used for STANDARD steps that don't require async execution.
        """
        import asyncio

        # Ensure that the function itself is awaited if it's an async function
        if asyncio.iscoroutinefunction(func):
            # Await async function
            result = await func(state=state, context=context)
        else:
            result = func(state=state, context=context)

        # Ensure result is a dict
        return result if isinstance(result, dict) else {}

    async def dispatch_async_task(self,
                           func_path: str,
                           state_data: Dict[str, Any],
                           workflow_id: str,
                           current_step_index: int,
                           data_region: Optional[str] = None,
                           **kwargs) -> Dict[str, Any]:
        """
        Dispatches an asynchronous task to Celery workers.

        The workflow will pause (status = PENDING_ASYNC) and resume when the
        task completes via the resume_from_async_task callback.

        Args:
            func_path: Python path to task function (e.g., "my_app.tasks.process_payment")
            state_data: Workflow state as dict
            workflow_id: Workflow UUID
            current_step_index: Current step index (for resumption)
            data_region: Optional region for queue routing

        Returns:
            Celery task ID
        """
        from rufus.tasks import resume_from_async_task

        # Import the task function
        func = self._get_workflow_builder()._import_from_string(func_path)
        if not func:
            raise ValueError(f"Task function not found: {func_path}")

        # Check if function is a Celery task
        if not hasattr(func, 'apply_async'):
            raise ValueError(
                f"Function {func_path} is not a Celery task. "
                f"Decorate with @celery_app.task"
            )

        # Strip internal engine params — NOT to be forwarded to user task functions
        merge_strategy = kwargs.pop('merge_strategy', 'SHALLOW')
        merge_conflict_behavior = kwargs.pop('merge_conflict_behavior', 'PREFER_NEW')
        kwargs.pop('_previous_step_result', None)

        # Prepare task payload — only user_input kwargs remain in **kwargs
        task_kwargs = {
            'state': state_data,
            'workflow_id': workflow_id,
            **kwargs
        }

        # Chain task with workflow resumption
        # Task result → resume_from_async_task(result, workflow_id, current_step_index)
        async_task = func.apply_async(
            kwargs=task_kwargs,
            link=resume_from_async_task.s(workflow_id, current_step_index),
            queue=data_region if data_region else 'default'
        )

        logger.info(f"Dispatched async task {async_task.id} for workflow {workflow_id}")
        return {"_async_dispatch": True, "task_id": async_task.id}

    async def dispatch_parallel_tasks(self,
                               tasks: List[Any],
                               state_data: Dict[str, Any],
                               workflow_id: str,
                               current_step_index: int,
                               merge_function_path: Optional[str] = None,
                               data_region: Optional[str] = None,
                               merge_strategy: str = "SHALLOW",
                               merge_conflict_behavior: str = "PREFER_NEW") -> Dict[str, Any]:
        """
        Dispatches multiple tasks for parallel execution.

        Tasks run concurrently across Celery workers. When all tasks complete,
        results are merged and the workflow resumes.

        Args:
            tasks: List of ParallelExecutionTask configs
            state_data: Workflow state as dict
            workflow_id: Workflow UUID
            current_step_index: Current step index
            merge_function_path: Optional custom merge function
            data_region: Optional region for queue routing
            merge_strategy: Strategy for merging results (SHALLOW or DEEP)
            merge_conflict_behavior: How to handle conflicts (PREFER_NEW, PREFER_OLD, RAISE_ERROR)

        Returns:
            Celery group task ID
        """
        from celery import chord
        from rufus.tasks import merge_and_resume_parallel_tasks

        # Build Celery task signatures
        celery_tasks = []
        for task_config in tasks:
            func_path = task_config.func_path
            func = self._get_workflow_builder()._import_from_string(func_path)

            if not func or not hasattr(func, 'apply_async'):
                raise ValueError(f"Invalid Celery task: {func_path}")

            # Create task signature — include per-task kwargs for dynamic fan-out
            task_sig = func.s(state=state_data, workflow_id=workflow_id, **task_config.kwargs)
            celery_tasks.append(task_sig)

        # Create callback signature
        callback = merge_and_resume_parallel_tasks.s(
            workflow_id,
            current_step_index,
            merge_function_path,
            merge_strategy,
            merge_conflict_behavior
        )

        # Use chord: parallel tasks → merge results → resume workflow
        workflow = chord(celery_tasks, queue=data_region if data_region else 'default')(callback)

        logger.info(f"Dispatched parallel task group {workflow.id} for workflow {workflow_id}")
        return {"_async_dispatch": True, "task_id": workflow.id}

    async def dispatch_sub_workflow(self, child_id: str, parent_id: str,
                                     sub_workflow_type: str = None, initial_data: dict = None):
        """
        Dispatches a sub-workflow for execution.

        The child workflow runs independently until completion, then resumes
        the parent workflow via execute_sub_workflow task.

        Args:
            child_id: Child workflow UUID
            parent_id: Parent workflow UUID
            sub_workflow_type: Ignored — child is already persisted by caller
            initial_data: Ignored — child is already persisted by caller
        """
        from rufus.tasks import execute_sub_workflow

        task = execute_sub_workflow.apply_async(
            args=(child_id, parent_id)
        )

        logger.info(f"Dispatched sub-workflow {child_id} for parent {parent_id}, task {task.id}")
        return {"_async_dispatch": True, "task_id": task.id}

    async def report_child_status_to_parent(self,
                                     child_id: str,
                                     parent_id: str,
                                     child_new_status: str,
                                     child_current_step_name: Optional[str] = None,
                                     child_result: Optional[Dict[str, Any]] = None):
        """
        Reports child workflow status to parent.

        This is called automatically when a child workflow completes or fails.
        The parent workflow resumes with merged child results.

        Args:
            child_id: Child workflow UUID
            parent_id: Parent workflow UUID
            child_new_status: Child's new status (COMPLETED, FAILED, etc.)
            child_current_step_name: Child's current step
            child_result: Child's final result
        """
        from rufus.tasks import resume_parent_from_child

        if child_new_status == "COMPLETED":
            task = resume_parent_from_child.apply_async(
                args=(parent_id, child_id)
            )
            logger.info(f"Reported child {child_id} completion to parent {parent_id}, task {task.id}")
            return task.id
        else:
            logger.warning(f"Child {child_id} status {child_new_status} - parent {parent_id} may need manual intervention")

    def dispatch_independent_workflow(self, workflow_id: str):
        """
        Dispatches an independent workflow (fire-and-forget pattern).

        The workflow runs to completion without blocking the caller.
        Use this for background jobs, notifications, etc.

        Args:
            workflow_id: Workflow UUID to execute
        """
        from rufus.tasks import execute_independent_workflow

        task = execute_independent_workflow.apply_async(
            args=(workflow_id,)
        )

        logger.info(f"Dispatched independent workflow {workflow_id}, task {task.id}")
        return task.id

    def register_scheduled_workflow(self,
                                   schedule_name: str,
                                   workflow_type: str,
                                   cron_expression: str,
                                   initial_data: Dict[str, Any]):
        """
        Registers a workflow to be scheduled for execution.

        Inserts a row into the `scheduled_workflows` DB table. Celery Beat
        then polls this table via `poll_scheduled_workflows` every minute.

        Args:
            schedule_name: Unique schedule identifier
            workflow_type: Workflow type to instantiate
            cron_expression: Cron schedule (e.g., "0 0 * * *")
            initial_data: Initial workflow state data
        """
        import json
        from datetime import datetime, timezone
        from rufus import tasks

        provider = tasks._persistence_provider
        if provider is None:
            raise RuntimeError(
                "Persistence provider not initialized — cannot register scheduled workflow."
            )

        try:
            from croniter import croniter
            next_run = croniter(cron_expression, datetime.now(timezone.utc)).get_next(datetime)
        except Exception as e:
            raise ValueError(f"Invalid cron expression '{cron_expression}': {e}") from e

        async def _insert():
            async with provider.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO scheduled_workflows
                        (id, schedule_name, workflow_type, cron_expression,
                         initial_data, enabled, next_run_at, run_count, created_at, updated_at)
                    VALUES
                        (gen_random_uuid(), $1, $2, $3, $4, true, $5, 0, now(), now())
                    ON CONFLICT (schedule_name) DO UPDATE SET
                        workflow_type   = EXCLUDED.workflow_type,
                        cron_expression = EXCLUDED.cron_expression,
                        initial_data    = EXCLUDED.initial_data,
                        enabled         = true,
                        next_run_at     = EXCLUDED.next_run_at,
                        updated_at      = now()
                    """,
                    schedule_name,
                    workflow_type,
                    cron_expression,
                    json.dumps(initial_data),
                    next_run,
                )

        pg_executor.run_coroutine_sync(_insert())
        logger.info(
            f"[SCHEDULER] Registered schedule '{schedule_name}' "
            f"({workflow_type}) next_run_at={next_run.isoformat()}"
        )
