"""Daily notifications job: one digest per person of what waits for them,
plus one summary for the shared Teams channel. Demo agents are left out.

Each digest is unique per person per day, so running the job twice sends nothing new."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from api.auth import ROLES
from db.base import get_db_session
from db.models import (Agent, AgentAccessRequest, AgentBudget, AgentRisk, GovernanceReview, PhoenixProject, User)
from governance import costing
from governance import notify_rules as rules
from orchestrations.risk_scan import as_utc
from services import notify
from services.usage_repo import priced_usage
from shared.config import get_settings

ACTIVE_RISK = ("open", "acknowledged", "mitigating")


async def _facts(today: date) -> dict:
    s = get_settings()
    now = notify.utcnow()
    async with get_db_session() as db:
        users = [{"id": u.id, "role": u.role, "name": u.name, "awayUntil": u.away_until, "deputy": u.deputy_user_id}
                 for u in (await db.execute(select(User).where(User.is_active == True))).scalars().all()]  # noqa: E712
        agents = {a.id: a for a in (await db.execute(
            select(Agent).where(Agent.is_demo == False, Agent.lifecycle_stage != "Deprecated"))).scalars().all()}  # noqa: E712
        ids = list(agents)
        reviews, expiring = [], []
        for g in (await db.execute(select(GovernanceReview).where(GovernanceReview.agent_id.in_(ids)))).scalars().all():
            a = agents[g.agent_id]
            if g.status == "In Review":
                reviews.append({"agentId": a.id, "agentName": a.name, "gate": g.gate, "slaDays": s.review_sla_days,
                                "since": as_utc(g.updated_at).date() if g.updated_at else None})
            elif g.status in ("Approved", "Approved with Conditions") and g.expires_at:
                exp = as_utc(g.expires_at)
                if exp <= now + timedelta(days=s.notify_expiry_days):
                    expiring.append({"agentId": a.id, "agentName": a.name, "gate": g.gate, "expiresOn": exp.date(),
                                     "ownerUserId": a.owner_user_id})
        requests = [{"agentId": q.agent_id, "agentName": agents[q.agent_id].name, "team": q.team,
                     "ownerUserId": agents[q.agent_id].owner_user_id}
                    for q in (await db.execute(select(AgentAccessRequest).where(
                        AgentAccessRequest.status == "pending", AgentAccessRequest.agent_id.in_(ids)))).scalars().all()]
        budgets = []
        for b in (await db.execute(select(AgentBudget).where(AgentBudget.agent_id.in_(ids)))).scalars().all():
            if not b.monthly_budget_cents:
                continue
            usage = await priced_usage(db, b.agent_id)
            if usage["source"] not in costing.REAL_SOURCES:
                continue
            mtd = costing.month_to_date_cents(usage["rows"], today, b.budget_reset_day)
            st = costing.budget_status(mtd, b.monthly_budget_cents, b.alert_threshold_pct or 80)
            if st["state"] in ("at_threshold", "over_budget"):
                a = agents[b.agent_id]
                budgets.append({"agentId": a.id, "agentName": a.name, "state": st["state"], "usedPct": st["used_pct"],
                                "ownerUserId": a.owner_user_id})
        linked = {a.phoenix_project for a in agents.values() if a.phoenix_project}
        projects = [{"name": p.name} for p in (await db.execute(select(PhoenixProject).where(
            PhoenixProject.state == "new"))).scalars().all()
            if p.name not in linked and p.first_seen_at and as_utc(p.first_seen_at) >= now - timedelta(days=1)]
        risks = [{"agentId": r.agent_id, "agentName": agents[r.agent_id].name, "title": r.title, "dueDate": r.due_date,
                  "ownerUserId": agents[r.agent_id].owner_user_id}
                 for r in (await db.execute(select(AgentRisk).where(
                     AgentRisk.agent_id.in_(ids), AgentRisk.status.in_(ACTIVE_RISK), AgentRisk.due_date < today))).scalars().all()]
        from api.routers.ops.portfolio import attention_facts
        from governance import attention

        af = await attention_facts(db)
        silent = [{**x, "ownerUserId": agents[x["agentId"]].owner_user_id}
                  for x in attention.silent(af["rows"], af["last"], today) if x["agentId"] in agents]
    return {"users": users, "reviews": reviews, "expiring": expiring, "requests": requests, "budgets": budgets,
            "projects": projects, "risks": risks, "silent": silent}


async def send_daily_notifications(agent_id: str | None = None, trigger: str = "manual", **_) -> dict:
    today = notify.utcnow().date()
    facts = await _facts(today)
    digests = rules.build_digests(today=today, roles=ROLES, **facts)
    sent, delivered = 0, {"sent": 0, "failed": 0, "not_configured": 0, "no_email": 0}
    for user_id, items in digests.items():
        nid = await notify.enqueue(user_id=user_id, kind="digest", subject=rules.digest_subject(items), items=items,
                                   dedupe_key=f"digest:{user_id}:{today.isoformat()}")
        if nid:
            sent += 1
            result = await notify.deliver(nid)
            status = (result.get("email") or {}).get("status")
            if status in delivered:
                delivered[status] += 1
    summary = rules.channel_summary(digests)
    if summary:
        nid = await notify.enqueue(user_id=None, kind="channel_summary", subject="Agent Registry: today's summary",
                                   items=summary, dedupe_key=f"channel:{today.isoformat()}")
        if nid:
            await notify.deliver(nid)
    certification = await certification_notices(today)
    return {"status": "ok", "people": len(digests), "digestsStored": sent, "email": delivered,
            "channels": notify.channels(), "items": sum(len(v) for v in digests.values()), "certificationChanges": certification}


async def certification_notices(today: date) -> dict:
    """Teams with approved access hear when an agent gains or loses its certification
    for reuse. The first run only records the current state."""
    from sqlalchemy.orm import selectinload

    from db.models import AgentAccessRequest
    from services import reuse_repo
    from services.ai_meter import get_setting, set_setting

    async with get_db_session() as db:
        agents = (await db.execute(select(Agent).options(selectinload(Agent.governance_reviews)))).scalars().all()
        certs = await reuse_repo.certifications(db, agents)
        grants = (await db.execute(select(AgentAccessRequest).where(AgentAccessRequest.status == "approved"))).scalars().all()
    now = {a.id: bool(certs[a.id].get("certified")) for a in agents}
    before = await get_setting("reuse.certified")
    await set_setting("reuse.certified", now, "system")
    if not isinstance(before, dict):
        return {"changed": 0, "told": 0, "firstRun": True}
    names = {a.id: a.name for a in agents}
    changed = [aid for aid, c in now.items() if aid in before and before[aid] != c]
    told = 0
    for aid in changed:
        gained = now[aid]
        for g in [g for g in grants if g.agent_id == aid]:
            text = (f"{names[aid]} is now certified for reuse." if gained else
                    f"{names[aid]} is no longer certified for reuse: {', '.join(u['message'] for u in certs[aid].get('unmet', [])[:3]) or 'see its Integrate tab'}.")
            if await notify.notify(user_id=g.requester_id, kind="certification", subject=f"Agent Registry: certification of {names[aid]} changed",
                                   items=[{"type": "certification", "text": f"{text} Your team {g.team} uses it.", "link": f"/agents/{aid}?tab=integrate"}],
                                   dedupe_key=f"certification:{aid}:{g.requester_id}:{today.isoformat()}"):
                told += 1
    return {"changed": len(changed), "told": told}
