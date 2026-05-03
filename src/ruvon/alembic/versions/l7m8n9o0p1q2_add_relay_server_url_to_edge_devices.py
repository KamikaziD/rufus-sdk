"""add relay_server_url and mesh_advisory to edge_devices

Revision ID: l7m8n9o0p1q2
Revises: k6l7m8n9o0p1
Create Date: 2026-03-25

"""
from alembic import op
import sqlalchemy as sa

revision = 'l7m8n9o0p1q2'
down_revision = 'k6l7m8n9o0p1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('edge_devices', sa.Column('relay_server_url', sa.Text(), nullable=True))
    op.add_column('edge_devices', sa.Column('mesh_advisory', sa.Text(), nullable=True))
    # Index to quickly find active relay servers (non-null relay_server_url)
    op.create_index('ix_device_relay_server', 'edge_devices', ['relay_server_url'])


def downgrade():
    op.drop_index('ix_device_relay_server', table_name='edge_devices')
    op.drop_column('edge_devices', 'mesh_advisory')
    op.drop_column('edge_devices', 'relay_server_url')
