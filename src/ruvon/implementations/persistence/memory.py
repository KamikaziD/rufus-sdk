import time
from typing import List, Dict, Any, Optional

from ruvon.providers.persistence import PersistenceProvider
from ruvon.providers.dtos import WorkflowRecord, TaskRecord

class InMemoryPersistence(PersistenceProvider):
    """An in-memory persistence provider for testing and simple use cases."""

    def __init__(self):
        self._workflows: Dict[str, Dict[str, Any]] = {}
        self._execution_logs: List[Dict[str, Any]] = []
        self._compensation_logs: List[Dict[str, Any]] = []
        self._audit_events: List[Dict[str, Any]] = []
        self._metrics: List[Dict[str, Any]] = []
        self._scheduled_workflows: Dict[str, Dict[str, Any]] = {}
        self._task_records: Dict[str, Dict[str, Any]] = {}


    async def initialize(self):
        """Initializes the in-memory store (no-op for in-memory)."""
        print("[InMemoryPersistence] Initialized (no-op)")
        pass

    async def close(self):
        """Closes the in-memory store (no-op for in-memory)."""
        print("[InMemoryPersistence] Closed (no-op)")
        pass

    async def save_workflow(self, workflow_id: str, workflow_data: Dict[str, Any]):
        """Saves the workflow state to the in-memory dictionary."""
        self._workflows[workflow_id] = workflow_data

    async def load_workflow(self, workflow_id: str) -> Optional[WorkflowRecord]:
        """Loads the workflow state from the in-memory dictionary."""
        data = self._workflows.get(workflow_id)
        if data is None:
            return None
        return WorkflowRecord(
            id=data.get("id", workflow_id),
            workflow_type=data.get("workflow_type", ""),
            status=data.get("status", "ACTIVE"),
            current_step=data.get("current_step", 0),
            state=data.get("state", {}),
            steps_config=data.get("steps_config", []),
            state_model_path=data.get("state_model_path", ""),
            workflow_version=data.get("workflow_version"),
            definition_snapshot=data.get("definition_snapshot"),
            saga_mode=data.get("saga_mode", False),
            completed_steps_stack=data.get("completed_steps_stack", []),
            parent_execution_id=data.get("parent_execution_id"),
            blocked_on_child_id=data.get("blocked_on_child_id"),
            data_region=data.get("data_region"),
            priority=data.get("priority"),
            idempotency_key=data.get("idempotency_key"),
            metadata=data.get("metadata"),
            owner_id=data.get("owner_id"),
            org_id=data.get("org_id"),
        )

    async def list_workflows(self, **filters) -> List[Dict[str, Any]]:
        """Lists workflows from the in-memory dictionary, with optional filtering."""
        filtered_workflows = []
        for wf_data in self._workflows.values():
            match = True
            for key, value in filters.items():
                if wf_data.get(key) != value:
                    match = False
                    break
            if match:
                filtered_workflows.append(wf_data)
        return filtered_workflows

    async def log_execution(self, workflow_id: str, log_level: str, message: str, step_name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Logs an execution event to in-memory list."""
        self._execution_logs.append({
            "workflow_id": workflow_id,
            "log_level": log_level,
            "message": message,
            "step_name": step_name,
            "metadata": metadata,
            "timestamp": time.time()
        })
        # print(f"[InMemoryPersistence - Log] {log_level} for {workflow_id} (Step: {step_name}): {message}")

    def log_execution_sync(self, workflow_id: str, log_level: str, message: str, step_name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Synchronously logs an execution event."""
        # For in-memory, we can directly call the async version and ignore await.
        # In a real sync context, this might need an async_to_sync wrapper.
        self.log_execution(workflow_id, log_level, message, step_name, metadata)


    async def log_compensation(self, execution_id: str, step_name: str, step_index: int, action_type: str, action_result: Dict[str, Any], state_before: Optional[Dict[str, Any]] = None, state_after: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None, executed_by: Optional[str] = None):
        """Logs a compensation event to in-memory list."""
        self._compensation_logs.append({
            "execution_id": execution_id,
            "step_name": step_name,
            "step_index": step_index,
            "action_type": action_type,
            "action_result": action_result,
            "state_before": state_before,
            "state_after": state_after,
            "error_message": error_message,
            "executed_by": executed_by,
            "timestamp": time.time()
        })
        # print(f"[InMemoryPersistence - Compensation Log] Workflow {execution_id}, Step {step_name}: {action_type} - {error_message or action_result}")

    def log_compensation_sync(self, execution_id: str, step_name: str, step_index: int, action_type: str, action_result: Dict[str, Any], state_before: Optional[Dict[str, Any]] = None, state_after: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None, executed_by: Optional[str] = None):
        """Synchronously logs a compensation event."""
        self.log_compensation(execution_id, step_name, step_index, action_type, action_result, state_before, state_after, error_message, executed_by)


    async def log_audit_event(self, workflow_id: str, event_type: str, step_name: Optional[str] = None, user_id: Optional[str] = None, worker_id: Optional[str] = None, old_state: Optional[Dict[str, Any]] = None, new_state: Optional[Dict[str, Any]] = None, decision_rationale: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Logs an audit event to in-memory list."""
        self._audit_events.append({
            "workflow_id": workflow_id,
            "event_type": event_type,
            "step_name": step_name,
            "user_id": user_id,
            "worker_id": worker_id,
            "old_state": old_state,
            "new_state": new_state,
            "decision_rationale": decision_rationale,
            "metadata": metadata,
            "timestamp": time.time()
        })

    def log_audit_event_sync(self, workflow_id: str, event_type: str, step_name: Optional[str] = None, user_id: Optional[str] = None, worker_id: Optional[str] = None, old_state: Optional[Dict[str, Any]] = None, new_state: Optional[Dict[str, Any]] = None, decision_rationale: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Synchronously logs an audit event."""
        self.log_audit_event(workflow_id, event_type, step_name, user_id, worker_id, old_state, new_state, decision_rationale, metadata)


    async def record_metric(self, workflow_id: str, workflow_type: str, metric_name: str, metric_value: float, unit: Optional[str] = None, step_name: Optional[str] = None, tags: Optional[Dict[str, Any]] = None):
        """Records a performance or operational metric to in-memory list."""
        self._metrics.append({
            "workflow_id": workflow_id,
            "workflow_type": workflow_type,
            "metric_name": metric_name,
            "metric_value": metric_value,
            "unit": unit,
            "step_name": step_name,
            "tags": tags,
            "timestamp": time.time()
        })

    def record_metric_sync(self, workflow_id: str, workflow_type: str, metric_name: str, metric_value: float, unit: Optional[str] = None, step_name: Optional[str] = None, tags: Optional[Dict[str, Any]] = None):
        """Synchronously records a performance or operational metric."""
        self.record_metric(workflow_id, workflow_type, metric_name, metric_value, unit, step_name, tags)


    async def get_workflow_metrics(self, workflow_id: str, limit: int = 100) -> List[Dict]:
        """Retrieves performance metrics for a specific workflow from in-memory list."""
        return [m for m in self._metrics if m["workflow_id"] == workflow_id][:limit]

    async def get_workflow_summary(self, hours: int = 24) -> List[Dict]:
        """Retrieves a summary of workflow executions (basic in-memory)."""
        print("WARNING: get_workflow_summary not fully implemented for InMemoryPersistence.")
        return []

    async def register_scheduled_workflow(self, schedule_name: str, workflow_type: str, cron_expression: str, initial_data: Optional[Dict[str, Any]] = None, enabled: bool = True):
        """Registers a scheduled workflow in-memory."""
        self._scheduled_workflows[schedule_name] = {
            "workflow_type": workflow_type,
            "cron_expression": cron_expression,
            "initial_data": initial_data,
            "enabled": enabled,
            "timestamp": time.time()
        }

    def register_scheduled_workflow_sync(self, schedule_name: str, workflow_type: str, cron_expression: str, initial_data: Optional[Dict[str, Any]] = None, enabled: bool = True):
        """Synchronously registers a scheduled workflow."""
        self.register_scheduled_workflow(schedule_name, workflow_type, cron_expression, initial_data, enabled)


    async def create_task_record(self, execution_id: str, step_name: str, step_index: int, task_data: Optional[Dict[str, Any]] = None, idempotency_key: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None, max_retries: int = 3) -> TaskRecord:
        """Creates a task record in-memory."""
        task_id = f"task_{execution_id}_{step_index}_{time.time()}"
        raw = {
            "task_id": task_id,
            "execution_id": execution_id,
            "step_name": step_name,
            "step_index": step_index,
            "status": "PENDING",
            "task_data": task_data,
            "idempotency_key": idempotency_key or task_id,
            "metadata": metadata,
            "retry_count": 0,
            "max_retries": max_retries,
        }
        self._task_records[task_id] = raw
        return TaskRecord(
            task_id=task_id,
            execution_id=execution_id,
            step_name=step_name,
            step_index=step_index,
            status="PENDING",
            task_data=task_data,
            idempotency_key=idempotency_key or task_id,
            retry_count=0,
            max_retries=max_retries,
        )

    def create_task_record_sync(self, execution_id: str, step_name: str, step_index: int, task_data: Optional[Dict[str, Any]] = None, idempotency_key: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None, max_retries: int = 3) -> Dict[str, Any]:
        """Synchronously creates a task record."""
        return self.create_task_record(execution_id, step_name, step_index, task_data, idempotency_key, metadata, max_retries)


    async def update_task_status(self, task_id: str, status: str, result: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None) -> None:
        """Updates the status of a task record in-memory."""
        if task_id in self._task_records:
            self._task_records[task_id]["status"] = status
            self._task_records[task_id]["result"] = result
            self._task_records[task_id]["error_message"] = error_message
            self._task_records[task_id]["updated_at"] = time.time()

    def update_task_status_sync(self, task_id: str, status: str, result: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None) -> None:
        """Synchronously updates the status of a task record."""
        self.update_task_status(task_id, status, result, error_message)


    async def get_task_record(self, task_id: str) -> Optional[TaskRecord]:
        """Retrieves a task record from in-memory."""
        raw = self._task_records.get(task_id)
        if raw is None:
            return None
        return TaskRecord(
            task_id=raw["task_id"],
            execution_id=raw["execution_id"],
            step_name=raw["step_name"],
            step_index=raw["step_index"],
            status=raw["status"],
            task_data=raw.get("task_data"),
            result=raw.get("result"),
            idempotency_key=raw.get("idempotency_key"),
            retry_count=raw.get("retry_count", 0),
            max_retries=raw.get("max_retries", 3),
        )

    def get_task_record_sync(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Synchronously retrieves a task record."""
        return self.get_task_record(task_id)
    
    async def get_active_workflows(self, limit: int = 100) -> List[Dict]:
        """Retrieves active workflows (placeholder for in-memory)."""
        # For in-memory, just return all workflows as active for simplicity
        return list(self._workflows.values())[:limit]