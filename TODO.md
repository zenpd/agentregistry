# Agent Registry — Implementation Roadmap (High Level)

*What is done, what is missing, and the step-by-step order to close the gaps. Based on the V1/V2 feature plan vs. what is actually implemented today.*

---

## 1. Production-Ready Today

- **Registry core** — agent inventory CRUD, departments, lifecycle stages, filters/search
- **Governance** — 3 gates (ARB / Security / Data Protection), gate status flow, exceptions with expiry, recertification
- **Tokenomics analysis** — token usage accounting, model price catalogue, per-agent cost calculation, cost-per-invocation
- **Waste detection** — idle agents, model overkill, always-on monitors, RAG bloat (rule-based checks)
- **Impact analysis** — dependency graph, outage simulation, concentration risk
- **Agent offboarding** — 7-stage decommissioning workflow with credential revocation
- **Shadow AI classification** — discovery intake with confidence scoring and HIGH/MEDIUM/LOW risk
- **Risk classification** — dynamic risk based on revenue at stake
- **Agent identity** — service accounts, Entra-style IDs, API key hashing, revocation
- **Budget tracking** — monthly budget per agent with usage reporting
- **EU AI Act reporting** — risk-tier grouping of the portfolio (reporting only)
- **Predictive cost analysis** — 3-month cost projection

---

## 2. Missing Functionalities — Step by Step

### Step 1 — Make token data real
Token usage today comes from seed data. Nothing measures reality yet.
- Build the **OTel/Phoenix span collector** that turns live LLM traces into per-agent token usage
- Populate **daily agent metrics** (tokens, cost, error rate) so trend charts show truth
- Move token storage to a **time-series table** (hypertable) with monthly rollups

### Step 2 — Enforce budgets and stop runaway agents
Budgets are recorded but never enforced.
- Enforce **max tokens per invocation** at the runtime path
- Add the **circuit breaker**: hard stop, auto-pause on breach, max iterations
- Add **infinite-loop protection** with alerts to the owner

### Step 3 — Automate cost anomaly detection
Anomalies table exists; nothing detects them.
- Scheduled **spike / loop / budget-breach detection** jobs
- Owner notifications when an agent crosses its alert threshold

### Step 4 — Real discovery pipeline
Discovery currently scans only the registry's own database.
- Build collectors for the planned sources: **Vertex AI, GitHub config scanner, cloud logs, MCP gateway, network traffic analysis**
- Cross-source **dedup and entity resolution** so one agent found by three sources becomes one record
- **Discovery scheduling** so scans run periodically, not only on manual trigger

### Step 5 — Turn on governance enforcement
- **Enable RBAC** with the 5 planned roles (currently every logged-in user is admin) + user management screen
- **Runtime policy enforcement** — policy-as-code evaluated when agents are invoked, not just reviewed
- **EU AI Act assessment flow** — guided classification of each agent into risk tiers, with sign-off and conformity-assessment tracking
- **Cross-functional governance committee** — charter, review board queue, decision records
- **Workshop → funded pipeline** — track AI candidates from ideation workshop to funded initiative

### Step 6 — Token efficiency and routing
- **Model routing (70/20/10 strategy)** — route simple tasks to small models automatically
- **Cache optimization** — cache strategy, warming, and hit-rate reporting beyond raw cached-token counts
- **Cost per business outcome** — link token spend to the business value each agent claims
- **Prompt compression** — detect and fix prompt bloat (LLMLingua-style)
- **Conversation pruning** — sliding window / summary compression for long-running agents
- **Batch workload detection surfaced in UI** — detection exists in the API; make it visible and actionable

### Step 7 — MCP governance
- **Approval workflow** for registering MCP servers
- **Tool permission audit** — who/which agent can call which tool
- **MCP cost tracking** per the hybrid pricing model in the plan

### Step 8 — Portfolio experience
- **Global search drawer** across all agents, systems, databases
- **Quick registration** from any screen
- **Exports** — PDF gate reports, CSV waste reports
- **Trace viewer** — drill from an agent into its Phoenix traces in-app
- **AI ambition dashboard** — planned vs. actual portfolio view
- **Use case stitching** — link related agents into end-to-end business processes

---

## 3. Operational Foundations (run in parallel)

- Decide **SQLite (dev) vs Postgres (prod)** and keep Alembic migrations as the single source of truth
- **Scheduler** for all recurring jobs (discovery, waste, anomalies, recertification)
- **Temporal durability mode** for long-running workflows (worker exists, not used in dev)
- **Redis** for sessions/rate-limiting when running more than one worker
- **Test coverage** — end-to-end UI tests from UI_TEST_CASES.md; backend tests beyond health check
- **CI/CD** pipelines wired to real environments (pipeline files have placeholders)

---

## 4. Order of Attack (suggested)

1. Steps 1–2 (real token data + enforcement) — highest impact, everything else depends on real usage data
2. Step 4 (real discovery) — fills the registry with what actually exists
3. Step 5 (governance enforcement) — required before production rollout
4. Steps 3, 6, 7 — automation and optimization layers
5. Step 8 + ops work — polish, scale, compliance evidence
