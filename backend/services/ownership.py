"""Who is accountable for an agent: transfer, a backup owner, and what happens
when an owner's account is deactivated (the backup takes over; without one the
agent becomes an orphan and the admins are told)."""
from __future__ import annotations

from sqlalchemy import or_, select

from db.base import get_db_session
from db.models import Agent, AuditLog, User
from services import notify


async def transfer(agent_id: str, *, owner_user_id: str | None, backup_user_id: str | None, owner_text: str | None,
                   actor: str, reason: str = "") -> dict:
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise LookupError("Agent not found")
        people = {}
        for uid in {u for u in (owner_user_id, backup_user_id) if u}:
            user = await db.get(User, uid)
            if user is None or not user.is_active:
                raise ValueError("The owner and the backup owner must be active users.")
            people[uid] = user
        if owner_user_id and owner_user_id == backup_user_id:
            raise ValueError("The backup owner must be a different person.")
        before = {"owner": agent.owner, "ownerUserId": agent.owner_user_id, "backupOwnerUserId": agent.backup_owner_user_id}
        if owner_user_id is not None or owner_text is not None:
            agent.owner_user_id = owner_user_id or None
            agent.owner = people[owner_user_id].name if owner_user_id else (owner_text or "").strip() or agent.owner
        if backup_user_id is not None:
            agent.backup_owner_user_id = backup_user_id or None
        after = {"owner": agent.owner, "ownerUserId": agent.owner_user_id, "backupOwnerUserId": agent.backup_owner_user_id}
        db.add(AuditLog(org_id="org-default", actor=actor, action="ownership.transfer", entity_type="agent", entity_id=agent_id,
                        changes={"before": before, "after": after, **({"reason": reason} if reason else {})}))
        name = agent.name
        new_owner = agent.owner_user_id if agent.owner_user_id != before["ownerUserId"] else None
    if new_owner:
        await notify.notify(user_id=new_owner, kind="ownership", subject=f"Agent Registry: you now own {name}",
                            items=[{"type": "ownership", "text": f"You are now the accountable owner of {name}.", "link": f"/agents/{agent_id}"}],
                            dedupe_key=f"ownership:{agent_id}:{new_owner}:{notify.utcnow().isoformat()[:16]}")
    return after


async def on_deactivated(user_id: str, actor: str) -> dict:
    """The person can no longer sign in: their agents go to the backup owner, or become orphans."""
    moved, orphaned = [], []
    async with get_db_session() as db:
        agents = (await db.execute(select(Agent).where(or_(Agent.owner_user_id == user_id, Agent.backup_owner_user_id == user_id)))).scalars().all()
        for a in agents:
            if a.backup_owner_user_id == user_id:
                a.backup_owner_user_id = None
            if a.owner_user_id != user_id:
                continue
            backup = await db.get(User, a.backup_owner_user_id) if a.backup_owner_user_id else None
            if backup is not None and backup.is_active:
                before = a.owner
                a.owner_user_id, a.owner, a.backup_owner_user_id = backup.id, backup.name, None
                db.add(AuditLog(org_id="org-default", actor="system", action="ownership.transfer", entity_type="agent", entity_id=a.id,
                                changes={"before": {"owner": before, "ownerUserId": user_id}, "after": {"owner": backup.name, "ownerUserId": backup.id},
                                         "reason": "The owner's account was deactivated; the backup owner took over."}))
                moved.append({"agentId": a.id, "name": a.name, "to": backup.id})
            else:
                orphaned.append({"agentId": a.id, "name": a.name})
    for m in moved:
        await notify.notify(user_id=m["to"], kind="ownership", subject=f"Agent Registry: you now own {m['name']}",
                            items=[{"type": "ownership", "text": f"You took over {m['name']} as its backup owner: its owner's account was deactivated.",
                                    "link": f"/agents/{m['agentId']}"}], dedupe_key=f"ownership:{m['agentId']}:{m['to']}:deactivation")
    if orphaned:
        items = [{"type": "orphan", "text": f"{o['name']} has no owner: its owner's account was deactivated and no backup was set.",
                  "link": f"/agents/{o['agentId']}"} for o in orphaned]
        for admin in await notify.admins():
            await notify.notify(user_id=admin, kind="orphans", subject="Agent Registry: agents without an owner", items=items,
                                dedupe_key=f"orphans:{user_id}:{admin}")
    return {"moved": moved, "orphaned": orphaned}


async def orphans(db) -> list[dict]:
    """Agents nobody answers for: no owner, or an owner account that is no longer active."""
    inactive = set((await db.execute(select(User.id).where(User.is_active == False))).scalars())  # noqa: E712
    out = []
    for a in (await db.execute(select(Agent).where(Agent.lifecycle_stage != "Deprecated"))).scalars():
        if not (a.owner or "").strip() or a.owner.strip().lower() == "unassigned":
            out.append({"agentId": a.id, "name": a.name, "text": "No accountable owner is recorded."})
        elif a.owner_user_id and a.owner_user_id in inactive:
            out.append({"agentId": a.id, "name": a.name, "text": f"The owner {a.owner} can no longer sign in."})
    return out
