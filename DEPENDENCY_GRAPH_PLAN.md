# Agent Registry — Complete Dependency Graph Plan (v1)

**Goal:** bring the Agent Registry's dependency graph to the same standard as **cobol_contextintel** — an interactive, information-rich, end-to-end dependency graph with a shared backend/UI contract, legend toggles, hierarchical drill-down, and impact analysis wired into the visualisation.

**Reference studied:** `cobol_contextintel` — `analysis/neo4j_graph_view.py`, `graph_store/neo4j_loader.py`, `api/routers/graph.py`, `frontend/app.js::showNeo4jGraph`, `.claude/skills/dependency-graph/SKILL.md`.

---

## 1. What cobol_contextintel does (the standard to match)

### The end-to-end chain

```
analysis pipeline → JSON artifacts (call_graph, file_access, batch_graph,
                    cics_graph, functional_groups, rules)
        ↓
Neo4j graph store (loader proves a round-trip; graph facts live in a real graph DB)
        ↓
Server-side pyvis builder → one HTML document, every node/edge styled in Python
        ↓
API returns {html, node_count, edge_count, entry_point_count, legend, group_colors}
        ↓
Frontend: legend chips + metric tiles in the parent, sandboxed <iframe srcdoc> for the canvas
        ↓
parent ⇄ iframe postMessage protocol (filters, focus, readiness)
```

**The load-bearing design rules (copy these, they are the "why" behind everything):**

1. **`ci_kind` mutual exclusivity** — every node carries exactly one kind; the legend offers one toggle per kind. Entry-point-ness is a *border decoration* (`ci_entry` attribute), never a kind.
2. **An edge is hidden when either endpoint is hidden** — no arrows pointing at empty space.
3. **Nodes are hidden, never removed** from the DataSet — toggling a kind back on restores the exact layout instead of re-stabilising.
4. **One visibility code path** — filters and focus mode go through the same `applyFilters()`.
5. **The hierarchical view is BFS, out-edges only, first visit wins** — "what happens when this entry point fires", drawn as a tree; physics off, positions captured and restored; `fit()` scoped to tree nodes; branch edges straight, loop-backs curved.
6. **A "which end do I edit" table** is maintained as a contract — every visual change has exactly one owner file.

**Node kinds (reference):** `group:<Name>` (functional), `external`, `data_file`, `cics_map`, `jcl_job`, `jcl_step`. Entry-point-ness = border decoration (`ci_entry: batch|online|both`).

**Interactivity:** legend chips with live visible counts, master toggle, right-click "Hierarchical view from here" on entry points, focus banner with way back, hover tooltips, physics layout, metric tiles, per-node rule counts.

---

## 2. Current agentregistry state (the gap)

| Capability | cobol_contextintel | agentregistry today |
|---|---|---|
| Graph source | Pipeline artifacts + Neo4j store (round-trip proven) | Built on the fly from `agents` JSON columns (`enterprise_systems`, `databases`, `mcp_servers`) |
| Node kinds | 6+ kinds, namespaced, mutually exclusive | 4 informal types (`agent`, `system`, `database`, `mcp`) — **knowledge bases and consumers have no node at all** |
| Edge types | Typed + labelled (calls, access modes, TRIGGERS, RUNS) | Untyped grey lines; `calls` and `consumers` ignored as edges (agents float isolated) |
| Interactivity | Zoom/pan/physics, kind toggles, right-click hierarchical view, tooltips | Static radial SVG; click for a small detail panel only |
| Entry points | `ci_entry` borders + right-click "hierarchical view from here" | None |
| Impact/blast radius | — | Backend endpoint exists (`orchestrations/impact_analysis.py`) but **not visualised on the graph** |
| Concentration risk | — | Endpoint exists, not visualised |
| Summary metrics | Node/edge/file/entry counts + tiles + processing order | None |
| Maintenance contract | "Which end do I edit" table | None |

**Key data we already have but the graph ignores:** `knowledge_bases`, `consumers`, `calls` (agent→agent), `inputs`/`outputs`, stage, dept, model, value, `at_risk`, governance review states, token usage.

---

## 3. Target model for the Agent Registry

### 3.1 Node kinds (mutually exclusive, namespaced)

