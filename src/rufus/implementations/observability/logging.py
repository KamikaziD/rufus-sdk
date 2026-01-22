import logging
from typing import Any, Dict, Optional, List
from rufus.providers.observer import WorkflowObserver

logger = logging.getLogger(__name__)

class LoggingObserver(WorkflowObserver):
    """
    An implementation of WorkflowObserver that logs workflow events using Python's standard logging module.
    """
    async def on_workflow_started(self, workflow_id: str, workflow_type: str, initial_state: Any):
        logger.info(f"Workflow Started: ID={workflow_id}, Type={workflow_type}, InitialState={initial_state}")

    async def on_step_executed(self, workflow_id: str, step_name: str, step_index: int, status: str, result: Optional[Dict[str, Any]], current_state: Any):
        logger.info(f"Step Executed: Workflow={workflow_id}, Step={step_name}({step_index}), Status={status}, Result={result}, State={current_state}")

    async def on_workflow_completed(self, workflow_id: str, workflow_type: str, final_state: Any):
        logger.info(f"Workflow Completed: ID={workflow_id}, Type={workflow_type}, FinalState={final_state}")

    async def on_workflow_failed(self, workflow_id: str, workflow_type: str, error_message: str, current_state: Any):
        logger.error(f"Workflow Failed: ID={workflow_id}, Type={workflow_type}, Error={error_message}, State={current_state}")

    async def on_workflow_status_changed(self, workflow_id: str, old_status: str, new_status: str, current_step_name: Optional[str], final_result: Optional[Dict[str, Any]] = None):
        logger.info(f"Workflow Status Changed: ID={workflow_id}, Old={old_status}, New={new_status}, Step={current_step_name}, Result={final_result}")

    async def on_workflow_rolled_back(self, workflow_id: str, workflow_type: str, message: str, current_state: Any, completed_steps_stack: List[Dict[str, Any]]):
        logger.warning(f"Workflow Rolled Back: ID={workflow_id}, Type={workflow_type}, Message={message}, State={current_state}, Steps={completed_steps_stack}")

    async def on_step_failed(self, workflow_id: str, step_name: str, step_index: int, error_message: str, current_state: Any):
        logger.error(f"Step Failed: Workflow={workflow_id}, Step={step_name}({step_index}), Error={error_message}, State={current_state}")