"""Azure Cost Management -> agent_infra_costs (metered hosting cost per agent).

parse_query_response is pure; collect_infra_costs does the network and DB work.
Allocation: a resource tagged `<tag_key>=<agent id>` belongs to that agent;
otherwise an agent's resource link (exact resource id, or an ancestor such as
its resource group) claims `share_pct` of it; anything left is unallocated.
Showback only: nothing here changes an Azure resource or an agent.
"""
from __future__ import annotations

import secrets
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Collection, Iterable, Mapping

import httpx
from sqlalchemy import delete, select

from db.base import get_db_session
from db.models import Agent, AgentInfraCost, AgentResourceLink
from shared.config import get_settings
from shared.logger import get_logger

log = get_logger("costs.azure_cost_collector")

API_VERSION = "2023-11-01"
MANAGEMENT_HOST = "https://management.azure.com"
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
TOKEN_SCOPE = "https://management.azure.com/.default"
TIMEOUT_SECONDS = 60.0
MAX_PAGES = 50
MAX_DAYS = 90
NO_RESOURCE_ID = "(no resource id)"

# Column names Cost Management uses for the summed cost, most specific first.
_COST_COLUMNS = ("costusd", "cost", "pretaxcost")

# Settings field -> the env var an operator sets.
_REQUIRED = (
    ("azure_cost_scope", "AZURE_COST_SCOPE"),
    ("azure_tenant_id", "AZURE_TENANT_ID"),
    ("azure_client_id", "AZURE_CLIENT_ID"),
    ("azure_client_secret", "AZURE_CLIENT_SECRET"),
)


# ── Pure parsing and allocation ──────────────────────────────────────────────

def _norm_id(resource_id: str | None) -> str:
    return (resource_id or "").strip().rstrip("/").lower()


def service_from_resource_id(resource_id: str) -> str | None:
    """'Microsoft.App/containerApps' from a full ARM resource id."""
    parts = [p for p in resource_id.strip("/").split("/") if p]
    lower = [p.lower() for p in parts]
    if "providers" not in lower:
        return None
    i = lower.index("providers")
    return f"{parts[i + 1]}/{parts[i + 2]}" if i + 2 < len(parts) else None


def _usage_date(value: Any) -> date:
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit() and len(value) == 8):
        text = str(int(value))
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise ValueError(f"Unrecognised UsageDate value {value!r}")


def _best_links(resource_l: str, links: list[dict]) -> dict[str, int]:
    """agent_id -> share_pct of that agent's most specific link covering the resource."""
    best: dict[str, tuple[int, int]] = {}
    for link in links:
        lid = link["_id"]
        if resource_l != lid and not resource_l.startswith(lid + "/"):
            continue
        current = best.get(link["agent_id"])
        if current is None or len(lid) > current[0]:
            best[link["agent_id"]] = (len(lid), link["share_pct"])
    return {agent: share for agent, (_, share) in best.items()}


