"""ORM models for Agent Registry domain.

Extends the bootstrap's Session model with the full Agent Registry domain:
agents, departments, governance reviews, discoveries, token usage, budgets,
waste findings, cost anomalies, users, and audit log.
"""
from __future__ import annotations

from datetime import datetime, date
from typing import Optional, List

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, func,
    UniqueConstraint, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    cost_center: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        Index("idx_agents_org_id", "org_id"),
        Index("idx_agents_dept_id", "dept_id"),
        Index("idx_agents_lifecycle_stage", "lifecycle_stage"),
        Index("idx_agents_ai_type", "ai_type"),
        Index("idx_agents_model_name", "model_name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=False)
    dept_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("departments.id"), index=True)

    # Identity
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ai_type: Mapped[str] = mapped_column(String(50), nullable=False, default="Autonomous Agent")
    function: Mapped[Optional[str]] = mapped_column(String(100))
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_contact: Mapped[Optional[str]] = mapped_column(String(255))

    # Lifecycle
    lifecycle_stage: Mapped[str] = mapped_column(String(50), nullable=False, default="Ideation")
    version: Mapped[Optional[str]] = mapped_column(String(50))
    time_in_stage_weeks: Mapped[int] = mapped_column(Integer, default=0)
    at_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_note: Mapped[Optional[str]] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(20), default="LOW")

    # Technical
    model_name: Mapped[Optional[str]] = mapped_column(String(100))
    model_provider: Mapped[Optional[str]] = mapped_column(String(100))
    runtime: Mapped[Optional[str]] = mapped_column(String(100))
    framework: Mapped[Optional[str]] = mapped_column(String(100))
    api_endpoint: Mapped[Optional[str]] = mapped_column(String(500))
    sla: Mapped[Optional[str]] = mapped_column(String(255))
    # Which Phoenix project this agent's real traces are exported under (see
    # discovery/phoenix_client.py) — a human-set link, never guessed from the
    # agent name, since a real deployment's OTel service/project name doesn't
    # reliably match its registry display name (e.g. "retail bank onboarding"
    # vs the real project "retail-onboarding"). NULL means "not linked yet" —
    # the Diagram tab shows a clear empty state for that, not an error.
    phoenix_project: Mapped[Optional[str]] = mapped_column(String(255))
    # Per-agent OVERRIDE of the org-wide common endpoint (PhoenixConfig / the
    # Settings tab) — NULL means "use the common one". Set only when this
    # specific app exports traces to its own Phoenix/OTel collector instead
    # of the shared org instance (the onboarding form's endpoint dropdown).
    phoenix_endpoint: Mapped[Optional[str]] = mapped_column(String(500))
    # Free-form markdown the owner pastes at onboarding time to describe the
    # app in their own words (architecture notes, gotchas, links) — optional,
    # shown verbatim on the agent's own page. Not parsed/validated; it's
    # reference context, not structured data the registry reasons over.
    context_md: Mapped[Optional[str]] = mapped_column(Text)

    # Value
    value_amount: Mapped[int] = mapped_column(Integer, default=0)
    value_type: Mapped[Optional[str]] = mapped_column(String(50))
    hours_saved_monthly: Mapped[int] = mapped_column(Integer, default=0)
    business_outcome: Mapped[Optional[str]] = mapped_column(Text)

    # V2 compliance & policy fields (F-59, F-58, F-67)
    eu_ai_act_category: Mapped[str] = mapped_column(String(32), default="Minimal Risk")
    max_tokens_per_invocation: Mapped[Optional[int]] = mapped_column(Integer)
    batch_processing: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_per_business_outcome: Mapped[Optional[float]] = mapped_column(Float)

    # Metadata (stored as JSON arrays)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    enterprise_systems: Mapped[list] = mapped_column(JSON, default=list)
    databases: Mapped[list] = mapped_column(JSON, default=list)
    knowledge_bases: Mapped[list] = mapped_column(JSON, default=list)
    mcp_servers: Mapped[list] = mapped_column(JSON, default=list)
    calls: Mapped[list] = mapped_column(JSON, default=list)
    consumers: Mapped[list] = mapped_column(JSON, default=list)
    inputs: Mapped[list] = mapped_column(JSON, default=list)
    outputs: Mapped[list] = mapped_column(JSON, default=list)

    # Source tracking
    source: Mapped[str] = mapped_column(String(50), default="manual")
    discovered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    shadow_ai_risk: Mapped[Optional[str]] = mapped_column(String(20))

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deprecated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sunset_date: Mapped[Optional[date]] = mapped_column(Date)

    # Relationships
    governance_reviews: Mapped[List["GovernanceReview"]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    token_usage: Mapped[List["AgentTokenUsage"]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    budget: Mapped[Optional["AgentBudget"]] = relationship(back_populates="agent", cascade="all, delete-orphan", uselist=False)
    identity: Mapped[Optional["AgentIdentity"]] = relationship(back_populates="agent", cascade="all, delete-orphan", uselist=False)


class AgentIdentity(Base):
    __tablename__ = "agent_identities"
    __table_args__ = (
        Index("idx_agent_identities_service_account", "service_account"),
    )

    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), primary_key=True)
    service_account: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    entra_agent_id: Mapped[Optional[str]] = mapped_column(String(255))
    api_key_hash: Mapped[Optional[str]] = mapped_column(String(255))
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    agent: Mapped["Agent"] = relationship(back_populates="identity")


