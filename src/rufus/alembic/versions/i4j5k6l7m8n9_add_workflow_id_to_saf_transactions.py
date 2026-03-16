"""Add workflow_id to saf_transactions.

Revision ID: i4j5k6l7m8n9
Revises: h3i4j5k6l7m8
Create Date: 2026-03-16

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'i4j5k6l7m8n9'
down_revision: Union[str, Sequence[str], None] = 'h3i4j5k6l7m8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE saf_transactions ADD COLUMN IF NOT EXISTS workflow_id TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE saf_transactions DROP COLUMN IF EXISTS workflow_id")
