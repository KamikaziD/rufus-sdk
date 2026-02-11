"""add workflow observability tables

Revision ID: 047d1ed10688
Revises:
Create Date: 2026-02-11 15:36:56.473670

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '047d1ed10688'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add workflow observability tables for audit logging, heartbeats, and metrics."""

    # Create workflow_audit_log table
    op.create_table(
        'workflow_audit_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('workflow_id', postgresql.UUID(), nullable=False),
        sa.Column('timestamp', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('step_name', sa.String(length=200), nullable=True),
        sa.Column('actor', sa.String(length=200), nullable=True),
        sa.Column('old_status', sa.String(length=50), nullable=True),
        sa.Column('new_status', sa.String(length=50), nullable=True),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.Column('workflow_id', postgresql.UUID(), nullable=False),
        sa.Column('worker_id', sa.String(length=100), nullable=False),
        sa.Column('last_heartbeat', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('current_step', sa.String(length=200), nullable=True),
        sa.Column('step_started_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=True),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflow_executions.id'], name='fk_workflow_heartbeats_workflow_id_workflow_executions', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('workflow_id', name='pk_workflow_heartbeats')
    )

    op.create_index('ix_heartbeat_time', 'workflow_heartbeats', ['last_heartbeat'])

    # Create workflow_metrics table
    op.create_table(
        'workflow_metrics',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('workflow_id', postgresql.UUID(), nullable=False),
        sa.Column('metric_type', sa.String(length=50), nullable=False),
        sa.Column('metric_name', sa.String(length=100), nullable=False),
        sa.Column('metric_value', sa.Integer(), nullable=True),
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('timestamp', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflow_executions.id'], name='fk_workflow_metrics_workflow_id_workflow_executions', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='pk_workflow_metrics')
    )

    op.create_index('ix_metrics_type_timestamp', 'workflow_metrics', ['metric_type', 'timestamp'])
    op.create_index('ix_metrics_workflow', 'workflow_metrics', ['workflow_id', 'timestamp'])
    op.create_index('ix_workflow_metrics_workflow_id', 'workflow_metrics', ['workflow_id'])


def downgrade() -> None:
    """Remove workflow observability tables."""

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
