from typing import Any, Dict, Optional, List
from rufus.providers.observer import WorkflowObserver

class NoopWorkflowObserver(WorkflowObserver):
    """
    A no-operation (noop) implementation of WorkflowObserver.
    All methods do nothing. Useful as a default or when no specific
    observability is required.
    """
    async def on_workflow_started(self, workflow_id: str, workflow_type: str, initial_state: Any):
        pass

    async def on_step_executed(self, workflow_id: str, step_name: str, step_index: int, status: str, result: Optional[Dict[str, Any]], current_state: Any):
        pass

    async def on_workflow_completed(self, workflow_id: str, workflow_type: str, final_state: Any):
        pass

    async def on_workflow_failed(self, workflow_id: str, workflow_type: str, error_message: str, current_state: Any):
        pass

    async def on_workflow_status_changed(self, workflow_id: str, old_status: str, new_status: str, current_step_name: Optional[str], final_result: Optional[Dict[str, Any]] = None):
        pass

    async def on_workflow_rolled_back(self, workflow_id: str, workflow_type: str, message: str, current_state: Any, completed_steps_stack: List[Dict[str, Any]]):
        pass

    async def on_step_failed(self, workflow_id: str, step_name: str, step_index: int, error_message: str, current_state: Any):
        pass