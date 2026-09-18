"""context.md persistence: versions, the cached insight per content hash,
and the confirm/dismiss flow for suggestions.

The document is stored and analysed as data only. Suggestions never change
anything until a person confirms one.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Agent, AgentContextInsight, AgentContextVersion, AgentRisk, AuditLog, GovernanceReview,
)
from governance import context_reader as cr
from governance.risk_lifecycle import history_entry
from shared.config import get_settings
from shared.logger import get_logger

log = get_logger("services.context")

LLM_TIMEOUT_S = 15
RULE_PREFIX = "context."
SECRET_VALUE_LABEL = "Secret-like value"

# Serialises context writes: two first views of an agent (overview + context
# requests fired together) would otherwise both insert version 1 / the insight row.
_write_lock = asyncio.Lock()


class SuggestionNotFound(LookupError):
    pass


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def _present(content: str | None) -> bool:
    return bool((content or "").strip())


# ── Versions ────────────────────────────────────────────────────────────────

async def list_versions(db: AsyncSession, agent_id: str) -> list[AgentContextVersion]:
    result = await db.execute(
        select(AgentContextVersion)
        .where(AgentContextVersion.agent_id == agent_id)
        .order_by(AgentContextVersion.saved_at.desc(), AgentContextVersion.id.desc())
    )
    return list(result.scalars().all())


async def latest_version(db: AsyncSession, agent_id: str) -> AgentContextVersion | None:
    versions = await list_versions(db, agent_id)
    return versions[0] if versions else None


async def get_version(db: AsyncSession, agent_id: str, version_id: str) -> AgentContextVersion | None:
    version = await db.get(AgentContextVersion, version_id)
    return version if version and version.agent_id == agent_id else None


def version_to_dict(v: AgentContextVersion, include_content: bool = False) -> dict:
    out = {
        "id": v.id,
        "savedAt": _iso(v.saved_at),
        "savedBy": v.saved_by,
        "sizeBytes": v.size_bytes,
        "hash": v.content_hash,
        "removed": not _present(v.content),
    }
    if include_content:
        out["content"] = v.content
    return out


def _new_version(agent_id: str, content: str, saved_by: str) -> AgentContextVersion:
    return AgentContextVersion(
        id=secrets.token_hex(8), agent_id=agent_id, content_hash=content_hash(content), content=content,
        size_bytes=len(content.encode("utf-8")), saved_by=saved_by, saved_at=_now(),
    )


async def ensure_initial_version(db: AsyncSession, agent: Agent) -> None:
    """Records agents.context_md as a version when no version holds it yet:
    registrations through POST /agents and edits through PUT /agents/{id}
    set the column without creating a version."""
    if not _present(agent.context_md):
        return
    current = content_hash(agent.context_md)
    latest = await latest_version(db, agent.id)
    if latest and latest.content_hash == current:
        return
    async with _write_lock:
        latest = await latest_version(db, agent.id)
        if latest and latest.content_hash == current:
            return
        db.add(_new_version(agent.id, agent.context_md, "registration" if latest is None else "agent profile edit"))
        await db.commit()


# ── Analysis ────────────────────────────────────────────────────────────────

def _llm_client():
    """(OpenAI client, deployment) from llm_client configured by Settings, or
    None when Azure OpenAI is not configured."""
    from llm_client import LLMClient

    settings = get_settings()
    llm = LLMClient()
    llm.endpoint, llm.api_key = settings.azure_openai_endpoint, settings.azure_openai_api_key
    llm.deployment, llm.api_version = settings.azure_openai_deployment, settings.azure_openai_api_version
    client = llm._get_client()
    if client is None:
        return None
    return client.with_options(timeout=LLM_TIMEOUT_S, max_retries=0), llm.deployment


async def _llm_summary(content: str) -> tuple[str | None, str]:
    """(summary, llm_status). Status: ok | disabled | not_configured | unavailable."""
    if not get_settings().context_llm_enabled:
        return None, "disabled"
    configured = _llm_client()
    if configured is None:
        return None, "not_configured"
    client, deployment = configured
    system, user = cr.llm_messages(content)

    def complete() -> str:
        resp = client.chat.completions.create(
            model=deployment,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
            max_tokens=400,
        )
        return resp.choices[0].message.content or ""

    try:
        raw = await asyncio.to_thread(complete)
    except Exception as exc:
        log.warning("context.llm_unavailable", error=type(exc).__name__)
        return None, "unavailable"
    summary = cr.clean_summary(raw)
    return (summary, "ok") if summary else (None, "unavailable")


def _dismissed_map(row: AgentContextInsight | None) -> dict[str, list[str]]:
    sections = (row.sections if row else None) or {}
    return dict(sections.get("dismissed") or {})


def _parsed_sections(row: AgentContextInsight) -> dict[str, str]:
    return dict((row.sections or {}).get("parsed") or {})


async def gate_statuses(db: AsyncSession, agent_id: str) -> dict[str, str]:
    """Gate -> status; an approval past its expiry does not count as Approved."""
    now = _now()
    statuses = {}
    for r in (await db.execute(select(GovernanceReview).where(GovernanceReview.agent_id == agent_id))).scalars():
        status = r.status
        expires = r.expires_at.replace(tzinfo=r.expires_at.tzinfo or timezone.utc) if r.expires_at else None
        if status == "Approved" and expires and expires < now:
            status = "Approved (expired)"
        statuses[r.gate] = status
    return statuses


async def _risk_suggestions(db: AsyncSession, agent: Agent, row: AgentContextInsight) -> list[dict]:
    present, _ = cr.section_status(_parsed_sections(row))
    facts = {
        "stage": agent.lifecycle_stage,
        "reviews": await gate_statuses(db, agent.id),
        "euAiActCategory": agent.eu_ai_act_category,
        "oversightDocumented": "Human oversight" in present,
    }
    return cr.suggested_risks(row.keyword_hits or [], facts)


async def _dependency_suggestions(db: AsyncSession, agent: Agent) -> list[dict]:
    result = await db.execute(select(
        Agent.id, Agent.name, Agent.enterprise_systems, Agent.databases, Agent.knowledge_bases, Agent.mcp_servers,
    ))
    agents = [dict(r._mapping) for r in result]
    names = {a["id"]: a["name"] for a in agents}
    catalog = cr.dependency_catalog(agents, exclude_agent_id=agent.id)
    declared = cr.declared_dependency_names({
        "name": agent.name, "enterprise_systems": agent.enterprise_systems, "databases": agent.databases,
        "knowledge_bases": agent.knowledge_bases, "mcp_servers": agent.mcp_servers,
        "consumers": agent.consumers, "calls": agent.calls,
    }, names)
    return cr.dependency_suggestions(agent.context_md or "", catalog, declared)


async def _confirmed_rule_ids(db: AsyncSession, agent_id: str) -> set[str]:
    result = await db.execute(
        select(AgentRisk.rule_id).where(AgentRisk.agent_id == agent_id, AgentRisk.rule_id.like(f"{RULE_PREFIX}%"))
    )
    return {r for r in result.scalars().all() if r}


def _risk_key(key: str) -> str:
    return f"risk:{key}"


def _dependency_key(name: str) -> str:
    return f"dependency:{name.strip().lower()}"


async def _analyse(db: AsyncSession, agent: Agent, content: str, h: str,
                   row: AgentContextInsight | None, dismissed: list[str]) -> AgentContextInsight:
    """Rule-based analysis always; the LLM summary unless `row` already has
    one. The LLM call happens before any write so SQLite is not held locked."""
    sections = cr.parse_sections(content)
    hits = cr.keyword_scan(content)
    if row is not None and row.llm_status == "ok":
        summary, llm_status = row.summary, row.llm_status
    else:
        summary, llm_status = await _llm_summary(content)
    if row is None:
        row = AgentContextInsight(content_hash=h, agent_id=agent.id)
        db.add(row)
    dismissed_map = _dismissed_map(row)
    if dismissed:
        dismissed_map[agent.id] = sorted(set(dismissed_map.get(agent.id, [])) | set(dismissed))
    row.sections = {"parsed": sections, "dismissed": dismissed_map}
    row.completeness_pct = cr.completeness(sections)
    row.keyword_hits = hits
    row.summary, row.llm_status = summary, llm_status
    row.suggested_risks = await _risk_suggestions(db, agent, row)
    row.suggested_dependencies = await _dependency_suggestions(db, agent)
    return row


async def _insight_row(db: AsyncSession, agent: Agent) -> AgentContextInsight | None:
    """The cached insight for the agent's current context.md, computed once
    per content hash."""
    if not _present(agent.context_md):
        return None
    h = content_hash(agent.context_md)
    row = await db.get(AgentContextInsight, h)
    if row is not None:
        return row
    async with _write_lock:
        row = await db.get(AgentContextInsight, h)
        if row is None:
            row = await _analyse(db, agent, agent.context_md, h, None, [])
            await db.commit()
    return row


def _hit_view(hit: dict) -> dict:
    label = cr.KEYWORD_CATEGORIES.get(hit.get("category"), {}).get("label", SECRET_VALUE_LABEL)
    return {**hit, "label": label}


async def get_insight(db: AsyncSession, agent: Agent) -> dict | None:
    """Insight for the current context.md with live suggestions: confirmed
    and dismissed ones are left out, and risk suggestions follow the
    agent's current gate statuses."""
    row = await _insight_row(db, agent)
    if row is None:
        return None
    parsed = _parsed_sections(row)
    present, missing = cr.section_status(parsed)
    dismissed = set(_dismissed_map(row).get(agent.id, []))
    confirmed = await _confirmed_rule_ids(db, agent.id)
    risks = [
        r for r in await _risk_suggestions(db, agent, row)
        if f"{RULE_PREFIX}{r['key']}" not in confirmed and _risk_key(r["key"]) not in dismissed
    ]
    deps = [d for d in await _dependency_suggestions(db, agent) if _dependency_key(d["name"]) not in dismissed]
    return {
        "hash": row.content_hash,
        "sections": parsed,
        "sectionsPresent": present,
        "sectionsMissing": missing,
        "completenessPct": row.completeness_pct,
        "keywordHits": [_hit_view(h) for h in row.keyword_hits or []],
        "suggestedRisks": risks,
        "suggestedDependencies": deps,
        "dismissed": sorted(dismissed),
        "summary": row.summary if row.llm_status == "ok" else None,
        "llmStatus": row.llm_status,
        "analysedAt": _iso(row.created_at),
    }


