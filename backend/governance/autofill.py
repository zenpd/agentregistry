"""What the registry may fill in or correct on an agent's record by itself,
and when. Pure rules: no database, no network, no model.

The aim is that nobody is told "go and type this in" for something the
registry can see for itself. The limits are just as deliberate:

- Only the fields in FIELD_LABELS are ever touched. An owner, a business
  outcome, a value, a budget, a service level, a review decision and a stage
  are things only a person can give, and are never set here.
- Facts come from evidence, not from a model: the model name from real usage,
  tools and knowledge sources from traces, the contract from the app's own
  API document. A model is used only to draft a description or capabilities
  for a record that has none, and that draft has to cite what it saw.
- Text is filled in only where the field is empty. Nothing a person wrote is
  overwritten.
- A field a person has taken back is left alone for good: if someone undoes an
  automatic update, or edits the field afterwards (emptying it counts), the
  registry does not touch that field again. The two lists read from traces are
  the exception in one direction only: newly seen tools are still added, and
  anything a person removed is never added back.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence

from discovery import observed_deps
from governance import reuse
from governance.gate_policy import canonical_model

FIELD_LABELS: dict[str, str] = {
    "model_name": "Model",
    "mcp_servers": "Tools and MCP servers",
    "knowledge_bases": "Knowledge bases",
    "api_endpoint": "API endpoint",
    "description": "Description",
    "capabilities": "Capabilities",
    "inputs": "Inputs",
    "outputs": "Outputs",
}
LIST_FIELDS = frozenset({"mcp_servers", "knowledge_bases", "capabilities", "inputs", "outputs"})
SOURCE_LABELS: dict[str, str] = {
    "usage": "its real usage",
    "traces": "its traces",
    "app_api": "the app's own API description",
    "address_pattern": "the address pattern in Settings",
    "ai_draft": "an AI draft from its traces",
}
# What only a person can give. Listed for the page and for the insight agents; never set automatically.
ONLY_A_PERSON = ("an accountable owner", "the department", "the business outcome", "the declared value and hours saved",
                 "a budget", "a service level", "the EU AI Act tier", "review decisions", "the lifecycle stage")

MIN_REAL_CALLS = 5          # fewer calls than this is too little to correct a declared model
MIN_TOP_SHARE = 0.6         # the most-used model must carry this share of the calls
MIN_APP_DESCRIPTION = 20
DRAFT_DESCRIPTION = (30, 400)
MAX_LIST = 12
MAX_ITEM = 120


@dataclass(frozen=True)
class Past:
    """An earlier automatic update to one field (newest first in a history)."""
    field: str
    old: Any
    new: Any
    reverted: bool = False


def blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple)):
        return not [v for v in value if str(v).strip()]
    return False


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).lower()


def same(a: Any, b: Any) -> bool:
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        return [_norm(x) for x in (a or [])] == [_norm(x) for x in (b or [])]
    return _norm(a) == _norm(b)


def taken_back(field: str, history: Sequence[Past]) -> bool:
    """A person undid an automatic update to this field: it is theirs now."""
    return any(p.field == field and p.reverted for p in history)


def edited_since(field: str, current: Any, history: Sequence[Past]) -> bool:
    """The value no longer equals what the registry last put there, so a person changed it."""
    latest = next((p for p in history if p.field == field and not p.reverted), None)
    return latest is not None and not same(current, latest.new)


def owned_by_person(field: str, current: Any, history: Sequence[Past]) -> bool:
    """A person undid what the registry put in this field, or changed it afterwards (emptying it
    counts). Either way it is theirs, and the registry leaves it alone from then on."""
    return taken_back(field, history) or edited_since(field, current, history)


def _clean_list(values: Any, limit: int = MAX_LIST) -> list[str]:
    out: list[str] = []
    for value in values or []:
        item = " ".join(str(value).split()).rstrip(".")
        if not item or reuse.is_plumbing(item):
            continue
        if len(item) > MAX_ITEM:
            item = item[: MAX_ITEM - 1].rstrip() + "…"
        if _norm(item) not in {_norm(o) for o in out}:
            out.append(item)
    return out[:limit]


def _update(field: str, old: Any, new: Any, source: str, reason: str) -> dict:
    return {"field": field, "old": old, "new": new, "source": source, "reason": reason[:600]}


def _family(name: Any, aliases: Mapping) -> str:
    """A model name reduced to its family: case, separators and a trailing release date
    (2025-04-14 or 20250929) do not make it a different model."""
    text = re.sub(r"[^a-z0-9]", "", canonical_model(str(name or ""), aliases).lower())
    return re.sub(r"20\d{6}$", "", text)


def _plan_model(record: Mapping, evidence: Mapping, history: Sequence[Past]) -> list[dict]:
    declared = record.get("model_name")
    if owned_by_person("model_name", declared, history):
        return []
    aliases = evidence.get("aliases") or {}
    counted = [(m, int(c or 0)) for m, c in evidence.get("usage_models") or [] if int(c or 0) > 0]
    used = [(m, c) for m, c in counted if m and m != "unknown"]
    total = sum(c for _, c in counted)                        # calls whose model is unknown still count against the share
    if not used or sum(c for _, c in used) < MIN_REAL_CALLS:
        return []
    if not blank(declared) and any(_family(m, aliases) == _family(declared, aliases) for m, _ in used):
        return []                                             # the declared model is in use: nothing to correct
    top, top_calls = max(used, key=lambda pair: pair[1])
    if top_calls / total < MIN_TOP_SHARE:
        return []                                             # no single model clearly in use
    days = evidence.get("usage_days") or 30
    was = f"none used the declared {declared}" if not blank(declared) else "the record named no model"
    return [_update("model_name", declared, top, "usage",
                    f"{top_calls} of its {total} real calls in the last {days} days used {top}; {was}.")]


def _times(count: Any) -> str:
    n = int(count or 0)
    return "once" if n == 1 else f"{n} times"


def _plan_dependencies(record: Mapping, evidence: Mapping, history: Sequence[Past]) -> list[dict]:
    out = []
    for field in ("mcp_servers", "knowledge_bases"):
        if taken_back(field, history):
            continue
        current = list(record.get(field) or [])
        # Something the registry added before and a person has since removed is not added again.
        added_before = {_norm(x) for p in history if p.field == field
                        for x in (p.new or []) if _norm(x) not in {_norm(y) for y in (p.old or [])}}
        seen = [o for o in evidence.get("observed_only") or []
                if observed_deps.ADOPT_FIELD.get(str(o.get("kind") or "").lower()) == field
                and _norm(o.get("name")) not in added_before]
        if not seen:
            continue
        plan = observed_deps.adopt_items({field: current}, [{"name": o["name"], "kind": o["kind"]} for o in seen])
        if field not in plan["fields"]:
            continue
        names = {_norm(a["name"]) for a in plan["added"]}
        times = ", ".join(f"{o['name']} ({_times(o.get('count'))})" for o in seen if _norm(o["name"]) in names)
        out.append(_update(field, current, plan["fields"][field], "traces",
                           f"Seen in its traces but not on the record: {times}."))
    return out


def _plan_from_app(record: Mapping, evidence: Mapping, history: Sequence[Past]) -> list[dict]:
    app = evidence.get("app") or {}
    out = []
    def free(field: str) -> bool:                             # empty, and not emptied by a person
        return blank(record.get(field)) and not owned_by_person(field, record.get(field), history)

    if app.get("via") == "pattern" and app.get("url") and free("api_endpoint"):
        out.append(_update("api_endpoint", record.get("api_endpoint"), app["url"], "address_pattern",
                           "An app answered with its API description at the address pattern from Settings for this agent's Phoenix project."))
    text = " ".join(str(app.get("description") or "").split())
    if len(text) >= MIN_APP_DESCRIPTION and free("description"):
        out.append(_update("description", record.get("description"), text[:2000], "app_api",
                           "Taken from the description the app publishes in its own API document; none had been entered."))
    reasons = {
        "capabilities": "Taken from the operations in the app's own API document; none had been entered.",
        "inputs": "Taken from the request fields in the app's own API document; none had been entered.",
        "outputs": "Taken from the response fields in the app's own API document; none had been entered.",
    }
    for field, reason in reasons.items():
        values = _clean_list(app.get(field))
        if values and free(field):
            out.append(_update(field, list(record.get(field) or []), values, "app_api", reason))
    return out


def _plan_from_draft(record: Mapping, evidence: Mapping, history: Sequence[Past], already: set[str]) -> list[dict]:
    draft = evidence.get("draft") or {}
    out = []
    text = " ".join(str(draft.get("description") or "").split())
    low, high = DRAFT_DESCRIPTION
    def free(field: str) -> bool:
        return field not in already and blank(record.get(field)) and not owned_by_person(field, record.get(field), history)

    if low <= len(text) <= high and free("description"):
        out.append(_update("description", record.get("description"), text, "ai_draft",
                           "Drafted by AI from the steps and tools in its traces, because no description had been entered."))
    values = _clean_list(draft.get("capabilities"), limit=8)
    if values and free("capabilities"):
        out.append(_update("capabilities", list(record.get("capabilities") or []), values, "ai_draft",
                           "Drafted by AI from the steps in its traces, because no capabilities had been entered."))
    return out


def plan_updates(record: Mapping[str, Any], evidence: Mapping[str, Any], history: Sequence[Past] = ()) -> list[dict]:
    """The updates to apply now: [{field, old, new, source, reason}]. Empty when
    the evidence is too thin, the record is already right, or a person owns the field."""
    updates = [*_plan_model(record, evidence, history), *_plan_dependencies(record, evidence, history),
               *_plan_from_app(record, evidence, history)]
    updates += _plan_from_draft(record, evidence, history, {u["field"] for u in updates})
    return [u for u in updates if u["field"] in FIELD_LABELS and not same(u["old"], u["new"])]


def needs_draft(record: Mapping[str, Any], evidence: Mapping[str, Any], history: Sequence[Past] = ()) -> bool:
    """Is there still an empty description or capability list that only a draft could fill?"""
    planned = {u["field"] for u in plan_updates(record, {**evidence, "draft": None}, history)}
    return any(blank(record.get(f)) and f not in planned and not owned_by_person(f, record.get(f), history)
               for f in ("description", "capabilities"))


def undo_value(field: str, current: Any, old: Any, new: Any) -> tuple[bool, Any, str | None]:
    """(possible, value to restore, why not). A list loses only what was added and is still there;
    anything a person added since is kept. A single value is restored only if nobody changed it since."""
    if field in LIST_FIELDS:
        before = {_norm(x) for x in (old or [])}
        added = {_norm(x) for x in (new or [])} - before
        kept = [x for x in (current or []) if _norm(x) not in added]
        if len(kept) == len(current or []):
            return False, current, "What was added has already been removed."
        return True, kept, None
    if not same(current, new):
        return False, current, "This field was changed after the automatic update, so there is nothing to undo. Edit it directly."
    return True, old, None


REVIEW_LABELS = {"arb": "Architecture", "security": "Security", "dp": "Data Protection"}


def missing_from_person(facts: Mapping[str, Any]) -> list[dict]:
    """What only a person can give and this record does not have yet, most important first:
    [{key, label, why}]. Worked out from the record, so it is exact and reads the same everywhere.
    facts: owner, dept_id, business_outcome, value_amount, hours_saved_monthly, has_budget, sla,
    reviews {gate: status}."""
    out: list[dict] = []

    def need(key: str, label: str, why: str) -> None:
        out.append({"key": key, "label": label, "why": why})

    if blank(facts.get("owner")) or _norm(facts.get("owner")) == "unassigned":
        need("owner", "An accountable owner", "Nobody is named as answerable for this agent.")
    if blank(facts.get("business_outcome")):
        need("business_outcome", "The business outcome", "The record does not say what result this agent is for.")
    if not (facts.get("value_amount") or 0):                  # hours saved alone give no return on cost
        need("value", "The declared value", "No monthly value or hours saved is entered, so return on cost cannot be worked out.")
    reviews = facts.get("reviews") or {}
    waiting = [label for gate, label in REVIEW_LABELS.items() if (reviews.get(gate) or "Not Submitted") == "Not Submitted"]
    if waiting:
        need("reviews", "Review submissions", f"Not submitted yet: {', '.join(waiting)}.")
    if not facts.get("has_budget"):
        need("budget", "A monthly budget", "Spend is tracked but not checked against a limit.")
    if blank(facts.get("sla")):
        need("sla", "A service level", "Teams that want to reuse it cannot see what availability to expect.")
    if blank(facts.get("dept_id")):
        need("department", "The department", "It does not appear under any business unit.")
    return out


def display(field: str, value: Any) -> str:
    if blank(value):
        return "empty"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)
