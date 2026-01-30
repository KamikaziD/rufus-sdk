"""
PostgreSQL Persistence Adapter for Rufus Workflow Engine

Provides durable, ACID-compliant workflow state management with:
- Atomic task claiming for distributed   workers
- LISTEN/NOTIFY for real-time updates
- Saga compensation logging
- Audit trails and metrics
- Idempotency keys
"""

import asyncpg
import asyncio
import os
from typing import Optional, Dict, Any, List
from datetime import datetime
import logging
import uuid # For idempotency key generation if not provided

logger = logging.getLogger(__name__)

# Import from rufus package structure
from rufus.implementations.security.crypto_utils import encrypt_string, decrypt_string
from rufus.workflow import Workflow # Assuming Workflow class is in rufus.workflow
from rufus.providers.persistence import PersistenceProvider # Import the interface
from rufus.utils.serialization import serialize, deserialize  # High-performance JSON serialization


class PostgresPersistenceProvider(PersistenceProvider):
    """PostgreSQL-backed workflow persistence with advanced features"""

    def __init__(self, db_url: str, pool_min_size: int = None, pool_max_size: int = None):
        self.db_url = db_url
        self.pool: Optional[asyncpg.Pool] = None
        self._initialized = False
        self.encryption_enabled = os.getenv("ENABLE_ENCRYPTION_AT_REST", "false").lower() == "true"

        # Optimized pool settings (configurable via env or constructor)
        self.pool_min_size = pool_min_size or int(os.getenv("POSTGRES_POOL_MIN_SIZE", "10"))
        self.pool_max_size = pool_max_size or int(os.getenv("POSTGRES_POOL_MAX_SIZE", "50"))
        self.pool_command_timeout = int(os.getenv("POSTGRES_POOL_COMMAND_TIMEOUT", "10"))
        self.pool_max_queries = int(os.getenv("POSTGRES_POOL_MAX_QUERIES", "50000"))
        self.pool_max_inactive_lifetime = int(os.getenv("POSTGRES_POOL_MAX_INACTIVE_LIFETIME", "300"))

    async def initialize(self):
        """Create connection pool and verify schema"""
        if self._initialized:
            return

        try:
            self.pool = await asyncpg.create_pool(
                self.db_url,
                min_size=self.pool_min_size,
                max_size=self.pool_max_size,
                max_queries=self.pool_max_queries,
                max_inactive_connection_lifetime=self.pool_max_inactive_lifetime,
                command_timeout=self.pool_command_timeout,
                server_settings={
                    'application_name': 'rufus_workflow_engine',
                    'statement_timeout': f'{self.pool_command_timeout * 1000}',  # Convert to ms
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
            logger.info(
                f"PostgreSQL workflow store initialized with optimized pool "
                f"(min={self.pool_min_size}, max={self.pool_max_size}, "
                f"timeout={self.pool_command_timeout}s, max_queries={self.pool_max_queries})"
            )

        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL store: {e}")
            raise

    async def close(self):
        """Close connection pool"""
        if self.pool:
            await self.pool.close()
            self._initialized = False

    async def save_workflow(self, workflow_id: str, workflow_dict: Dict[str, Any]) -> None:
        """
        Save workflow state with atomic update

        Args:
            workflow_id: UUID of the workflow
            workflow_dict: Dictionary representation of the Workflow object to persist
        """
        if not self._initialized:
            await self.initialize()

        # Ensure workflow_dict has necessary keys, or provide defaults
        workflow_dict.setdefault('saga_mode', False)
        workflow_dict.setdefault('completed_steps_stack', [])
        workflow_dict.setdefault('data_region', 'us-east-1')
        workflow_dict.setdefault('priority', 5)
        workflow_dict.setdefault('metadata', {})


        # Encryption Logic
        state_json = serialize(workflow_dict['state'])
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
                    (id, workflow_type, workflow_version, definition_snapshot, current_step, status, state,
                     steps_config, state_model_path, updated_at, saga_mode,
                     completed_steps_stack, parent_execution_id, blocked_on_child_id,
                     data_region, priority, idempotency_key, metadata,
                     owner_id, org_id, encrypted_state, encryption_key_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21)
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
                workflow_dict.get('workflow_version'),
                serialize(workflow_dict.get('definition_snapshot')) if workflow_dict.get('definition_snapshot') else None,
                workflow_dict['current_step'],
                workflow_dict['status'],
                state_to_store,
                serialize(workflow_dict['steps_config']),
                workflow_dict['state_model_path'],
                workflow_dict['saga_mode'],
                serialize(workflow_dict['completed_steps_stack']),
                workflow_dict['parent_execution_id'],
                workflow_dict['blocked_on_child_id'],
                workflow_dict['data_region'],
                workflow_dict['priority'],
                workflow_dict['idempotency_key'],
                serialize(workflow_dict['metadata']),
                workflow_dict['owner_id'],
                workflow_dict['org_id'],
                encrypted_state_bytes,
                encryption_key_id
            )

            logger.debug(f"Saved workflow {workflow_id} (status={workflow_dict['status']})")

    async def load_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """
        Load workflow by ID

        Returns:
            Dictionary representation of Workflow instance or None if not found
        """
        if not self._initialized:
            await self.initialize()

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, workflow_type, workflow_version, definition_snapshot, current_step, status,
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
                        state_data = deserialize(decrypted_json)
                except Exception as e:
                    logger.error(f"Decryption failed for workflow {workflow_id}: {e}")
                    raise

            workflow_dict = {
                'id': str(row['id']),
                'workflow_type': row['workflow_type'],
                'workflow_version': row['workflow_version'],
                'definition_snapshot': deserialize(row['definition_snapshot']) if row['definition_snapshot'] else None,
                'current_step': row['current_step'],
                'status': row['status'],
                # Ensure state is a dict if it was a JSON string
                'state': deserialize(state_data) if isinstance(state_data, str) else state_data,
                'steps_config': deserialize(row['steps_config']) if isinstance(row['steps_config'], str) else row['steps_config'],
                'state_model_path': row['state_model_path'],
                'saga_mode': row['saga_mode'],
                'completed_steps_stack': deserialize(row['completed_steps_stack']) if isinstance(row['completed_steps_stack'], str) else row['completed_steps_stack'],
                'parent_execution_id': str(row['parent_execution_id']) if row['parent_execution_id'] else None,
                'blocked_on_child_id': str(row['blocked_on_child_id']) if row['blocked_on_child_id'] else None,
                'data_region': row['data_region'],
                'priority': row['priority'],
                'idempotency_key': row['idempotency_key'],
                'metadata': deserialize(row['metadata']) if isinstance(row['metadata'], str) else row['metadata'],
                'owner_id': row['owner_id'],
                'org_id': row['org_id']
            }

            return workflow_dict

    async def list_workflows(self, **filters) -> List[Dict[str, Any]]:
        """List workflows based on filters (e.g., status, workflow_type)"""
        if not self._initialized:
            await self.initialize()

        async with self.pool.acquire() as conn:
            query = "SELECT id, workflow_type, current_step, status, updated_at FROM workflow_executions"
            params = []
            conditions = []

            if 'status' in filters:
                conditions.append(f"status = ${len(params) + 1}")
                params.append(filters['status'])
            if 'workflow_type' in filters:
                conditions.append(f"workflow_type = ${len(params) + 1}")
                params.append(filters['workflow_type'])
            # Add other filters as needed

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            query += " ORDER BY updated_at DESC" # Default sorting

            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]


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
                    'task_data': deserialize(row['task_data']) if row['task_data'] else {},
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
                serialize(action_result),
                error_message,
                serialize(state_before) if state_before else None,
                serialize(state_after) if state_after else None,
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
                serialize(old_state) if old_state else None,
                serialize(new_state) if new_state else None,
                decision_rationale,
                serialize(metadata) if metadata else None
            )

    async def log_execution(
        self,
        workflow_id: str,
        log_level: str,
        message: str,
        step_name: str = None,
        metadata: Dict = None
    ):
        """Log an execution event for debugging"""
        if not self._initialized:
            await self.initialize()

        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO workflow_execution_logs
                    (workflow_id, execution_id, step_name, log_level, message, metadata, logged_at)
                VALUES ($1, $1, $2, $3, $4, $5, NOW())
            """,
                workflow_id, # Reusing workflow_id as execution_id for now
                step_name,
                log_level,
                message,
                serialize(metadata) if metadata else None
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
                serialize(tags) if tags else None
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
                serialize(initial_data) if initial_data else '{}',
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
                serialize(task_data) if task_data else '{}',
                idempotency_key,
                serialize(metadata) if metadata else '{}',
                max_retries
            )
            return dict(row)

    async def update_task_status(self, task_id: str, status: str, result: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None) -> None:
        """
        Updates the status of a task record in the database.
        """
        if not self._initialized:
            await self.initialize()

        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE tasks
                SET status = $1,
                    result = $2,
                    last_error = $3,
                    completed_at = NOW(),
                    updated_at = NOW()
                WHERE task_id = $4
            """, status, serialize(result) if result else None, error_message, task_id)

    async def get_task_record(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a task record from the database.
        """
        if not self._initialized:
            await self.initialize()

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT task_id, execution_id, step_name, step_index, status, task_data, idempotency_key, retry_count, max_retries
                FROM tasks
                WHERE task_id = $1
            """, task_id)

            if row:
                return {
                    'task_id': str(row['task_id']),
                    'execution_id': str(row['execution_id']),
                    'step_name': row['step_name'],
                    'step_index': row['step_index'],
                    'status': row['status'],
                    'task_data': deserialize(row['task_data']) if row['task_data'] else {},
                    'idempotency_key': row['idempotency_key'],
                    'retry_count': row['retry_count'],
                    'max_retries': row['max_retries']
                }
            return None

    # --- Heartbeat Operations (Zombie Detection & Recovery) ---

    async def upsert_heartbeat(
        self,
        workflow_id: uuid.UUID,
        worker_id: str,
        current_step: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Upsert heartbeat record for a workflow.

        This is used by HeartbeatManager to track worker health. If a worker
        crashes, the heartbeat becomes stale and can be detected by ZombieScanner.

        Args:
            workflow_id: ID of the workflow being processed
            worker_id: Identifier of the worker
            current_step: Name of the current step (optional)
            metadata: Additional context (PID, hostname, etc.)
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workflow_heartbeats (
                    workflow_id, worker_id, last_heartbeat, current_step,
                    step_started_at, metadata
                )
                VALUES ($1, $2, NOW(), $3, NOW(), $4)
                ON CONFLICT (workflow_id)
                DO UPDATE SET
                    worker_id = EXCLUDED.worker_id,
                    last_heartbeat = NOW(),
                    current_step = EXCLUDED.current_step,
                    metadata = EXCLUDED.metadata
                """,
                str(workflow_id),
                worker_id,
                current_step,
                serialize(metadata or {})
            )

    async def delete_heartbeat(self, workflow_id: uuid.UUID) -> None:
        """
        Delete heartbeat record when workflow completes or step finishes.

        Args:
            workflow_id: ID of the workflow
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM workflow_heartbeats WHERE workflow_id = $1",
                str(workflow_id)
            )

    async def get_stale_heartbeats(
        self,
        stale_threshold_seconds: int = 120
    ) -> List[Dict[str, Any]]:
        """
        Find workflows with stale heartbeats (potential zombies).

        A stale heartbeat indicates a worker may have crashed while processing
        a workflow step.

        Args:
            stale_threshold_seconds: Consider heartbeats older than this as stale

        Returns:
            List of stale heartbeat records with workflow details
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    h.workflow_id,
                    h.worker_id,
                    h.last_heartbeat,
                    h.current_step,
                    h.step_started_at,
                    h.metadata,
                    w.workflow_type,
                    w.status,
                    w.current_step as workflow_current_step
                FROM workflow_heartbeats h
                JOIN workflow_executions w ON h.workflow_id = w.id::text
                WHERE h.last_heartbeat < NOW() - INTERVAL '%s seconds'
                AND w.status IN ('RUNNING', 'WAITING_EXTERNAL_INPUT', 'WAITING_CHILD_HUMAN_INPUT')
                ORDER BY h.last_heartbeat ASC
                """,
                stale_threshold_seconds
            )

            return [
                {
                    'workflow_id': row['workflow_id'],
                    'worker_id': row['worker_id'],
                    'last_heartbeat': row['last_heartbeat'],
                    'current_step': row['current_step'],
                    'step_started_at': row['step_started_at'],
                    'metadata': deserialize(row['metadata']) if row['metadata'] else {},
                    'workflow_type': row['workflow_type'],
                    'status': row['status'],
                    'workflow_current_step': row['workflow_current_step']
                }
                for row in rows
            ]

    async def mark_workflow_as_crashed(
        self,
        workflow_id: uuid.UUID,
        reason: str
    ) -> None:
        """
        Mark a workflow as failed due to worker crash.

        Updates the workflow status to FAILED_WORKER_CRASH and logs the reason.

        Args:
            workflow_id: ID of the workflow
            reason: Description of why the workflow was marked as crashed
        """
        async with self.pool.acquire() as conn:
            # Update workflow status
            await conn.execute(
                """
                UPDATE workflow_executions
                SET status = 'FAILED_WORKER_CRASH',
                    updated_at = NOW()
                WHERE id = $1::uuid
                """,
                str(workflow_id)
            )

            # Log audit event
            await conn.execute(
                """
                INSERT INTO workflow_audit_log (
                    workflow_id, event_type, step_name, recorded_at, metadata
                )
                VALUES ($1::uuid, 'WORKER_CRASH_DETECTED', NULL, NOW(), $2)
                """,
                str(workflow_id),
                serialize({'reason': reason, 'recovery_action': 'marked_as_failed'})
            )

            # Log execution event
            await conn.execute(
                """
                INSERT INTO workflow_execution_logs (
                    workflow_id, log_level, message, logged_at, metadata
                )
                VALUES ($1::uuid, 'ERROR', $2, NOW(), $3)
                """,
                str(workflow_id),
                f"Workflow marked as FAILED_WORKER_CRASH: {reason}",
                serialize({'recovery_action': 'zombie_scanner', 'automated': True})
            )

    # --- Synchronous Bridge Methods (for Celery tasks) ---

    def _run_coroutine_sync(self, coro):
        """Helper to run a coroutine synchronously using the PostgresExecutor."""
        from rufus.implementations.execution.postgres_executor import pg_executor
        return pg_executor.run_coroutine_sync(coro)

    def register_scheduled_workflow_sync(self, schedule_name: str, workflow_type: str, cron_expression: str, initial_data: Dict[str, Any] = None):
        """Sync wrapper for register_scheduled_workflow."""
        self._run_coroutine_sync(
            self.register_scheduled_workflow(schedule_name, workflow_type, cron_expression, initial_data)
        )

    def log_execution_sync(self, workflow_id: str, log_level: str, message: str, step_name: str = None, metadata: Dict = None):
        """Sync wrapper for log_execution."""
        self._run_coroutine_sync(
            self.log_execution(workflow_id, log_level, message, step_name=step_name, metadata=metadata)
        )

    def log_audit_event_sync(self, workflow_id: str, event_type: str, step_name: str = None, new_state: Dict = None, metadata: Dict = None):
        """Sync wrapper for log_audit_event."""
        self._run_coroutine_sync(
            self.log_audit_event(workflow_id, event_type, step_name=step_name, new_state=new_state, metadata=metadata)
        )

    def log_compensation_sync(self, execution_id: str, step_name: str, step_index: int, action_type: str, action_result: Dict, state_before: Dict = None, state_after: Dict = None, error_message: str = None):
        """Sync wrapper for log_compensation."""
        self._run_coroutine_sync(
            self.log_compensation(
                execution_id, step_name, step_index, action_type, action_result, 
                state_before=state_before, state_after=state_after, error_message=error_message
            )
        )
    
    def record_metric_sync(self, workflow_id: str, workflow_type: str, metric_name: str, metric_value: float, unit: str = None, step_name: str = None):
        """Sync wrapper for record_metric."""
        self._run_coroutine_sync(
            self.record_metric(workflow_id, workflow_type, metric_name, metric_value, unit=unit, step_name=step_name)
        )

    def create_task_record_sync(self, execution_id: str, step_name: str, step_index: int, task_data: Dict[str, Any] = None, idempotency_key: str = None, metadata: Dict[str, Any] = None, max_retries: int = 3) -> Dict[str, Any]:
        """Sync wrapper for create_task_record."""
        return self._run_coroutine_sync(
            self.create_task_record(execution_id, step_name, step_index, task_data, idempotency_key, metadata, max_retries)
        )

    def update_task_status_sync(self, task_id: str, status: str, result: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None) -> None:
        """Sync wrapper for update_task_status."""
        self._run_coroutine_sync(
            self.update_task_status(task_id, status, result, error_message)
        )

    def get_task_record_sync(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Sync wrapper for get_task_record."""
        return self._run_coroutine_sync(
            self.get_task_record(task_id)
        )

# Singleton instance registry per event loop
_postgres_stores: Dict[asyncio.AbstractEventLoop, PostgresPersistenceProvider] = {}


async def get_postgres_store(db_url: str = None) -> PostgresPersistenceProvider:
    """Get or create PostgreSQL store singleton for the current event loop"""
    global _postgres_stores
    
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Should not happen in async context, but fallback or raise
        raise RuntimeError("get_postgres_store must be called within a running event loop")

    if loop not in _postgres_stores:
        if db_url is None:
            db_url = os.getenv('DATABASE_URL')
            if not db_url:
                raise ValueError("DATABASE_URL environment variable not set")

        store = PostgresPersistenceProvider(db_url)
        await store.initialize()
        _postgres_stores[loop] = store

    return _postgres_stores[loop]
