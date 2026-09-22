"""Identify and consume: how a team finds an agent it can reuse instead of
building a new one, and what it needs to call it. Pure functions only; the
database side is services/reuse_repo.py.

Certified for reuse is derived, never stored: Production stage, every
governance gate approved and unexpired, and nothing HIGH or CRITICAL on the
Risk tab. Deriving it from the same gate and risk data the Governance and
Risk tabs show means the badge can never disagree with them.
"""
from __future__ import annotations

import ipaddress
import os
import re
from datetime import datetime
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from governance.gate_policy import APPROVED_STATUSES, GATES, endpoint_kind, gate_expiry_state

CERTIFIED_STAGE = "Production"
BLOCKING_SEVERITIES = frozenset({"HIGH", "CRITICAL"})
NOT_REUSABLE_STAGES = frozenset({"Deprecated"})

_WORD = re.compile(r"[a-z0-9]+")
# Words that say nothing about what an agent does. "agent" is here because
# nearly every registered name contains it.
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "for", "to", "of", "in", "on", "with", "by", "from", "that", "this",
    "which", "who", "what", "does", "do", "is", "are", "be", "it", "its", "as", "at", "into", "i", "we",
    "our", "need", "needs", "want", "find", "any", "all", "can", "will", "using", "use", "uses", "based",
    "per", "via", "new", "existing", "agent", "agents", "application", "applications", "app", "apps",
    "e", "g", "eg", "etc", "about", "against", "over", "under", "across", "between", "before", "after",
    "when", "where", "how", "than", "then", "not", "no", "also", "more", "most", "very", "only", "each",
    "every", "other", "their", "them", "they", "has", "have", "so", "if", "up", "out",
})

# Weight of a query term by the best field it matched in.
SEARCH_FIELDS: tuple[tuple[str, int], ...] = (
    ("name", 3), ("capabilities", 3), ("tags", 2), ("description", 1),
    ("business_outcome", 1), ("inputs", 1), ("outputs", 1), ("ai_type", 1),
)
SIMILARITY_FIELDS = ("name", "capabilities", "description", "business_outcome", "tags")
MIN_SHARED_TERMS = 2
MIN_OVERLAP = 0.5
SIMILAR_LIMIT = 5


# ── Words ────────────────────────────────────────────────────────────────────

def tokens(*values: Any) -> list[str]:
    """Distinct meaningful words, in order of first appearance. Accepts
    strings and lists of strings."""
    out: list[str] = []
    for value in values:
        items = value if isinstance(value, (list, tuple)) else [value]
        for item in items:
            for word in _WORD.findall(str(item or "").lower()):
                if len(word) < 2 or word in _STOPWORDS or word in out:
                    continue
                out.append(word)
    return out


def same_word(a: str, b: str) -> bool:
    """Two forms of one word: extract/extraction, invoice/invoices,
    reconcile/reconciliation. A shared prefix of at least five letters and
    three quarters of the shorter word keeps contract/control apart."""
    if a == b:
        return True
    shorter = min(len(a), len(b))
    if shorter < 5:
        return False
    common = len(os.path.commonprefix([a, b]))
    return common >= 5 and common >= 0.75 * shorter


def term_matches(query: str, word: str) -> bool:
    """Search matching: also accepts a word the query is the start of, so a
    half-typed term keeps finding results."""
    return word.startswith(query) or same_word(query, word)


# ── Search (identify) ────────────────────────────────────────────────────────

