"""
PersistenceProvider — abstract interface for all Rufus storage backends.

Implementations: SQLitePersistenceProvider, PostgresPersistenceProvider,
                 MemoryPersistenceProvider, RedisPersistenceProvider

# API FROZEN v1.0
"""

from abc import ABC, abstractmethod
from typing import List, Any, Dict, Optional

from ruvon.providers.dtos import (
    WorkflowRecord,
    TaskRecord,
    AuditLogRecord,
    MetricRecord,
    SyncStateRecord,
)


# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------

class PersistenceError(RuntimeError):
    """Base class for all persistence-layer errors."""


class WorkflowNotFoundError(PersistenceError):
    """Raised when a workflow_id does not exist in the backing store."""


class DuplicateIdempotencyKeyError(PersistenceError):
    """Raised on INSERT when the idempotency_key is already present."""


class TaskNotFoundError(PersistenceError):
    """Raised when a task_id does not exist in the backing store."""


# ---------------------------------------------------------------------------
# CompatibilityMixin — sync wrappers retained for Celery workers
# ---------------------------------------------------------------------------

class CompatibilityMixin:
    """
    Synchronous wrappers kept for Celery task context where no event loop runs.

    All methods delegate to their async counterparts via asyncio.run().
    Concrete implementations may override these with direct sync implementations
    if that is more efficient (e.g. psycopg2 in the Celery worker).

    NOTE: These methods are NOT part of the frozen abstract interface and will
    be removed in v2.0 once Celery workers are migrated to async.
    """

    def log_execution_sync(self, workflow_id: str, log_level: str, message: str,
                           step_name: Optional[str] = None,
                           metadata: Optional[Dict[str, Any]] = None):
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            self.log_execution(workflow_id, log_level, message, step_name, metadata)
        )

    def log_audit_event_sync(self, workflow_id: str, event_type: str,
                             step_name: Optional[str] = None,
                             user_id: Optional[str] = None,
                             worker_id: Optional[str] = None,
                             old_state: Optional[Dict[str, Any]] = None,
                             new_state: Optional[Dict[str, Any]] = None,
                             decision_rationale: Optional[str] = None,
                             metadata: Optional[Dict[str, Any]] = None):
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            self.log_audit_event(workflow_id, event_type, step_name, user_id,
                                 worker_id, old_state, new_state,
                                 decision_rationale, metadata)
        )

    def log_compensation_sync(self, execution_id: str, step_name: str,
                              step_index: int, action_type: str,
                              action_result: Dict[str, Any],
                              state_before: Optional[Dict[str, Any]] = None,
                              state_after: Optional[Dict[str, Any]] = None,
                              error_message: Optional[str] = None,
                              executed_by: Optional[str] = None):
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            self.log_compensation(execution_id, step_name, step_index,
                                  action_type, action_result, state_before,
                                  state_after, error_message, executed_by)
        )

    def record_metric_sync(self, workflow_id: str, workflow_type: str,
                           metric_name: str, metric_value: float,
                           unit: Optional[str] = None,
                           step_name: Optional[str] = None,
                           tags: Optional[Dict[str, Any]] = None):
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            self.record_metric(workflow_id, workflow_type, metric_name,
                               metric_value, unit, step_name, tags)
        )

    def register_scheduled_workflow_sync(self, schedule_name: str,
                                         workflow_type: str,
                                         cron_expression: str,
                                         initial_data: Optional[Dict[str, Any]] = None,
                                         enabled: bool = True):
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            self.register_scheduled_workflow(schedule_name, workflow_type,
                                             cron_expression, initial_data, enabled)
        )

    def create_task_record_sync(self, execution_id: str, step_name: str,
                                step_index: int,
                                task_data: Optional[Dict[str, Any]] = None,
                                idempotency_key: Optional[str] = None,
                                metadata: Optional[Dict[str, Any]] = None,
                                max_retries: int = 3) -> Dict[str, Any]:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self.create_task_record(execution_id, step_name, step_index,
                                    task_data, idempotency_key, metadata, max_retries)
        )

    def update_task_status_sync(self, task_id: str, status: str,
                                result: Optional[Dict[str, Any]] = None,
                                error_message: Optional[str] = None):
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            self.update_task_status(task_id, status, result, error_message)
        )

    def get_task_record_sync(self, task_id: str) -> Optional[Dict[str, Any]]:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self.get_task_record(task_id)
        )


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class PersistenceProvider(CompatibilityMixin, ABC):
    """Abstracts the storage of workflow state and related operational data."""

    # --- Lifecycle ----------------------------------------------------------

    @abstractmethod
    async def initialize(self):
        """Initializes the persistence provider (e.g., connects to DB)."""

    @abstractmethod
    async def close(self):
        """Closes any open connections or resources."""

    # --- Workflow CRUD ------------------------------------------------------

    @abstractmethod
    async def save_workflow(self, workflow_id: str, workflow_data: Dict[str, Any]):
        """Saves the complete workflow data."""

    @abstractmethod
    async def load_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Loads the complete workflow data. Returns None if not found."""

    @abstractmethod
    async def list_workflows(self, **filters) -> List[Dict[str, Any]]:
        """Lists workflows based on filters."""

    @abstractmethod
    async def get_active_workflows(self, limit: int = 100) -> List[Dict]:
        """Gets a list of currently active (ACTIVE status) workflows."""

    # --- Task queue ---------------------------------------------------------

    @abstractmethod
    async def create_task_record(self, execution_id: str, step_name: str,
                                 step_index: int,
                                 task_data: Optional[Dict[str, Any]] = None,
                                 idempotency_key: Optional[str] = None,
                                 metadata: Optional[Dict[str, Any]] = None,
                                 max_retries: int = 3) -> Dict[str, Any]:
        """Creates a record for an asynchronous task."""

    @abstractmethod
    async def update_task_status(self, task_id: str, status: str,
                                 result: Optional[Dict[str, Any]] = None,
                                 error_message: Optional[str] = None) -> None:
        """Updates the status of an asynchronous task record."""

    @abstractmethod
    async def get_task_record(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves an asynchronous task record."""

    async def claim_next_task(self, worker_id: str,
                             step_name: Optional[str] = None) -> Optional[TaskRecord]:
        """
        Atomically claims the next pending task for a worker.

        Returns None if no tasks are available.
        Must be safe to call concurrently from multiple workers.

        Default raises NotImplementedError. Override in backends that support
        atomic task claiming (PostgreSQL FOR UPDATE SKIP LOCKED, SQLite EXCLUSIVE).
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement claim_next_task()."
        )

    # --- Logging / audit ----------------------------------------------------

    @abstractmethod
    async def log_execution(self, workflow_id: str, log_level: str, message: str,
                            step_name: Optional[str] = None,
                            metadata: Optional[Dict[str, Any]] = None):
        """Logs an execution event for a workflow."""

    @abstractmethod
    async def log_compensation(self, execution_id: str, step_name: str,
                               step_index: int, action_type: str,
                               action_result: Dict[str, Any],
                               state_before: Optional[Dict[str, Any]] = None,
                               state_after: Optional[Dict[str, Any]] = None,
                               error_message: Optional[str] = None,
                               executed_by: Optional[str] = None):
        """Logs a compensation action for a saga, including state snapshots."""

    @abstractmethod
    async def log_audit_event(self, workflow_id: str, event_type: str,
                              step_name: Optional[str] = None,
                              user_id: Optional[str] = None,
                              worker_id: Optional[str] = None,
                              old_state: Optional[Dict[str, Any]] = None,
                              new_state: Optional[Dict[str, Any]] = None,
                              decision_rationale: Optional[str] = None,
                              metadata: Optional[Dict[str, Any]] = None):
        """Logs an audit event for compliance and traceability."""

    # --- Metrics ------------------------------------------------------------

    @abstractmethod
    async def record_metric(self, workflow_id: str, workflow_type: str,
                            metric_name: str, metric_value: float,
                            unit: Optional[str] = None,
                            step_name: Optional[str] = None,
                            tags: Optional[Dict[str, Any]] = None):
        """Records a performance or operational metric."""

    @abstractmethod
    async def get_workflow_metrics(self, workflow_id: str,
                                   limit: int = 100) -> List[Dict]:
        """Retrieves performance metrics for a specific workflow."""

    @abstractmethod
    async def get_workflow_summary(self, hours: int = 24) -> List[Dict]:
        """Retrieves a summary of workflow executions over a period."""

    # --- Scheduling ---------------------------------------------------------

    @abstractmethod
    async def register_scheduled_workflow(self, schedule_name: str,
                                          workflow_type: str,
                                          cron_expression: str,
                                          initial_data: Optional[Dict[str, Any]] = None,
                                          enabled: bool = True):
        """Registers or updates a scheduled workflow."""

    # --- Edge sync methods --------------------------------------------------
    # These 5 methods exist only on edge-capable backends (SQLite).
    # The default implementations raise NotImplementedError so that server-side
    # backends (Postgres) fail loudly rather than silently if called by mistake.

    async def get_pending_sync_workflows(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Returns terminal-status workflows not yet synced to the cloud.

        Used by EdgeWorkflowSyncer. Default raises NotImplementedError.
        Backends: SQLitePersistenceProvider.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_pending_sync_workflows(). "
            "This method is only available on edge-capable backends (SQLite)."
        )

    async def get_audit_logs_for_workflows(self, workflow_ids: List[str],
                                           limit_per_workflow: int = 50) -> List[Dict[str, Any]]:
        """
        Returns audit log rows for the given workflow IDs.

        Used by EdgeWorkflowSyncer. Default raises NotImplementedError.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_audit_logs_for_workflows()."
        )

    async def delete_synced_workflows(self, workflow_ids: List[str]) -> int:
        """
        Deletes synced workflow rows from local storage to prevent DB bloat.

        Returns the number of rows deleted.
        Default raises NotImplementedError.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement delete_synced_workflows()."
        )

    async def get_edge_sync_state(self, key: str) -> Optional[str]:
        """
        Reads a value string from edge_sync_state table.

        Returns the raw string value (or None if not set).
        Implementations return a plain str, not a SyncStateRecord wrapper.

        Default raises NotImplementedError.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_edge_sync_state()."
        )

    async def set_edge_sync_state(self, key: str, value: str) -> None:
        """
        Writes/updates a key in edge_sync_state table.

        Default raises NotImplementedError.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement set_edge_sync_state()."
        )
