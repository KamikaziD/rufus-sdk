"""
ExecutionProvider — abstract interface for task dispatch and execution environments.

Implementations: SyncExecutor, CeleryExecutionProvider, ThreadPoolExecutionProvider,
                 PostgresExecutor, BrowserSyncExecutor

# API FROZEN v1.0
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Dict, Optional, Callable


# ---------------------------------------------------------------------------
# ExecutionContext — tracing / actor context forwarded with every task
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ExecutionContext:
    """
    Carries tracing and actor metadata alongside a dispatched task.

    Passed as an optional additive parameter to dispatch_async_task and
    dispatch_parallel_tasks. Existing callers that pass None are unaffected.
    """
    trace_id: str
    workflow_id: str
    step_name: str
    attempt: int = 1
    actor_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class ExecutionProvider(ABC):
    """Abstracts the execution of async and parallel workflow steps."""

    @abstractmethod
    def execute_sync_step_function(
        self,
        step_func: Callable,
        state: Any,
        context: "StepContext",  # ruvon.models.StepContext
    ) -> Any:
        """Executes a synchronous step function immediately."""

    @abstractmethod
    def dispatch_async_task(
        self,
        func_path: str,
        state_data: Dict[str, Any],
        workflow_id: str,
        current_step_index: int,
        data_region: Optional[str],
        execution_context: Optional[ExecutionContext] = None,
        **kwargs,
    ) -> str:
        """Dispatches an asynchronous task and returns a task ID."""

    @abstractmethod
    def dispatch_parallel_tasks(
        self,
        tasks: List[Any],
        state_data: Dict[str, Any],
        workflow_id: str,
        current_step_index: int,
        merge_function_path: Optional[str],
        data_region: Optional[str],
        execution_context: Optional[ExecutionContext] = None,
    ) -> str:
        """Dispatches multiple tasks for parallel execution and returns a group ID."""

    @abstractmethod
    def report_child_status_to_parent(
        self,
        child_id: str,
        parent_id: str,
        child_new_status: str,
        child_current_step_name: Optional[str],
        child_result: Optional[Dict[str, Any]],
    ):
        """Reports the status of a child workflow to its parent."""

    @abstractmethod
    def dispatch_independent_workflow(self, workflow_id: str):
        """Dispatches an independent workflow to be run."""

    @abstractmethod
    def register_scheduled_workflow(
        self,
        schedule_name: str,
        workflow_type: str,
        cron_expression: str,
        initial_data: Dict[str, Any],
    ):
        """Registers a workflow to be scheduled for execution."""

    # --- Task management methods (new in v1.0) ------------------------------

    def get_task_status(self, task_id: str) -> str:
        """
        Returns the current status string for the given task ID.

        Default raises NotImplementedError. Backends that support task
        inspection (Celery, PostgresExecutor) should override this.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_task_status()."
        )

    def cancel_task(self, task_id: str) -> bool:
        """
        Requests cancellation of a pending/running task.

        Returns True if the cancellation request was accepted, False otherwise.
        Default raises NotImplementedError.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement cancel_task()."
        )
