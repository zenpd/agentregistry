"""phoenix projects seen by discovery

Revision ID: 0003_phoenix_projects
Revises: 0002_agent_registry
Create Date: 2026-10-01 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0003_phoenix_projects'
down_revision = '0002_agent_registry'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('phoenix_config', sa.Column('app_url_template', sa.String(length=500), nullable=True))
    op.create_table('phoenix_projects',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('org_id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=True),
        sa.Column('dismiss_reason', sa.String(length=500), nullable=True),
        sa.Column('dismissed_by', sa.String(length=255), nullable=True),
        sa.Column('span_count', sa.Integer(), nullable=True),
        sa.Column('window_days', sa.Integer(), nullable=True),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=True),
        sa.Column('models', sa.JSON(), nullable=True),
        sa.Column('tools', sa.JSON(), nullable=True),
        sa.Column('mcp_servers', sa.JSON(), nullable=True),
        sa.Column('agent_names', sa.JSON(), nullable=True),
        sa.Column('retrievers', sa.JSON(), nullable=True),
        sa.Column('span_kinds', sa.JSON(), nullable=True),
        sa.Column('attribute_keys', sa.JSON(), nullable=True),
        sa.Column('scan_error', sa.String(length=500), nullable=True),
        sa.Column('scanned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'name', name='uq_phoenix_projects_org_name'),
    )
    op.create_index('idx_phoenix_projects_org_id', 'phoenix_projects', ['org_id'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_phoenix_projects_org_id', table_name='phoenix_projects')
    op.drop_table('phoenix_projects')
    op.drop_column('phoenix_config', 'app_url_template')
