"""phase 4: value method and attestation, measured outcomes

Revision ID: 0009_phase4_value
Revises: 0008_phase3_reuse
Create Date: 2026-10-08 23:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0009_phase4_value'
down_revision = '0008_phase3_reuse'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('agents') as batch:
        batch.add_column(sa.Column('value_method', sa.String(length=30), nullable=True))
        batch.add_column(sa.Column('value_basis', sa.Text(), nullable=True))
        batch.add_column(sa.Column('value_hourly_rate_cents', sa.Integer(), nullable=True))
    op.create_table(
        'value_attestations',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('agent_id', sa.String(length=64), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('declared_cents', sa.Integer(), nullable=True),
        sa.Column('declared_method', sa.String(length=30), nullable=True),
        sa.Column('attested_cents', sa.Integer(), nullable=True),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('attested_by', sa.String(length=255), nullable=True),
        sa.Column('attested_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('idx_value_attestations_agent', 'value_attestations', ['agent_id'])
    op.create_table(
        'agent_outcomes',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('agent_id', sa.String(length=64), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('outcome', sa.String(length=120), nullable=False),
        sa.Column('count', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=True),
        sa.Column('recorded_by', sa.String(length=255), nullable=True),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('agent_id', 'day', 'outcome', name='uq_agent_outcomes'),
    )


def downgrade() -> None:
    op.drop_table('agent_outcomes')
    op.drop_index('idx_value_attestations_agent', table_name='value_attestations')
    op.drop_table('value_attestations')
    with op.batch_alter_table('agents') as batch:
        for col in ('value_hourly_rate_cents', 'value_basis', 'value_method'):
            batch.drop_column(col)
