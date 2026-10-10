"""The registry's own AI: what each function costs, its switch, the monthly
cap, recent runs, and a check that every page still answers with AI off."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from api.auth import require_admin, require_read
from db.base import get_db_session
from db.models import AiRun, AuditLog
from orchestrations.risk_scan import as_utc
from services import ai_meter

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Registry AI"])


class SwitchBody(BaseModel):
    enabled: bool


class CapBody(BaseModel):
    monthlyCapCents: Optional[int] = Field(None, ge=0)


def _model_status() -> dict:
    """Whether an AI model is set up, from where its key comes, and where it is. Never returns a secret."""
    from urllib.parse import urlparse
    from agents.insights.runtime import model_setup_hint
    from shared.config import get_settings
    s = get_settings()
    if not s.azure_openai_api_key and s.azure_openai_api_key_kv_uri:
        s.resolve_missing_secrets()
    key = bool(s.azure_openai_api_key)
    return {
        "configured": bool(s.azure_openai_endpoint) and key,
        "endpointHost": urlparse(s.azure_openai_endpoint).netloc if s.azure_openai_endpoint else None,
        "deployment": s.azure_openai_deployment,
        "keySet": key,
        "keyFrom": ("Key Vault" if s.azure_openai_api_key_kv_uri else "the environment") if key else None,
        "keyVaultAddressSet": bool(s.azure_openai_api_key_kv_uri),
        "problem": None if (s.azure_openai_endpoint and key) else model_setup_hint(s),
    }


@router.post("/ai-usage/model-check")
async def model_check(_=Depends(require_admin)):
    """Sends one tiny request to the AI model and says whether it answered."""
    import time
    from agents.insights.runtime import ModelUnavailable, get_model
    status = _model_status()
    if not status["configured"]:
        return {**status, "ok": False, "message": status["problem"]}
    started = time.monotonic()
    try:
        reply = await get_model(max_tokens=5).ainvoke("Reply with the word ok.")
    except ModelUnavailable as exc:
        return {**status, "ok": False, "message": str(exc)}
    except Exception as exc:  # the network, a refused key or a wrong deployment name: say which kind, never the key
        text = str(exc)
        kind = ("The network could not reach the model (is the VPN or the private network connected?)" if any(w in text.lower() for w in ("connect", "timeout", "resolve", "unreachable"))
                else "The model refused the request (check the key and the deployment name)" if any(w in text for w in ("401", "403", "404", "Unauthorized", "Forbidden", "NotFound", "DeploymentNotFound"))
                else "The model request failed")
        return {**status, "ok": False, "message": f"{kind}: {type(exc).__name__}."}
    return {**status, "ok": True, "message": f"The model answered in {int((time.monotonic() - started) * 1000)} ms.", "reply": str(getattr(reply, "content", ""))[:40]}


@router.get("/ai-usage")
async def ai_usage(_=Depends(require_read)):
    now = ai_meter.utcnow()
    since = now - timedelta(days=30)
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    switches = await ai_meter.switches()
    async with get_db_session() as db:
        rows = (await db.execute(
            select(AiRun.function, func.count(), func.sum(AiRun.input_tokens), func.sum(AiRun.output_tokens),
                   func.sum(AiRun.cost_cents), func.avg(AiRun.duration_ms))
            .where(AiRun.created_at >= since, AiRun.status != "refused").group_by(AiRun.function))).all()
        refused = dict((await db.execute(select(AiRun.function, func.count()).where(
            AiRun.created_at >= since, AiRun.status == "refused").group_by(AiRun.function))).all())
        recent = (await db.execute(select(AiRun).order_by(AiRun.created_at.desc()).limit(40))).scalars().all()
        last = {}
        for r in (await db.execute(select(AiRun).where(AiRun.status == "ok").order_by(AiRun.created_at.desc()).limit(500))).scalars().all():
            last.setdefault(r.function, r)
    by_fn = {r[0]: r for r in rows}
    cap = await ai_meter.get_setting("ai.monthly_cap_cents")
    spent = await ai_meter.month_spend_cents()
    return {
        "model": _model_status(),
        "monthStart": month.date().isoformat(),
        "spentThisMonthCents": round(spent, 2),
        "monthlyCapCents": cap,
        "capState": "no_cap" if not cap else "reached" if spent >= cap else "within",
        "interactiveCeiling": ai_meter.INTERACTIVE_CEILING,
        "functions": [{
            "function": f, "label": label, "enabled": switches[f],
            "runs30d": int(by_fn[f][1]) if f in by_fn else 0,
            "refused30d": int(refused.get(f, 0)),
            "inputTokens30d": int(by_fn[f][2] or 0) if f in by_fn else 0,
            "outputTokens30d": int(by_fn[f][3] or 0) if f in by_fn else 0,
            "costCents30d": round(float(by_fn[f][4] or 0), 2) if f in by_fn else 0.0,
            "avgMs": int(by_fn[f][5] or 0) if f in by_fn else None,
            "lastModel": last[f].model if f in last else None,
            "lastPromptVersion": last[f].prompt_version if f in last else None,
        } for f, label in ai_meter.FUNCTIONS.items()],
        "recent": [{
            "at": as_utc(r.created_at).isoformat() if r.created_at else None, "function": r.function, "kind": r.kind,
            "agentId": r.agent_id, "model": r.model, "promptVersion": r.prompt_version, "inputTokens": r.input_tokens,
            "outputTokens": r.output_tokens, "costCents": r.cost_cents, "durationMs": r.duration_ms, "status": r.status,
            "reason": r.reason, "scheduled": not r.interactive,
        } for r in recent],
    }


@router.put("/ai-usage/switches/{function}")
async def set_switch(function: str, body: SwitchBody, user=Depends(require_admin)):
    if function not in ai_meter.FUNCTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown AI function {function!r}")
    current = await ai_meter.get_setting("ai.switches", {}) or {}
    await ai_meter.set_setting("ai.switches", {**current, function: body.enabled}, user.get("user_id"))
    async with get_db_session() as db:
        db.add(AuditLog(org_id="org-default", actor=user.get("user_id", "unknown"), action="settings.update",
                        entity_type="ai_function", entity_id=function, changes={"enabled": body.enabled}))
    return {"function": function, "enabled": body.enabled}


@router.put("/ai-usage/cap")
async def set_cap(body: CapBody, user=Depends(require_admin)):
    await ai_meter.set_setting("ai.monthly_cap_cents", body.monthlyCapCents or None, user.get("user_id"))
    async with get_db_session() as db:
        db.add(AuditLog(org_id="org-default", actor=user.get("user_id", "unknown"), action="settings.update",
                        entity_type="ai_cap", entity_id="monthly", changes={"monthlyCapCents": body.monthlyCapCents}))
    return {"monthlyCapCents": body.monthlyCapCents or None}


@router.post("/ai-usage/off-check")
async def ai_off_check(_=Depends(require_admin)):
    """Runs each AI function's code path with the AI switched off and confirms it
    answers without the model: a stated reason or the non-AI draft, never an error."""
    from agents.insights.runtime import run_insight
    from agents.insights.specs import SPECS
    from api.routers.ops.governance import _ask_llm
    from services.context_service import _llm_summary

    token = ai_meter.force_off.set(True)
    checks = []
    try:
        for kind in ("agent_brief", "ask", "registration_coach", "evidence_review", "trace_audit", "record_draft"):
            spec = SPECS.get(kind) or next(iter(SPECS.values()))
            r = await run_insight(spec, agent_id=None, request="AI-off check", actor="ai-off-check")
            checks.append({"function": ai_meter.function_for_kind(spec.kind), "kind": spec.kind,
                           "passed": r["status"] == "unavailable" and bool(r.get("reason")),
                           "shows": r.get("reason") or r["status"]})
        notes = await _ask_llm("check", "check")
        checks.append({"function": "review_notes", "kind": None, "passed": notes is None,
                       "shows": "The rule-based draft of the review notes (no AI)."})
        summary, status = await _llm_summary("# Purpose\nAI-off check")
        checks.append({"function": "context_summary", "kind": None, "passed": summary is None and status == "disabled",
                       "shows": "The context sections and completeness, without the AI summary."})
    finally:
        ai_meter.force_off.reset(token)
    return {"passed": all(c["passed"] for c in checks), "checks": checks}
