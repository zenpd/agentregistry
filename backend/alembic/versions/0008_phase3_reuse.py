"""phase 3: observed consumers, search gaps, start from a certified agent

Revision ID: 0008_phase3_reuse
Revises: 0007_phase2_lifecycle
Create Date: 2026-10-08 21:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0008_phase3_reuse'
down_revision = '0007_phase2_lifecycle'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('agents') as batch:
        batch.add_column(sa.Column('started_from_agent_id', sa.String(length=64), nullable=True))
    op.create_table(
        'observed_consumers',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('agent_id', sa.String(length=64), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('caller', sa.String(length=255), nullable=False),
        sa.Column('caller_agent_id', sa.String(length=64), nullable=True),
        sa.Column('calls', sa.Integer(), nullable=True),
        sa.Column('first_seen', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('agent_id', 'kind', 'caller', name='uq_observed_consumers'),
    )
    op.create_table(
        'search_log',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('user_id', sa.String(length=64), nullable=True),
        sa.Column('query', sa.String(length=255), nullable=False),
        sa.Column('results', sa.Integer(), nullable=True),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('idx_search_log_at', 'search_log', ['at'])


def downgrade() -> None:
    op.drop_index('idx_search_log_at', table_name='search_log')
    op.drop_table('search_log')
    op.drop_table('observed_consumers')
    with op.batch_alter_table('agents') as batch:
        batch.drop_column('started_from_agent_id')
