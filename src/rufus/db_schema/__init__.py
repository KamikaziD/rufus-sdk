"""
Rufus Database Schema Package.

This package contains SQLAlchemy Core table definitions for:
- Alembic migration generation
- Type-safe schema definition
- Database-agnostic type mapping (PostgreSQL + SQLite)

Note: Pydantic models are in rufus.models (separate file)
"""

from rufus.db_schema.database import (
    metadata,
    workflow_executions,
    workflow_audit_log,
    workflow_metrics,
    workflow_heartbeats,
    edge_devices,
    device_commands,
    get_table_by_name,
    get_all_tables,
    get_core_tables,
    get_edge_tables,
)

__all__ = [
    'metadata',
    'workflow_executions',
    'workflow_audit_log',
    'workflow_metrics',
    'workflow_heartbeats',
    'edge_devices',
    'device_commands',
    'get_table_by_name',
    'get_all_tables',
    'get_core_tables',
    'get_edge_tables',
]
