from abc import ABC, abstractmethod
from typing import List, Any, Dict, Optional

class PersistenceProvider(ABC):
    """Abstracts the storage of workflow state and related operational data."""

    @abstractmethod
    async def initialize(self):
        """Initializes the persistence provider (e.g., connects to DB, sets up client)."""
        pass

    @abstractmethod
    async def close(self):
        """Closes any open connections or resources."""
        pass

    @abstractmethod
    async def save_workflow(self, workflow_id: str, workflow_data: Dict[str, Any]):
        """Saves the complete workflow data."""
        pass

    @abstractmethod
    async def load_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Loads the complete workflow data."""
        pass

    @abstractmethod
    async def list_workflows(self, **filters) -> List[Dict[str, Any]]:
        """Lists workflows based on filters."""
        pass

    @abstractmethod
    async def log_execution(self, workflow_id: str, log_level: str, message: str, step_name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Logs an execution event for a workflow, e.g., for debugging."""
        pass

    @abstractmethod
    async def log_compensation(self, execution_id: str, step_name: str, step_index: int, action_type: str, action_result: Dict[str, Any], state_before: Optional[Dict[str, Any]] = None, state_after: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None, executed_by: Optional[str] = None):
        """Logs a compensation action for a saga, including state snapshots."""
        pass

    @abstractmethod
    async def log_audit_event(self, workflow_id: str, event_type: str, step_name: Optional[str] = None, user_id: Optional[str] = None, worker_id: Optional[str] = None, old_state: Optional[Dict[str, Any]] = None, new_state: Optional[Dict[str, Any]] = None, decision_rationale: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Logs an audit event for compliance and traceability."""
        pass

    @abstractmethod
    async def record_metric(self, workflow_id: str, workflow_type: str, metric_name: str, metric_value: float, unit: Optional[str] = None, step_name: Optional[str] = None, tags: Optional[Dict[str, Any]] = None):
        """Records a performance or operational metric."""
        pass

    @abstractmethod
    async def get_workflow_metrics(self, workflow_id: str, limit: int = 100) -> List[Dict]:
        """Retrieves performance metrics for a specific workflow."""
        pass

    @abstractmethod
    async def get_workflow_summary(self, hours: int = 24) -> List[Dict]:
        """Retrieves a summary of workflow executions over a period."""
        pass

    @abstractmethod
    async def register_scheduled_workflow(self, schedule_name: str, workflow_type: str, cron_expression: str, initial_data: Optional[Dict[str, Any]] = None, enabled: bool = True):
        """Registers or updates a scheduled workflow."""
        pass
    
    @abstractmethod
    async def create_task_record(self, execution_id: str, step_name: str, step_index: int, task_data: Optional[Dict[str, Any]] = None, idempotency_key: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None, max_retries: int = 3) -> Dict[str, Any]:
        """Creates a record for an asynchronous task."""
        pass

    @abstractmethod
    async def update_task_status(self, task_id: str, status: str, result: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None) -> None:
        """Updates the status of an asynchronous task record."""
        pass

    @abstractmethod
    async def get_task_record(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves an asynchronous task record."""
        pass

    # Synchronous wrappers for Celery tasks might also be needed in the interface
    # For now, I'll assume that the WorkflowEngine or ExecutionProvider handles the async->sync bridging
    # or that these sync methods are called directly on the concrete implementation when in a sync context.

    @abstractmethod
    def log_execution_sync(self, workflow_id: str, log_level: str, message: str, step_name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Synchronously logs an execution event for a workflow."""
        pass

    @abstractmethod
    def log_audit_event_sync(self, workflow_id: str, event_type: str, step_name: Optional[str] = None, user_id: Optional[str] = None, worker_id: Optional[str] = None, old_state: Optional[Dict[str, Any]] = None, new_state: Optional[Dict[str, Any]] = None, decision_rationale: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Synchronously logs an audit event for compliance."""
        pass

    @abstractmethod
    def log_compensation_sync(self, execution_id: str, step_name: str, step_index: int, action_type: str, action_result: Dict[str, Any], state_before: Optional[Dict[str, Any]] = None, state_after: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None, executed_by: Optional[str] = None):
        """Synchronously logs a compensation action for a saga."""
        pass
    
    @abstractmethod
    def record_metric_sync(self, workflow_id: str, workflow_type: str, metric_name: str, metric_value: float, unit: Optional[str] = None, step_name: Optional[str] = None, tags: Optional[Dict[str, Any]] = None):
        """Synchronously records a performance or operational metric."""
        pass

    @abstractmethod
    def register_scheduled_workflow_sync(self, schedule_name: str, workflow_type: str, cron_expression: str, initial_data: Optional[Dict[str, Any]] = None, enabled: bool = True):
        """Synchronously registers or updates a scheduled workflow."""
        pass

    @abstractmethod
    def create_task_record_sync(self, execution_id: str, step_name: str, step_index: int, task_data: Optional[Dict[str, Any]] = None, idempotency_key: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None, max_retries: int = 3) -> Dict[str, Any]:
        """Synchronously creates a record for an asynchronous task."""
        pass

    @abstractmethod
    def update_task_status_sync(self, task_id: str, status: str, result: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None) -> None:
        """Synchronously updates the status of an asynchronous task record."""
        pass
    
    @abstractmethod
    def get_task_record_sync(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Synchronously retrieves an asynchronous task record."""
        pass

    @abstractmethod
    async def get_active_workflows(self, limit: int = 100) -> List[Dict]:
        """Gets a list of currently active workflows."""
        pass
