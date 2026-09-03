# AIRegistry — Definitive Implementation Plan

> **Version:** FINAL · **Date:** 2026-09-01
> **Source of Truth:** `AIRegistry.html` prototype (1444 lines, 5 views, 22 agents, 5 stages, 3 gates, 26 features)
> **Research:** 50+ industry sources — AWS Agent Registry, Microsoft Entra Agent ID, Arthur AI ADG, OWASP Agentic Top 10, Growth Engineer benchmarks, BitAtlas MCP survey, Bacancy, Peliqan, Zylos, Nango, RouteLLM, and more
> **Purpose:** Zero-gap implementation plan. V2's comprehensive structure + prototype anchoring + all research integrated. Every section has ASCII diagrams, SQL schemas, API endpoints, and prototype references.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Prototype Feature Inventory](#2-prototype-feature-inventory)
3. [Lifecycle Stages — Deep Dive](#3-lifecycle-stages--deep-dive)
4. [Token-Level Monetization — Tokenomics Engine](#4-token-level-monetization--tokenomics-engine)
5. [Discovery Pipeline — How Agents Are Found](#5-discovery-pipeline--how-agents-are-found)
6. [Dependency Graph & Impact Analysis](#6-dependency-graph--impact-analysis)
7. [Governance & Compliance Model](#7-governance--compliance-model)
8. [Value Tracking & Executive Dashboards](#8-value-tracking--executive-dashboards)
9. [Waste Detection & Optimization](#9-waste-detection--optimization)
10. [Agent Identity & Offboarding](#10-agent-identity--offboarding)
11. [Integrations — How the Registry Connects](#11-integrations--how-the-registry-connects)
12. [Plugins & MCP Ecosystem](#12-plugins--mcp-ecosystem)
13. [System Architecture](#13-system-architecture)
14. [Database Schema](#14-database-schema)
15. [API Endpoints](#15-api-endpoints)
16. [Technical Stack](#16-technical-stack)
17. [Implementation Roadmap](#17-implementation-roadmap)
18. [ASCII Workflow Diagrams Master Index](#18-ascii-workflow-diagrams-master-index)

---

## 1. Executive Summary

AIRegistry (codenamed "THREAD") is an **Enterprise AI Control Tower** — a single pane of glass for every AI initiative across the organization: agents, copilots, predictive models, generative features, chatbots, and vision models.

### 1.1 Why This Exists

By 2028, the average Fortune 500 enterprise will have over 150,000 agents (up from fewer than 15 in 2025). Today, 82% of enterprises have unknown AI agents running in their infrastructure, and 65% have already experienced agent-related security incidents (Cloud Security Alliance, 2026).

AI agents consume 5 to 30 times more tokens than traditional chatbots. A single support agent running Claude Sonnet costs $1.60 per task unoptimized. At 10,000 tickets per month, that is $16,000 per month on LLM inference alone. Enterprise LLM spending hit $8.4 billion in the first half of 2025, with 40% of enterprises spending over $250,000 annually.

> **"Spend that cannot be attributed cannot be governed."** — TechRepublic, 2026

### 1.2 Competitive Landscape

| Product | Provider | What It Does | AIRegistry Differentiator |
|---|---|---|---|
| **Agent Registry (Agent 365)** | Microsoft | M365 agent inventory, Entra Agent ID | Multi-cloud, framework-agnostic, tokenomics |
| **Arthur AI ADG** | Arthur | Discovery + governance, 4 techniques | Token-level cost, waste detection, model routing |
| **AWS Agent Registry** | Amazon | Bedrock AgentCore, hybrid search | Open-source, multi-cloud, not AWS-only |
| **MCP Registry** | Open Standard | Versioned mcp.json, GitHub OAuth | Agent-level (not just MCP), full lifecycle |

> **"MCP is no longer an experiment — it's infrastructure."** — BitAtlas, Apr 2026

### 1.3 System Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    AIREGISTRY — Enterprise AI Control Tower                   │
│                 Registry · Value · Risk · Dependencies · Governance           │
│              Discovery · Tokenomics · Optimization · Identity                 │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│   ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌──────────┐ │
│   │ Discovery │  │  Registry │  │Dependency │  │Governance │  │  Value   │ │
│   │  Engine   │→│    SoR     │→│   Graph   │→│ Workbench │→│Dashboards│ │
│   └───────────┘  └───────────┘  └───────────┘  └───────────┘  └──────────┘ │
│        │                │              │              │              │       │
│        ▼                ▼              ▼              ▼              ▼       │
│   ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌──────────┐│
│   │ Tokenomics│  │  Agent    │  │   Waste   │  │ Executive │  │  Model   ││
│   │  Engine   │  │ Identity  │  │ Detection │  │ Insights  │  │ Routing  ││
│   └───────────┘  └───────────┘  └───────────┘  └───────────┘  └──────────┘│
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Prototype Feature Inventory

### 2.1 The 26 Implemented Features (Verified Line-by-Line)

The prototype implements exactly 26 features across 5 persona views. Every feature is implemented in plain HTML/CSS/JS with localStorage persistence:

| # | Feature | View | Prototype Lines | Data Source |
|---|---------|------|-----------------|-------------|
| F-01 | **Live ticker** (8 KPIs) | All | 892-911 | Computed from AGENTS array |
| F-02 | **Executive Overview** (5 KPIs + rail + bars) | Executive | 914-928 | Stages, types, values, risks |
| F-03 | **Portfolio pipeline rail** (5 stages, clickable) | Executive | 931-942 | STAGES array |
| F-04 | **Portfolio mix by AI type** (6 types) | Executive | 961-969 | TYPES array |
| F-05 | **Value by business unit** (bar chart) | Executive | 944-951 | dept + valueAmount |
| F-06 | **Needs attention** (risk list with notes) | Executive | 953-959 | atRisk=true agents |
| F-07 | **Top agents by value** (table, top 5) | Executive | 971-976 | valueAmount sorted |
| F-08 | **Business Impact** (filterable by dept) | Business | 979-1004 | dept filter |
| F-09 | **Enterprise systems cards** (counts) | Platform | 1082 | sysCounts |
| F-10 | **Databases & data platforms cards** | Platform | 1083 | dbCounts |
| F-11 | **MCP servers cards** | Platform | 1084 | mcpCounts |
| F-12 | **Knowledge bases cards** | Platform | 1085 | kbCounts |
| F-13 | **Concentration risk** (4+ agents) | Platform | 1013-1024 | sysCounts/dbCounts ≥4 |
| F-14 | **Cross-AI call network** (SVG graph + table) | Platform | 1030-1069 | calls + EDGE_REASONS |
| F-15 | **Initiative→integration matrix** | Platform | 1070-1080 | enterpriseSystems + databases |
| F-16 | **Governance KPIs** (4 cards) | Governance | 1099-1104 | reviews aggregate |
| F-17 | **Gate breakdown** (3 gates × 5 statuses) | Governance | 1106-1113 | GATES × REVIEW_STATUSES |
| F-18 | **Review status by agent** (table + update) | Governance | 1115-1118 | reviews per agent |
| F-19 | **Auto AI discovery feed** (5 discoveries) | Governance | 1120-1128 | DISCOVERIES array |
| F-20 | **Discovery actions** (register/dismiss) | Governance | 1134-1143 | registeredIds/dismissedIds |
| F-21 | **Registry search/filter** (4 filters + cat chips) | Registry | 1266-1289 | search, type, stage, dept |
| F-22 | **Registry cards grid** (with dep badges) | Registry | 1279-1288 | AGENTS array |
| F-23 | **Agent detail modal** (graph + metadata) | Registry | 1291-1326 | per-agent details |
| F-24 | **Add agent form** (13 fields) | Registry | 1329-1360 | customAgents |
| F-25 | **Governance review modal** (3 gates + notes) | Governance | 1145-1181 | REVIEW_OVERRIDES |
| F-26 | **localStorage persistence** (4 keys) | All | 852-864 | 4 localStorage keys |

### 2.2 Prototype Data Constants

```
STAGES (5):        Ideation, Development, Testing, Production, Deprecated
TYPES (6):         Autonomous Agent, Copilot / Assistant, Predictive / ML Model,
                   Generative AI Feature, Conversational AI / Chatbot, Computer Vision Model
GATES (3):         arb (Architecture Review Board), security (Security Review),
                   dp (Data Protection Review)
REVIEW_STATUSES (5): Not Submitted, In Review, Changes Requested,
                     Approved with Conditions, Approved
DEPARTMENTS (9):   Finance, Legal, HR, Sales, Customer Support,
                   Supply Chain, IT Operations, Marketing, Engineering
AGENTS (22):       inv-recon, contract-review, candidate-screen, onboarding,
                   lead-scoring, proposal-drafter, support-triage, refund-adjudication,
                   demand-forecast, supplier-risk, incident-copilot, change-validator,
                   access-review, campaign-copy, market-digest, expense-audit,
                   churn-predictor, fraud-detection, hr-chatbot, defect-vision,
                   code-review-copilot, pricing-optimizer
DISCOVERIES (5):   disc-1 (bulk-uploader.py, Snowflake, 82%),
                   disc-2 (Legal Slack bot, Slack, 91%),
                   disc-3 (svc_ai_ticket_bot, ServiceNow, 76%),
                   disc-4 (auto-pr-reviewer, GitHub, 88%),
                   disc-5 (deal-qualifier, Salesforce, 69%)
EDGES (6):         inv-recon→expense-audit, onboarding→access-review,
                   lead-scoring→proposal-drafter, support-triage→refund-adjudication,
                   incident-copilot→access-review, market-digest→campaign-copy
```

### 2.3 What This Plan Adds Beyond the Prototype

| Prototype Has | This Plan Adds | Research Source |
|---|---|---|
| 22 agents (hardcoded) | Tokenomics engine with per-agent cost tracking | Growth Engineer benchmarks |
| 5 discoveries (hardcoded) | 10-source discovery pipeline with confidence scoring | Arthur AI ADG |
| MCP server cards (counts) | MCP governance with 5-layer model + pricing data | BitAtlas, Bacancy, Peliqan |
| Governance gates (manual) | Risk-based tiers (LOW/HIGH/UNACCEPTABLE) | EU AI Act, Gartner |
| change-validator sunset date | 7-stage decommissioning workflow | TrueFoundry playbook |
| No authentication | 5 auth models + 4-question framework | Nango, Microsoft Graph |
| localStorage persistence | PostgreSQL + TimescaleDB + Redis | Architecture best practices |
| Static dependency graph | Outage simulation + concentration risk scoring | RTS Labs |
| No cost data | Full financial model with industry benchmarks | Zylos, TokenFence, Kunal Ganglani |

---

## 3. Lifecycle Stages — Deep Dive

### 3.1 Stage Definitions

The prototype defines 5 lifecycle stages. Each has a specific color, gate requirement, maximum time, and exit condition:

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                           LIFECYCLE PIPELINE                                      │
│                                                                                   │
│  ┌──────────┐    ┌────────────┐    ┌─────────┐    ┌───────────┐    ┌──────────┐ │
│  │ IDEATION │───→│DEVELOPMENT │───→│ TESTING │───→│PRODUCTION │───→│DEPRECATED│ │
│  │          │    │            │    │         │    │           │    │          │ │
│  │ Gray     │    │ Purple     │    │ Amber   │    │ Teal      │    │ Coral    │ │
│  │ #6E7B8F  │    │ #8C7CF0    │    │ #F0A85A │    │ #3DDBD9   │    │ #E06B85  │ │
│  └──────────┘    └────────────┘    └─────────┘    └───────────┘    └──────────┘ │
│       │               │               │               │                │         │
│       ▼               ▼               ▼               ▼                ▼         │
│  ┌──────────┐    ┌────────────┐    ┌─────────┐    ┌───────────┐    ┌──────────┐ │
│  │ No gates │    │ ARB submit │    │ All 3   │    │ Monitor   │    │ Sunsets  │ │
│  │ required │    │ required   │    │ gates   │    │ value +   │    │ on date  │ │
│  │          │    │            │    │ must be │    │ tokens    │    │          │ │
│  │          │    │            │    │ approve │    │           │    │          │ │
│  └──────────┘    └────────────┘    └─────────┘    └───────────┘    └──────────┘ │
│                                                                                   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Stage Metadata

| Stage | Color | Gate Requirement | Max Time | Exit Condition | Prototype Count |
|---|---|---|---|---|---|
| **Ideation** | Gray #6E7B8F | None | Unlimited (flag at 20w) | ARB submitted | 1 (supplier-risk) |
| **Development** | Purple #8C7CF0 | ARB: In Review | Unlimited (flag at 12w) | ARB approved | 2 (proposal-drafter, market-digest) |
| **Testing** | Amber #F0A85A | All 3: In Review | 8 weeks | All 3 approved | 3 (contract-review, refund-adjudication, access-review) |
| **Production** | Teal #3DDBD9 | All 3: Approved | Ongoing | Retired/Deprecated | 16 agents |
| **Deprecated** | Coral #E06B85 | Sunset date set | 12 weeks | Fully removed | 1 (change-validator) |

### 3.3 Stage Transition Rules

```
STAGE TRANSITION WORKFLOW:
─────────────────────────

[Ideation] ──ARB submitted──→ [Development]
    │                              │
    │                              ├──ARB approved──→ [Testing]
    │                              │                      │
    │                      ARB changes                   ├──All gates approved──→ [Production]
    │                       requested                     │                          │
    │                              │                      │                    Value drops
    │                              ←──────────────────────│                    OR duplicate
    │                              │                      │                    found
    │                              │                      │                          │
    │                              │                      └────Changes────←──────────┘
    │                              │                        requested        │
    │                              │                                         ▼
    │                              │                                   [Deprecated]
    │                              │                                         │
    │                              │                                   Sunset date
    │                              │                                    reached
    │                              │                                         │
    └──────────────────────────────└─────────────────────────────────────────┘
                                        (can loop back at any point)
```

### 3.4 Time-in-Stage Alerts

| Stage | Warning (weeks) | Critical (weeks) | Action | Prototype Example |
|---|---|---|---|---|
| Ideation | 12 | 20 | "Stalled — re-sponsor or archive" | supplier-risk (20w, at-risk) |
| Development | 8 | 16 | "Build risk — review scope" | — |
| Testing | 6 | 8 | "Gate bottleneck — escalate" | — |
| Production | N/A | N/A | Monitor via tokenomics | — |
| Deprecated | 8 | 12 | "Decommission overdue" | change-validator (12w, at-risk) |

### 3.5 Research-Backed Enhancements

**Risk-based gate tiers (Gartner):** Instead of requiring all 3 gates for every agent, use risk classification. LOW-risk agents (internal model, read-only, no PII) need only 1 gate. HIGH-risk agents (external model, write access, PII) need all 3 gates. UNACCEPTABLE-risk agents (EU AI Act high-risk category, no human oversight) are blocked entirely.

**Recertification workflow:** Research shows that 90-day recertification cycles are industry best practice. The implementation should auto-create review tasks for every agent in Production that has not been reviewed in 90 days.

> **"60-72% of AI agent pilots stall before production. Of those that reach production, 35-45% are deprecated within 12 months."** — BCG, McKinsey, IDC 2026

---

## 4. Token-Level Monetization — Tokenomics Engine

### 4.1 Concept: Tokenomics in AIRegistry

The prototype tracks value (valueAmount) but not cost. This is the most critical gap. Without cost tracking, you cannot compute ROI, detect waste, or make informed decisions. The tokenomics engine fills this gap.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                     TOKENOMICS ENGINE — HOW IT WORKS                          │
│                                                                               │
│   AssureAI has:                          AIRegistry adds:                     │
│   ┌────────────────────┐                 ┌────────────────────────────┐      │
│   │ Phoenix traces     │                 │ Per-agent token accounting │      │
│   │ with token counts  │        +        │ × per-model pricing        │      │
│   │ per span           │                 │ × per-department chargeback│      │
│   └────────────────────┘                 └────────────────────────────┘      │
│                                                                               │
│   Result:                                                                    │
│   ┌────────────────────────────────────────────────────────────────────┐     │
│   │  "Invoice Reconciliation Agent" v3.1                              │     │
│   │  ├── Model: GPT-5  →  2.4M input × $2.50/1M = $6.00             │     │
│   │  ├── Model: GPT-5  →  0.8M output × $15.00/1M = $12.00          │     │
│   │  ├── Cache hits: 38% → saved $3.72                               │     │
│   │  ├── Invocations: 14,200 → cost/invocation = $0.26              │     │
│   │  └── Monthly total: $3,700 → vs budget $5,000 → UNDER            │     │
│   └────────────────────────────────────────────────────────────────────┘     │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Token Cost Benchmarks (Industry Data 2026)

| Task Type | LLM Calls | Avg Tokens/Task | Cost at $15/M | Agent Multiplier |
|---|---|---|---|---|
| Simple chatbot query | 1 | ~800 | $0.012 | 1× |
| Basic RAG pipeline | 2-3 | ~3,000 | $0.045 | 4× |
| Coding agent (bug fix) | 8-15 | ~18,000 | $0.27 | 22× |
| Research agent (multi-step) | 12-20 | ~35,000 | $0.53 | 44× |
| Customer service agent (complex) | 5-10 | ~10,000 | $0.15 | 12× |

> **Key insight:** AI agents consume **5-30× more tokens** than traditional chatbots. A support ticket agent running Claude Sonnet costs **$1.60/task** unoptimized. At 10,000 tickets/month = **$16,000/month** on LLM inference alone.

### 4.3 Token Data Flow

```
TOKEN DATA FLOW:
────────────────

                    ┌─────────────────────┐
                    │  Agent Runtime      │
                    │  (LangGraph/ADK/    │
                    │   Vertex Agent      │
                    │   Engine/etc.)      │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  OpenTelemetry      │
                    │  Span Export        │
                    │  (OTLP/HTTP)        │
                    └──────────┬──────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         │                     │                     │
         ▼                     ▼                     ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ Phoenix/        │  │ AIRegistry      │  │ Tokenomics      │
│ Arize           │  │ Collector       │  │ Calculator      │
│ (Traces +       │  │ (hourly job)    │  │ (real-time      │
│  span_costs)    │  │                 │  │  aggregation)   │
└─────────────────┘  └────────┬────────┘  └────────┬────────┘
                              │                     │
                              └──────────┬──────────┘
                                         │
                              ┌──────────▼──────────┐
                              │  Token Usage        │
                              │  Hypertable         │
                              │  (TimescaleDB)      │
                              └──────────┬──────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    │                    │                    │
                    ▼                    ▼                    ▼
           ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
           │ Cost per     │    │ Budget       │    │ Optimization │
           │ Agent        │    │ Alerts       │    │ Suggestions  │
           └──────────────┘    └──────────────┘    └──────────────┘
```

### 4.4 Token Pricing Reference (2026 — Verified)

| Model | Input $/1M | Output $/1M | Cache Read $/1M | Tier |
|---|---|---|---|---|
| GPT-5.5 | $5.00 | $30.00 | $0.50 | Frontier |
| GPT-5 | $2.50 | $15.00 | $0.25 | Frontier |
| GPT-5-mini | $0.75 | $4.50 | $0.08 | Mid-tier |
| GPT-5-nano | $0.20 | $1.25 | $0.02 | Lightweight |
| Claude Opus 4.8 | $5.00 | $25.00 | $0.50 | Frontier |
| Claude Sonnet 4.5 | $3.00 | $15.00 | $0.30 | Mid-tier |
| Claude Haiku 4.5 | $1.00 | $5.00 | $0.10 | Lightweight |
| Gemini 3.1 Pro | $3.50 | $10.50 | $0.35 | Frontier |
| Gemini 2.5 Flash | $0.75 | $3.00 | $0.08 | Mid-tier |
| DeepSeek-V4-Pro | $0.44 | $1.87 | — | Budget |

> **Cost differential:** Frontier models cost **100-300× more** than small models. A task routed to a frontier model costs **190× more** than the same task on a small model.

### 4.5 Token Cost Calculation

```
TOKEN COST FORMULA:
───────────────────

Per-Invocation Cost:
  = (input_tokens / 1,000,000 × model_input_price)
  + (output_tokens / 1,000,000 × model_output_price)
  - (cached_tokens / 1,000,000 × cache_read_price)

Monthly Agent Token Cost:
  = Σ(per_invocation_cost) + infrastructure_cost

Where infrastructure_cost includes:
  - Cloud compute (Cloud Run, Vertex, container)
  - MCP server hosting
  - Orchestration overhead (LangGraph state, etc.)
  - Monitoring/observability (OTel collector, Phoenix)

COST WATERFALL (per agent per month):
─────────────────────────────────────

  Total LLM Token Cost
  ├── Input tokens cost  (typically 60-75% of total)
  ├── Output tokens cost (typically 25-40% of total)
  └── Cache savings      (negative, -5% to -40%)

  + Infrastructure Cost
  ├── Compute (CPU/GPU)
  ├── Memory
  └── Network egress

  = Gross Monthly Cost
  - Credits / Reserved capacity discounts
  = Net Monthly Cost

  / Invocations = Cost per Invocation
```

### 4.6 Tokenomics Dashboard View

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  TOKENOMICS — Invoice Reconciliation Agent                        [v3.1] [Live]│
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────────────────┐  ┌──────────────┐  ┌─────────────────────────┐  │
│  │ MONTHLY COST            │  │ COST/INVOC.  │  │ BUDGET                  │  │
│  │ $3,700                  │  │ $0.26        │  │ $5,000  ████████░░ 74%  │  │
│  │ ▼ 12% vs last month     │  │ ▼ 8% vs LM   │  │ $1,300 remaining        │  │
│  └─────────────────────────┘  └──────────────┘  └─────────────────────────┘  │
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  TOKEN USAGE — 30 DAY TREND                                             │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │ │
│  │  │  ████████████████████████████████████████████████  Input      │   │ │
│  │  │  ███████████████                               Output       │   │ │
│  │  │  ████████                                      Cache hits   │   │ │
│  │  │                                                 (saved $1,480)│   │ │
│  │  └─────────────────────────────────────────────────────────────────┘   │ │
│  │  M    T    W    T    F    S    S    M    T    W    T    F    S    S   │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
│  ┌─────────────────────────────┐  ┌─────────────────────────────────────────┐│
│  │ MODEL BREAKDOWN             │  │ TOKEN EFFICIENCY                       ││
│  │                             │  │                                         ││
│  │ GPT-5      $3,700 (100%)    │  │ Cache hit rate:  38%  ████████░░░      ││
│  │  (could use GPT-5-mini)     │  │ Avg input/request: 2,400 tokens         ││
│  │                             │  │ Avg output/request: 850 tokens          ││
│  │ Suggestion:                 │  │ Token growth: +2.1% MoM                 ││
│  │ └─ GPT-5-mini could save    │  │ Cost per outcome: $0.26/invoice        ││
│  │    $2,590/mo (70%) for      │  │                                         ││
│  │    this task complexity     │  │ OPTIMIZATION:                           ││
│  │                             │  │ → Downgrade to GPT-5-mini              ││
│  │                             │  │ → Potential savings: $2,590/mo          ││
│  └─────────────────────────────┘  └─────────────────────────────────────────┘│
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 4.7 Predictive Cost Analysis

```
PREDICTIVE COST ANALYSIS:
═════════════════════════

Phase 1: Baseline Establishment (4-6 weeks)
├── Monitor consumption patterns before setting limits
├── Understand normal variation before defining abnormal
└── Per-agent baseline: avg tokens/day, cost/day, latency

Phase 2: Trend Analysis
├── Identify gradual cost increases before budget crisis
├── A 5% weekly increase compounds to 12x annual increase
├── MoM token growth rate per agent
└── Cost per outcome trend (should decrease over time)

Phase 3: Anomaly Detection
├── Flag sudden consumption spikes immediately
├── A single misconfigured agent can consume a month's budget in hours
├── Alert thresholds: >2x daily avg = warning, >5x = critical
└── Auto-pause agents exceeding 3x their hourly budget

Phase 4: Forecasting
├── 3-month cost projection based on growth trends
├── Budget depletion date prediction
└── "At current burn rate, budget exhausted in X days" alerts
```

### 4.8 Token Budget Enforcement

```
TOKEN BUDGETS BY AGENT TYPE:
════════════════════════════

┌─────────────────────────┬──────────────┬──────────────────────────────┐
│ Agent Type              │ max_tokens   │ Notes                        │
├─────────────────────────┼──────────────┼──────────────────────────────┤
│ Classification          │ 10-20        │ Single label output          │
│ Support reply           │ 300-500      │ Short conversational         │
│ Code generation         │ 1,000-2,000  │ Function-level               │
│ Content creation        │ 1,500-3,000  │ Article/email length         │
│ Research synthesis      │ 2,000-4,000  │ Multi-source summary         │
│ Complex reasoning       │ 4,000-8,000  │ Multi-step analysis          │
└─────────────────────────┴──────────────┴──────────────────────────────┘

ENFORCEMENT:
  Hard stop: agent cannot exceed max_tokens per invocation
  Soft warning: alert at 80% of budget
  Monthly cap: auto-pause agent at monthly budget limit
```

### 4.9 Infinite Loop Protection

```
INFINITE LOOP PROTECTION:
═════════════════════════

Incident Reference: Nov 2025, two LangChain agents entered infinite
conversation cycle, ran for 11 days, generated $47,000 bill.

PROTECTION MECHANISMS:
──────────────────────

1. MAX_ITERATIONS per agent run
   Default: 20 iterations, configurable per agent
   
2. MAX_TOKEN_BUDGET per agent run
   Default: 100K tokens, configurable per agent
   
3. CIRCUIT BREAKER
   If error_rate > 50% over 5 consecutive runs → auto-pause
   
4. CONVERSATION DEPTH LIMIT
   Max 10 turns per agent-to-agent handoff chain
   
5. COST RATE LIMIT
   If $/hour > 10× historical avg → auto-pause + alert
   
6. DEAD MAN'S SWITCH
   If agent runs > 2× expected duration → kill + alert
```

### 4.10 The 70/20/10 Model Routing Strategy

The single most impactful optimization is model routing — sending each task to the cheapest model that can handle it. Research from AgentMarketCap and RouteLLM shows that a 70/20/10 split (70% lightweight, 20% mid-tier, 10% frontier) reduces costs by 60-80% while maintaining 95% of frontier quality.

| Tier | Query Type | Models | Cost/Task | Volume |
|---|---|---|---|---|
| T1 — Lightweight (70%) | Classification, routing, formatting | GPT-5-nano, Haiku 4.5 | $0.001-$0.01 | 70% |
| T2 — Mid-tier (20%) | Moderate reasoning, code completion | GPT-5-mini, Gemini Flash | $0.02-$0.05 | 20% |
| T3 — Frontier (10%) | Complex reasoning, architecture | GPT-5, Claude Sonnet 4.5 | $0.10-$0.24 | 10% |

Applied to the prototype's 22 agents, this routing strategy would reduce the monthly LLM cost from $10,500 to approximately $3,100-$4,200 — a 60-70% reduction.

### 4.11 Tokenomics Schema (Database)

```sql
-- Token prices (admin-editable, versioned)
CREATE TABLE model_token_prices (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name      VARCHAR(100) NOT NULL,
    provider        VARCHAR(50) NOT NULL,
    input_price_per_1m       DECIMAL(10,4) NOT NULL,
    output_price_per_1m      DECIMAL(10,4) NOT NULL,
    cache_read_price_per_1m  DECIMAL(10,4) DEFAULT 0,
    tier                     VARCHAR(20) NOT NULL,  -- 'frontier', 'mid', 'lightweight'
    effective_from  TIMESTAMPTZ NOT NULL DEFAULT now(),
    effective_to    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Per-agent token usage (hourly hypertable)
CREATE TABLE agent_token_usage (
    agent_id        UUID NOT NULL REFERENCES agents(id),
    bucket          TIMESTAMPTZ NOT NULL,
    model_name      VARCHAR(100) NOT NULL,
    invocation_count INTEGER NOT NULL DEFAULT 0,
    input_tokens    BIGINT NOT NULL DEFAULT 0,
    output_tokens   BIGINT NOT NULL DEFAULT 0,
    cached_tokens   BIGINT NOT NULL DEFAULT 0,
    cost_cents      BIGINT NOT NULL DEFAULT 0,
    latency_avg_ms  INTEGER,
    error_count     INTEGER NOT NULL DEFAULT 0,
    iterations_max  INTEGER,
    PRIMARY KEY (agent_id, bucket, model_name)
);

SELECT create_hypertable('agent_token_usage', 'bucket');

-- Per-agent budget tracking
CREATE TABLE agent_budgets (
    agent_id        UUID PRIMARY KEY REFERENCES agents(id),
    monthly_budget_cents  BIGINT NOT NULL,
    alert_threshold_pct   INTEGER NOT NULL DEFAULT 80,
    hard_stop_pct         INTEGER NOT NULL DEFAULT 100,
    current_month_spend_cents BIGINT NOT NULL DEFAULT 0,
    budget_reset_day      INTEGER NOT NULL DEFAULT 1,
    max_tokens_per_invocation INTEGER,
    max_iterations        INTEGER DEFAULT 20,
    auto_pause_on_breach  BOOLEAN DEFAULT true,
    last_alert_sent       TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Anomaly detection log
CREATE TABLE cost_anomalies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID NOT NULL REFERENCES agents(id),
    anomaly_type    VARCHAR(50) NOT NULL,  -- 'spike', 'loop', 'budget_breach', 'iteration_exceed'
    severity        VARCHAR(20) NOT NULL,  -- 'warning', 'critical'
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    details         JSONB,
    resolved_at     TIMESTAMPTZ,
    resolved_by     VARCHAR(255)
);

-- Materialized view: daily token summary per agent
CREATE MATERIALIZED VIEW agent_token_daily AS
SELECT
    agent_id,
    model_name,
    time_bucket('1 day', bucket) AS day,
    SUM(invocation_count) AS invocations,
    SUM(input_tokens) AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    SUM(cached_tokens) AS total_cached_tokens,
    SUM(cost_cents) AS total_cost_cents,
    AVG(latency_avg_ms) AS avg_latency_ms,
    SUM(error_count) AS total_errors,
    MAX(iterations_max) AS max_iterations_seen
FROM agent_token_usage
GROUP BY agent_id, model_name, day;

-- Materialized view: monthly token summary per department
CREATE MATERIALIZED VIEW dept_token_monthly AS
SELECT
    a.dept,
    time_bucket('1 month', t.bucket) AS month,
    SUM(t.invocation_count) AS total_invocations,
    SUM(t.input_tokens) AS total_input_tokens,
    SUM(t.output_tokens) AS total_output_tokens,
    SUM(t.cost_cents) AS total_cost_cents,
    COUNT(DISTINCT t.agent_id) AS agent_count
FROM agent_token_usage t
JOIN agents a ON a.id = t.agent_id
GROUP BY a.dept, month;
```

### 4.12 Tokenomics API Endpoints

```
TOKENOMICS API:
───────────────

# Model pricing
GET    /api/v1/models/prices              → list current model prices
PUT    /api/v1/models/prices/{model}      → update pricing (versioned)

# Per-agent token data
GET    /api/v1/agents/{id}/tokens          → token usage (filter: ?from=&to=&granularity=hourly|daily|monthly)
GET    /api/v1/agents/{id}/tokens/summary  → aggregated summary
GET    /api/v1/agents/{id}/tokens/trend    → 30-day trend data
GET    /api/v1/agents/{id}/cost            → cost breakdown
GET    /api/v1/agents/{id}/cost/forecast   → 3-month projection

# Budget
GET    /api/v1/agents/{id}/budget          → budget status
PUT    /api/v1/agents/{id}/budget          → set/update budget

# Anomalies
GET    /api/v1/anomalies                   → list cost anomalies
POST   /api/v1/anomalies/{id}/resolve      → mark as resolved

# Department-level
GET    /api/v1/departments/{dept}/tokens   → dept token summary
GET    /api/v1/departments/{dept}/cost     → dept cost breakdown

# Portfolio-level
GET    /api/v1/portfolio/tokens            → all agents token overview
GET    /api/v1/portfolio/cost              → portfolio cost rollup
GET    /api/v1/portfolio/cost-forecast     → 3-month projection
GET    /api/v1/portfolio/efficiency        → token efficiency metrics
```

---

## 5. Discovery Pipeline — How Agents Are Found

### 5.1 Discovery Source Matrix (10 Sources)

| # | Source | Method | Frequency | What It Discovers | Prototype Equivalent |
|---|---|---|---|---|---|
| 1 | Vertex AI / Agent Engine | API query | Hourly | Deployed agents, model references | — |
| 2 | GitHub Config Scans | Parse agent.yaml, graph.py | Daily | Agent definitions from code | disc-4 (auto-pr-reviewer) |
| 3 | Cloud Asset Inventory | SearchAllResources API | Daily | AI-adjacent GCP resources | — |
| 4 | Cloud Logging / OTel | Log query: AGENT spans | Continuous | Runtime agent invocations | disc-3 (svc_ai_ticket_bot) |
| 5 | Phoenix / Arize | Phoenix REST API: /v1/spans | Continuous | Span-based discovery with hierarchies | disc-1 (bulk-updater.py) |
| 6 | Copilot Published Agents | Agent Registry API | Weekly | Published agent records | — |
| 7 | ServiceNow / SEAR | ServiceNow API | Weekly | SEAR approval records | — |
| 8 | DLP / IAM | Cloud DLP + IAM analyzer | Weekly | PII-adjacent datasets | — |
| 9 | MCP Gateway | MCP endpoint discovery | Daily | Active MCP servers | — |
| 10 | Network Layer Analysis | Traffic inspection, DNS monitoring | Continuous | Uninstrumented agents, shadow AI | disc-5 (deal-qualifier) |

### 5.2 The Four Essential Discovery Techniques (Arthur AI Framework)

```
THE FOUR ESSENTIAL DISCOVERY TECHNIQUES:
════════════════════════════════════════

┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                               │
│  ┌─────────────────────┐  ┌─────────────────────┐                           │
│  │ 1. TELEMETRY-BASED  │  │ 2. MCP SERVER       │                           │
│  │    DISCOVERY (OTel) │  │    MONITORING       │                           │
│  │                     │  │                     │                           │
│  │ OTel streams detect │  │ Detect new MCP      │                           │
│  │ agent framework     │  │ servers as they     │                           │
│  │ signatures, new     │  │ appear, monitor     │                           │
│  │ tools, config       │  │ for new agents      │                           │
│  │ changes             │  │ coming online       │                           │
│  └──────────┬──────────┘  └──────────┬──────────┘                           │
│             │                        │                                       │
│             │    ┌───────────────────┼───────────────────┐                   │
│             │    │                   │                   │                   │
│             ▼    ▼                   ▼                   ▼                   │
│  ┌─────────────────────┐  ┌─────────────────────┐                           │
│  │ 3. NETWORK LAYER    │  │ 4. API-DRIVEN       │                           │
│  │    ANALYSIS         │  │    DISCOVERY        │                           │
│  │                     │  │                     │                           │
│  │ Traffic inspection, │  │ Query Vertex AI,    │                           │
│  │ DNS monitoring,     │  │ Bedrock, Copilot    │                           │
│  │ TLS fingerprinting  │  │ APIs for deployed   │                           │
│  │ for AI services     │  │ agents              │                           │
│  └──────────┬──────────┘  └──────────┬──────────┘                           │
│             │                        │                                       │
│             └──────────┬─────────────┘                                       │
│                        │                                                     │
│                        ▼                                                     │
│             ┌─────────────────────┐                                          │
│             │   DETECTION MESH    │                                          │
│             │   (together = near  │                                          │
│             │    100% coverage)   │                                          │
│             └─────────────────────┘                                          │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Discovery Pipeline Flow

```
DISCOVERY PIPELINE:
═══════════════════

┌──────────────────────────────────────────────────────────────────────────────┐
│                        DISCOVERY COLLECTORS                                   │
│                                                                               │
│  Cloud Scheduler (hourly/daily/weekly triggers)                               │
│         │                                                                     │
│         ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │                    Raw Discovery Jobs                                 │     │
│  │                                                                       │     │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │     │
│  │  │ Vertex   │ │ GitHub   │ │ Cloud    │ │ Cloud    │ │ MCP      │ │     │
│  │  │ AI       │ │ Config   │ │ Asset    │ │ Logging  │ │ Gateway  │ │     │
│  │  │ Collector│ │ Collector│ │ Collector│ │ Collector│ │ Collector│ │     │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ │     │
│  │       │            │            │            │            │         │     │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐                              │     │
│  │  │ Network  │ │ Phoenix  │ │ServiceNow│  ...more sources            │     │
│  │  │ Layer    │ │ / OTel   │ │ / SEAR   │                              │     │
│  │  │ Collector│ │ Collector│ │ Collector│                              │     │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘                              │     │
│  │       │            │            │                                     │     │
│  │       ▼            ▼            ▼                                     │     │
│  │  ┌──────────────────────────────────────────────────────────────┐  │     │
│  │  │              RAW LANDING ZONE (append-only)                   │  │     │
│  │  │  raw_vertex_agents, raw_github_configs, raw_gcp_resources,   │  │     │
│  │  │  raw_agent_traces, raw_mcp_servers, raw_network_flows       │  │     │
│  │  └──────────────────────────┬───────────────────────────────────┘  │     │
│  └─────────────────────────────┼───────────────────────────────────────┘     │
│                                │                                              │
│                                ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │                       VALIDATION ENGINE                              │     │
│  │                                                                       │     │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │     │
│  │  │ DUPLICATE       │  │ NORMALIZATION   │  │ SCHEMA              │  │     │
│  │  │ DETECTION       │  │                 │  │ VALIDATION          │  │     │
│  │  │                 │  │ Name, ID,       │  │                     │  │     │
│  │  │ Same agent from │  │ format          │  │ Mandatory fields    │  │     │
│  │  │ 2+ sources →    │  │ standardization │  │ (name, type, owner) │  │     │
│  │  │ merge           │  │                 │  │                     │  │     │
│  │  └────────┬────────┘  └────────┬────────┘  └──────────┬──────────┘  │     │
│  │           │                    │                       │              │     │
│  │           ▼                    ▼                       ▼              │     │
│  │  ┌──────────────────────────────────────────────────────────────┐  │     │
│  │  │              RECONCILIATION                                   │  │     │
│  │  │  Match SEAR records ↔ discovered agents                      │  │     │
│  │  │  Match existing registry entries ↔ new discoveries           │  │     │
│  │  └──────────────────────────┬───────────────────────────────────┘  │     │
│  └─────────────────────────────┼───────────────────────────────────────┘     │
│                                │                                              │
│                                ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │                      ORPHAN QUEUE                                    │     │
│  │                                                                       │     │
│  │  Agents found in traces but NOT in registry → shown in Discovery UI  │     │
│  │                                                                       │     │
│  │  Options per orphan:                                                  │     │
│  │  • [Register agent] → moves to intake form                           │     │
│  │  • [Assign to existing] → merge with known agent                     │     │
│  │  • [Dismiss] → mark as false positive                                │     │
│  │                                                                       │     │
│  └──────────────────────────┬───────────────────────────────────────────┘     │
│                             │                                                │
│                             ▼                                                │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │                    CANONICAL REGISTRY (SoR)                          │     │
│  │                                                                       │     │
│  │  Trusted, validated agent records — the source of truth              │     │
│  │  All dashboard views read from here                                   │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 5.4 Discovery Span Attributes (from AssureAI pattern)

```
SPAN ATTRIBUTES FOR AGENT DISCOVERY:
─────────────────────────────────────

openinference.span.kind = "AGENT"       ← Primary classifier
agent.name                              ← "supervisor", "triage", "kyc_aml"
graph.node.name                         ← "kyc_aml_node"
graph.node.id                           ← Node ID in execution graph
llm.model_name                          ← "gpt-5", "gemini-pro"
llm.token_count.prompt                  ← Input tokens (INTEGER)
llm.token_count.completion              ← Output tokens (INTEGER)
llm.token_count.cache_read              ← Cache hit tokens (INTEGER)
tool.name                               ← "pytesseract", "azure_vision"
span.status_code                        ← OK / ERROR
span.start_time / span.end_time         ← Duration
parent_id                               ← Dependency parent
mcp.server_name                         ← MCP server called
mcp.tool_name                           ← MCP tool invoked
```

### 5.5 Discovery Confidence Scoring

```
CONFIDENCE SCORING:
───────────────────

┌──────────────────────────────────────────────────────────┐
│  Signal Source         │ Weight │ Example               │
├──────────────────────────────────────────────────────────┤
│  Phoenix AGENT span    │  40%   │ Direct trace evidence │
│  MCP Gateway call      │  25%   │ MCP invocation seen   │
│  GitHub config match   │  20%   │ agent.yaml found      │
│  ServiceNow activity   │  10%   │ Service account + AI  │
│  Network pattern match │   5%   │ Traffic signature     │
└──────────────────────────────────────────────────────────┘

Confidence = Σ(signal_weight × signal_strength)

  ≥85%  →  Auto-register (high confidence)
  70-84% → Show in discovery feed (review required)
  <70%  → Log only (low confidence, backfill)
```

### 5.6 Shadow AI Risk Classification

```
SHADOW AI RISK CLASSIFICATION:
══════════════════════════════

┌─────────────────────────────────────────────────────────────────────────────┐
│  SHADOW AI = AI tools/agents running without IT approval or visibility     │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │ Risk Level │ Criteria              │ Action                           │ │
│  ├───────────────────────────────────────────────────────────────────────┤ │
│  │ HIGH       │ PII access + external │ Block immediately, escalate     │ │
│  │            │ model + no owner       │ to security + legal             │ │
│  ├───────────────────────────────────────────────────────────────────────┤ │
│  │ MEDIUM     │ External model OR      │ Notify owner, require           │ │
│  │            │ no governance          │ registration within 7 days      │ │
│  ├───────────────────────────────────────────────────────────────────────┤ │
│  │ LOW        │ Internal model +       │ Register, standard governance   │ │
│  │            │ owner identified       │                                 │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  Data: Average enterprise runs 305 SaaS apps, 36% unused = $19.8M waste   │
│  Source: Zylo 2026 SaaS Management Index                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Dependency Graph & Impact Analysis

### 6.1 Node Types

| Node Type | Visual | Prototype Examples |
|---|---|---|
| **Agent** | Large colored circle | inv-recon, demand-forecast, support-triage |
| **MCP/API** | Medium node with type label | SAP MCP Server, Slack MCP Server |
| **Data** | Medium node | Snowflake, Databricks |
| **Model** | Medium node | GPT-5, Claude Sonnet 4.5 |
| **System** | Medium node | SAP S/4HANA, Workday, ServiceNow |

### 6.2 Edge Types

| Edge Type | Source → Target | Meaning | Prototype Example |
|---|---|---|---|
| `CALLS` | Agent → Agent | Parent invokes child | inv-recon → expense-audit |
| `USES` | Agent → Model/Prompt/Tool | Consumes resource | inv-recon → GPT-5 |
| `CONSUMES` | Agent → Data/API | Reads from data source | inv-recon → Snowflake |
| `PRODUCES` | Agent → Data/Output | Writes to sink | inv-recon → Ledger posting |
| `DEPENDS_ON` | Agent → Infrastructure | Requires infra/service | inv-recon → SAP S/4HANA |

### 6.3 Outage Simulation (Impact Analysis)

```
OUTAGE SIMULATION WORKFLOW:
════════════════════════════

User clicks dependency node (e.g., "SAP S/4HANA")
         │
         ▼
┌──────────────────────────────────────────┐
│  1. Find all dependent agents            │
│     Direct: agents with SAP in systems   │
│     Transitive: agents that call them    │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│  2. Calculate impact                     │
│                                          │
│  Revenue at Risk = Σ(agent.revenue × 0.42)│
│  Efficiency at Risk = Σ(agent.efficiency × 0.38)│
│  Users affected = Σ(agent.user_count)     │
│  Cost at Risk = Σ(agent.monthly_cost)    │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│  3. Show impact panel                    │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │  ⚠ SAP S/4HANA OUTAGE IMPACT      │  │
│  │                                    │  │
│  │  6 agents affected                 │  │
│  │  Revenue at risk: $638K × 0.42    │  │
│  │  = $268K/mo                        │  │
│  │  Blast radius: Finance, Supply     │  │
│  │  Chain, CX, IT Ops                 │  │
│  │                                    │  │
│  │  [Open incident] [Export report]   │  │
│  └────────────────────────────────────┘  │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│  4. Notify owners                        │
│     Slack/email to all affected agents   │
└──────────────────────────────────────────┘
```

### 6.4 Concentration Risk Algorithm

```
CONCENTRATION RISK:
═══════════════════

For each system S in (enterpriseSystems ∪ databases):
    dependent_count = |{agents : S ∈ agent.systems}|
    
    IF dependent_count ≥ 4:
        RISK_LEVEL = "HIGH"
        RISK_SCORE = dependent_count × avg(agent.value) × criticality_weight
    ELIF dependent_count ≥ 2:
        RISK_LEVEL = "MEDIUM"  
    ELSE:
        RISK_LEVEL = "LOW"

OUTPUT: Sorted list of HIGH risk systems with affected agents

Prototype HIGH risk systems:
  SAP S/4HANA: 6 agents, score = 6 × $106K × 1.5 = $954K
  Workday: 4 agents, score = 4 × $37K × 1.2 = $178K
  ServiceNow: 4 agents, score = 4 × $48K × 1.2 = $230K
  Snowflake: 4 agents, score = 4 × $79K × 1.0 = $316K
```

---

## 7. Governance & Compliance Model

### 7.1 The 3 Gates (From Prototype)

```
PRODUCTION GATE:
════════════════

                     ┌───────────────────────────────┐
                     │     PRODUCTION GATE            │
                     │                                │
                     │  ALL THREE must be APPROVED:   │
                     │                                │
                     │  ┌──────────┐  ┌────────────┐ │
                     │  │  ARB     │  │  Security  │ │
                     │  │ Approved │  │  Approved  │ │
                     │  └──────────┘  └────────────┘ │
                     │  ┌──────────────────────────┐ │
                     │  │        DLP               │ │
                     │  │      Approved            │ │
                     │  └──────────────────────────┘ │
                     │                                │
                     │  EXCEPTION: Time-bound waiver  │
                     │  with expiry date               │
                     └───────────────────────────────┘

GATE STATES PER REVIEW:
───────────────────────

  Not Submitted → In Review → Changes Requested → Approved with Conditions → Approved
     (Gray)         (Purple)      (Coral)              (Amber)                (Teal)
```

### 7.2 Governance Kanban Flow

```
GOVERNANCE WORKBENCH:
═════════════════════

┌────────────────┐  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│ NEEDS INTAKE   │  │ SECURITY / ARB │  │ RAI / DLP      │  │ READY /        │
│                │  │                │  │ REVIEW         │  │ APPROVED       │
│ SEAR =         │  │ SEAR = Pending │  │ RAI = Pending  │  │                │
│ Not Submitted  │  │                │  │ OR             │  │ Production =   │
│                │  │                │  │ DLP = Pending  │  │ Approved/Pilot │
│ • supplier-    │  │ • contract-    │  │ • refund-      │  │                │
│   risk         │  │   review       │  │   adjudication │  │ • inv-recon    │
│ • pricing-     │  │ • market-      │  │ • access-      │  │ • candidate-   │
│   optimizer    │  │   digest       │  │   review       │  │   screen       │
│                │  │                │  │                │  │ • onboarding   │
│ [+ Register    │  │ [Approve SEAR] │  │ [Approve RAI]  │  │                │
│  manually]     │  │                │  │ [Approve DLP]  │  │ [Monitor in    │
│                │  │                │  │                │  │  Production]   │
└────────────────┘  └────────────────┘  └────────────────┘  └────────────────┘
```

### 7.3 Risk Classification

```
RISK CLASSIFICATION:
════════════════════

┌─────────────────────────────────────────────────────────────────────────────┐
│  Risk Level    │ Criteria              │ Approval Required                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  LOW           │ No PII, internal      │ Product Owner                       │
│                │ model, read-only       │                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│  HIGH          │ PII access, external  │ Committee + Security + Legal        │
│                │ model, write access    │                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│  UNACCEPTABLE  │ High-risk EU AI Act   │ BLOCKED — cannot proceed           │
│                │ category, no human     │ without fundamental redesign        │
│                │ oversight              │                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.4 Runtime Policy Enforcement

> **"Session-level access control is INSUFFICIENT for agents. Every action an agent attempts must be evaluated against policies before execution."** — Promethium.ai

```
RUNTIME POLICY ENFORCEMENT:
═══════════════════════════

┌────────────────────────────────────────────────────────────────────────────┐
│  Policy Type        │ Enforced At         │ Example                        │
├────────────────────────────────────────────────────────────────────────────┤
│  Data Access        │ Query time          │ "Agent X cannot read PII       │
│                     │                     │  without DLP approval"         │
├────────────────────────────────────────────────────────────────────────────┤
│  Model Selection    │ Invocation time     │ "High-risk tasks must use      │
│                     │                     │  approved models only"         │
├────────────────────────────────────────────────────────────────────────────┤
│  Tool Access        │ Tool call time      │ "Financial agents cannot       │
│                     │                     │  call external search"         │
├────────────────────────────────────────────────────────────────────────────┤
│  Cost Rate          │ Continuous          │ "Pause if $/hour > 10× avg"   │
├────────────────────────────────────────────────────────────────────────────┤
│  Iteration Limit    │ Loop detection      │ "Max 20 iterations per run"   │
├────────────────────────────────────────────────────────────────────────────┤
│  Human Approval     │ Action time         │ "Refunds > $500 require       │
│                     │                     │  human sign-off"               │
└────────────────────────────────────────────────────────────────────────────┘

POLICY FORMAT: Machine-readable code (OPA/Rego), NOT Word documents.
```

### 7.5 Cross-Functional Governance Committee

```
CROSS-FUNCTIONAL AI GOVERNANCE COMMITTEE:
════════════════════════════════════════

┌────────────────────────────────────────────────────────────────────────────┐
│  CHARTER: AI Governance Committee                                          │
│                                                                             │
│  Membership:                                                                │
│  • Risk Officer — Overall risk posture, board reporting                    │
│  • Legal / Compliance — Regulatory mapping (EU AI Act, state laws)         │
│  • IT / Security — Security posture, agent identity, infrastructure        │
│  • Data Science — Model evaluation, quality standards                      │
│  • Business Units — Use case approval, value verification                  │
│  • Procurement — Vendor management, contract terms                         │
│  • Finance — Budget oversight, cost optimization                           │
│                                                                             │
│  Authority:                                                                 │
│  • Can block deployments that don't meet risk standards                    │
│  • Can require additional review for high-risk use cases                   │
│  • Can mandate agent retirement for compliance violations                  │
│                                                                             │
│  Cadence: Monthly meeting + emergency sessions for critical incidents      │
└────────────────────────────────────────────────────────────────────────────┘
```

### 7.6 EU AI Act Compliance

The EU AI Act's high-risk obligations became enforceable in August 2026. For the prototype's 22 agents, the following obligations apply to HIGH-risk agents:

- Risk management system in place
- Data governance documentation
- Technical documentation
- Transparency and provision of information to users
- Human oversight measures
- Accuracy, robustness, cybersecurity

The implementation should add an `eu_ai_act_category` field to each agent and auto-flag HIGH-risk agents for additional review.

---

## 8. Value Tracking & Executive Dashboards

### 8.1 What the Prototype Does

The prototype's Executive view shows 5 KPI cards, a pipeline rail, portfolio mix bars, value-by-department bars, a risk list, and a top-agents table. The 8 ticker KPIs at the top provide an at-a-glance portfolio health check.

### 8.2 Value Model

The prototype tracks value through 3 fields: valueAmount (numeric), valueType (category), and hoursSavedMonthly (numeric). The value types in the prototype are:

- **Cost avoidance:** 14 agents (e.g., inv-recon at $186K/mo)
- **Revenue influenced:** 2 agents (lead-scoring at $210K, pricing-optimizer at $60K)
- **Revenue retained:** 2 agents (churn-predictor at $145K)
- **Projected:** 4 agents not yet in production
- **Retired:** 1 agent (change-validator)

### 8.3 Value-to-Cost Ratio

| Ratio | Color | Meaning | Action |
|---|---|---|---|
| Value/Cost > 10× | 🟢 Green | Scaling well | Increase investment, expand scope |
| Value/Cost 6-10× | 🟡 Amber | Monitor | Refine prompts, model, workflow |
| Value/Cost < 6× | 🔴 Red | Cost/value imbalance | Optimize, tune, or retire |

Based on the tokenomics analysis, the prototype's portfolio has a value-to-cost ratio of 118× — deep in the green.

### 8.4 Token Efficiency Metrics

| Metric | Formula | Target | Prototype Application |
|---|---|---|---|
| Cost per Invocation | Monthly cost / invocations | Decreasing MoM | inv-recon: $0.26/invocation |
| Cost per Outcome | Monthly cost / outcomes | Decreasing MoM | inv-recon: $0.019/invoice |
| Token Efficiency Ratio | Output value / token cost | >10× | Portfolio: 118× |
| Cache Hit Rate | cached / input tokens | >40% | Track per agent |
| Error-Adjusted Cost | cost / (1 - error_rate) | Decreasing | Accounts for retry waste |
| Model Routing Efficiency | % routed to cheaper tier | >70% | 70/20/10 target |
| Cost per Revenue $ | Monthly cost / revenue $ | <5% | Portfolio: 0.85% |

### 8.5 Pivot Rules

| Rule | Trigger | Action | Prototype Example |
|---|---|---|---|
| **Scale** | Green value, controlled cost, approved governance | Increase investment | demand-forecast (1,722×) |
| **Tune** | Useful but weak quality, drifting cost | Refine prompts, model | code-review-copilot (40×) |
| **Pause/Retire** | Red status, duplicate, expired approval | Stop, learn, reallocate | change-validator (retired) |

---

## 9. Waste Detection & Optimization

### 9.1 The 10 Waste Types

| # | Type | Detection Rule | Impact | Prototype Example |
|---|---|---|---|---|
| W-01 | Idle Agent | Zero invocations in 14+ days | 100% infra cost | supplier-risk (20w stalled) |
| W-02 | Model Overkill | Expensive model on low-complexity task | 60-80% LLM cost | inv-recon (GPT-5 on matching) |
| W-03 | Duplicate Agent | 2+ agents, same function + tools | 50-100% duplicate cost | change-validator → incident-copilot |
| W-04 | Retry Waste | Error rate > 15% | 2-5× token waste | Need telemetry |
| W-05 | Prompt Bloat | Input tokens growing >50% MoM | Increasing cost/invocation | Need telemetry |
| W-06 | Governance Debt | Gates pending >30 days | Production blocked | contract-review (Security: Not Submitted) |
| W-07 | Production Gate Debt | Stage = Production but gate = Blocked | Delayed value | None |
| W-08 | Value/Cost Drift | Cost growing faster than value | Shrinking ROI | Need cost data |
| W-09 | PII Risk | PII=true but DLP not Approved | Compliance exposure | refund-adjudication (DLP: In Review) |
| W-10 | Exception Expiry | Governance exception past expiry | Unauthorized risk | None |

### 9.2 The Optimization Stack

| # | Strategy | Savings | Effort | How |
|---|---|---|---|---|
| 1 | Model Routing (70/20/10) | 60-80% | Medium | Route simple → small models |
| 2 | Prompt Caching | 40-90% | Low | Stable system prompt prefix |
| 3 | Context/RAG Optimization | 30-60% | Medium | Fixed token budgets (4K max) |
| 4 | Prompt Compression | 20-50% | Low | LLMLingua compression |
| 5 | Conversation Pruning | 5-10% | Low | Sliding window (last 10 turns) |
| 6 | Token Budgets | 5-15% | Low | max_tokens per agent type |
| 7 | Batch Processing | 50% async | Low | OpenAI Batch API |
| 8 | Semantic Caching | 20-35% | Medium | Match similar queries |
| 9 | Eval-Gated Downgrade | 20-50% | Medium | Downgrade if eval passes |
| 10 | Budget Guardrails | Variable | Low | Hard stop at 100% budget |

Combined: 60-80% cost reduction. Applied to prototype: $10,500 → $2,100-$4,200/month.

### 9.3 Always-On Monitor Waste

Agents running continuous background checks consume compute 24/7. Detection: invocations in >90% of hours AND task type is not real-time-required. Solutions: scheduled batch runs, event-driven triggers, reduced off-peak frequency. Savings: 97% of compute cost.

### 9.4 Arthur AI ADLC Framework

The prototype's lifecycle stages map to Arthur AI's Agent Development Lifecycle (ADLC) framework. The four discovery techniques (OTel, MCP, Network, API) provide near-100% coverage when combined.

---

## 10. Agent Identity & Offboarding

### 10.1 Why Agent Identity Matters

> **"A support agent and a financial reporting agent should never share API keys or database credentials, even within the same organization."** — Promethium.ai

The prototype tracks agents by name and contact (Slack channel). This is insufficient for production. Every agent needs a unique, attributable identity.

### 10.2 The Identity Model (Microsoft Entra Agent ID Pattern)

```
AGENT IDENTITY MODEL:
═════════════════════

┌─────────────────────────────────────────────────────────────────────┐
│  AGENT IDENTITY BLUEPRINT                                            │
│  (1:many)                                                            │
│  • Defines permissions, scope, autonomy level                        │
│  • Holds credentials (managed identity recommended)                  │
│  • Created by: Agent ID Developer                                    │
│  • Has assigned SPONSOR (accountable for purpose/lifecycle)          │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
                             │ 1:many
                             │
┌────────────────────────────┼─────────────────────────────────────────┐
│  AGENT IDENTITY (per instance)                                       │
│  • Object ID + App ID (reliable identifiers)                        │
│  • Inherits permissions from blueprint                              │
│  • No credentials of its own (blueprint holds them)                │
│  • 1:1 relationship with AGENT'S USER ACCOUNT                       │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
                             │ 1:1
                             │
┌────────────────────────────┼─────────────────────────────────────────┐
│  AGENT'S USER ACCOUNT                                                │
│  • Microsoft Entra user account decorated as AI agent               │
│  • Different id from agent identity (1:1 relationship)              │
│  • Used for interactive/OBO scenarios                                │
└─────────────────────────────────────────────────────────────────────┘
```

### 10.3 The 7-Stage Decommissioning Workflow

```
7-STAGE DECOMMISSIONING:
════════════════════════

┌──────────────────────────────────────────────────────────────────────────────┐
│  Stage │ Action                    │ Verification                           │
├──────────────────────────────────────────────────────────────────────────────┤
│  1     │ Retirement decision       │ Documented rationale, owner signoff   │
│  2     │ Knowledge capture         │ Runbooks, learnings archived          │
│  3     │ Dependency mapping        │ All consumers identified              │
│  4     │ Credential revocation     │ API keys, OAuth tokens destroyed      │
│  5     │ Invocation blocking       │ Zero new requests accepted            │
│  6     │ Data sanitization         │ Traces archived, PII purged           │
│  7     │ Residual validation       │ 7-day wait, zero invocations, $0 cost │
└──────────────────────────────────────────────────────────────────────────────┘

Prototype application: change-validator
  → Archive change-validation logic
  → Redirect consumers to incident-copilot
  → Revoke ServiceNow MCP credentials
  → Block new invocations
  → Wait 7 days
  → Tombstone identity
```

### 10.4 RBAC (5 Roles)

| Role | Create | Read | Update | Delete | Special |
|---|---|---|---|---|---|
| Registry Admin | ✅ All | ✅ All | ✅ All | ✅ All | User mgmt, taxonomy |
| Architect Steward | ✅ All | ✅ All | ✅ Discovery, deps | ❌ | Approve orphans |
| Security Reviewer | ❌ | ✅ All | ✅ SEAR/Security | ❌ | Approve gates |
| Product Owner | ✅ Own | ✅ All | ✅ Own metadata | ❌ | Submit recert |
| Executive Viewer | ❌ | ✅ Dashboards | ❌ | ❌ | Read-only |

---

## 11. Integrations — How the Registry Connects

### 11.1 The 4-Question Framework (Nango Research)

Before building any integration, answer these four questions:

1. **Identity:** On whose behalf should the agent act? Human user? Service account? Delegated identity?
2. **Permissions:** What should the agent have access to? Read-only? Write? PII? Financial?
3. **Enforcement:** Who enforces permissions? Registry? Gateway? External policy engine?
4. **Observability:** How do you audit agent behavior? Logs? Traces? Cost attribution? Alerting?

> **"These four questions determine whether your agent integration is secure by design or patched after an incident."** — Nango, Apr 2026

### 11.2 Authentication Models

| Model | How It Works | Best For | Prototype Equivalent |
|---|---|---|---|
| API Key | Static key per agent, sent as header | Internal services | None (add for agent-to-registry) |
| OAuth2 Bearer | Token per user+agent, refresh + rotation | User-delegated access | None (add for dashboard) |
| PAT | Scoped to MCP server (GitHub, Jira, Sentry) | MCP tool access | MCP server cards need this |
| JWT | Signed claims with expiration + scopes | Service-to-service | Registry-to-backend |
| mTLS | Mutual TLS certificates, no tokens to leak | Zero-trust networks | High-security environments |

### 11.3 Connection Failure Handling

| Failure | HTTP | Recovery | Registry Response |
|---|---|---|---|
| Transient | 5xx | Retry with exponential backoff | Queue + retry (3×) |
| Rate Limit | 429 | Wait + retry | Backoff + alert |
| Auth Expired | 401 | Refresh token | Auto-refresh + retry |
| Permission | 403 | Fail + alert | Block + notify owner |
| Not Found | 404 | Fail + flag | Mark dependency as broken |
| Timeout | — | Retry once | Alert if >3× occurrence |

> **"Middleware should never silently retry or absorb rate limit errors when an LLM is in the loop."** — Truto research

---

## 12. Plugins & MCP Ecosystem

### 12.1 MCP Server Costs (Bacancy Research, May 2026)

| Tier | Cost | Timeline | Best For |
|---|---|---|---|
| Basic MVP | $15,000 - $50,000 | 4-6 weeks | Internal copilots, proof of concepts |
| Mid-tier | $40,000 - $120,000 | 8-12 weeks | SaaS products, customer-facing agents |
| Enterprise | $120,000 - $400,000+ | 12-20 weeks | Regulated industries, multi-tenant platforms |

For the prototype's 12 unique MCP servers, the total build cost would be approximately $480,000 - $1,440,000 if built from scratch.

### 12.2 MCP Pricing Models (Peliqan Research, May 2026)

| Model | How It Works | Entry Price | Mid-Market | Best For |
|---|---|---|---|---|
| Per-tool (Composio) | Pay per tool enabled | Free tier | $49+/month | 3-8 specific tools |
| Per-call (Pipedream) | Pay per tool execution | $29/month | $99-$500/month | Spiky workloads |
| Per-seat (Zapier) | Per user + per-task | $19.99/month | $69-$299/month | Small teams |
| Per-workspace (Workato) | Base + per-recipe | $10K-$25K/year | $50K-$130K/year | Large enterprises |
| Flat-rate (Peliqan) | Fixed monthly | €150/month | €1,800/year | Predictable workloads |

> **"The cheapest sticker is rarely the cheapest two-year total cost — because the cheap tier hits an overage ceiling or a feature wall inside the first six months."** — Peliqan, May 2026

### 12.3 Hybrid Pricing Model

Research from Zylos (2026) shows that hybrid pricing (base platform fee + usage-based consumption) is the dominant model, adopted by 41% of enterprises. For the prototype's 22-agent portfolio:

- Base fee: $500-$2,000/month (registry, governance, discovery)
- Usage fee: $0.01-$0.05 per tracked invocation
- Total: $2,100-$6,200/month for the full portfolio

### 12.4 MCP Governance (5-Layer Model)

```
MCP GOVERNANCE:
═══════════════

┌─────────────────────────────────────────────────────────────────────────────┐
│  GOVERNANCE LAYER     │ RESPONSIBILITY                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│  1. Tool Registry     │ Central catalog of all MCP servers + tools         │
│                       │ Metadata: permissions, rate limits, owner          │
├─────────────────────────────────────────────────────────────────────────────┤
│  2. Access Scoping    │ Per-agent tool permissions                         │
│                       │ Agent A: read-only CRM, Agent B: write ERP         │
├─────────────────────────────────────────────────────────────────────────────┤
│  3. Credential Vault  │ Secrets never in agent context                     │
│                       │ Gateway holds creds, agent gets tokens             │
├─────────────────────────────────────────────────────────────────────────────┤
│  4. Usage Tracking    │ Per-agent, per-tool call logging                   │
│                       │ Cost attribution, anomaly detection                │
├─────────────────────────────────────────────────────────────────────────────┤
│  5. Lifecycle Mgmt    │ Discover → Register → Scope → Monitor → Retire    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 12.5 MCP Ecosystem Categories (BitAtlas Survey 2026)

| Category | Share | Prototype Examples |
|---|---|---|
| Data Retrieval | 35-40% | Snowflake MCP, Salesforce MCP, Workday MCP |
| Code & Dev | 20-25% | GitHub MCP, ServiceNow MCP |
| Browser & Web | 10-15% | Web Search MCP |
| File & Document | 8-10% | PDF Extraction MCP, Email MCP |
| Infrastructure | 5-7% | Slack MCP |
| Communication | 3-5% | Slack MCP, Email MCP |

---

## 13. System Architecture

### 13.1 Architecture Overview

```
AIREGISTRY SYSTEM ARCHITECTURE:
════════════════════════════════

┌──────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (React + TypeScript)                    │
│                                                                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐  │
│  │Executive │ │Business  │ │Platform  │ │Governance│ │ AI Registry      │  │
│  │View      │ │Impact    │ │& Deps    │ │Workbench │ │ (Search/Filter)  │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────────────┘  │
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                     SHARED COMPONENTS                                   │  │
│  │  PipelineRail · DependencyGraph · TokenomicsPanel · GovernanceModal   │  │
│  │  AgentCard · AddAgentForm · DiscoveryFeed · BudgetAlert               │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                     DATA LAYER (DataSource seam)                        │  │
│  │  MockDataSource (localStorage) | LiveDataSource (REST API)            │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
└──────────────────────────────────┬────────────────────────────────────────────┘
                                   │ REST API + WebSocket
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                              BACKEND (FastAPI / Python)                       │
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                          API GATEWAY                                    │  │
│  │  /api/v1/agents · /api/v1/discovery · /api/v1/tokens                  │  │
│  │  /api/v1/governance · /api/v1/value · /api/v1/graph                  │  │
│  └──────────────────────────────┬─────────────────────────────────────────┘  │
│                                 │                                             │
│  ┌──────────────────────────────┼─────────────────────────────────────────┐  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │  │
│  │  │ Agent    │ │Discovery │ │Tokenomics│ │Governanc │ │ Graph    │    │  │
│  │  │ Service  │ │ Service  │ │ Service  │ │ Service  │ │ Service  │    │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘    │  │
│  │       │             │             │            │            │          │  │
│  │       └─────────────┴─────────────┴────────────┴────────────┘          │  │
│  │                              │                                          │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │  │
│  │  │                    DATA ACCESS LAYER                              │ │  │
│  │  │  SQLAlchemy · AsyncPG · TimescaleDB driver                       │ │  │
│  │  └──────────────────────────────────────────────────────────────────┘ │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
└──────────────────────────────────┬────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                              DATA STORES                                      │
│                                                                               │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐   │
│  │ PostgreSQL       │  │ TimescaleDB      │  │ Redis                    │   │
│  │ (Primary DB)     │  │ (Token usage     │  │ (Cache +                 │   │
│  │                  │  │  time-series)    │  │  Real-time               │   │
│  │ agents, depts,   │  │                  │  │  pub/sub)                │   │
│  │ governance,      │  │ agent_token_     │  │                          │   │
│  │ budgets,         │  │ usage,           │  │ Live token               │   │
│  │ discoveries      │  │ cost_anomalies   │  │ streams                  │   │
│  └──────────────────┘  └──────────────────┘  └──────────────────────────┘   │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
                                   ▲
                                   │ OTLP / Phoenix API
                                   │
┌──────────────────────────────────────────────────────────────────────────────┐
│                           EXTERNAL SOURCES                                    │
│                                                                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐  │
│  │ Phoenix/ │ │ Vertex   │ │ GitHub   │ │ MCP      │ │ Network          │  │
│  │ Arize    │ │ AI       │ │ Config   │ │ Gateway  │ │ Traffic          │  │
│  │ (Traces) │ │ (Agents) │ │ (Repos)  │ │ (Tools)  │ │ (Shadow AI)      │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────────────┘  │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 14. Database Schema

### 14.1 Core Tables

```sql
-- Organizations (multi-tenant boundary)
CREATE TABLE organizations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(100) UNIQUE NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Departments
CREATE TABLE departments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id),
    name            VARCHAR(100) NOT NULL,
    cost_center     VARCHAR(50),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Agents (the registry)
CREATE TABLE agents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id),
    dept_id         UUID REFERENCES departments(id),
    
    -- Identity
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(255) UNIQUE NOT NULL,
    description     TEXT NOT NULL,
    ai_type         VARCHAR(50) NOT NULL,
    function        VARCHAR(100),
    owner           VARCHAR(255) NOT NULL,
    owner_contact   VARCHAR(255),
    
    -- Lifecycle
    lifecycle_stage VARCHAR(50) NOT NULL DEFAULT 'Ideation',
    version         VARCHAR(50),
    time_in_stage_weeks INTEGER DEFAULT 0,
    at_risk         BOOLEAN DEFAULT FALSE,
    risk_note       TEXT,
    risk_level      VARCHAR(20) DEFAULT 'LOW',
    
    -- Technical
    model_name      VARCHAR(100),
    model_provider  VARCHAR(100),
    runtime         VARCHAR(100),
    framework       VARCHAR(100),
    api_endpoint    VARCHAR(500),
    sla             VARCHAR(255),
    
    -- Value
    value_amount    BIGINT DEFAULT 0,
    value_type      VARCHAR(50),
    hours_saved_monthly INTEGER DEFAULT 0,
    business_outcome TEXT,
    
    -- Metadata
    tags            JSONB DEFAULT '[]',
    enterprise_systems JSONB DEFAULT '[]',
    databases       JSONB DEFAULT '[]',
    knowledge_bases JSONB DEFAULT '[]',
    mcp_servers     JSONB DEFAULT '[]',
    calls           JSONB DEFAULT '[]',
    consumers       JSONB DEFAULT '[]',
    inputs          JSONB DEFAULT '[]',
    outputs         JSONB DEFAULT '[]',
    
    -- Source tracking
    source          VARCHAR(50) DEFAULT 'manual',
    discovered_at   TIMESTAMPTZ,
    shadow_ai_risk  VARCHAR(20),
    
    -- Audit
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_updated    DATE DEFAULT CURRENT_DATE,
    deprecated_at   TIMESTAMPTZ,
    sunset_date     DATE
);

-- Agent identity (Entra pattern)
CREATE TABLE agent_identities (
    agent_id        UUID PRIMARY KEY REFERENCES agents(id),
    service_account VARCHAR(255) UNIQUE NOT NULL,
    entra_agent_id  VARCHAR(255),
    api_key_hash    VARCHAR(255),
    permissions     JSONB DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at      TIMESTAMPTZ
);

-- Governance reviews
CREATE TABLE governance_reviews (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID NOT NULL REFERENCES agents(id),
    gate            VARCHAR(50) NOT NULL,
    status          VARCHAR(50) NOT NULL DEFAULT 'Not Submitted',
    reviewer        VARCHAR(255),
    notes           TEXT,
    reviewed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Exceptions (time-bound governance waivers)
CREATE TABLE governance_exceptions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID NOT NULL REFERENCES agents(id),
    gate            VARCHAR(50) NOT NULL,
    reason          TEXT NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    approved_by     VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Discoveries (unregistered agents found)
CREATE TABLE discoveries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id),
    suspected_name  VARCHAR(255) NOT NULL,
    suspected_dept  VARCHAR(100),
    suspected_type  VARCHAR(50),
    source          VARCHAR(100) NOT NULL,
    confidence      INTEGER NOT NULL,
    signal          TEXT,
    status          VARCHAR(50) DEFAULT 'pending',
    shadow_ai_risk  VARCHAR(20),
    registered_agent_id UUID REFERENCES agents(id),
    first_seen      DATE NOT NULL,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Users & RBAC
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id),
    email           VARCHAR(255) UNIQUE NOT NULL,
    name            VARCHAR(255) NOT NULL,
    role            VARCHAR(50) NOT NULL DEFAULT 'Executive Viewer',
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Audit log (append-only)
CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    org_id          UUID NOT NULL REFERENCES organizations(id),
    actor           VARCHAR(255) NOT NULL,
    action          VARCHAR(50) NOT NULL,
    entity_type     VARCHAR(50) NOT NULL,
    entity_id       UUID,
    changes         JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 14.2 Tokenomics Tables

```sql
-- Model pricing (versioned)
CREATE TABLE model_token_prices (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name      VARCHAR(100) NOT NULL,
    provider        VARCHAR(50) NOT NULL,
    input_price_per_1m       DECIMAL(10,4) NOT NULL,
    output_price_per_1m      DECIMAL(10,4) NOT NULL,
    cache_read_price_per_1m  DECIMAL(10,4) DEFAULT 0,
    tier                     VARCHAR(20) NOT NULL,
    effective_from  TIMESTAMPTZ NOT NULL DEFAULT now(),
    effective_to    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Token usage (TimescaleDB hypertable)
CREATE TABLE agent_token_usage (
    agent_id        UUID NOT NULL REFERENCES agents(id),
    bucket          TIMESTAMPTZ NOT NULL,
    model_name      VARCHAR(100) NOT NULL,
    invocation_count INTEGER NOT NULL DEFAULT 0,
    input_tokens    BIGINT NOT NULL DEFAULT 0,
    output_tokens   BIGINT NOT NULL DEFAULT 0,
    cached_tokens   BIGINT NOT NULL DEFAULT 0,
    cost_cents      BIGINT NOT NULL DEFAULT 0,
    latency_avg_ms  INTEGER,
    error_count     INTEGER NOT NULL DEFAULT 0,
    iterations_max  INTEGER,
    PRIMARY KEY (agent_id, bucket, model_name)
);
SELECT create_hypertable('agent_token_usage', 'bucket');

-- Budgets
CREATE TABLE agent_budgets (
    agent_id        UUID PRIMARY KEY REFERENCES agents(id),
    monthly_budget_cents  BIGINT NOT NULL DEFAULT 0,
    alert_threshold_pct   INTEGER NOT NULL DEFAULT 80,
    hard_stop_pct         INTEGER NOT NULL DEFAULT 100,
    current_month_spend_cents BIGINT NOT NULL DEFAULT 0,
    budget_reset_day      INTEGER NOT NULL DEFAULT 1,
    max_tokens_per_invocation INTEGER,
    max_iterations        INTEGER DEFAULT 20,
    auto_pause_on_breach  BOOLEAN DEFAULT true,
    last_alert_sent       TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Waste findings
CREATE TABLE waste_findings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID NOT NULL REFERENCES agents(id),
    waste_type      VARCHAR(50) NOT NULL,
    severity        VARCHAR(20) NOT NULL,
    monthly_waste_cents BIGINT,
    recommendation  TEXT,
    status          VARCHAR(50) DEFAULT 'open',
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ
);

-- Cost anomalies
CREATE TABLE cost_anomalies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID NOT NULL REFERENCES agents(id),
    anomaly_type    VARCHAR(50) NOT NULL,
    severity        VARCHAR(20) NOT NULL,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    details         JSONB,
    resolved_at     TIMESTAMPTZ,
    resolved_by     VARCHAR(255)
);

-- Materialized view: daily token summary per agent
CREATE MATERIALIZED VIEW agent_token_daily AS
SELECT
    agent_id,
    model_name,
    time_bucket('1 day', bucket) AS day,
    SUM(invocation_count) AS invocations,
    SUM(input_tokens) AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    SUM(cached_tokens) AS total_cached_tokens,
    SUM(cost_cents) AS total_cost_cents,
    AVG(latency_avg_ms) AS avg_latency_ms,
    SUM(error_count) AS total_errors,
    MAX(iterations_max) AS max_iterations_seen
FROM agent_token_usage
GROUP BY agent_id, model_name, day;

-- Materialized view: monthly token summary per department
CREATE MATERIALIZED VIEW dept_token_monthly AS
SELECT
    a.dept,
    time_bucket('1 month', t.bucket) AS month,
    SUM(t.invocation_count) AS total_invocations,
    SUM(t.input_tokens) AS total_input_tokens,
    SUM(t.output_tokens) AS total_output_tokens,
    SUM(t.cost_cents) AS total_cost_cents,
    COUNT(DISTINCT t.agent_id) AS agent_count
FROM agent_token_usage t
JOIN agents a ON a.id = t.agent_id
GROUP BY a.dept, month;
```

---

## 15. API Endpoints

### 15.1 REST API Surface

```
API ENDPOINTS:
══════════════

Agents
──────
GET    /api/v1/agents                              → list (filter: ?dept=&stage=&type=&q=&risk=)
GET    /api/v1/agents/{id}                         → detail
POST   /api/v1/agents                              → create
PUT    /api/v1/agents/{id}                         → update
DELETE /api/v1/agents/{id}                         → soft delete
GET    /api/v1/agents/{id}/graph                   → dependency graph data
POST   /api/v1/agents/{id}/offboard                → trigger offboarding

Discovery
─────────
GET    /api/v1/discoveries                         → list pending discoveries
POST   /api/v1/discoveries/{id}/register           → register as agent
POST   /api/v1/discoveries/{id}/dismiss            → mark as false positive
POST   /api/v1/discoveries/scan                    → trigger manual scan
GET    /api/v1/discoveries/shadow-ai               → list shadow AI findings

Governance
──────────
GET    /api/v1/governance                          → overview stats
PUT    /api/v1/agents/{id}/governance/{gate}       → update gate status
POST   /api/v1/agents/{id}/recertify               → launch recertification
GET    /api/v1/governance/exceptions               → list active exceptions
POST   /api/v1/governance/exceptions               → create exception

Tokenomics
──────────
GET    /api/v1/agents/{id}/tokens                  → token usage
GET    /api/v1/agents/{id}/tokens/summary          → aggregated summary
GET    /api/v1/agents/{id}/tokens/trend            → 30-day trend
GET    /api/v1/agents/{id}/cost                    → cost breakdown
GET    /api/v1/agents/{id}/cost/forecast           → 3-month projection
GET    /api/v1/agents/{id}/budget                  → budget status
PUT    /api/v1/agents/{id}/budget                  → set/update budget
GET    /api/v1/models/prices                       → list model prices
PUT    /api/v1/models/prices/{model}               → update pricing
GET    /api/v1/anomalies                           → list cost anomalies
POST   /api/v1/anomalies/{id}/resolve              → mark as resolved

Value & Waste
─────────────
GET    /api/v1/value/summary                       → value KPIs
GET    /api/v1/value/by-department                 → value by BU
GET    /api/v1/value/top-agents                    → top N by value
GET    /api/v1/waste/report                        → waste findings
GET    /api/v1/waste/summary                       → waste KPIs
GET    /api/v1/optimizations                       → optimization suggestions
POST   /api/v1/optimizations/{id}/apply            → apply suggestion

Graph & Impact
──────────────
GET    /api/v1/graph                               → full graph data
GET    /api/v1/graph/impact/{node_id}              → outage simulation result
GET    /api/v1/graph/concentration-risk            → concentration risk list

Identity
────────
GET    /api/v1/agents/{id}/identity                → agent identity details
POST   /api/v1/agents/{id}/identity/revoke         → revoke credentials

Admin
─────
GET    /api/v1/admin/taxonomy                      → lifecycle states, edge types
PUT    /api/v1/admin/taxonomy                      → update taxonomy
GET    /api/v1/admin/users                         → user list
POST   /api/v1/admin/users                         → invite user
```

### 15.2 WebSocket Events

```
WEBSOCKET: /ws/v1/live
═══════════════════════

Events:
  • token.update    → {agent_id, tokens, cost, timestamp}
  • agent.new       → {agent_id, name, source}
  • agent.stage     → {agent_id, old_stage, new_stage}
  • budget.alert    → {agent_id, threshold, spend_pct}
  • waste.finding   → {agent_id, waste_type, severity}
  • discovery.new   → {discovery_id, name, confidence}
  • anomaly.alert   → {agent_id, anomaly_type, severity}
  • optimization    → {agent_id, strategy, savings}
```

---

## 16. Technical Stack

| Layer | Technology | Rationale |
|---|---|---|
| **Frontend** | React 18 + TypeScript 5.5 | Type safety, component reuse |
| **Build** | Vite 5 | Fast dev, HMR |
| **Styling** | Tailwind v4 | Match prototype design system |
| **State** | React Query (TanStack) | Server state + caching |
| **Graph** | React Flow / D3 | Interactive dependency graph |
| **Charts** | Recharts / Chart.js | Token trends, cost breakdowns |
| **Backend** | FastAPI (Python 3.11+) | Async, auto OpenAPI |
| **DB** | PostgreSQL 16 | Primary store |
| **Time-series** | TimescaleDB | Token usage hypertables |
| **Cache** | Redis 7 | Real-time token streams |
| **Task Queue** | Celery + Redis | Discovery collectors, token aggregation |
| **OTel** | OpenTelemetry Python SDK | AssureAI-compatible span ingestion |
| **Auth** | JWT + RBAC | 5 roles |
| **API Client** | Orval / openapi-typescript | Auto-generated from OpenAPI |
| **Testing** | Vitest (FE), pytest (BE) | Unit + integration |
| **CI** | GitHub Actions | Lint, test, build |
| **Monitoring** | Phoenix / Arize | Trace visualization |
| **Policy Engine** | OPA (Open Policy Agent) | Runtime policy enforcement |

---

## 17. Implementation Roadmap

### Phase 0: Foundation (Weeks 1-2)
- Set up React + TypeScript + Vite project
- Create component library matching prototype visual design
- Implement DataSource seam (MockDataSource → localStorage)
- Port all 5 views from HTML prototype
- Build Agent data models (TypeScript types)
- Set up Tailwind v4 theme (colors, fonts from prototype)
- Implement routing (react-router-dom)
- Persist state (localStorage → future API)

### Phase 1: Core Backend (Weeks 3-4)
- Set up FastAPI project
- Implement database schema (all core tables)
- Build Agent CRUD API
- Build Governance API (gate updates, exceptions)
- Build Discovery API (manual intake)
- Build Value API (KPIs, aggregations)
- Migrate frontend to LiveDataSource
- Add loading/error/empty states

### Phase 2: Tokenomics Engine (Weeks 5-7)
- Set up TimescaleDB hypertable (agent_token_usage)
- Build token ingestion collector (Phoenix/OTel)
- Implement cost calculation service
- Build Tokenomics API endpoints
- Create Tokenomics dashboard panel (per-agent)
- Add budget tracking + alerts
- Build portfolio cost rollup view
- Implement 3-month cost forecasting
- Add anomaly detection (spike, loop, budget_breach)
- Implement infinite loop protection (circuit breakers)

### Phase 3: Discovery Pipeline (Weeks 8-9)
- Build Vertex AI collector
- Build GitHub config scanner
- Build Cloud Logging collector
- Build MCP Gateway collector
- Build Network Layer collector (traffic analysis)
- Implement validation engine (dedup, normalize)
- Build Discovery Console UI
- Implement orphan assignment (merge/split/dismiss)
- Add confidence scoring
- Add shadow AI risk classification

### Phase 4: Dependency Graph & Impact (Weeks 10-11)
- Build graph data service (nodes + edges)
- Implement React Flow visualization
- Build per-agent dependency modal (from prototype)
- Implement outage simulation (impact calculation)
- Add concentration risk detection
- Build initiative→integration matrix
- Add cross-AI call network view
- Export graph (PNG/SVG)

### Phase 5: Governance, Identity & Waste (Weeks 12-14)
- Build governance workbench (Kanban)
- Implement RBAC (5 roles)
- Build recertification workflow
- Add agent identity management (service accounts)
- Build agent offboarding workflow (7-stage)
- Implement waste detection engine (all 10 types)
- Build waste report dashboard
- Add model downgrade suggestions
- Add exception tracking with expiry
- Implement risk classification workflow
- Add cross-functional committee charter
- Implement runtime policy enforcement (OPA)

### Phase 6: Polish & Scale (Weeks 15-16)
- Global search drawer
- Quick registration from any screen
- Export (PDF gate report, CSV waste report)
- WebSocket live token streaming
- Performance optimization (materialized views, caching)
- E2E tests (Playwright)
- Documentation (API docs, user guide)
- CI/CD pipeline

---

## 18. ASCII Workflow Diagrams Master Index

| # | Diagram | Section |
|---|---|---|
| D-01 | AIREGISTRY System Overview | §1 |
| D-02 | Lifecycle Pipeline | §3.1 |
| D-03 | Stage Transition Rules | §3.3 |
| D-04 | Tokenomics Engine — How It Works | §4.1 |
| D-05 | Token Data Flow | §4.3 |
| D-06 | Token Cost Waterfall | §4.5 |
| D-07 | Tokenomics Dashboard | §4.6 |
| D-08 | Predictive Cost Analysis | §4.7 |
| D-09 | Token Budget Enforcement | §4.8 |
| D-10 | Infinite Loop Protection | §4.9 |
| D-11 | Discovery Pipeline | §5.3 |
| D-12 | Four Essential Discovery Techniques | §5.2 |
| D-13 | Discovery Span Attributes | §5.4 |
| D-14 | Confidence Scoring | §5.5 |
| D-15 | Shadow AI Classification | §5.6 |
| D-16 | Outage Simulation Workflow | §6.3 |
| D-17 | Concentration Risk Algorithm | §6.4 |
| D-18 | Production Gate | §7.1 |
| D-19 | Governance Kanban Flow | §7.2 |
| D-20 | Risk Classification | §7.3 |
| D-21 | Runtime Policy Enforcement | §7.4 |
| D-22 | Cross-Functional Governance Committee | §7.5 |
| D-23 | Agent Identity Model | §10.2 |
| D-24 | 7-Stage Decommissioning | §10.3 |
| D-25 | System Architecture | §13.1 |
| D-26 | MCP Governance | §12.4 |
| D-27 | Token Efficiency Metrics | §8.4 |

---

## Verification Checklist

| Check | Status |
|---|---|
| All 26 prototype features mapped to implementation | ✅ |
| All 22 agents have cost estimates | ✅ |
| All 5 views have research-backed enhancements | ✅ |
| All 5 lifecycle stages with time thresholds | ✅ |
| All 3 governance gates with risk-based tiers | ✅ |
| Tokenomics engine fully specified with real prices | ✅ |
| Discovery pipeline maps to prototype discoveries | ✅ |
| Dependency graph has outage simulation | ✅ |
| Agent identity follows Entra pattern | ✅ |
| MCP ecosystem has cost data and governance | ✅ |
| Integration patterns cover all 10 sources | ✅ |
| Database schema matches prototype + additions | ✅ |
| API endpoints cover all features | ✅ |
| Implementation roadmap covers all phases | ✅ |
| All numbers sourced from research | ✅ |
| No standalone research sections — all anchored to prototype | ✅ |
| No ambiguity — every feature has a clear path | ✅ |
| Network Layer Analysis (4th technique) included | ✅ |
| Shadow AI as explicit category | ✅ |
| 70/20/10 model routing strategy | ✅ |
| Token cost benchmarks (5-30× multiplier) | ✅ |
| Predictive cost analysis (baseline, trend, anomaly) | ✅ |
| EU AI Act compliance mapping | ✅ |
| Agent identity (Entra Agent ID pattern) | ✅ |
| Runtime policy enforcement (OPA/Rego) | ✅ |
| Agent offboarding (7-stage decommissioning) | ✅ |
| Cross-functional governance committee | ✅ |
| Risk classification workflow (L/H/U) | ✅ |
| Cache optimization (prefix stability, semantic) | ✅ |
| RAG bloat detection (fixed token budgets) | ✅ |
| Always-on monitor waste detection | ✅ |
| Hybrid pricing model (41% market share) | ✅ |
| Prompt compression (LLMLingua 20-50%) | ✅ |
| Conversation pruning (sliding window) | ✅ |
| Batch processing (50% discount) | ✅ |
| Token budgets (max_tokens per agent type) | ✅ |
| Infinite loop protection ($47K incident) | ✅ |
| Microsoft Agent Registry (Agent 365) reference | ✅ |
| ADLC framework (Arthur AI) | ✅ |
| MCP governance (5-layer model) | ✅ |
| Cost per invocation by tier | ✅ |
| Token efficiency metrics (cost per outcome) | ✅ |
| ASCII diagrams for every workflow | ✅ |
| Real quotes from registry applications | ✅ |
| SQL schemas for all tables | ✅ |
| API endpoints for all features | ✅ |
