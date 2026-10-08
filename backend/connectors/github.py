"""GitHub (or GitHub Enterprise), read-only: find repositories that build agents
before they run. It lists an organisation's repositories, reads each file tree,
and opens only dependency files, MCP configurations and agent cards to look for
signals. Source code is not read.

A repository becomes a finding when it shows at least one signal: an agent
framework dependency, an MCP server or configuration, or an A2A agent card."""
from __future__ import annotations

import base64
import json
import re
from typing import Any

import httpx

from connectors.base import ConnectorError, Finding

FRAMEWORKS = {
    "langgraph": "LangGraph", "langchain": "LangChain", "crewai": "CrewAI", "autogen": "AutoGen", "pyautogen": "AutoGen",
    "semantic-kernel": "Semantic Kernel", "semantic_kernel": "Semantic Kernel", "openai-agents": "OpenAI Agents SDK",
    "@openai/agents": "OpenAI Agents SDK", "llama-index": "LlamaIndex", "llama_index": "LlamaIndex", "haystack-ai": "Haystack",
    "google-adk": "Google ADK", "@mastra/core": "Mastra", "@langchain/langgraph": "LangGraph", "@langchain/core": "LangChain",
    "pydantic-ai": "Pydantic AI", "smolagents": "smolagents", "agno": "Agno", "strands-agents": "Strands Agents",
}
MCP_DEPS = ("mcp", "fastmcp", "@modelcontextprotocol/sdk")
TRACING_DEPS = {"openinference": "OpenInference", "arize-phoenix": "Phoenix", "langfuse": "Langfuse", "opentelemetry": "OpenTelemetry"}
DEP_FILES = re.compile(r"(^|/)(requirements[^/]*\.txt|pyproject\.toml|package\.json|Pipfile|setup\.py|setup\.cfg)$")
MCP_FILES = re.compile(r"(^|/)(\.?mcp(_config)?\.json|claude_desktop_config\.json|\.vscode/mcp\.json|\.cursor/mcp\.json)$")
CARD_FILES = re.compile(r"(^|/)\.well-known/(agent-card|agent)\.json$")
MAX_FILES_READ = 8
MAX_FILE_BYTES = 200_000


def _dep_hits(text: str) -> tuple[set[str], bool, set[str]]:
    """(frameworks, uses MCP, tracing) from a dependency file's text. Pure."""
    low = text.lower()
    names = set(re.findall(r'["\']?(@?[a-z0-9][a-z0-9_.\-/]*)["\']?\s*[:=<>~!\[,;\n]', low + "\n"))
    names |= set(re.findall(r"^\s*([a-z0-9][a-z0-9_.\-]*)", low, flags=re.M))
    frameworks = {label for dep, label in FRAMEWORKS.items() if dep in names or any(n.startswith(dep + "[") for n in names)}
    mcp = any(d in names for d in MCP_DEPS)
    tracing = {label for dep, label in TRACING_DEPS.items() if any(n.startswith(dep) for n in names)}
    return frameworks, mcp, tracing


class GitHubConnector:
    kind = "github"

    def __init__(self, settings: dict, secret: dict, transport: httpx.AsyncBaseTransport | None = None):
        self.api = (settings.get("apiUrl") or "https://api.github.com").rstrip("/")
        self.orgs = [o.strip() for o in (settings.get("orgs") or []) if o and o.strip()]
        self.max_repos = int(settings.get("maxRepos") or 100)
        self.token = secret.get("token") or ""
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        if not self.orgs:
            raise ConnectorError("not_configured", "Name at least one GitHub organisation or user.")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return httpx.AsyncClient(base_url=self.api, headers=headers, timeout=30, transport=self._transport)

    async def _get(self, client, path: str, **params) -> Any:
        try:
            r = await client.get(path, params=params or None)
        except httpx.HTTPError as exc:
            raise ConnectorError("unreachable", f"GitHub did not answer ({type(exc).__name__}).")
        if r.status_code == 401:
            raise ConnectorError("unauthorized", "GitHub refused the token.")
        if r.status_code == 403 and r.headers.get("x-ratelimit-remaining") == "0":
            raise ConnectorError("failed", "GitHub's rate limit is used up. Add a token, or try again in an hour.")
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise ConnectorError("failed", f"GitHub answered HTTP {r.status_code} for {path}.")
        return r.json()

    async def _repos(self, client, owner: str) -> list[dict]:
        out: list[dict] = []
        for base in (f"/orgs/{owner}/repos", f"/users/{owner}/repos"):
            page = 1
            while len(out) < self.max_repos:
                batch = await self._get(client, base, per_page=100, page=page, sort="pushed")
                if batch is None:
                    break
                out.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
            if out:
                break
        return out[: self.max_repos]

    async def _read(self, client, repo: str, path: str) -> str | None:
        body = await self._get(client, f"/repos/{repo}/contents/{path}")
        if not body or body.get("size", 0) > MAX_FILE_BYTES or body.get("encoding") != "base64":
            return None
        return base64.b64decode(body.get("content") or "").decode("utf-8", errors="replace")

    async def test(self) -> dict:
        async with self._client() as client:
            found = await self._repos(client, self.orgs[0])
        return {"ok": True, "message": f"Connected. {self.orgs[0]} has {len(found)} repositor{'y' if len(found) == 1 else 'ies'} visible."}

    async def scan_repo(self, client, repo: dict) -> Finding | None:
        full, branch = repo["full_name"], repo.get("default_branch") or "main"
        tree = await self._get(client, f"/repos/{full}/git/trees/{branch}", recursive="1")
        paths = [t["path"] for t in (tree or {}).get("tree", []) if t.get("type") == "blob"]
        frameworks: set[str] = set()
        tracing: set[str] = set()
        mcp = False
        card: dict | None = None
        reads = 0
        for path in paths:
            if reads >= MAX_FILES_READ:
                break
            if DEP_FILES.search(path):
                reads += 1
                text = await self._read(client, full, path)
                if text:
                    f, m, t = _dep_hits(text)
                    frameworks |= f
                    tracing |= t
                    mcp = mcp or m
            elif CARD_FILES.search(path) and card is None:
                reads += 1
                text = await self._read(client, full, path)
                try:
                    data = json.loads(text or "{}")
                    card = {"path": path, "name": data.get("name"), "description": data.get("description"),
                            "skills": [s.get("name") for s in data.get("skills") or [] if isinstance(s, dict)][:10]}
                except ValueError:
                    card = {"path": path, "name": None, "description": None, "skills": []}
        mcp_config = [p for p in paths if MCP_FILES.search(p)][:5]
        if not (frameworks or mcp or mcp_config or card):
            return None
        return Finding(kind="code_repo", external_id=full, name=(card or {}).get("name") or repo["name"], url=repo.get("html_url"),
                       details={"repo": full, "description": repo.get("description"), "language": repo.get("language"),
                                "frameworks": sorted(frameworks), "mcpServer": mcp, "mcpConfigs": mcp_config,
                                "agentCard": card, "tracing": sorted(tracing), "pushedAt": repo.get("pushed_at"),
                                "archived": bool(repo.get("archived")), "defaultBranch": branch})

    async def sync(self) -> list[Finding]:
        findings: list[Finding] = []
        async with self._client() as client:
            for owner in self.orgs:
                for repo in await self._repos(client, owner):
                    if repo.get("fork"):
                        continue
                    found = await self.scan_repo(client, repo)
                    if found:
                        findings.append(found)
        return findings
