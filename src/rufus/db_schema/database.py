"""
SQLAlchemy Database Models for Rufus Workflow Engine.

This module is the single source of truth for all PostgreSQL tables.
Used for:
- Alembic migration generation
- Type-safe schema definition
- Database-agnostic type mapping (PostgreSQL + SQLite)

Table inventory (36 cloud tables + alembic_version managed by Alembic):

  Core workflow (7):
    workflow_executions, workflow_audit_log, workflow_execution_logs,
    workflow_metrics, workflow_heartbeats, tasks, compensation_log

  Scheduling (1):
    scheduled_workflows

  Edge device management - cloud side (3):
    edge_devices, worker_nodes, worker_commands

  Live workflow updates (2):
    workflow_definitions, server_commands

  Command infrastructure (8):
    command_broadcasts, command_batches, command_templates, device_commands,
    command_schedules, schedule_executions, command_versions, command_changelog

  Audit & compliance (2):
    command_audit_log, audit_retention_policies

  Authorization & RBAC (5):
    authorization_roles, role_assignments, authorization_policies,
    command_approvals, approval_responses

  Webhooks & rate limiting (4):
    webhook_registrations, webhook_deliveries,
    rate_limit_rules, rate_limit_tracking

  Edge config & SAF (4):
    device_configs, saf_transactions, device_assignments, policies

  WASM component registry (1):
    wasm_components

Note: Persistence providers use raw SQL for performance-critical operations.
Note: command_audit_log.searchable_text (TSVECTOR GENERATED) is added via
      op.execute() in the Alembic migration — it cannot be modelled in SA generically.
"""

