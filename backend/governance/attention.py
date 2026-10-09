"""Lifecycle signals across the portfolio, from usage the registry already
stores. Pure functions.

- silent: a Production agent linked to tracing with no call for SILENT_DAYS days;
- running after retirement: a Deprecated agent with calls after it was retired;
- calls a retired agent: an agent whose record says it calls a Deprecated agent."""
from __future__ import annotations

from datetime import date

SILENT_DAYS = 7


def silent(agents: list[dict], last_call: dict[str, date | None], today: date, days: int = SILENT_DAYS) -> list[dict]:
    out = []
    for a in agents:
        if a["stage"] != "Production" or not a.get("linked"):
            continue
        last = last_call.get(a["id"])
        if last is None or (today - last).days >= days:
            out.append({"agentId": a["id"], "name": a["name"], "lastCall": last.isoformat() if last else None,
                        "days": (today - last).days if last else None,
                        "text": (f"No call for {(today - last).days} days (last on {last.isoformat()})." if last
                                 else "No call recorded since it was linked to tracing.")})
    return sorted(out, key=lambda x: -(x["days"] or 10_000))


def running_after_retirement(agents: list[dict], calls_since: dict[str, int]) -> list[dict]:
    out = []
    for a in agents:
        n = calls_since.get(a["id"], 0)
        if a["stage"] == "Deprecated" and n > 0:
            out.append({"agentId": a["id"], "name": a["name"], "calls": n,
                        "text": f"{n} call{'s' if n != 1 else ''} after it was retired on {a.get('deprecatedOn') or 'an unknown date'}."})
    return out


def calls_retired(agents: list[dict]) -> list[dict]:
    retired = {a["id"]: a for a in agents if a["stage"] == "Deprecated"}
    by_name = {a["name"].lower(): a for a in retired.values()}
    out = []
    for a in agents:
        if a["stage"] == "Deprecated":
            continue
        for target in a.get("calls") or []:
            hit = retired.get(target) or by_name.get(str(target).lower())
            if hit:
                out.append({"agentId": a["id"], "name": a["name"], "retiredId": hit["id"], "retiredName": hit["name"],
                            "text": f"{a['name']} is declared to call {hit['name']}, which is retired."})
    return out
