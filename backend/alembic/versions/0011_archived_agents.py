"""archived agents: left out of every page and job, kept in the database

Revision ID: 0011_archived_agents
Revises: 0010_phase5_compliance
Create Date: 2026-10-08 23:30:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0011_archived_agents'
down_revision = '0010_phase5_compliance'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('agents') as batch:
        batch.add_column(sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('archived_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('agents') as batch:
        batch.drop_column('archived_reason')
        batch.drop_column('archived_at')
