# Agent Registry Improvement Plan

## 1. Summary

- **Where the registry stops and AssureAI starts.** AssureAI answers one question: how good are an agent's answers. It does that with pillar scores, checks, gate reports, quality trends, configuration drift and review of judged results. The registry answers six other questions, and it builds only for those:
  1. Which AI agents exist, including the ones nobody registered?
  2. Who is accountable for each one?
  3. May it run at its current stage?
  4. Who uses it?
  5. What does it cost and what does it return?
  6. What breaks if it changes or stops?
- **How the registry uses AssureAI.** It takes the latest AssureAI verdict as one line of evidence on the Governance tab, with the date and a link (item 37). It copies no scores and draws no quality charts.
- **What this plan holds.** 62 improvements in six phases. They come from the earlier product plan, the discovery plan, the TODO list, the prototype gap analysis and the improvement analysis. 21 of them are partly built and 41 are not built.
- **What it leaves out.** 11 items that AssureAI covers, and 9 items that the registry should not build at all (section 8). This includes one feature that is built now, the Trace Content Audit insight, which judges answer quality.

Sizes are rough. Small is up to 2 days, Medium is about a week and Large is several weeks. Phase lengths are rough sums of those sizes.

**Table 1. Phases**

| Phase | Purpose | Items | Partly built | Not built | Rough length |
| --- | --- | --- | --- | --- | --- |
| 0. Honest and safe | Correct what is shown, enforce roles, tell people what happened | 1 to 12 | 7 | 5 | 6 to 8 weeks |
| 1. Know every agent | Find, match and register agents without typing | 13 to 23 | 2 | 9 | 8 weeks, plus 3 to 4 weeks for each cloud |
| 2. Accountability and lifecycle | Owners, classification, gates that react to change | 24 to 37 | 7 | 7 | 6 to 8 weeks |
| 3. Reuse | Show who really uses an agent and prove reuse | 38 to 44 | 0 | 7 | 4 weeks |
| 4. Cost and value | Make value believable and spend explainable | 45 to 54 | 5 | 5 | 5 weeks |
| 5. Compliance and audit | Evidence an auditor can use without help | 55 to 62 | 0 | 8 | 8 weeks |
| Total | | 62 | 21 | 41 | |

Codes in the "From" column point to the earlier documents. P1 means the product plan (for example P1-G8 is its item G8). DP means the discovery plan, TODO means the TODO list, PG means the prototype gap analysis and IA means the improvement analysis (for example IA-17 is its item 17).

## 2. Phase 0: Honest and Safe

| No. | Improvement | What changes for the user | From | Size | Built now |
| --- | --- | --- | --- | --- | --- |
| 1 | Real or demo flag on each agent | Executive, Business Impact and Platform leave the 16 seeded demo agents out unless a switch is on. Nothing is deleted. | P1-H12, P1-H13, IA-1 | Medium | Built 2026-10-08. Changed the same day: demo agents are shown by default for first looks, the switch moved to Settings, and 10 repeated demo agents are archived (kept, can be brought back) |
| 2 | Close the gate bypasses | Stage, risk level and at-risk can be changed only through the Governance tab. New agents start at Ideation unless an admin gives a reason. The portfolio Governance page loses its Approved dropdown and its auto-review button. | IA-4, IA-5, P1-G9 | Small | Built 2026-10-08 (fixed in place: the dropdown confirms and records the signed-in reviewer, auto-review became a proposal) |
| 3 | Display and pricing faults | The Executive bar draws expenditure. A new model price closes the old one. Three wording and list mismatches are aligned. | IA-2, IA-3, IA-7 | Small | Built 2026-10-08 |
| 4 | Remove pretend and dead code | The offboarding text, the invented identities, the "save 70%" text, the example routes with no login, three unreachable pages, 23 unused API functions, one unused component, two reports with no screen and the unused WebSocket stub are removed. | IA-6, TODO P0 | Small | Deferred to the final cleanup (no removal until the end) |
| 5 | Enforced roles and real people | Owner and reviewer are picked from the user list. The reviewer is the signed-in user. The 5 roles already in the code are enforced. Users can be edited and deactivated. The login page stops printing the demo password. | P1-G1, P1-H1, IA-27 | Large | Built 2026-10-08 (owner picker comes with item 24) |
| 6 | Audit page and export | An audit page filtered by person, action, agent, date and "people or machine", with a CSV export that is itself logged. | P1-C1, P1-H8, IA-26 | Small | Built 2026-10-08 |
| 7 | Scheduler on by default | Numbers stay current without a click. A failed job is shown on the Pipelines page and sent as a notification (item 8). | P1-M1 | Small | Built 2026-10-08 |
| 8 | Notifications | E-mail or a Teams webhook, one message per person per day: approvals waiting or expiring, budget thresholds, new discovered projects, failed jobs, contract changes and deprecations for consumers. | P1-G4, P1-M2, P1-U1, IA-25 | Medium | Built 2026-10-08 (the in-app inbox works now, and e-mail and Teams once configured) |
| 9 | Test connection for Phoenix | One button answers connected, unauthorized, project not found, unreachable or blocked address. | IA-28 | Small | Built 2026-10-08 |
| 10 | Platform foundation | PostgreSQL, one migration chain checked in CI, secrets in a vault, a real signing key, shared rate limits, tests in CI, a database role that cannot change audit rows, images tagged by commit, a published list of known limits. | P1-H2 to P1-H6, P1-H11, TODO P0, IA-33 | Large | Built 2026-10-08 except shared rate limits (a known limit): migrations repaired and checked on PostgreSQL 18, append-only audit, signing-key guard, CI test stages, commit-tagged images, known limits |
| 11 | The registry's own AI use | A Settings card with each AI function of the registry, its switch, runs, model, prompt version, tokens, cost and a monthly cap. An "AI off" check confirms every page still works. | IA-29, P1 gate G-AI | Medium | Built 2026-10-08 |
| 12 | Manual test cases and defect log | A test-case sheet in the test-maker format, one module per tab and page, and a defect log with causes. | IA-32, TODO P3 | Medium | Built 2026-10-08: 77 manual test cases in 14 modules and a log of 15 defects found and fixed, in the test-maker format (Agent-Registry-Test-Cases-v1.csv and .xlsx) |

