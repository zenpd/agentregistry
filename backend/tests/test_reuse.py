"""governance/reuse.py: search, the duplicate check, certification and the
Try it address rules. Pure, no database."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from governance import reuse

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
APPROVED = {g: {"status": "Approved", "expires_at": NOW + timedelta(days=200)} for g in ("arb", "security", "dp")}
NO_RISK = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}

INV = {"id": "inv", "name": "Invoice Reconciliation Agent", "stage": "Production",
       "description": "Matches incoming vendor invoices against POs and goods-receipt records.",
       "capabilities": ["Invoice matching"], "tags": ["finance"], "api_endpoint": "/agents/v1/inv"}
HR = {"id": "hr", "name": "HR Policy Chatbot", "stage": "Production",
      "description": "Answers employee questions about leave and benefits policy.", "tags": ["hr"]}


# ── words ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("extract", "extraction"), ("invoice", "invoices"), ("reconcile", "reconciliation"),
    ("document", "documents"), ("predict", "prediction"), ("kyc", "kyc"),
])
def test_same_word_joins_forms_of_one_word(a, b):
    assert reuse.same_word(a, b) and reuse.same_word(b, a)


@pytest.mark.parametrize("a,b", [("contract", "control"), ("support", "supplier"), ("compliance", "complaint"),
                                 ("hr", "hrs")])
def test_same_word_keeps_different_words_apart(a, b):
    assert not reuse.same_word(a, b)


def test_tokens_drop_filler_words_and_repeats():
    assert reuse.tokens("An agent that extracts the KYC documents", ["KYC"]) == ["extracts", "kyc", "documents"]


# ── search ───────────────────────────────────────────────────────────────────

def test_search_finds_an_agent_described_in_other_words():
    match = reuse.search_match("reconcile invoices", INV)
    assert match == {"score": 6, "matched": ["reconcile", "invoices"]}


def test_search_needs_half_the_terms():
    # One of three terms is not enough: "invoice" alone must not surface
    # every finance agent for an unrelated three-word query.
    assert reuse.search_match("invoice weather forecast", INV) is None
    assert reuse.search_match("invoice weather", INV) is not None


def test_search_accepts_a_half_typed_word():
    assert reuse.search_match("reconc", INV)["matched"] == ["reconc"]


def test_search_weights_name_and_capabilities_over_description():
    in_capability = reuse.search_match("matching", INV)["score"]
    in_description = reuse.search_match("goods", INV)["score"]
    assert in_capability == 3 and in_description == 1


def test_search_of_only_filler_words_falls_back_to_the_name():
    assert reuse.search_match("agent", INV) is not None
    assert reuse.search_match("agent", HR) is None


def test_empty_search_matches_everything():
    assert reuse.search_match("  ", HR) == {"score": 0, "matched": []}


# ── similar agents ───────────────────────────────────────────────────────────

def test_similar_flags_the_existing_agent_for_the_same_job():
    [match] = reuse.similar_agents(
        {"name": "Invoice Reconciliation Bot", "description": "Matches vendor invoices to purchase orders"}, [INV, HR])
    assert match["id"] == "inv" and match["score"] >= reuse.MIN_OVERLAP
    assert {"invoice", "reconciliation"} <= set(match["matchedTerms"])


def test_similar_ignores_an_unrelated_registration():
    assert reuse.similar_agents({"name": "Weather reporter", "description": "Posts the daily weather"},
                                [INV, HR]) == []


def test_one_shared_word_is_not_a_duplicate():
    assert reuse.similar_agents({"name": "Vendor onboarding", "description": "Collects supplier bank details"},
                                [INV]) == []


def test_a_shared_capability_is_enough():
    [match] = reuse.similar_agents({"name": "AP helper", "capabilities": ["invoice matching"]}, [INV])
    assert match["sharedCapabilities"] == ["invoice matching"]


def test_the_same_endpoint_is_enough():
    [match] = reuse.similar_agents({"name": "Something else", "api_endpoint": "/agents/v1/INV"}, [INV])
    assert match["sameEndpoint"] is True


def test_deprecated_agents_and_the_agent_itself_are_never_suggested():
    candidate = {**INV}
    assert reuse.similar_agents(candidate, [INV]) == []
    assert reuse.similar_agents({**INV, "id": "new"}, [{**INV, "stage": "Deprecated"}]) == []


# ── certification ────────────────────────────────────────────────────────────

def test_production_approved_and_no_high_risk_is_certified():
    cert = reuse.certification("Production", APPROVED, {**NO_RISK, "MEDIUM": 3}, NOW)
    assert cert == {"certified": True, "unmet": [], "withConditions": []}


def test_every_unmet_criterion_is_reported():
    reviews = {**APPROVED, "security": {"status": "In Review"}, "dp": {"status": "Approved",
                                                                       "expires_at": NOW - timedelta(days=1)}}
    cert = reuse.certification("Testing", reviews, {**NO_RISK, "HIGH": 1, "CRITICAL": 1}, NOW)
    assert not cert["certified"]
    assert [(u["code"], u["gate"]) for u in cert["unmet"]] == [
        ("stage", None), ("gate_not_approved", "security"), ("gate_expired", "dp"), ("open_high_risk", None),
    ]
    assert "2 open HIGH or CRITICAL" in cert["unmet"][-1]["message"]


def test_a_missing_gate_counts_as_not_submitted():
    cert = reuse.certification("Production", {"arb": APPROVED["arb"]}, NO_RISK, NOW)
    assert [u["gate"] for u in cert["unmet"]] == ["security", "dp"]


def test_approval_with_conditions_certifies_but_says_so():
    reviews = {**APPROVED, "dp": {"status": "Approved with Conditions", "expires_at": None}}
    cert = reuse.certification("Production", reviews, NO_RISK, NOW)
    assert cert["certified"] and cert["withConditions"] == ["dp"]


# ── contract ─────────────────────────────────────────────────────────────────

def test_contract_gaps_list_what_a_consumer_would_have_to_ask_for():
    gaps = reuse.contract_gaps({"api_endpoint": "https://phoenix.example.com:6006", "inputs": ["x"]})
    assert gaps[0].startswith("The API endpoint is a tracing URL")
    assert "No output described" in gaps and "No input described" not in gaps
    assert reuse.contract_gaps({"api_endpoint": "/a", "inputs": ["x"], "outputs": ["y"], "capabilities": ["c"],
                                "sla": "99%", "rate_limit": "10/s", "owner_contact": "a@b.c"}) == []


def test_example_payload_is_keyed_by_the_declared_inputs():
    assert reuse.example_payload(["Vendor invoice", "PO number"]) == {"vendor_invoice": "", "po_number": ""}
    assert reuse.example_payload([]) == {"input": ""}


# ── Try it ───────────────────────────────────────────────────────────────────

def test_relative_endpoints_need_a_gateway():
    with pytest.raises(reuse.TryItBlocked, match="AGENT_GATEWAY_BASE_URL"):
        reuse.resolve_try_url("/agents/v1/inv", "")
    assert reuse.resolve_try_url("/agents/v1/inv", "https://gw.example.com/") == "https://gw.example.com/agents/v1/inv"


@pytest.mark.parametrize("endpoint,reason", [
    ("", "No API endpoint"),
    ("https://my-phoenix.example.com/v1/traces", "tracing URL"),
    ("Not yet built", "not an http"),
    ("ftp://files.example.com/x", "not an http"),
    ("https://user:pw@agent.example.com/run", "Credentials"),
    ("/agents/v1/x (sunset 2026-09-30)", "spaces"),
])
def test_endpoints_that_cannot_be_called_are_refused(endpoint, reason):
    with pytest.raises(reuse.TryItBlocked, match=reason):
        reuse.resolve_try_url(endpoint, "https://gw.example.com")


@pytest.mark.parametrize("address", ["169.254.169.254", "::ffff:169.254.169.254", "fe80::1%en0", "0.0.0.0",
                                     "224.0.0.1", "240.0.0.1"])
def test_metadata_link_local_and_reserved_addresses_are_refused(address):
    with pytest.raises(reuse.TryItBlocked):
        reuse.check_addresses([address], allow_loopback=True)


def test_loopback_only_in_development_and_private_ranges_always():
    reuse.check_addresses(["127.0.0.1", "::1"], allow_loopback=True)
    with pytest.raises(reuse.TryItBlocked, match="loopback"):
        reuse.check_addresses(["127.0.0.1"], allow_loopback=False)
    reuse.check_addresses(["10.2.3.4", "172.16.0.9", "192.168.1.5", "20.1.2.3"], allow_loopback=False)


def test_one_bad_address_among_many_refuses_the_call():
    with pytest.raises(reuse.TryItBlocked):
        reuse.check_addresses(["20.1.2.3", "169.254.169.254"], allow_loopback=False)
