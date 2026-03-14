"""v1.0 edge: last_device_sequence + api_key_rotated_at

Revision ID: f1a2b3c4d5e6
Revises: e1f2a3b4c5d6
Create Date: 2026-03-14
"""

from alembic import op
import sqlalchemy as sa

revision = "f1a2b3c4d5e6"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade():
    # Track the last device_sequence seen by the cloud for monotonic validation
    op.add_column(
        "edge_devices",
        sa.Column(
            "last_device_sequence",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    # Track when the API key was last rotated for audit / compliance
    op.add_column(
        "edge_devices",
        sa.Column("api_key_rotated_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_column("edge_devices", "api_key_rotated_at")
    op.drop_column("edge_devices", "last_device_sequence")
