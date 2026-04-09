"""
SQLite Persistence Adapter for Ruvon Workflow Engine

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

# Import from ruvon package structure
from ruvon.workflow import Workflow
from ruvon.providers.persistence import PersistenceProvider
from ruvon.providers.dtos import WorkflowRecord, TaskRecord, MetricRecord
from ruvon.utils.serialization import serialize, deserialize


# SQLite schema definition - matches PostgreSQL schema with type conversions
SQLITE_SCHEMA = """
-- Core workflow execution state
CREATE TABLE IF NOT EXISTS workflow_executions (
    id TEXT PRIMARY KEY,
    workflow_type TEXT NOT NULL,
    workflow_version TEXT,
    definition_snapshot TEXT,
    current_step INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT '{}',
    steps_config TEXT NOT NULL DEFAULT '[]',
    state_model_path TEXT NOT NULL,
    saga_mode INTEGER DEFAULT 0,
    completed_steps_stack TEXT DEFAULT '[]',
    parent_execution_id TEXT,
    blocked_on_child_id TEXT,
    data_region TEXT DEFAULT 'us-east-1',
    priority INTEGER DEFAULT 5,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    idempotency_key TEXT UNIQUE,
    metadata TEXT DEFAULT '{}',
    FOREIGN KEY (parent_execution_id) REFERENCES workflow_executions(id) ON DELETE CASCADE
);

-- Task queue
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    step_name TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    worker_id TEXT,
    claimed_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    last_error TEXT,
    task_data TEXT,
    result TEXT,
    idempotency_key TEXT UNIQUE,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (execution_id) REFERENCES workflow_executions(id) ON DELETE CASCADE
);

-- Compensation log (Saga pattern)
CREATE TABLE IF NOT EXISTS compensation_log (
    log_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    step_name TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    action_result TEXT,
    error_message TEXT,
    executed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    executed_by TEXT,
    state_before TEXT,
    state_after TEXT,
    FOREIGN KEY (execution_id) REFERENCES workflow_executions(id) ON DELETE CASCADE
);

-- Audit log
CREATE TABLE IF NOT EXISTS workflow_audit_log (
    audit_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    execution_id TEXT,
    event_type TEXT NOT NULL,
    step_name TEXT,
    user_id TEXT,
    worker_id TEXT,
    recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
    old_state TEXT,
    new_state TEXT,
    state_diff TEXT,
    decision_rationale TEXT,
    metadata TEXT DEFAULT '{}',
    ip_address TEXT,
    user_agent TEXT,
    FOREIGN KEY (workflow_id) REFERENCES workflow_executions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_audit_workflow_id ON workflow_audit_log(workflow_id);

-- Execution logs
CREATE TABLE IF NOT EXISTS workflow_execution_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    execution_id TEXT,
    step_name TEXT,
    log_level TEXT NOT NULL,
    message TEXT NOT NULL,
    logged_at TEXT DEFAULT CURRENT_TIMESTAMP,
    worker_id TEXT,
    metadata TEXT DEFAULT '{}',
    trace_id TEXT,
    correlation_id TEXT
);

-- Metrics
CREATE TABLE IF NOT EXISTS workflow_metrics (
    metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    workflow_type TEXT,
    execution_id TEXT,
    step_name TEXT,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    unit TEXT,
    recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
    tags TEXT DEFAULT '{}'
);