from sqlalchemy import (
    MetaData, Table, Column, Index, ForeignKey,
    String, Integer, Boolean, DateTime, Text, LargeBinary, func,
    UniqueConstraint, CheckConstraint, BigInteger
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

workflow_execution_logs = Table(
    'workflow_execution_logs',
    metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('workflow_id', String(36), nullable=False, index=True),
    Column('execution_id', String(36)),
    Column('step_name', String(200)),
    Column('log_level', String(20), nullable=False),  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    Column('message', Text, nullable=False),
    Column('metadata', Text),  # JSONB in PostgreSQL
    Column('logged_at', DateTime, server_default=func.now(), nullable=False),

    Index('ix_execution_logs_workflow', 'workflow_id'),
    Index('ix_execution_logs_level', 'log_level'),
    Index('ix_execution_logs_time', 'logged_at'),
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

# Task queue — used by both postgres.py and sqlite.py (claim_next_task, create_task_record)
# Also used by SyncManager (step_name='SAF_Sync') and ConfigManager (step_name='CONFIG_CACHE')
tasks = Table(
    'tasks',
    metadata,
    Column('task_id', String(36), primary_key=True),
    Column('execution_id', String(36), ForeignKey('workflow_executions.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('step_name', String(200), nullable=False),
    Column('step_index', Integer, nullable=False),
    Column('status', String(50), nullable=False, server_default='PENDING'),
    Column('worker_id', String(100)),
    Column('claimed_at', DateTime),
    Column('started_at', DateTime),
    Column('completed_at', DateTime),
    Column('retry_count', Integer, server_default='0'),
    Column('max_retries', Integer, server_default='3'),
    Column('last_error', Text),
    Column('task_data', Text),   # JSONB in PostgreSQL
    Column('result', Text),      # JSONB in PostgreSQL
    Column('idempotency_key', String(255), unique=True),
    Column('created_at', DateTime, server_default=func.now()),
    Column('updated_at', DateTime, server_default=func.now(), onupdate=func.now()),

    Index('ix_tasks_claim', 'status', 'created_at'),
    Index('ix_tasks_execution', 'execution_id', 'step_index'),
)

# Saga compensation log — used by both postgres.py and sqlite.py (log_compensation)
compensation_log = Table(
    'compensation_log',
    metadata,
    Column('log_id', String(36), primary_key=True),
    Column('execution_id', String(36), ForeignKey('workflow_executions.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('step_name', String(200), nullable=False),
    Column('step_index', Integer, nullable=False),
    Column('action_type', String(50), nullable=False),
    Column('action_result', Text),   # JSONB in PostgreSQL
    Column('error_message', Text),
    Column('executed_at', DateTime, server_default=func.now()),
    Column('executed_by', String(100)),
    Column('state_before', Text),    # JSONB in PostgreSQL
    Column('state_after', Text),     # JSONB in PostgreSQL
)

# Scheduled workflows — referenced by postgres.py:register_scheduled_workflow
scheduled_workflows = Table(
    'scheduled_workflows',
    metadata,
    Column('id', String(36), primary_key=True, server_default=func.now()),
    Column('schedule_name', String(200), unique=True, nullable=False),
    Column('workflow_type', String(200), nullable=False),
    Column('cron_expression', String(100), nullable=False),
    Column('initial_data', Text, server_default='{}'),  # JSONB in PostgreSQL
    Column('enabled', Boolean, server_default='true'),
    Column('last_run_at', DateTime),
    Column('next_run_at', DateTime),
    Column('run_count', Integer, server_default='0'),
    Column('created_at', DateTime, server_default=func.now()),
    Column('updated_at', DateTime, server_default=func.now(), onupdate=func.now()),

    Index('ix_scheduled_workflows_enabled', 'enabled', 'next_run_at'),
)

# ============================================================================
# Edge Device Tables (cloud side — PostgreSQL only)
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

# Celery worker fleet registry — previously only in Alembic migration d08b401e4c86
worker_nodes = Table(
    'worker_nodes',
    metadata,
    Column('worker_id', String(100), primary_key=True),
    Column('hostname', String(255)),
    Column('region', String(50)),
    Column('zone', String(50)),
    Column('capabilities', Text, server_default='{}'),  # JSONB in PostgreSQL
    Column('status', String(20)),   # 'online', 'offline'
    Column('last_heartbeat', DateTime),
    Column('created_at', DateTime, server_default=func.now()),
    Column('updated_at', DateTime, server_default=func.now(), onupdate=func.now()),
    Column('sdk_version', String(50), nullable=True),
    Column('pending_command_count', Integer, server_default='0'),
    Column('last_command_at', DateTime, nullable=True),

    Index('ix_worker_status', 'status'),
    Index('ix_worker_heartbeat', 'last_heartbeat'),
    Index('ix_worker_region', 'region'),
)

# Worker command queue — DB-delivery channel for control plane → Celery worker commands
worker_commands = Table(
    'worker_commands',
    metadata,
    Column('command_id', String(100), primary_key=True),
    Column('worker_id', String(100), ForeignKey('worker_nodes.worker_id', ondelete='CASCADE'), nullable=True),
    # NULL worker_id = broadcast; target_filter JSON narrows which workers execute
    Column('target_filter', Text, nullable=True),   # JSONB: {region, zone, capabilities, ...}
    Column('command_type', String(50), nullable=False),
    # Values: restart|pool_restart|drain|update_code|update_config|
    #         pause_queue|resume_queue|set_concurrency|check_health
    Column('command_data', Text, server_default='{}'),
    Column('status', String(20), server_default='pending'),
    # Values: pending|delivered|executing|completed|failed|expired|cancelled
    Column('priority', String(20), server_default='normal'),
    # Values: low|normal|high|critical
    Column('created_at', DateTime, server_default=func.now()),
    Column('created_by', String(100), nullable=True),
    Column('delivered_at', DateTime, nullable=True),
    Column('executed_at', DateTime, nullable=True),
    Column('completed_at', DateTime, nullable=True),
    Column('expires_at', DateTime, nullable=True),
    Column('result', Text, nullable=True),        # JSONB: execution result
    Column('error_message', Text, nullable=True),
    Column('retry_count', Integer, server_default='0'),
    Column('max_retries', Integer, server_default='0'),

    Index('ix_worker_cmd_worker_status', 'worker_id', 'status'),
    Index('ix_worker_cmd_status_created', 'status', 'created_at'),
    Index('ix_worker_cmd_expires', 'expires_at'),
)

# ============================================================================
# Command Infrastructure
# ============================================================================
# Live Workflow Updates
# ============================================================================

# DB-backed workflow YAML definitions with version history and hot-reload support
workflow_definitions = Table(
    'workflow_definitions',
    metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('workflow_type', String(200), nullable=False),
    Column('version', Integer, nullable=False, server_default='1'),
    Column('yaml_content', Text, nullable=False),
    Column('is_active', Boolean, nullable=False, server_default='true'),
    Column('description', Text),
    Column('uploaded_by', String(200)),
    Column('created_at', DateTime, server_default=func.now()),

    UniqueConstraint('workflow_type', 'version', name='uq_wf_def_type_ver'),
    Index('ix_wf_def_type_active', 'workflow_type', 'is_active'),
)

# Control plane server commands (mirrors worker_commands for the server process itself)
server_commands = Table(
    'server_commands',
    metadata,
    Column('id', String(36), primary_key=True),   # UUID
    Column('command', String(100), nullable=False),
    Column('payload', Text, nullable=False, server_default='{}'),  # JSONB in PG
    Column('status', String(50), nullable=False, server_default='pending'),
    Column('result', Text),                        # JSONB in PG
    Column('created_by', String(200)),
    Column('created_at', DateTime, server_default=func.now()),
    Column('updated_at', DateTime, server_default=func.now()),

    Index('ix_srv_cmd_status', 'status', 'created_at'),
)

# ============================================================================

# Fleet-wide broadcast commands (no FK — referenced by device_commands.broadcast_id)
command_broadcasts = Table(
    'command_broadcasts',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('broadcast_id', String(100), unique=True, nullable=False),
    Column('command_type', String(100), nullable=False),
    Column('command_data', Text, server_default='{}'),
    Column('target_filter', Text, nullable=False),   # JSONB in PostgreSQL
    Column('rollout_config', Text),                  # JSONB in PostgreSQL
    Column('created_by', String(100)),
    Column('status', String(50), server_default='pending'),
    Column('total_devices', Integer, server_default='0'),
    Column('completed_devices', Integer, server_default='0'),
    Column('failed_devices', Integer, server_default='0'),
    Column('created_at', DateTime, server_default=func.now()),
    Column('started_at', DateTime),
    Column('completed_at', DateTime),
    Column('cancelled_at', DateTime),
    Column('error_message', Text),

    Index('ix_broadcast_status', 'status'),
    Index('ix_broadcast_created', 'created_at'),
)

# Atomic multi-command batches for a single device
command_batches = Table(
    'command_batches',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('batch_id', String(100), unique=True, nullable=False),
    Column('device_id', String(100), ForeignKey('edge_devices.device_id', ondelete='CASCADE'), nullable=False, index=True),
    Column('execution_mode', String(50), server_default='sequential'),
    Column('status', String(50), server_default='pending'),
    Column('total_commands', Integer, server_default='0'),
    Column('completed_commands', Integer, server_default='0'),
    Column('failed_commands', Integer, server_default='0'),
    Column('created_at', DateTime, server_default=func.now()),
    Column('started_at', DateTime),
    Column('completed_at', DateTime),
    Column('error_message', Text),

    Index('ix_batch_device', 'device_id'),
    Index('ix_batch_status', 'status'),
)

# Reusable command templates
command_templates = Table(
    'command_templates',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('template_name', String(100), unique=True, nullable=False),
    Column('description', Text),
    Column('commands', Text, nullable=False),   # JSONB in PostgreSQL
    Column('variables', Text, server_default='[]'),  # JSONB in PostgreSQL
    Column('created_by', String(100)),
    Column('version', String(50), server_default='1.0.0'),
    Column('is_active', Boolean, server_default='true'),
    Column('tags', Text, server_default='[]'),   # JSONB in PostgreSQL
    Column('created_at', DateTime, server_default=func.now()),
    Column('updated_at', DateTime, server_default=func.now(), onupdate=func.now()),

    Index('ix_template_name', 'template_name'),
    Index('ix_template_active', 'is_active'),
)

# Individual device commands — expanded to include all columns from init-db.sql + ALTERs
device_commands = Table(
    'device_commands',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('command_id', String(100), unique=True, nullable=False),
    Column('device_id', String(100), ForeignKey('edge_devices.device_id', ondelete='CASCADE'), nullable=False, index=True),
    Column('command_type', String(100), nullable=False),
    Column('command_data', Text, server_default='{}'),
    Column('status', String(50), server_default='pending'),
    Column('priority', Integer, server_default='5'),
    Column('created_at', DateTime, server_default=func.now()),
    Column('sent_at', DateTime),
    Column('delivered_at', DateTime),
    Column('executed_at', DateTime),
    Column('completed_at', DateTime),
    Column('expires_at', DateTime),
    Column('result', Text),
    Column('error_message', Text),
    # Retry management
    Column('retry_policy', Text),    # JSONB in PostgreSQL
    Column('retry_count', Integer, server_default='0'),
    Column('max_retries', Integer, server_default='0'),
    Column('next_retry_at', DateTime),
    Column('last_retry_at', DateTime),
    # Batch / broadcast linkage (added via ALTER TABLE in init-db.sql)
    Column('batch_id', String(100), ForeignKey('command_batches.batch_id', ondelete='SET NULL'), nullable=True),
    Column('batch_sequence', Integer),
    Column('broadcast_id', String(100), ForeignKey('command_broadcasts.broadcast_id', ondelete='SET NULL'), nullable=True),
    # Versioning
    Column('command_version', String(50)),

    Index('ix_command_device_status', 'device_id', 'status'),
    Index('ix_command_created', 'created_at'),
    Index('ix_command_expires', 'expires_at'),
    Index('ix_command_retry', 'next_retry_at'),
    Index('ix_command_batch', 'batch_id', 'batch_sequence'),
    Index('ix_command_broadcast', 'broadcast_id'),
    Index('ix_command_version', 'command_type', 'command_version'),
)

# Scheduled and recurring command execution
command_schedules = Table(
    'command_schedules',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('schedule_id', String(100), unique=True, nullable=False),
    Column('schedule_name', String(200)),
    Column('device_id', String(100), ForeignKey('edge_devices.device_id', ondelete='CASCADE'), nullable=True),
    Column('target_filter', Text),    # JSONB in PostgreSQL, nullable
    Column('command_type', String(100), nullable=False),
    Column('command_data', Text, server_default='{}'),
    Column('schedule_type', String(50), nullable=False),  # 'one_time' | 'recurring'
    Column('execute_at', DateTime),
    Column('cron_expression', String(100)),
    Column('timezone', String(50), server_default='UTC'),
    Column('status', String(50), server_default='active'),
    Column('next_execution_at', DateTime),
    Column('last_execution_at', DateTime),
    Column('execution_count', Integer, server_default='0'),
    Column('max_executions', Integer),   # NULL = unlimited
    Column('maintenance_window_start', Text),  # TIME — stored as TEXT for SQLite compat
    Column('maintenance_window_end', Text),    # TIME — stored as TEXT for SQLite compat
    Column('created_by', String(100)),
    Column('created_at', DateTime, server_default=func.now()),
    Column('updated_at', DateTime, server_default=func.now(), onupdate=func.now()),
    Column('expires_at', DateTime),
    Column('error_message', Text),
    Column('retry_policy', Text),    # JSONB in PostgreSQL

    Index('ix_schedule_next_execution', 'next_execution_at', 'status'),
    Index('ix_schedule_device', 'device_id'),
    Index('ix_schedule_status', 'status'),
    Index('ix_schedule_type', 'schedule_type'),
)

schedule_executions = Table(
    'schedule_executions',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('schedule_id', String(100), ForeignKey('command_schedules.schedule_id', ondelete='CASCADE'), nullable=False, index=True),
    Column('execution_number', Integer, nullable=False),
    Column('scheduled_for', DateTime, nullable=False),
    Column('executed_at', DateTime),
    Column('status', String(50), server_default='pending'),
    Column('command_id', String(100)),
    Column('broadcast_id', String(100)),
    Column('result_summary', Text),
    Column('error_message', Text),
    Column('created_at', DateTime, server_default=func.now()),

    Index('ix_schedule_execution_schedule', 'schedule_id'),
    Index('ix_schedule_execution_status', 'status'),
    Index('ix_schedule_execution_scheduled_for', 'scheduled_for'),
)

# ============================================================================
# Audit & Compliance
# ============================================================================

# Command audit log — TSVECTOR column (searchable_text) added via op.execute() in migration
# BigInteger PK maps to BIGSERIAL in PostgreSQL
command_audit_log = Table(
    'command_audit_log',
    metadata,
    Column('id', BigInteger, primary_key=True, autoincrement=True),
    Column('audit_id', String(100), unique=True, nullable=False),
    Column('event_type', String(50), nullable=False),
    Column('command_id', String(100)),
    Column('broadcast_id', String(100)),
    Column('batch_id', String(100)),
    Column('schedule_id', String(100)),
    Column('device_id', String(100)),
    Column('device_type', String(50)),
    Column('merchant_id', String(100)),
    Column('command_type', String(100)),
    Column('command_data', Text, server_default='{}'),   # JSONB in PostgreSQL
    Column('actor_type', String(50)),
    Column('actor_id', String(100)),
    Column('actor_ip', String(45)),
    Column('user_agent', Text),
    Column('status', String(50)),
    Column('result_data', Text, server_default='{}'),    # JSONB in PostgreSQL
    Column('error_message', Text),
    Column('timestamp', DateTime, server_default=func.now(), nullable=False),
    Column('duration_ms', Integer),
    Column('session_id', String(100)),
    Column('request_id', String(100)),
    Column('parent_audit_id', String(100)),
    Column('data_region', String(50)),
    Column('compliance_tags', Text, server_default='[]'),  # JSONB in PostgreSQL
    # searchable_text TSVECTOR GENERATED — added by migration, not modelable generically

    Index('ix_audit_timestamp', 'timestamp'),
    Index('ix_audit_device', 'device_id', 'timestamp'),
    Index('ix_audit_command_id', 'command_id'),
    Index('ix_audit_actor', 'actor_id', 'timestamp'),
    Index('ix_audit_event_type', 'event_type', 'timestamp'),
    Index('ix_audit_merchant', 'merchant_id', 'timestamp'),
    Index('ix_audit_status', 'status'),
    Index('ix_audit_device_event', 'device_id', 'event_type', 'timestamp'),
    Index('ix_audit_actor_event', 'actor_id', 'event_type', 'timestamp'),
)

audit_retention_policies = Table(
    'audit_retention_policies',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('policy_name', String(100), unique=True, nullable=False),
    Column('retention_days', Integer, nullable=False),
    Column('event_types', Text, server_default='[]'),   # JSONB in PostgreSQL
    Column('archive_before_delete', Boolean, server_default='true'),
    Column('archive_location', Text),
    Column('is_active', Boolean, server_default='true'),
    Column('created_at', DateTime, server_default=func.now()),
    Column('updated_at', DateTime, server_default=func.now(), onupdate=func.now()),
)

# ============================================================================
# Authorization & RBAC
# ============================================================================

authorization_roles = Table(
    'authorization_roles',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('role_name', String(100), unique=True, nullable=False),
    Column('description', Text),
    Column('permissions', Text, server_default='[]'),  # JSONB in PostgreSQL
    Column('is_system_role', Boolean, server_default='false'),
    Column('created_by', String(100)),
    Column('created_at', DateTime, server_default=func.now()),
    Column('updated_at', DateTime, server_default=func.now(), onupdate=func.now()),

    Index('ix_role_name', 'role_name'),
)

role_assignments = Table(
    'role_assignments',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('user_id', String(100), nullable=False),
    Column('role_name', String(100), ForeignKey('authorization_roles.role_name', ondelete='CASCADE'), nullable=False),
    Column('assigned_by', String(100)),
    Column('assigned_at', DateTime, server_default=func.now()),
    Column('expires_at', DateTime),

    UniqueConstraint('user_id', 'role_name', name='uq_role_assignments_user_role'),
    Index('ix_role_assignment_user', 'user_id'),
    Index('ix_role_assignment_role', 'role_name'),
)

authorization_policies = Table(
    'authorization_policies',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('policy_name', String(100), unique=True, nullable=False),
    Column('command_type', String(100)),
    Column('device_type', String(50)),
    Column('required_roles', Text, server_default='[]'),   # JSONB in PostgreSQL
    Column('requires_approval', Boolean, server_default='false'),
    Column('approvers_required', Integer, server_default='1'),
    Column('approval_timeout_seconds', Integer, server_default='3600'),
    Column('allowed_during_maintenance_only', Boolean, server_default='false'),
    Column('risk_level', String(20), server_default='low'),
    Column('is_active', Boolean, server_default='true'),
    Column('created_by', String(100)),
    Column('created_at', DateTime, server_default=func.now()),
    Column('updated_at', DateTime, server_default=func.now(), onupdate=func.now()),

    Index('ix_policy_command_type', 'command_type'),
    Index('ix_policy_active', 'is_active'),
)

command_approvals = Table(
    'command_approvals',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('approval_id', String(100), unique=True, nullable=False),
    Column('command_type', String(100), nullable=False),
    Column('command_data', Text, server_default='{}'),   # JSONB in PostgreSQL
    Column('device_id', String(100)),
    Column('target_filter', Text),   # JSONB in PostgreSQL
    Column('requested_by', String(100), nullable=False),
    Column('requested_at', DateTime, server_default=func.now()),
    Column('status', String(50), server_default='pending'),
    Column('approvers_required', Integer, nullable=False),
    Column('approvers_count', Integer, server_default='0'),
    Column('expires_at', DateTime),
    Column('completed_at', DateTime),
    Column('reason', Text),
    Column('command_id', String(100)),
    Column('risk_level', String(20)),
    Column('metadata', Text, server_default='{}'),   # JSONB in PostgreSQL

    Index('ix_approval_status', 'status'),
    Index('ix_approval_requested_by', 'requested_by'),
    Index('ix_approval_expires', 'expires_at', 'status'),
)

approval_responses = Table(
    'approval_responses',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('approval_id', String(100), ForeignKey('command_approvals.approval_id', ondelete='CASCADE'), nullable=False, index=True),
    Column('approver_id', String(100), nullable=False),
    Column('response', String(20), nullable=False),
    Column('comment', Text),
    Column('responded_at', DateTime, server_default=func.now()),

    UniqueConstraint('approval_id', 'approver_id', name='uq_approval_responses_approval_approver'),
    Index('ix_approval_response_approver', 'approver_id'),
)

# ============================================================================
# Command Versioning
# ============================================================================

command_versions = Table(
    'command_versions',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('command_type', String(100), nullable=False),
    Column('version', String(50), nullable=False),
    Column('schema_definition', Text, nullable=False),  # JSONB in PostgreSQL
    Column('changelog', Text),
    Column('is_active', Boolean, server_default='true'),
    Column('is_deprecated', Boolean, server_default='false'),
    Column('deprecated_reason', Text),
    Column('created_by', String(100)),
    Column('created_at', DateTime, server_default=func.now()),

    UniqueConstraint('command_type', 'version', name='uq_command_versions_type_version'),
    Index('ix_command_version_type', 'command_type'),
    Index('ix_command_version_active', 'is_active'),
)

command_changelog = Table(
    'command_changelog',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('command_type', String(100), nullable=False),
    Column('from_version', String(50)),
    Column('to_version', String(50), nullable=False),
    Column('change_type', String(50), nullable=False),
    Column('changes', Text, nullable=False),  # JSONB in PostgreSQL
    Column('migration_guide', Text),
    Column('created_by', String(100)),
    Column('created_at', DateTime, server_default=func.now()),

    Index('ix_changelog_command', 'command_type'),
    Index('ix_changelog_version', 'to_version'),
)

# ============================================================================
# Webhooks & Rate Limiting
# ============================================================================

webhook_registrations = Table(
    'webhook_registrations',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('webhook_id', String(100), unique=True, nullable=False),
    Column('name', String(200), nullable=False),
    Column('url', Text, nullable=False),
    Column('events', Text, nullable=False),   # JSONB in PostgreSQL
    Column('secret', String(100)),
    Column('headers', Text, server_default='{}'),   # JSONB in PostgreSQL
    Column('retry_policy', Text),                   # JSONB in PostgreSQL
    Column('is_active', Boolean, server_default='true'),
    Column('created_by', String(100)),
    Column('created_at', DateTime, server_default=func.now()),
    Column('updated_at', DateTime, server_default=func.now(), onupdate=func.now()),

    Index('ix_webhook_active', 'is_active'),
)

webhook_deliveries = Table(
    'webhook_deliveries',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('webhook_id', String(100), ForeignKey('webhook_registrations.webhook_id', ondelete='CASCADE'), nullable=False, index=True),
    Column('event_type', String(50), nullable=False),
    Column('event_data', Text, nullable=False),   # JSONB in PostgreSQL
    Column('status', String(50), server_default='pending'),
    Column('http_status', Integer),
    Column('response_body', Text),
    Column('error_message', Text),
    Column('attempt_count', Integer, server_default='0'),
    Column('delivered_at', DateTime),
    Column('created_at', DateTime, server_default=func.now()),

    Index('ix_webhook_delivery_status', 'status'),
    Index('ix_webhook_delivery_created', 'created_at'),
)

rate_limit_rules = Table(
    'rate_limit_rules',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('rule_name', String(100), unique=True, nullable=False),
    Column('resource_pattern', String(200), nullable=False),
    Column('limit_per_window', Integer, nullable=False),
    Column('window_seconds', Integer, nullable=False),
    Column('scope', String(50), nullable=False),
    Column('is_active', Boolean, server_default='true'),
    Column('created_at', DateTime, server_default=func.now()),
    Column('updated_at', DateTime, server_default=func.now(), onupdate=func.now()),

    Index('ix_rate_limit_active', 'is_active'),
)

# BigInteger PK maps to BIGSERIAL in PostgreSQL
rate_limit_tracking = Table(
    'rate_limit_tracking',
    metadata,
    Column('id', BigInteger, primary_key=True, autoincrement=True),
    Column('identifier', String(200), nullable=False),
    Column('resource', String(200), nullable=False),
    Column('request_count', Integer, server_default='1'),
    Column('window_start', DateTime, server_default=func.now()),
    Column('window_end', DateTime, nullable=False),
    Column('last_request', DateTime, server_default=func.now()),

    UniqueConstraint('identifier', 'resource', 'window_start', name='uq_rate_limit_window'),
    Index('ix_rate_limit_identifier', 'identifier', 'resource', 'window_end'),
    Index('ix_rate_limit_cleanup', 'window_end'),
)

# ============================================================================
# Edge Config & SAF (cloud-side tables)
# ============================================================================

# Cloud-side device configuration versions
device_configs = Table(
    'device_configs',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('device_id', String(200), nullable=True),  # NULL = global fleet config; set = per-device
    Column('config_id', String(36)),
    Column('config_version', String(50), nullable=False),
    Column('config_data', Text, nullable=False, server_default='{}'),
    Column('etag', String(64), nullable=False),
    Column('is_active', Boolean, server_default='false'),
    Column('created_by', String(100)),
    Column('description', Text),
    Column('created_at', DateTime, server_default=func.now()),

    Index('ix_config_active', 'is_active'),
    Index('ix_config_version', 'config_version'),
    Index('ix_config_device_id', 'device_id'),
)

# Cloud-side SAF transaction records (synced from edge devices)
# Note: device_id is NOT a FK here (device may not be registered yet on sync)
saf_transactions = Table(
    'saf_transactions',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('transaction_id', String(100), nullable=False),
    Column('idempotency_key', String(255), unique=True, nullable=False),
    Column('device_id', String(100), nullable=False, index=True),
    Column('merchant_id', String(100)),
    Column('amount_cents', BigInteger),
    Column('currency', String(3)),
    Column('card_token', String(255)),
    Column('card_last_four', String(4)),
    Column('encrypted_payload', Text),
    Column('encryption_key_id', String(100)),
    Column('status', String(50), server_default='pending'),
    Column('workflow_id', String(100), nullable=True),
    Column('relay_device_id', Text, nullable=True),
    Column('relay_source_device_id', Text, nullable=True),
    Column('hop_count', Integer, nullable=True),
    Column('relayed_at', DateTime(timezone=True), nullable=True),
    Column('synced_at', DateTime),
    Column('processed_at', DateTime),
    Column('settlement_batch_id', String(100)),
    Column('error_message', Text),
    Column('created_at', DateTime, server_default=func.now()),

    Index('ix_saf_status', 'status'),
    Index('ix_saf_idempotency', 'idempotency_key'),
)

# Policy assignments to devices (currently in-memory in policy_service.py)
device_assignments = Table(
    'device_assignments',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('device_id', String(100), nullable=False, index=True),
    Column('policy_id', String(36), nullable=False),
    Column('policy_version', String(50), nullable=False),
    Column('assigned_artifact', String(255), nullable=False),
    Column('artifact_hash', String(64)),
    Column('artifact_url', Text),
    Column('status', String(50), server_default='pending'),
    Column('current_artifact', String(255)),
    Column('current_hash', String(64)),
    Column('assigned_at', DateTime, server_default=func.now()),
    Column('downloaded_at', DateTime),
    Column('installed_at', DateTime),
    Column('failed_at', DateTime),
    Column('error_message', Text),
    Column('retry_count', Integer, server_default='0'),

    UniqueConstraint('device_id', 'policy_id', name='uq_device_assignments_device_policy'),
    Index('ix_assignment_policy', 'policy_id'),
    Index('ix_assignment_status', 'status'),
)

# Fraud rules and configuration policies
policies = Table(
    'policies',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('policy_name', String(100), unique=True, nullable=False),
    Column('description', Text),
    Column('version', String(50), server_default='1.0.0'),
    Column('status', String(50), server_default='draft'),
    Column('rules', Text, nullable=False, server_default='[]'),  # JSONB in PostgreSQL
    Column('rollout', Text, server_default='{}'),                # JSONB in PostgreSQL
    Column('created_by', String(100)),
    Column('created_at', DateTime, server_default=func.now()),
    Column('updated_at', DateTime, server_default=func.now(), onupdate=func.now()),
    Column('tags', Text, server_default='{}'),   # JSONB in PostgreSQL

    Index('ix_policy_status', 'status'),
    Index('ix_policy_name', 'policy_name'),
)

# ============================================================================
# WASM Component Registry
# ============================================================================

wasm_components = Table(
    'wasm_components',
    metadata,
    Column('id', String(36), primary_key=True),
    Column('name', String(200), nullable=False, index=True),
    Column('version_tag', String(50), nullable=False),
    Column('binary_hash', String(64), nullable=False),     # SHA-256 hex digest
    Column('blob_storage_path', Text, nullable=False),     # Local disk path to .wasm file
    Column('input_schema', Text),                          # JSON string (optional documentation)
    Column('output_schema', Text),                         # JSON string (optional documentation)
    Column('created_at', DateTime, server_default=func.now()),
    Column('updated_at', DateTime, server_default=func.now(), onupdate=func.now()),

    UniqueConstraint('binary_hash', name='uq_wasm_components_binary_hash'),
    Index('ix_wasm_components_name', 'name'),
    Index('ix_wasm_components_hash', 'binary_hash'),
)

# ============================================================================
# Schema Migrations Table (managed by Alembic)
# ============================================================================
# Note: alembic_version (version_num VARCHAR(32) PRIMARY KEY) is created
# automatically by Alembic and is not defined here.

# ============================================================================
# Helper Functions
# ============================================================================

def get_table_by_name(table_name: str) -> Table:
    """Get table object by name."""
    return metadata.tables.get(table_name)


def get_all_tables() -> dict:
    """Get all table objects keyed by name."""
    return metadata.tables


def get_core_tables() -> list:
    """
    Tables shared by both PostgreSQL and SQLite (edge deployments).
    These are created by sqlite.py's SQLITE_SCHEMA.
    """
    return [
        workflow_executions,
        workflow_audit_log,
        workflow_execution_logs,
        workflow_metrics,
        workflow_heartbeats,
        tasks,
        compensation_log,
    ]


def get_cloud_only_tables() -> list:
    """
    Tables only created in PostgreSQL cloud deployments.
    Edge SQLite databases do NOT have these.
    """
    return [
        scheduled_workflows,
        worker_nodes,
        worker_commands,
        workflow_definitions,
        server_commands,
        command_broadcasts,
        command_batches,
        command_templates,
        command_schedules,
        schedule_executions,
        command_audit_log,
        audit_retention_policies,
        authorization_roles,
        role_assignments,
        authorization_policies,
        command_approvals,
        approval_responses,
        command_versions,
        command_changelog,
        webhook_registrations,
        webhook_deliveries,
        rate_limit_rules,
        rate_limit_tracking,
        device_configs,
        saf_transactions,
        device_assignments,
        policies,
    ]


def get_edge_device_tables() -> list:
    """
    Tables for edge device management (cloud-side).
    These exist in the cloud PostgreSQL but manage edge device state.
    """
    return [
        edge_devices,
        device_commands,
    ]
