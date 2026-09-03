"""Shared state definitions for AIRegistry LangGraph orchestrations."""
from typing import TypedDict, Optional, Annotated
from langgraph.graph.message import add_messages
import operator


class DiscoveryState(TypedDict):
    """State for the discovery pipeline orchestration."""
    org_id: str
    sources_scanned: Annotated[list[str], operator.add]
    raw_findings: Annotated[list[dict], operator.add]
    validated_findings: Annotated[list[dict], operator.add]
    duplicates_removed: int
    confidence_scores: Annotated[list[dict], operator.add]
    discoveries_created: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    status: str


class GovernanceState(TypedDict):
    """State for the governance review workflow orchestration."""
    agent_id: str
    org_id: str
    current_gate: str
    reviews: dict[str, str]
    notes: dict[str, str]
    all_approved: bool
    changes_requested: bool
    final_decision: str
    notifications_sent: Annotated[list[str], operator.add]


class TokenomicsState(TypedDict):
    """State for the tokenomics analysis orchestration."""
    agent_id: str
    model_name: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    model_input_price: float
    model_output_price: float
    cache_read_price: float
    invocation_count: int
    cost_per_invocation: float
    monthly_cost: float
    budget: float
    budget_usage_pct: float
    anomaly_detected: bool
    anomaly_type: Optional[str]
    suggestions: Annotated[list[str], operator.add]


class WasteDetectionState(TypedDict):
    """State for the waste detection orchestration."""
    org_id: str
    agents_analyzed: Annotated[list[str], operator.add]
    idle_agents: Annotated[list[dict], operator.add]
    overkill_agents: Annotated[list[dict], operator.add]
    duplicate_agents: Annotated[list[dict], operator.add]
    always_on_agents: Annotated[list[dict], operator.add]
    rag_bloat_agents: Annotated[list[dict], operator.add]
    total_waste_cents: int
    findings_saved: Annotated[list[str], operator.add]


class ImpactAnalysisState(TypedDict):
    """State for the impact analysis orchestration."""
    target_node_id: str
    target_node_type: str
    direct_deps: Annotated[list[str], operator.add]
    transitive_deps: Annotated[list[str], operator.add]
    affected_agents: Annotated[list[dict], operator.add]
    revenue_at_risk: int
    efficiency_at_risk: int
    blast_radius_depts: Annotated[list[str], operator.add]
    risk_level: str
    mitigation_suggestions: Annotated[list[str], operator.add]
