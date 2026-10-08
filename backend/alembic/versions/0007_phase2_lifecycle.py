"""phase 2: approval snapshots, two-signer waivers, classification, versions, ownership and delegation

Revision ID: 0007_phase2_lifecycle
Revises: 0006_phase1_discovery
Create Date: 2026-10-08 18:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0007_phase2_lifecycle'
down_revision = '0006_phase1_discovery'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('governance_reviews') as batch:
        batch.add_column(sa.Column('approved_snapshot', sa.JSON(), nullable=True))
    with op.batch_alter_table('governance_exceptions') as batch:
        batch.add_column(sa.Column('status', sa.String(length=20), nullable=True))
        batch.add_column(sa.Column('first_signer', sa.String(length=255), nullable=True))
        batch.add_column(sa.Column('second_signer', sa.String(length=255), nullable=True))
        batch.add_column(sa.Column('second_signed_at', sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('away_until', sa.Date(), nullable=True))
        batch.add_column(sa.Column('deputy_user_id', sa.String(length=64), nullable=True))
    with op.batch_alter_table('agent_access_requests') as batch:
        batch.add_column(sa.Column('agent_version', sa.String(length=50), nullable=True))
    op.create_table(
        'classification_records',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('agent_id', sa.String(length=64), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('answers', sa.JSON(), nullable=True),
        sa.Column('suggested_category', sa.String(length=32), nullable=False),
        sa.Column('suggested_risk_level', sa.String(length=20), nullable=False),
        sa.Column('reasons', sa.JSON(), nullable=True),
        sa.Column('category', sa.String(length=32), nullable=True),
        sa.Column('risk_level', sa.String(length=20), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('proposed_by', sa.String(length=255), nullable=True),
        sa.Column('proposed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('confirmed_by', sa.String(length=255), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_classification_records_agent', 'classification_records', ['agent_id'])
    op.create_table(
        'approved_tools',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('kind', sa.String(length=30), nullable=True),
        sa.Column('risk_class', sa.String(length=10), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('added_by', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('name', name='uq_approved_tools_name'),
    )
    op.create_table(
        'agent_versions',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('agent_id', sa.String(length=64), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.String(length=50), nullable=False),
        sa.Column('changelog', sa.Text(), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=True),
        sa.Column('released_by', sa.String(length=255), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('agent_id', 'version', name='uq_agent_versions'),
    )
    op.create_table(
        'agent_retirements',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('agent_id', sa.String(length=64), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('replacement_agent_id', sa.String(length=64), nullable=True),
        sa.Column('steps', sa.JSON(), nullable=True),
        sa.Column('started_by', sa.String(length=255), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_agent_retirements_agent', 'agent_retirements', ['agent_id'])
    op.create_table(
        'evidence_verdicts',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('agent_id', sa.String(length=64), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('connector_id', sa.String(length=64), nullable=True),
        sa.Column('run_id', sa.String(length=64), nullable=False),
        sa.Column('verdict', sa.String(length=20), nullable=True),
        sa.Column('application', sa.String(length=255), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('url', sa.String(length=500), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('recorded_by', sa.String(length=255), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('agent_id', 'run_id', name='uq_evidence_verdicts'),
    )


def downgrade() -> None:
    op.drop_table('evidence_verdicts')
    op.drop_index('idx_agent_retirements_agent', table_name='agent_retirements')
    op.drop_table('agent_retirements')
    op.drop_table('agent_versions')
    op.drop_table('approved_tools')
    op.drop_index('idx_classification_records_agent', table_name='classification_records')
    op.drop_table('classification_records')
    with op.batch_alter_table('agent_access_requests') as batch:
        batch.drop_column('agent_version')
    with op.batch_alter_table('users') as batch:
        batch.drop_column('deputy_user_id')
        batch.drop_column('away_until')
    with op.batch_alter_table('governance_exceptions') as batch:
        for col in ('second_signed_at', 'second_signer', 'first_signer', 'status'):
            batch.drop_column(col)
    with op.batch_alter_table('governance_reviews') as batch:
        batch.drop_column('approved_snapshot')