# ── Writes ──────────────────────────────────────────────────────────────────

def _audit(agent_id: str, user_id: str, action: str, changes: dict) -> AuditLog:
    return AuditLog(org_id="org-default", actor=user_id, action=action, entity_type="agent",
                    entity_id=agent_id, changes=changes)


async def save_context(db: AsyncSession, agent: Agent, content: str, user_id: str) -> dict:
    """Saves a new version unless it matches the latest one. Empty or
    whitespace-only content removes the context; history is kept. Returns
    {status: saved | removed | unchanged, version}."""
    content = content if _present(content) else ""
    await ensure_initial_version(db, agent)
    async with _write_lock:
        latest = await latest_version(db, agent.id)
        previous_row = await db.get(AgentContextInsight, content_hash(agent.context_md)) if _present(agent.context_md) else None
        carried = _dismissed_map(previous_row).get(agent.id, [])

        changed = (latest.content_hash if latest else content_hash("")) != content_hash(content)
        version = None
        if content:
            h = content_hash(content)
            row = await db.get(AgentContextInsight, h)
            agent.context_md = content
            if row is None or row.llm_status != "ok" or changed:
                await _analyse(db, agent, content, h, row, carried)
        else:
            agent.context_md = None
        if changed:
            version = _new_version(agent.id, content, user_id)
            db.add(version)
            db.add(_audit(agent.id, user_id, "context.remove" if not content else "context.save", {
                "versionId": version.id, "hash": version.content_hash, "sizeBytes": version.size_bytes,
                "previousHash": latest.content_hash if latest else None,
            }))
        await db.commit()
    status = "unchanged" if not changed else ("saved" if content else "removed")
    return {"status": status, "version": version_to_dict(version) if version else None}


