"""catch up the schema with the models (tables and columns added without migrations)

Before this revision, 12 tables and 19 columns existed only in the models
(create_all made them in development), so a database built by Alembic alone
was incomplete. Generated from the models against a database at 0002, keeping
only creations: nothing is dropped, and added columns are nullable so
existing rows stay valid.

Revision ID: 0002a_catch_up_schema
Revises: 0002_agent_registry
Create Date: 2026-10-08 11:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0002a_catch_up_schema'
down_revision = '0002_agent_registry'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('job_runs',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('job', sa.String(length=64), nullable=False),
    sa.Column('agent_id', sa.String(length=64), nullable=True),
    sa.Column('trigger', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('summary', sa.JSON(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('job_runs', schema=None) as batch_op:
        batch_op.create_index('idx_job_runs_job_started', ['job', 'started_at'], unique=False)

    op.create_table('model_aliases',
    sa.Column('alias', sa.String(length=150), nullable=False),
    sa.Column('model_name', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('alias')
    )
    op.create_table('phoenix_config',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('org_id', sa.String(length=64), nullable=False),
    sa.Column('api_key', sa.String(length=255), nullable=True),
    sa.Column('endpoint', sa.String(length=500), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('agent_access_requests',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('agent_id', sa.String(length=64), nullable=False),
    sa.Column('requester_id', sa.String(length=64), nullable=False),
    sa.Column('requester_name', sa.String(length=255), nullable=True),
    sa.Column('team', sa.String(length=255), nullable=False),
    sa.Column('purpose', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('decided_by', sa.String(length=255), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.Column('added_to_consumers', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('agent_access_requests', schema=None) as batch_op:
        batch_op.create_index('idx_agent_access_requests_agent_id', ['agent_id'], unique=False)
        batch_op.create_index('idx_agent_access_requests_status', ['status'], unique=False)

    op.create_table('agent_context_insights',
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('agent_id', sa.String(length=64), nullable=False),
    sa.Column('sections', sa.JSON(), nullable=False),
    sa.Column('completeness_pct', sa.Integer(), nullable=False),
    sa.Column('keyword_hits', sa.JSON(), nullable=False),
    sa.Column('suggested_risks', sa.JSON(), nullable=False),
    sa.Column('suggested_dependencies', sa.JSON(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('llm_status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.PrimaryKeyConstraint('content_hash')
    )
    op.create_table('agent_context_versions',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('agent_id', sa.String(length=64), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('saved_by', sa.String(length=255), nullable=True),
    sa.Column('saved_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('agent_context_versions', schema=None) as batch_op:
        batch_op.create_index('idx_agent_context_versions_agent_id', ['agent_id'], unique=False)

    op.create_table('agent_infra_costs',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('agent_id', sa.String(length=64), nullable=False),
    sa.Column('cost_date', sa.Date(), nullable=False),
    sa.Column('resource_id', sa.String(length=500), nullable=False),
    sa.Column('service_name', sa.String(length=150), nullable=True),
    sa.Column('cost_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=10), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('allocation', sa.String(length=20), nullable=False),
    sa.Column('ingested_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('agent_id', 'cost_date', 'resource_id', name='uq_agent_infra_cost')
    )
    with op.batch_alter_table('agent_infra_costs', schema=None) as batch_op:
        batch_op.create_index('idx_agent_infra_costs_agent_id', ['agent_id'], unique=False)

    op.create_table('agent_infra_profiles',
    sa.Column('agent_id', sa.String(length=64), nullable=False),
    sa.Column('platform', sa.String(length=100), nullable=True),
    sa.Column('resource_group', sa.String(length=255), nullable=True),
    sa.Column('monthly_cost_cents', sa.Integer(), nullable=False),
    sa.Column('components', sa.JSON(), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=True),
    sa.Column('updated_by', sa.String(length=255), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.PrimaryKeyConstraint('agent_id')
    )
    op.create_table('agent_metrics',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('agent_id', sa.String(length=64), nullable=False),
    sa.Column('metric_date', sa.Date(), nullable=False),
    sa.Column('avg_tokens', sa.Float(), nullable=True),
    sa.Column('total_cost', sa.Float(), nullable=True),
    sa.Column('efficiency', sa.Float(), nullable=True),
    sa.Column('error_rate', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('agent_id', 'metric_date', name='uq_agent_metrics')
    )
    with op.batch_alter_table('agent_metrics', schema=None) as batch_op:
        batch_op.create_index('idx_agent_metrics_agent_id', ['agent_id'], unique=False)
        batch_op.create_index('idx_agent_metrics_date', ['metric_date'], unique=False)

    op.create_table('agent_resource_links',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('agent_id', sa.String(length=64), nullable=False),
    sa.Column('resource_id', sa.String(length=500), nullable=False),
    sa.Column('share_pct', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('agent_id', 'resource_id', name='uq_agent_resource_link')
    )
    with op.batch_alter_table('agent_resource_links', schema=None) as batch_op:
        batch_op.create_index('idx_agent_resource_links_agent_id', ['agent_id'], unique=False)

    op.create_table('agent_risks',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('agent_id', sa.String(length=64), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=False),
    sa.Column('severity', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rule_id', sa.String(length=100), nullable=True),
    sa.Column('owner', sa.String(length=255), nullable=True),
    sa.Column('mitigation', sa.Text(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('accepted_until', sa.Date(), nullable=True),
    sa.Column('accepted_by', sa.String(length=255), nullable=True),
    sa.Column('last_detected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('history', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('agent_risks', schema=None) as batch_op:
        batch_op.create_index('idx_agent_risks_agent_id', ['agent_id'], unique=False)
        batch_op.create_index('idx_agent_risks_category', ['category'], unique=False)
        batch_op.create_index('idx_agent_risks_status', ['status'], unique=False)

    op.create_table('model_routing',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('agent_id', sa.String(length=64), nullable=False),
    sa.Column('tier', sa.String(length=20), nullable=False),
    sa.Column('model_name', sa.String(length=100), nullable=False),
    sa.Column('routing_pct', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('agent_budgets', schema=None) as batch_op:
        batch_op.create_index('idx_agent_budgets_agent_id', ['agent_id'], unique=False)

    with op.batch_alter_table('agent_identities', schema=None) as batch_op:
        batch_op.create_index('idx_agent_identities_service_account', ['service_account'], unique=False)

    with op.batch_alter_table('agent_token_usage', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('run_count', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('raw_model_names', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('ingested_at', sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('phoenix_project', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('phoenix_endpoint', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('context_md', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('eu_ai_act_category', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('max_tokens_per_invocation', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('batch_processing', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('cost_per_business_outcome', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('capabilities', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('rate_limit', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('reuse_checked', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('reuse_justification', sa.Text(), nullable=True))
        batch_op.create_index(batch_op.f('ix_agents_dept_id'), ['dept_id'], unique=False)

    with op.batch_alter_table('departments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_departments_org_id'), ['org_id'], unique=False)

    with op.batch_alter_table('governance_reviews', schema=None) as batch_op:
        batch_op.add_column(sa.Column('conditions', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('evidence', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('checklist', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index('idx_users_email', ['email'], unique=False)


def downgrade() -> None:
    raise NotImplementedError("0002a only adds missing schema; restore from a backup to go below it.")
