# Zensar Enterprise AI Control Plane Registry

*(codename: **THREAD** — UI prototype "AI Control Tower")*

A single enterprise-wide **AI control plane** that lets Zensar discover, govern,
measure, secure, reuse and scale every AI agent, copilot, model and workflow —
across every platform, including ZenseAI and third-party stacks.

> v1.0 · 11 August 2026 · Scope: all AI assets across Zensar, including ZenseAI
> & third-party platforms.

---

## Problem this solves

AI agents and copilots are being built across Zensar by many teams, on many
platforms, at the same time — ZenseAI, Microsoft Copilot Studio & M365
Copilot, Azure AI Foundry & Azure OpenAI, AWS Bedrock, Google Vertex AI,
GitHub Copilot extensions, ServiceNow, Salesforce, and other SaaS AI, plus
custom/client-specific builds. There is no single place to see what exists,
who owns it, what value it delivers, or what risk it carries — leading to
duplicate builds, inconsistent governance, unclear ROI, uncontrolled cost, and
unmanaged risk. Leadership cannot currently answer: *how many AI agents exist,
what do they deliver, and what breaks if one fails?*

## Core capabilities

| Capability | What it does |
|---|---|
| **Registry** | Authoritative inventory — every agent gets a unique ID, named owner, and business purpose |
| **Discovery** | Automated, cross-platform detection of agents built on ZenseAI or any third-party platform; flags duplicate, orphaned, or unregistered ("shadow AI") agents |
| **Value & ROI** | Expected vs. actual value and cost-to-value ratio tracked per agent (productivity, revenue, cost, CX/EX, reuse dimensions) |
| **Risk & Governance** | Security, privacy, Responsible AI, compliance, operational, financial, and vendor risk — gated by lifecycle stage (POC → Pilot → Production) |
| **Dependency Graph** | Impact and blast-radius visibility — know what breaks when an agent fails |
| **Cost Management** | Spend visibility by asset, business unit, and client (platform, token, infra) |
| **Executive Dashboards** | Role-based views of the AI portfolio, value, and risk |
| **Marketplace & Reuse** | Certified capability catalogue, available enterprise-wide |

**Design principle:** platform-agnostic discovery — every agent, on every
platform, held to one Zensar governance standard. Every agent must be
registered before it reaches production, regardless of platform, owner, or
business unit.

**MVP excludes:** full automated discovery on day one across every platform,
predictive risk scoring, and a full marketplace.

## Scope

- **In-scope asset types:** AI agents & autonomous agents, copilots & virtual
  assistants, agentic workflows & AI applications, RAG solutions & knowledge
  assistants, AI APIs & AI-enabled automations, ML models & foundation model
  integrations, MCP servers & tool connectors, client-facing & internal
  productivity AI tools.
- **Platforms covered:** ZenseAI, Microsoft Copilot Studio & M365 Copilot,
  Azure AI Foundry & Azure OpenAI, AWS Bedrock, Google Vertex AI, GitHub
  Copilot, ServiceNow & Salesforce AI, UiPath, and custom/open-source/
  client-specific environments.

---

## What's in this repo

| Path | What it is |
|---|---|
| [`Zensar_AI_Control_Plane_Registry.pptx`](Zensar_AI_Control_Plane_Registry.pptx) | Requirements deck — problem statement, vision, scope, value/ROI model, risk & governance gates |
| [`THREAD_SolArch_v6_3.pdf`](THREAD_SolArch_v6_3.pdf) | Solution architecture document |
| [`AIRegistry.html`](AIRegistry.html) | "AI Control Tower" UI prototype — open directly in a browser |
| [`AIRegistry-V1.0.html`](AIRegistry-V1.0.html), [`2-THREAD_Figma_Style_Dynamic_Prototype_Executive.html`](2-THREAD_Figma_Style_Dynamic_Prototype_Executive.html) | "THREAD" Figma-style dynamic UI prototypes (executive view) |
| `app/` | Backend/frontend scaffold for the registry service — see status below |
| `infra/`, `azure-pipelines-*.yml` | Azure Container Apps deployment scripts + CI/CD |
| [`BOOTSTRAP_GUIDE.md`](BOOTSTRAP_GUIDE.md) | Architecture guide for the `app/` scaffold (LangGraph supervisor loop, Temporal durability, observability) |

### `app/` status

`app/` is the **ZenLabs Agent Foundry accelerator scaffold** — the same
production-shaped FastAPI + LangGraph + Temporal + React skeleton used across
`digital-onboarding`, `zenarc`, `merchant-onboard`, `capmarkets`, and others —
checked in as-is, **not yet bootstrapped/customized** for the registry
(`__APP_NAME__`-style placeholders are still present in `template.config.json`,
`app/api/main.py`, `app/shared/config.py`, etc.). It's the intended starting
point for the registry's backend (agent registration API, discovery workers,
ROI/risk data model) once that work begins — see
[BOOTSTRAP_GUIDE.md](BOOTSTRAP_GUIDE.md) for how the supervisor loop, Temporal
workflows, and observability stack fit together, and `bootstrap.py` /
`template.config.json` for how to run it through the bootstrapper if this
becomes its own generated app rather than an in-place scaffold.

### Viewing the prototypes

The HTML files are self-contained — open them directly in a browser, no build
step required:

```bash
open AIRegistry.html
open 2-THREAD_Figma_Style_Dynamic_Prototype_Executive.html
```

---

## Status

Design/requirements phase — the requirements deck, solution architecture doc,
and UI prototypes are the current source of truth. The `app/` scaffold has not
yet been customized to the registry's actual data model (agent inventory,
ownership, value/ROI tracking, risk gates, dependency graph) or wired to a
discovery integration for any of the platforms in scope.