## 3. Phase 1: Know Every Agent

| No. | Improvement | What changes for the user | From | Size | Built now |
| --- | --- | --- | --- | --- | --- |
| 13 | Candidate triage | Each discovered candidate gets a guessed owner with the reason, a confidence tier, an assignee and a due date, and can be merged into or split from an existing record. | P1-D7, DP phase B | Medium | Built 2026-10-08 |
| 14 | Identity resolver | One agent seen by several sources becomes one record, matched on endpoint, Phoenix project, service name or model deployment. The registration form says when the chosen Phoenix project is already linked to another record (two records share retail-onboarding now). | P1-D6, DP phase B, IA-24 | Medium | Built 2026-10-08 (matching on service name, API address, name and model with tools, plus the shared-project check) |
| 15 | Discovered page hygiene | Projects that AssureAI creates for its experiments are skipped. Projects named default or holding several services are flagged. Each row shows spans, models and error share. | IA-30 | Small | Built 2026-10-08 |
| 16 | Registry API keys, CLI and CI gate | A build step registers or updates an agent and fails when it is not certified for the target stage. Keys are shown once, stored as a hash, scoped, revocable and logged. | P1-U2, P1-U3, DP phase C, IA-23 | Large | Built 2026-10-08 (keys, CI check, register by manifest, tools/registry_cli.py) |
| 17 | Bulk import | Register many agents from a CSV file, with a preview of what will be created or matched. | P1-R8 | Medium | Built 2026-10-08 |
| 18 | More trace sources | OpenTelemetry (OTLP) and Langfuse adapters next to Phoenix, one adapter each. | P1-M3, DP phase C | Large | Built 2026-10-08 for Langfuse (discovery and usage). An OTLP receiver is not built: apps that send OTLP send it to Phoenix, which the registry reads |
| 19 | Code host scan | A GitHub scan finds agent frameworks, MCP configurations and agent cards in repositories before they run. | P1-D4, DP phase C | Large | Built 2026-10-08 and checked live against public GitHub repositories |
| 20 | Cloud connectors | Microsoft first, then the cloud the first design partner uses. | P1-D2, DP phase D | Large for each cloud | Built 2026-10-08, checked against recorded Azure answers only (no Azure access here) |
| 21 | Trace-attribute convention | The registry reads agent.owner, agent.department and agent.version from spans and fills the record from them. | DP phase C | Small | Built 2026-10-08 (version filled from agent.version, owner and department offered for a person to confirm) |
| 22 | Agent card export | Each certified agent is published as an A2A agent card, so other tools can find the catalogue. | P1-R6 | Medium | Built 2026-10-08 |
| 23 | Silent and retired-but-called agents | A list of Production agents with no trace for 7 days, and a count of calls to Deprecated agents seen in other agents' traces. | IA-10, DP phase C, TODO 3.9 | Medium | Built 2026-10-08 |

## 4. Phase 2: Accountability and Lifecycle

