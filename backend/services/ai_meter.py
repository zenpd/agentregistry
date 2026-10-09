"""The registry's own AI: one switch per function, a monthly spend cap, and a
record of every call (model, prompt version, tokens, cost, time, result).

A switched-off function or a reached cap refuses the call before the model is
asked; the caller then shows its non-AI answer. Scheduled work stops at the
cap; a person's request still runs until 1.2 times the cap."""
from __future__ import annotations

import secrets
from contextvars import ContextVar
from datetime import datetime, timezone

from sqlalchemy import func, select

from db.base import get_db_session
from db.models import AiRun, RegistrySetting
from governance import costing
from services.usage_repo import load_aliases, load_prices
from shared.config import get_settings

FUNCTIONS: dict[str, str] = {
    "insights": "Insight cards on agent tabs",
    "ask": "Ask the Registry",
    "registration_coach": "Registration coach and duplicate finder",
    "evidence_review": "Evidence reader",
    "trace_audit": "Trace content audit",
    "record_draft": "Record draft (automatic fill)",
    "review_notes": "Review notes drafting",
    "context_summary": "Context summary",
}
INTERACTIVE_CEILING = 1.2

# Set by the AI-off check so every function behaves as if switched off.
force_off: ContextVar[bool] = ContextVar("ai_force_off", default=False)


def function_for_kind(kind: str) -> str:
    if kind in ("ask", "evidence_review", "trace_audit", "record_draft"):
        return kind
    if kind in ("registration_coach", "duplicates"):
        return "registration_coach"
    return "insights"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def get_setting(key: str, default=None):
    async with get_db_session() as db:
        row = await db.get(RegistrySetting, key)
    return row.value.get("v", default) if row and isinstance(row.value, dict) else default


async def set_setting(key: str, value, actor: str) -> None:
    async with get_db_session() as db:
        row = await db.get(RegistrySetting, key)
        if row is None:
            db.add(RegistrySetting(key=key, value={"v": value}, updated_by=actor))
        else:
            row.value, row.updated_by = {"v": value}, actor


async def switches() -> dict[str, bool]:
    saved = await get_setting("ai.switches", {}) or {}
    return {f: bool(saved.get(f, True)) for f in FUNCTIONS}


async def month_spend_cents() -> float:
    start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    async with get_db_session() as db:
        total = (await db.execute(select(func.coalesce(func.sum(AiRun.cost_cents), 0)).where(AiRun.created_at >= start))).scalar()
    return float(total or 0)


async def refusal(function: str, interactive: bool = True) -> str | None:
    """Why this call may not run now, or None when it may."""
    if force_off.get():
        return "The registry's AI is switched off (AI-off check)."
    if not (await switches()).get(function, True):
        return f"{FUNCTIONS.get(function, function)} is switched off in Settings."
    cap = await get_setting("ai.monthly_cap_cents")
    if cap:
        spent = await month_spend_cents()
        limit = cap * (INTERACTIVE_CEILING if interactive else 1.0)
        if spent >= limit:
            return ("The registry's monthly AI budget is used up" + ("" if interactive else " for scheduled work")
                    + f" (${spent / 100:,.2f} of ${cap / 100:,.2f}).")
    return None


async def price_cents(model: str | None, input_tokens: int, output_tokens: int) -> float | None:
    if not model:
        return None
    async with get_db_session() as db:
        prices, aliases = await load_prices(db), await load_aliases(db)
    price = prices.get(costing.normalize_model(model, aliases))
    return round(costing.token_cost_cents(input_tokens, output_tokens, 0, price), 4) if price else None


async def record(function: str, *, kind: str | None = None, agent_id: str | None = None, model: str | None = None,
                 prompt_version: str | None = None, input_tokens: int = 0, output_tokens: int = 0, duration_ms: int = 0,
                 status: str = "ok", reason: str | None = None, interactive: bool = True, actor: str | None = None) -> None:
    cost = await price_cents(model, input_tokens, output_tokens) if (input_tokens or output_tokens) else 0.0
    async with get_db_session() as db:
        db.add(AiRun(id=secrets.token_hex(10), function=function, kind=kind, agent_id=agent_id, model=model,
                     prompt_version=prompt_version, input_tokens=input_tokens, output_tokens=output_tokens, cost_cents=cost,
                     duration_ms=duration_ms, status=status, reason=(reason or "")[:300] or None,
                     interactive=interactive, actor=actor))


def deployment() -> str:
    return get_settings().azure_openai_deployment
