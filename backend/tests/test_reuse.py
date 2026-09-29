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
    assert cert["certified"] is True and cert["unmet"] == [] and cert["withConditions"] == []
    assert all(c["met"] for c in cert["checks"])


def test_every_check_is_listed_met_or_not_with_the_tab_that_resolves_it():
    reviews = {**APPROVED, "arb": {"status": "In Review"}, "security": {"status": "Not Submitted"}}
    cert = reuse.certification("Ideation", reviews, {**NO_RISK, "HIGH": 2}, NOW)
    checks = {c["key"]: c for c in cert["checks"]}
    assert list(checks) == ["stage", "arb", "security", "dp", "risk"]
    assert [checks[k]["met"] for k in checks] == [False, False, False, True, False]
    assert checks["arb"]["detail"] == "In review, awaiting the reviewer's decision"
    assert checks["security"]["detail"] == "Not submitted for review yet"
    assert checks["dp"]["detail"] == "Approved"
    assert checks["risk"]["detail"].startswith("2 open") and checks["risk"]["tab"] == "risk"
    assert {checks[k]["tab"] for k in ("stage", "arb", "security", "dp")} == {"governance"}
    # The unmet list is the failing checks, in the same order.
    assert len(cert["unmet"]) == sum(not c["met"] for c in cert["checks"])
    assert cert["unmet"][1]["message"] == "Architecture Review Board: in review, awaiting the reviewer's decision"


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
    [dp] = [c for c in cert["checks"] if c["key"] == "dp"]
    assert dp["met"] and dp["conditions"] and dp["detail"] == "Approved with conditions"


# ── contract ─────────────────────────────────────────────────────────────────

def test_contract_gaps_list_what_a_consumer_would_have_to_ask_for():
    gaps = reuse.contract_gaps({"api_endpoint": "https://phoenix.example.com:6006", "inputs": ["x"]})
    assert gaps[0].startswith("The API endpoint is a tracing URL")
    assert "No output described" in gaps and "No input described" not in gaps
    assert reuse.contract_gaps({"api_endpoint": "/a", "inputs": ["x"], "outputs": ["y"], "capabilities": ["c"],
                                "sla": "99%", "rate_limit": "10/s", "owner_contact": "a@b.c"}) == []


@pytest.mark.parametrize("endpoint", [
    "https://payment-orchestrator-fe.example.com/analytics",
    "https://digital-onboarding-fe.example.com/dashboard",
    "https://app.example.com/",
    "https://www.example.com/login",
])
def test_a_web_page_is_flagged_with_where_to_find_the_api(endpoint):
    advice = reuse.endpoint_advice(endpoint)
    assert advice["looksLike"] == "frontend"
    assert "/api/" in advice["message"]
    assert any("openapi.json" in w for w in advice["where"])


def test_a_tracing_url_says_it_belongs_in_the_phoenix_field():
    advice = reuse.endpoint_advice("https://zaf-phoenix.example.com/")
    assert advice["looksLike"] == "tracing" and "Phoenix project field" in advice["message"]


@pytest.mark.parametrize("endpoint", [
    "https://payment-orchestrator-fe.example.com/api/v1/payments",
    "https://onboarding-be.example.com/api/v1/onboard/start",
    "/agents/v1/invoice-reconciliation",
    "https://agent.example.com/v2/run",
])
def test_an_api_endpoint_is_left_alone(endpoint):
    assert reuse.endpoint_advice(endpoint) is None


def test_no_advice_when_there_is_nothing_recorded():
    assert reuse.endpoint_advice("") is None
    assert reuse.endpoint_advice("Not yet built") is None


