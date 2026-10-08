"""phase 5: auditor end date, hash-chained decision log, incidents and stop requests

Revision ID: 0010_phase5_compliance
Revises: 0009_phase4_value
Create Date: 2026-10-09 01:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0010_phase5_compliance'
down_revision = '0009_phase4_value'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('access_until', sa.Date(), nullable=True))
    op.create_table(
        'decision_chain',
        sa.Column('seq', sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column('audit_id', sa.Integer(), sa.ForeignKey('audit_log.id'), nullable=False),
        sa.Column('prev_hash', sa.String(length=64), nullable=False),
        sa.Column('hash', sa.String(length=64), nullable=False),
        sa.Column('sealed_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('audit_id', name='uq_decision_chain_audit'),
    )
    op.create_table(
        'incidents',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('agent_id', sa.String(length=64), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=True),
        sa.Column('external_id', sa.String(length=120), nullable=True),
        sa.Column('url', sa.String(length=500), nullable=True),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('stop_requested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('stop_requested_by', sa.String(length=255), nullable=True),
        sa.Column('stop_reason', sa.Text(), nullable=True),
        sa.Column('stop_acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('stop_acknowledged_by', sa.String(length=255), nullable=True),
        sa.Column('stop_note', sa.Text(), nullable=True),
    )
    op.create_index('idx_incidents_agent', 'incidents', ['agent_id'])
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        op.execute("CREATE TRIGGER IF NOT EXISTS decision_chain_no_update BEFORE UPDATE ON decision_chain "
                   "BEGIN SELECT RAISE(ABORT, 'decision_chain rows cannot be changed'); END")
        op.execute("CREATE TRIGGER IF NOT EXISTS decision_chain_no_delete BEFORE DELETE ON decision_chain "
                   "BEGIN SELECT RAISE(ABORT, 'decision_chain rows cannot be deleted'); END")
    elif bind.dialect.name == 'postgresql':
        op.execute("CREATE OR REPLACE FUNCTION decision_chain_append_only() RETURNS trigger AS $$ "
                   "BEGIN RAISE EXCEPTION 'decision_chain rows cannot be changed or deleted'; END; $$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER decision_chain_append_only BEFORE UPDATE OR DELETE ON decision_chain "
                   "FOR EACH ROW EXECUTE FUNCTION decision_chain_append_only()")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute("DROP TRIGGER IF EXISTS decision_chain_append_only ON decision_chain")
    op.drop_index('idx_incidents_agent', table_name='incidents')
    op.drop_table('incidents')
    op.drop_table('decision_chain')
    with op.batch_alter_table('users') as batch:
        batch.drop_column('access_until')