| No. | Improvement | What changes for the user | From | Size | Built now |
| --- | --- | --- | --- | --- | --- |
| 24 | Ownership rules | Owner transfer, a backup owner, and an orphan list when an owner leaves or is deactivated. | P1-R7 | Medium | Built 2026-10-08 (owner and backup owner, takeover when an owner is deactivated, ownerless list) |
| 25 | Time in stage | The agent page shows weeks in the current stage. A stalled-stage alert fires after a limit per stage. | PG-R3, TODO 3.5 | Small | Built 2026-10-08 (weeks in stage on the Governance tab, stall limits per stage in Settings) |
| 26 | Completeness score and required fields | One score per agent and the fields a person still owes, with fields required before Testing. | P1-R3, P1-R4 | Small | Built 2026-10-08 (a completeness score over 15 fields, required fields per stage in Settings) |
| 27 | Classification wizard and record | Questions on purpose, people affected, data used and decisions made. The result is a suggested EU AI Act tier with reasons, confirmed by a named person and stored. | P1-R2, P1-C6 | Medium | Built 2026-10-08 (questions, suggestion with reasons, proposal and confirmation by a decider, retention question for item 61) |
| 28 | Gate templates and enforcement by tier | Which gates, which evidence and how long an approval lasts, set by risk tier. Block or warn is also set by tier. | P1-G2, P1-G3 | Medium | Built 2026-10-08 (gates, approval length and warn or block per risk tier in Settings) |
| 29 | Risk class from tools | An approved list of tools and systems, each low, medium or high. An agent's class is the highest among its tools. | IA-20 | Medium | Built 2026-10-08 (approved tool list in Settings, tool class on the Governance tab and in the classification suggestion) |
| 30 | Changed since approval | A copy and hash of the structural fields at each approval. A change of model, tools or endpoint reopens the gates it affects and says what changed. | P1-G8, IA-17 | Medium | Built 2026-10-08 (a copy and hash of the record at each approval, the daily check reopens the affected reviews) |
| 31 | Tool calls on the approved list | The share of tool calls that go to tools approved at the last review, shown as gate evidence. | IA-11 | Small after item 30 | Built 2026-10-08 (share of traced tool calls that go to tools approved at the last Security Review, from the latest trace sample) |
| 32 | Waivers with two sign-offs | A failed gate can be waived only with a reason and two different signers. Security failures cannot be waived. A report lists open waivers and their end dates. | P1-G11, IA-18 | Medium | Built 2026-10-08 (two different signers, Security failures cannot be waived, waiver report) |
| 33 | Approvals queue, timers and delegation | The queue is ranked by open critical findings, then risk tier, then days waiting. It has a history of decisions, deadline reminders and a deputy for absent reviewers. | P1-G4, P1-G5, IA-19 | Medium | Built 2026-10-08 (ranked queue, overdue after 5 days, decided history, deputies for absent reviewers) |
| 34 | Controls list | Settings shows each control as enforced or only recorded, read from the settings themselves. | IA-21 | Small | Built 2026-10-08 (16 controls, read from the settings each time) |
| 35 | Versions and changelog | Each agent has versions with a changelog, and consumers see which version they use. | P1-U4 | Medium | Built 2026-10-08 (released versions with changelog, the version each team uses, consumers told) |
| 36 | Real offboarding | Retiring an agent runs checked steps: no traffic for 7 days, consumers told, registry keys revoked, stage set to Deprecated. Each step is logged. | TODO 3.9, IA-6 | Medium | Built 2026-10-08 (checked steps, the stage route refuses Deprecated, each step logged) |
| 37 | AssureAI evidence line | The Governance tab shows the latest AssureAI verdict, its date and a link, matched by Phoenix project. No scores are copied. A missing or failed verdict can be set as a readiness gap for Production. | Replaces P1-M5, IA-15 and IA-16 | Medium | Built 2026-10-08, checked against recorded AssureAI answers only. A person or the CI pipeline records the run id, because an AssureAI run key cannot list runs |

## 5. Phase 3: Reuse

