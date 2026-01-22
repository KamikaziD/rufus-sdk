from typing import Protocol, Dict, Any, Optional, List
from pydantic import BaseModel
import asyncio

class WorkflowObserver(Protocol):
    """
    Protocol for observing workflow events.
    Implementations can log, publish to message queues, update UIs, etc.
    """
    async def initialize(self):
        """Initializes the observer, e.g., connecting to a message broker."""
        pass # Default no-op implementation

    async def close(self):
        """Closes the observer, e.g., disconnecting from a message broker."""
        pass # Default no-op implementation

    async def on_workflow_started(self, workflow_id: str, workflow_type: str, initial_state: BaseModel):
        """Called when a new workflow execution starts."""
        pass

    async def on_step_executed(self, workflow_id: str, step_name: str, step_index: int, status: str, result: Optional[Dict[str, Any]], current_state: BaseModel):
        """Called after a workflow step has been executed."""
        pass

    async def on_workflow_completed(self, workflow_id: str, workflow_type: str, final_state: BaseModel):
        """Called when a workflow execution successfully completes."""
        pass

    async def on_workflow_failed(self, workflow_id: str, workflow_type: str, error_message: str, current_state: BaseModel):
        """Called when a workflow execution fails."""
        pass

    async def on_workflow_status_changed(self, workflow_id: str, old_status: str, new_status: str, current_step_name: Optional[str], final_result: Optional[Dict[str, Any]] = None):
        """Called when the workflow's overall status changes."""
        pass

    async def on_workflow_rolled_back(self, workflow_id: str, workflow_type: str, message: str, current_state: BaseModel, completed_steps_stack: List[Dict[str, Any]]):
        """Called when a saga rollback operation is performed."""
        pass

    async def on_step_failed(self, workflow_id: str, step_name: str, step_index: int, error_message: str, current_state: BaseModel):
        """Called when a workflow step execution fails."""
        pass