def parse_query_response(
    payload: Mapping,
    tag_key: str,
    resource_links: Iterable[Mapping],
    *,
    agent_ids: Collection[str] | None = None,
) -> dict:
    """Allocate a Cost Management query result to agents.

    payload: {"properties": {"columns": [{name, type}], "rows": [[...]]}}.
    resource_links: [{agent_id, resource_id, share_pct}].
    agent_ids: registered agent ids; a tag value naming no registered agent
    falls through to the links. Returns {allocations, unallocated_cents,
    unallocated_resources}; cents are integers.
    """
    props = payload.get("properties") or {}
    names = [str(c.get("name") or "").lower() for c in props.get("columns") or []]
    col = {name: i for i, name in enumerate(names)}
    cost_i = next((col[c] for c in _COST_COLUMNS if c in col), None)
    if cost_i is None or "usagedate" not in col:
        raise ValueError(f"Query result has no cost or UsageDate column (columns: {names})")
    date_i, res_i, svc_i = col["usagedate"], col.get("resourceid"), col.get("servicename")
    cur_i, tk_i, tv_i = col.get("currency"), col.get("tagkey"), col.get("tagvalue")
    usd_only = _COST_COLUMNS[0] in col

    known = {a.lower(): a for a in agent_ids} if agent_ids is not None else None
    tag_l = tag_key.strip().lower()
    links = []
    for link in resource_links:
        share = min(max(int(link.get("share_pct") or 0), 0), 100)
        if share and link.get("resource_id"):
            links.append({"agent_id": link["agent_id"], "_id": _norm_id(link["resource_id"]), "share_pct": share})

    allocated: dict[tuple[str, date, str], dict] = {}
    unallocated: dict[str, dict] = defaultdict(lambda: {"cost_cents": 0.0, "service_name": None})

    def allocate(agent_id: str, day: date, resource: str, service: str | None, cents: float, currency: str, how: str):
        entry = allocated.setdefault((agent_id, day, resource), {
            "agent_id": agent_id, "cost_date": day, "resource_id": resource, "service_name": service,
            "cost_cents": 0.0, "currency": currency, "allocation": how,
        })
        entry["cost_cents"] += cents

    for row in props.get("rows") or []:
        cents = float(row[cost_i] or 0) * 100
        if not cents:
            continue
        day = _usage_date(row[date_i])
        resource = (str(row[res_i]).strip() if res_i is not None and row[res_i] else "") or NO_RESOURCE_ID
        service = (row[svc_i] if svc_i is not None else None) or service_from_resource_id(resource)
        currency = "USD" if usd_only else ((row[cur_i] if cur_i is not None else None) or "USD")

        tag_value = str(row[tv_i]).strip() if tv_i is not None and row[tv_i] else ""
        tag_matches = tk_i is not None and str(row[tk_i] or "").strip().lower() == tag_l
        if tag_matches and tag_value:
            agent = tag_value if known is None else known.get(tag_value.lower())
            if agent:
                allocate(agent, day, resource, service, cents, currency, "tag")
                continue

        shares = _best_links(_norm_id(resource), links) if resource != NO_RESOURCE_ID else {}
        total_share = sum(shares.values())
        # Over-claimed resources are scaled down so no more than the real cost is allocated.
        scale = 100 / total_share if total_share > 100 else 1.0
        for agent, share in shares.items():
            allocate(agent, day, resource, service, cents * share / 100 * scale, currency, "link")
        remainder = cents * (1 - min(total_share, 100) / 100)
        if remainder:
            unallocated[resource]["cost_cents"] += remainder
            unallocated[resource]["service_name"] = unallocated[resource]["service_name"] or service

    allocations = [
        {**a, "cost_cents": round(a["cost_cents"])}
        for a in sorted(allocated.values(), key=lambda a: (a["cost_date"], a["agent_id"], a["resource_id"]))
    ]
    resources = sorted(
        ({"resource_id": r, "service_name": v["service_name"], "cost_cents": round(v["cost_cents"])}
         for r, v in unallocated.items()),
        key=lambda r: r["cost_cents"], reverse=True,
    )
    return {
        "allocations": allocations,
        "unallocated_cents": round(sum(v["cost_cents"] for v in unallocated.values())),
        "unallocated_resources": resources,
    }


def missing_settings(settings: Any) -> list[str]:
    return [env for field, env in _REQUIRED if not str(getattr(settings, field, "") or "").strip()]


_ACCOUNT_SEGMENTS = {"subscriptions", "billingaccounts", "billingprofiles", "managementgroups"}


def mask_scope(scope: str | None) -> str | None:
    """'/subscriptions/1234...-90ab/resourceGroups/rg' -> '/subscriptions/****90ab/resourceGroups/rg'."""
    if not (scope or "").strip():
        return None
    parts = scope.strip().strip("/").split("/")
    for i in range(1, len(parts)):
        if parts[i - 1].lower() in _ACCOUNT_SEGMENTS:
            parts[i] = "****" + parts[i][-4:]
    return "/" + "/".join(parts)


