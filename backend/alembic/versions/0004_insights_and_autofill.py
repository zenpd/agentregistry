"""insight agents and automatic record updates

Revision ID: 0004_insights_and_autofill
Revises: 0003_phoenix_projects
Create Date: 2026-10-06 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0004_insights_and_autofill'
down_revision = '0003_phoenix_projects'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('insights',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('org_id', sa.String(length=64), nullable=False),
        sa.Column('agent_id', sa.String(length=64), nullable=True),
        sa.Column('kind', sa.String(length=50), nullable=False),
        sa.Column('subject', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('output', sa.JSON(), nullable=True),
        sa.Column('refs', sa.JSON(), nullable=True),
        sa.Column('tools_used', sa.JSON(), nullable=True),
        sa.Column('checks', sa.JSON(), nullable=True),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.Column('prompt_version', sa.String(length=20), nullable=True),
        sa.Column('steps', sa.Integer(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_insights_agent_kind', 'insights', ['agent_id', 'kind'], unique=False)
    op.create_index('idx_insights_org_id', 'insights', ['org_id'], unique=False)

    op.create_table('insight_feedback',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('insight_id', sa.String(length=64), nullable=False),
        sa.Column('verdict', sa.String(length=20), nullable=False),
        sa.Column('note', sa.String(length=1000), nullable=True),
        sa.Column('actor', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['insight_id'], ['insights.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_insight_feedback_insight', 'insight_feedback', ['insight_id'], unique=False)

    op.create_table('content_audit_opt_ins',
        sa.Column('agent_id', sa.String(length=64), nullable=False),
        sa.Column('opted_by', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('agent_id'),
    )

    op.create_table('agent_field_updates',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('org_id', sa.String(length=64), nullable=False),
        sa.Column('agent_id', sa.String(length=64), nullable=False),
        sa.Column('field', sa.String(length=50), nullable=False),
        sa.Column('old_value', sa.JSON(), nullable=True),
        sa.Column('new_value', sa.JSON(), nullable=True),
        sa.Column('source', sa.String(length=30), nullable=False),
        sa.Column('reason', sa.String(length=600), nullable=True),
        sa.Column('applied_by', sa.String(length=255), nullable=False),
        sa.Column('applied_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('reverted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reverted_by', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_agent_field_updates_agent', 'agent_field_updates', ['agent_id', 'field'], unique=False)

    op.create_table('agent_record_checks',
        sa.Column('agent_id', sa.String(length=64), nullable=False),
        sa.Column('org_id', sa.String(length=64), nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('link', sa.String(length=800), nullable=False),
        sa.Column('complete', sa.Boolean(), nullable=True),
        sa.Column('evidence', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
        sa.PrimaryKeyConstraint('agent_id'),
    )


def downgrade() -> None:
    op.drop_table('agent_record_checks')
    op.drop_index('idx_agent_field_updates_agent', table_name='agent_field_updates')
    op.drop_table('agent_field_updates')
    op.drop_table('content_audit_opt_ins')
    op.drop_index('idx_insight_feedback_insight', table_name='insight_feedback')
    op.drop_table('insight_feedback')
    op.drop_index('idx_insights_org_id', table_name='insights')
    op.drop_index('idx_insights_agent_kind', table_name='insights')
    op.drop_table('insights')
