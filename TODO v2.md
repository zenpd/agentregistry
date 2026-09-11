# Agent Registry — TODO v2 (Exhaustive)

*Deep module-by-module analysis of the current project merged with the full original TODO. The simple `TODO.md` is the summary; this file is the complete working backlog.*

**Legend:** 🔴 P0 · 🟠 P1 core product · 🟡 P2 frontend/UX · ⚪ P3 ops/scale · ✅ fixed in this session


---

## 1. Module-by-Module Maturity Matrix

| Module | State | Notes |
|---|---|---|
| `api/routers/registry.py` | 🟠 Functional | 40+ endpoints; V2 features partial (see §4) |
| `api/auth.py` | 🟠 Functional | JWT works; RBAC coded but disabled (admin-for-all) |
| `api/websocket_events.py` | 🔴 Stub | Connection manager + `broadcast_event()` exist, but **nothing publishes events and the UI never opens a socket** |
| `api/routers/orchestrations.py` | 🟠 Functional | 5 workflow triggers wired |
| `orchestrations/discovery_pipeline.py` | 🟠 Partial | Scans internal DB only; 5 sources; no external collectors |
| `orchestrations/governance_workflow.py` | 🟠 Partial | Rule-based criteria checks; no committee/OPA |
| `orchestrations/tokenomics_analysis.py` | 🟠 Partial | Analysis on seed data only |
| `orchestrations/waste_detection.py` | 🟠 Partial | 3–4 checks of the planned 10 |
| `orchestrations/impact_analysis.py` | 🟠 Partial | Traversal works; no $/hr blast radius |
| `db/models.py` | 🟢 Good | 18 tables incl. V2 stubs (model_routing, agent_metrics, phoenix_config) |
| `scripts/init_db.py` + `seed.py` | 🟢 Good | 22 agents, usage, prices, users, identities |
| `workers/worker.py` + `workflows/` | ⚪ Dormant | Temporal worker + durable workflow exist; routers run inline; never exercised |
| `agents/` (LangGraph) | ⚪ Baseline | Supervisor is rule-based (not LLM-routed); 1 example specialist; guardrails = history cap + 2 injection markers |
| `llm_client.py` | 🟢 Good design | Azure OpenAI + deterministic fallback |
| `evaluations/` | 🔴 Empty | No eval harness at all |
| `ingestion/connectors/` | 🔴 Empty | No external discovery/ingestion connectors |
| `config/rules/` | 🔴 Empty | No policy rules (OPA-ready dir, unused) |
| `config/prompts/` | 🟡 Minimal | supervisor + example_agent YAMLs; supervisor prompt not actually used by rule-based router |
| `services/audit.py` | 🟡 Thin | AuditLog written on CRUD; no query/API/UI to view audit trail |
| `alembic/versions/` | 🟠 Drift risk | Migration 0002 creates 14 tables; models now define ~18 (`phoenix_config`, `agent_metrics`, `model_routing` not in migrations) |
| `tests/` | 🔴 Thin | 1 health test; no router/orchestration/DB tests |
| `ui/src` (11 pages) | 🟠 Good | All pages call the API; several backend features have no UI (duplicates, identity UI, budget editor, forecast, trends, WS) |
| `ui` stores | 🟡 Minimal | `zustand` is a dependency but unused; auth token in localStorage only |
| `ui` e2e | 🔴 Absent | Playwright in devDependencies, no config, no tests (46 cases ready in UI_TEST_CASES.md) |
| `observability/tracing.py` | 🟢 Working | Phoenix OTLP + LangChain/OpenAI instrumentors verified end-to-end |
| `api/rate_limiting.py` | 🟡 OK for dev | In-memory per-process; breaks with >1 uvicorn worker |
| `security/vault.py` | 🟢 Wired | KV URI resolution verified in config |
| `infra/aca-setup.sh` + CI | 🟡 Placeholders | Pipeline vars/`__PLACEHOLDER__` not wired to a real environment |
| `docker-compose.yml` | 🟡 Unused locally | Full stack defined (pg, redis, temporal, phoenix) but Docker not available on this machine |
| LLM (Azure OpenAI) | 🔴 Blocked | 403 private-endpoint-only; DNS still public; pending Azure networking work |

---

## 2. 🔴 P0 — Blockers (before anything else)


- [ ] **JWT secret is a known default** (`AIREGISTRY_SECRET_KEY=change-me-...`) — tokens are forgeable by anyone with the repo; also the production startup guard checks `APP_SECRET_KEY` but **not** the key that actually signs JWTs. Generate a real secret + extend the guard.
- [ ] **Decide the dev/prod database** — SQLite vs Postgres — and make Alembic the source of truth (close the 4-table migration drift; add `alembic check` to CI).
- [ ] **Wire the WebSocket event bus** — publishers in orchestrations (discovery.new, budget.alert, anomaly.alert, token.update) + a UI consumer; today it's a disconnected stub.
- [ ] **A scheduler exists nowhere** — discovery, waste, anomaly, recertification, budget-reset jobs need a recurring runner (Temporal schedules or APScheduler).

## 3. 🟠 P1 — Core Backend (step by step)

### 3.1 Real token data (foundation for everything)
- [ ] OTel/Phoenix span collector → per-agent `agent_token_usage` rollups
- [ ] Populate `agent_metrics` daily (tokens, cost, error rate, efficiency) — table exists, never written
- [ ] Timescale/hypertable + monthly rollups for portfolio history

