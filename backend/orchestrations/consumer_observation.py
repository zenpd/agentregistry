"""Who calls each agent, from its traces. For every agent linked to a Phoenix
project it reads the latest trace sample (the same sample the Diagram tab uses)
and records:

- teams that name themselves with the span attribute consumer.team (or caller.team),
- other registered agents whose traces show a call to this agent by name.

The first time a caller is seen is kept, so the time from an access approval to
the first call can be measured. Counts are for the latest sample, not all time."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from db.base import get_db_session
from db.models import Agent, ObservedConsumer
from shared.logger import get_logger

log = get_logger("orchestrations.consumer_observation")


def _key(name: str) -> str:
    return " ".join(str(name).split()).lower()


def _ts(v: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None


async def observe_consumers(agent_id: str | None = None, trigger: str = "manual", **_: Any) -> dict:
    from api.routers.ops.diagram import _load_agent, _sample

    async with get_db_session() as db:
        q = select(Agent).where(Agent.phoenix_project.is_not(None), Agent.phoenix_project != "")
        agents = (await db.execute(q)).scalars().all()
        everyone = (await db.execute(select(Agent.id, Agent.name))).all()
    if agent_id:
        agents = [a for a in agents if a.id == agent_id]
    if not agents:
        return {"status": "skipped", "reason": "No agent is linked to a Phoenix project."}
    by_name = {_key(n): i for i, n in everyone}
    found: dict[tuple[str, str, str], dict] = {}
    unreachable, read = [], 0
    for a in agents:
        agent, base_url, api_key = await _load_agent(a.id)
        sample = await _sample(agent, base_url, api_key, refresh=True)
        if sample["status"] == "phoenix_unreachable":
            unreachable.append(a.name)
            continue
        read += 1
        for c in sample.get("callers") or []:
            found[(a.id, "team", c["caller"])] = {"calls": c["calls"], "first": _ts(c["firstSeen"]), "last": _ts(c["lastSeen"]), "callerAgentId": None}
        window_end = _ts((sample.get("sampleWindow") or {}).get("to"))
        for o in ((sample.get("observed") or {}).get("agents") or []):
            callee = by_name.get(_key(o["name"]))
            if callee and callee != a.id:
                found[(callee, "agent", a.name)] = {"calls": o["count"], "first": window_end, "last": window_end, "callerAgentId": a.id}
    now = datetime.now(timezone.utc)
    added = 0
    async with get_db_session() as db:
        existing = {(r.agent_id, r.kind, r.caller): r for r in (await db.execute(select(ObservedConsumer))).scalars()}
        for (aid, kind, caller), v in found.items():
            row = existing.get((aid, kind, caller))
            if row is None:
                row = ObservedConsumer(id=secrets.token_hex(8), agent_id=aid, kind=kind, caller=caller, first_seen=v["first"])
                db.add(row)
                added += 1
            elif v["first"] and (row.first_seen is None or v["first"] < row.first_seen):
                row.first_seen = v["first"]
            row.calls, row.caller_agent_id, row.updated_at = v["calls"], v["callerAgentId"], now
            if v["last"]:
                row.last_seen = v["last"]
        # A caller not in this read keeps its first and last call; its count is for the latest read, so it drops to 0.
        read_ids = {a.id for a in agents if a.name not in unreachable}
        for key, row in existing.items():
            if key not in found and (row.agent_id in read_ids or (row.kind == "agent" and row.caller_agent_id in read_ids)):
                row.calls, row.updated_at = 0, now
    status = "ok" if not unreachable else ("partial" if read else "error")
    return {"status": status, "agentsRead": read, "callers": len(found), "newCallers": added,
            **({"reason": f"Phoenix did not answer for {', '.join(unreachable)}."} if unreachable else {})}
