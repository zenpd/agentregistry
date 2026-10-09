"""Matching discovered projects to records, project hygiene, owner guesses,
and the lifecycle attention signals."""
from __future__ import annotations

from datetime import date

from governance import attention, identity

AGENTS = [
    {"id": "dig", "slug": "digital-onboarding", "name": "Digital Onboarding", "owner": "Retail CX",
     "apiEndpoint": "https://retail-onboarding-be.example.io/api", "modelName": "gpt-4.1-mini", "mcpServers": ["kyc", "ocr", "crm"]},
    {"id": "iso", "slug": "iso-mapper", "name": "Iso Mapper", "owner": "Payments", "apiEndpoint": "", "modelName": "gpt-4.1",
     "mcpServers": []},
]


def test_strongest_key_wins_and_names_alone_are_only_medium():
    m = identity.matches({"name": "retail-onboarding", "serviceNames": [], "models": [], "tools": []}, AGENTS)
    assert m[0]["agentId"] == "dig" and m[0]["confidence"] == "high" and "API address" in m[0]["reason"]
    m = identity.matches({"name": "iso mapper v2", "serviceNames": [], "models": [], "tools": []}, AGENTS)
    assert m[0]["agentId"] == "iso" and m[0]["confidence"] == "medium"
    m = identity.matches({"name": "x", "serviceNames": [], "models": ["gpt-4.1-mini"], "tools": ["kyc", "ocr"]}, AGENTS)
    assert m[0]["confidence"] == "low"
    assert identity.matches({"name": "unrelated-thing", "serviceNames": [], "models": [], "tools": []}, AGENTS) == []


def test_owner_from_spans_beats_owner_of_a_match():
    best = {"name": "Digital Onboarding", "owner": "Retail CX", "confidence": "high"}
    assert identity.owner_guess({"hints": {"agent.owner": "Card Ops"}}, best)["value"] == "Card Ops"
    assert identity.owner_guess({"hints": {}}, best) == {"value": "Retail CX", "confidence": "medium",
                                                         "reason": "Owner of the matching record Digital Onboarding."}
    assert identity.owner_guess({}, None) is None


def test_hygiene_and_evaluation_projects():
    codes = {h["code"] for h in identity.hygiene({"name": "default", "serviceNames": ["a", "b"], "spanCount": 100, "errorCount": 30})}
    assert codes == {"default_project", "several_services", "high_errors"}
    assert identity.is_evaluation_project("Experiment-3fa9c21b") and not identity.is_evaluation_project("experiments-team")


def test_attention_signals():
    today = date(2026, 10, 8)
    agents = [{"id": "p1", "name": "Live", "stage": "Production", "linked": True, "calls": ["old"]},
              {"id": "p2", "name": "Never", "stage": "Production", "linked": True, "calls": []},
              {"id": "p3", "name": "Unlinked", "stage": "Production", "linked": False, "calls": []},
              {"id": "old", "name": "Old", "stage": "Deprecated", "linked": True, "calls": [], "deprecatedOn": "2026-09-01"}]
    s = attention.silent(agents, {"p1": date(2026, 9, 28), "p2": None}, today)
    assert [x["agentId"] for x in s] == ["p2", "p1"] and s[1]["days"] == 10
    assert attention.running_after_retirement(agents, {"old": 42})[0]["calls"] == 42
    assert attention.calls_retired(agents)[0]["retiredName"] == "Old"
