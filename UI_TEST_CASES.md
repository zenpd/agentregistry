# Agent Registry - UI Test Cases

Precondition: backend on http://localhost:8001, frontend on http://localhost:5173.
Demo creds: admin@airegistry.local / admin123
## 1. Authentication
TC-AUTH-01 | Navigate to /agents without login | Redirect to /login | Expected: login page with Sign in heading visible
TC-AUTH-02 | Fill email=admin@airegistry.local, password=admin123, click Sign in | Redirect to / | Expected: Executive Overview heading visible
TC-AUTH-03 | Fill bad credentials, click Sign in | Stay on /login | Expected: Invalid credentials error visible
TC-AUTH-04 | Fill empty email/password, click Sign in | Stay on /login | Expected: HTML5 validation blocks submit
## 2. Executive Overview (/)

TC-EXEC-01 | Load / | KPI cards visible | Expected: Total Agents, Monthly Value, In Pipeline, At Risk, AI Types cards render
TC-EXEC-02 | Load / | Pipeline rail shows 5 stages | Expected: Ideation, Development, Testing, Production, Deprecated columns
TC-EXEC-03 | Load / | Portfolio Mix by AI Type chart | Expected: SVG bar chart renders with categories
TC-EXEC-04 | Load / | Value by Business Unit chart | Expected: SVG bar chart renders with dept labels
TC-EXEC-05 | Load / | Top Agents table | Expected: table with Agent, Type, Department, Stage, Value/mo, Basis columns
TC-EXEC-06 | Load / | At Risk section | Expected: Needs Attention section visible when at_risk agents exist
TC-EXEC-07 | Click pipeline chip agent name | Opens detail modal | Expected: AgentDetailModal visible with agent data
TC-EXEC-08 | Click outside modal | Closes modal | Expected: modal disappears
## 3. AI Registry (/agents)

TC-REG-01 | Load /agents | Registry header + Register button | Expected: AI Registry heading and + Register new AI application button
TC-REG-02 | Load /agents | Filter dropdowns | Expected: All stages, All types, All departments selects visible
TC-REG-03 | Load /agents | Category chips | Expected: All, MCP, Systems, Databases, Knowledge, Agent calls chips
TC-REG-04 | Type "Demand" in search | Filters results | Expected: only agents with Demand in name shown
TC-REG-05 | Select stage=Production | Filters results | Expected: all cards show Production badge
TC-REG-06 | Select type=Autonomous Agent | Filters results | Expected: only Autonomous Agent cards shown
TC-REG-07 | Click MCP category chip | Filters results | Expected: only agents with mcpServers shown
TC-REG-08 | Click a registry card | Opens detail modal | Expected: AgentDetailModal visible with full agent data
TC-REG-09 | Click + Register new | Opens create modal | Expected: Create Agent form visible
TC-REG-10 | Fill name=Test Agent, click Create | Creates agent | Expected: success toast, agent appears in list
TC-REG-11 | Click Close on detail modal | Closes modal | Expected: modal disappears, back to grid
## 4. Governance & Discovery (/governance)

TC-GOV-01 | Load /governance | KPI cards | Expected: Cleared, Blocked, In active review, Unregistered AI apps found
TC-GOV-02 | Load /governance | Gate breakdown | Expected: Architecture Review, Security Review, Data Protection cards with status counts
TC-GOV-03 | Load /governance | Review status table | Expected: Agent, Stage, arb/security/dp selects, Actions columns
TC-GOV-04 | Change arb status to Approved | Saves review | Expected: value persists, table updates
TC-GOV-05 | Click Run review | Triggers governance workflow | Expected: button shows Running... then refreshes data
TC-GOV-06 | Discovery feed cards | Expected: suspectedName, dept, source, confidence badge, Register + Dismiss buttons
TC-GOV-07 | Click Register on discovery | Registers agent | Expected: discovery removed from pending list
TC-GOV-08 | Click Dismiss on discovery | Dismisses | Expected: discovery removed from pending list
## 5. Business Impact (/business)

