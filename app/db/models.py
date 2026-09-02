"""ORM models for Agent Registry domain.

Extends the bootstrap's Session model with the full Agent Registry domain:
agents, departments, governance reviews, discoveries, token usage, budgets,
waste findings, cost anomalies, users, and audit log.
"""
from __future__ import annotations

from datetime import datetime, date
from typing import Optional, List

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func,
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

    # Value
    value_amount: Mapped[int] = mapped_column(Integer, default=0)
    value_type: Mapped[Optional[str]] = mapped_column(String(50))
    hours_saved_monthly: Mapped[int] = mapped_column(Integer, default=0)
    business_outcome: Mapped[Optional[str]] = mapped_column(Text)

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
    avg_tokens: Mapped[Optional[float]] = mapped_column()
    total_cost: Mapped[Optional[float]] = mapped_column()
    efficiency: Mapped[Optional[float]] = mapped_column()
    error_rate: Mapped[Optional[float]] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelRouting(Base):
    __tablename__ = "model_routing"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    routing_pct: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
