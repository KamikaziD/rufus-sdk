"""Patch workflow_metrics schema and rate_limit_tracking unique constraint.

workflow_metrics: add workflow_type, step_name, unit, recorded_at columns
  that the rc3 postgres.py INSERT expects but the initial migration omitted.

rate_limit_tracking: add UNIQUE(identifier, resource, window_start) for
  ON CONFLICT upsert used by the rate-limiter middleware.

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2026-03-16

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'h3i4j5k6l7m8'
down_revision: Union[str, Sequence[str], None] = 'g2h3i4j5k6l7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── workflow_metrics: add missing columns ─────────────────────────────────
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('workflow_metrics')}

    if 'workflow_type' not in existing_cols:
        op.add_column('workflow_metrics',
                      sa.Column('workflow_type', sa.String(200), nullable=True))

    if 'step_name' not in existing_cols:
        op.add_column('workflow_metrics',
                      sa.Column('step_name', sa.String(200), nullable=True))

    if 'unit' not in existing_cols:
        op.add_column('workflow_metrics',
                      sa.Column('unit', sa.String(50), nullable=True))

    if 'recorded_at' not in existing_cols:
        op.add_column('workflow_metrics',
                      sa.Column('recorded_at', sa.DateTime,
                                server_default=sa.func.now(), nullable=True))

    # ── workflow_metrics: make metric_type nullable (rc3 INSERT omits it) ──────
    op.alter_column('workflow_metrics', 'metric_type', nullable=True)

    # ── rate_limit_tracking: add unique constraint for ON CONFLICT upsert ─────
    existing_constraints = {
        c['name']
        for c in insp.get_unique_constraints('rate_limit_tracking')
    }
    if 'uq_rate_limit_window' not in existing_constraints:
        op.create_unique_constraint(
            'uq_rate_limit_window',
            'rate_limit_tracking',
            ['identifier', 'resource', 'window_start'],
        )


def downgrade() -> None:
    op.drop_constraint('uq_rate_limit_window', 'rate_limit_tracking',
                       type_='unique')
    op.drop_column('workflow_metrics', 'recorded_at')
    op.drop_column('workflow_metrics', 'unit')
    op.drop_column('workflow_metrics', 'step_name')
    op.drop_column('workflow_metrics', 'workflow_type')
