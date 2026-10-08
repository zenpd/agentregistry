"""The controls list: every rule the registry applies, and whether it is enforced
(the registry refuses the action), only recorded (it warns or logs, a person
acts), or off. Read from the settings themselves, so the list cannot drift from
what the registry does."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select, text

from api.auth import WEAK_KEYS, _get_secret_key, rbac_on, require_read
from db.base import engine, get_db_session
from db.models import ApprovedTool, ConnectorConfig
from governance import gate_policy as gp
from governance import templates as tpl
from services import notify
from services.ai_meter import get_setting
from shared.config import get_settings

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Controls"])


def _label(key: str) -> str:
    from governance.lifecycle import FIELD_LABELS
    return FIELD_LABELS.get(key, key)


def control(key: str, name: str, state: str, detail: str, where: str) -> dict:
    return {"key": key, "name": name, "state": state, "detail": detail, "where": where}


async def _audit_triggers() -> bool:
    async with engine.connect() as conn:
        if conn.dialect.name == "sqlite":
            q = "SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name IN ('audit_log_no_update','audit_log_no_delete')"
            return (await conn.execute(text(q))).scalar() == 2
        if conn.dialect.name == "postgresql":
            return bool((await conn.execute(text("SELECT 1 FROM pg_trigger WHERE tgname = 'audit_log_append_only'"))).scalar())
    return False


@router.get("/governance/controls")
async def controls(_=Depends(require_read)):
    s = get_settings()
    templates = await tpl.templates()
    required = await tpl.required_fields()
    tiers_block = [t for t, v in templates.items() if v.get("mode") == "block"]
    tiers_warn = [t for t, v in templates.items() if v.get("mode") != "block"]
    gate_state = "enforced" if not tiers_warn else ("recorded" if not tiers_block else "partly")
    async with get_db_session() as db:
        tools = (await db.execute(select(ApprovedTool.id))).scalars().all()
        assureai = (await db.execute(select(ConnectorConfig.id).where(ConnectorConfig.kind == "assureai",
                                                                      ConnectorConfig.enabled == True))).scalars().all()  # noqa: E712
    cap = await get_setting("ai.monthly_cap_cents")
    ch = notify.channels()
    key = _get_secret_key() or ""
    strong = not (key.lower() in WEAK_KEYS or key.startswith("change-me") or len(key) < 32)
    out = [
        control("roles", "Role checks on every action", "enforced" if rbac_on() else "off",
                "Each request is checked against the person's role." if rbac_on()
                else "RBAC_ENABLED is false, so every signed-in person can do everything.", "Backend setting RBAC_ENABLED"),
        control("stage_gates", "Reviews before a stage change", gate_state,
                ("A stage change is refused for risk level " + ", ".join(tiers_block) + "." if tiers_block else "")
                + (" For risk level " + ", ".join(tiers_warn) + " it is a warning only: the move happens and the warnings are logged." if tiers_warn else ""),
                "Settings → Governance rules"),
        control("required_fields", "Fields required before each stage", gate_state,
                "Development: " + ", ".join(_label(k) for k in required.get("Development", [])) + ". Testing adds: "
                + ", ".join(_label(k) for k in required.get("Testing", []) if k not in required.get("Development", []))
                + ". Production adds: " + ", ".join(_label(k) for k in required.get("Production", []) if k not in required.get("Testing", [])) + ".",
                "Settings → Governance rules"),
        control("approval_expiry", "Approvals expire", "enforced",
                "An approval lasts " + ", ".join(f"{v['validityDays']} days for {t} risk" for t, v in templates.items())
                + ". An expired approval counts as not approved.", "Settings → Governance rules"),
        control("change_reopens", "A change after approval reopens the reviews it affects",
                "enforced" if s.scheduler_enabled else "recorded",
                "The daily governance check compares the record with the copy kept at approval and reopens the affected reviews."
                if s.scheduler_enabled else "The scheduler is off, so this runs only when the governance job is started by hand.",
                "Pipelines → governance checks"),
        control("waivers", "Waivers need two different signers", "enforced",
                "A waiver counts only after a second person who may decide that review also signs it. A failed Security Review cannot be waived.",
                "Built in"),
        control("self_approval", "Nobody approves their own access request", "off" if s.allow_self_approval else "enforced",
                "ALLOW_SELF_APPROVAL is on (a testing setting), so a requester may approve their own request."
                if s.allow_self_approval else "A requester cannot approve their own request.", "Backend setting ALLOW_SELF_APPROVAL"),
        control("classification", "Classification confirmed by an authorised role", "enforced",
                "Only an Architect Steward, Data Protection Officer or Registry Admin changes an agent's EU AI Act category and risk level. "
                "A result below the suggestion needs a written reason.", "Built in"),
        control("tool_list", "Risk class from approved tools", "recorded" if tools else "off",
                f"{len(tools)} tools on the approved list. The highest class raises the classification suggestion. "
                "Unlisted tools are shown on the Governance tab." if tools else "The approved tool list is empty.",
                "Settings → Approved tools"),
        control("retirement", "Retirement only through checked steps", "enforced",
                "The stage becomes Deprecated only after 7 days without calls, consumers told and access revoked.", "Built in"),
        control("assureai", "AssureAI verdict before Production",
                ("enforced" if tiers_block and not tiers_warn else "recorded") if await tpl.assureai_required() else "off",
                ("AssureAI is the testing tool linked in Settings → Connectors. An agent with no verdict or a failed one gets a warning before Production, or is refused, as set for its risk level. " + (f"{len(assureai)} AssureAI connector(s) set up."
                 if assureai else "No AssureAI connector is set up yet, so every agent shows the warning."))
                if await tpl.assureai_required() else "Not required. The verdict is shown as evidence when recorded.",
                "Settings → Governance rules"),
        control("audit", "Audit rows cannot be changed or deleted", "enforced" if await _audit_triggers() else "off",
                "Database triggers refuse any change or deletion of an audit row." if await _audit_triggers()
                else "The database triggers are missing. Restart the backend to create them.", "Database"),
        control("ai_cap", "Monthly cap on the registry's own AI", "enforced" if cap else "off",
                f"Scheduled AI work stops at ${int(cap) / 100:,.2f} a month. AI that a person starts with a button keeps working until 1.2 times that amount." if cap
                else "No cap is set.", "Settings → Registry AI"),
        control("budgets", "Monthly budgets per agent", "recorded",
                "Spend above the alert threshold raises a notice to the owner. Calls are not stopped.", "Agent → Tokenomics"),
        control("notices", "Daily notices", "enforced" if s.scheduler_enabled else "off",
                "Sent once a day to the in-app inbox" + (", e-mail" if ch.get("email") else "") + (", the Teams channel" if ch.get("teams") else "") + "."
                if s.scheduler_enabled else "The scheduler is off, so no daily notice is sent.", "Settings → Notifications"),
        control("signing_key", "Strong sign-in signing key", "enforced" if strong else "off",
                "The signing key is at least 32 characters and is not a known default." if strong
                else "The signing key is a default or shorter than 32 characters. The backend refuses to start like this outside development.",
                "Backend setting AIREGISTRY_SECRET_KEY"),
    ]
    counts = {k: sum(1 for c in out if c["state"] == k) for k in ("enforced", "partly", "recorded", "off")}
    return {"controls": out, "counts": counts}
