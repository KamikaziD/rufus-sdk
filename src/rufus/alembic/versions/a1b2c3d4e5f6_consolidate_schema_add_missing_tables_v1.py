"""consolidate schema: add all missing tables and fix device_commands columns

Revision ID: a1b2c3d4e5f6
Revises: 441ed90ac861
Create Date: 2026-02-23 00:00:00.000000

This migration makes database.py the single source of truth for all PostgreSQL tables.

Changes:
- Add tasks table (was only in init-db.sql, used by both persistence providers)
- Add compensation_log table (was only in init-db.sql, used by log_compensation)
- Add scheduled_workflows table (referenced in postgres.py but defined nowhere)
- Expand device_commands with 13 missing columns (command_id, sent_at, completed_at,
  expires_at, retry_policy, retry_count, max_retries, next_retry_at, last_retry_at,
  batch_id, batch_sequence, broadcast_id, command_version)
- Add 24 cloud-only tables: command_broadcasts, command_batches, command_templates,
  command_schedules, schedule_executions, command_audit_log, audit_retention_policies,
  authorization_roles, role_assignments, authorization_policies, command_approvals,
  approval_responses, command_versions, command_changelog, webhook_registrations,
  webhook_deliveries, rate_limit_rules, rate_limit_tracking, device_configs,
  saf_transactions, device_assignments, policies
- Add TSVECTOR generated column to command_audit_log (PostgreSQL only)
- Migrate seed data from init-db.sql into this migration

Note: worker_nodes was already added in migration d08b401e4c86 and is not re-created here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '441ed90ac861'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================================
    # 1. tasks — used by both postgres.py and sqlite.py
    # =========================================================================
    op.create_table(
        'tasks',
        sa.Column('task_id', sa.String(length=36), nullable=False),
        sa.Column('execution_id', sa.String(length=36), nullable=False),
        sa.Column('step_name', sa.String(length=200), nullable=False),
        sa.Column('step_index', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='PENDING'),
        sa.Column('worker_id', sa.String(length=100), nullable=True),
        sa.Column('claimed_at', sa.DateTime(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('retry_count', sa.Integer(), server_default='0'),
        sa.Column('max_retries', sa.Integer(), server_default='3'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('task_data', sa.Text(), nullable=True),
        sa.Column('result', sa.Text(), nullable=True),
        sa.Column('idempotency_key', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(
            ['execution_id'], ['workflow_executions.id'],
            name='fk_tasks_execution_id_workflow_executions', ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('task_id', name='pk_tasks'),
        sa.UniqueConstraint('idempotency_key', name='uq_tasks_idempotency_key'),
    )
    op.create_index('ix_tasks_claim', 'tasks', ['status', 'created_at'])
    op.create_index('ix_tasks_execution', 'tasks', ['execution_id', 'step_index'])
    op.create_index('ix_tasks_execution_id', 'tasks', ['execution_id'])

    # =========================================================================
    # 2. compensation_log — used by log_compensation in both providers
    # =========================================================================
    op.create_table(
        'compensation_log',
        sa.Column('log_id', sa.String(length=36), nullable=False),
        sa.Column('execution_id', sa.String(length=36), nullable=False),
        sa.Column('step_name', sa.String(length=200), nullable=False),
        sa.Column('step_index', sa.Integer(), nullable=False),
        sa.Column('action_type', sa.String(length=50), nullable=False),
        sa.Column('action_result', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('executed_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('executed_by', sa.String(length=100), nullable=True),
        sa.Column('state_before', sa.Text(), nullable=True),
        sa.Column('state_after', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ['execution_id'], ['workflow_executions.id'],
            name='fk_compensation_log_execution_id_workflow_executions', ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('log_id', name='pk_compensation_log'),
    )
    op.create_index('ix_compensation_log_execution_id', 'compensation_log', ['execution_id'])

    # =========================================================================
    # 3. scheduled_workflows — referenced in postgres.py:register_scheduled_workflow
    # =========================================================================
    op.create_table(
        'scheduled_workflows',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('schedule_name', sa.String(length=200), nullable=False),
        sa.Column('workflow_type', sa.String(length=200), nullable=False),
        sa.Column('cron_expression', sa.String(length=100), nullable=False),
        sa.Column('initial_data', sa.Text(), server_default='{}'),
        sa.Column('enabled', sa.Boolean(), server_default='true'),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('next_run_at', sa.DateTime(), nullable=True),
        sa.Column('run_count', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id', name='pk_scheduled_workflows'),
        sa.UniqueConstraint('schedule_name', name='uq_scheduled_workflows_schedule_name'),
    )
    op.create_index('ix_scheduled_workflows_enabled', 'scheduled_workflows', ['enabled', 'next_run_at'])

    # =========================================================================
    # 4. command_broadcasts — no FK, must come before device_commands
    # =========================================================================
    op.create_table(
        'command_broadcasts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('broadcast_id', sa.String(length=100), nullable=False),
        sa.Column('command_type', sa.String(length=100), nullable=False),
        sa.Column('command_data', sa.Text(), server_default='{}'),
        sa.Column('target_filter', sa.Text(), nullable=False),
        sa.Column('rollout_config', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=50), server_default='pending'),
        sa.Column('total_devices', sa.Integer(), server_default='0'),
        sa.Column('completed_devices', sa.Integer(), server_default='0'),
        sa.Column('failed_devices', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id', name='pk_command_broadcasts'),
        sa.UniqueConstraint('broadcast_id', name='uq_command_broadcasts_broadcast_id'),
    )
    op.create_index('ix_broadcast_status', 'command_broadcasts', ['status'])
    op.create_index('ix_broadcast_created', 'command_broadcasts', ['created_at'])

    # =========================================================================
    # 5. command_batches — FK → edge_devices, must come before device_commands
    # =========================================================================
    op.create_table(
        'command_batches',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('batch_id', sa.String(length=100), nullable=False),
        sa.Column('device_id', sa.String(length=100), nullable=False),
        sa.Column('execution_mode', sa.String(length=50), server_default='sequential'),
        sa.Column('status', sa.String(length=50), server_default='pending'),
        sa.Column('total_commands', sa.Integer(), server_default='0'),
        sa.Column('completed_commands', sa.Integer(), server_default='0'),
        sa.Column('failed_commands', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ['device_id'], ['edge_devices.device_id'],
            name='fk_command_batches_device_id_edge_devices', ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id', name='pk_command_batches'),
        sa.UniqueConstraint('batch_id', name='uq_command_batches_batch_id'),
    )
    op.create_index('ix_batch_device', 'command_batches', ['device_id'])
    op.create_index('ix_batch_status', 'command_batches', ['status'])

    # =========================================================================
    # 6. command_templates — no FK
    # =========================================================================
    op.create_table(
        'command_templates',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('template_name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('commands', sa.Text(), nullable=False),
        sa.Column('variables', sa.Text(), server_default='[]'),
        sa.Column('created_by', sa.String(length=100), nullable=True),
        sa.Column('version', sa.String(length=50), server_default='1.0.0'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('tags', sa.Text(), server_default='[]'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id', name='pk_command_templates'),
        sa.UniqueConstraint('template_name', name='uq_command_templates_template_name'),
    )
    op.create_index('ix_template_name', 'command_templates', ['template_name'])
    op.create_index('ix_template_active', 'command_templates', ['is_active'])

    # =========================================================================
    # 7. Expand device_commands with 13 missing columns
    #    Existing columns: id, device_id, command_type, command_data, status,
    #                      priority, created_at, delivered_at, executed_at,
    #                      result, error_message
    #    Adding: command_id, sent_at, completed_at, expires_at, retry_policy,
    #            retry_count, max_retries, next_retry_at, last_retry_at,
    #            batch_id, batch_sequence, broadcast_id, command_version
    # =========================================================================
    op.add_column('device_commands', sa.Column('command_id', sa.String(length=100), nullable=True))
    op.add_column('device_commands', sa.Column('sent_at', sa.DateTime(), nullable=True))
    op.add_column('device_commands', sa.Column('completed_at', sa.DateTime(), nullable=True))
    op.add_column('device_commands', sa.Column('expires_at', sa.DateTime(), nullable=True))
    op.add_column('device_commands', sa.Column('retry_policy', sa.Text(), nullable=True))
    op.add_column('device_commands', sa.Column('retry_count', sa.Integer(), server_default='0'))
    op.add_column('device_commands', sa.Column('max_retries', sa.Integer(), server_default='0'))
    op.add_column('device_commands', sa.Column('next_retry_at', sa.DateTime(), nullable=True))
    op.add_column('device_commands', sa.Column('last_retry_at', sa.DateTime(), nullable=True))
    op.add_column('device_commands', sa.Column('batch_id', sa.String(length=100), nullable=True))
    op.add_column('device_commands', sa.Column('batch_sequence', sa.Integer(), nullable=True))
    op.add_column('device_commands', sa.Column('broadcast_id', sa.String(length=100), nullable=True))
    op.add_column('device_commands', sa.Column('command_version', sa.String(length=50), nullable=True))

    # Add unique constraint on command_id (populated for new rows; NULLs excluded)
    op.create_index('ix_device_command_command_id', 'device_commands', ['command_id'], unique=True)
    op.create_index('ix_command_expires', 'device_commands', ['expires_at'])
    op.create_index('ix_command_retry', 'device_commands', ['next_retry_at'])
    op.create_index('ix_command_batch', 'device_commands', ['batch_id', 'batch_sequence'])
    op.create_index('ix_command_broadcast', 'device_commands', ['broadcast_id'])
    op.create_index('ix_command_version', 'device_commands', ['command_type', 'command_version'])

    # FK constraints for batch_id and broadcast_id (PostgreSQL only — additive)
    op.create_foreign_key(
        'fk_device_commands_batch_id_command_batches',
        'device_commands', 'command_batches',
        ['batch_id'], ['batch_id'], ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_device_commands_broadcast_id_command_broadcasts',
        'device_commands', 'command_broadcasts',
        ['broadcast_id'], ['broadcast_id'], ondelete='SET NULL'
    )

    # =========================================================================
    # 8. command_schedules — FK → edge_devices (nullable)
    # =========================================================================
    op.create_table(
        'command_schedules',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('schedule_id', sa.String(length=100), nullable=False),
        sa.Column('schedule_name', sa.String(length=200), nullable=True),
        sa.Column('device_id', sa.String(length=100), nullable=True),
        sa.Column('target_filter', sa.Text(), nullable=True),
        sa.Column('command_type', sa.String(length=100), nullable=False),
        sa.Column('command_data', sa.Text(), server_default='{}'),
        sa.Column('schedule_type', sa.String(length=50), nullable=False),
        sa.Column('execute_at', sa.DateTime(), nullable=True),
        sa.Column('cron_expression', sa.String(length=100), nullable=True),
        sa.Column('timezone', sa.String(length=50), server_default='UTC'),
        sa.Column('status', sa.String(length=50), server_default='active'),
        sa.Column('next_execution_at', sa.DateTime(), nullable=True),
        sa.Column('last_execution_at', sa.DateTime(), nullable=True),
        sa.Column('execution_count', sa.Integer(), server_default='0'),
        sa.Column('max_executions', sa.Integer(), nullable=True),
        sa.Column('maintenance_window_start', sa.Text(), nullable=True),
        sa.Column('maintenance_window_end', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_policy', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ['device_id'], ['edge_devices.device_id'],
            name='fk_command_schedules_device_id_edge_devices', ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id', name='pk_command_schedules'),
        sa.UniqueConstraint('schedule_id', name='uq_command_schedules_schedule_id'),
    )
    op.create_index('ix_schedule_next_execution', 'command_schedules', ['next_execution_at', 'status'])
    op.create_index('ix_schedule_device', 'command_schedules', ['device_id'])
    op.create_index('ix_schedule_status', 'command_schedules', ['status'])
    op.create_index('ix_schedule_type', 'command_schedules', ['schedule_type'])

    # =========================================================================
    # 9. schedule_executions — FK → command_schedules
    # =========================================================================
    op.create_table(
        'schedule_executions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('schedule_id', sa.String(length=100), nullable=False),
        sa.Column('execution_number', sa.Integer(), nullable=False),
        sa.Column('scheduled_for', sa.DateTime(), nullable=False),
        sa.Column('executed_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=50), server_default='pending'),
        sa.Column('command_id', sa.String(length=100), nullable=True),
        sa.Column('broadcast_id', sa.String(length=100), nullable=True),
        sa.Column('result_summary', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(
            ['schedule_id'], ['command_schedules.schedule_id'],
            name='fk_schedule_executions_schedule_id_command_schedules', ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id', name='pk_schedule_executions'),
    )
    op.create_index('ix_schedule_execution_schedule', 'schedule_executions', ['schedule_id'])
    op.create_index('ix_schedule_execution_status', 'schedule_executions', ['status'])
    op.create_index('ix_schedule_execution_scheduled_for', 'schedule_executions', ['scheduled_for'])

    # =========================================================================
    # 10. command_audit_log — TSVECTOR column added via raw SQL below
    # =========================================================================
    op.create_table(
        'command_audit_log',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('audit_id', sa.String(length=100), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('command_id', sa.String(length=100), nullable=True),
        sa.Column('broadcast_id', sa.String(length=100), nullable=True),
        sa.Column('batch_id', sa.String(length=100), nullable=True),
        sa.Column('schedule_id', sa.String(length=100), nullable=True),
        sa.Column('device_id', sa.String(length=100), nullable=True),
        sa.Column('device_type', sa.String(length=50), nullable=True),
        sa.Column('merchant_id', sa.String(length=100), nullable=True),
        sa.Column('command_type', sa.String(length=100), nullable=True),
        sa.Column('command_data', sa.Text(), server_default='{}'),
        sa.Column('actor_type', sa.String(length=50), nullable=True),
        sa.Column('actor_id', sa.String(length=100), nullable=True),
        sa.Column('actor_ip', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('result_data', sa.Text(), server_default='{}'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('session_id', sa.String(length=100), nullable=True),
        sa.Column('request_id', sa.String(length=100), nullable=True),
        sa.Column('parent_audit_id', sa.String(length=100), nullable=True),
        sa.Column('data_region', sa.String(length=50), nullable=True),
        sa.Column('compliance_tags', sa.Text(), server_default='[]'),
        sa.PrimaryKeyConstraint('id', name='pk_command_audit_log'),
        sa.UniqueConstraint('audit_id', name='uq_command_audit_log_audit_id'),
    )
    op.create_index('ix_audit_timestamp', 'command_audit_log', ['timestamp'])
    op.create_index('ix_audit_device', 'command_audit_log', ['device_id', 'timestamp'])
    op.create_index('ix_audit_command_id', 'command_audit_log', ['command_id'])
    op.create_index('ix_audit_actor', 'command_audit_log', ['actor_id', 'timestamp'])
    op.create_index('ix_cmd_audit_event_type', 'command_audit_log', ['event_type', 'timestamp'])
    op.create_index('ix_audit_merchant', 'command_audit_log', ['merchant_id', 'timestamp'])
    op.create_index('ix_audit_status', 'command_audit_log', ['status'])
    op.create_index('ix_audit_device_event', 'command_audit_log', ['device_id', 'event_type', 'timestamp'])
    op.create_index('ix_audit_actor_event', 'command_audit_log', ['actor_id', 'event_type', 'timestamp'])

    # Add PostgreSQL TSVECTOR generated column for full-text search (raw SQL — not portable)
    op.execute("""
        DO $$ BEGIN
            IF current_setting('server_version_num')::int >= 120000 THEN
                ALTER TABLE command_audit_log
                ADD COLUMN IF NOT EXISTS searchable_text TSVECTOR
                GENERATED ALWAYS AS (
                    to_tsvector('english',
                        COALESCE(event_type, '') || ' ' ||
                        COALESCE(command_type, '') || ' ' ||
                        COALESCE(device_id, '') || ' ' ||
                        COALESCE(actor_id, '')
                    )
                ) STORED;
            END IF;
        END $$;
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_search ON command_audit_log USING GIN(searchable_text)"
    )

    # =========================================================================
    # 11. audit_retention_policies — no FK
    # =========================================================================
    op.create_table(
        'audit_retention_policies',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('policy_name', sa.String(length=100), nullable=False),
        sa.Column('retention_days', sa.Integer(), nullable=False),
        sa.Column('event_types', sa.Text(), server_default='[]'),
        sa.Column('archive_before_delete', sa.Boolean(), server_default='true'),
        sa.Column('archive_location', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id', name='pk_audit_retention_policies'),
        sa.UniqueConstraint('policy_name', name='uq_audit_retention_policies_policy_name'),
    )

    # =========================================================================
    # 12. authorization_roles — no FK
    # =========================================================================
    op.create_table(
        'authorization_roles',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('role_name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('permissions', sa.Text(), server_default='[]'),
        sa.Column('is_system_role', sa.Boolean(), server_default='false'),
        sa.Column('created_by', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id', name='pk_authorization_roles'),
        sa.UniqueConstraint('role_name', name='uq_authorization_roles_role_name'),
    )
    op.create_index('ix_role_name', 'authorization_roles', ['role_name'])

    # =========================================================================
    # 13. role_assignments — FK → authorization_roles
    # =========================================================================
    op.create_table(
        'role_assignments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=100), nullable=False),
        sa.Column('role_name', sa.String(length=100), nullable=False),
        sa.Column('assigned_by', sa.String(length=100), nullable=True),
        sa.Column('assigned_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ['role_name'], ['authorization_roles.role_name'],
            name='fk_role_assignments_role_name_authorization_roles', ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id', name='pk_role_assignments'),
        sa.UniqueConstraint('user_id', 'role_name', name='uq_role_assignments_user_role'),
    )
    op.create_index('ix_role_assignment_user', 'role_assignments', ['user_id'])
    op.create_index('ix_role_assignment_role', 'role_assignments', ['role_name'])

    # =========================================================================
    # 14. authorization_policies — no FK
    # =========================================================================
    op.create_table(
        'authorization_policies',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('policy_name', sa.String(length=100), nullable=False),
        sa.Column('command_type', sa.String(length=100), nullable=True),
        sa.Column('device_type', sa.String(length=50), nullable=True),
        sa.Column('required_roles', sa.Text(), server_default='[]'),
        sa.Column('requires_approval', sa.Boolean(), server_default='false'),
        sa.Column('approvers_required', sa.Integer(), server_default='1'),
        sa.Column('approval_timeout_seconds', sa.Integer(), server_default='3600'),
        sa.Column('allowed_during_maintenance_only', sa.Boolean(), server_default='false'),
        sa.Column('risk_level', sa.String(length=20), server_default='low'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_by', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id', name='pk_authorization_policies'),
        sa.UniqueConstraint('policy_name', name='uq_authorization_policies_policy_name'),
    )
    op.create_index('ix_policy_command_type', 'authorization_policies', ['command_type'])
    op.create_index('ix_policy_active', 'authorization_policies', ['is_active'])

    # =========================================================================
    # 15. command_approvals — no FK
    # =========================================================================
    op.create_table(
        'command_approvals',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('approval_id', sa.String(length=100), nullable=False),
        sa.Column('command_type', sa.String(length=100), nullable=False),
        sa.Column('command_data', sa.Text(), server_default='{}'),
        sa.Column('device_id', sa.String(length=100), nullable=True),
        sa.Column('target_filter', sa.Text(), nullable=True),
        sa.Column('requested_by', sa.String(length=100), nullable=False),
        sa.Column('requested_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('status', sa.String(length=50), server_default='pending'),
        sa.Column('approvers_required', sa.Integer(), nullable=False),
        sa.Column('approvers_count', sa.Integer(), server_default='0'),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('command_id', sa.String(length=100), nullable=True),
        sa.Column('risk_level', sa.String(length=20), nullable=True),
        sa.Column('metadata', sa.Text(), server_default='{}'),
        sa.PrimaryKeyConstraint('id', name='pk_command_approvals'),
        sa.UniqueConstraint('approval_id', name='uq_command_approvals_approval_id'),
    )
    op.create_index('ix_approval_status', 'command_approvals', ['status'])
    op.create_index('ix_approval_requested_by', 'command_approvals', ['requested_by'])
    op.create_index('ix_approval_expires', 'command_approvals', ['expires_at', 'status'])

    # =========================================================================
    # 16. approval_responses — FK → command_approvals
    # =========================================================================
    op.create_table(
        'approval_responses',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('approval_id', sa.String(length=100), nullable=False),
        sa.Column('approver_id', sa.String(length=100), nullable=False),
        sa.Column('response', sa.String(length=20), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('responded_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(
            ['approval_id'], ['command_approvals.approval_id'],
            name='fk_approval_responses_approval_id_command_approvals', ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id', name='pk_approval_responses'),
        sa.UniqueConstraint('approval_id', 'approver_id', name='uq_approval_responses_approval_approver'),
    )
    op.create_index('ix_approval_response_approval', 'approval_responses', ['approval_id'])
    op.create_index('ix_approval_response_approver', 'approval_responses', ['approver_id'])

    # =========================================================================
    # 17. command_versions — no FK
    # =========================================================================
    op.create_table(
        'command_versions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('command_type', sa.String(length=100), nullable=False),
        sa.Column('version', sa.String(length=50), nullable=False),
        sa.Column('schema_definition', sa.Text(), nullable=False),
        sa.Column('changelog', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('is_deprecated', sa.Boolean(), server_default='false'),
        sa.Column('deprecated_reason', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id', name='pk_command_versions'),
        sa.UniqueConstraint('command_type', 'version', name='uq_command_versions_type_version'),
    )
    op.create_index('ix_command_version_type', 'command_versions', ['command_type'])
    op.create_index('ix_command_version_active', 'command_versions', ['is_active'])

    # =========================================================================
    # 18. command_changelog — no FK
    # =========================================================================
    op.create_table(
        'command_changelog',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('command_type', sa.String(length=100), nullable=False),
        sa.Column('from_version', sa.String(length=50), nullable=True),
        sa.Column('to_version', sa.String(length=50), nullable=False),
        sa.Column('change_type', sa.String(length=50), nullable=False),
        sa.Column('changes', sa.Text(), nullable=False),
        sa.Column('migration_guide', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id', name='pk_command_changelog'),
    )
    op.create_index('ix_changelog_command', 'command_changelog', ['command_type'])
    op.create_index('ix_changelog_version', 'command_changelog', ['to_version'])

    # =========================================================================
    # 19. webhook_registrations — no FK
    # =========================================================================
    op.create_table(
        'webhook_registrations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('webhook_id', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('events', sa.Text(), nullable=False),
        sa.Column('secret', sa.String(length=100), nullable=True),
        sa.Column('headers', sa.Text(), server_default='{}'),
        sa.Column('retry_policy', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_by', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id', name='pk_webhook_registrations'),
        sa.UniqueConstraint('webhook_id', name='uq_webhook_registrations_webhook_id'),
    )
    op.create_index('ix_webhook_active', 'webhook_registrations', ['is_active'])

    # =========================================================================
    # 20. webhook_deliveries — FK → webhook_registrations
    # =========================================================================
    op.create_table(
        'webhook_deliveries',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('webhook_id', sa.String(length=100), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('event_data', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=50), server_default='pending'),
        sa.Column('http_status', sa.Integer(), nullable=True),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('attempt_count', sa.Integer(), server_default='0'),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(
            ['webhook_id'], ['webhook_registrations.webhook_id'],
            name='fk_webhook_deliveries_webhook_id_webhook_registrations', ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id', name='pk_webhook_deliveries'),
    )
    op.create_index('ix_webhook_delivery_webhook', 'webhook_deliveries', ['webhook_id'])
    op.create_index('ix_webhook_delivery_status', 'webhook_deliveries', ['status'])
    op.create_index('ix_webhook_delivery_created', 'webhook_deliveries', ['created_at'])

    # =========================================================================
    # 21. rate_limit_rules — no FK
    # =========================================================================
    op.create_table(
        'rate_limit_rules',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('rule_name', sa.String(length=100), nullable=False),
        sa.Column('resource_pattern', sa.String(length=200), nullable=False),
        sa.Column('limit_per_window', sa.Integer(), nullable=False),
        sa.Column('window_seconds', sa.Integer(), nullable=False),
        sa.Column('scope', sa.String(length=50), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id', name='pk_rate_limit_rules'),
        sa.UniqueConstraint('rule_name', name='uq_rate_limit_rules_rule_name'),
    )
    op.create_index('ix_rate_limit_active', 'rate_limit_rules', ['is_active'])

    # =========================================================================
    # 22. rate_limit_tracking — no FK
    # =========================================================================
    op.create_table(
        'rate_limit_tracking',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('identifier', sa.String(length=200), nullable=False),
        sa.Column('resource', sa.String(length=200), nullable=False),
        sa.Column('request_count', sa.Integer(), server_default='1'),
        sa.Column('window_start', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('window_end', sa.DateTime(), nullable=False),
        sa.Column('last_request', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id', name='pk_rate_limit_tracking'),
    )
    op.create_index('ix_rate_limit_identifier', 'rate_limit_tracking', ['identifier', 'resource', 'window_end'])
    op.create_index('ix_rate_limit_cleanup', 'rate_limit_tracking', ['window_end'])

    # =========================================================================
    # 23. device_configs — no FK
    # =========================================================================
    op.create_table(
        'device_configs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('config_id', sa.String(length=36), nullable=True),
        sa.Column('config_version', sa.String(length=50), nullable=False),
        sa.Column('config_data', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('etag', sa.String(length=64), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='false'),
        sa.Column('created_by', sa.String(length=100), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id', name='pk_device_configs'),
    )
    op.create_index('ix_config_active', 'device_configs', ['is_active'])
    op.create_index('ix_config_version', 'device_configs', ['config_version'])

    # =========================================================================
    # 24. saf_transactions — no FK on device_id (device may sync before registering)
    # =========================================================================
    op.create_table(
        'saf_transactions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('transaction_id', sa.String(length=100), nullable=False),
        sa.Column('idempotency_key', sa.String(length=255), nullable=False),
        sa.Column('device_id', sa.String(length=100), nullable=False),
        sa.Column('merchant_id', sa.String(length=100), nullable=True),
        sa.Column('amount_cents', sa.BigInteger(), nullable=True),
        sa.Column('currency', sa.String(length=3), nullable=True),
        sa.Column('card_token', sa.String(length=255), nullable=True),
        sa.Column('card_last_four', sa.String(length=4), nullable=True),
        sa.Column('encrypted_payload', sa.Text(), nullable=True),
        sa.Column('encryption_key_id', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=50), server_default='pending'),
        sa.Column('synced_at', sa.DateTime(), nullable=True),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('settlement_batch_id', sa.String(length=100), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id', name='pk_saf_transactions'),
        sa.UniqueConstraint('idempotency_key', name='uq_saf_transactions_idempotency_key'),
    )
    op.create_index('ix_saf_device', 'saf_transactions', ['device_id'])
    op.create_index('ix_saf_status', 'saf_transactions', ['status'])
    op.create_index('ix_saf_idempotency', 'saf_transactions', ['idempotency_key'])

    # =========================================================================
    # 25. device_assignments — no FK (policy_id is a UUID string, no FK table)
    # =========================================================================
    op.create_table(
        'device_assignments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('device_id', sa.String(length=100), nullable=False),
        sa.Column('policy_id', sa.String(length=36), nullable=False),
        sa.Column('policy_version', sa.String(length=50), nullable=False),
        sa.Column('assigned_artifact', sa.String(length=255), nullable=False),
        sa.Column('artifact_hash', sa.String(length=64), nullable=True),
        sa.Column('artifact_url', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), server_default='pending'),
        sa.Column('current_artifact', sa.String(length=255), nullable=True),
        sa.Column('current_hash', sa.String(length=64), nullable=True),
        sa.Column('assigned_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('downloaded_at', sa.DateTime(), nullable=True),
        sa.Column('installed_at', sa.DateTime(), nullable=True),
        sa.Column('failed_at', sa.DateTime(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), server_default='0'),
        sa.PrimaryKeyConstraint('id', name='pk_device_assignments'),
        sa.UniqueConstraint('device_id', 'policy_id', name='uq_device_assignments_device_policy'),
    )
    op.create_index('ix_assignment_device', 'device_assignments', ['device_id'])
    op.create_index('ix_assignment_policy', 'device_assignments', ['policy_id'])
    op.create_index('ix_assignment_status', 'device_assignments', ['status'])

    # =========================================================================
    # 26. policies — no FK
    # =========================================================================
    op.create_table(
        'policies',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('policy_name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('version', sa.String(length=50), server_default='1.0.0'),
        sa.Column('status', sa.String(length=50), server_default='draft'),
        sa.Column('rules', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('rollout', sa.Text(), server_default='{}'),
        sa.Column('created_by', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('tags', sa.Text(), server_default='{}'),
        sa.PrimaryKeyConstraint('id', name='pk_policies'),
        sa.UniqueConstraint('policy_name', name='uq_policies_policy_name'),
    )
    op.create_index('ix_policy_status', 'policies', ['status'])
    op.create_index('ix_policy_name', 'policies', ['policy_name'])

    # =========================================================================
    # Seed data (migrated from init-db.sql)
    # =========================================================================
    import uuid

    # Default audit retention policy (PCI DSS: 7 years = 2555 days)
    op.execute(f"""
        INSERT INTO audit_retention_policies (id, policy_name, retention_days, event_types, archive_before_delete, is_active)
        VALUES ('{uuid.uuid4()}', 'pci_compliance_default', 2555, '[]', true, true)
        ON CONFLICT (policy_name) DO NOTHING
    """)

    # Default RBAC roles
    op.execute(f"""
        INSERT INTO authorization_roles (id, role_name, description, permissions, is_system_role) VALUES
            ('{uuid.uuid4()}', 'admin', 'Full system access', '["*"]', true),
            ('{uuid.uuid4()}', 'operator', 'Standard operations', '["command:create","command:view","device:view","broadcast:create"]', true),
            ('{uuid.uuid4()}', 'viewer', 'Read-only access', '["command:view","device:view","audit:view"]', true),
            ('{uuid.uuid4()}', 'approver', 'Can approve commands', '["approval:approve","approval:reject","approval:view"]', true)
        ON CONFLICT (role_name) DO NOTHING
    """)

    # Default authorization policies
    op.execute(f"""
        INSERT INTO authorization_policies (id, policy_name, command_type, required_roles, requires_approval, approvers_required, risk_level) VALUES
            ('{uuid.uuid4()}', 'firmware_update_policy', 'update_firmware', '["admin"]', true, 2, 'critical'),
            ('{uuid.uuid4()}', 'device_delete_policy', 'delete_device', '["admin"]', true, 1, 'high'),
            ('{uuid.uuid4()}', 'config_update_policy', 'update_config', '["admin","operator"]', false, 0, 'medium'),
            ('{uuid.uuid4()}', 'restart_policy', 'restart', '["admin","operator"]', false, 0, 'low')
        ON CONFLICT (policy_name) DO NOTHING
    """)

    # Default rate limit rules
    op.execute(f"""
        INSERT INTO rate_limit_rules (id, rule_name, resource_pattern, limit_per_window, window_seconds, scope) VALUES
            ('{uuid.uuid4()}', 'global_api_limit', '/api/v1/*', 1000, 60, 'ip'),
            ('{uuid.uuid4()}', 'command_creation_limit', '/api/v1/commands', 100, 60, 'user'),
            ('{uuid.uuid4()}', 'approval_limit', '/api/v1/approvals', 50, 60, 'user')
        ON CONFLICT (rule_name) DO NOTHING
    """)

    # Default device config v1.0.0
    op.execute(f"""
        INSERT INTO device_configs (id, config_version, config_data, etag, is_active, description)
        VALUES (
            '{uuid.uuid4()}',
            '1.0.0',
            '{{"floor_limit": 25.00, "max_offline_transactions": 100, "fraud_rules": [], "features": {{"offline_mode": true, "ai_inference": true}}, "workflows": {{}}, "models": {{}}}}',
            'default-etag-v1',
            true,
            'Default configuration for edge devices'
        )
        ON CONFLICT DO NOTHING
    """)

    # Default command versions
    # Note: spaces added after ":" before numeric values to avoid SQLAlchemy named-param regex matching ":0"/":300"
    _v1 = str(uuid.uuid4())
    _v2 = str(uuid.uuid4())
    _v3 = str(uuid.uuid4())
    _v4 = str(uuid.uuid4())
    op.execute(sa.text(f"""
        INSERT INTO command_versions (id, command_type, version, schema_definition, changelog, created_by) VALUES
            ('{_v1}', 'restart', '1.0.0', '{{"type": "object", "properties": {{"delay_seconds": {{"type": "integer", "minimum": 0, "maximum": 300}}}}, "required": []}}', 'Initial version', 'system'),
            ('{_v2}', 'health_check', '1.0.0', '{{"type": "object", "properties": {{}}, "required": []}}', 'Initial version', 'system'),
            ('{_v3}', 'update_firmware', '1.0.0', '{{"type": "object", "properties": {{"version": {{"type": "string"}}, "url": {{"type": "string", "format": "uri"}}}}, "required": ["version"]}}', 'Initial version', 'system'),
            ('{_v4}', 'clear_cache', '1.0.0', '{{"type": "object", "properties": {{"cache_type": {{"type": "string", "enum": ["all", "temp", "logs"]}}}}, "required": []}}', 'Initial version', 'system')
        ON CONFLICT (command_type, version) DO NOTHING
    """))


def downgrade() -> None:
    # Drop in reverse FK order

    # Seed data (no need to delete explicitly — tables dropped below)

    # Drop cloud-only tables (reverse of upgrade order)
    op.drop_table('policies')
    op.drop_table('device_assignments')

    op.drop_index('ix_saf_idempotency', table_name='saf_transactions')
    op.drop_index('ix_saf_status', table_name='saf_transactions')
    op.drop_index('ix_saf_device', table_name='saf_transactions')
    op.drop_table('saf_transactions')

    op.drop_index('ix_config_version', table_name='device_configs')
    op.drop_index('ix_config_active', table_name='device_configs')
    op.drop_table('device_configs')

    op.drop_index('ix_rate_limit_cleanup', table_name='rate_limit_tracking')
    op.drop_index('ix_rate_limit_identifier', table_name='rate_limit_tracking')
    op.drop_table('rate_limit_tracking')

    op.drop_index('ix_rate_limit_active', table_name='rate_limit_rules')
    op.drop_table('rate_limit_rules')

    op.drop_index('ix_webhook_delivery_created', table_name='webhook_deliveries')
    op.drop_index('ix_webhook_delivery_status', table_name='webhook_deliveries')
    op.drop_index('ix_webhook_delivery_webhook', table_name='webhook_deliveries')
    op.drop_table('webhook_deliveries')

    op.drop_index('ix_webhook_active', table_name='webhook_registrations')
    op.drop_table('webhook_registrations')

    op.drop_index('ix_changelog_version', table_name='command_changelog')
    op.drop_index('ix_changelog_command', table_name='command_changelog')
    op.drop_table('command_changelog')

    op.drop_index('ix_command_version_active', table_name='command_versions')
    op.drop_index('ix_command_version_type', table_name='command_versions')
    op.drop_table('command_versions')

    op.drop_index('ix_approval_response_approver', table_name='approval_responses')
    op.drop_index('ix_approval_response_approval', table_name='approval_responses')
    op.drop_table('approval_responses')

    op.drop_index('ix_approval_expires', table_name='command_approvals')
    op.drop_index('ix_approval_requested_by', table_name='command_approvals')
    op.drop_index('ix_approval_status', table_name='command_approvals')
    op.drop_table('command_approvals')

    op.drop_index('ix_policy_active', table_name='authorization_policies')
    op.drop_index('ix_policy_command_type', table_name='authorization_policies')
    op.drop_table('authorization_policies')

    op.drop_index('ix_role_assignment_role', table_name='role_assignments')
    op.drop_index('ix_role_assignment_user', table_name='role_assignments')
    op.drop_table('role_assignments')

    op.drop_index('ix_role_name', table_name='authorization_roles')
    op.drop_table('authorization_roles')

    op.drop_table('audit_retention_policies')

    # Drop TSVECTOR index before dropping command_audit_log
    op.execute('DROP INDEX IF EXISTS idx_audit_search')
    op.drop_index('ix_audit_actor_event', table_name='command_audit_log')
    op.drop_index('ix_audit_device_event', table_name='command_audit_log')
    op.drop_index('ix_audit_status', table_name='command_audit_log')
    op.drop_index('ix_audit_merchant', table_name='command_audit_log')
    op.drop_index('ix_cmd_audit_event_type', table_name='command_audit_log')
    op.drop_index('ix_audit_actor', table_name='command_audit_log')
    op.drop_index('ix_audit_command_id', table_name='command_audit_log')
    op.drop_index('ix_audit_device', table_name='command_audit_log')
    op.drop_index('ix_audit_timestamp', table_name='command_audit_log')
    op.drop_table('command_audit_log')

    op.drop_index('ix_schedule_execution_scheduled_for', table_name='schedule_executions')
    op.drop_index('ix_schedule_execution_status', table_name='schedule_executions')
    op.drop_index('ix_schedule_execution_schedule', table_name='schedule_executions')
    op.drop_table('schedule_executions')

    op.drop_index('ix_schedule_type', table_name='command_schedules')
    op.drop_index('ix_schedule_status', table_name='command_schedules')
    op.drop_index('ix_schedule_device', table_name='command_schedules')
    op.drop_index('ix_schedule_next_execution', table_name='command_schedules')
    op.drop_table('command_schedules')

    # Revert device_commands expansions
    op.drop_constraint('fk_device_commands_broadcast_id_command_broadcasts', 'device_commands', type_='foreignkey')
    op.drop_constraint('fk_device_commands_batch_id_command_batches', 'device_commands', type_='foreignkey')
    op.drop_index('ix_command_version', table_name='device_commands')
    op.drop_index('ix_command_broadcast', table_name='device_commands')
    op.drop_index('ix_command_batch', table_name='device_commands')
    op.drop_index('ix_command_retry', table_name='device_commands')
    op.drop_index('ix_command_expires', table_name='device_commands')
    op.drop_index('ix_device_command_command_id', table_name='device_commands')
    op.drop_column('device_commands', 'command_version')
    op.drop_column('device_commands', 'broadcast_id')
    op.drop_column('device_commands', 'batch_sequence')
    op.drop_column('device_commands', 'batch_id')
    op.drop_column('device_commands', 'last_retry_at')
    op.drop_column('device_commands', 'next_retry_at')
    op.drop_column('device_commands', 'max_retries')
    op.drop_column('device_commands', 'retry_count')
    op.drop_column('device_commands', 'retry_policy')
    op.drop_column('device_commands', 'expires_at')
    op.drop_column('device_commands', 'completed_at')
    op.drop_column('device_commands', 'sent_at')
    op.drop_column('device_commands', 'command_id')

    op.drop_index('ix_template_active', table_name='command_templates')
    op.drop_index('ix_template_name', table_name='command_templates')
    op.drop_table('command_templates')

    op.drop_index('ix_batch_status', table_name='command_batches')
    op.drop_index('ix_batch_device', table_name='command_batches')
    op.drop_table('command_batches')

    op.drop_index('ix_broadcast_created', table_name='command_broadcasts')
    op.drop_index('ix_broadcast_status', table_name='command_broadcasts')
    op.drop_table('command_broadcasts')

    op.drop_index('ix_scheduled_workflows_enabled', table_name='scheduled_workflows')
    op.drop_table('scheduled_workflows')

    op.drop_index('ix_compensation_log_execution_id', table_name='compensation_log')
    op.drop_table('compensation_log')

    op.drop_index('ix_tasks_execution_id', table_name='tasks')
    op.drop_index('ix_tasks_execution', table_name='tasks')
    op.drop_index('ix_tasks_claim', table_name='tasks')
    op.drop_table('tasks')