| No. | Improvement | What changes for the user | From | Size | Built now |
| --- | --- | --- | --- | --- | --- |
| 38 | Observed consumers | The Integrate tab marks each consumer as approved, seen in traces or both, with the last call and the call count. It lists approved teams that never call and callers that are not approved. | P1-U5, IA-22 | Medium | Built 2026-10-08 (callers recognised by the span attribute consumer.team, or by another agent's traces calling it) |
| 39 | Consumer notices | Approved consumers are told about deprecation, contract change and certification change. | P1-U1 | Small after item 8 | Built 2026-10-08 (retirement, contract change and certification change) |
| 40 | Reuse metrics | Reuse rate, builds avoided and time to first call, per agent and per unit. | P1-U7 | Medium | Built 2026-10-08 (reuse rate, builds avoided and time to first call, per agent and per unit) |
| 41 | Programme health page | Known against discovered agents, owner coverage, approval speed, overdue reviews and reuse rate on one page. | P1-L1 | Medium | Built 2026-10-08 (Programme Health page) |
| 42 | Search-gap report | What people searched for and did not find, as a signal for new shared agents. | P1-L2 | Small | Built 2026-10-08 (empty searches on the AI Registry page, on Programme Health) |
| 43 | Start from a certified agent | A new registration can copy a certified agent's contract as its starting point. | P1-U8 (could) | Small | Built 2026-10-08 (registration form) |
| 44 | Chargeback between units | The cost of a shared agent is split across the units that call it. | P1-U9 (could) | Medium | Built 2026-10-08 (token cost split by calls seen from approved teams, equally when none are seen, CSV export) |

## 6. Phase 4: Cost and Value

| No. | Improvement | What changes for the user | From | Size | Built now |
| --- | --- | --- | --- | --- | --- |
| 45 | Value attestation | The owner declares value, a finance reviewer confirms or adjusts it with a note and a date, and pages mark value as declared or attested. | P1-V1 | Medium | Built 2026-10-08 (Finance Reviewer role, attested, adjusted or declared again shown with every value) |
| 46 | Value method | Cost avoidance, revenue influenced, time saved with a rate, or risk avoided, shown next to every value figure. | P1-V2 | Small | Built 2026-10-08 (method and basis with every value figure) |
| 47 | Measured outcomes and cost per outcome | Outcomes come from a CSV file or a webhook, and cost per outcome is calculated from measured outcomes. | P1-V3, P1-V7, P1-M9 | Medium | Built 2026-10-08 (CSV, webhook or typed in, cost per outcome over 30 days) |
| 48 | Scorecard report | A one-page PDF per unit and for the portfolio: agents, value, cost, return, risk and reuse. | P1-V5 | Medium | Built 2026-10-08 (one-page PDF per unit and for the portfolio) |
| 49 | Reuse savings | Builds avoided multiplied by an agreed build cost. | P1-V6 | Small after item 40 | Built 2026-10-08 (agreed build cost in Settings) |
| 50 | Model what-if and price forecast | The last 30 days of tokens priced at other models, with "quality was not compared", and the effect of a price change. | P1-M10, P1-M11, IA-14 | Small | Built 2026-10-08 (the same tokens at every priced model, a price change slider, quality not compared) |
| 51 | Cost without Phoenix | Usage entered by hand or imported from CSV for agents with no tracing. | P1-M12 | Medium | Built 2026-10-08 (typed in or imported for agents without tracing, source shown as entered by hand) |
| 52 | Azure cost setup and test | A guided setup with a test of the Azure Cost Management connection. | P1-M4 | Small | Built 2026-10-08, not tested against a live Azure subscription (no access here) |
| 53 | Idle and duplicate spend | Production agents with no traffic but with infrastructure cost, and agents that duplicate another one while both are paid for. This replaces the placeholder waste job. | TODO 3.7, IA-10 | Medium | Built 2026-10-08 (daily spend review job, findings shown as financial risks). The placeholder job is kept unused until the final cleanup |
| 54 | Scenario view | "If these agents move to Production", the change in value and cost. | P1-V8 (could) | Small | Built 2026-10-08 (Business Impact) |

## 7. Phase 5: Compliance and Audit

| No. | Improvement | What changes for the user | From | Size | Built now |
| --- | --- | --- | --- | --- | --- |
| 55 | Compliance packs with dates | Control lists for EU AI Act, ISO 42001, NIST AI RMF and an India pack, kept as data. Regulatory dates are settings. | P1-C2, P1-C10 | Large | Built 2026-10-08 (EU AI Act 17, ISO/IEC 42001 Annex A 38, NIST AI RMF categories 19, India DPDP Act 10). The default dates are to be checked against the official texts |
| 56 | Control coverage view | For example "ISO 42001: 31 of 38 controls evidenced", with the missing controls named. | P1-C3 | Medium | Built 2026-10-08 (Compliance page, missing evidence named per agent) |
| 57 | Evidence pack export | A PDF and CSV per agent and per control, with a hash. | P1-C4 | Medium | Built 2026-10-08 (PDF and CSV, SHA-256 recorded in the audit trail, a copy can be checked against it) |
| 58 | Auditor role | Read-only access with an end date, and every access logged. | P1-C5 | Small after item 5 | Built 2026-10-08 (end date required, every request logged) |
| 59 | Hash-chained decision log | Each decision record carries the hash of the one before, and a check shows any change. | P1-C7, P1-G7 | Medium | Built 2026-10-08 (decisions sealed after each commit in an append-only chain table, check on the Compliance page) |
| 60 | Incidents and stop requests | Link an incident in PagerDuty or ServiceNow to an agent, ask the owner to stop it, and keep an incident and change history per agent. | P1-M7, P1-C8 | Medium | Built 2026-10-08. Incidents are linked by address or posted by PagerDuty or ServiceNow automation. The registry does not read those systems |
| 61 | Data and retention report | The personal data each agent touches and how long it is kept, from the classification answers. | P1-C11 | Small after item 27 | Built 2026-10-08 (Compliance page, from the classification answers) |
| 62 | GRC export | Export to ServiceNow, OneTrust or Archer. | P1-C9 (could) | Medium | Built 2026-10-08 (CSV for the import step of each tool, column mapping done in the tool) |

## 8. What the Registry Does Not Build

**Table 8.1. Covered by AssureAI, so not built in the registry (11 items)**

| Item | Where it came from | What the registry does instead |
| --- | --- | --- |
| Quality scorecard: success rate, latency P50 and P95, throughput, tokens per request, trace completeness, telemetry coverage | IA-8 | Keeps its existing usage, cost and risk figures. AssureAI's trace-only checks measure these. |
| Latency and success alerts against the past week | IA-9 | Keeps its existing cost anomalies. AssureAI raises regressions between runs. |
| Loop detection and step efficiency | IA-12 | Nothing. AssureAI's Step Efficiency check covers it. |
| "n of m checks measurable" and instrumentation hints | IA-13 | Its insight card says only why a registry field could not be filled in. |
| Evaluator score panel and evaluation score import | IA-15, P1-M5 | One evidence line with a link (item 37). |
| AssureAI pillar scores on the agent page | IA-16 | One evidence line with a link (item 37). |
| Per-step latency and token breakdown | IA-9 | Nothing. The Diagram tab keeps its structure view. |
| Trace Content Audit insight (built now) | Insights plan, agent 8 | Switch it off and remove it. It judges answer quality, which is AssureAI's task. |
| SLA tracking beyond the existing rule | P1-M8 | Keeps the one rule that raises a finding when the 95th-percentile time exceeds the declared SLA. AssureAI tracks service-level burn. |
| New safety scoring of PII and injection | P1-M6 | Keeps the counts of PII and injection flags already on spans as risk register entries. |
| An evaluation harness in backend/evaluations | TODO 1 | Nothing. The folder is unused scaffold. |

**Table 8.2. Not built for other reasons (9 items)**

| Item | Where it came from | Reason |
| --- | --- | --- |
| Runtime enforcement, circuit breaker, automatic pause on budget, policy checks at call time | TODO 3.2, TODO 3.5 | The registry asks the owner to stop an agent and never stops one itself until the enforcement gate is passed (product plan section 15.3). |
| Model routing service, prompt compression, conversation pruning | TODO 3.6 | These belong to the agent's own runtime. |
| Temporal workers and the LangGraph supervisor scaffold | TODO P3 | Not used by any registry feature. Remove them with item 4 or leave them alone. |
| Live ticker in the top bar and persona tags | PG-G1, PG-G2 | The Executive page already holds the same totals. |
| Policy as code | P1-G6 | Comes after the fixed tier templates of item 28 are in use. |
| Committee meeting mode | P1-G10 | Low demand. The queue of item 33 covers batch review. |
| Public or partner catalogue | P1-U10 | The plan marks it Won't for now. |
| Agents on laptops | P1-D10 | Belongs to a different security product. |
| Benchmarks across customers | P1-V9 | Needs many customers and their consent. |

## 9. Decisions for the Owner

| No. | Decision | Recommendation |
| --- | --- | --- |
| 1 | Switch off and remove the Trace Content Audit insight | Yes. Answer quality is AssureAI's task. |
| 2 | The 16 demo agents: hide behind a switch or delete | Hide behind a switch (item 1). |
| 3 | Turn on role checks before building waivers and the auditor role | Yes. Items 32 and 58 need more than the 1 user that exists now. |
| 4 | The first outside source after Phoenix | The CI gate and registry API (item 16). They need no customer cloud access and bring agents in at build time. |
| 5 | How the registry reads the AssureAI verdict (item 37) | A run-scoped key per application, matched by Phoenix project. Whether the routes return real data is still to be verified in AssureAI. |
