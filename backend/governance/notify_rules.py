"""Who is told about what in the daily digest. Pure functions over plain
facts, so the rules are tested without a database.

Recipients by item type:
- review waiting / approval expiring: the people whose role decides that gate,
  or the Registry Admins when nobody holds that role;
- access request, budget, discovered project, overdue risk: the agent's
  owner account when one is linked, and the Registry Admins.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

GATE_LABELS = {"arb": "Architecture Review Board", "security": "Security Review", "dp": "Data Protection Review"}


def deciders(gate: str, users: list[dict], roles: dict[str, dict], admins: list[str]) -> list[str]:
    """Active people whose role decides this gate, Registry Admins excluded; admins when none."""
    found = [u["id"] for u in users if u["role"] != "Registry Admin" and gate in roles.get(u["role"], {}).get("gates", set())]
    return found or list(admins)


def build_digests(*, today: date, users: list[dict], roles: dict[str, dict], reviews: list[dict], expiring: list[dict],
                  requests: list[dict], budgets: list[dict], projects: list[dict], risks: list[dict],
                  silent: list[dict] | None = None) -> dict[str, list[dict]]:
    """user id → list of digest items, each {type, text, link, agentId}."""
    admins = [u["id"] for u in users if u["role"] == "Registry Admin"]
    out: dict[str, list[dict]] = defaultdict(list)

    def to(people, item):
        for p in dict.fromkeys(people):
            out[p].append(item)

    def owners(row) -> list[str]:
        return ([row["ownerUserId"]] if row.get("ownerUserId") else []) + admins

    for r in reviews:
        days = (today - r["since"]).days if r.get("since") else None
        waited = f" for {days} day{'s' if days != 1 else ''}" if days is not None else ""
        late = " It is overdue." if r.get("slaDays") is not None and days is not None and days > r["slaDays"] else ""
        to(deciders(r["gate"], users, roles, admins), {
            "type": "review_waiting", "agentId": r["agentId"], "link": f"/agents/{r['agentId']}?tab=governance",
            "text": f"{r['agentName']}: the {GATE_LABELS.get(r['gate'], r['gate'])} has waited for a decision{waited}.{late}"})
    for e in expiring:
        when = "expired on" if e["expiresOn"] < today else "expires on"
        to(deciders(e["gate"], users, roles, admins) + ([e["ownerUserId"]] if e.get("ownerUserId") else []), {
            "type": "approval_expiring", "agentId": e["agentId"], "link": f"/agents/{e['agentId']}?tab=governance",
            "text": f"{e['agentName']}: the {GATE_LABELS.get(e['gate'], e['gate'])} approval {when} {e['expiresOn'].isoformat()}."})
    for q in requests:
        to(owners(q), {"type": "access_request", "agentId": q["agentId"], "link": "/approvals",
                       "text": f"{q['team']} asked to use {q['agentName']}."})
    for b in budgets:
        state = "is over its monthly budget" if b["state"] == "over_budget" else f"has used {b['usedPct']:.0f}% of its monthly budget"
        to(owners(b), {"type": "budget", "agentId": b["agentId"], "link": f"/agents/{b['agentId']}?tab=tokenomics",
                       "text": f"{b['agentName']} {state}."})
    for p in projects:
        to(admins, {"type": "discovered", "agentId": None, "link": "/discovered",
                    "text": f"Phoenix project {p['name']} sends traces and is not registered."})
    for k in risks:
        to(owners(k), {"type": "risk_overdue", "agentId": k["agentId"], "link": f"/agents/{k['agentId']}?tab=risk",
                       "text": f"{k['agentName']}: risk “{k['title']}” was due on {k['dueDate'].isoformat()}."})
    for q in silent or []:
        to(owners(q), {"type": "silent", "agentId": q["agentId"], "link": f"/agents/{q['agentId']}",
                       "text": f"{q['name']} is in Production but silent: {q['text']}"})
    return route_to_deputies(dict(out), users, today)


def route_to_deputies(digests: dict[str, list[dict]], users: list[dict], today: date) -> dict[str, list[dict]]:
    """Items for someone who is away go to their deputy, marked as such. The away
    person keeps nothing in their digest until they are back."""
    by_id = {u["id"]: u for u in users}
    out: dict[str, list[dict]] = defaultdict(list)
    for uid, items in digests.items():
        u = by_id.get(uid, {})
        away = u.get("awayUntil") and u["awayUntil"] >= today
        deputy = u.get("deputy") if away else None
        if deputy and deputy in by_id:
            out[deputy].extend({**it, "text": f"For {u.get('name') or uid}, who is away until {u['awayUntil'].isoformat()}: {it['text']}"}
                               for it in items)
        else:
            out[uid].extend(items)
    return dict(out)


def digest_subject(items: list[dict]) -> str:
    n = len(items)
    return f"Agent Registry: {n} item{'s' if n != 1 else ''} for you today"


def channel_summary(digests: dict[str, list[dict]]) -> list[dict]:
    """One line per item type across everyone, for the shared Teams channel."""
    seen: dict[tuple, dict] = {}
    for items in digests.values():
        for it in items:
            seen.setdefault((it["type"], it["text"]), it)
    labels = {"review_waiting": "reviews waiting", "approval_expiring": "approvals expiring", "access_request": "access requests",
              "budget": "budget alerts", "discovered": "unregistered projects", "risk_overdue": "overdue risks",
              "silent": "silent Production agents"}
    counts: dict[str, int] = defaultdict(int)
    for (t, _), _it in seen.items():
        counts[t] += 1
    return [{"type": t, "text": f"{c} {labels.get(t, t)}", "link": None} for t, c in counts.items()]
