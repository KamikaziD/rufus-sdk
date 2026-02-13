"""
SQLAlchemy Database Models for Rufus Workflow Engine.

This module defines the database schema using SQLAlchemy Core (not ORM).
Models are used for:
- Alembic migration generation
- Type-safe schema definition
- Database-agnostic type mapping (PostgreSQL + SQLite)

Note: Persistence providers still use raw SQL for performance-critical operations.
"""

from sqlalchemy import (
    MetaData, Table, Column, Index, ForeignKey,
    String, Integer, Boolean, DateTime, Text, LargeBinary, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET
from datetime import datetime

# Metadata with naming convention for constraints
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s"
    }
)

# ============================================================================
# Core Workflow Tables
# ============================================================================

workflow_executions = Table(
    'workflow_executions',
    metadata,
    Column('id', String(36), primary_key=True),  # UUID as string for SQLite compat
    Column('workflow_type', String(200), nullable=False, index=True),
    Column('workflow_version', String(50)),
    Column('definition_snapshot', Text),  # JSONB in PostgreSQL, TEXT in SQLite
    Column('current_step', String(200)),
    Column('status', String(50), nullable=False, index=True),
    Column('state', Text, nullable=False),  # JSONB in PostgreSQL, TEXT in SQLite
    Column('steps_config', Text, nullable=False, server_default='[]'),
    Column('state_model_path', String(500), nullable=False),
    Column('saga_mode', Boolean, server_default='false'),
    Column('completed_steps_stack', Text, server_default='[]'),
    Column('parent_execution_id', String(36), ForeignKey('workflow_executions.id'), nullable=True),
    Column('blocked_on_child_id', String(36), nullable=True),
    Column('data_region', String(50), server_default='us-east-1'),
    Column('priority', Integer, server_default='5'),
    Column('idempotency_key', String(255), unique=True),
    Column('metadata', Text, server_default='{}'),
    Column('owner_id', String(200)),
    Column('org_id', String(200)),
    Column('encrypted_state', LargeBinary),
    Column('encryption_key_id', String(100)),
    Column('error_message', Text),
    Column('created_at', DateTime, server_default=func.now()),
    Column('updated_at', DateTime, server_default=func.now(), onupdate=func.now()),
    Column('completed_at', DateTime),

    # Composite indexes for common queries
    Index('ix_workflow_status_created', 'status', 'created_at'),
    Index('ix_workflow_type_status', 'workflow_type', 'status'),
    Index('ix_workflow_owner', 'owner_id', 'created_at'),
)

workflow_audit_log = Table(
    'workflow_audit_log',
    metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('workflow_id', String(36), ForeignKey('workflow_executions.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('timestamp', DateTime, server_default=func.now(), nullable=False),
    Column('event_type', String(50), nullable=False),
    Column('step_name', String(200)),
    Column('actor', String(200)),
    Column('old_status', String(50)),
    Column('new_status', String(50)),
    Column('details', Text),  # JSONB in PostgreSQL
    Column('execution_duration_ms', Integer),

    Index('ix_audit_workflow_timestamp', 'workflow_id', 'timestamp'),
    Index('ix_audit_event_type', 'event_type', 'timestamp'),
)

workflow_metrics = Table(
    'workflow_metrics',
    metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('workflow_id', String(36), ForeignKey('workflow_executions.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('metric_type', String(50), nullable=False),
    Column('metric_name', String(100), nullable=False),
    Column('metric_value', Integer),
    Column('tags', Text),  # JSONB in PostgreSQL
    Column('timestamp', DateTime, server_default=func.now(), nullable=False),

    Index('ix_metrics_type_timestamp', 'metric_type', 'timestamp'),
    Index('ix_metrics_workflow', 'workflow_id', 'timestamp'),
)

workflow_heartbeats = Table(
    'workflow_heartbeats',
    metadata,
    Column('workflow_id', String(36), ForeignKey('workflow_executions.id', ondelete='CASCADE'), primary_key=True),
    Column('worker_id', String(100), nullable=False),
    Column('last_heartbeat', DateTime, nullable=False, server_default=func.now()),
    Column('current_step', String(200)),
    Column('step_started_at', DateTime),
    Column('metadata', Text, server_default='{}'),

    Index('ix_heartbeat_time', 'last_heartbeat'),
)

# ============================================================================
# Edge Device Tables (PostgreSQL only - for cloud control plane)
# ============================================================================

edge_devices = Table(
    'edge_devices',
    metadata,
    Column('id', String(36), primary_key=True),  # UUID as string
    Column('device_id', String(100), unique=True, nullable=False, index=True),
    Column('device_type', String(50), nullable=False),
    Column('device_name', String(200)),
    Column('merchant_id', String(100)),
    Column('location', String(200)),
    Column('api_key_hash', String(64), nullable=False),
    Column('public_key', Text),
    Column('firmware_version', String(50)),
    Column('sdk_version', String(50)),
    Column('capabilities', Text, server_default='[]'),
    Column('status', String(50), server_default='online'),
    Column('metadata', Text, server_default='{}'),
    Column('last_heartbeat_at', DateTime),
    Column('last_sync_at', DateTime),
    Column('registered_at', DateTime, server_default=func.now()),
    Column('updated_at', DateTime, server_default=func.now(), onupdate=func.now()),

    Index('ix_device_status', 'status'),
    Index('ix_device_merchant', 'merchant_id'),
    Index('ix_device_heartbeat', 'last_heartbeat_at'),
)

device_commands = Table(
    'device_commands',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('device_id', String(100), ForeignKey('edge_devices.device_id', ondelete='CASCADE'), nullable=False, index=True),
    Column('command_type', String(100), nullable=False),
    Column('command_data', Text, nullable=False),
    Column('status', String(50), server_default='pending'),
    Column('priority', Integer, server_default='5'),
    Column('created_at', DateTime, server_default=func.now()),
    Column('delivered_at', DateTime),
    Column('executed_at', DateTime),
    Column('result', Text),
    Column('error_message', Text),

    Index('ix_command_device_status', 'device_id', 'status'),
    Index('ix_command_created', 'created_at'),
)

# ============================================================================
# Schema Migrations Table (managed by Alembic)
# ============================================================================
# Note: This table is automatically created by Alembic
# We don't define it here, but it exists:
# - alembic_version (version_num VARCHAR(32) PRIMARY KEY)

# ============================================================================
# Helper Functions
# ============================================================================

def get_table_by_name(table_name: str) -> Table:
    """Get table object by name."""
    return metadata.tables.get(table_name)

def get_all_tables() -> dict:
    """Get all table objects."""
    return metadata.tables

def get_core_tables() -> list:
    """Get core workflow tables (present in both PostgreSQL and SQLite)."""
    return [
        workflow_executions,
        workflow_audit_log,
        workflow_metrics,
        workflow_heartbeats,
    ]

def get_edge_tables() -> list:
    """Get edge-specific tables (PostgreSQL only)."""
    return [
        edge_devices,
        device_commands,
    ]
