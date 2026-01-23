import redis
import os
import asyncio
from typing import Optional, Dict, Any, List

from rufus.providers.persistence import PersistenceProvider
from rufus.workflow import Workflow # For type hinting in from_dict method
from rufus.utils.serialization import serialize, deserialize  # High-performance JSON serialization

class RedisPersistenceProvider(PersistenceProvider):
    """Redis-backed workflow persistence store."""

    def __init__(self, host: str = 'localhost', port: int = 6379, db: int = 0):
        self.host = host
        self.port = port
        self.db = db
        self._redis_client: Optional[redis.Redis] = None
        self._initialized = False

    async def initialize(self):
        """Connect to Redis and ping to ensure connectivity."""
        if self._initialized:
            return
        try:
            self._redis_client = redis.Redis(
                host=self.host, port=self.port, db=self.db, decode_responses=True
            )
            await self._redis_client.ping()
            self._initialized = True
            print(f"RedisPersistenceProvider connected to {self.host}:{self.port}")
        except redis.exceptions.ConnectionError as e:
            print(
                f"Warning: Could not connect to Redis at {self.host}:{self.port}. "
                "RedisPersistenceProvider will be non-functional. Error: {e}"
            )
            self._redis_client = None
            raise

    async def close(self):
        """Close the Redis connection."""
        if self._redis_client:
            await self._redis_client.close()
            self._redis_client = None
            self._initialized = False

    async def save_workflow(self, workflow_id: str, workflow_data: Dict[str, Any]) -> None:
        """Saves the workflow state to Redis."""
        if not self._redis_client:
            await self.initialize() # Attempt to initialize if not already

        if self._redis_client:
            serialized_workflow = serialize(workflow_data)
            await self._redis_client.set(f"workflow:{workflow_id}", serialized_workflow)
            # Publish update for WebSocket subscribers (assuming this is handled elsewhere for now)
            # channel = f"workflow_events:{workflow_id}"
            # await self._redis_client.publish(channel, serialized_workflow)
        else:
            raise RuntimeError("Redis client not initialized.")

    async def load_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Loads the workflow state from Redis."""
        if not self._redis_client:
            await self.initialize()

        if not self._redis_client:
            return None # Cannot load if client is not initialized

        data = await self._redis_client.get(f"workflow:{workflow_id}")
        if not data:
            return None
        return deserialize(data)

    async def list_workflows(self, **filters) -> List[Dict[str, Any]]:
        """Lists workflows based on filters (basic implementation for Redis)."""
        if not self._redis_client:
            await self.initialize()

        if not self._redis_client:
            return []

        # This is a very basic implementation. Real-world Redis might use SCAN or sorted sets.
        keys = await self._redis_client.keys("workflow:*")
        workflows = []
        for key in keys:
            workflow_id = key.split(":", 1)[1]
            workflow_data = await self.load_workflow(workflow_id)
            if workflow_data:
                # Apply simple filters
                match = True
                for f_key, f_value in filters.items():
                    if workflow_data.get(f_key) != f_value:
                        match = False
                        break
                if match:
                    workflows.append(workflow_data)
        return workflows

    async def log_execution(self, workflow_id: str, log_level: str, message: str, step_name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Logs execution events to Redis (e.g., using a LIST or STREAM)."""
        if not self._redis_client:
            await self.initialize()
        
        if self._redis_client:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "workflow_id": workflow_id,
                "log_level": log_level,
                "message": message,
                "step_name": step_name,
                "metadata": metadata
            }
            # Using RPUSH to append to a list, or XADD for a stream
            await self._redis_client.rpush(f"workflow_log:{workflow_id}", serialize(log_entry))
        else:
            print(f"WARNING: Redis not connected, execution log for {workflow_id} not saved.")

    async def log_compensation(self, execution_id: str, step_name: str, step_index: int, action_type: str, action_result: Dict[str, Any], state_before: Optional[Dict[str, Any]] = None, state_after: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None, executed_by: Optional[str] = None):
        """Logs compensation events to Redis."""
        if not self._redis_client:
            await self.initialize()
        
        if self._redis_client:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "execution_id": execution_id,
                "step_name": step_name,
                "step_index": step_index,
                "action_type": action_type,
                "action_result": action_result,
                "error_message": error_message,
                "state_before": state_before,
                "state_after": state_after,
                "executed_by": executed_by
            }
            await self._redis_client.rpush(f"compensation_log:{execution_id}", serialize(log_entry))
        else:
            print(f"WARNING: Redis not connected, compensation log for {execution_id} not saved.")

    async def log_audit_event(self, workflow_id: str, event_type: str, step_name: Optional[str] = None, user_id: Optional[str] = None, worker_id: Optional[str] = None, old_state: Optional[Dict[str, Any]] = None, new_state: Optional[Dict[str, Any]] = None, decision_rationale: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Logs audit events to Redis."""
        if not self._redis_client:
            await self.initialize()
        
        if self._redis_client:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "workflow_id": workflow_id,
                "event_type": event_type,
                "step_name": step_name,
                "user_id": user_id,
                "worker_id": worker_id,
                "old_state": old_state,
                "new_state": new_state,
                "decision_rationale": decision_rationale,
                "metadata": metadata
            }
            await self._redis_client.rpush(f"audit_log:{workflow_id}", serialize(log_entry))
        else:
            print(f"WARNING: Redis not connected, audit log for {workflow_id} not saved.")


    async def record_metric(self, workflow_id: str, workflow_type: str, metric_name: str, metric_value: float, unit: Optional[str] = None, step_name: Optional[str] = None, tags: Optional[Dict[str, Any]] = None):
        """Records a performance or operational metric to Redis."""
        if not self._redis_client:
            await self.initialize()
        
        if self._redis_client:
            metric_entry = {
                "timestamp": datetime.now().isoformat(),
                "workflow_id": workflow_id,
                "workflow_type": workflow_type,
                "metric_name": metric_name,
                "metric_value": metric_value,
                "unit": unit,
                "step_name": step_name,
                "tags": tags
            }
            # Using RPUSH to append to a list, or XADD for a stream
            await self._redis_client.rpush(f"workflow_metrics:{workflow_id}", serialize(metric_entry))
        else:
            print(f"WARNING: Redis not connected, metric for {workflow_id} not saved.")

    async def get_workflow_metrics(self, workflow_id: str, limit: int = 100) -> List[Dict]:
        """Retrieves performance metrics for a specific workflow from Redis."""
        if not self._redis_client:
            await self.initialize()
        
        if not self._redis_client:
            return []
        
        metrics = await self._redis_client.lrange(f"workflow_metrics:{workflow_id}", 0, limit - 1)
        return [deserialize(m) for m in metrics]


    async def get_workflow_summary(self, hours: int = 24) -> List[Dict]:
        """Retrieves a summary of workflow executions over a period (Not fully implemented for Redis)."""
        print(f"WARNING: get_workflow_summary not fully implemented for RedisPersistenceProvider.")
        return []

    async def register_scheduled_workflow(self, schedule_name: str, workflow_type: str, cron_expression: str, initial_data: Optional[Dict[str, Any]] = None, enabled: bool = True):
        """Registers a scheduled workflow in Redis."""
        if not self._redis_client:
            await self.initialize()
        
        if self._redis_client:
            schedule_data = {
                "workflow_type": workflow_type,
                "cron_expression": cron_expression,
                "initial_data": initial_data,
                "enabled": enabled,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            await self._redis_client.hset("scheduled_workflows", schedule_name, serialize(schedule_data))
        else:
            print(f"WARNING: Redis not connected, scheduled workflow {schedule_name} not registered.")


    async def create_task_record(self, execution_id: str, step_name: str, step_index: int, task_data: Optional[Dict[str, Any]] = None, idempotency_key: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None, max_retries: int = 3) -> Dict[str, Any]:
        """Creates a task record in Redis."""
        if not self._redis_client:
            await self.initialize()
        
        if self._redis_client:
            task_id = str(uuid.uuid4())
            record = {
                "task_id": task_id,
                "execution_id": execution_id,
                "step_name": step_name,
                "step_index": step_index,
                "status": "PENDING",
                "task_data": task_data,
                "idempotency_key": idempotency_key or f"{execution_id}:{step_index}:{task_id}",
                "metadata": metadata,
                "retry_count": 0,
                "max_retries": max_retries,
                "created_at": datetime.now().isoformat()
            }
            await self._redis_client.hset(f"tasks:{task_id}", mapping=record)
            # Optionally push task_id to a processing queue
            await self._redis_client.lpush("pending_tasks", task_id)
            return record
        else:
            raise RuntimeError("Redis client not initialized for task record creation.")


    async def update_task_status(self, task_id: str, status: str, result: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None) -> None:
        """Updates the status of a task record in Redis."""
        if not self._redis_client:
            await self.initialize()
        
        if self._redis_client:
            update_data = {
                "status": status,
                "updated_at": datetime.now().isoformat()
            }
            if result:
                update_data["result"] = serialize(result)
            if error_message:
                update_data["last_error"] = error_message
            
            await self._redis_client.hset(f"tasks:{task_id}", mapping=update_data)
        else:
            raise RuntimeError("Redis client not initialized for task status update.")

    async def get_task_record(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a task record from Redis."""
        if not self._redis_client:
            await self.initialize()
        
        if self._redis_client:
            record = await self._redis_client.hgetall(f"tasks:{task_id}")
            if record:
                # Deserialize nested JSON fields
                if 'task_data' in record:
                    record['task_data'] = deserialize(record['task_data'])
                if 'metadata' in record:
                    record['metadata'] = deserialize(record['metadata'])
                if 'result' in record:
                    record['result'] = deserialize(record['result'])
                # Convert numeric fields
                if 'retry_count' in record:
                    record['retry_count'] = int(record['retry_count'])
                if 'max_retries' in record:
                    record['max_retries'] = int(record['max_retries'])
                return record
            return None
        return None

    # --- Synchronous wrappers for Celery tasks ---

    def _run_coroutine_sync(self, coro):
        """Helper to run a coroutine synchronously (simple blocking for Redis)."""
        # For Redis, if it's not truly async-io bound in this context, we can just run it.
        # In a real Celery worker, this might involve async_to_sync or similar.
        # For this example, we'll assume the context handles it or simple blocking is fine.
        # In a test environment, this might run directly.
        return asyncio.run(coro)

    def save_workflow_sync(self, workflow_id: str, workflow_data: Dict[str, Any]) -> None:
        """Synchronously saves the workflow state."""
        self._run_coroutine_sync(self.save_workflow(workflow_id, workflow_data))

    def load_workflow_sync(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Synchronously loads the workflow state."""
        return self._run_coroutine_sync(self.load_workflow(workflow_id))
    
    def log_execution_sync(self, workflow_id: str, log_level: str, message: str, step_name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Synchronously logs an execution event."""
        self._run_coroutine_sync(self.log_execution(workflow_id, log_level, message, step_name, metadata))

    def log_compensation_sync(self, execution_id: str, step_name: str, step_index: int, action_type: str, action_result: Dict[str, Any], state_before: Optional[Dict[str, Any]] = None, state_after: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None, executed_by: Optional[str] = None):
        """Synchronously logs a compensation event."""
        self._run_coroutine_sync(self.log_compensation(execution_id, step_name, step_index, action_type, action_result, state_before, state_after, error_message, executed_by))

    def log_audit_event_sync(self, workflow_id: str, event_type: str, step_name: Optional[str] = None, user_id: Optional[str] = None, worker_id: Optional[str] = None, old_state: Optional[Dict[str, Any]] = None, new_state: Optional[Dict[str, Any]] = None, decision_rationale: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Synchronously logs an audit event."""
        self._run_coroutine_sync(self.log_audit_event(workflow_id, event_type, step_name, user_id, worker_id, old_state, new_state, decision_rationale, metadata))

    def record_metric_sync(self, workflow_id: str, workflow_type: str, metric_name: str, metric_value: float, unit: Optional[str] = None, step_name: Optional[str] = None, tags: Optional[Dict[str, Any]] = None):
        """Synchronously records a metric."""
        self._run_coroutine_sync(self.record_metric(workflow_id, workflow_type, metric_name, metric_value, unit, step_name, tags))

    def register_scheduled_workflow_sync(self, schedule_name: str, workflow_type: str, cron_expression: str, initial_data: Optional[Dict[str, Any]] = None, enabled: bool = True):
        """Synchronously registers a scheduled workflow."""
        self._run_coroutine_sync(self.register_scheduled_workflow(schedule_name, workflow_type, cron_expression, initial_data, enabled))

    def create_task_record_sync(self, execution_id: str, step_name: str, step_index: int, task_data: Optional[Dict[str, Any]] = None, idempotency_key: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None, max_retries: int = 3) -> Dict[str, Any]:
        """Synchronously creates a task record."""
        return self._run_coroutine_sync(self.create_task_record(execution_id, step_name, step_index, task_data, idempotency_key, metadata, max_retries))

    def update_task_status_sync(self, task_id: str, status: str, result: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None) -> None:
        """Synchronously updates the status of a task record."""
        self._run_coroutine_sync(self.update_task_status(task_id, status, result, error_message))

    def get_task_record_sync(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Synchronously retrieves a task record."""
        return self._run_coroutine_sync(self.get_task_record(task_id))

    async def get_active_workflows(self, limit: int = 100) -> List[Dict]:
        """Retrieves active workflows (placeholder for Redis)."""
        print(f"WARNING: get_active_workflows not fully implemented for RedisPersistenceProvider.")
        return []