def config_status(settings: Any) -> dict:
    missing = missing_settings(settings)
    return {
        "configured": not missing,
        "missing": missing,
        "scope": mask_scope(settings.azure_cost_scope),
        "tagKey": (settings.azure_cost_tag_key or "agent-id").strip(),
    }


def query_body(tag_key: str, start: date, end: date) -> dict:
    # Cost Management accepts at most two grouping clauses, so ServiceName is
    # derived from the resource id instead of being grouped on.
    return {
        "type": "ActualCost",
        "timeframe": "Custom",
        "timePeriod": {"from": f"{start.isoformat()}T00:00:00Z", "to": f"{end.isoformat()}T23:59:59Z"},
        "dataset": {
            "granularity": "Daily",
            "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
            "grouping": [
                {"type": "Dimension", "name": "ResourceId"},
                {"type": "TagKey", "name": tag_key},
            ],
        },
    }


# ── Network ──────────────────────────────────────────────────────────────────

class CostApiError(Exception):
    def __init__(self, status: str, reason: str, http_status: int | None = None, retry_after: str | None = None):
        super().__init__(reason)
        self.status, self.reason, self.http_status, self.retry_after = status, reason, http_status, retry_after


def _http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT_SECONDS)


def _azure_error(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
        text = f"{err.get('code') or ''}: {err.get('message') or ''}".strip(": ")
    except (ValueError, AttributeError):
        text = ""
    return (text or resp.reason_phrase or "")[:300]


def _raise_for(resp: httpx.Response, what: str) -> None:
    code = resp.status_code
    if code in (401, 403):
        raise CostApiError("forbidden", f"{what} was refused (HTTP {code}). {_azure_error(resp)}".strip(), code)
    if code == 429:
        retry = resp.headers.get("x-ms-ratelimit-microsoft.costmanagement-qpu-retry-after") or resp.headers.get("retry-after")
        raise CostApiError("throttled", f"{what} was throttled (HTTP 429).", code, retry)
    if code >= 400:
        raise CostApiError("error", f"{what} failed (HTTP {code}). {_azure_error(resp)}".strip(), code)


async def _access_token(client: httpx.AsyncClient, settings: Any) -> str:
    resp = await client.post(
        TOKEN_URL.format(tenant=settings.azure_tenant_id.strip()),
        data={
            "grant_type": "client_credentials",
            "client_id": settings.azure_client_id.strip(),
            "client_secret": settings.azure_client_secret,
            "scope": TOKEN_SCOPE,
        },
    )
    if resp.status_code in (400, 401):
        # AAD answers a bad client id/secret with 400/401 and an error code only.
        try:
            code = resp.json().get("error") or ""
        except ValueError:
            code = ""
        raise CostApiError("forbidden", f"Azure AD token request was refused (HTTP {resp.status_code}) {code}".strip(), resp.status_code)
    _raise_for(resp, "Azure AD token request")
    return resp.json()["access_token"]


async def fetch_query_pages(client: httpx.AsyncClient, token: str, scope: str, body: dict) -> dict:
    """All pages of one query merged into a single payload (columns + rows)."""
    url = f"{MANAGEMENT_HOST}{scope}/providers/Microsoft.CostManagement/query?api-version={API_VERSION}"
    headers = {"Authorization": f"Bearer {token}"}
    columns: list = []
    rows: list = []
    pages = 0
    while url and pages < MAX_PAGES:
        resp = await client.post(url, json=body, headers=headers)
        _raise_for(resp, "Cost Management query")
        pages += 1
        if resp.status_code == 204:
            break
        props = (resp.json() or {}).get("properties") or {}
        columns = columns or props.get("columns") or []
        rows.extend(props.get("rows") or [])
        url = props.get("nextLink")
        # Never send the bearer token anywhere but Azure Resource Manager.
        if url and not url.lower().startswith(MANAGEMENT_HOST):
            raise CostApiError("error", "Cost Management returned a nextLink outside management.azure.com.")
    return {"properties": {"columns": columns, "rows": rows}, "pages": pages, "truncated": bool(url)}


# ── Job ──────────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _store(allocations: list[dict], start: date, end: date, agent_id: str | None) -> int:
    """Replace the stored metered rows of the collected window, so a re-run
    (Azure revises recent days for up to 72 h) or a removed link never
    leaves stale cost behind."""
    now = _utcnow()
    async with get_db_session() as db:
        stmt = delete(AgentInfraCost).where(
            AgentInfraCost.source == "azure", AgentInfraCost.cost_date >= start, AgentInfraCost.cost_date <= end,
        )
        if agent_id:
            stmt = stmt.where(AgentInfraCost.agent_id == agent_id)
        await db.execute(stmt)
        for a in allocations:
            db.add(AgentInfraCost(
                id=secrets.token_hex(12), agent_id=a["agent_id"], cost_date=a["cost_date"],
                resource_id=a["resource_id"][:500], service_name=a["service_name"][:150] if a["service_name"] else None,
                cost_cents=a["cost_cents"], currency=(a["currency"] or "USD")[:10], source="azure",
                allocation=a["allocation"], ingested_at=now,
            ))
    return len(allocations)


async def _load_links_and_agents() -> tuple[list[dict], list[str]]:
    async with get_db_session() as db:
        links = (await db.execute(select(AgentResourceLink))).scalars().all()
        agent_ids = list((await db.execute(select(Agent.id))).scalars().all())
    return [{"agent_id": l.agent_id, "resource_id": l.resource_id, "share_pct": l.share_pct} for l in links], agent_ids


async def collect_infra_costs(agent_id: str | None = None, trigger: str = "manual", days: int = 7) -> dict:
    """Pull the last `days` of daily ActualCost for AZURE_COST_SCOPE and store
    what can be allocated to agents. Never raises for an Azure failure: the
    status says what happened (ok | partial | not_configured | forbidden |
    throttled | unreachable | error)."""
    settings = get_settings()
    missing = missing_settings(settings)
    if missing:
        return {"status": "not_configured", "trigger": trigger, "missing": missing,
                "reason": "Azure Cost Management is not configured: set " + ", ".join(missing) + "."}

    days = min(max(int(days or 7), 1), MAX_DAYS)
    end = _utcnow().date()
    start = end - timedelta(days=days - 1)
    scope = "/" + settings.azure_cost_scope.strip().strip("/")
    tag_key = (settings.azure_cost_tag_key or "agent-id").strip()
    base = {"trigger": trigger, "from": start.isoformat(), "to": end.isoformat(), "tagKey": tag_key}

    try:
        async with _http_client() as client:
            token = await _access_token(client, settings)
            payload = await fetch_query_pages(client, token, scope, query_body(tag_key, start, end))
    except CostApiError as exc:
        log.warning("infra_costs.azure_failed", status=exc.status, http_status=exc.http_status)
        result = {**base, "status": exc.status, "reason": exc.reason, "httpStatus": exc.http_status}
        if exc.retry_after:
            result["retryAfterSeconds"] = exc.retry_after
        return result
    except httpx.RequestError as exc:
        log.warning("infra_costs.unreachable", error=type(exc).__name__)
        return {**base, "status": "unreachable", "reason": f"Azure did not answer ({type(exc).__name__})."}

    links, agent_ids = await _load_links_and_agents()
    try:
        parsed = parse_query_response(payload, tag_key, links, agent_ids=agent_ids)
    except ValueError as exc:
        return {**base, "status": "error", "reason": str(exc)}

    allocations = [a for a in parsed["allocations"] if agent_id is None or a["agent_id"] == agent_id]
    written = await _store(allocations, start, end, agent_id)
    status = "partial" if parsed["unallocated_cents"] > 0 or payload["truncated"] else "ok"
    return {
        **base,
        "status": status,
        "rows": written,
        "allocated_cents": sum(a["cost_cents"] for a in allocations),
        "unallocated_cents": parsed["unallocated_cents"],
        "unallocated_resources": parsed["unallocated_resources"],
        "agents": sorted({a["agent_id"] for a in allocations}),
        "pages": payload["pages"],
        "truncated": payload["truncated"],
    }
