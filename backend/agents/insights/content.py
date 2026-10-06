"""Gathers the two kinds of text the registry otherwise never reads: evidence
documents attached to a review, and a sample of an agent's trace text.

Both are untrusted. The text is fetched by code, shortened, redacted, fenced
and handed to a single model call that has no tools. Trace text is read only
for an agent whose owner opted in, is held only for the length of the call and
is never stored or logged: only the verdicts and span references are kept."""
from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from agents.insights.runtime import fence
from agents.insights.tools import RefBook, _clip
from governance import reuse
from governance.context_reader import redact
from shared.config import get_settings

MAX_DOCUMENTS = 5
MAX_DOCUMENT_BYTES = 600_000
MAX_DOCUMENT_CHARS = 7000
FETCH_TIMEOUT = 45.0   # the first request to an idle app can take this long
TRACE_SAMPLE = 24
MAX_SPAN_CHARS = 900
_TEXT_TYPES = ("text/", "application/json", "application/xml", "application/xhtml")


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return " ".join(html.unescape(raw).split())


async def fetch_document(url: str) -> dict:
    """{ok, text | reason}. Same address checks as the app lookup: the name is
    resolved once, checked, and the connection goes to that checked address;
    redirects are not followed; only text is read, up to a size limit."""
    from api.routers.ops import integrate
    from api.routers.ops.discovery import ALLOWED_PORTS, pinned_request
    settings = get_settings()
    try:
        parsed = urlparse(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return {"ok": False, "reason": "The link is not a valid web address"}
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username:
        return {"ok": False, "reason": "The link is not a plain web address"}
    if port not in ALLOWED_PORTS and settings.app_env != "development":
        return {"ok": False, "reason": "Only the standard web ports can be read"}
    try:
        addresses = await integrate._resolve(parsed.hostname, port)
        reuse.check_addresses(addresses, settings.app_env == "development")
    except reuse.TryItBlocked as exc:
        return {"ok": False, "reason": str(exc)}
    except (OSError, ValueError):
        return {"ok": False, "reason": "The address could not be found from this server"}
    target, headers, extensions = pinned_request(url, addresses[0])
    headers["Accept"] = "text/html, text/plain, application/json;q=0.9, */*;q=0.1"
    try:
        async with integrate._http_client(FETCH_TIMEOUT) as client:
            async with client.stream("GET", target, headers=headers, extensions=extensions) as resp:
                raw, truncated = await integrate._read_capped(resp, MAX_DOCUMENT_BYTES)
    except httpx.HTTPError as exc:
        return {"ok": False, "reason": f"It could not be fetched ({type(exc).__name__})"}
    if resp.is_redirect:
        return {"ok": False, "reason": "The link redirects (often to a sign-in page), which is not followed"}
    if not resp.is_success:
        return {"ok": False, "reason": f"The link answered {resp.status_code} (it may need a sign-in)"}
    kind = resp.headers.get("content-type", "").lower()
    if not kind.startswith(_TEXT_TYPES):
        return {"ok": False, "reason": f"Only text and web pages can be read, not {kind.split(';')[0] or 'this file type'}"}
    text = raw.decode(resp.charset_encoding or "utf-8", errors="replace")
    text = html_to_text(text) if "html" in kind or "xml" in kind else " ".join(text.split())
    if len(text) < 40:
        return {"ok": False, "reason": "The page has no readable text (it may need a sign-in or a browser)"}
    return {"ok": True, "text": redact(text)[:MAX_DOCUMENT_CHARS], "truncated": truncated or len(text) > MAX_DOCUMENT_CHARS}


async def evidence_block(agent_id: str, gate: str | None, book: RefBook) -> tuple[str, dict]:
    """(data block for the reader, {documents, readable, items}). Empty block when no evidence is attached."""
    from api.routers.ops import governance
    g = await governance.get_governance(agent_id, _={"user_id": "insight-agent", "role": "viewer"})
    parts, documents, readable, items, unreadable = [], 0, 0, 0, []
    for review in g["gates"]:
        if gate and review["gate"] != gate:
            continue
        links = (review.get("evidence") or [])[:MAX_DOCUMENTS]
        if not links:
            continue
        checklist = []
        for c in review.get("checklist") or []:
            checklist.append({"ref": book.ref("check", agent_id, c["id"], label=c["label"]), "item": c["label"],
                              "ticked": c.get("tick"), "result": c.get("result")})
        items += len(checklist)
        lines = [f"Review: {review['label']} (status: {review['status']})", "Checklist items:"]
        lines += [f"- ref={c['ref']} | {c['item']} | ticked={c['ticked']} | result={c['result']}" for c in checklist]
        parts.append("\n".join(lines))
        for n, link in enumerate(links):
            documents += 1
            label = _clip(link.get("label") or link.get("url"), 120)
            ref = book.ref("evidence", agent_id, review["gate"], n, label=f"Evidence: {label}")
            doc = await fetch_document(link["url"])
            if doc["ok"]:
                readable += 1
                parts.append(fence(f"evidence document ref={ref} title={label}", doc["text"]))
            else:
                unreadable.append(f"{label}: {doc['reason']}")
                parts.append(f"Evidence document ref={ref} title={label}: COULD NOT BE READ — {doc['reason']}")
    return "\n\n".join(parts), {"documents": documents, "readable": readable, "items": items, "unreadable": unreadable}


# ── Trace text (opt-in only) ────────────────────────────────────────────────

_CONTENT_KEYS = ("input.value", "output.value")


def _span_text(span: dict) -> dict | None:
    attrs = span.get("attributes") or {}
    said = {k.split(".")[0]: _clip(attrs[k], MAX_SPAN_CHARS) for k in _CONTENT_KEYS if isinstance(attrs.get(k), str) and attrs[k].strip()}
    failed = str(span.get("status_code") or "").upper() == "ERROR"
    if not said and not failed:
        return None
    error = _clip(span.get("status_message"), 300) if failed else ""
    for event in span.get("events") or []:
        if isinstance(event, dict) and "exception" in str(event.get("name", "")).lower():
            error = error or _clip((event.get("attributes") or {}).get("exception.message"), 300)
    return {"kind": str(span.get("span_kind") or attrs.get("openinference.span.kind") or "").upper(),
            "name": _clip(span.get("name"), 80), "failed": failed, "error": error, **said}


async def trace_block(agent_id: str, book: RefBook) -> tuple[str, dict]:
    """(data block, {status, reason?, spansRead, sampled}). The caller has already checked the opt-in."""
    from api.routers import registry
    from db.base import get_db_session
    from db.models import Agent
    from discovery.phoenix_client import PhoenixClient, PhoenixError
    from sqlalchemy import select

    async with get_db_session() as db:
        agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one()
        base_url, api_key = await registry._resolve_phoenix_endpoint(db, agent)
        project, purpose = (agent.phoenix_project or "").strip(), agent.description or ""
    if not project:
        return "", {"status": "nothing_to_read", "reason": "No Phoenix project is linked to this agent."}
    if not base_url:
        return "", {"status": "nothing_to_read", "reason": "No Phoenix address is configured."}
    try:
        async with PhoenixClient(base_url, api_key=api_key, timeout=45.0) as client:
            spans = [s async for s in client.spans(project, limit=100, max_pages=2)]
    except PhoenixError:
        return "", {"status": "unavailable", "reason": "Phoenix could not be reached. Check the VPN and try again."}
    picked: list[tuple[dict, dict]] = []
    # Failures first, then the widest spread of step names, so one busy step does not fill the sample.
    seen_names: dict[str, int] = {}
    for span in sorted(spans, key=lambda s: str(s.get("status_code") or "").upper() != "ERROR"):
        text = _span_text(span)
        if not text:
            continue
        if seen_names.get(text["name"], 0) >= 3 and not text["failed"]:
            continue
        seen_names[text["name"]] = seen_names.get(text["name"], 0) + 1
        picked.append((span, text))
        if len(picked) >= TRACE_SAMPLE:
            break
    if not picked:
        return "", {"status": "nothing_to_read", "spansRead": len(spans),
                    "reason": "The recent traces carry no input or output text and no failures to read."}
    lines = [f"Stated purpose of the agent: {_clip(purpose, 500) or '(none recorded)'}", f"Sample: {len(picked)} of the {len(spans)} most recent traced steps."]
    for span, text in picked:
        span_id = (span.get("context") or {}).get("span_id") or span.get("id") or "unknown"
        ref = book.ref("span", agent_id, span_id, label=f"Traced step {text['name']}")
        body = "\n".join(f"{k}: {v}" for k, v in text.items() if v not in ("", False))
        lines.append(fence(f"traced step ref={ref}", body))
    return "\n\n".join(lines), {"status": "ok", "spansRead": len(spans), "sampled": len(picked)}
