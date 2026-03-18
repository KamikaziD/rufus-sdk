"""Add device_id to device_configs for per-device configuration.

Revision ID: j5k6l7m8n9o0
Revises: i4j5k6l7m8n9
Create Date: 2026-03-17

NULL device_id = global fleet config (existing rows)
Non-NULL device_id = per-device config (takes priority over fleet config)
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'j5k6l7m8n9o0'
down_revision: Union[str, Sequence[str], None] = 'i4j5k6l7m8n9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE device_configs ADD COLUMN IF NOT EXISTS device_id TEXT DEFAULT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_config_device_id ON device_configs (device_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_config_device_id")
    op.execute("ALTER TABLE device_configs DROP COLUMN IF EXISTS device_id")
