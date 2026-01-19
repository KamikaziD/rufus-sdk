"""
Workflow Persistence Layer - Factory Pattern
Supports both Redis (development) and PostgreSQL (production) backends.
Switch between them using the WORKFLOW_STORAGE environment variable.
"""
import redis
import json
import os
import asyncio
from typing import Optional, Protocol, Union, Any
from abc import abstractmethod
# Import the specific Postgres store for the factory
from .persistence_postgres import get_postgres_store, PostgresWorkflowStore as RawPostgresWorkflowStore # Avoid name collision
class Workflow(Protocol):
    # Minimal protocol for Workflow object, to avoid circular imports.
    # The actual Workflow class has more attributes.
    id: str
    def to_dict(self) -> dict: ...
    @staticmethod
    def from_dict(data: dict) -> 'Workflow': ...
class AbstractWorkflowStore(Protocol):
    """Abstract base class for workflow persistence stores."""
    
    @abstractmethod
    def save(self, workflow_id: str, workflow_instance: Workflow) -> Union[None, asyncio.Task]:
        ...
    @abstractmethod
    def load(self, workflow_id: str) -> Union[Optional[Workflow], asyncio.Task]:
        ...
class RedisWorkflowStore:
    """Redis-backed workflow persistence store."""
    def __init__(self, host: str = 'localhost', port: int = 6379, db: int = 0):
        self.host = host
        self.port = port
        self.db = db
        self._redis_client: Optional[redis.Redis] = None
        self._initialize_client()
    def _initialize_client(self):
        try:
            self._redis_client = redis.Redis(
                host=self.host, port=self.port, db=self.db, decode_responses=True
            )
            self._redis_client.ping()
        except redis.exceptions.ConnectionError as e:
            print(
                f"Warning: Could not connect to Redis at {self.host}:{self.port}. "
                "RedisWorkflowStore will be non-functional. Error: {e}"
            )
            self._redis_client = None
    def save(self, workflow_id: str, workflow_instance: Workflow) -> None:
        if self._redis_client:
            workflow_dict = workflow_instance.to_dict()
            serialized_workflow = json.dumps(workflow_dict)
            self._redis_client.set(f"workflow:{workflow_id}", serialized_workflow)
            channel = f"workflow_events:{workflow_id}"
            self._redis_client.publish(channel, serialized_workflow)
    def load(self, workflow_id: str) -> Optional[Workflow]:
        if not self._redis_client:
            return None
        data = self._redis_client.get(f"workflow:{workflow_id}")
        if not data:
            return None
        workflow_data = json.loads(data)
        from .workflow import Workflow # Late import to avoid circular dependency
        return Workflow.from_dict(workflow_data)

    def save_sync(self, workflow_id: str, workflow_instance: Workflow) -> None:
        """Explicitly run save synchronously."""
        self.save(workflow_id, workflow_instance)

    def load_sync(self, workflow_id: str) -> Optional[Workflow]:
        """Explicitly run load synchronously."""
        return self.load(workflow_id)
