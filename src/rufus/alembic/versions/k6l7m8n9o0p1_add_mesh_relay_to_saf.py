"""add mesh_relay columns to saf_transactions

Revision ID: k6l7m8n9o0p1
Revises: j5k6l7m8n9o0
Create Date: 2026-03-22

"""
from alembic import op
import sqlalchemy as sa

revision = 'k6l7m8n9o0p1'
down_revision = 'j5k6l7m8n9o0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('saf_transactions', sa.Column('relay_device_id', sa.Text(), nullable=True))
    op.add_column('saf_transactions', sa.Column('relay_source_device_id', sa.Text(), nullable=True))
    op.add_column('saf_transactions', sa.Column('hop_count', sa.Integer(), nullable=True))
    op.add_column('saf_transactions', sa.Column('relayed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('saf_transactions', 'relayed_at')
    op.drop_column('saf_transactions', 'hop_count')
    op.drop_column('saf_transactions', 'relay_source_device_id')
    op.drop_column('saf_transactions', 'relay_device_id')
