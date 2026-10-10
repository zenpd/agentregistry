import { Link } from 'react-router-dom'
import {
  BadgeCheck, BarChart3, ClipboardList, FileText, KeyRound, LineChart, PlusCircle, Radar, ShieldCheck, Users,
} from 'lucide-react'

type Status = 'working' | 'setup' | 'prototype' | 'planned'
const STATUS: Record<Status, { label: string; className: string }> = {
  working: { label: 'Working', className: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  setup: { label: 'Needs setup', className: 'bg-amber-50 text-amber-800 ring-amber-200' },
  prototype: { label: 'Prototype', className: 'bg-sky-50 text-sky-700 ring-sky-200' },
  planned: { label: 'Planned', className: 'bg-slate-100 text-slate-700 ring-slate-200' },
}

// An agent's path through the registry, from first registration to reuse.
const JOURNEY: { title: string; what: string; where: string; to: string; icon: typeof PlusCircle }[] = [
  { title: 'Register', what: 'Pick a project found in Phoenix, or paste the app’s address, and the form fills itself. Similar agents are shown first, so a team reuses instead of rebuilding.', where: 'Discovered Agents · Agent Registry', to: '/discovered', icon: PlusCircle },
  { title: 'Contract', what: 'Endpoint, inputs, outputs, SLA and owner — what another team needs to call it.', where: 'Agent → Integrate', to: '/agents', icon: FileText },
  { title: 'Reviews', what: 'Architecture, Security and Data Protection each decide, with evidence and an expiry date.', where: 'Integration Approval · agent Governance tab', to: '/approvals', icon: ShieldCheck },
  { title: 'Stage', what: 'Ideation → Development → Testing → Production. Stage rules list what is still missing.', where: 'Agent → Governance', to: '/governance', icon: ClipboardList },
  { title: 'Certified for reuse', what: 'Automatic once it is in Production, every required review is approved and no high or critical risk is open.', where: 'Agent → Integrate', to: '/agents', icon: BadgeCheck },
  { title: 'Consume', what: 'Teams try it with their own input, then request access. The owner approves.', where: 'Agent → Integrate · Integration Approval', to: '/approvals', icon: KeyRound },
  { title: 'Monitor', what: 'Usage, cost, risk and last-seen activity are kept current by the daily jobs (the scheduler is on unless the installation turned it off).', where: 'Pipelines', to: '/pipelines', icon: LineChart },
  { title: 'Report', what: 'Leaders see value, cost and what is holding value back, per business unit.', where: 'Executive (with the business impact by unit)', to: '/', icon: BarChart3 },
]

// How an application gets from Phoenix into the registry, step by step.
const DISCOVERY: { title: string; when: string; steps: string[]; calls: string }[] = [
  {
    title: 'Scan Phoenix', when: 'Scan now, or once a day when the scheduler is on',
    steps: [
      'The registry asks Phoenix for its list of projects, 100 at a time, until it has them all.',
      'For each project it asks for the traced steps of the last 7 days, newest first, up to 300.',
      'From those it keeps names and counts only: models, tools, MCP servers, agent names, retrievers and the time of the last step. Prompt and answer text is never kept.',
      'A project with nothing in 7 days gets one more request, for its newest step ever, so its last-seen date is real.',
      'Six projects are read at a time. The result is saved in the registry’s own database.',
    ],
    calls: 'One-way and read-only: the registry asks, Phoenix answers. Nothing is written to Phoenix. About 1 to 4 requests per project.',
  },
  {
    title: 'Compare with the registry', when: 'Each time the Discovered Agents page opens',
    steps: [
      'The saved project list is compared with the “Phoenix project” field of every registered agent.',
      'A project that an agent is linked to goes to Registered. One that was dismissed goes to Dismissed. The rest are New.',
    ],
    calls: 'No request to Phoenix. The page shows what the last scan saved, so it opens fast and works without the VPN.',
  },
  {
    title: 'Label and tidy', when: 'On the Discovered Agents page',
    steps: [
      'Active: steps in the last 7 days. Quiet: seen before, nothing in 7 days. Stale: nothing for 30 days. No calls: Phoenix lists it but it has no traces.',
      'Dismiss hides a project that is not an application and asks for a reason. It stays hidden across scans until someone brings it back.',
      'If the Phoenix address is changed in Settings, the list is cleared (dismissals are kept) and the page asks for a new scan.',
    ],
    calls: 'No request to Phoenix.',
  },
  {
    title: 'Register with the form filled', when: 'Click Register on a project',
    steps: [
      'The form opens with what the traces say: name, model, tools and MCP servers, knowledge bases, agents it calls, and the Phoenix link.',
      'If an app address pattern is saved in Settings, the registry builds the address from the project name and checks that an app answers there.',
      'It reads that app’s OpenAPI document first (this also wakes an app that was idle), then its agent card and health check.',
      'Description, capabilities, inputs and outputs are filled from those. Only empty fields are filled, and each shows where its value came from.',
      'Owner, department, business outcome and value are entered by a person. Nothing is saved until Register is pressed.',
    ],
    calls: 'Up to four read-only requests to the app itself. The address is a guess from the project name, and is labelled as one.',
  },
  {
    title: 'Read usage, complete the record, work out cost', when: 'Straight after registering',
    steps: [
      'The new agent is linked to its project, so the registry reads that project’s model calls from Phoenix (30 days the first time).',
      'It then fills in what the record is still missing from what it can see: the model really in use, tools and knowledge sources seen in traces, and the contract from the app’s own API description.',
      'It stores daily tokens per model, works out cost from the price list, then runs the risk and governance checks for that agent.',
      'The Discovered Agents page shows when this is done, with a link to the agent.',
    ],
    calls: 'Read-only requests to Phoenix for that one project and to the app itself. Afterwards the daily jobs keep it current (the scheduler is on unless the installation turned it off).',
  },
]

// How a record is kept complete and then explained, without anyone typing what the registry can see for itself.
const INSIGHT_STEPS: { title: string; text: string }[] = [
  { title: 'The registry reads', text: 'Once a day, and the first time an agent’s page is opened, it reads the agent’s real usage, its traces and the app’s own API description. Read-only; prompt and answer text is not read.' },
  { title: 'It fills in the record', text: 'Model, tools, knowledge sources, API address, description, capabilities, inputs and outputs. Facts come from evidence; AI drafts a description only when nothing else can. Text a person wrote is never overwritten.' },
  { title: 'It recalculates', text: 'Cost, risks and governance checks are worked out again on the corrected record, so every tab shows figures for the record as it now is.' },
  { title: 'AI agents explain', text: 'At the bottom of each tab one card says what was filled in, what the analysis found and what only a person can provide. Code drops any point that cites no real record and flags any figure the tools did not return.' },
  { title: 'A person stays in charge', text: 'Every automatic change is logged and has an Undo; an undone or edited field is left alone from then on. Owner, value, budget, reviews and stage are only ever set by people.' },
]

const PERSONAS: { who: string; why: string; pages: { label: string; to: string }[] }[] = [
  { who: 'Executives', why: 'Portfolio health, value against cost, risk', pages: [{ label: 'Executive', to: '/' }] },
  { who: 'Business unit owners', why: 'My unit’s agents, outcomes and blockers', pages: [{ label: 'Executive (business impact by unit)', to: '/' }] },
  { who: 'Builders and product teams', why: 'Find, register, contract and call agents', pages: [{ label: 'Agent Registry', to: '/agents' }] },
  { who: 'Reviewers (Architecture · Security · Data Protection)', why: 'Decide reviews and access requests', pages: [{ label: 'Integration Approval', to: '/approvals' }, { label: 'Governance', to: '/governance' }] },
  { who: 'IT and architecture', why: 'Shared systems, dependencies, blast radius', pages: [{ label: 'Platform', to: '/platform' }, { label: 'All Agents Graph', to: '/dependencies' }] },
  { who: 'Admins', why: 'Tracing endpoint, users, rules, connectors, background jobs', pages: [{ label: 'Settings', to: '/settings' }, { label: 'Pipelines', to: '/pipelines' }] },
  { who: 'Finance reviewers', why: 'Attest or adjust the value owners declare, chargeback', pages: [{ label: 'Executive (business impact by unit)', to: '/' }] },
  { who: 'Compliance and auditors', why: 'Control coverage, evidence packs, the decision log, the audit trail', pages: [{ label: 'Compliance', to: '/compliance' }, { label: 'Audit Trail', to: '/audit' }] },
]

type Row = { item: string; detail: string; status: Status }
const COLUMNS: { title: string; sub: string; rows: Row[] }[] = [
  {
    title: 'Screens', sub: 'What you see in the browser',
    rows: [
      { item: 'Executive overview', detail: 'Totals, value against cost, risk by category, pipeline, value by unit', status: 'working' },
      { item: 'Executive: business impact by unit', detail: 'Per unit: value, cost to run, return, value waiting to go live, missing numbers', status: 'working' },
      { item: 'Agent Registry', detail: 'Search by what agents do, reuse status on every card, registration with a duplicate check', status: 'working' },
      { item: 'Agent page', detail: 'Overview, Diagram, Governance, Tokenomics, Business Value, Risk, Integrate', status: 'working' },
      { item: 'Discovered Agents', detail: 'Phoenix projects that are not registered yet: register one (the form fills from its traces and from the app itself) or dismiss it. Shows which registered agents have gone quiet', status: 'working' },
      { item: 'Ask the Registry', detail: 'A question in plain words, answered from the registry with links to the agents concerned', status: 'working' },
      { item: 'Integration Approval', detail: 'Access requests, reviews and classifications awaiting a decision (ranked by findings, risk tier and wait, with who can decide and who is away) and governance findings in one inbox, and a Decided history', status: 'working' },
      { item: 'Compliance', detail: 'EU AI Act, ISO/IEC 42001, NIST AI RMF and India DPDP Act controls mapped to the records the registry holds, with the gaps named per agent, evidence exports, the decision log check, the data and retention report and a GRC export', status: 'working' },
      { item: 'Audit Trail', detail: 'Every event, filterable, with CSV export', status: 'working' },
      { item: 'Platform and Dependencies', detail: 'Shared systems, concentration risk, call network and the dependency graph', status: 'working' },
      { item: 'Try it (Agent → Integrate)', detail: 'Calls an agent from the server; finds the real API paths from its openapi.json', status: 'working' },
      { item: 'Governance findings', detail: 'What the registry noticed on a registered agent: too long in a stage, no reviews, or in Production with no usage', status: 'working' },
    ],
  },
  {
    title: 'Server', sub: 'FastAPI + async SQLAlchemy',
    rows: [
      { item: 'Registry and contract APIs', detail: 'Agents, contracts, access requests, users', status: 'working' },
      { item: 'Governance', detail: 'Three reviews with evidence and expiry, rules per risk tier (which reviews, how long an approval lasts, warn or block), required fields per stage, a change after approval reopens the affected reviews, waivers with two signers', status: 'working' },
      { item: 'Classification', detail: 'Questions on purpose, people affected, data and decisions give a suggested EU AI Act category and risk level with reasons. A decider confirms it. The approved tool list raises the risk level of agents that use high-risk tools', status: 'working' },
      { item: 'Lifecycle', detail: 'Owner and backup owner, away periods with a deputy, versions with a changelog, retirement in checked steps, incidents with stop requests', status: 'working' },
      { item: 'Decision log', detail: 'Every decision is sealed in a hash chain right after it is saved, so a changed or removed decision is found', status: 'working' },
      { item: 'Value and cost', detail: 'Value declared with a method and attested or adjusted by finance, measured outcomes and cost per outcome, the same tokens priced at other models, idle and duplicate spend, the Production scenario, a scorecard PDF', status: 'working' },
      { item: 'Reuse certification', detail: 'Worked out from stage, reviews and risk — never stored, so it cannot go stale', status: 'working' },
      { item: 'Risk engine', detail: 'Six categories; findings with a lifecycle (open, acknowledged, mitigating, accepted, resolved)', status: 'working' },
      { item: 'Background jobs', detail: 'Phoenix discovery, connector scan, usage, who calls each agent, record auto-fill, Azure cost, cost roll-up, spend review, risk scan, governance checks, the AI insights refresh and daily notifications, with a run log', status: 'working' },
      { item: 'Records fill themselves', detail: 'The registry fills in or corrects eight fields from real usage, traces and the app’s own API description: model, tools, knowledge bases, API address, description, capabilities, inputs, outputs. Each change is logged with the old value and can be undone. It never sets an owner, value, budget, review or stage', status: 'working' },
      { item: 'Register from an address', detail: 'Reads the app’s agent card, OpenAPI document and health check to fill the form; each field shows its source', status: 'working' },
      { item: 'Daily scheduler', detail: 'Runs the daily jobs by itself, including the Phoenix scan and the daily notifications. On by default (SCHEDULER_ENABLED=false turns it off)', status: 'working' },
      { item: 'Insight agents (LangGraph)', detail: 'AI agents that read the registry’s own figures through read-only tools and explain them. One card at the bottom of every agent tab: agent brief, how it works and record against reality, review pack, cost root cause, value against cost, risks explained, similar agents by meaning. Also a registration coach, an evidence reader and Ask the Registry. Every point rests on a named record; the insight agents themselves change nothing. Not yet checked against human-labelled test sets', status: 'working' },
      { item: 'Insights write themselves', detail: 'A summary is written the first time a tab is opened, rewritten once a day for agents with real traces, and rewritten when the record changes. “Check again” does it on request', status: 'working' },
      { item: 'Trace content audit', detail: 'Reads a sample of an agent’s real questions and answers to judge quality, personal data and failures. Off for every agent until its owner switches it on; the text is not stored', status: 'setup' },
      { item: 'AI assistance', detail: 'Drafts review notes and context summaries (Azure OpenAI)', status: 'working' },
      { item: 'Role-based access', detail: 'Eight roles, enforced on every action. A Finance Reviewer attests value, an Auditor has read-only access until an end date with every request logged. Each review gate is decided by its own role (Architect Steward, Security Reviewer, Data Protection Officer) or a Registry Admin, and the signed-in person is recorded as the reviewer', status: 'working' },
      { item: 'Audit trail', detail: 'Every change, decision and automatic action, filterable by person, action, record and date, with CSV export. Audit rows cannot be changed or deleted, even in the database', status: 'working' },
      { item: 'Notifications', detail: 'A daily message to each person about what waits for them, and an immediate notice to admins when a scheduled job fails. Always in the in-app inbox (the bell); e-mail and a Teams channel once configured', status: 'working' },
      { item: 'Demo agents', detail: 'One complete example agent, labelled Demo, is always shown so that every page has a fully filled-in agent to look at. The other example agents are hidden. DEMO_AGENTS_ENABLED=false in the backend settings leaves all of them out', status: 'working' },
    ],
  },
  {
    title: 'Data and connections', sub: 'Where the numbers come from',
    rows: [
      { item: 'Registry database', detail: 'Agents, reviews, risks, usage, runs. SQLite locally; the migrations also build the full schema on PostgreSQL (checked on PostgreSQL 18)', status: 'working' },
      { item: 'E-mail and Teams', detail: 'Delivery of notifications outside the app. Needs SMTP_HOST and SMTP_FROM, or TEAMS_WEBHOOK_URL', status: 'setup' },
      { item: 'Phoenix traces', detail: 'Finds projects, token usage, trajectories and risk signals, read-only; reachable over the VPN. Needs the address and a key in Settings', status: 'working' },
      { item: 'Model prices', detail: 'Per-model token prices and name aliases for cost', status: 'working' },
      { item: 'Declared value', detail: 'Monthly value with its method and basis, entered by each owner and attested or adjusted by a finance reviewer', status: 'working' },
      { item: 'Usage without tracing', detail: 'Daily calls and tokens typed in or imported for agents with no tracing link', status: 'working' },
      { item: 'Connectors', detail: 'Langfuse (projects and usage), GitHub (repositories that build agents) and Azure (model deployments), read-only, set up in Settings', status: 'setup' },
      { item: 'Azure hosting cost', detail: 'Metered cost per agent, set up and tested in Settings → Cost settings. Until then the owner’s figure or a stage estimate is used', status: 'setup' },
      { item: 'Agent gateway', detail: 'Lets Try it call agents registered with a relative path', status: 'setup' },
    ],
  },
]

const NEXT = [
  'Discovery in AWS and Google Cloud accounts and SaaS agent platforms',
  'Reading incident status from PagerDuty and ServiceNow directly',
  'Single sign-on through the company directory',
  'Prototype parity: live ticker, hours reclaimed and units adopting on Executive',
]

// What the product does not do yet, stated plainly for anyone deploying it.
const KNOWN_LIMITS = [
  'Sign-in uses local accounts. Single sign-on through a company directory is not built.',
  'Rate limits and the Try it limiter are kept in the memory of one server process, so they multiply when the backend runs as several replicas.',
  'The registry records who may use an agent, but issues no key to call the agent and cannot stop a call: an API gateway does that.',
  'Phoenix is read over the VPN. When it does not answer, trace-based numbers stay at their last stored values and the pages say so.',
  'The insight agents have not been checked against human-labelled test sets.',
  'One organisation per installation. Separate tenants are not built.',
  'Compliance packs show which records the registry holds for each control. They are not a statement that the organisation complies, and the default regulatory dates are to be checked against the official texts.',
  'PagerDuty and ServiceNow are not read: an incident is linked by its address or posted to the registry by their automation.',
]

function Pill({ status }: { status: Status }) {
  const s = STATUS[status]
  return <span className={`inline-flex h-fit shrink-0 items-center rounded-full px-2 py-0.5 text-[12px] font-bold ring-1 ${s.className}`}>{s.label}</span>
}

function SectionTitle({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="mb-4 flex items-start gap-2.5">
      <span className="mt-1 h-4 w-1 shrink-0 rounded-full bg-gradient-to-b from-zen-400 to-zen-700" aria-hidden />
      <div>
        <h2 className="text-[16px] font-extrabold text-slate-900">{title}</h2>
        <p className="text-[13px] text-slate-600">{sub}</p>
      </div>
    </div>
  )
}

// How it works: what the registry does from registration to reuse, who uses
// which page, and — honestly — what is working in this build and what is not.
export default function HowItWorksPage() {
  return (
    <div className="space-y-5 animate-fade-in max-w-6xl">
      <div>
        <h1 className="text-2xl font-bold gradient-text">How it works</h1>
        <p className="text-slate-600 mt-0.5">What the registry does for an AI agent, from registering it to reusing it — and what is working in this build.</p>
      </div>

      <section className="card p-5" data-testid="journey">
        <SectionTitle title="An agent’s journey" sub="Every agent follows these steps. Each one links to where it happens." />
        <ol className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {JOURNEY.map((j, i) => (
            <li key={j.title}>
              <Link to={j.to} className="group flex h-full gap-3 rounded-xl border border-slate-200 bg-white p-3.5 transition-shadow hover:border-zen-200 hover:shadow-md">
                <div className="flex flex-col items-center gap-1">
                  <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-zen text-white shadow-sm"><j.icon size={17} /></span>
                  <span className="text-[12px] font-extrabold text-zen-600">{i + 1}</span>
                </div>
                <div className="min-w-0">
                  <div className="text-[14.5px] font-bold text-slate-900">{j.title}</div>
                  <p className="mt-0.5 text-[12.5px] leading-snug text-slate-700">{j.what}</p>
                  <span className="mt-1.5 inline-block text-[12.5px] font-semibold text-zen-700 group-hover:underline">{j.where} →</span>
                </div>
              </Link>
            </li>
          ))}
        </ol>
      </section>

      <section className="card p-5" data-testid="discovery-steps">
        <SectionTitle title="How discovery works" sub="How an application sending traces to Phoenix ends up registered, and which requests are made at each step." />
        <ol className="space-y-3">
          {DISCOVERY.map((d, i) => (
            <li key={d.title} className="flex gap-3 rounded-xl border border-slate-200 bg-white p-4">
              <div className="flex flex-col items-center gap-1">
                <span className="grid h-9 w-9 place-items-center rounded-xl bg-violet-50 text-violet-600"><Radar size={17} /></span>
                <span className="text-[12px] font-extrabold text-zen-600">{i + 1}</span>
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-[14.5px] font-bold text-slate-900">{d.title}</span>
                  <span className="text-[12px] text-slate-600">{d.when}</span>
                </div>
                <ul className="mt-1.5 space-y-1">
                  {d.steps.map(step => (
                    <li key={step} className="flex items-start gap-2 text-[13px] leading-snug text-slate-700">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-zen-400" aria-hidden />{step}
                    </li>
                  ))}
                </ul>
                <p className="mt-2 rounded-lg bg-slate-50 px-2.5 py-1.5 text-[12.5px] text-slate-700 ring-1 ring-slate-100">
                  <span className="font-semibold text-slate-800">Requests: </span>{d.calls}
                </p>
              </div>
            </li>
          ))}
        </ol>
        <p className="mt-3 text-[12.5px] text-slate-600">
          Discovery only finds applications that send traces to the Phoenix set in Settings. A Phoenix project is not always one application: some are experiments, and one project can hold several agents.
          See it on the <Link to="/discovered" className="font-semibold text-zen-700 hover:underline">Discovered Agents</Link> page and the job on <Link to="/pipelines" className="font-semibold text-zen-700 hover:underline">Pipelines</Link>.
        </p>
      </section>

      <section className="card p-5" data-testid="insight-steps">
        <SectionTitle title="How records fill themselves and how the AI insights work" sub="The registry fills in what it can see. Code calculates the figures. AI agents explain them. People decide." />
        <ol className="grid grid-cols-1 md:grid-cols-5 gap-3">
          {INSIGHT_STEPS.map((s, i) => (
            <li key={s.title} className="rounded-xl border border-slate-200 bg-white p-3.5">
              <div className="text-[12px] font-extrabold text-zen-600">STEP {i + 1}</div>
              <div className="text-[14px] font-bold text-slate-900">{s.title}</div>
              <p className="mt-0.5 text-[12.5px] leading-snug text-slate-700">{s.text}</p>
            </li>
          ))}
        </ol>
        <p className="mt-3 text-[12.5px] text-slate-600">
          The numbers on every tab are calculated by code and are the same whether or not a summary is written. Reviewers are told when a check passes on a field the registry filled in, and a change to the model or tools after approval still asks for recertification.
          The summaries have been tried on real agents but are not yet measured against human reviewers, so treat them as a starting point. See one at the bottom of any agent tab, or <Link to="/ask" className="font-semibold text-zen-700 hover:underline">ask a question</Link>.
        </p>
      </section>

      <section className="card p-5" data-testid="personas">
        <SectionTitle title="Who uses what" sub="Start from the page for your role." />
        <ul className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {PERSONAS.map(p => (
            <li key={p.who} className="flex gap-3 rounded-xl bg-slate-50/80 p-3.5 ring-1 ring-slate-100">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-zen-50 text-zen-600"><Users size={17} /></span>
              <div className="min-w-0">
                <div className="text-[14px] font-bold text-slate-900">{p.who}</div>
                <p className="text-[12.5px] text-slate-700">{p.why}</p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {p.pages.map(pg => (
                    <Link key={pg.label} to={pg.to} className="rounded-full bg-white px-2.5 py-0.5 text-[12px] font-semibold text-zen-700 ring-1 ring-zen-200 hover:bg-zen-50">{pg.label}</Link>
                  ))}
                </div>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section data-testid="build-status">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <SectionTitle title="What is in this build" sub="Each part and whether it is working today." />
          <div className="flex flex-wrap gap-1.5">{(Object.keys(STATUS) as Status[]).map(s => <Pill key={s} status={s} />)}</div>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {COLUMNS.map(c => (
            <div key={c.title} className="card p-5">
              <div className="mb-3">
                <h3 className="text-[15px] font-extrabold text-slate-900">{c.title}</h3>
                <p className="text-[12.5px] text-slate-600">{c.sub}</p>
              </div>
              <ul className="space-y-2.5">
                {c.rows.map(r => (
                  <li key={r.item} className="flex gap-2.5">
                    <Pill status={r.status} />
                    <div>
                      <div className="text-[13.5px] font-bold text-slate-900">{r.item}</div>
                      <div className="text-[12.5px] leading-snug text-slate-600">{r.detail}</div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      <section className="card p-5" data-testid="next">
        <SectionTitle title="Next" sub="Not in this build yet." />
        <ul className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {NEXT.map(n => (
            <li key={n} className="flex items-start gap-2 text-[13.5px] text-slate-700">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-400" aria-hidden />{n}
            </li>
          ))}
        </ul>
      </section>

      <section className="card p-5" data-testid="known-limits">
        <SectionTitle title="Known limits" sub="What this build does not do." />
        <ul className="space-y-1.5">
          {KNOWN_LIMITS.map(n => (
            <li key={n} className="flex items-start gap-2 text-[13.5px] text-slate-700">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" aria-hidden />{n}
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
