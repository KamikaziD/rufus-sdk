"""baseline schema: workflow_executions and observability tables

Revision ID: 047d1ed10688
Revises:
Create Date: 2026-02-11 15:36:56.473670

Creates all core workflow tables for fresh database setup:
- workflow_executions (main workflow state table)
- workflow_audit_log (event logging)
- workflow_heartbeats (worker health monitoring)
- workflow_metrics (performance tracking)

Supports both PostgreSQL and SQLite using database-agnostic types.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '047d1ed10688'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create baseline schema with workflow_executions and observability tables."""

    # Create workflow_executions table (baseline)
    op.create_table(
        'workflow_executions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('workflow_type', sa.String(length=200), nullable=False),
        sa.Column('workflow_version', sa.String(length=50), nullable=True),
        sa.Column('definition_snapshot', sa.Text(), nullable=True),
        sa.Column('current_step', sa.String(length=200), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('state', sa.Text(), nullable=False),
        sa.Column('steps_config', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('state_model_path', sa.String(length=500), nullable=False),
        sa.Column('saga_mode', sa.Boolean(), server_default='false'),
        sa.Column('completed_steps_stack', sa.Text(), server_default='[]'),
        sa.Column('parent_execution_id', sa.String(length=36), nullable=True),
        sa.Column('blocked_on_child_id', sa.String(length=36), nullable=True),
        sa.Column('data_region', sa.String(length=50), server_default='us-east-1'),
        sa.Column('priority', sa.Integer(), server_default='5'),
        sa.Column('idempotency_key', sa.String(length=255), nullable=True),
        sa.Column('metadata', sa.Text(), server_default='{}'),
        sa.Column('owner_id', sa.String(length=200), nullable=True),
        sa.Column('org_id', sa.String(length=200), nullable=True),
        sa.Column('encrypted_state', sa.LargeBinary(), nullable=True),
        sa.Column('encryption_key_id', sa.String(length=100), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['parent_execution_id'], ['workflow_executions.id'], name='fk_workflow_executions_parent_execution_id_workflow_executions'),
        sa.PrimaryKeyConstraint('id', name='pk_workflow_executions'),
        sa.UniqueConstraint('idempotency_key', name='uq_workflow_executions_idempotency_key')
    )

    op.create_index('ix_workflow_executions_status', 'workflow_executions', ['status'])
    op.create_index('ix_workflow_executions_workflow_type', 'workflow_executions', ['workflow_type'])
    op.create_index('ix_workflow_status_created', 'workflow_executions', ['status', 'created_at'])
    op.create_index('ix_workflow_type_status', 'workflow_executions', ['workflow_type', 'status'])
    op.create_index('ix_workflow_owner', 'workflow_executions', ['owner_id', 'created_at'])

    # Create workflow_audit_log table
    op.create_table(
        'workflow_audit_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('workflow_id', sa.String(length=36), nullable=False),
        sa.Column('timestamp', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('step_name', sa.String(length=200), nullable=True),
        sa.Column('actor', sa.String(length=200), nullable=True),
        sa.Column('old_status', sa.String(length=50), nullable=True),
        sa.Column('new_status', sa.String(length=50), nullable=True),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('execution_duration_ms', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflow_executions.id'], name='fk_workflow_audit_log_workflow_id_workflow_executions', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='pk_workflow_audit_log')
    )

    op.create_index('ix_audit_event_type', 'workflow_audit_log', ['event_type', 'timestamp'])
    op.create_index('ix_audit_workflow_timestamp', 'workflow_audit_log', ['workflow_id', 'timestamp'])
    op.create_index('ix_workflow_audit_log_workflow_id', 'workflow_audit_log', ['workflow_id'])

    # Create workflow_heartbeats table
    op.create_table(
        'workflow_heartbeats',
        sa.Column('workflow_id', sa.String(length=36), nullable=False),
        sa.Column('worker_id', sa.String(length=100), nullable=False),
        sa.Column('last_heartbeat', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('current_step', sa.String(length=200), nullable=True),
        sa.Column('step_started_at', sa.DateTime(), nullable=True),
        sa.Column('metadata', sa.Text(), server_default='{}', nullable=True),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflow_executions.id'], name='fk_workflow_heartbeats_workflow_id_workflow_executions', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('workflow_id', name='pk_workflow_heartbeats')
    )

    op.create_index('ix_heartbeat_time', 'workflow_heartbeats', ['last_heartbeat'])

    # Create workflow_metrics table
    op.create_table(
        'workflow_metrics',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('workflow_id', sa.String(length=36), nullable=False),
        sa.Column('metric_type', sa.String(length=50), nullable=False),
        sa.Column('metric_name', sa.String(length=100), nullable=False),
        sa.Column('metric_value', sa.Integer(), nullable=True),
        sa.Column('tags', sa.Text(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflow_executions.id'], name='fk_workflow_metrics_workflow_id_workflow_executions', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='pk_workflow_metrics')
    )

    op.create_index('ix_metrics_type_timestamp', 'workflow_metrics', ['metric_type', 'timestamp'])
    op.create_index('ix_metrics_workflow', 'workflow_metrics', ['workflow_id', 'timestamp'])
    op.create_index('ix_workflow_metrics_workflow_id', 'workflow_metrics', ['workflow_id'])


def downgrade() -> None:
    """Remove all workflow tables."""

    # Drop workflow_metrics table
    op.drop_index('ix_workflow_metrics_workflow_id', table_name='workflow_metrics')
    op.drop_index('ix_metrics_workflow', table_name='workflow_metrics')
    op.drop_index('ix_metrics_type_timestamp', table_name='workflow_metrics')
    op.drop_table('workflow_metrics')

    # Drop workflow_heartbeats table
    op.drop_index('ix_heartbeat_time', table_name='workflow_heartbeats')
    op.drop_table('workflow_heartbeats')

    # Drop workflow_audit_log table
    op.drop_index('ix_workflow_audit_log_workflow_id', table_name='workflow_audit_log')
    op.drop_index('ix_audit_workflow_timestamp', table_name='workflow_audit_log')
    op.drop_index('ix_audit_event_type', table_name='workflow_audit_log')
    op.drop_table('workflow_audit_log')

    # Drop workflow_executions table (baseline)
    op.drop_index('ix_workflow_owner', table_name='workflow_executions')
    op.drop_index('ix_workflow_type_status', table_name='workflow_executions')
    op.drop_index('ix_workflow_status_created', table_name='workflow_executions')
    op.drop_index('ix_workflow_executions_workflow_type', table_name='workflow_executions')
    op.drop_index('ix_workflow_executions_status', table_name='workflow_executions')
    op.drop_table('workflow_executions')