def search_match(query: str, agent: Mapping[str, Any]) -> dict | None:
    """{score, matched} when the agent answers the query, else None.

    A term counts once, at the weight of the best field it matched. At least
    half the query's terms must match, so a natural phrase ("extract KYC
    documents") still finds an agent described in other words, while one
    common word alone does not match every agent."""
    raw = (query or "").strip().lower()
    if not raw:
        return {"score": 0, "matched": []}
    terms = tokens(raw)
    if not terms:
        # Only filler words ("agent"): fall back to a plain name search.
        return {"score": 1, "matched": []} if raw in str(agent.get("name") or "").lower() else None
    field_words = {f: tokens(agent.get(f)) for f, _ in SEARCH_FIELDS}
    score, matched = 0, []
    for term in terms:
        best = max((w for f, w in SEARCH_FIELDS if any(term_matches(term, t) for t in field_words[f])), default=0)
        if best:
            score += best
            matched.append(term)
    if len(matched) < max(1, (len(terms) + 1) // 2):
        return None
    return {"score": score, "matched": matched}


# ── Similar agents (identify, at registration) ──────────────────────────────

def _phrase_covered(phrase: list[str], words: list[str]) -> bool:
    return bool(phrase) and all(any(same_word(p, w) for w in words) for p in phrase)


def similar_agents(candidate: Mapping[str, Any], agents: Iterable[Mapping[str, Any]],
                   limit: int = SIMILAR_LIMIT) -> list[dict]:
    """Existing agents that already seem to do what the candidate describes.

    Flagged when a declared capability is shared, the API endpoint is the
    same, or at least two meaningful words are shared and they make up half
    of the shorter description."""
    cand_terms = tokens(*(candidate.get(f) for f in SIMILARITY_FIELDS))
    cand_caps = [tokens(c) for c in candidate.get("capabilities") or []]
    cand_endpoint = (candidate.get("api_endpoint") or "").strip().lower()
    out = []
    for agent in agents:
        if agent.get("id") == candidate.get("id") or agent.get("stage") in NOT_REUSABLE_STAGES:
            continue
        words = tokens(*(agent.get(f) for f in SIMILARITY_FIELDS))
        agent_caps = [tokens(c) for c in agent.get("capabilities") or []]
        shared_caps = sorted({
            " ".join(p) for p in cand_caps
            if any(_phrase_covered(p, c) or _phrase_covered(c, p) for c in agent_caps)
        })
        matched = [t for t in cand_terms if any(same_word(t, w) for w in words)]
        overlap = len(matched) / min(len(cand_terms), len(words)) if cand_terms and words else 0.0
        same_endpoint = bool(cand_endpoint) and cand_endpoint == (agent.get("api_endpoint") or "").strip().lower()
        if not (shared_caps or same_endpoint or (len(matched) >= MIN_SHARED_TERMS and overlap >= MIN_OVERLAP)):
            continue
        out.append({
            "id": agent.get("id"), "name": agent.get("name"), "stage": agent.get("stage"),
            "owner": agent.get("owner"), "description": agent.get("description"),
            "score": round(min(1.0, overlap + 0.25 * len(shared_caps) + (0.5 if same_endpoint else 0)), 2),
            "matchedTerms": matched, "sharedCapabilities": shared_caps, "sameEndpoint": same_endpoint,
        })
    out.sort(key=lambda m: (-m["score"], m["name"] or ""))
    return out[:limit]


# ── Certified for reuse ──────────────────────────────────────────────────────

def _unmet(code: str, message: str, gate: str | None = None) -> dict:
    return {"code": code, "gate": gate, "message": message}


def certification(stage: str | None, reviews: Mapping[str, Mapping[str, Any]],
                  risk_counts: Mapping[str, int], now: datetime) -> dict:
    """{certified, unmet, withConditions}. reviews: gate -> {status,
    expires_at}. risk_counts: severity -> count of active findings, as the
    Risk tab scores them (stored findings plus live financial ones)."""
    unmet = []
    if stage != CERTIFIED_STAGE:
        unmet.append(_unmet("stage", f"Stage is {stage or 'not set'}; only Production agents are certified"))
    with_conditions = []
    for gate, label in GATES.items():
        review = reviews.get(gate) or {}
        status = review.get("status") or "Not Submitted"
        if status not in APPROVED_STATUSES:
            unmet.append(_unmet("gate_not_approved", f"{label} is {status}", gate))
        elif gate_expiry_state(review, now) == "expired":
            unmet.append(_unmet("gate_expired", f"{label} approval has expired", gate))
        elif status == "Approved with Conditions":
            with_conditions.append(gate)
    blocking = sum(int(risk_counts.get(s) or 0) for s in BLOCKING_SEVERITIES)
    if blocking:
        unmet.append(_unmet("open_high_risk", f"{blocking} open HIGH or CRITICAL risk finding(s)"))
    return {"certified": not unmet, "unmet": unmet, "withConditions": with_conditions}


# ── Contract (consume) ───────────────────────────────────────────────────────

_ENDPOINT_GAP = {
    "missing": "No API endpoint recorded",
    "observability": "The API endpoint is a tracing URL (e.g. Phoenix), not the agent's own API",
    "invalid": "The API endpoint is not an http(s) URL or a path",
}


def contract_gaps(agent: Mapping[str, Any]) -> list[str]:
    """What a consuming team would still have to ask the owner for."""
    gaps = []
    kind = endpoint_kind(agent.get("api_endpoint"))
    if kind != "app":
        gaps.append(_ENDPOINT_GAP[kind])
    if not agent.get("inputs"):
        gaps.append("No input described")
    if not agent.get("outputs"):
        gaps.append("No output described")
    if not agent.get("capabilities"):
        gaps.append("No capabilities listed, so search can only find this agent by its name and description")
    if not (agent.get("sla") or "").strip():
        gaps.append("No SLA recorded")
    if not (agent.get("rate_limit") or "").strip():
        gaps.append("No rate limit recorded")
    if not (agent.get("owner_contact") or "").strip():
        gaps.append("No owner contact recorded")
    return gaps


MAX_LIST_ITEMS = 30
MAX_ITEM_CHARS = 120


def clean_list(values: Iterable[Any]) -> list[str]:
    """Trimmed, whitespace-collapsed, case-insensitively de-duplicated.
    Raises ValueError past MAX_LIST_ITEMS entries or MAX_ITEM_CHARS each."""
    out: list[str] = []
    for value in values:
        item = " ".join(str(value).split())
        if not item:
            continue
        if len(item) > MAX_ITEM_CHARS:
            raise ValueError(f"'{item[:40]}…' is longer than {MAX_ITEM_CHARS} characters")
        if item.lower() not in {o.lower() for o in out}:
            out.append(item)
    if len(out) > MAX_LIST_ITEMS:
        raise ValueError(f"At most {MAX_LIST_ITEMS} entries per list")
    return out


def example_payload(inputs: Iterable[str] | None) -> dict[str, str]:
    """A starting request body keyed by the declared inputs."""
    keys = [re.sub(r"[^a-z0-9]+", "_", str(i).lower()).strip("_") for i in inputs or []]
    keys = [k for k in keys if k]
    return {k: "" for k in keys} or {"input": ""}


# ── Try it: where the call may go ────────────────────────────────────────────

class TryItBlocked(ValueError):
    """The call is refused before any request is made; the message says why."""


def resolve_try_url(endpoint: str | None, gateway_base: str | None) -> str:
    value = (endpoint or "").strip()
    kind = endpoint_kind(value)
    if kind != "app":
        raise TryItBlocked(_ENDPOINT_GAP[kind])
    if value.startswith("/"):
        base = (gateway_base or "").strip().rstrip("/")
        if not base:
            raise TryItBlocked("The endpoint is a relative path and no agent gateway base URL is "
                               "configured (AGENT_GATEWAY_BASE_URL)")
        value = base + value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise TryItBlocked("The endpoint is not an http(s) URL")
    if parsed.username or parsed.password:
        raise TryItBlocked("Credentials embedded in the endpoint URL are not allowed")
    if any(ch.isspace() for ch in value):
        raise TryItBlocked("The endpoint contains spaces, so it is not a callable URL")
    return value


def check_addresses(addresses: Iterable[str], allow_loopback: bool) -> None:
    """Refuses cloud metadata, link-local, multicast and reserved addresses,
    and loopback outside development. Private ranges stay allowed: internal
    agents normally live on them."""
    for raw in addresses:
        ip = ipaddress.ip_address(str(raw).split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        # Loopback first: Python also counts ::1 as reserved.
        if ip.is_loopback:
            if not allow_loopback:
                raise TryItBlocked(f"The endpoint resolves to {ip} (loopback), which is only allowed in development")
            continue
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise TryItBlocked(f"The endpoint resolves to {ip}, a link-local or reserved address")
