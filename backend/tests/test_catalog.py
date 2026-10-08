"""Agent cards: only certified agents are published; a preview shows any card."""
from __future__ import annotations

from types import SimpleNamespace

from api.routers.ops.catalog import agent_card


def test_card_is_built_from_the_record():
    a = SimpleNamespace(id="inv", name="Invoice Agent", description="Matches invoices", business_outcome="", api_endpoint="https://inv.example/api",
                        version="2.1.0", owner="Finance", ai_type="Autonomous Agent", capabilities=["Invoice matching", "Exception routing"],
                        lifecycle_stage="Production", inputs=["Invoice"], outputs=["Match"], sla="99.5%", rate_limit="10/s")
    c = agent_card(a, certified=True)
    assert c["name"] == "Invoice Agent" and c["url"] == "https://inv.example/api" and c["version"] == "2.1.0"
    assert [s["id"] for s in c["skills"]] == ["invoice-matching", "exception-routing"]
    assert c["x-agent-registry"]["certifiedForReuse"] is True and c["documentationUrl"].endswith("/agents/inv")
