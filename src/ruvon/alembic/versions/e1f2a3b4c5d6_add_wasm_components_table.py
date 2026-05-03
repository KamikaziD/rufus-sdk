"""Add wasm_components table for WASM binary registry

Revision ID: e1f2a3b4c5d6
Revises: 441ed90ac861
Create Date: 2026-03-10 00:00:00.000000

Adds the wasm_components table to track pre-compiled WebAssembly binaries
managed by the cloud control plane. Binaries are stored on local disk;
this table holds metadata and the path to each binary.

Uses IF NOT EXISTS / IF EXISTS guards so it is safe to apply on databases
that were already migrated manually.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = '441ed90ac861'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS wasm_components (
            id                VARCHAR(36) PRIMARY KEY,
            name              VARCHAR(200) NOT NULL,
            version_tag       VARCHAR(50)  NOT NULL,
            binary_hash       VARCHAR(64)  NOT NULL,
            blob_storage_path TEXT         NOT NULL,
            input_schema      TEXT,
            output_schema     TEXT,
            created_at        TIMESTAMP    DEFAULT NOW(),
            updated_at        TIMESTAMP    DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_wasm_components_binary_hash
        ON wasm_components (binary_hash)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_wasm_components_name
        ON wasm_components (name)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_wasm_components_hash
        ON wasm_components (binary_hash)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_wasm_components_hash")
    op.execute("DROP INDEX IF EXISTS ix_wasm_components_name")
    op.execute("DROP INDEX IF EXISTS uq_wasm_components_binary_hash")
    op.execute("DROP TABLE IF EXISTS wasm_components")
