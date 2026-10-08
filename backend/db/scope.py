"""Which agents a request may see.

Demo agents (created by the seed script) are left out of every query that
reads agents, unless the viewer switched them on. The switch travels as the
request header ``X-Include-Demo: 1``. Doing this in one place, on every ORM
select, keeps the numbers-equal rule: the agent list, the portfolio pages and
the approvals inbox all count the same agents.

Two exceptions:
- the agent named in an agent-scoped URL (``/api/v1/agents/{id}/...``) is
  always visible, so a demo agent's own page still opens;
- code that runs outside a request (jobs, scripts, tests) sees every agent,
  because the context default is "do not hide".

Archived agents are left out everywhere, in requests and in jobs alike, except
their own agent-scoped URL and code that asks for them with ``showing_archived()``
(the list of archived agents in Settings, which can bring one back).

With DEMO_AGENTS_ENABLED=false the demo agents are left out everywhere too, even
their own agent-scoped URL: the installation runs as if they were not there.

Queries that aggregate a child table (usage rows, reviews, risks) without
selecting from ``agents`` are not covered by the ORM filter; they call
``hidden_agent_ids`` and leave those ids out themselves.
"""
from __future__ import annotations

import re
from contextvars import ContextVar

from sqlalchemy import and_, event, func, or_, select
from sqlalchemy.orm import Session, with_loader_criteria

HEADER = b"x-include-demo"
_AGENT_PATH = re.compile(r"^/api/v1/agents/([^/]+)")

_hide_demo: ContextVar[bool] = ContextVar("hide_demo", default=False)
_show_archived: ContextVar[bool] = ContextVar("show_archived", default=False)
# Internal: lets hidden_agent_ids and the startup seed check read every agent row.
_unfiltered: ContextVar[bool] = ContextVar("unfiltered", default=False)
_always_show: ContextVar[tuple[str, ...]] = ContextVar("always_show", default=())


def hiding_demo() -> bool:
    return _hide_demo.get()


def set_scope(hide_demo: bool, always_show: tuple[str, ...] = ()):
    """For tests and scripts. Returns tokens for reset_scope."""
    return _hide_demo.set(hide_demo), _always_show.set(always_show)


def reset_scope(tokens) -> None:
    _hide_demo.reset(tokens[0])
    _always_show.reset(tokens[1])


class showing_archived:
    """``with showing_archived():`` lets the enclosed queries see archived agents."""

    def __enter__(self):
        self._token = _show_archived.set(True)

    def __exit__(self, *exc):
        _show_archived.reset(self._token)


def demo_enabled() -> bool:
    try:
        from shared.config import get_settings
        return bool(get_settings().demo_agents_enabled)
    except Exception:
        return True


def _criteria():
    from db.models import Agent

    not_demo = func.coalesce(Agent.is_demo, False) == False  # noqa: E712
    # What this viewer leaves out: archived agents, and demo agents when hidden. The
    # agent named in the URL is shown anyway.
    shown = Agent.archived_at.is_(None) if not _show_archived.get() else None
    if _hide_demo.get():
        shown = not_demo if shown is None else and_(shown, not_demo)
    keep = _always_show.get()
    if shown is not None and keep:
        shown = or_(shown, Agent.id.in_(keep))
    # What the installation leaves out, whatever the URL: demo agents when turned off.
    if not demo_enabled():
        shown = not_demo if shown is None else and_(shown, not_demo)
    return shown


class unfiltered:
    """``with unfiltered():`` reads every agent row (no archive, demo or installation filter)."""

    def __enter__(self):
        self._token = _unfiltered.set(True)

    def __exit__(self, *exc):
        _unfiltered.reset(self._token)


@event.listens_for(Session, "do_orm_execute")
def _leave_out_demo(state) -> None:
    if _unfiltered.get() or not state.is_select or state.is_column_load or state.is_relationship_load:
        return
    criteria = _criteria()
    if criteria is None:
        return
    from db.models import Agent

    state.statement = state.statement.options(with_loader_criteria(Agent, criteria, include_aliases=True))


async def hidden_agent_ids(db) -> set[str]:
    """Ids of the agents this request does not show: archived ones, and demo ones
    when the viewer hides them (empty when nothing is hidden)."""
    from db.models import Agent

    keep = set(_always_show.get())
    hiding = _hide_demo.get() or not demo_enabled()
    cond = Agent.archived_at.is_not(None)
    if hiding:
        cond = or_(cond, Agent.is_demo == True)  # noqa: E712
    with unfiltered():
        rows = (await db.execute(select(Agent.id).where(cond))).scalars().all()
    if not demo_enabled():
        return set(rows)          # turned off for the installation: not even the URL's own agent
    return {r for r in rows if r not in keep}


class DemoScopeMiddleware:
    """Pure ASGI middleware, so the context it sets reaches the endpoint."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            return await self.app(scope, receive, send)
        include = any(k == HEADER and v.strip() in (b"1", b"true") for k, v in scope.get("headers", []))
        match = _AGENT_PATH.match(scope["path"])
        tokens = set_scope(not include, (match.group(1),) if match else ())
        try:
            await self.app(scope, receive, send)
        finally:
            reset_scope(tokens)
