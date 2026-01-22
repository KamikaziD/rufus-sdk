"""
PostgreSQL Persistence Adapter for Confucius Workflow Engine

Provides durable, ACID-compliant workflow state management with:
- Atomic task claiming for distributed   workers
- LISTEN/NOTIFY for real-time updates
- Saga compensation logging
- Audit trails and metrics
- Idempotency keys
"""

import asyncpg
import asyncio
import json
import os
from typing import Optional, Dict, Any, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


from .crypto_utils import encrypt_string, decrypt_string

class PostgresWorkflowStore:
    """PostgreSQL-backed workflow persistence with advanced features"""

    def __init__(self, db_url: str):
        # Revert temporary hack for testing environment debugging.
        # Now use the db_url passed, which should be correctly set via os.getenv.
        self.db_url = db_url 
        self.pool: Optional[asyncpg.Pool] = None
        self._initialized = False
        self.encryption_enabled = os.getenv("ENABLE_ENCRYPTION_AT_REST", "false").lower() == "true"

    async def initialize(self):
        """Create connection pool and verify schema"""
        if self._initialized:
            return

        try:
            self.pool = await asyncpg.create_pool(
                self.db_url,
                min_size=5,
                max_size=20,
                command_timeout=60,
                server_settings={
                    'application_name': 'confucius_workflow_engine'
                }
            )

            # Verify schema exists
            async with self.pool.acquire() as conn:
                result = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'workflow_executions'
                    )
                """)

                if not result:
                    logger.warning(
                        "workflow_executions table not found. "
                        "Please run migrations: psql $DATABASE_URL < migrations/001_init_postgresql_schema.sql"
                    )

            self._initialized = True
            logger.info(f"PostgreSQL workflow store initialized with pool (min=5, max=20)")

        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL store: {e}")
            raise

    async def close(self):
        """Close connection pool"""
        if self.pool:
            await self.pool.close()
            self._initialized = False

    async def save_workflow(self, workflow_id: str, workflow_instance) -> None:
        """
        Save workflow state with atomic update

        Args:
            workflow_id: UUID of the workflow
            workflow_instance: Workflow object to persist
        """
        if not self._initialized:
            await self.initialize()

        from .workflow import Workflow

        if not isinstance(workflow_instance, Workflow):
            raise ValueError("workflow_instance must be a Workflow object")

        workflow_dict = workflow_instance.to_dict()
        
        # Encryption Logic
        state_json = json.dumps(workflow_dict['state'])
        encrypted_state_bytes = None
        encryption_key_id = None
        state_to_store = state_json # Default plaintext

        if self.encryption_enabled:
            try:
                encrypted_state_bytes = encrypt_string(state_json)
                state_to_store = '{}' # Store empty JSON in plaintext column
                encryption_key_id = "default" # TODO: Support key rotation/IDs
            except Exception as e:
                logger.error(f"Encryption failed for workflow {workflow_id}: {e}")
                # Fallback to plaintext or raise? Raising is safer.
                raise

        async with self.pool.acquire() as conn:
            # Upsert workflow execution
            await conn.execute("""
                INSERT INTO workflow_executions
                    (id, workflow_type, current_step, status, state,
                     steps_config, state_model_path, updated_at, saga_mode,
                     completed_steps_stack, parent_execution_id, blocked_on_child_id,
                     data_region, priority, idempotency_key, metadata,
                     owner_id, org_id, encrypted_state, encryption_key_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
                ON CONFLICT (id) DO UPDATE SET
                    current_step = EXCLUDED.current_step,
                    status = EXCLUDED.status,
                    state = EXCLUDED.state,
                    steps_config = EXCLUDED.steps_config,
                    updated_at = NOW(),
                    saga_mode = EXCLUDED.saga_mode,
                    completed_steps_stack = EXCLUDED.completed_steps_stack,
                    blocked_on_child_id = EXCLUDED.blocked_on_child_id,
                    metadata = EXCLUDED.metadata,
                    owner_id = EXCLUDED.owner_id,
                    org_id = EXCLUDED.org_id,
                    encrypted_state = EXCLUDED.encrypted_state,
                    encryption_key_id = EXCLUDED.encryption_key_id
            """,
                workflow_dict['id'],
                workflow_dict['workflow_type'],
                workflow_dict['current_step'],
                workflow_dict['status'],
                state_to_store,
                json.dumps(workflow_dict['steps_config']),
                workflow_dict['state_model_path'],
                workflow_dict.get('saga_mode', False),
                json.dumps(workflow_dict.get('completed_steps_stack', [])),
                workflow_dict.get('parent_execution_id'),
                workflow_dict.get('blocked_on_child_id'),
                workflow_dict.get('data_region', 'us-east-1'),
                workflow_dict.get('priority', 5),
                workflow_dict.get('idempotency_key'),
                json.dumps(workflow_dict.get('metadata', {})),
                workflow_dict.get('owner_id'),
                workflow_dict.get('org_id'),
                encrypted_state_bytes,
                encryption_key_id
            )

            logger.debug(f"Saved workflow {workflow_id} (status={workflow_dict['status']})")

    async def load_workflow(self, workflow_id: str):
        """
        Load workflow by ID

        Returns:
            Workflow instance or None if not found
        """
        if not self._initialized:
            await self.initialize()

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, workflow_type, current_step, status,
                       state, steps_config, state_model_path, saga_mode,
                       completed_steps_stack, parent_execution_id,
                       blocked_on_child_id, data_region, priority,
                       idempotency_key, metadata, created_at, updated_at,
                       owner_id, org_id, encrypted_state, encryption_key_id
                FROM workflow_executions
                WHERE id = $1
            """, workflow_id)

            if not row:
                return None

            # Decryption Logic
            state_data = row['state'] # Default plaintext
            if row['encrypted_state']:
                try:
                    decrypted_json = decrypt_string(row['encrypted_state'])
                    if decrypted_json:
                        state_data = json.loads(decrypted_json)
                except Exception as e:
                    logger.error(f"Decryption failed for workflow {workflow_id}: {e}")
                    # If decryption fails, we might fall back to plaintext if available (likely empty dict)
                    # or raise error. Raising is safer to prevent data corruption.
                    raise

            workflow_dict = {
                'id': str(row['id']),
                'workflow_type': row['workflow_type'],
                'current_step': row['current_step'],
                'status': row['status'],
                'state': json.loads(state_data) if isinstance(state_data, str) else state_data,
                'steps_config': json.loads(row['steps_config']) if isinstance(row['steps_config'], str) else row['steps_config'],
                'state_model_path': row['state_model_path'],
                'saga_mode': row['saga_mode'],
                'completed_steps_stack': json.loads(row['completed_steps_stack']) if isinstance(row['completed_steps_stack'], str) else row['completed_steps_stack'],
                'parent_execution_id': str(row['parent_execution_id']) if row['parent_execution_id'] else None,
                'blocked_on_child_id': str(row['blocked_on_child_id']) if row['blocked_on_child_id'] else None,
                'data_region': row['data_region'],
                'priority': row['priority'],
                'idempotency_key': row['idempotency_key'],
                'metadata': json.loads(row['metadata']) if isinstance(row['metadata'], str) else row['metadata'],
                'owner_id': row['owner_id'],
                'org_id': row['org_id']
            }

            from .workflow import Workflow
            return Workflow.from_dict(workflow_dict)

    async def claim_pending_task(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """
        Atomically claim a pending task for execution (FOR UPDATE SKIP LOCKED pattern)

        Args:
            worker_id: Identifier of the worker claiming the task

        Returns:
            Task data dict or None if no tasks available
        """
        if not self._initialized:
            await self.initialize()

        async with self.pool.acquire() as conn:
            # Atomic task claim using PostgreSQL's FOR UPDATE SKIP LOCKED
            row = await conn.fetchrow("""
                UPDATE tasks
                SET status = 'RUNNING',
                    worker_id = $1,
                    claimed_at = NOW(),
                    started_at = NOW(),
                    updated_at = NOW()
                WHERE task_id = (
                    SELECT task_id
                    FROM tasks
                    WHERE status = 'PENDING'
                      AND retry_count < max_retries
                    ORDER BY created_at
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING task_id, execution_id, step_name, step_index,
                          task_data, idempotency_key
            """, worker_id)

            if row:
                return {
                    'task_id': str(row['task_id']),
                    'execution_id': str(row['execution_id']),
                    'step_name': row['step_name'],
                    'step_index': row['step_index'],
                    'task_data': json.loads(row['task_data']) if row['task_data'] else {},
                    'idempotency_key': row['idempotency_key']
                }

            return None

    async def log_compensation(
        self,
        execution_id: str,
        step_name: str,
        step_index: int,
        action_type: str,
        action_result: Dict[str, Any],
        error_message: str = None,
        state_before: Dict[str, Any] = None,
        state_after: Dict[str, Any] = None,
        executed_by: str = None
    ):
        """
        Log a saga compensation action

        Args:
            execution_id: Workflow execution ID
            step_name: Name of the step being compensated
            step_index: Index of the step
            action_type: 'FORWARD', 'COMPENSATE', 'COMPENSATE_FAILED'
            action_result: Result of the action
            error_message: Error message if action failed
            state_before: State before action (optional)
            state_after: State after action (optional)
            executed_by: Worker ID (optional)
        """
        if not self._initialized:
            await self.initialize()

        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO compensation_log
                    (execution_id, step_name, step_index, action_type,
                     action_result, error_message, state_before, state_after,
                     executed_by, executed_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
            """,
                execution_id,
                step_name,
                step_index,
                action_type,
                json.dumps(action_result),
                error_message,
                json.dumps(state_before) if state_before else None,
                json.dumps(state_after) if state_after else None,
                executed_by
            )

    async def log_audit_event(
        self,
        workflow_id: str,
        event_type: str,
        step_name: str = None,
        user_id: str = None,
        worker_id: str = None,
        old_state: Dict = None,
        new_state: Dict = None,
        decision_rationale: str = None,
        metadata: Dict = None
    ):
        """Log an audit event for compliance"""
        if not self._initialized:
            await self.initialize()

        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO workflow_audit_log
                    (workflow_id, event_type, step_name, user_id, worker_id,
                     old_state, new_state, decision_rationale, metadata, recorded_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
            """,
                workflow_id,
                event_type,
                step_name,
                user_id,
                worker_id,
                json.dumps(old_state) if old_state else None,
                json.dumps(new_state) if new_state else None,
                decision_rationale,
                json.dumps(metadata) if metadata else None
            )

    async def log_execution(
        self,
        workflow_id: str,
        execution_id: str,
        step_name: str,
        event_type: str,
        message: str,
        metadata: Dict = None
    ):
        """Log an execution event for debugging"""
        if not self._initialized:
            await self.initialize()

        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO workflow_execution_logs
                    (workflow_id, execution_id, step_name, event_type, message, metadata, logged_at)
                VALUES ($1, $2, $3, $4, $5, $6, NOW())
            """,
                workflow_id,
                execution_id,
                step_name,
                event_type,
                message,
                json.dumps(metadata) if metadata else None
            )

    async def record_metric(
        self,
        workflow_id: str,
        workflow_type: str,
        metric_name: str,
        metric_value: float,
        unit: str = None,
        step_name: str = None,
        tags: Dict = None
    ):
        """Record a performance metric"""
        if not self._initialized:
            await self.initialize()

        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO workflow_metrics
                    (workflow_id, workflow_type, step_name, metric_name,
                     metric_value, unit, tags, recorded_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
            """,
                workflow_id,
                workflow_type,
                step_name,
                metric_name,
                metric_value,
                unit,
                json.dumps(tags) if tags else None
            )

    async def get_workflow_metrics(self, workflow_id: str, limit: int = 100) -> List[Dict]:
        """Get metrics for a workflow"""
        if not self._initialized:
            await self.initialize()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT step_name, metric_name, metric_value, unit, tags, recorded_at
                FROM workflow_metrics
                WHERE workflow_id = $1
                ORDER BY recorded_at DESC
                LIMIT $2
            """, workflow_id, limit)

            return [dict(row) for row in rows]

    async def get_active_workflows(self, limit: int = 100) -> List[Dict]:
        """Get all active workflows"""
        if not self._initialized:
            await self.initialize()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM active_workflows
                LIMIT $1
            """, limit)

            return [dict(row) for row in rows]

    async def get_workflow_summary(self, hours: int = 24) -> List[Dict]:
        """Get workflow execution summary for the past N hours"""
        if not self._initialized:
            await self.initialize()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    workflow_type,
                    COUNT(DISTINCT id) as total_executions,
                    COUNT(DISTINCT CASE WHEN status = 'COMPLETED' THEN id END) as completed,
                    COUNT(DISTINCT CASE WHEN status LIKE 'FAILED%' THEN id END) as failed,
                    COUNT(DISTINCT CASE WHEN status LIKE 'PENDING%' OR status = 'ACTIVE' THEN id END) as active,
                    MAX(updated_at) as last_execution,
                    AVG(EXTRACT(EPOCH FROM (updated_at - created_at))) as avg_duration_seconds
                FROM workflow_executions
                WHERE created_at > NOW() - INTERVAL '1 hour' * $1
                GROUP BY workflow_type
                ORDER BY total_executions DESC
            """, hours)

            return [dict(row) for row in rows]

    async def register_scheduled_workflow(
        self,
        schedule_name: str,
        workflow_type: str,
        cron_expression: str,
        initial_data: Dict[str, Any] = None,
        enabled: bool = True
    ):
        """
        Register a new dynamic schedule.
        Upsert logic: if schedule_name exists, update it.
        """
        if not self._initialized:
            await self.initialize()

        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO scheduled_workflows
                    (schedule_name, workflow_type, cron_expression, initial_data, enabled, updated_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
                ON CONFLICT (schedule_name) DO UPDATE SET
                    workflow_type = EXCLUDED.workflow_type,
                    cron_expression = EXCLUDED.cron_expression,
                    initial_data = EXCLUDED.initial_data,
                    enabled = EXCLUDED.enabled,
                    updated_at = NOW()
            """,
                schedule_name,
                workflow_type,
                cron_expression,
                json.dumps(initial_data) if initial_data else '{}',
                enabled
            )
            logger.info(f"Registered scheduled workflow: {schedule_name} ({cron_expression})")

    async def create_task_record(self, execution_id: str, step_name: str, step_index: int, task_data: Dict[str, Any] = None, idempotency_key: str = None, metadata: Dict[str, Any] = None, max_retries: int = 3) -> Dict[str, Any]:
        """
        Creates a new task record in the database.
        """
        if not self._initialized:
            await self.initialize()

        idempotency_key = idempotency_key or f"{execution_id}:{step_index}:{uuid.uuid4().hex}"

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO tasks (execution_id, step_name, step_index, task_data, idempotency_key, metadata, max_retries)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING task_id, idempotency_key
                """,
                execution_id,
                step_name,
                step_index,
                json.dumps(task_data) if task_data else '{}',
                idempotency_key,
                json.dumps(metadata) if metadata else '{}',
                max_retries
            )
            return dict(row)

    # --- Synchronous Bridge Methods ---

    def register_scheduled_workflow_sync(self, schedule_name: str, workflow_type: str, cron_expression: str, initial_data: Dict[str, Any] = None):
        """Sync wrapper for register_scheduled_workflow using PostgresExecutor"""
        from .postgres_executor import pg_executor
        pg_executor.run_coroutine_sync(
            self.register_scheduled_workflow(schedule_name, workflow_type, cron_expression, initial_data)
        )

    def log_execution_sync(self, workflow_id: str, log_level: str, message: str, step_name: str = None, metadata: Dict = None):
        """Sync wrapper for log_execution using PostgresExecutor"""
        from .postgres_executor import pg_executor
        pg_executor.run_coroutine_sync(
            self.log_execution(workflow_id, log_level, message, step_name=step_name, metadata=metadata)
        )

    def log_audit_event_sync(self, workflow_id: str, event_type: str, step_name: str = None, new_state: Dict = None, metadata: Dict = None):
        """Sync wrapper for log_audit_event using PostgresExecutor"""
        from .postgres_executor import pg_executor
        pg_executor.run_coroutine_sync(
            self.log_audit_event(workflow_id, event_type, step_name=step_name, new_state=new_state, metadata=metadata)
        )

    def log_compensation_sync(self, execution_id: str, step_name: str, step_index: int, action_type: str, action_result: Dict, state_before: Dict = None, state_after: Dict = None, error_message: str = None):
        """Sync wrapper for log_compensation using PostgresExecutor"""
        from .postgres_executor import pg_executor
        pg_executor.run_coroutine_sync(
            self.log_compensation(
                execution_id, step_name, step_index, action_type, action_result, 
                state_before=state_before, state_after=state_after, error_message=error_message
            )
        )
    
    def record_metric_sync(self, workflow_id: str, workflow_type: str, metric_name: str, metric_value: float, unit: str = None, step_name: str = None):
        """Sync wrapper for record_metric using PostgresExecutor"""
        from .postgres_executor import pg_executor
        pg_executor.run_coroutine_sync(
            self.record_metric(workflow_id, workflow_type, metric_name, metric_value, unit=unit, step_name=step_name)
        )

    def create_task_record_sync(self, execution_id: str, step_name: str, step_index: int, task_data: Dict[str, Any] = None, idempotency_key: str = None, metadata: Dict[str, Any] = None, max_retries: int = 3) -> Dict[str, Any]:
        """Sync wrapper for create_task_record using PostgresExecutor"""
        from .postgres_executor import pg_executor
        return pg_executor.run_coroutine_sync(
            self.create_task_record(execution_id, step_name, step_index, task_data, idempotency_key, metadata, max_retries)
        )


# Singleton instance registry per event loop
_postgres_stores: Dict[asyncio.AbstractEventLoop, PostgresWorkflowStore] = {}


async def get_postgres_store() -> PostgresWorkflowStore:
    """Get or create PostgreSQL store singleton for the current event loop"""
    global _postgres_stores
    
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Should not happen in async context, but fallback or raise
        raise RuntimeError("get_postgres_store must be called within a running event loop")

    if loop not in _postgres_stores:
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            raise ValueError("DATABASE_URL environment variable not set")

        store = PostgresWorkflowStore(db_url)
        await store.initialize()
        _postgres_stores[loop] = store

    return _postgres_stores[loop]
