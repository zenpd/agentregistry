"""phase 1: discovery triage, convention hints, keys, sources and findings

Revision ID: 0006_phase1_discovery
Revises: 0005_phase0_foundation
Create Date: 2026-10-08 14:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0006_phase1_discovery'
down_revision = '0005_phase0_foundation'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('phoenix_projects') as batch:
        batch.add_column(sa.Column('error_count', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('service_names', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('hints', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('assignee_user_id', sa.String(length=64), nullable=True))
        batch.add_column(sa.Column('due_date', sa.Date(), nullable=True))
        batch.add_column(sa.Column('triage_note', sa.String(length=1000), nullable=True))

    with op.batch_alter_table('agents') as batch:
        batch.add_column(sa.Column('source_repo', sa.String(length=500), nullable=True))
        batch.add_column(sa.Column('cloud_resource_id', sa.String(length=500), nullable=True))
        batch.add_column(sa.Column('trace_connector_id', sa.String(length=64), nullable=True))

    op.create_table('connector_configs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=False),
        sa.Column('settings', sa.JSON(), nullable=True),
        sa.Column('secret_enc', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_status', sa.String(length=30), nullable=True),
        sa.Column('last_message', sa.String(length=500), nullable=True),
        sa.Column('last_found', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table('external_findings',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('connector_id', sa.String(length=64), nullable=False),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('external_id', sa.String(length=500), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('url', sa.String(length=500), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('state', sa.String(length=20), nullable=True),
        sa.Column('dismiss_reason', sa.String(length=500), nullable=True),
        sa.Column('linked_agent_id', sa.String(length=64), nullable=True),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['connector_id'], ['connector_configs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('connector_id', 'external_id', name='uq_external_findings'),
    )
    op.create_index('idx_external_findings_state', 'external_findings', ['state'], unique=False)

    op.create_table('api_keys',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=False),
        sa.Column('prefix', sa.String(length=20), nullable=False),
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column('scopes', sa.JSON(), nullable=True),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_by', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key_hash', name='uq_api_keys_hash'),
    )


def downgrade() -> None:
    op.drop_table('api_keys')
    op.drop_index('idx_external_findings_state', table_name='external_findings')
    op.drop_table('external_findings')
    op.drop_table('connector_configs')
    with op.batch_alter_table('agents') as batch:
        for col in ('trace_connector_id', 'cloud_resource_id', 'source_repo'):
            batch.drop_column(col)
    with op.batch_alter_table('phoenix_projects') as batch:
        for col in ('triage_note', 'due_date', 'assignee_user_id', 'hints', 'service_names', 'error_count'):
            batch.drop_column(col)
