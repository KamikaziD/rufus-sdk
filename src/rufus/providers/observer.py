from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List

class WorkflowObserver(ABC):
    """Provides hooks for observing workflow events."""

    def on_workflow_started(self, workflow_id: str, workflow_type: str, initial_state: Any):
        """Called when a workflow starts."""
        pass

    def on_step_executed(self, workflow_id: str, step_name: str, step_index: int, status: str, result: Optional[Dict[str, Any]], current_state: Any):
        """Called after a step is executed."""
        pass

    def on_workflow_completed(self, workflow_id: str, workflow_type: str, final_state: Any):
        """Called when a workflow completes."""
        pass

    def on_workflow_failed(self, workflow_id: str, workflow_type: str, error_message: str, current_state: Any):
        """Called when a workflow fails."""
        pass

    def on_workflow_status_changed(self, workflow_id: str, old_status: str, new_status: str, current_step_name: Optional[str], final_result: Optional[Dict[str, Any]] = None):
        """Called when the overall workflow status changes."""
        pass

    def on_workflow_rolled_back(self, workflow_id: str, workflow_type: str, message: str, current_state: Any, completed_steps_stack: List[Dict[str, Any]]):
        """Called when a workflow undergoes a saga rollback."""
        pass

    def on_step_failed(self, workflow_id: str, step_name: str, step_index: int, error_message: str, current_state: Any):
        """Called when a step execution fails."""
        pass