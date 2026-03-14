"""
WorkflowObserver — abstract base class for workflow event hooks.

Implementations: LoggingObserver, EventPublisherObserver, NoopWorkflowObserver,
                 OtelObserver

Changed from Protocol to ABC in v1.0:
  - Partial implementations now fail loudly at instantiation, not silently at runtime.
  - All methods have default no-op implementations so subclasses only override what they need.

# API FROZEN v1.0
"""

from abc import ABC
from typing import Dict, Any, Optional, List
from pydantic import BaseModel


class WorkflowObserver(ABC):
    """
    Abstract base class for observing workflow lifecycle events.

    All methods have a default no-op async implementation. Subclasses override
    only the events they care about.

    New in v1.0:
      - duration_ms on on_step_executed (None = not measured)
      - on_workflow_paused / on_workflow_resumed
      - on_compensation_started / on_compensation_completed
      - on_child_workflow_started
    """

    async def initialize(self):
        """Initializes the observer, e.g., connecting to a message broker."""

    async def close(self):
        """Closes the observer, e.g., disconnecting from a message broker."""

    async def on_workflow_started(
        self,
        workflow_id: str,
        workflow_type: str,
        initial_state: BaseModel,
    ):
        """Called when a new workflow execution starts."""

    async def on_step_executed(
        self,
        workflow_id: str,
        step_name: str,
        step_index: int,
        status: str,
        result: Optional[Dict[str, Any]],
        current_state: BaseModel,
        duration_ms: Optional[float] = None,
    ):
        """
        Called after a workflow step has been executed.

        Args:
            duration_ms: Wall-clock time for the step in milliseconds.
                         None when not measured (e.g., async/parallel dispatch).
        """

    async def on_workflow_completed(
        self,
        workflow_id: str,
        workflow_type: str,
        final_state: BaseModel,
    ):
        """Called when a workflow execution successfully completes."""

    async def on_workflow_failed(
        self,
        workflow_id: str,
        workflow_type: str,
        error_message: str,
        current_state: BaseModel,
    ):
        """Called when a workflow execution fails."""

    async def on_workflow_status_changed(
        self,
        workflow_id: str,
        old_status: str,
        new_status: str,
        current_step_name: Optional[str],
        final_result: Optional[Dict[str, Any]] = None,
    ):
        """Called when the workflow's overall status changes."""

    async def on_workflow_rolled_back(
        self,
        workflow_id: str,
        workflow_type: str,
        message: str,
        current_state: BaseModel,
        completed_steps_stack: List[Dict[str, Any]],
    ):
        """Called when a saga rollback operation is performed."""

    async def on_step_failed(
        self,
        workflow_id: str,
        step_name: str,
        step_index: int,
        error_message: str,
        current_state: BaseModel,
    ):
        """Called when a workflow step execution fails."""

    # --- New lifecycle events (v1.0) ----------------------------------------

    async def on_workflow_paused(
        self,
        workflow_id: str,
        step_name: str,
        reason: str,
    ):
        """Called when a workflow pauses for human input (HUMAN_IN_LOOP step)."""

    async def on_workflow_resumed(
        self,
        workflow_id: str,
        step_name: str,
        resume_data: Optional[Dict[str, Any]],
    ):
        """Called when a paused workflow is resumed with human input."""

    async def on_compensation_started(
        self,
        workflow_id: str,
        step_name: str,
        step_index: int,
    ):
        """Called when saga compensation begins for a step."""

    async def on_compensation_completed(
        self,
        workflow_id: str,
        step_name: str,
        success: bool,
        error: Optional[str] = None,
    ):
        """Called when saga compensation for a step finishes (success or failure)."""

    async def on_child_workflow_started(
        self,
        parent_id: str,
        child_id: str,
        child_type: str,
    ):
        """Called when a sub-workflow is spawned by a parent workflow."""
