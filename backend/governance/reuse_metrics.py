"""Reuse: who really uses an agent, reuse figures per agent and unit, the split of a
shared agent's cost across the teams that call it, and programme health.
Pure functions over plain data."""
from __future__ import annotations

from datetime import date, datetime
from statistics import median
from typing import Any, Iterable, Mapping


def _key(name: str) -> str:
    return " ".join(str(name).split()).lower()


# ── Observed consumers ───────────────────────────────────────────────────────

STATUS_TEXT = {
    "both": "Approved and calling",
    "approved_not_calling": "Approved, no call seen",
    "calling_not_approved": "Calling without approval",
    "declared_only": "Declared by the owner, no grant and no call seen",
}


def consumer_view(approved: Iterable[Mapping[str, Any]], declared: Iterable[str], observed: Iterable[Mapping[str, Any]]) -> dict:
    """Each consumer once, matched by name ignoring capitals and spaces.

    approved: [{team, approvedAt}]   declared: [team]   observed: [{caller, kind, calls, firstSeen, lastSeen}]"""
    rows: dict[str, dict] = {}

    def row(name: str) -> dict:
        return rows.setdefault(_key(name), {"name": name, "approved": False, "declared": False, "seen": False, "kind": "team",
                                            "calls": None, "firstSeen": None, "lastSeen": None, "approvedAt": None})

    for g in approved:
        r = row(g["team"])
        r["approved"], r["approvedAt"] = True, g.get("approvedAt")
    for t in declared:
        row(t)["declared"] = True
    for o in observed:
        r = row(o["caller"])
        r.update(seen=True, kind=o.get("kind", "team"), calls=o.get("calls"), firstSeen=o.get("firstSeen"), lastSeen=o.get("lastSeen"),
                 callerAgentId=o.get("callerAgentId"))
    for r in rows.values():
        r["status"] = ("both" if r["approved"] and r["seen"] else "approved_not_calling" if r["approved"]
                       else "calling_not_approved" if r["seen"] else "declared_only")
        r["statusText"] = STATUS_TEXT[r["status"]]
    out = sorted(rows.values(), key=lambda r: (["calling_not_approved", "approved_not_calling", "both", "declared_only"].index(r["status"]),
                                               r["name"].lower()))
    return {"consumers": out,
            "approvedNotCalling": [r["name"] for r in out if r["status"] == "approved_not_calling"],
            "callingNotApproved": [r["name"] for r in out if r["status"] == "calling_not_approved"]}


# ── Reuse figures ────────────────────────────────────────────────────────────

