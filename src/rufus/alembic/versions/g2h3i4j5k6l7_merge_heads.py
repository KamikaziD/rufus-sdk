"""Merge workflow-definitions branch and wasm-edge branch into single head.

Revision ID: g2h3i4j5k6l7
Revises: c1d2e3f4a5b6, f1a2b3c4d5e6
Create Date: 2026-03-16

"""
from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'g2h3i4j5k6l7'
down_revision: Union[str, Sequence[str], None] = ('c1d2e3f4a5b6', 'f1a2b3c4d5e6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass  # Merge only — no schema changes


def downgrade() -> None:
    pass
