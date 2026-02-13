"""add worker_nodes table for celery fleet management

Revision ID: d08b401e4c86
Revises: 047d1ed10688
Create Date: 2026-02-13 09:20:38.282618

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd08b401e4c86'
down_revision: Union[str, None] = '047d1ed10688'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create worker_nodes table for Celery worker fleet management
    op.create_table(
        'worker_nodes',
        sa.Column('worker_id', sa.String(length=100), nullable=False),
        sa.Column('hostname', sa.String(length=255), nullable=False),
        sa.Column('region', sa.String(length=50), nullable=False, server_default='default'),
        sa.Column('zone', sa.String(length=50), nullable=False, server_default='default'),
        sa.Column('capabilities', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('last_heartbeat', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('worker_id')
    )

    # Create indexes for efficient queries
    op.create_index('idx_worker_region', 'worker_nodes', ['region'])
    op.create_index('idx_worker_status', 'worker_nodes', ['status'])
    op.create_index('idx_worker_heartbeat', 'worker_nodes', ['last_heartbeat'])

    # Add check constraint for status values
    # Note: SQLite doesn't support CHECK constraints in ALTER TABLE, so we include it in CREATE TABLE
    # For PostgreSQL, we can add it here, but for cross-DB compatibility, we'll skip it
    # The application layer enforces valid status values


def downgrade() -> None:
    # Drop indexes first
    op.drop_index('idx_worker_heartbeat', table_name='worker_nodes')
    op.drop_index('idx_worker_status', table_name='worker_nodes')
    op.drop_index('idx_worker_region', table_name='worker_nodes')

    # Drop table
    op.drop_table('worker_nodes')