def test_a_real_backend_host_is_not_told_to_become_one():
    # payment-orchestrator-test-1e343e93's actual recorded endpoint: a real
    # -be host whose path happens to be one of the generic UI words. Without
    # a host check, this used to trip the frontend-page heuristic and then
    # tell the owner to "use the same host with -be instead of -fe" — advice
    # that makes no sense for a host that already says -be.
    assert reuse.endpoint_advice(
        "https://payment-orchestrator-be.bravesky-d9f9eeb7.eastus2.azurecontainerapps.io/analytics") is None
    assert reuse.endpoint_advice("https://onboarding-backend.example.com/overview") is None
    # A -fe host still gets flagged even when a -be host would otherwise be
    # excused by the same path word, and even when it's paired with a -be
    # segment somewhere later in the host (frontend markers win outright).
    assert reuse.endpoint_advice("https://checkout-fe.example.com/reports") is not None


@pytest.mark.parametrize("endpoint,sibling", [
    ("https://digital-onboarding-fe.x.azurecontainerapps.io/dashboard",
     "https://digital-onboarding-be.x.azurecontainerapps.io"),
    ("https://ZenARC-FE.example.com/", "https://zenarc-be.example.com"),
    ("http://shop-fe.internal:8080/home", "http://shop-be.internal:8080"),
    ("https://shop-frontend.example.com/", "https://shop-backend.example.com"),
    ("https://frontend.shop.example.com/", "https://backend.shop.example.com"),
])
def test_a_fe_host_pairs_with_its_be_host(endpoint, sibling):
    assert reuse.backend_sibling(endpoint) == sibling
    advice = reuse.endpoint_advice(endpoint)
    assert advice["suggestedBase"] == sibling and sibling in advice["message"]


def test_advice_points_to_try_it_when_the_be_host_is_known():
    known = reuse.endpoint_advice("https://shop-fe.example.com/dashboard")["where"][0]
    assert "https://shop-be.example.com" in known and "Load API operations" in known
    unknown = reuse.endpoint_advice("https://www.example.com/login")["where"][0]
    assert "Load API operations" not in unknown and "/openapi.json" in unknown


@pytest.mark.parametrize("endpoint", [
    "https://www.example.com/login", "https://app.example.com/", "https://onboarding-be.example.com/dashboard",
    "/dashboard", "", None,
])
def test_no_be_host_is_guessed_without_a_fe_marker(endpoint):
    assert reuse.backend_sibling(endpoint) is None


def test_try_it_defaults_a_web_page_to_its_be_host():
    target = reuse.try_target("https://onboarding-fe.example.com/dashboard", "")
    assert target == {"url": "https://onboarding-fe.example.com/dashboard", "base": "https://onboarding-be.example.com",
                      "path": "/", "backendDefault": True, "pathEditable": True}


def test_try_it_keeps_a_real_api_endpoint_as_recorded():
    target = reuse.try_target("https://pay-be.example.com/analytics?region=eu", "")
    assert target["base"] == "https://pay-be.example.com" and target["path"] == "/analytics?region=eu"
    assert not target["backendDefault"] and target["pathEditable"]
    # Behind the shared agent gateway only the registered path may be called.
    gateway = reuse.try_target("/agents/v1/inv", "https://gw.example.com")
    assert gateway["url"] == "https://gw.example.com/agents/v1/inv" and not gateway["pathEditable"]


def test_a_chosen_path_stays_on_the_target_host():
    base = "https://onboarding-be.example.com"
    assert reuse.join_try_path(base, "/api/v1/onboard/start") == base + "/api/v1/onboard/start"
    assert reuse.join_try_path(base + "/", "/@evil.com?q=1") == base + "/@evil.com?q=1"


@pytest.mark.parametrize("path", ["api/v1/x", "//evil.com/x", "https://evil.com/x", "/a b", "/a\\b", "/a\tb", ""])
def test_a_path_that_could_leave_the_host_is_refused(path):
    with pytest.raises(reuse.TryItBlocked):
        reuse.join_try_path("https://onboarding-be.example.com", path)