class GovernanceReview(Base):
    __tablename__ = "governance_reviews"
    __table_args__ = (
        Index("idx_governance_reviews_agent_id", "agent_id"),
        Index("idx_governance_reviews_gate", "gate"),
        Index("idx_governance_reviews_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    gate: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="Not Submitted")
    reviewer: Mapped[Optional[str]] = mapped_column(String(255))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    conditions: Mapped[Optional[str]] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    checklist: Mapped[dict] = mapped_column(JSON, default=dict)
    # When the current approval stops counting; NULL until approved.
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    agent: Mapped["Agent"] = relationship(back_populates="governance_reviews")


class GovernanceException(Base):
    __tablename__ = "governance_exceptions"
    __table_args__ = (
        Index("idx_governance_exceptions_agent_id", "agent_id"),
        Index("idx_governance_exceptions_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    gate: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_by: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Discovery(Base):
    __tablename__ = "discoveries"
    __table_args__ = (
        Index("idx_discoveries_status", "status"),
        Index("idx_discoveries_org_id", "org_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=False)
    suspected_name: Mapped[str] = mapped_column(String(255), nullable=False)
    suspected_dept: Mapped[Optional[str]] = mapped_column(String(100))
    suspected_type: Mapped[Optional[str]] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    signal: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    shadow_ai_risk: Mapped[Optional[str]] = mapped_column(String(20))
    registered_agent_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("agents.id"))
    first_seen: Mapped[date] = mapped_column(Date, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentTokenUsage(Base):
    __tablename__ = "agent_token_usage"
    __table_args__ = (
        Index("idx_agent_token_usage_agent_id", "agent_id"),
        Index("idx_agent_token_usage_bucket", "bucket"),
        UniqueConstraint("agent_id", "bucket", "model_name", name="uq_token_usage"),
    )

    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False, primary_key=True)
    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, primary_key=True)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False, primary_key=True)
    invocation_count: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    latency_avg_ms: Mapped[Optional[int]] = mapped_column(Integer)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    iterations_max: Mapped[Optional[int]] = mapped_column(Integer)
    # "phoenix" rows come from real traces; "seed" rows are demo data and are
    # ignored for an agent once it has any phoenix rows.
    source: Mapped[str] = mapped_column(String(20), default="seed")
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    raw_model_names: Mapped[list] = mapped_column(JSON, default=list)
    ingested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    agent: Mapped["Agent"] = relationship(back_populates="token_usage")


class ModelTokenPrice(Base):
    __tablename__ = "model_token_prices"
    __table_args__ = (
        Index("idx_model_token_prices_model_name", "model_name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    input_price_per_1m: Mapped[float] = mapped_column(nullable=False)
    output_price_per_1m: Mapped[float] = mapped_column(nullable=False)
    cache_read_price_per_1m: Mapped[float] = mapped_column(default=0)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    effective_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentBudget(Base):
    __tablename__ = "agent_budgets"
    __table_args__ = (
        Index("idx_agent_budgets_agent_id", "agent_id"),
    )

    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), primary_key=True)
    monthly_budget_cents: Mapped[int] = mapped_column(Integer, default=0)
    alert_threshold_pct: Mapped[int] = mapped_column(Integer, default=80)
    hard_stop_pct: Mapped[int] = mapped_column(Integer, default=100)
    current_month_spend_cents: Mapped[int] = mapped_column(Integer, default=0)
    budget_reset_day: Mapped[int] = mapped_column(Integer, default=1)
    max_tokens_per_invocation: Mapped[Optional[int]] = mapped_column(Integer)
    max_iterations: Mapped[int] = mapped_column(Integer, default=20)
    auto_pause_on_breach: Mapped[bool] = mapped_column(Boolean, default=True)
    last_alert_sent: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    agent: Mapped["Agent"] = relationship(back_populates="budget")


class WasteFinding(Base):
    __tablename__ = "waste_findings"
    __table_args__ = (
        Index("idx_waste_findings_agent_id", "agent_id"),
        Index("idx_waste_findings_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    waste_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    monthly_waste_cents: Mapped[Optional[int]] = mapped_column(Integer)
    recommendation: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="open")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class CostAnomaly(Base):
    __tablename__ = "cost_anomalies"
    __table_args__ = (
        Index("idx_cost_anomalies_agent_id", "agent_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    anomaly_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    details: Mapped[Optional[dict]] = mapped_column(JSON)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[Optional[str]] = mapped_column(String(255))


# The general (non-financial) risk register. Financial risk stays modeled as
# WasteFinding/CostAnomaly above, deliberately not duplicated here — the
# portfolio-wide risk summary endpoint (governance/risks/summary) merges rows
# from all three tables into one categorized view rather than one table
# trying to be everything. Categories are a closed, fixed set (see
# governance/risk_categories.py) — this column is NOT a free-text field a
# caller can invent a new category into.
class AgentRisk(Base):
    __tablename__ = "agent_risks"
    __table_args__ = (
        Index("idx_agent_risks_agent_id", "agent_id"),
        Index("idx_agent_risks_category", "category"),
        Index("idx_agent_risks_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="LOW")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    # How this finding was produced — "auto" findings come from
    # governance/risk_detection.py reading real signals (governance gate
    # status, reconstructed-trace error rates); "manual" ones are hand-added
    # by a reviewer. Never silently overwritten by a re-scan either way — see
    # that module's upsert logic.
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="auto")
    # Lifecycle: open → acknowledged → mitigating → resolved, or accepted
    # (until accepted_until). A re-scan closes auto findings whose condition
    # cleared and reopens resolved ones that reappear (matched by rule_id).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rule_id: Mapped[Optional[str]] = mapped_column(String(100))
    owner: Mapped[Optional[str]] = mapped_column(String(255))
    mitigation: Mapped[Optional[str]] = mapped_column(Text)
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    accepted_until: Mapped[Optional[date]] = mapped_column(Date)
    accepted_by: Mapped[Optional[str]] = mapped_column(String(255))
    last_detected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Append-only list of {at, by, action, note} entries.
    history: Mapped[list] = mapped_column(JSON, default=list)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("idx_users_email", "email"),
        Index("idx_users_org_id", "org_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="Executive Viewer")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_log_org_id", "org_id"),
        Index("idx_audit_log_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String(64))
    changes: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ── Additional Tables ─────────────────────────────────────────────────────────

class PhoenixConfig(Base):
    __tablename__ = "phoenix_config"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=False)
    api_key: Mapped[Optional[str]] = mapped_column(String(255))
    endpoint: Mapped[Optional[str]] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AgentMetric(Base):
    __tablename__ = "agent_metrics"
    __table_args__ = (
        Index("idx_agent_metrics_agent_id", "agent_id"),
        Index("idx_agent_metrics_date", "metric_date"),
        UniqueConstraint("agent_id", "metric_date", name="uq_agent_metrics"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    avg_tokens: Mapped[Optional[float]] = mapped_column(Float)
    total_cost: Mapped[Optional[float]] = mapped_column(Float)
    efficiency: Mapped[Optional[float]] = mapped_column(Float)
    error_rate: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelRouting(Base):
    __tablename__ = "model_routing"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    routing_pct: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ── Agent operations (tokenomics, infra cost, context, jobs) ────────────────

class ModelAlias(Base):
    """Maps a model name as it appears in traces (e.g. gpt-4.1-mini-2025-04-14)
    to the model_token_prices.model_name it is billed as."""
    __tablename__ = "model_aliases"

    alias: Mapped[str] = mapped_column(String(150), primary_key=True)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentInfraProfile(Base):
    """Owner-declared hosting cost — used when no metered cost exists."""
    __tablename__ = "agent_infra_profiles"

    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), primary_key=True)
    platform: Mapped[Optional[str]] = mapped_column(String(100))
    resource_group: Mapped[Optional[str]] = mapped_column(String(255))
    monthly_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    components: Mapped[list] = mapped_column(JSON, default=list)
    effective_from: Mapped[Optional[date]] = mapped_column(Date)
    updated_by: Mapped[Optional[str]] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AgentResourceLink(Base):
    """Links an Azure resource (or resource group) to an agent for metered
    cost allocation when the resource has no agent-id tag, or is shared."""
    __tablename__ = "agent_resource_links"
    __table_args__ = (
        UniqueConstraint("agent_id", "resource_id", name="uq_agent_resource_link"),
        Index("idx_agent_resource_links_agent_id", "agent_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(500), nullable=False)
    share_pct: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentInfraCost(Base):
    """Daily metered infrastructure cost per agent and resource
    (Azure Cost Management)."""
    __tablename__ = "agent_infra_costs"
    __table_args__ = (
        UniqueConstraint("agent_id", "cost_date", "resource_id", name="uq_agent_infra_cost"),
        Index("idx_agent_infra_costs_agent_id", "agent_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    cost_date: Mapped[date] = mapped_column(Date, nullable=False)
    resource_id: Mapped[str] = mapped_column(String(500), nullable=False)
    service_name: Mapped[Optional[str]] = mapped_column(String(150))
    cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    source: Mapped[str] = mapped_column(String(20), default="azure")
    allocation: Mapped[str] = mapped_column(String(20), default="tag")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentContextVersion(Base):
    """Every saved version of an agent's context.md."""
    __tablename__ = "agent_context_versions"
    __table_args__ = (
        Index("idx_agent_context_versions_agent_id", "agent_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    saved_by: Mapped[Optional[str]] = mapped_column(String(255))
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentContextInsight(Base):
    """Cached analysis of one context.md version (rule-based always,
    LLM-assisted when available). Keyed by content hash so it is computed
    once per version."""
    __tablename__ = "agent_context_insights"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    sections: Mapped[dict] = mapped_column(JSON, default=dict)
    completeness_pct: Mapped[int] = mapped_column(Integer, default=0)
    keyword_hits: Mapped[list] = mapped_column(JSON, default=list)
    suggested_risks: Mapped[list] = mapped_column(JSON, default=list)
    suggested_dependencies: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    llm_status: Mapped[str] = mapped_column(String(20), default="not_run")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobRun(Base):
    """One execution of a scheduled or manually triggered job."""
    __tablename__ = "job_runs"
    __table_args__ = (
        Index("idx_job_runs_job_started", "job", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_id: Mapped[Optional[str]] = mapped_column(String(64))
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[Optional[str]] = mapped_column(Text)
