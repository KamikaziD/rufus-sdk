from abc import ABC, abstractmethod
from typing import Any, List, Dict, Optional, Callable

class ExecutionProvider(ABC):
    """Abstracts the execution of async and parallel steps."""

    @abstractmethod
    def execute_sync_step_function(self, step_func: Callable, state: Any, context: Any) -> Any:
        """Executes a synchronous step function immediately."""
        pass

    @abstractmethod
    def dispatch_async_task(self, func_path: str, state_data: Dict[str, Any], workflow_id: str, current_step_index: int, data_region: Optional[str], **kwargs) -> str:
        """Dispatches an asynchronous task and returns a task ID."""
        pass

    @abstractmethod
    def dispatch_parallel_tasks(self, tasks: List[Any], state_data: Dict[str, Any], workflow_id: str, current_step_index: int, merge_function_path: Optional[str], data_region: Optional[str]) -> str:
        """Dispatches multiple tasks for parallel execution and returns a group ID."""
        pass

    @abstractmethod
    def report_child_status_to_parent(self, child_id: str, parent_id: str, child_new_status: str, child_current_step_name: Optional[str], child_result: Optional[Dict[str, Any]]):
        """Reports the status of a child workflow to its parent."""
        pass

    @abstractmethod
    def dispatch_independent_workflow(self, workflow_id: str):
        """Dispatches an independent workflow to be run."""
        pass

    @abstractmethod
    def register_scheduled_workflow(self, schedule_name: str, workflow_type: str, cron_expression: str, initial_data: Dict[str, Any]):
        """Registers a workflow to be scheduled for execution."""
        pass