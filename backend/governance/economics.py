"""Revenue-vs-expenditure economics for one agent or the whole portfolio.

Revenue is the agent's own declared `value_amount` ($/mo business value) —
already a first-class field, not invented here. Expenditure is two real
components:
  - token/LLM cost: summed from AgentMetric.total_cost (already computed
    elsewhere in this codebase for cost_per_outcome — reused, not redefined).
  - infra cost: NOT real Azure billing data. This codebase has no Azure Cost
    Management integration, so this is an explicit, clearly-labeled ESTIMATE
    keyed on lifecycle stage (a Production agent presumably runs more
    replicas/compute than an Ideation one sitting in a backlog). Every
    response that includes it says so in the field name
    (`estimatedInfraCostCents`) — never presented as metered fact.
"""

from __future__ import annotations

# Cents/month, by lifecycle stage — a coarse, stated-as-such placeholder for
# real infra billing. Ideation/Development agents aren't deployed yet, so
# they cost nothing to host.
_INFRA_COST_CENTS_BY_STAGE: dict[str, int] = {
    "Ideation": 0,
    "Development": 0,
    "Testing": 2000,      # $20/mo — shared/low-tier hosting
    "Production": 8000,   # $80/mo — dedicated hosting assumption
    "Deprecated": 0,
}


def estimated_infra_cost_cents(stage: str | None) -> int:
    return _INFRA_COST_CENTS_BY_STAGE.get(stage or "", 0)


def agent_economics(
    *, value_amount: int, stage: str | None, token_cost_dollars: float
) -> dict:
    """`value_amount` is $/mo (the existing field, whole dollars).
    `token_cost_dollars` is whatever unit AgentMetric.total_cost is already
    stored in (dollars, matching cost_per_outcome's own usage of that field
    unconverted) — kept as dollars throughout rather than mixed with the
    cents used for infra, converted once at the end for a single consistent
    response shape."""
    infra_cents = estimated_infra_cost_cents(stage)
    token_cents = round(token_cost_dollars * 100)
    expenditure_cents = infra_cents + token_cents
    revenue_cents = value_amount * 100
    return {
        "revenueCents": revenue_cents,
        "tokenCostCents": token_cents,
        "estimatedInfraCostCents": infra_cents,
        "expenditureCents": expenditure_cents,
        "netCents": revenue_cents - expenditure_cents,
    }
