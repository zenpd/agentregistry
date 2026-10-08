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
    # The signed-in account accountable for the agent, when the owner is a person
    # with an account (owner stays the display text: a person or a team name).
    owner_user_id: Mapped[Optional[str]] = mapped_column(String(64))
    # Stands in for the owner when they are away, and inherits the agent if they leave.
    backup_owner_user_id: Mapped[Optional[str]] = mapped_column(String(64))

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
    # Where else this agent is known: its code repository and its cloud resource
    # (set when a person links a connector finding to the record).
    source_repo: Mapped[Optional[str]] = mapped_column(String(500))
    cloud_resource_id: Mapped[Optional[str]] = mapped_column(String(500))
    # A Langfuse connector whose project holds this agent's traces (instead of Phoenix).
    trace_connector_id: Mapped[Optional[str]] = mapped_column(String(64))
    # The certified agent whose contract this one started from, when it did.
    started_from_agent_id: Mapped[Optional[str]] = mapped_column(String(64))
    # How the declared value is worked out: cost_avoidance | revenue_influenced | time_saved | risk_avoided.
    value_method: Mapped[Optional[str]] = mapped_column(String(30))
    value_basis: Mapped[Optional[str]] = mapped_column(Text)
    # For time saved: the hourly rate behind the value, in cents (the blended rate when empty).
    value_hourly_rate_cents: Mapped[Optional[int]] = mapped_column(Integer)
    # Archived: left out of every page, count and job, but kept in the database and can be brought back.
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    archived_reason: Mapped[Optional[str]] = mapped_column(Text)
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
    # What the agent does, as short phrases ("KYC document extraction") —
    # what capability search and the registration duplicate check match on.
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    rate_limit: Mapped[Optional[str]] = mapped_column(String(255))
    # Recorded at registration when similar agents already existed: which
    # ones the registering team was shown, and why none of them fit.
    reuse_checked: Mapped[list] = mapped_column(JSON, default=list)
    reuse_justification: Mapped[Optional[str]] = mapped_column(Text)

    # Source tracking
    source: Mapped[str] = mapped_column(String(50), default="manual")
    # True for the example agents the seed script creates. Portfolio pages leave
    # them out unless the viewer switches them on (db/scope.py).
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
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