-- Heartbeat tracking (zombie detection & recovery)
CREATE TABLE IF NOT EXISTS workflow_heartbeats (
    workflow_id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    current_step TEXT,
    step_started_at TEXT,
    metadata TEXT DEFAULT '{}',
    FOREIGN KEY (workflow_id) REFERENCES workflow_executions(id) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_workflow_status ON workflow_executions(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_type ON workflow_executions(workflow_type);
CREATE INDEX IF NOT EXISTS idx_workflow_priority ON workflow_executions(priority, created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_claim ON tasks(status, created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_execution ON tasks(execution_id, step_index);
CREATE INDEX IF NOT EXISTS idx_logs_workflow ON workflow_execution_logs(workflow_id, logged_at DESC);
CREATE INDEX IF NOT EXISTS idx_metrics_workflow ON workflow_metrics(workflow_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_heartbeat_time ON workflow_heartbeats(last_heartbeat ASC);

-- Triggers for updated_at timestamps
CREATE TRIGGER IF NOT EXISTS update_workflow_timestamp
AFTER UPDATE ON workflow_executions
BEGIN
    UPDATE workflow_executions SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_task_timestamp
AFTER UPDATE ON tasks
BEGIN
    UPDATE tasks SET updated_at = CURRENT_TIMESTAMP WHERE task_id = NEW.task_id;
END;

-- ===================================================================
-- Edge-Specific Tables (new deployments)
-- SyncManager and ConfigManager still use tasks table (legacy support)
-- ===================================================================

CREATE TABLE IF NOT EXISTS saf_pending_transactions (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL,
    idempotency_key TEXT UNIQUE NOT NULL,
    workflow_id TEXT,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    card_token TEXT NOT NULL,
    card_last_four TEXT,
    encrypted_payload TEXT,
    encryption_key_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending_sync',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    queued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    synced_at TEXT,
    sync_attempts INTEGER NOT NULL DEFAULT 0,
    last_sync_error TEXT,
    metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_saf_status ON saf_pending_transactions(status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_saf_idempotency ON saf_pending_transactions(idempotency_key);

CREATE TABLE IF NOT EXISTS device_config_cache (
    device_id TEXT PRIMARY KEY,
    config_version TEXT NOT NULL,
    config_data TEXT NOT NULL,
    etag TEXT,
    cached_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_poll_at TEXT
);

CREATE TABLE IF NOT EXISTS edge_sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS edge_workflow_cache (
    workflow_type TEXT PRIMARY KEY,
    yaml_content  TEXT NOT NULL,
    version       TEXT,
    updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS device_wasm_cache (
    binary_hash   TEXT PRIMARY KEY,
    binary_data   BLOB NOT NULL,
    last_accessed TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Monotonic sequence counter for SAF sync (one row per device)
CREATE TABLE IF NOT EXISTS device_sequence (
    device_id     TEXT PRIMARY KEY,
    last_sequence INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Sync advisory lock (process-safe; replaces in-memory _sync_in_progress flag)
CREATE TABLE IF NOT EXISTS sync_lock (
    lock_key      TEXT PRIMARY KEY,
    holder_id     TEXT NOT NULL,
    acquired_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class SQLitePersistenceProvider(PersistenceProvider):
    """SQLite-backed workflow persistence for development and testing"""

    def __init__(
        self,
        db_path: str = ":memory:",
        timeout: float = 5.0,
        check_same_thread: bool = False,
        auto_init: bool = True
    ):
        """
        Initialize SQLite persistence provider

        Args:
            db_path: Path to SQLite database file or ":memory:" for in-memory
            timeout: Database lock timeout in seconds
            check_same_thread: SQLite thread safety check (disable for async)
            auto_init: Auto-create schema if missing (default: True for dev convenience)
        """
        self.db_path = db_path
        self.timeout = timeout
        self.check_same_thread = check_same_thread
        self.auto_init = auto_init
        self.conn: Optional[aiosqlite.Connection] = None
        self._initialized = False

    async def initialize(self):
        """Create database connection and initialize schema if needed"""
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

            # Check if schema exists
            async with self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='workflow_executions'"
            ) as cursor:
                result = await cursor.fetchone()

            if not result:
                if self.auto_init:
                    # Auto-create schema
                    logger.info(f"Schema not found, auto-initializing database: {self.db_path}")
                    await self._create_schema()
                    logger.info("Schema created successfully")
                else:
                    # Warn user to run migrations
                    logger.warning(
                        "workflow_executions table not found. "
                        "Run 'ruvon db init' or set auto_init=True"
                    )

            self._initialized = True
            logger.info(f"SQLite workflow store initialized (db={self.db_path})")

        except Exception as e:
            logger.error(f"Failed to initialize SQLite store: {e}")
            raise

    async def _create_schema(self):
        """Create database schema by applying all migrations"""
        import sys
        from pathlib import Path

        # Add tools directory to path so we can import migrate
        # __file__ is src/ruvon/implementations/persistence/sqlite.py
        # Need 5 parents to get to project root: persistence -> implementations -> ruvon -> src -> root
        project_root = Path(__file__).parent.parent.parent.parent.parent
        tools_dir = project_root / "tools"
        if str(tools_dir) not in sys.path:
            sys.path.insert(0, str(tools_dir))

        try:
            from migrate import MigrationManager

            # Determine migrations directory
            migrations_dir = project_root / "migrations"

            # Create migration manager with existing connection
            manager = MigrationManager(
                db_type='sqlite',
                conn=self.conn,
                migrations_dir=str(migrations_dir)
            )

            # Apply all migrations (silent mode for auto-init)
            await manager.init_fresh_database(silent=True)

            # Also run embedded schema to ensure tables added after the migration
            # baseline (e.g. device_sequence, sync_lock) exist.  All statements
            # use CREATE TABLE IF NOT EXISTS so this is idempotent.
            await self.conn.executescript(SQLITE_SCHEMA)
            await self.conn.commit()

        except ImportError as e:
            logger.error(f"Failed to import MigrationManager: {e}")
            logger.warning("Falling back to embedded schema")
            # Fallback to embedded schema if migration tools not available
            await self.conn.executescript(SQLITE_SCHEMA)
            await self.conn.commit()

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
        workflow_version = workflow_dict.get('workflow_version')
        definition_snapshot = self._serialize_json(workflow_dict.get('definition_snapshot')) if workflow_dict.get('definition_snapshot') else None
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

        # If a different workflow holds the same idempotency_key, replace it explicitly
        # before the upsert so the UNIQUE constraint doesn't conflict.
        if idempotency_key:
            await self.conn.execute(
                "DELETE FROM workflow_executions WHERE idempotency_key = ? AND id != ?",
                (idempotency_key, workflow_id),
            )

        # Upsert via ON CONFLICT(id) DO UPDATE to avoid triggering ON DELETE CASCADE
        # on child tables (e.g. tasks) when the same workflow row is updated in-place.
        await self.conn.execute("""
            INSERT INTO workflow_executions (
                id, workflow_type, workflow_version, definition_snapshot, current_step, status, state, steps_config,
                state_model_path, saga_mode, completed_steps_stack,
                parent_execution_id, blocked_on_child_id, data_region, priority,
                idempotency_key, metadata, completed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                workflow_type = excluded.workflow_type,
                workflow_version = excluded.workflow_version,
                definition_snapshot = excluded.definition_snapshot,
                current_step = excluded.current_step,
                status = excluded.status,
                state = excluded.state,
                steps_config = excluded.steps_config,
                state_model_path = excluded.state_model_path,
                saga_mode = excluded.saga_mode,
                completed_steps_stack = excluded.completed_steps_stack,
                parent_execution_id = excluded.parent_execution_id,
                blocked_on_child_id = excluded.blocked_on_child_id,
                data_region = excluded.data_region,
                priority = excluded.priority,
                idempotency_key = excluded.idempotency_key,
                metadata = excluded.metadata,
                completed_at = excluded.completed_at,
                updated_at = CURRENT_TIMESTAMP
        """, (
            workflow_id, workflow_type, workflow_version, definition_snapshot, current_step, status, state, steps_config,
            state_model_path, saga_mode, completed_steps_stack,
            parent_execution_id, blocked_on_child_id, data_region, priority,
            idempotency_key, metadata, completed_at
        ))
        await self.conn.commit()

        # Write audit event
        _STATUS_TO_EVENT = {
            'RUNNING':   'STEP_EXECUTED',
            'COMPLETED': 'WORKFLOW_COMPLETED',
            'FAILED':    'WORKFLOW_FAILED',
            'PENDING':   'WORKFLOW_CREATED',
            'PAUSED':    'WORKFLOW_PAUSED',
            'CANCELLED': 'WORKFLOW_CANCELLED',
        }
        event_type = _STATUS_TO_EVENT.get(workflow_dict.get('status', ''), 'STATUS_CHANGED')
        try:
            await self.conn.execute(
                """
                INSERT INTO workflow_audit_log
                    (audit_id, workflow_id, event_type, step_name, user_id, new_state)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    workflow_id,
                    event_type,
                    str(workflow_dict.get('current_step', '')) if workflow_dict.get('current_step') is not None else None,
                    workflow_dict.get('owner_id'),
                    workflow_dict.get('status'),
                )
            )
            await self.conn.commit()
        except Exception as _audit_err:
            logger.warning(f"Audit log write failed (non-fatal): {_audit_err}")

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
                id, workflow_type, workflow_version, definition_snapshot, current_step, status, state, steps_config,
                state_model_path, saga_mode, completed_steps_stack,
                parent_execution_id, blocked_on_child_id, data_region, priority,
                created_at, updated_at, completed_at, idempotency_key, metadata
            FROM workflow_executions
            WHERE id = ?
        """, (workflow_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return WorkflowRecord(
            id=row[0],
            workflow_type=row[1],
            workflow_version=row[2],
            definition_snapshot=self._deserialize_json(row[3]) if row[3] else None,
            current_step=row[4],
            status=row[5],
            state=self._deserialize_json(row[6]),
            steps_config=self._deserialize_json(row[7]),
            state_model_path=row[8],
            saga_mode=self._int_to_bool(row[9]),
            completed_steps_stack=self._deserialize_json(row[10]),
            parent_execution_id=row[11],
            blocked_on_child_id=row[12],
            data_region=row[13],
            priority=row[14],
            created_at=self._from_iso8601(row[15]),
            updated_at=self._from_iso8601(row[16]),
            completed_at=self._from_iso8601(row[17]),
            idempotency_key=row[18],
            metadata=self._deserialize_json(row[19]),
        )

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

        return TaskRecord(
            task_id=task_id,
            execution_id=execution_id,
            step_name=step_name,
            step_index=step_index,
            status='PENDING',
        )

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

        return TaskRecord(
            task_id=row[0],
            execution_id=row[1],
            step_name=row[2],
            step_index=row[3],
            status=row[4],
            worker_id=row[5],
            claimed_at=self._from_iso8601(row[6]),
            started_at=self._from_iso8601(row[7]),
            completed_at=self._from_iso8601(row[8]),
            retry_count=row[9],
            max_retries=row[10],
            last_error=row[11],
            task_data=self._deserialize_json(row[12]),
            result=self._deserialize_json(row[13]),
            idempotency_key=row[14],
            created_at=self._from_iso8601(row[15]),
            updated_at=self._from_iso8601(row[16]),
        )

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
            metrics.append(MetricRecord(
                workflow_id=workflow_id,
                metric_name=row[0],
                metric_value=row[1],
                unit=row[2],
                step_name=row[3],
                recorded_at=self._from_iso8601(row[4]),
                tags=self._deserialize_json(row[5]),
            ))

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
    # HEARTBEAT OPERATIONS (Zombie Detection & Recovery)
    # ============================================================================

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
        async with self.conn.execute(
            """
            INSERT OR REPLACE INTO workflow_heartbeats (
                workflow_id, worker_id, last_heartbeat, current_step,
                step_started_at, metadata
            )
            VALUES (?, ?, CURRENT_TIMESTAMP, ?, CURRENT_TIMESTAMP, ?)
            """,
            (
                str(workflow_id),
                worker_id,
                current_step,
                serialize(metadata or {})
            )
        ):
            await self.conn.commit()

    async def delete_heartbeat(self, workflow_id: uuid.UUID) -> None:
        """
        Delete heartbeat record when workflow completes or step finishes.

        Args:
            workflow_id: ID of the workflow
        """
        async with self.conn.execute(
            "DELETE FROM workflow_heartbeats WHERE workflow_id = ?",
            (str(workflow_id),)
        ):
            await self.conn.commit()

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
        cursor = await self.conn.execute(
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
            JOIN workflow_executions w ON h.workflow_id = w.id
            WHERE datetime(h.last_heartbeat) < datetime('now', '-' || ? || ' seconds')
            AND w.status IN ('RUNNING', 'WAITING_EXTERNAL_INPUT', 'WAITING_CHILD_HUMAN_INPUT')
            ORDER BY h.last_heartbeat ASC
            """,
            (stale_threshold_seconds,)
        )

        rows = await cursor.fetchall()
        return [
            {
                'workflow_id': row[0],
                'worker_id': row[1],
                'last_heartbeat': row[2],
                'current_step': row[3],
                'step_started_at': row[4],
                'metadata': deserialize(row[5]) if row[5] else {},
                'workflow_type': row[6],
                'status': row[7],
                'workflow_current_step': row[8]
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
        # Update workflow status
        await self.conn.execute(
            """
            UPDATE workflow_executions
            SET status = 'FAILED_WORKER_CRASH',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (str(workflow_id),)
        )

        # Log audit event
        await self.conn.execute(
            """
            INSERT INTO workflow_audit_log (
                workflow_id, event_type, step_name, recorded_at, metadata
            )
            VALUES (?, 'WORKER_CRASH_DETECTED', NULL, CURRENT_TIMESTAMP, ?)
            """,
            (
                str(workflow_id),
                serialize({'reason': reason, 'recovery_action': 'marked_as_failed'})
            )
        )

        # Log execution event
        await self.conn.execute(
            """
            INSERT INTO workflow_execution_logs (
                workflow_id, log_level, message, logged_at, metadata
            )
            VALUES (?, 'ERROR', ?, CURRENT_TIMESTAMP, ?)
            """,
            (
                str(workflow_id),
                f"Workflow marked as FAILED_WORKER_CRASH: {reason}",
                serialize({'recovery_action': 'zombie_scanner', 'automated': True})
            )
        )

        await self.conn.commit()

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

    # ============================================================================
    # EDGE WORKFLOW SYNC METHODS
    # ============================================================================

    async def get_pending_sync_workflows(self, limit: int = 100) -> list[dict]:
        """Return up to `limit` terminal-status workflows not yet synced to cloud.

        Ordered oldest-first so backlog drains in chronological order.
        Once synced, rows are deleted by delete_synced_workflows() — so there
        is no need for a time-based watermark; a full scan is safe and correct.
        """
        terminal = ("COMPLETED", "FAILED", "CANCELLED", "FAILED_ROLLED_BACK")
        placeholders = ",".join("?" * len(terminal))
        sql = (
            f"SELECT * FROM workflow_executions WHERE status IN ({placeholders})"
            f" ORDER BY COALESCE(completed_at, updated_at) LIMIT ?"
        )
        async with self.conn.execute(sql, [*terminal, limit]) as cursor:
            rows = await cursor.fetchall()
            if not rows:
                return []
            cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def get_audit_logs_for_workflows(
        self, workflow_ids: list[str], limit_per_workflow: int = 50
    ) -> list[dict]:
        """Return up to limit_per_workflow audit log rows per workflow ID."""
        if not workflow_ids:
            return []
        results: list[dict] = []
        for wf_id in workflow_ids:
            async with self.conn.execute(
                """
                SELECT * FROM workflow_audit_log
                WHERE workflow_id = ?
                ORDER BY recorded_at ASC
                LIMIT ?
                """,
                (wf_id, limit_per_workflow),
            ) as cursor:
                rows = await cursor.fetchall()
                if rows:
                    cols = [d[0] for d in cursor.description]
                    results.extend(dict(zip(cols, row)) for row in rows)
        return results

    async def delete_synced_workflows(self, workflow_ids: list[str]) -> int:
        """Delete synced workflows + their audit rows. Returns deleted workflow count.

        Audit rows are deleted explicitly before workflows so this works on both:
        - New DBs (schema has FK ON DELETE CASCADE — explicit delete is a no-op cascade)
        - Existing DBs created before the FK was added (no cascade, explicit delete required)
        """
        if not workflow_ids:
            return 0
        placeholders = ",".join("?" * len(workflow_ids))
        # Delete audit rows first (avoids FK violation on DBs with the constraint)
        await self.conn.execute(
            f"DELETE FROM workflow_audit_log WHERE workflow_id IN ({placeholders})",
            workflow_ids,
        )
        async with self.conn.execute(
            f"DELETE FROM workflow_executions WHERE id IN ({placeholders})", workflow_ids
        ) as cursor:
            deleted = cursor.rowcount
        await self.conn.commit()
        return deleted

    async def get_edge_sync_state(self, key: str) -> str | None:
        """Read a key from edge_sync_state. Returns None if not set."""
        async with self.conn.execute(
            "SELECT value FROM edge_sync_state WHERE key=?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else None

    async def set_edge_sync_state(self, key: str, value: str) -> None:
        """Upsert a key/value pair in edge_sync_state."""
        await self.conn.execute(
            "INSERT INTO edge_sync_state(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
            (key, value),
        )
        await self.conn.commit()

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
