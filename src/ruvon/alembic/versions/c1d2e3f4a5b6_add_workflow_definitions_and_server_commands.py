"""add workflow_definitions and server_commands tables

Revision ID: c1d2e3f4a5b6
Revises: b2c3d4e5f6a7
Create Date: 2026-03-03 12:00:00.000000

Uses IF NOT EXISTS / IF EXISTS so it is safe to apply on DBs that were
already migrated via the raw-SQL escape hatch (lessons.md pattern).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── workflow_definitions ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS workflow_definitions (
            id            SERIAL PRIMARY KEY,
            workflow_type VARCHAR(200) NOT NULL,
            version       INTEGER NOT NULL DEFAULT 1,
            yaml_content  TEXT NOT NULL,
            is_active     BOOLEAN NOT NULL DEFAULT TRUE,
            description   TEXT,
            uploaded_by   VARCHAR(200),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_wf_def_type_ver
        ON workflow_definitions(workflow_type, version)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_wf_def_type_active
        ON workflow_definitions(workflow_type, is_active)
    """)

    # ── server_commands ───────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS server_commands (
            id          VARCHAR(36) PRIMARY KEY,
            command     VARCHAR(100) NOT NULL,
            payload     JSONB NOT NULL DEFAULT '{}',
            status      VARCHAR(50) NOT NULL DEFAULT 'pending',
            result      JSONB,
            created_by  VARCHAR(200),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_srv_cmd_status
        ON server_commands(status, created_at)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_srv_cmd_status")
    op.execute("DROP TABLE IF EXISTS server_commands")
    op.execute("DROP INDEX IF EXISTS ix_wf_def_type_active")
    op.execute("DROP INDEX IF EXISTS uq_wf_def_type_ver")
    op.execute("DROP TABLE IF EXISTS workflow_definitions")