class AgentAccessRequest(Base):
    """A team asking to consume an agent. Approval adds the team to the
    agent's consumers, which is what puts it in the dependency graph."""
    __tablename__ = "agent_access_requests"
    __table_args__ = (
        Index("idx_agent_access_requests_agent_id", "agent_id"),
        Index("idx_agent_access_requests_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    requester_id: Mapped[str] = mapped_column(String(64), nullable=False)
    requester_name: Mapped[Optional[str]] = mapped_column(String(255))
    team: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    # pending → approved | rejected; approved → revoked.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    decided_by: Mapped[Optional[str]] = mapped_column(String(255))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[Optional[str]] = mapped_column(Text)
    # True when approval is what added the team to consumers; revoking only
    # removes a consumer entry this request put there, never a declared one.
    added_to_consumers: Mapped[bool] = mapped_column(Boolean, default=False)
    # The agent version this team uses; set at approval to the version current then.
    agent_version: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    # The structural fields the current approval was given for (governance/lifecycle.snapshot).
    approved_snapshot: Mapped[Optional[dict]] = mapped_column(JSON)
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
    # Waiver with two sign-offs: pending until a second person signs. NULL status
    # is an exception recorded before the two-signer rule (counted as active).
    status: Mapped[Optional[str]] = mapped_column(String(20))
    first_signer: Mapped[Optional[str]] = mapped_column(String(255))
    second_signer: Mapped[Optional[str]] = mapped_column(String(255))
    second_signed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


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
    # Away until this date: reviews and notices for this person go to the deputy meanwhile.
    away_until: Mapped[Optional[date]] = mapped_column(Date)
    deputy_user_id: Mapped[Optional[str]] = mapped_column(String(64))
    # For an Auditor: the last day the account can sign in. Every request is logged.
    access_until: Mapped[Optional[date]] = mapped_column(Date)
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
    # Where apps are hosted, with {project} for the Phoenix project name, e.g.
    # https://{project}-be.<env>.azurecontainerapps.io — used to find an app's address.
    app_url_template: Mapped[Optional[str]] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PhoenixProject(Base):
    """One Phoenix project seen by the discovery job: what it is doing, not
    its content. Names and counts only — never prompt or answer text."""
    __tablename__ = "phoenix_projects"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_phoenix_projects_org_name"),
        Index("idx_phoenix_projects_org_id", "org_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="new")  # new | dismissed
    dismiss_reason: Mapped[Optional[str]] = mapped_column(String(500))
    dismissed_by: Mapped[Optional[str]] = mapped_column(String(255))
    span_count: Mapped[int] = mapped_column(Integer, default=0)
    window_days: Mapped[int] = mapped_column(Integer, default=7)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    models: Mapped[Optional[list]] = mapped_column(JSON)
    tools: Mapped[Optional[list]] = mapped_column(JSON)
    mcp_servers: Mapped[Optional[list]] = mapped_column(JSON)
    agent_names: Mapped[Optional[list]] = mapped_column(JSON)
    retrievers: Mapped[Optional[list]] = mapped_column(JSON)
    span_kinds: Mapped[Optional[list]] = mapped_column(JSON)
    attribute_keys: Mapped[Optional[list]] = mapped_column(JSON)
    scan_error: Mapped[Optional[str]] = mapped_column(String(500))
    scanned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # What the last scan read besides names: error spans in the sample, service
    # names, and the values of the trace-attribute convention (agent.owner, ...).
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    service_names: Mapped[Optional[list]] = mapped_column(JSON)
    hints: Mapped[Optional[dict]] = mapped_column(JSON)
    # Triage: who looks at this candidate, by when, and a note.
    assignee_user_id: Mapped[Optional[str]] = mapped_column(String(64))
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    triage_note: Mapped[Optional[str]] = mapped_column(String(1000))


class Insight(Base):
    """One AI-written insight: what an insight agent found, the records it
    cited and how it was produced. Holds registry facts and the agent's
    wording only — never prompt or answer text of another team's agent."""
    __tablename__ = "insights"
    __table_args__ = (
        Index("idx_insights_agent_kind", "agent_id", "kind"),
        Index("idx_insights_org_id", "org_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=False)
    agent_id: Mapped[Optional[str]] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok | unavailable | error | nothing_to_read
    output: Mapped[Optional[dict]] = mapped_column(JSON)
    refs: Mapped[Optional[dict]] = mapped_column(JSON)
    tools_used: Mapped[Optional[list]] = mapped_column(JSON)
    checks: Mapped[Optional[dict]] = mapped_column(JSON)
    model: Mapped[Optional[str]] = mapped_column(String(100))
    prompt_version: Mapped[Optional[str]] = mapped_column(String(20))
    steps: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InsightFeedback(Base):
    __tablename__ = "insight_feedback"
    __table_args__ = (Index("idx_insight_feedback_insight", "insight_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    insight_id: Mapped[str] = mapped_column(String(64), ForeignKey("insights.id"), nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)  # useful | not_useful
    note: Mapped[Optional[str]] = mapped_column(String(1000))
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentFieldUpdate(Base):
    """One field of an agent's record that the registry filled in or corrected
    by itself, with what it was before, what it is based on, and whether a
    person has since undone it. This is the record that makes an automatic
    change visible and reversible."""
    __tablename__ = "agent_field_updates"
    __table_args__ = (Index("idx_agent_field_updates_agent", "agent_id", "field"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    field: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[Optional[dict]] = mapped_column(JSON)       # {"v": <value>} so that "" and [] survive
    new_value: Mapped[Optional[dict]] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(30), nullable=False)   # usage | traces | app_api | address_pattern | ai_draft
    reason: Mapped[Optional[str]] = mapped_column(String(600))
    applied_by: Mapped[str] = mapped_column(String(255), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reverted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reverted_by: Mapped[Optional[str]] = mapped_column(String(255))


class AgentRecordCheck(Base):
    """When the registry last read an agent's evidence to keep its record filled
    in, and for which sources. One row per agent; it decides when to look again."""
    __tablename__ = "agent_record_checks"

    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    link: Mapped[str] = mapped_column(String(800), nullable=False, default="")   # tracing project and address it was read for
    complete: Mapped[bool] = mapped_column(Boolean, default=True)                # every source it has could be read
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)                   # {realCalls, tracesRead, appRead, draftUsed, unread}


class ContentAuditOptIn(Base):
    """An owner's recorded permission for a sample of their agent's trace text
    to be read and judged. Without a row here, trace text is never read."""
    __tablename__ = "content_audit_opt_ins"

    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    opted_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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


class Notification(Base):
    """One message to one person (or, with no user, to the shared Teams channel):
    a daily digest of what waits for them, or an immediate notice such as a
    failed job. Always shown in the in-app inbox; also e-mailed or posted to
    Teams when those channels are configured. deliveries records each attempt."""
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_notifications_dedupe"),
        Index("idx_notifications_user", "user_id", "read_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=False)
    user_id: Mapped[Optional[str]] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(40), nullable=False)          # digest | job_failed | consumer_notice | ...
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    items: Mapped[list] = mapped_column(JSON, default=list)                # [{text, link, agentId, type}]
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    deliveries: Mapped[dict] = mapped_column(JSON, default=dict)           # {email: {status, error, at}, teams: {...}}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class RegistrySetting(Base):
    """A setting an admin changes in the app (not in the environment), with who
    changed it. Keys: ai.switches, ai.monthly_cap_cents, ..."""
    __tablename__ = "registry_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Optional[dict]] = mapped_column(JSON)
    updated_by: Mapped[Optional[str]] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AiRun(Base):
    """One call of the registry's own AI (an insight, Ask, a draft): which
    function, which model and prompt version, tokens, cost and how it ended."""
    __tablename__ = "ai_runs"
    __table_args__ = (Index("idx_ai_runs_function_created", "function", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    function: Mapped[str] = mapped_column(String(50), nullable=False)
    kind: Mapped[Optional[str]] = mapped_column(String(50))
    agent_id: Mapped[Optional[str]] = mapped_column(String(64))
    model: Mapped[Optional[str]] = mapped_column(String(100))
    prompt_version: Mapped[Optional[str]] = mapped_column(String(20))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_cents: Mapped[Optional[float]] = mapped_column(Float)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="ok")      # ok | unavailable | refused
    reason: Mapped[Optional[str]] = mapped_column(String(300))
    interactive: Mapped[bool] = mapped_column(Boolean, default=True)
    actor: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiKey(Base):
    """A key for the registry's own API (CI pipelines, scripts). Shown once at
    issue; only its SHA-256 hash and first characters are stored."""
    __tablename__ = "api_keys"
    __table_args__ = (UniqueConstraint("key_hash", name="uq_api_keys_hash"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, default=list)              # read | register | certify_check
    created_by: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[Optional[str]] = mapped_column(String(255))


class ConnectorConfig(Base):
    """A source the registry reads to find agents: Langfuse, a GitHub
    organisation, an Azure subscription. Read-only. The secret is stored
    encrypted and never returned."""
    __tablename__ = "connector_configs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)          # langfuse | github | azure
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)             # host, orgs, subscriptions, ...
    secret_enc: Mapped[Optional[str]] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[Optional[str]] = mapped_column(String(30))         # ok | failed | not_configured
    last_message: Mapped[Optional[str]] = mapped_column(String(500))
    last_found: Mapped[int] = mapped_column(Integer, default=0)


class ExternalFinding(Base):
    """Something a connector found that may be an agent: a Langfuse project, a
    repository with agent code, a cloud model deployment or agent."""
    __tablename__ = "external_findings"
    __table_args__ = (
        UniqueConstraint("connector_id", "external_id", name="uq_external_findings"),
        Index("idx_external_findings_state", "state"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    connector_id: Mapped[str] = mapped_column(String(64), ForeignKey("connector_configs.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)          # trace_project | code_repo | cloud_deployment | cloud_agent
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(500))
    details: Mapped[dict] = mapped_column(JSON, default=dict)              # signals: frameworks, models, counts, ...
    state: Mapped[str] = mapped_column(String(20), default="new")          # new | dismissed | linked
    dismiss_reason: Mapped[Optional[str]] = mapped_column(String(500))
    linked_agent_id: Mapped[Optional[str]] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ClassificationRecord(Base):
    """One classification of an agent: the answers, the rule-based suggestion with
    its reasons, and the category and risk level a named person confirmed. Every
    record is kept; the latest confirmed one is the agent's classification."""
    __tablename__ = "classification_records"
    __table_args__ = (Index("idx_classification_records_agent", "agent_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="proposed")     # proposed | confirmed | replaced
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    suggested_category: Mapped[str] = mapped_column(String(32), nullable=False)
    suggested_risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[Optional[str]] = mapped_column(String(32))
    risk_level: Mapped[Optional[str]] = mapped_column(String(20))
    note: Mapped[Optional[str]] = mapped_column(Text)
    proposed_by: Mapped[Optional[str]] = mapped_column(String(255))
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(255))
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ApprovedTool(Base):
    """A tool, system, database or knowledge base on the approved list, with a risk
    class. An agent's tool class is the highest class among the tools it declares."""
    __tablename__ = "approved_tools"
    __table_args__ = (UniqueConstraint("name", name="uq_approved_tools_name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), default="mcp")           # mcp | system | database | knowledge_base
    risk_class: Mapped[str] = mapped_column(String(10), default="MEDIUM")  # LOW | MEDIUM | HIGH
    note: Mapped[Optional[str]] = mapped_column(Text)
    added_by: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())


class AgentVersion(Base):
    """A released version of an agent with its changelog and the structural fields
    at release, so a consumer can see what changed between the version it uses and the latest."""
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version", name="uq_agent_versions"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    changelog: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    released_by: Mapped[Optional[str]] = mapped_column(String(255))
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentRetirement(Base):
    """Retiring an agent: checked steps (no traffic for 7 days, consumers told, keys
    revoked, stage set to Deprecated), each recorded with who and when."""
    __tablename__ = "agent_retirements"
    __table_args__ = (Index("idx_agent_retirements_agent", "agent_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="in_progress")  # in_progress | done | cancelled
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    replacement_agent_id: Mapped[Optional[str]] = mapped_column(String(64))
    steps: Mapped[dict] = mapped_column(JSON, default=dict)                 # key → {state, at, by, detail}
    started_by: Mapped[Optional[str]] = mapped_column(String(255))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class EvidenceVerdict(Base):
    """The verdict of one AssureAI evaluation run recorded against an agent: pass or
    fail, the run date and a link. No scores are copied."""
    __tablename__ = "evidence_verdicts"
    __table_args__ = (UniqueConstraint("agent_id", "run_id", name="uq_evidence_verdicts"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    connector_id: Mapped[Optional[str]] = mapped_column(String(64))
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    verdict: Mapped[Optional[str]] = mapped_column(String(20))             # pass | fail | None when not read
    application: Mapped[Optional[str]] = mapped_column(String(255))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    url: Mapped[Optional[str]] = mapped_column(String(500))
    error: Mapped[Optional[str]] = mapped_column(Text)
    recorded_by: Mapped[Optional[str]] = mapped_column(String(255))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ObservedConsumer(Base):
    """A caller of an agent seen in its traces: a team that names itself with the
    span attribute consumer.team, or another registered agent whose traces call
    this one. Refreshed by the daily consumer observation job."""
    __tablename__ = "observed_consumers"
    __table_args__ = (UniqueConstraint("agent_id", "kind", "caller", name="uq_observed_consumers"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)          # team | agent
    caller: Mapped[str] = mapped_column(String(255), nullable=False)
    caller_agent_id: Mapped[Optional[str]] = mapped_column(String(64))
    calls: Mapped[int] = mapped_column(Integer, default=0)                 # in the latest trace sample read
    first_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class SearchLog(Base):
    """A search for agents that found nothing: the signal for a new shared agent."""
    __tablename__ = "search_log"
    __table_args__ = (Index("idx_search_log_at", "at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(64))
    query: Mapped[str] = mapped_column(String(255), nullable=False)
    results: Mapped[int] = mapped_column(Integer, default=0)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ValueAttestation(Base):
    """A finance reviewer's check of an agent's declared value: confirmed as declared,
    or adjusted to another amount, with a note and a date. Every check is kept."""
    __tablename__ = "value_attestations"
    __table_args__ = (Index("idx_value_attestations_agent", "agent_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)        # attested | adjusted
    declared_cents: Mapped[int] = mapped_column(Integer, default=0)        # monthly value declared at the time
    declared_method: Mapped[Optional[str]] = mapped_column(String(30))
    attested_cents: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    attested_by: Mapped[Optional[str]] = mapped_column(String(255))
    attested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentOutcome(Base):
    """A measured business outcome of an agent on one day (for example 120 invoices
    matched), from a CSV file, a webhook or typed in. One row per agent, day and outcome."""
    __tablename__ = "agent_outcomes"
    __table_args__ = (UniqueConstraint("agent_id", "day", "outcome", name="uq_agent_outcomes"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    outcome: Mapped[str] = mapped_column(String(120), nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(20), default="manual")      # csv | webhook | manual
    recorded_by: Mapped[Optional[str]] = mapped_column(String(255))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DecisionChain(Base):
    """The hash chain over decision records in the audit log. Each entry holds the hash
    of one decision row together with the hash of the entry before it, so changing or
    removing any sealed decision breaks every hash after it. Append-only."""
    __tablename__ = "decision_chain"
    __table_args__ = (UniqueConstraint("audit_id", name="uq_decision_chain_audit"),)

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    audit_id: Mapped[int] = mapped_column(Integer, ForeignKey("audit_log.id"), nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sealed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Incident(Base):
    """An incident linked to an agent (from PagerDuty, ServiceNow or entered here), and
    a request to the owner to stop the agent, with the owner's acknowledgement."""
    __tablename__ = "incidents"
    __table_args__ = (Index("idx_incidents_agent", "agent_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="manual")      # pagerduty | servicenow | manual | other
    external_id: Mapped[Optional[str]] = mapped_column(String(120))
    url: Mapped[Optional[str]] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="medium")    # low | medium | high | critical
    status: Mapped[str] = mapped_column(String(20), default="open")        # open | resolved
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[str]] = mapped_column(String(255))
    stop_requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    stop_requested_by: Mapped[Optional[str]] = mapped_column(String(255))
    stop_reason: Mapped[Optional[str]] = mapped_column(Text)
    stop_acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    stop_acknowledged_by: Mapped[Optional[str]] = mapped_column(String(255))
    stop_note: Mapped[Optional[str]] = mapped_column(Text)