async def _find_suggestion(db: AsyncSession, agent: Agent, kind: str, ref: str) -> dict:
    ref = (ref or "").strip()
    if kind == "risk":
        row = await _insight_row(db, agent)
        found = [r for r in await _risk_suggestions(db, agent, row) if r["key"] == ref] if row else []
    elif kind == "dependency":
        found = [d for d in await _dependency_suggestions(db, agent) if d["name"].lower() == ref.lower()] if _present(agent.context_md) else []
    else:
        raise SuggestionNotFound(f"Unknown suggestion type '{kind}'")
    if not found:
        raise SuggestionNotFound(f"No current {kind} suggestion '{ref}' for this agent")
    return found[0]


async def confirm_suggestion(db: AsyncSession, agent: Agent, kind: str, ref: str, user_id: str) -> dict:
    """A person confirms a suggestion. A risk becomes an open agent_risks row
    (source context, rule_id context.<key>); a dependency is appended to the
    declared field it belongs to."""
    suggestion = await _find_suggestion(db, agent, kind, ref)
    async with _write_lock:
        if kind == "risk":
            rule_id = f"{RULE_PREFIX}{suggestion['key']}"
            existing = (await db.execute(
                select(AgentRisk).where(AgentRisk.agent_id == agent.id, AgentRisk.rule_id == rule_id)
            )).scalars().first()
            if existing:
                return {"status": "exists", "type": kind, "riskId": existing.id, "ruleId": rule_id}
            now = _now()
            risk = AgentRisk(
                id=secrets.token_hex(8), agent_id=agent.id, category=suggestion["category"],
                severity=suggestion["severity"], title=suggestion["title"],
                description=f"{suggestion['description']}\n\nFrom context.md: \"{suggestion['excerpt']}\"",
                source="context", status="open", rule_id=rule_id, detected_at=now, last_detected_at=now,
                history=[history_entry(now, user_id, "confirmed from context.md suggestion", suggestion["title"])],
            )
            db.add(risk)
            db.add(_audit(agent.id, user_id, "context.suggestion.confirm", {
                "type": kind, "key": suggestion["key"], "riskId": risk.id, "ruleId": rule_id,
                "category": risk.category, "severity": risk.severity,
            }))
            await db.commit()
            return {"status": "created", "type": kind, "riskId": risk.id, "ruleId": rule_id}

        field, value = suggestion["field"], suggestion["value"]
        current = list(getattr(agent, field) or [])
        if value in current:
            return {"status": "exists", "type": kind, "field": field, "name": suggestion["name"]}
        setattr(agent, field, [*current, value])
        db.add(_audit(agent.id, user_id, "context.suggestion.confirm", {
            "type": kind, "name": suggestion["name"], "field": field, "value": value,
        }))
        await db.commit()
        return {"status": "added", "type": kind, "field": field, "name": suggestion["name"], "value": value}


async def dismiss_suggestion(db: AsyncSession, agent: Agent, kind: str, ref: str, user_id: str) -> dict:
    """Hides a suggestion for this agent. Dismissals carry over to later
    versions of the document."""
    suggestion = await _find_suggestion(db, agent, kind, ref)
    key = _risk_key(suggestion["key"]) if kind == "risk" else _dependency_key(suggestion["name"])
    row = await _insight_row(db, agent)
    async with _write_lock:
        dismissed_map = _dismissed_map(row)
        if key in dismissed_map.get(agent.id, []):
            return {"status": "unchanged", "dismissed": key}
        dismissed_map[agent.id] = sorted({*dismissed_map.get(agent.id, []), key})
        row.sections = {**(row.sections or {}), "dismissed": dismissed_map}
        db.add(_audit(agent.id, user_id, "context.suggestion.dismiss", {"type": kind, "key": key}))
        await db.commit()
    return {"status": "dismissed", "dismissed": key}
