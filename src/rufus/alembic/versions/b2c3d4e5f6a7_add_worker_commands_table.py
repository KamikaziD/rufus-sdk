"""add worker_commands table and worker_nodes fleet columns

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-03 00:00:00.000000

Changes:
- Add 3 columns to worker_nodes: sdk_version, pending_command_count, last_command_at
- Create worker_commands table (DB-delivery channel for control plane → Celery worker commands)
- Add 3 indexes on worker_commands
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── worker_nodes: 3 new columns ─────────────────────────────────────────
    op.add_column('worker_nodes',
        sa.Column('sdk_version', sa.String(50), nullable=True))
    op.add_column('worker_nodes',
        sa.Column('pending_command_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('worker_nodes',
        sa.Column('last_command_at', sa.DateTime(), nullable=True))

    # ── worker_commands table ────────────────────────────────────────────────
    op.create_table(
        'worker_commands',
        sa.Column('command_id', sa.String(100), primary_key=True),
        sa.Column('worker_id', sa.String(100),
                  sa.ForeignKey('worker_nodes.worker_id', ondelete='CASCADE'), nullable=True),
        sa.Column('target_filter', sa.Text(), nullable=True),
        sa.Column('command_type', sa.String(50), nullable=False),
        sa.Column('command_data', sa.Text(), server_default='{}'),
        sa.Column('status', sa.String(20), server_default='pending'),
        sa.Column('priority', sa.String(20), server_default='normal'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('created_by', sa.String(100), nullable=True),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.Column('executed_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('result', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), server_default='0'),
        sa.Column('max_retries', sa.Integer(), server_default='0'),
    )

    op.create_index('ix_worker_cmd_worker_status', 'worker_commands', ['worker_id', 'status'])
    op.create_index('ix_worker_cmd_status_created', 'worker_commands', ['status', 'created_at'])
    op.create_index('ix_worker_cmd_expires', 'worker_commands', ['expires_at'])


def downgrade() -> None:
    op.drop_index('ix_worker_cmd_expires', table_name='worker_commands')
    op.drop_index('ix_worker_cmd_status_created', table_name='worker_commands')
    op.drop_index('ix_worker_cmd_worker_status', table_name='worker_commands')
    op.drop_table('worker_commands')

    op.drop_column('worker_nodes', 'last_command_at')
    op.drop_column('worker_nodes', 'pending_command_count')
    op.drop_column('worker_nodes', 'sdk_version')
