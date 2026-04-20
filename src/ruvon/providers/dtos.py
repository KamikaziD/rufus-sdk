"""
Domain Transfer Objects (DTOs) for Ruvon provider interfaces.

These msgspec.Struct subclasses replace Dict[str, Any] return types across all
provider interfaces, giving implementations a verifiable contract and enabling
static analysis to catch schema drift early.

All fields map 1-to-1 with the DB columns defined in:
  - PostgreSQL: src/ruvon/db_schema/database.py  (source of truth)
  - SQLite:     SQLITE_SCHEMA in sqlite.py        (edge equivalent)

Nullable DB columns are represented as Optional fields.

# API FROZEN v1.0
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import msgspec


class WorkflowRecord(msgspec.Struct):
    """Represents a row from workflow_executions."""
    id: str
    workflow_type: str
    status: str
    current_step: int
    state: Dict[str, Any]
    steps_config: List[Dict[str, Any]]
    state_model_path: str
    # Optional fields
    workflow_version: Optional[str] = None
    definition_snapshot: Optional[Dict[str, Any]] = None
    saga_mode: bool = False
    completed_steps_stack: List[Dict[str, Any]] = []
    parent_execution_id: Optional[str] = None
    blocked_on_child_id: Optional[str] = None
    data_region: Optional[str] = None
    priority: Optional[int] = None
    idempotency_key: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    owner_id: Optional[str] = None
    org_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None


class TaskRecord(msgspec.Struct):
    """Represents a row from the tasks table."""
    task_id: str
    execution_id: str
    step_name: str
    step_index: int
    status: str
    # Optional fields
    worker_id: Optional[str] = None
    claimed_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    last_error: Optional[str] = None
    task_data: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    idempotency_key: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AuditLogRecord(msgspec.Struct):
    """Represents a row from workflow_audit_log."""
    workflow_id: str
    event_type: str
    # Optional fields
    audit_id: Optional[str] = None
    execution_id: Optional[str] = None
    step_name: Optional[str] = None
    actor: Optional[str] = None          # PostgreSQL column name
    user_id: Optional[str] = None        # SQLite column name alias
    old_status: Optional[str] = None     # PostgreSQL column name
    new_status: Optional[str] = None     # PostgreSQL column name
    old_state: Optional[str] = None      # SQLite column name alias
    new_state: Optional[str] = None      # SQLite column name alias
    details: Optional[Dict[str, Any]] = None   # PostgreSQL column name
    metadata: Optional[Dict[str, Any]] = None  # SQLite column name alias
    timestamp: Optional[str] = None      # PostgreSQL column name
    recorded_at: Optional[str] = None    # SQLite column name alias
    execution_duration_ms: Optional[float] = None


class MetricRecord(msgspec.Struct):
    """Represents a row from workflow_metrics."""
    workflow_id: str
    metric_name: str
    metric_value: float
    # Optional fields
    metric_id: Optional[int] = None
    workflow_type: Optional[str] = None
    execution_id: Optional[str] = None
    step_name: Optional[str] = None
    unit: Optional[str] = None
    tags: Optional[Dict[str, Any]] = None
    recorded_at: Optional[str] = None


class SyncStateRecord(msgspec.Struct):
    """Represents a row from edge_sync_state."""
    key: str
    value: str
    updated_at: Optional[str] = None