TC-BIZ-01 | Load /business | Header + dept filter | Expected: Business Impact heading, All + dept buttons
TC-BIZ-02 | Load /business | 3 KPI cards | Expected: Agents Running, Value/Month, Hours Saved/Month
TC-BIZ-03 | Click dept-supply-chain | Filters table | Expected: only supply-chain agents shown
TC-BIZ-04 | Click All | Resets filter | Expected: all agents shown
TC-BIZ-05 | Load /business | Dept value cards | Expected: per-department cards with agentCount and totalValue
TC-BIZ-06 | Load /business | Agent table columns | Expected: Agent, Department, AI Type, Stage, Owner, Outcome, Value/mo, Hours Saved
## 6. Platform & Dependencies (/platform)

TC-PLT-01 | Load /platform | Mini cards | Expected: Enterprise Systems, Databases, MCP Servers, Knowledge Bases cards with counts
TC-PLT-02 | Load /platform | Concentration risk | Expected: bars showing agents per system/db
TC-PLT-03 | Load /platform | Cross-AI Call Network SVG | Expected: NetworkGraph renders with nodes and edges
TC-PLT-04 | Load /platform | Edge table | Expected: Caller, Callee, Why columns with rows
TC-PLT-05 | Load /platform | Initiative-Integration matrix | Expected: grid of agents x systems with ●/— cells
## 7. Tokenomics (/tokenomics)

TC-TOK-01 | Load /tokenomics | KPI cards | Expected: Agents in Production, Total Value/mo, Model Types, Optimization Opportunities
TC-TOK-02 | Load /tokenomics | Model pricing table | Expected: Model, Provider, Tier, Input/1M, Output/1M columns with 5 rows
TC-TOK-03 | Load /tokenomics | Optimization suggestions | Expected: yellow section with agentName and reason when findings exist
TC-TOK-04 | Load /tokenomics | Agent cost estimates | Expected: Agent, Model, Stage, Value/mo table for production agents
## 8. Dependencies (/dependencies)

TC-DEP-01 | Load /dependencies | Header | Expected: Dependency Graph heading
TC-DEP-02 | Load /dependencies | SVG graph | Expected: circle nodes arranged radially with labels
TC-DEP-03 | Click a node | Selects node | Expected: node turns blue, detail panel shows Dependencies + Consumers
TC-DEP-04 | Click empty area | Deselects | Expected: detail panel shows Click a node to see details
## 9. Security & Compliance (/security)

TC-SEC-01 | Load /security | KPI cards | Expected: High Severity, Medium Severity, Low Severity, Agents Reviewed
TC-SEC-02 | Load /security | Findings table | Expected: Severity, Category, Agent, Description columns
TC-SEC-03 | Load /security | Decommissioning candidates | Expected: Deprecated agents listed with risk note
## 10. Dashboard (/dashboard)

TC-DASH-01 | Load /dashboard | Header | Expected: Welcome to Agent Registry heading
TC-DASH-02 | Load /dashboard | API Status card | Expected: Healthy (backend reachable)
TC-DASH-03 | Load /dashboard | Agents Registered card | Expected: number matching /api/v1/agents pagination.total
TC-DASH-04 | Load /dashboard | Governance Reviews card | Expected: number matching sum of all gate status counts
TC-DASH-05 | Load /dashboard | Quick links | Expected: 8 quick-link cards to each page

## 11. Playground (/playground)

TC-PLAY-01 | Load /playground | Header | Expected: Agent Playground heading
TC-PLAY-02 | Type message, click Send | Sends to /example/start | Expected: assistant reply appears
TC-PLAY-03 | Send second message | Resumes session | Expected: session_id and step shown

## 12. Settings (/settings)

TC-SET-01 | Load /settings | Header | Expected: Settings heading
TC-SET-02 | Load /settings | Guidance text | Expected: mentions .env.example and nginx proxy
