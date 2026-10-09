"""phase 0: demo flag, owner accounts, notifications, append-only audit

Revision ID: 0005_phase0_foundation
Revises: 0004_insights_and_autofill
Create Date: 2026-10-08 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0005_phase0_foundation'
down_revision = '0004_insights_and_autofill'
branch_labels = None
depends_on = None

SEED_AGENT_IDS = (
    'inv-recon', 'onboarding', 'lead-scoring', 'proposal-drafter', 'support-triage', 'refund-adjudication',
    'demand-forecast', 'incident-copilot', 'change-validator', 'access-review', 'campaign-copy',
    'expense-audit', 'churn-predictor', 'fraud-detection', 'hr-chatbot', 'defect-vision',
)

# Audit rows are append-only: an UPDATE or DELETE is refused by the database itself.
SQLITE_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log rows cannot be changed'); END",
    "CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log rows cannot be deleted'); END",
)
PG_FUNCTION = (
    "CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$ "
    "BEGIN RAISE EXCEPTION 'audit_log rows cannot be changed or deleted'; END; $$ LANGUAGE plpgsql"
)
PG_TRIGGER = (
    "CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log "
    "FOR EACH ROW EXECUTE FUNCTION audit_log_append_only()"
)


def upgrade() -> None:
    with op.batch_alter_table('agents') as batch:
        batch.add_column(sa.Column('is_demo', sa.Boolean(), nullable=False, server_default=sa.text('0' if op.get_bind().dialect.name == 'sqlite' else 'false')))
        batch.add_column(sa.Column('owner_user_id', sa.String(length=64), nullable=True))
        batch.add_column(sa.Column('backup_owner_user_id', sa.String(length=64), nullable=True))
    agents = sa.table('agents', sa.column('id', sa.String), sa.column('is_demo', sa.Boolean))
    op.execute(agents.update().where(agents.c.id.in_(SEED_AGENT_IDS)).values(is_demo=True))

    op.create_table('notifications',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('org_id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=True),
        sa.Column('kind', sa.String(length=40), nullable=False),
        sa.Column('subject', sa.String(length=300), nullable=False),
        sa.Column('items', sa.JSON(), nullable=True),
        sa.Column('dedupe_key', sa.String(length=200), nullable=False),
        sa.Column('deliveries', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dedupe_key', name='uq_notifications_dedupe'),
    )
    op.create_index('idx_notifications_user', 'notifications', ['user_id', 'read_at'], unique=False)

    op.create_table('registry_settings',
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.JSON(), nullable=True),
        sa.Column('updated_by', sa.String(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('key'),
    )
    op.create_table('ai_runs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('function', sa.String(length=50), nullable=False),
        sa.Column('kind', sa.String(length=50), nullable=True),
        sa.Column('agent_id', sa.String(length=64), nullable=True),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.Column('prompt_version', sa.String(length=20), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('cost_cents', sa.Float(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('reason', sa.String(length=300), nullable=True),
        sa.Column('interactive', sa.Boolean(), nullable=True),
        sa.Column('actor', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_ai_runs_function_created', 'ai_runs', ['function', 'created_at'], unique=False)

    if op.get_bind().dialect.name == 'sqlite':
        for stmt in SQLITE_TRIGGERS:
            op.execute(stmt)
    else:
        op.execute(PG_FUNCTION)
        op.execute(PG_TRIGGER)


def downgrade() -> None:
    if op.get_bind().dialect.name == 'sqlite':
        op.execute("DROP TRIGGER IF EXISTS audit_log_no_update")
        op.execute("DROP TRIGGER IF EXISTS audit_log_no_delete")
    else:
        op.execute("DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log")
        op.execute("DROP FUNCTION IF EXISTS audit_log_append_only()")
    op.drop_index('idx_ai_runs_function_created', table_name='ai_runs')
    op.drop_table('ai_runs')
    op.drop_table('registry_settings')
    op.drop_index('idx_notifications_user', table_name='notifications')
    op.drop_table('notifications')
    with op.batch_alter_table('agents') as batch:
        batch.drop_column('backup_owner_user_id')
        batch.drop_column('owner_user_id')
        batch.drop_column('is_demo')
