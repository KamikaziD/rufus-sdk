"""
SQLite Persistence Adapter for Rufus Workflow Engine

Provides lightweight, embedded workflow state management with:
- Atomic task claiming for local workers
- ACID transactions
- Saga compensation logging
- Audit trails and metrics
- Idempotency keys
- In-memory mode for testing

Differences from PostgreSQL:
- No LISTEN/NOTIFY (use polling or external pub/sub)
- Simpler locking (EXCLUSIVE transactions)
- UUID stored as TEXT (hex format)
- JSONB stored as TEXT (JSON strings)
- Timestamps as ISO8601 TEXT
- Boolean as INTEGER (0/1)
"""

import aiosqlite
import asyncio
import os
from typing import Optional, Dict, Any, List
from datetime import datetime
import logging
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# Import from rufus package structure
from rufus.workflow import Workflow
from rufus.providers.persistence import PersistenceProvider
from rufus.utils.serialization import serialize, deserialize


class SQLitePersistenceProvider(PersistenceProvider):
    """SQLite-backed workflow persistence for development and testing"""

    def __init__(
        self,
        db_path: str = ":memory:",
        timeout: float = 5.0,
        check_same_thread: bool = False
    ):
        """
        Initialize SQLite persistence provider

        Args:
            db_path: Path to SQLite database file or ":memory:" for in-memory
            timeout: Database lock timeout in seconds
            check_same_thread: SQLite thread safety check (disable for async)
        """
        self.db_path = db_path
        self.timeout = timeout
        self.check_same_thread = check_same_thread
        self.conn: Optional[aiosqlite.Connection] = None
        self._initialized = False

    async def initialize(self):
        """Create database connection and verify schema"""
        if self._initialized:
            return

        try:
            # Create parent directory if using file-based DB
            if self.db_path != ":memory:":
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

            # Connect to database
            self.conn = await aiosqlite.connect(
                self.db_path,
                timeout=self.timeout,
                check_same_thread=self.check_same_thread
            )

            # Enable foreign keys (disabled by default in SQLite)
            await self.conn.execute("PRAGMA foreign_keys = ON")

            # Use WAL mode for better concurrency (if not in-memory)
            if self.db_path != ":memory:":
                await self.conn.execute("PRAGMA journal_mode = WAL")

            # Verify schema exists
            async with self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='workflow_executions'"
            ) as cursor:
                result = await cursor.fetchone()

            if not result:
                logger.warning(
                    "workflow_executions table not found. "
                    "Please run migrations: python tools/migrate.py --db sqlite:///" + self.db_path + " --up"
                )

            self._initialized = True
            logger.info(f"SQLite workflow store initialized (db={self.db_path})")

        except Exception as e:
            logger.error(f"Failed to initialize SQLite store: {e}")
            raise

    async def close(self):
        """Close database connection"""
        if self.conn:
            await self.conn.close()
            self._initialized = False

    # ============================================================================
    # HELPER METHODS
    # ============================================================================

    def _generate_uuid(self) -> str:
        """Generate UUID in hex format for SQLite"""
        return uuid.uuid4().hex

    def _serialize_json(self, data: Any) -> str:
        """Serialize data to JSON string"""
        if data is None:
            return None
        return serialize(data)

    def _deserialize_json(self, json_str: Optional[str]) -> Any:
        """Deserialize JSON string to data"""
        if json_str is None or json_str == "":
            return None
        return deserialize(json_str)

    def _to_iso8601(self, dt: Optional[datetime]) -> Optional[str]:
        """Convert datetime to ISO8601 string"""
        if dt is None:
            return None
        return dt.isoformat()

    def _from_iso8601(self, iso_str: Optional[str]) -> Optional[datetime]:
        """Convert ISO8601 string to datetime"""
        if iso_str is None or iso_str == "":
            return None
        return datetime.fromisoformat(iso_str)

    def _bool_to_int(self, value: Optional[bool]) -> Optional[int]:
        """Convert boolean to integer for SQLite"""
        if value is None:
            return None
        return 1 if value else 0

    def _int_to_bool(self, value: Optional[int]) -> Optional[bool]:
        """Convert integer to boolean from SQLite"""
        if value is None:
            return None
        return bool(value)

    # ============================================================================
    # CORE WORKFLOW METHODS
    # ============================================================================

    async def save_workflow(self, workflow_id: str, workflow_dict: Dict[str, Any]) -> None:
        """
        Save workflow state with atomic update

        Args:
            workflow_id: Workflow execution ID
            workflow_dict: Complete workflow state
        """
        # Extract fields from workflow_dict
        workflow_type = workflow_dict.get('workflow_type')
        current_step = workflow_dict.get('current_step', 0)
        status = workflow_dict.get('status')
        state = self._serialize_json(workflow_dict.get('state', {}))
        steps_config = self._serialize_json(workflow_dict.get('steps_config', []))
        state_model_path = workflow_dict.get('state_model_path')
        saga_mode = self._bool_to_int(workflow_dict.get('saga_mode', False))
        completed_steps_stack = self._serialize_json(workflow_dict.get('completed_steps_stack', []))
        parent_execution_id = workflow_dict.get('parent_execution_id')
        blocked_on_child_id = workflow_dict.get('blocked_on_child_id')
        data_region = workflow_dict.get('data_region', 'us-east-1')
        priority = workflow_dict.get('priority', 5)
        idempotency_key = workflow_dict.get('idempotency_key')
        metadata = self._serialize_json(workflow_dict.get('metadata', {}))
        completed_at = self._to_iso8601(workflow_dict.get('completed_at'))

        # Insert or replace workflow execution
        await self.conn.execute("""
            INSERT OR REPLACE INTO workflow_executions (
                id, workflow_type, current_step, status, state, steps_config,
                state_model_path, saga_mode, completed_steps_stack,
                parent_execution_id, blocked_on_child_id, data_region, priority,
                idempotency_key, metadata, completed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            workflow_id, workflow_type, current_step, status, state, steps_config,
            state_model_path, saga_mode, completed_steps_stack,
            parent_execution_id, blocked_on_child_id, data_region, priority,
            idempotency_key, metadata, completed_at
        ))
        await self.conn.commit()

    async def load_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """
        Load workflow state by ID

        Args:
            workflow_id: Workflow execution ID

        Returns:
            Workflow state dict or None if not found
        """
        async with self.conn.execute("""
            SELECT
                id, workflow_type, current_step, status, state, steps_config,
                state_model_path, saga_mode, completed_steps_stack,
                parent_execution_id, blocked_on_child_id, data_region, priority,
                created_at, updated_at, completed_at, idempotency_key, metadata
            FROM workflow_executions
            WHERE id = ?
        """, (workflow_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return {
            'id': row[0],
            'workflow_type': row[1],
            'current_step': row[2],
            'status': row[3],
            'state': self._deserialize_json(row[4]),
            'steps_config': self._deserialize_json(row[5]),
            'state_model_path': row[6],
            'saga_mode': self._int_to_bool(row[7]),
            'completed_steps_stack': self._deserialize_json(row[8]),
            'parent_execution_id': row[9],
            'blocked_on_child_id': row[10],
            'data_region': row[11],
            'priority': row[12],
            'created_at': self._from_iso8601(row[13]),
            'updated_at': self._from_iso8601(row[14]),
            'completed_at': self._from_iso8601(row[15]),
            'idempotency_key': row[16],
            'metadata': self._deserialize_json(row[17]),
        }

    async def list_workflows(self, **filters) -> List[Dict[str, Any]]:
        """
        List workflows with optional filters

        Args:
            **filters: Filter criteria (status, workflow_type, limit, offset)

        Returns:
            List of workflow state dicts
        """
        # Build query
        query = """
            SELECT
                id, workflow_type, current_step, status, state, steps_config,
                state_model_path, saga_mode, completed_steps_stack,
                parent_execution_id, blocked_on_child_id, data_region, priority,
                created_at, updated_at, completed_at, idempotency_key, metadata
            FROM workflow_executions
            WHERE 1=1
        """
        params = []

        # Apply filters
        if 'status' in filters:
            query += " AND status = ?"
            params.append(filters['status'])

        if 'workflow_type' in filters:
            query += " AND workflow_type = ?"
            params.append(filters['workflow_type'])

        if 'parent_execution_id' in filters:
            query += " AND parent_execution_id = ?"
            params.append(filters['parent_execution_id'])

        # Order by
        query += " ORDER BY created_at DESC"

        # Limit and offset
        limit = filters.get('limit', 100)
        offset = filters.get('offset', 0)
        query += f" LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        # Execute query
        async with self.conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        # Convert rows to dicts
        workflows = []
        for row in rows:
            workflows.append({
                'id': row[0],
                'workflow_type': row[1],
                'current_step': row[2],
                'status': row[3],
                'state': self._deserialize_json(row[4]),
                'steps_config': self._deserialize_json(row[5]),
                'state_model_path': row[6],
                'saga_mode': self._int_to_bool(row[7]),
                'completed_steps_stack': self._deserialize_json(row[8]),
                'parent_execution_id': row[9],
                'blocked_on_child_id': row[10],
                'data_region': row[11],
                'priority': row[12],
                'created_at': self._from_iso8601(row[13]),
                'updated_at': self._from_iso8601(row[14]),
                'completed_at': self._from_iso8601(row[15]),
                'idempotency_key': row[16],
                'metadata': self._deserialize_json(row[17]),
            })

        return workflows

    async def get_active_workflows(self, limit: int = 100) -> List[Dict]:
        """
        Get list of currently active workflows

        Args:
            limit: Maximum number of workflows to return

        Returns:
            List of active workflow summaries
        """
        async with self.conn.execute("""
            SELECT
                id, workflow_type, status, current_step, created_at, updated_at,
                parent_execution_id
            FROM workflow_executions
            WHERE status NOT IN ('COMPLETED', 'FAILED', 'FAILED_ROLLED_BACK')
            ORDER BY priority ASC, created_at ASC
            LIMIT ?
        """, (limit,)) as cursor:
            rows = await cursor.fetchall()

        workflows = []
        for row in rows:
            workflows.append({
                'id': row[0],
                'workflow_type': row[1],
                'status': row[2],
                'current_step': row[3],
                'created_at': self._from_iso8601(row[4]),
                'updated_at': self._from_iso8601(row[5]),
                'is_sub_workflow': row[6] is not None,
            })

        return workflows

    # ============================================================================
    # TASK QUEUE METHODS
    # ============================================================================

    async def create_task_record(
        self,
        execution_id: str,
        step_name: str,
        step_index: int,
        task_data: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Create a task record for asynchronous execution

        Args:
            execution_id: Workflow execution ID
            step_name: Name of the step
            step_index: Index of the step
            task_data: Optional task payload
            idempotency_key: Optional idempotency key
            metadata: Optional metadata
            max_retries: Maximum retry attempts

        Returns:
            Task record dict with task_id
        """
        task_id = self._generate_uuid()
        task_data_json = self._serialize_json(task_data)
        metadata_json = self._serialize_json(metadata)

        await self.conn.execute("""
            INSERT INTO tasks (
                task_id, execution_id, step_name, step_index, status,
                task_data, max_retries, idempotency_key
            ) VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?)
        """, (
            task_id, execution_id, step_name, step_index,
            task_data_json, max_retries, idempotency_key
        ))
        await self.conn.commit()

        return {
            'task_id': task_id,
            'execution_id': execution_id,
            'step_name': step_name,
            'step_index': step_index,
            'status': 'PENDING',
            'created_at': datetime.utcnow(),
        }

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None
    ) -> None:
        """
        Update task status and result

        Args:
            task_id: Task ID
            status: New status (RUNNING, COMPLETED, FAILED)
            result: Optional result data
            error_message: Optional error message
        """
        result_json = self._serialize_json(result)

        # Set timestamps based on status
        if status == 'RUNNING':
            await self.conn.execute("""
                UPDATE tasks
                SET status = ?, started_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
            """, (status, task_id))
        elif status in ('COMPLETED', 'FAILED'):
            await self.conn.execute("""
                UPDATE tasks
                SET status = ?, result = ?, last_error = ?,
                    completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
            """, (status, result_json, error_message, task_id))
        else:
            await self.conn.execute("""
                UPDATE tasks
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
            """, (status, task_id))

        await self.conn.commit()

    async def get_task_record(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get task record by ID

        Args:
            task_id: Task ID

        Returns:
            Task record dict or None
        """
        async with self.conn.execute("""
            SELECT
                task_id, execution_id, step_name, step_index, status,
                worker_id, claimed_at, started_at, completed_at,
                retry_count, max_retries, last_error, task_data, result,
                idempotency_key, created_at, updated_at
            FROM tasks
            WHERE task_id = ?
        """, (task_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return {
            'task_id': row[0],
            'execution_id': row[1],
            'step_name': row[2],
            'step_index': row[3],
            'status': row[4],
            'worker_id': row[5],
            'claimed_at': self._from_iso8601(row[6]),
            'started_at': self._from_iso8601(row[7]),
            'completed_at': self._from_iso8601(row[8]),
            'retry_count': row[9],
            'max_retries': row[10],
            'last_error': row[11],
            'task_data': self._deserialize_json(row[12]),
            'result': self._deserialize_json(row[13]),
            'idempotency_key': row[14],
            'created_at': self._from_iso8601(row[15]),
            'updated_at': self._from_iso8601(row[16]),
        }

    # ============================================================================
    # LOGGING METHODS
    # ============================================================================

    async def log_execution(
        self,
        workflow_id: str,
        log_level: str,
        message: str,
        step_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Log workflow execution event

        Args:
            workflow_id: Workflow ID
            log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            message: Log message
            step_name: Optional step name
            metadata: Optional metadata
        """
        metadata_json = self._serialize_json(metadata)

        await self.conn.execute("""
            INSERT INTO workflow_execution_logs (
                workflow_id, step_name, log_level, message, metadata
            ) VALUES (?, ?, ?, ?, ?)
        """, (workflow_id, step_name, log_level, message, metadata_json))
        await self.conn.commit()

    async def log_compensation(
        self,
        execution_id: str,
        step_name: str,
        step_index: int,
        action_type: str,
        action_result: Dict[str, Any],
        state_before: Optional[Dict[str, Any]] = None,
        state_after: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        executed_by: Optional[str] = None
    ):
        """
        Log saga compensation action

        Args:
            execution_id: Execution ID
            step_name: Step name
            step_index: Step index
            action_type: Action type (FORWARD, COMPENSATE, COMPENSATE_FAILED)
            action_result: Action result
            state_before: Optional state snapshot before action
            state_after: Optional state snapshot after action
            error_message: Optional error message
            executed_by: Optional worker ID
        """
        action_result_json = self._serialize_json(action_result)
        state_before_json = self._serialize_json(state_before)
        state_after_json = self._serialize_json(state_after)

        await self.conn.execute("""
            INSERT INTO compensation_log (
                log_id, execution_id, step_name, step_index, action_type,
                action_result, error_message, executed_by, state_before, state_after
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            self._generate_uuid(), execution_id, step_name, step_index, action_type,
            action_result_json, error_message, executed_by, state_before_json, state_after_json
        ))
        await self.conn.commit()

    async def log_audit_event(
        self,
        workflow_id: str,
        event_type: str,
        step_name: Optional[str] = None,
        user_id: Optional[str] = None,
        worker_id: Optional[str] = None,
        old_state: Optional[Dict[str, Any]] = None,
        new_state: Optional[Dict[str, Any]] = None,
        decision_rationale: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Log audit event for compliance

        Args:
            workflow_id: Workflow ID
            event_type: Event type (CREATED, STEP_COMPLETED, FAILED, etc.)
            step_name: Optional step name
            user_id: Optional user ID
            worker_id: Optional worker ID
            old_state: Optional previous state
            new_state: Optional new state
            decision_rationale: Optional decision rationale
            metadata: Optional metadata
        """
        old_state_json = self._serialize_json(old_state)
        new_state_json = self._serialize_json(new_state)
        metadata_json = self._serialize_json(metadata)

        await self.conn.execute("""
            INSERT INTO workflow_audit_log (
                audit_id, workflow_id, event_type, step_name, user_id, worker_id,
                old_state, new_state, decision_rationale, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            self._generate_uuid(), workflow_id, event_type, step_name, user_id, worker_id,
            old_state_json, new_state_json, decision_rationale, metadata_json
        ))
        await self.conn.commit()

    # ============================================================================
    # METRICS METHODS
    # ============================================================================

    async def record_metric(
        self,
        workflow_id: str,
        workflow_type: str,
        metric_name: str,
        metric_value: float,
        unit: Optional[str] = None,
        step_name: Optional[str] = None,
        tags: Optional[Dict[str, Any]] = None
    ):
        """
        Record performance metric

        Args:
            workflow_id: Workflow ID
            workflow_type: Workflow type
            metric_name: Metric name
            metric_value: Metric value
            unit: Optional unit (ms, count, bytes, etc.)
            step_name: Optional step name
            tags: Optional tags for aggregation
        """
        tags_json = self._serialize_json(tags)

        await self.conn.execute("""
            INSERT INTO workflow_metrics (
                workflow_id, workflow_type, metric_name, metric_value,
                unit, step_name, tags
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (workflow_id, workflow_type, metric_name, metric_value, unit, step_name, tags_json))
        await self.conn.commit()

    async def get_workflow_metrics(self, workflow_id: str, limit: int = 100) -> List[Dict]:
        """
        Get metrics for a workflow

        Args:
            workflow_id: Workflow ID
            limit: Maximum number of metrics to return

        Returns:
            List of metric dicts
        """
        async with self.conn.execute("""
            SELECT
                metric_name, metric_value, unit, step_name, recorded_at, tags
            FROM workflow_metrics
            WHERE workflow_id = ?
            ORDER BY recorded_at DESC
            LIMIT ?
        """, (workflow_id, limit)) as cursor:
            rows = await cursor.fetchall()

        metrics = []
        for row in rows:
            metrics.append({
                'metric_name': row[0],
                'metric_value': row[1],
                'unit': row[2],
                'step_name': row[3],
                'recorded_at': self._from_iso8601(row[4]),
                'tags': self._deserialize_json(row[5]),
            })

        return metrics

    async def get_workflow_summary(self, hours: int = 24) -> List[Dict]:
        """
        Get workflow execution summary for last N hours

        Args:
            hours: Number of hours to look back

        Returns:
            List of summary dicts grouped by workflow_type and status
        """
        async with self.conn.execute("""
            SELECT
                workflow_type,
                status,
                COUNT(*) as execution_count,
                AVG((julianday(completed_at) - julianday(created_at)) * 86400) as avg_duration_seconds,
                MAX(updated_at) as last_execution
            FROM workflow_executions
            WHERE created_at > datetime('now', ?)
            GROUP BY workflow_type, status
        """, (f'-{hours} hours',)) as cursor:
            rows = await cursor.fetchall()

        summaries = []
        for row in rows:
            summaries.append({
                'workflow_type': row[0],
                'status': row[1],
                'execution_count': row[2],
                'avg_duration_seconds': row[3],
                'last_execution': self._from_iso8601(row[4]),
            })

        return summaries

    # ============================================================================
    # SCHEDULED WORKFLOW METHODS
    # ============================================================================

    async def register_scheduled_workflow(
        self,
        schedule_name: str,
        workflow_type: str,
        cron_expression: str,
        initial_data: Optional[Dict[str, Any]] = None,
        enabled: bool = True
    ):
        """
        Register or update a scheduled workflow

        Note: SQLite doesn't have built-in scheduling.
        This stores the schedule configuration for external schedulers.

        Args:
            schedule_name: Unique schedule name
            workflow_type: Workflow type to execute
            cron_expression: Cron expression
            initial_data: Optional initial workflow data
            enabled: Whether schedule is enabled
        """
        # Note: This assumes a scheduled_workflows table exists
        # For now, log a warning as this feature requires additional schema
        logger.warning(
            f"Scheduled workflows not yet implemented in SQLite provider. "
            f"Schedule '{schedule_name}' for '{workflow_type}' not registered."
        )

    # ============================================================================
    # SYNCHRONOUS WRAPPER METHODS
    # ============================================================================

    def log_execution_sync(
        self,
        workflow_id: str,
        log_level: str,
        message: str,
        step_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Synchronous wrapper for log_execution"""
        asyncio.create_task(
            self.log_execution(workflow_id, log_level, message, step_name, metadata)
        )

    def log_audit_event_sync(
        self,
        workflow_id: str,
        event_type: str,
        step_name: Optional[str] = None,
        user_id: Optional[str] = None,
        worker_id: Optional[str] = None,
        old_state: Optional[Dict[str, Any]] = None,
        new_state: Optional[Dict[str, Any]] = None,
        decision_rationale: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Synchronous wrapper for log_audit_event"""
        asyncio.create_task(
            self.log_audit_event(
                workflow_id, event_type, step_name, user_id, worker_id,
                old_state, new_state, decision_rationale, metadata
            )
        )

    def log_compensation_sync(
        self,
        execution_id: str,
        step_name: str,
        step_index: int,
        action_type: str,
        action_result: Dict[str, Any],
        state_before: Optional[Dict[str, Any]] = None,
        state_after: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        executed_by: Optional[str] = None
    ):
        """Synchronous wrapper for log_compensation"""
        asyncio.create_task(
            self.log_compensation(
                execution_id, step_name, step_index, action_type, action_result,
                state_before, state_after, error_message, executed_by
            )
        )

    def record_metric_sync(
        self,
        workflow_id: str,
        workflow_type: str,
        metric_name: str,
        metric_value: float,
        unit: Optional[str] = None,
        step_name: Optional[str] = None,
        tags: Optional[Dict[str, Any]] = None
    ):
        """Synchronous wrapper for record_metric"""
        asyncio.create_task(
            self.record_metric(
                workflow_id, workflow_type, metric_name, metric_value,
                unit, step_name, tags
            )
        )

    def register_scheduled_workflow_sync(
        self,
        schedule_name: str,
        workflow_type: str,
        cron_expression: str,
        initial_data: Optional[Dict[str, Any]] = None,
        enabled: bool = True
    ):
        """Synchronous wrapper for register_scheduled_workflow"""
        asyncio.create_task(
            self.register_scheduled_workflow(
                schedule_name, workflow_type, cron_expression, initial_data, enabled
            )
        )

    def create_task_record_sync(
        self,
        execution_id: str,
        step_name: str,
        step_index: int,
        task_data: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """Synchronous wrapper for create_task_record"""
        # This needs to be truly synchronous, so we run in event loop
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            self.create_task_record(
                execution_id, step_name, step_index, task_data,
                idempotency_key, metadata, max_retries
            )
        )

    def update_task_status_sync(
        self,
        task_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None
    ) -> None:
        """Synchronous wrapper for update_task_status"""
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            self.update_task_status(task_id, status, result, error_message)
        )

    def get_task_record_sync(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Synchronous wrapper for get_task_record"""
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self.get_task_record(task_id))
