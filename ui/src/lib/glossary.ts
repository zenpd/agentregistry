// Short, plain definitions for the ⓘ tips next to registry terms (one place, one wording).
// Keep each to one or two short sentences. Add a term here, then use <InfoTip term="…" />.
export const GLOSSARY = {
  // ── Discovery ────────────────────────────────────────────────────────────────
  discovered: 'Phoenix projects that are sending traces but are not linked to a registered agent yet. Register each one, or dismiss it.',
  phoenix_project: 'The Phoenix project that holds this agent’s traces. Linking it is what brings in usage, cost and last-seen activity.',
  phoenix_scan: 'Reads every Phoenix project (read-only) and notes its models, tools and last activity. Runs daily when the scheduler is on, or press Scan now.',
  discovery_activity: 'Active: calls in the last scan window. Quiet: seen before, none lately. Stale: not seen for a long time. No calls: Phoenix lists it but it has no recent traces.',
  discovery_dismiss: 'Hides a project that is not an agent (a test, a duplicate). A reason is required, and you can bring it back later.',
  discovery_prefill: 'Starting values for the form, taken from traces or the app itself. Each one shows where it came from; nothing is saved until you confirm.',
  prefill_url: 'Paste the app’s address and the form fills from its agent card or OpenAPI document. Nothing is created until you press Register.',
  app_url_template: 'How your app addresses are built from the Phoenix project name. With it, registering a discovered project finds the app by itself; the address is a guess, so check it.',
  agent_card: 'A small public file (/.well-known/agent-card.json) where an agent describes itself: name, what it does, how to call it.',
  openapi_doc: 'The app’s own list of API operations (/openapi.json). Used to fill the description and capabilities, and by Try it.',
  backend_sibling: 'Web apps often come as a -fe (screen) and a -be (API) pair. The registry looks for the API on the -be address.',
  governance_findings: 'Checks on agents that are already registered (stalled, no reviews, shared systems). They are not new agents.',
  unregistered_ai: 'AI that was found running but is not in the registry. Registering it puts an owner and reviews around it.',

  // ── AI insights ──────────────────────────────────────────────────────────────
  ai_insight: 'An AI agent reads this agent’s records and writes what it finds. Each finding links to the record it came from. It never changes anything, and a person decides what to do.',
  trace_content: 'The actual text of what users asked and what the agent answered. The registry does not read it unless the owner switches this on, and never stores it.',
  ask_registry: 'Ask a question in plain words. An AI agent looks it up in the registry and answers with links. It cannot answer about anything outside the registry.',

  // ── Agent record ─────────────────────────────────────────────────────────────
  agent: 'An AI application the registry tracks: an agent, copilot, chatbot or model feature.',
  stage: 'Where the agent is in its life: Ideation, Development, Testing, Production or Deprecated. Moving it forward needs its reviews.',
  ai_type: 'What kind of AI it is, such as an autonomous agent, copilot or chatbot. It affects which risks are checked.',
  risk_level: 'How much oversight the agent needs. Higher levels need more reviews before production.',
  owner: 'The person accountable for the agent. Reviews, access requests and reminders go to them.',
  department: 'The business unit that runs the agent. Business Impact groups value and cost by department.',
  business_outcome: 'The result the agent exists to deliver, in one line. It is what its value is measured against.',
  declared_value: 'The monthly value the owner says the agent delivers. It is a claim until finance confirms it.',
  hours_saved: 'Hours of human work the agent saves each month, as declared by the owner.',
  capabilities: 'What the agent can do, one per line. Search and the duplicate check use these.',
  api_endpoint: 'The address where the agent is reached. Try it and the contract use it.',
  mcp_servers: 'Tools and MCP servers the agent calls. Adopting them from traces keeps the dependency map accurate.',
  consumers: 'Teams and agents that use this agent. They are told when it changes or retires.',
  sla: 'The service level the owner promises, for example 99.5% uptime or a 2 second answer.',
  similar_agents: 'Agents that look like this one by name, purpose or endpoint. Reuse one if it fits.',

  // ── Governance ───────────────────────────────────────────────────────────────
  gate: 'A review the agent must pass: Architecture, Security and Data Protection. Each has a reviewer role, evidence and an expiry.',
  gate_arb: 'Architecture Review Board: checks the design fits company standards and is supportable.',
  gate_security: 'Security review: checks access, secrets, data handling and attack surface.',
  gate_dp: 'Data Protection review: checks personal data use, retention and legal basis.',
  review_status: 'Not submitted, In review, Approved, Conditions or Changes requested. Only a reviewer sets it.',
  approval_expiry: 'Approvals expire, so they stay current. An expired approval needs recertifying.',
  recertification: 'Reopening a review because the approval expired or the agent changed materially.',
  stage_rules: 'Which reviews an agent needs for each stage. In warn mode they show a warning but never block a change.',
  governance_exception: 'A time-limited permission to skip one gate, with a reason and an end date.',
  self_approval: 'Lets the same person submit and approve. It is for testing only; switch it off before going live.',
  approvals_inbox: 'Everything waiting for someone’s decision across all agents, in one list.',
  material_change: 'A change that matters to reviewers, such as a new model, tool or endpoint. It can reopen reviews.',

  // ── Reuse ────────────────────────────────────────────────────────────────────
  certified_for_reuse: 'Other teams can safely build on this agent: it is in Production, all three reviews are approved and in date, and no high risk is open. It is worked out automatically.',
  certification_checks: 'The list of tests behind “certified”. Each one shows passed or failed with the reason.',
  try_it: 'Sends a real test call to the agent’s API from the server, so you can see how it answers before requesting access.',
  access_request: 'A team asks the owner to use this agent. Once approved they appear as a consumer.',
  contract: 'What the agent promises: its address, inputs, outputs, service level and rate limit.',

  // ── Cost, value and risk ─────────────────────────────────────────────────────
  tokens: 'The pieces of text a model reads and writes. Models charge by the token.',
  cost_to_run: 'What the agent costs each month: model tokens plus the infrastructure it runs on.',
  cost_complete: 'Whether both parts of the cost (tokens and infrastructure) are known. If not, the cost shown is a floor.',
  return_on_cost: 'Declared value divided by cost to run. Above 1× means it returns more than it costs.',
  value_waiting: 'Value declared for agents that are not live yet. It is what going live would add.',
  missing_numbers: 'Agents without a declared value, outcome or owner. Fill these in to make the totals trustworthy.',
  budget: 'The monthly spend limit set for an agent. Crossing the warning line raises an alert.',
  cost_anomaly: 'A day when spend jumped well above the agent’s normal level.',
  tokenomics: 'Token usage and cost per day and per model, read from Phoenix traces.',
  usage_demo: 'Example numbers shown until real usage arrives from Phoenix.',
  risk_register: 'The list of risks found for an agent. Each has a severity and moves through open, mitigating and resolved.',
  severity: 'How serious a risk is: Low, Medium, High or Critical. High and Critical stop an agent being certified for reuse.',
  blast_radius: 'Who and what would be affected if this agent failed or was removed.',
  concentration_risk: 'Many agents depending on the same system, model or tool, so one failure hits them all.',
  dependency_graph: 'A map of which agents, tools, models and systems each agent relies on.',

  // ── Operations ───────────────────────────────────────────────────────────────
  scheduler: 'Runs the daily jobs by itself. When it is off, numbers only change when someone presses Refresh or Run now.',
  job_run_log: 'Every job run with its time, who or what started it, and its result.',
  usage_ingestion: 'Reads LLM calls from each agent’s Phoenix project and stores daily token usage per model.',
  infra_costs: 'Pulls hosting cost from Azure Cost Management and assigns it to agents.',
  cost_rollup: 'Turns usage into daily cost, checks budgets and flags anomalies.',
  risk_scan: 'Runs the risk rules over every agent and records what it finds.',
  governance_checks: 'Finds approvals that are expiring or expired, and agents that need recertifying.',
  insight_refresh: 'Rewrites the AI insights on each traced agent’s tabs once a day, after the figures are refreshed. It only reads.',
  phoenix_discovery: 'Finds Phoenix projects that are not registered yet and lists them on the Discovered page.',
  audit_log: 'A record of who changed what and when.',
  user_role: 'What a person may do: admin, owner, reviewer, finance reviewer, viewer or auditor.',

  // ── Added by tooltip pass
  common_endpoint: 'The org-wide Phoenix/OTel address that onboarding and discovery use by default. An app can still set its own.',
} as const

export type GlossaryKey = keyof typeof GLOSSARY