class PostgresWorkflowStore:
    """PostgreSQL-backed workflow persistence store."""
    def __init__(self):
        pass

    async def _get_initialized_store(self) -> RawPostgresWorkflowStore:
        return await get_postgres_store()

    def save(self, workflow_id: str, workflow_instance: Workflow) -> Union[asyncio.Task, Any]:
        async def _async_save():
            store = await self._get_initialized_store()
            await store.save_workflow(workflow_id, workflow_instance)

        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                return _async_save()
        except RuntimeError:
            pass
        
        # Always run in the executor's thread for consistency (even if not strictly needed always)
        from .postgres_executor import pg_executor
        return pg_executor.run_coroutine_sync(_async_save)
    def load(self, workflow_id: str) -> Union[asyncio.Task, Any]:
        async def _async_load():
            store = await self._get_initialized_store()
            return await store.load_workflow(workflow_id)

        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                return _async_load()
        except RuntimeError:
            pass
        
        # Always run in the executor's thread
        from .postgres_executor import pg_executor
        return pg_executor.run_coroutine_sync(_async_load)

    def save_sync(self, workflow_id: str, workflow_instance: Workflow) -> Any:
        """Explicitly run save synchronously using the executor."""
        async def _async_save():
            store = await self._get_initialized_store()
            await store.save_workflow(workflow_id, workflow_instance)
            
        from .postgres_executor import pg_executor
        return pg_executor.run_coroutine_sync(_async_save)

    def load_sync(self, workflow_id: str) -> Any:
        """Explicitly run load synchronously using the executor."""
        async def _async_load():
            store = await self._get_initialized_store()
            return await store.load_workflow(workflow_id)

        from .postgres_executor import pg_executor
        return pg_executor.run_coroutine_sync(_async_load)

    def log_compensation_sync(self, execution_id, step_name, step_index, action_type, action_result, error_message=None, state_before=None, state_after=None, executed_by=None):
        async def _async_log():
            store = await self._get_initialized_store()
            await store.log_compensation(execution_id, step_name, step_index, action_type, action_result, error_message, state_before, state_after, executed_by)
        
        from .postgres_executor import pg_executor
        return pg_executor.run_coroutine_sync(_async_log)

    def log_audit_event_sync(self, workflow_id: str, event_type: str, step_name: str = None, user_id: str = None, worker_id: str = None, old_state: dict = None, new_state: dict = None, decision_rationale: str = None, metadata: dict = None):
        async def _async_log():
            store = await self._get_initialized_store()
            await store.log_audit_event(workflow_id, event_type, step_name, user_id, worker_id, old_state, new_state, decision_rationale, metadata)
        
        from .postgres_executor import pg_executor
        return pg_executor.run_coroutine_sync(_async_log)

    def log_execution_sync(self, workflow_id: str, execution_id: str, step_name: str, event_type: str, message: str, metadata: dict = None):
        async def _async_log():
            store = await self._get_initialized_store()
            await store.log_execution(workflow_id, execution_id, step_name, event_type, message, metadata)
        
        from .postgres_executor import pg_executor
        return pg_executor.run_coroutine_sync(_async_log)

    def record_metric_sync(self, workflow_id: str, workflow_type: str, metric_name: str, metric_value: float, unit: str = None, step_name: str = None, tags: dict = None):
        async def _async_record():
            store = await self._get_initialized_store()
            await store.record_metric(workflow_id, workflow_type, metric_name, metric_value, unit, step_name, tags)
        
        from .postgres_executor import pg_executor
        return pg_executor.run_coroutine_sync(_async_record)

_global_store: Optional[AbstractWorkflowStore] = None
def get_storage_backend() -> str:
    """Returns the name of the currently configured storage backend."""
    return os.getenv('WORKFLOW_STORAGE', 'redis').lower()

def get_workflow_store(backend_name: Optional[str] = None):
    """
    Factory function to get a workflow store instance.
    If no backend_name is provided, it reads from WORKFLOW_STORAGE env var.
    This function should be used to retrieve the store instance.
    """
    global _global_store
    
    if _global_store is None:
        backend = (backend_name or get_storage_backend())
        if backend == 'postgres' or backend == 'postgresql':
            _global_store = PostgresWorkflowStore()
        else:
            _global_store = RedisWorkflowStore(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", "6379"))
            )
    return _global_store

def save_workflow_state(workflow_id: str, workflow_instance: Workflow, store: Optional[AbstractWorkflowStore] = None, sync: bool = False) -> Union[None, asyncio.Task]:
    """
    Save workflow state to the specified or default backend.
    If sync=True, forces synchronous execution (blocking if needed).
    """
    store_instance = store or get_workflow_store()
    if sync and hasattr(store_instance, 'save_sync'):
        return store_instance.save_sync(workflow_id, workflow_instance)
    return store_instance.save(workflow_id, workflow_instance)

def load_workflow_state(workflow_id: str, store: Optional[AbstractWorkflowStore] = None, sync: bool = False) -> Union[Optional[Workflow], asyncio.Task]:
    """
    Load workflow state from the specified or default backend.
    If sync=True, forces synchronous execution (blocking if needed).
    """
    store_instance = store or get_workflow_store()
    if sync and hasattr(store_instance, 'load_sync'):
        return store_instance.load_sync(workflow_id)
    return store_instance.load(workflow_id)


def create_task_record(execution_id: str, step_name: str, step_index: int, task_data: dict = None, idempotency_key: str = None, metadata: dict = None, max_retries: int = 3, store: Optional[AbstractWorkflowStore] = None) -> dict:
    """
    Creates a task record in the persistence backend.
    """
    store_instance = store or get_workflow_store()
    if hasattr(store_instance, 'create_task_record_sync'):
        return store_instance.create_task_record_sync(execution_id, step_name, step_index, task_data, idempotency_key, metadata, max_retries)
    else:
        # Fallback for Redis or other non-Postgres stores
        # This is a mock implementation for now
        print(f"Warning: create_task_record not implemented for {type(store_instance).__name__}")
        return {"task_id": "mock_task_id", "idempotency_key": idempotency_key or f"{execution_id}:{step_index}:mock"}

# ============================================================================
# MIGRATION HELPER (Needs update for new store pattern)
# ============================================================================
# The migration helper will need to be updated to use the new store instances.
# For now, it will remain as is, but it will only work if Redis is directly accessible.
# It's less critical for the current task.