def _day(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def days_to_first_call(approved_at: Any, first_seen: Any) -> int | None:
    """Days from the access approval to the first call seen from that team; None when
    no call is seen, or the first call came before the approval."""
    a, f = _day(approved_at), _day(first_seen)
    if a is None or f is None or f < a:
        return None
    return (f - a).days


def reuse_figures(agents: Iterable[Mapping[str, Any]], grants: Iterable[Mapping[str, Any]],
                  observed: Iterable[Mapping[str, Any]]) -> dict:
    """agents: [{id, name, unit, stage}]  grants: [{agentId, team, approvedAt}]  observed: [{agentId, caller, kind, firstSeen}]

    Reuse rate: Production agents with at least one approved consumer team, out of all Production agents.
    Builds avoided: approved access grants, each a team that uses an existing agent instead of building one.
    Time to first call: median days from approval to the team's first call seen in traces."""
    agents = list(agents)
    grants = list(grants)
    first = {(o["agentId"], _key(o["caller"])): o.get("firstSeen") for o in observed if o.get("kind", "team") == "team"}
    per_agent: dict[str, dict] = {a["id"]: {"agentId": a["id"], "name": a["name"], "unit": a.get("unit") or "No unit",
                                            "stage": a.get("stage"), "buildsAvoided": 0, "daysToFirstCall": []} for a in agents}
    for g in grants:
        if g["agentId"] not in per_agent:
            continue
        p = per_agent[g["agentId"]]
        p["buildsAvoided"] += 1
        d = days_to_first_call(g.get("approvedAt"), first.get((g["agentId"], _key(g["team"]))))
        if d is not None:
            p["daysToFirstCall"].append(d)

    def summary(items: list[dict]) -> dict:
        prod = [p for p in items if p["stage"] == "Production"]
        reused = [p for p in prod if p["buildsAvoided"] > 0]
        days = [d for p in items for d in p["daysToFirstCall"]]
        return {"productionAgents": len(prod), "reusedAgents": len(reused),
                "reuseRate": round(100 * len(reused) / len(prod)) if prod else None,
                "buildsAvoided": sum(p["buildsAvoided"] for p in items),
                "medianDaysToFirstCall": median(days) if days else None, "firstCallsMeasured": len(days)}

    units: dict[str, list[dict]] = {}
    for p in per_agent.values():
        units.setdefault(p["unit"], []).append(p)
    agents_out = [{**{k: v for k, v in p.items() if k != "daysToFirstCall"},
                   "medianDaysToFirstCall": median(p["daysToFirstCall"]) if p["daysToFirstCall"] else None}
                  for p in per_agent.values()]
    return {"total": summary(list(per_agent.values())),
            "byUnit": sorted(({"unit": u, **summary(items)} for u, items in units.items()), key=lambda x: -x["buildsAvoided"]),
            "agents": sorted(agents_out, key=lambda x: (-x["buildsAvoided"], x["name"].lower()))}


# ── Chargeback ───────────────────────────────────────────────────────────────

def chargeback(cost_cents: float, owner_unit: str, approved_teams: Iterable[str], calls_by_team: Mapping[str, int]) -> dict:
    """Split one agent's cost for a period.

    With calls seen from approved teams: each approved team pays its share of the calls
    seen, and the owner's unit pays the share of calls from no approved team.
    With no calls seen: the cost is split equally between the owner's unit and the approved teams.
    Without approved teams the owner's unit pays everything."""
    teams = list(dict.fromkeys(t for t in approved_teams if t and _key(t) != _key(owner_unit)))
    if not teams:
        return {"basis": "owner_only", "basisText": "No approved consumer team, so the owner's unit pays all of it.",
                "shares": [{"payer": owner_unit, "share": 100, "cents": round(cost_cents)}]}
    seen = {t: int(calls_by_team.get(_key(t), 0)) for t in teams}
    total_calls = sum(int(v) for v in calls_by_team.values())
    if sum(seen.values()) > 0:
        shares = {t: seen[t] / total_calls for t in teams}
        shares[owner_unit] = 1 - sum(shares.values())
        basis, text = "calls", f"By calls seen in traces: {total_calls} calls, {sum(seen.values())} from approved teams."
    else:
        each = 1 / (len(teams) + 1)
        shares = {**{t: each for t in teams}, owner_unit: each}
        basis, text = "equal", "No calls from approved teams are seen in traces, so the cost is split equally with the owner's unit."
    rows = [{"payer": p, "share": round(100 * s, 1), "cents": round(cost_cents * s)} for p, s in shares.items() if s > 0]
    return {"basis": basis, "basisText": text, "shares": sorted(rows, key=lambda r: -r["cents"])}


# ── Programme health ─────────────────────────────────────────────────────────

def approval_speed(decisions: Iterable[Mapping[str, Any]]) -> dict:
    """decisions: [{submittedAt, decidedAt}] for gate decisions. Median days and count."""
    days = [(_day(d["decidedAt"]) - _day(d["submittedAt"])).days for d in decisions
            if _day(d.get("submittedAt")) and _day(d.get("decidedAt")) and _day(d["decidedAt"]) >= _day(d["submittedAt"])]
    return {"medianDays": median(days) if days else None, "decisions": len(days)}


def coalesce_search(previous: Mapping[str, Any] | None, query: str, seconds_since: float | None) -> bool:
    """Whether a new search continues the person's previous one (typing on): the same
    person within 60 seconds, and one text starts with the other."""
    if not previous or seconds_since is None or seconds_since > 60:
        return False
    a, b = _key(previous["query"]), _key(query)
    return a.startswith(b) or b.startswith(a)
