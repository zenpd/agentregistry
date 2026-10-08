"""Loading the admin-set governance settings (templates by risk tier, required
fields per stage, stall limits), with defaults that keep today's behaviour."""
from __future__ import annotations

from governance import gate_policy as gp
from governance import lifecycle
from shared.config import get_settings


async def templates() -> dict:
    from services.ai_meter import get_setting

    s = get_settings()
    saved = await get_setting("governance.templates")
    base = lifecycle.default_templates(int(s.gate_validity_days_default), int(s.gate_validity_days_high), gp.enforcement_mode())
    if isinstance(saved, dict) and lifecycle.check_templates(saved) is None:
        return saved
    return base


async def required_fields() -> dict:
    from services.ai_meter import get_setting

    saved = await get_setting("stage.required_fields")
    return saved if isinstance(saved, dict) else lifecycle.DEFAULT_REQUIRED


async def stall_weeks() -> dict:
    from services.ai_meter import get_setting

    saved = await get_setting("stage.stall_weeks")
    return saved if isinstance(saved, dict) else lifecycle.DEFAULT_STALL_WEEKS


async def assureai_required() -> bool:
    """Whether a missing or failed AssureAI verdict is a readiness gap for Production."""
    from services.ai_meter import get_setting

    return bool(await get_setting("evidence.assureai_required"))