SPEC = {
    "info": {"title": "Digital Banking Onboarding API"},
    "paths": {
        "/health": {"get": {"summary": "Health"}},
        "/api/v1/onboard/start": {"post": {
            "summary": "Start onboarding",
            "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Start"}}}},
        }},
        "/api/v1/onboard/{session_id}": {"get": {"operationId": "get_session"}, "delete": {"summary": "Cancel"}},
    },
    "components": {"schemas": {
        "Start": {"type": "object", "properties": {
            "customer_name": {"type": "string"},
            "product": {"type": "string", "enum": ["savings", "current"]},
            "age": {"anyOf": [{"type": "null"}, {"type": "integer"}]},
            "documents": {"type": "array", "items": {"$ref": "#/components/schemas/Doc"}},
            "channel": {"type": "string", "default": "web"},
        }},
        "Doc": {"type": "object", "properties": {"kind": {"type": "string", "example": "passport"}}},
    }},
}


def test_openapi_lists_the_get_and_post_operations_with_a_starting_body():
    found = reuse.openapi_operations(SPEC)
    assert found["title"] == "Digital Banking Onboarding API"
    assert [(o["method"], o["path"]) for o in found["operations"]] == [
        ("GET", "/health"), ("POST", "/api/v1/onboard/start"), ("GET", "/api/v1/onboard/{session_id}"),
    ]
    start = found["operations"][1]
    assert start["summary"] == "Start onboarding" and not start["hasPathParams"]
    assert start["exampleBody"] == {"customer_name": "", "product": "savings", "age": 0,
                                    "documents": [{"kind": "passport"}], "channel": "web"}
    assert found["operations"][2]["hasPathParams"] and found["operations"][2]["summary"] == "get_session"
    # DELETE can't be sent from Try it; it is counted, not silently dropped.
    assert found["otherMethods"] == 1 and found["truncated"] is False


def _post_body(schema, **extra):
    spec = {"paths": {"/a": {"post": {"requestBody": {"content": {"application/json": {"schema": schema}}}}}}, **extra}
    return reuse.openapi_operations(spec)["operations"][0]["exampleBody"]


@pytest.mark.parametrize("schema,expected", [
    # OpenAPI 3.1: a type list, and examples as a list.
    ({"type": "object", "properties": {"n": {"type": ["string", "null"]}}}, {"n": ""}),
    ({"type": "object", "properties": {"x": {"type": "string", "examples": ["hello"]}}}, {"x": "hello"}),
    # allOf composes: every part's fields, not only the first part's.
    ({"allOf": [{"type": "object", "properties": {"a": {"type": "string"}}},
                {"type": "object", "properties": {"b": {"type": "integer"}}}]}, {"a": "", "b": 0}),
    ({"anyOf": [{"type": ["null"]}, {"type": "boolean"}]}, False),
    # Malformed or unusual shapes give an empty start, never an error.
    ({"anyOf": [True]}, None),
    ({"type": "object", "properties": ["x"]}, {}),
    ({"type": 5}, None),
])
def test_starting_body_handles_31_composition_and_malformed_schemas(schema, expected):
    assert _post_body(schema) == expected


def test_a_shared_request_body_is_followed():
    spec = {"paths": {"/a": {"post": {"requestBody": {"$ref": "#/components/requestBodies/B"}}},
                      "/b": {"post": {"requestBody": ["not", "a", "body"]}}},
            "components": {"requestBodies": {"B": {"content": {"application/json": {
                "schema": {"type": "object", "properties": {"x": {"type": "string"}}}}}}}}}
    ops = reuse.openapi_operations(spec)["operations"]
    assert [o["exampleBody"] for o in ops] == [{"x": ""}, None]


def test_a_document_without_paths_is_not_an_openapi_spec():
    with pytest.raises(ValueError):
        reuse.openapi_operations({"hello": "world"})
    with pytest.raises(ValueError):
        reuse.openapi_operations(["not", "a", "dict"])


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