| `kind` | Nodes | Shape hint |
|---|---|---|
| `group:<dept_id>` | agents, one kind per department (Finance, HR, CX, …) — mirrors cobol's functional groups | circle |
| `system` | enterprise systems (SAP, Salesforce, Zendesk, …) | database shape |
| `database` | Snowflake, Databricks, … | database shape |
| `knowledge_base` | policy KBs, runbooks, playbooks | box |
| `mcp_server` | MCP/tool servers | box |
| `consumer` | downstream dashboards, queues, channels, portals | box |
| `external` | referenced but unregistered (shadow-AI candidates) | circle, pale fill |

**Entry-point-ness is a border decoration, not a kind** — `entry: production | pipeline` on agent nodes (Production = green border, Testing/Development = amber, Ideation = grey). Also ride-along attributes: `at_risk`, `model_name`, `value_amount`, `stage`, `dept_id`, `governance` (worst gate status) — these drive tooltips and overlays, never filters.

### 3.2 Edge types

| Edge | Meaning | Drawn as |
|---|---|---|
| `CALLS` | agent → agent (from `calls`) | solid, labelled |
| `CONSUMED_BY` | agent → consumer (from `consumers`) | dashed |
| `ACCESSES` | agent → system / database | dashed, coloured by target kind |
| `USES_KB` | agent → knowledge_base | dashed |
| `USES_MCP` | agent → mcp_server | dashed |

Every edge keeps `type` + endpoints; the backend also derives **reverse edges** for consumers so blast radius can walk upstream and downstream.

---

## 4. End-to-end architecture

```
agents + governance + token usage tables (SQLite today; Postgres/Neo4j optional)
        ↓  read by
services/graph_service.py        ← SINGLE graph builder (nodes, kinds, edges, metadata)
        ↓  served by
api/routers/graph.py  GET /api/v1/graph/v2
        → {nodes:[{id,name,kind,attrs}], edges:[{from,to,type}],
           legend:[{kind,label,count,color}], stats:{...}}
frontend
  PlatformView + DependencyGraphView → shared <DependencyGraph> component
  (react-flow canvas; legend chips; metric tiles; right-panel details)
```

Decisions:

