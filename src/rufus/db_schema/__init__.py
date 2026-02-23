"""
Rufus Database Schema Package.

This package contains SQLAlchemy Core table definitions for:
- Alembic migration generation
- Type-safe schema definition
- Database-agnostic type mapping (PostgreSQL + SQLite)

database.py is the single source of truth for all 33 cloud PostgreSQL tables.
edge_database.py documents the edge SQLite schema (managed via sqlite.py, not Alembic).

Note: Pydantic models are in rufus.models (separate file)
"""

from rufus.db_schema.database import (
    metadata,
    # Core workflow tables
    workflow_executions,
    workflow_audit_log,
    workflow_execution_logs,
    workflow_metrics,
    workflow_heartbeats,
    tasks,
    compensation_log,
    scheduled_workflows,
    # Edge device management (cloud side)
    edge_devices,
    worker_nodes,
    # Command infrastructure
    command_broadcasts,
    command_batches,
    command_templates,
    device_commands,
    command_schedules,
    schedule_executions,
    # Audit & compliance
    command_audit_log,
    audit_retention_policies,
    # Authorization & RBAC
    authorization_roles,
    role_assignments,
    authorization_policies,
    command_approvals,
    approval_responses,
    # Command versioning
    command_versions,
    command_changelog,
    # Webhooks & rate limiting
    webhook_registrations,
    webhook_deliveries,
    rate_limit_rules,
    rate_limit_tracking,
    # Edge config & SAF (cloud side)
    device_configs,
    saf_transactions,
    device_assignments,
    policies,
    # Helper functions
    get_table_by_name,
    get_all_tables,
    get_core_tables,
    get_cloud_only_tables,
    get_edge_device_tables,
)

__all__ = [
    'metadata',
    # Core workflow tables
    'workflow_executions',
    'workflow_audit_log',
    'workflow_execution_logs',
    'workflow_metrics',
    'workflow_heartbeats',
    'tasks',
    'compensation_log',
    'scheduled_workflows',
    # Edge device management (cloud side)
    'edge_devices',
    'worker_nodes',
    # Command infrastructure
    'command_broadcasts',
    'command_batches',
    'command_templates',
    'device_commands',
    'command_schedules',
    'schedule_executions',
    # Audit & compliance
    'command_audit_log',
    'audit_retention_policies',
    # Authorization & RBAC
    'authorization_roles',
    'role_assignments',
    'authorization_policies',
    'command_approvals',
    'approval_responses',
    # Command versioning
    'command_versions',
    'command_changelog',
    # Webhooks & rate limiting
    'webhook_registrations',
    'webhook_deliveries',
    'rate_limit_rules',
    'rate_limit_tracking',
    # Edge config & SAF (cloud side)
    'device_configs',
    'saf_transactions',
    'device_assignments',
    'policies',
    # Helper functions
    'get_table_by_name',
    'get_all_tables',
    'get_core_tables',
    'get_cloud_only_tables',
    'get_edge_device_tables',
]