### 3.2 Enforcement layer
- [ ] Enforce `max_tokens_per_invocation` per agent at the runtime path
- [ ] Circuit breaker: `hard_stop_pct`, `auto_pause_on_breach`, `max_iterations` (fields exist, no code)
- [ ] Infinite-loop protection with owner notification

### 3.3 Cost anomaly engine
- [ ] Spike / loop / budget-breach detection jobs writing `cost_anomalies`
- [ ] Threshold alerts (email/Slack/WS) when spend crosses `alert_threshold_pct`

### 3.4 Discovery pipeline v2
- [ ] External collectors: Vertex AI, GitHub config scanner, cloud logs, MCP gateway, network traffic
- [ ] Cross-source dedup/entity-resolution (one agent found by 3 sources = one record)
- [ ] Scheduled discovery runs + confidence scoring per plan §5.5

### 3.5 Governance depth
- [ ] Enable RBAC (5 roles) + seed role users + user management UI
- [ ] Runtime policy enforcement (OPA) — evaluate rules at invocation time
- [ ] EU AI Act assessment flow (guided classification + sign-off; tier *reporting* exists)
- [ ] Cross-functional committee: charter, review board queue, decision records
- [ ] Workshop → funded initiative pipeline; use-case stitching
- [ ] Stage transition rules + time-in-stage alerts automation
- [ ] Recertification scheduler (endpoint exists; no periodic expiry)

### 3.6 Token efficiency & routing
- [ ] 70/20/10 model routing service (`model_routing` table exists, empty)
- [ ] Cache strategy + hit-rate optimization beyond raw cached-token counts
- [ ] Cost-per-business-outcome on real data (endpoint exists; metrics table is empty)
- [ ] Prompt compression (LLMLingua-style bloat detection)
- [ ] Conversation pruning (sliding window / summary compression + alerts)

### 3.7 Waste engine completion
- [ ] Add remaining waste types: orphaned, duplicate, retry-storm, context-bloat, deprecated-model, low-value (plan §9.1)
- [ ] Resolve/dismiss workflow endpoints for findings
- [ ] Batch-processing suggestions surfaced with actions

### 3.8 MCP governance
- [ ] MCP server approval workflow
- [ ] Tool-permission audit (which agent may call which tool)
- [ ] MCP cost tracking per hybrid pricing model

### 3.9 Agent lifecycle automation
- [ ] Auto-detect stalled agents → risk flags (partly in discovery scan; formalize)
- [ ] Offboarding stage 7 residual-validation job (7-day zero-invocation check is manual today)

## 4. 🟡 P2 — Frontend / UX

- [ ] TokenomicsView: per-agent trend chart, 3-month forecast, budget editor (endpoints exist, unused)
- [ ] Duplicates report UI (`/agents/duplicates` endpoint exists, never called)
- [ ] Identity/offboarding UI (endpoints exist: `identity`, `identity/revoke`, `offboard`, `recertify`)
- [ ] SecurityView: wire waste + cost-anomaly feeds (currently agent-derived only)
- [ ] SettingsPage: real Phoenix config CRUD (`phoenix_config` table has no router), model price editor, user management
- [ ] Playground degraded mode: works without Redis/LLM (deterministic fallback exists — surface it)
- [ ] Governance Kanban view (plan §7.2) — current table is status-only
- [ ] Global search drawer; quick-register from any screen
- [ ] Exports: PDF gate report, CSV waste report
- [ ] Trace viewer linking agents → Phoenix UI
- [ ] AI ambition dashboard (planned vs actual portfolio)
- [ ] Replace ad-hoc state with the unused zustand store; move token storage to httpOnly cookie (localStorage XSS exposure)

## 5. ⚪ P3 — Ops & Scale

- [ ] Temporal durability mode per environment; start worker in compose; migrate orchestrations from inline to workflows
- [ ] Redis in compose + local docs (required by Playground sessions; rate limiter should move to Redis for multi-worker)
- [ ] Backend test suite: auth, registry CRUD, tokenomics math, orchestrations, DB layer
- [ ] Playwright E2E from `UI_TEST_CASES.md` (config + first suite)
- [ ] Prometheus `/metrics` endpoint (deps commented out)
- [ ] Phoenix tracing for orchestration workflows (currently only API+LLM instrumented)
- [ ] Wire CI pipelines to real ACA environments; `infra/` beyond `aca-setup.sh`
- [ ] CORS hardening for prod origins (dev list hardcoded)
- [ ] Docs: API guide, user guide, runbook

## 5. Verification Checklist (definition of done)

- [ ] A live agent's real token usage appears in dashboards without manual seed
- [ ] An agent exceeding its budget is automatically paused and its owner notified
- [ ] An unregistered agent deployed on a platform is discovered, scored, and appears in the console
- [ ] A non-admin role cannot mutate the registry (RBAC provable)
- [ ] An invocation violating a runtime policy is blocked and audited
- [ ] Every EU AI Act high-risk agent has an assessment record
- [ ] WS clients receive live events during discovery/budget/anomaly runs
- [ ] E2E suite green in CI on every PR

---

## 6. Suggested Order of Attack

1. **P0** — JWT secret rotation + guard, DB decision, scheduler choice, WS wiring
2. **§3.1–3.3** — real token data, enforcement, anomalies (turns demo into product)
3. **§3.4** — discovery collectors + scheduling (fills the registry with reality)
4. **§3.5** — governance enforcement (RBAC, OPA, EU AI Act, committee)
5. **§3.6–3.8** — routing, cache, compression, MCP governance
6. **§4 + §5** — frontend completeness, e2e, observability, CI/CD