1. **One graph builder** (`services/graph_service.py`) used by every endpoint (graph, impact, concentration) — cobol's "same builder for all surfaces" rule. Kill the duplicated adjacency-list code in `impact_analysis.py`.
2. **Graph store: stay on SQLite/Postgres first, Neo4j optional.** The registry graph is small (tens of agents); recursive CTEs in SQL are enough. Add `graph_store/neo4j_loader.py` (port of cobol's) behind a settings flag only when cross-run analysis or scale demands it — same shape as cobol so the port stays symmetric.
3. **Rendering: react-flow in the SPA**, not the pyvis-iframe trick. Cobol needed pyvis because its frontend is vanilla JS; agentregistry is a React SPA — but we **port the contracts, not the tech**: kinds, legend chips, hidden-not-removed, edge-hides-with-endpoint, one visibility code path, positions on toggle.
4. **Interactive contract (react-flow equivalents of the postMessage protocol):** one filter state (hidden kinds + dept/stage filter + search), one focus state (hierarchical root), one overlay state (impact result) — each rendered by exactly one component; the graph consumes all three through a single `useGraphView` hook.

---

## 5. Feature list (what "interactive and information" means here)

1. **Interactive legend chips** — one per kind, live visible-count per chip, master toggle; hiding a kind prunes its nodes *and* edges.
2. **Rich node visuals** — colour by department (group kind), border by stage/entry (Production green thick, Testing amber, Ideation grey), ▶ marker on `at_risk`, size by monthly value or token spend.
3. **Tooltips + right panel** — on hover/click: name, dept, stage, model, value/mo, hours saved, token cost, worst governance gate, at-risk note; Dependencies (out-edges) and Consumers (in-edges) lists, each clickable (traverses the graph).
4. **Hierarchical view from any agent** — right-click → "Show what this agent affects": BFS over out-edges, tree layout under the root (first-visit-wins parent, loop-backs drawn but not re-parented), physics off, previous positions restored on exit, scoped `fit()` — the cobol rules verbatim.
5. **Impact/outage overlay** — click "Simulate outage" on a node → existing `POST /graph/impact/{id}` runs → affected nodes highlighted red, downstream edges pulse, panel shows revenue at risk, hours at risk, affected departments, risk level, mitigation suggestions.
6. **Concentration-risk highlighting** — systems/databases with ≥ N dependents get a warning badge and a "spotlight" filter (reuses `/graph/concentration-risk`).
7. **Search & filter bar** — by name, department, stage, model; filters compose with kind toggles.
8. **Metric tiles above the canvas** — agents, dependencies, cross-agent calls, orphaned agents (zero edges), cross-department edges.
9. **Live refresh hook** — orchestrations (discovery, offboarding, agent create/update) publish `graph.changed` on the existing WebSocket bus; the graph view re-fetches (closes the WS-stub gap in TODO v2).

---

## 6. Implementation phases

### Phase 1 — Backend graph service + API v2 *(backend only, no UI change)*
- Create `backend/services/graph_service.py`: builds nodes/edges/kinds/legend from Agent rows; typed edges incl. `CALLS`, `CONSUMED_BY`, `ACCESSES`, `USES_KB`, `USES_MCP`; reverse edges; orphan detection; per-node attribute payload (stage, dept, value, model, at_risk, worst gate).
- New endpoints on `graph_router`:
  - `GET /api/v1/graph/v2` → nodes, edges, legend (kinds + counts + colours), stats
  - `GET /api/v1/graph/entry-points` → agents that are outage roots (Production + having consumers or callers)
  - keep `GET /graph/concentration-risk` and `GET /graph/impact/{node_id}` — refactor impact to use the shared builder
- Refactor `orchestrations/impact_analysis.py` to consume `graph_service` (removes duplicated adjacency code, fixes `consumers` being ignored).
- Tests: builder unit tests (kinds mutually exclusive, reverse edges, orphans), impact parity tests.

### Phase 2 — Interactive canvas (UI)
- New `ui/src/components/DependencyGraph.tsx` (react-flow) + `useGraphView` hook (filter/focus/overlay state).
- Legend chips, metric tiles, search box, right details panel; `DependencyGraphView` and `PlatformView` switch to it.
- Visual vocabulary from §3.1; edge styling from §3.2.

### Phase 3 — Hierarchical view + impact overlay
- "Show what this agent affects" (BFS tree, layout rules from cobol: physics off, saved positions, straight branches, curved loop-backs, scoped fit).
- Outage simulation overlay wired to the impact endpoint; concentration-risk spotlight.

### Phase 4 — Store upgrade (optional)
- `graph_store/neo4j_loader.py` port for cross-run/portfolio-scale analysis behind `settings.graph_store = "neo4j" | "sql"`; the service layer stays the only consumer so API/UI never change.

### Phase 5 — Live graph
- Publish `graph.changed` from create/update/delete/offboard/discovery paths; graph view subscribes and re-fetches with a visual "graph updated" toast.

---

## 7. Which end do I edit (maintenance contract)

| Change | File |
|---|---|
| Which nodes/edges exist, kinds, attributes, legend data | `backend/services/graph_service.py` |
| Blast radius, risk level, mitigation | `backend/orchestrations/impact_analysis.py` (via graph_service) |
| API shapes for the graph | `backend/api/routers/graph.py` |
| Node/edge visuals, tooltips, legend chips, metric tiles | `ui/src/components/DependencyGraph.tsx` |
| Filter/focus/overlay state rules | `ui/src/hooks/useGraphView.ts` |
| Hierarchical layout rules | `ui/src/hooks/useHierarchicalLayout.ts` |
| Live refresh behaviour | `ui/src/hooks/useGraphLive.ts` + `backend/api/websocket_events.py` publishers |

---

## 8. Acceptance checklist

- [ ] `GET /graph/v2` returns every node with exactly one kind; legend counts match node counts
- [ ] No agent floats isolated when it has `calls`/`consumers` (typed edges present)
- [ ] Hiding a kind removes its edges; re-showing restores the same layout
- [ ] Hierarchical view from a Production agent shows only what it reaches (out-edges), tree-shaped, exits back to the exact previous layout
- [ ] Outage simulation highlights affected subgraph with revenue/hours at risk and depts
- [ ] Concentration-risk systems carry warning badges and a spotlight filter
- [ ] Registry edits reflect in the graph without a manual reload (WS event)
- [ ] Cobol-parity rules hold: kinds mutually exclusive · edges hide with endpoints · nodes hidden-not-removed · one visibility code path
