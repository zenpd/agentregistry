import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity, ArrowRight, CalendarClock, Radar, Sparkles, CheckCircle2, ChevronRight, Cloud, Coins, Database, Loader2, Play, ShieldAlert,
  ShieldCheck, Wand2, Workflow, Bell, Plug, Users,
} from 'lucide-react'
import { getAgents } from '../services/api'
import { getJobRuns, getJobs, runJob, type JobListItem, type JobName, type JobRun, type JobsResponse } from '../services/ops/jobs'
import ErrorNote from '../components/ErrorNote'
import InfoTip from '../components/InfoTip'
import { GLOSSARY, type GlossaryKey } from '../lib/glossary'
import { TimeModeToggle, clockTime, useTimeMode } from '../lib/timeMode'
import { errorMessage } from './agent/shared'

// What each daily job does, in the reader's terms. Kept beside the page, not
// in the API: it is explanation, and the API stays the source of the facts.
const META: Record<JobName, {
  icon: typeof Activity; tone: string; does: string; reads: string[]; writes: string[]
  feeds: { label: string; to?: string }[]; needs?: string; alsoFrom?: string
}> = {
  phoenix_discovery: {
    icon: Radar, tone: 'bg-violet-50 text-violet-600',
    does: 'Reads every Phoenix project (read-only) and notes its models, tools and last activity. Projects that no agent is linked to appear on the Discovered Agents page, ready to register. Nothing is registered automatically, and prompt and answer text is never read.',
    reads: ['Phoenix projects and a recent sample of their traces'], writes: ['Discovered Agents page (new projects, activity of registered agents)'],
    feeds: [{ label: 'Discovered Agents page', to: '/discovered' }],
    needs: 'The Phoenix address and a read-only key in Settings → Common tracing endpoint. The server must be able to reach Phoenix (VPN).',
    alsoFrom: 'Discovered Agents → Scan now',
  },
  connector_sync: {
    icon: Plug, tone: 'bg-violet-50 text-violet-600',
    does: 'Scans every connector in Settings, read-only: Langfuse projects, GitHub repositories that build agents, and Azure model deployments and Foundry agents. What it finds waits on Discovered Agents → Other sources. It also reads daily token usage for agents whose traces are in Langfuse.',
    reads: ['Langfuse, GitHub and Azure, as configured'], writes: ['Findings on the Discovered Agents page', 'Daily usage of Langfuse-linked agents'],
    feeds: [{ label: 'Discovered Agents → Other sources', to: '/discovered' }, { label: 'Tokenomics tab (Langfuse agents)' }],
    needs: 'At least one connector in Settings → Connectors. Each one is tested and scanned from there too.',
    alsoFrom: 'Settings → Connectors → Scan now',
  },
  usage_ingestion: {
    icon: Activity, tone: 'bg-sky-50 text-sky-600',
    does: 'Reads the LLM calls in each agent’s Phoenix project and stores daily token usage per model. Prompt and answer text are never stored.',
    reads: ['Phoenix traces (read-only)'], writes: ['Daily usage per agent and model'],
    feeds: [{ label: 'Tokenomics tab' }, { label: 'Business Value tab' }, { label: 'Executive (cost to run)', to: '/' }],
    needs: 'A Phoenix project linked on the agent (Diagram tab). The server must be able to reach Phoenix (VPN).',
    alsoFrom: 'An agent’s Tokenomics tab → Refresh from Phoenix',
  },
  consumer_observation: {
    icon: Users, tone: 'bg-emerald-50 text-emerald-600',
    does: 'Reads the latest trace sample of each agent linked to Phoenix and records who calls it: teams that name themselves with the span attribute consumer.team, and other registered agents whose traces call it. The first call seen from each team is kept, so the time from an access approval to the first call can be measured. Prompt and answer text is never read.',
    reads: ['Phoenix traces (read-only, the latest sample per agent)'], writes: ['Observed consumers per agent'],
    feeds: [{ label: 'Integrate tab → Consumers' }, { label: 'Programme health' }, { label: 'Tokenomics tab → Chargeback' }],
    needs: 'A Phoenix project linked on the agent, and callers that set consumer.team on their spans. The server must be able to reach Phoenix (VPN).',
    alsoFrom: 'An agent’s Integrate tab → Read callers now',
  },
  record_autofill: {
    icon: Wand2, tone: 'bg-teal-50 text-teal-700',
    does: 'Keeps each agent’s record filled in from what the registry can see for itself, so nobody has to type it: the model really in use, the tools and knowledge sources seen in traces, and the description, capabilities, inputs and outputs from the app’s own API description. AI drafts a description only when nothing else can. It never overwrites what a person wrote, and never sets an owner, value, budget, review or stage.',
    reads: ['Daily usage', 'Phoenix traces (read-only)', 'The app’s own API description'], writes: ['Empty or outdated fields on the agent record', 'Audit log (every change, with the old value)'],
    feeds: [{ label: 'Overview, Diagram and Integrate tabs' }, { label: '“Filled in for you” on each agent tab' }],
    needs: 'A Phoenix project linked on the agent, or a web address for it. Each change can be undone on the agent’s page; an undone field is left to people from then on.',
    alsoFrom: 'Any agent tab → AI insights → Check again',
  },
  infra_costs: {
    icon: Cloud, tone: 'bg-indigo-50 text-indigo-600',
    does: 'Pulls daily Azure hosting cost and assigns it to agents, by an agent-id tag or a share of a linked resource. Read-only: nothing in Azure changes.',
    reads: ['Azure Cost Management'], writes: ['Metered hosting cost per agent'],
    feeds: [{ label: 'Tokenomics tab (metered hosting cost)' }],
    needs: 'AZURE_COST_SCOPE and a service principal with Cost Management Reader. Until then, hosting cost is the owner’s figure or a stage estimate.',
  },
  cost_rollup: {
    icon: Coins, tone: 'bg-emerald-50 text-emerald-600',
    does: 'Turns stored usage into daily cost per agent, checks budgets and opens or closes cost anomalies. Agents with only demo data are skipped.',
    reads: ['Daily usage', 'Model prices'], writes: ['Daily cost per agent', 'Cost anomalies'],
    feeds: [{ label: 'Tokenomics tab (budget, anomalies)' }, { label: 'Risk tab (financial findings)' }],
    alsoFrom: 'An agent’s Tokenomics tab → Refresh from Phoenix (right after usage)',
  },
  risk_scan: {
    icon: ShieldAlert, tone: 'bg-rose-50 text-rose-600',
    does: 'Runs the risk rules on every agent — governance, cost and trace signals — and records findings as new, updated, reopened or resolved. It never changes an agent.',
    reads: ['Reviews and stage', 'Costs and anomalies', 'Phoenix trace signals'], writes: ['Risk register'],
    feeds: [{ label: 'Risk tab' }, { label: 'Reuse certification' }, { label: 'Executive risk charts', to: '/' }],
    alsoFrom: 'An agent’s Risk tab → Scan now',
  },
  insight_refresh: {
    icon: Sparkles, tone: 'bg-zen-50 text-zen-600',
    does: 'For each agent that has real traces, AI agents re-read the day’s figures and rewrite the summary at the bottom of each of its tabs: what was found, what the registry filled in by itself, and what only a person can still provide. They only read; the insight agents change nothing. Insights that read documents or trace text are never run by this job.',
    reads: ['Everything the earlier jobs produced', 'The AI model (Azure OpenAI)'], writes: ['AI insights at the bottom of each agent tab'],
    feeds: [{ label: 'AI insights on every agent tab' }],
    needs: 'The AI model reachable from the server. Agents without traces get their summary the first time someone opens them.',
    alsoFrom: 'Any agent tab → AI insights → Check again',
  },
  notifications: {
    icon: Bell, tone: 'bg-orange-50 text-orange-600',
    does: 'Sends each person one message a day with what waits for them: reviews they decide, approvals about to expire, access requests, budget alerts, new unregistered projects and overdue risks. Demo agents are left out. A failed scheduled job is sent to the admins at once.',
    reads: ['Reviews, access requests, budgets, discovered projects, risks', 'People and their roles'], writes: ['Each person’s notification inbox (the bell)', 'E-mail and the Teams channel, when configured'],
    feeds: [{ label: 'The bell in the top bar' }, { label: 'Settings → Notifications', to: '/settings' }],
    needs: 'Nothing for the in-app inbox. E-mail needs SMTP_HOST and SMTP_FROM, Teams needs TEAMS_WEBHOOK_URL.',
  },
  spend_review: {
    icon: ShieldCheck, tone: 'bg-amber-50 text-amber-600',
    does: 'Lists Production agents that cost money with no calls, and pairs of agents that cost money and look like they do the same job. It never changes an agent.',
    reads: ['Monthly cost and value per agent', 'Usage per day'], writes: ['Spend findings'],
    feeds: [{ label: 'Executive (idle and duplicate spend)', to: '/' }],
  },
  governance_checks: {
    icon: ShieldCheck, tone: 'bg-amber-50 text-amber-600',
    does: 'Finds approvals that are expiring or have expired, and agents that need recertification. When the model, tools or endpoint changed after an approval, it reopens the reviews that change affects. It never changes a stage.',
    reads: ['Reviews and expiry dates', 'Stage and telemetry', 'The copy of the record kept at approval'], writes: ['Report in the run log', 'Reopened reviews'],
    feeds: [{ label: 'Governance tab (recertification)' }, { label: 'Integration Approval', to: '/approvals' }],
  },
}

type Health = 'ok' | 'warn' | 'failed' | 'never' | 'running' | 'muted'
const STATUS_TEXT: Record<string, [string, Health]> = {
  ok: ['OK', 'ok'], partial: ['Partial', 'warn'], skipped: ['Skipped', 'muted'], not_configured: ['Not configured', 'warn'],
  running: ['Running', 'running'], error: ['Failed', 'failed'], unreachable: ['Unreachable', 'failed'],
  stale: ['Did not finish', 'failed'], cancelled: ['Cancelled', 'failed'], unavailable: ['Unavailable', 'failed'],
}
const HEALTH_PILL: Record<Health, string> = {
  ok: 'bg-emerald-50 text-emerald-700 ring-emerald-200', warn: 'bg-amber-50 text-amber-800 ring-amber-200',
  failed: 'bg-rose-50 text-rose-700 ring-rose-200', never: 'bg-slate-100 text-slate-700 ring-slate-200',
  running: 'bg-zen-50 text-zen-700 ring-zen-200', muted: 'bg-slate-100 text-slate-700 ring-slate-200',
}
const health = (run: JobRun | null): [string, Health] => run ? (STATUS_TEXT[run.status] || [run.status, 'failed']) : ['Never run', 'never']
// The daily pipeline is judged by its run for all agents. A run for one agent (started from that
// agent's page, and often skipped because that agent has no traces) says nothing about the pipeline.
const dailyRun = (j: JobListItem): JobRun | null => j.lastAllAgentsRun ?? j.lastRun

function StatusPill({ run }: { run: JobRun | null }) {
  const [text, h] = health(run)
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12.5px] font-bold ring-1 ${HEALTH_PILL[h]}`} title={run?.status}>{text}</span>
}

function ago(iso: string | null): string {
  if (!iso) return '—'
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs} h ago`
  const days = Math.round(hrs / 24)
  return `${days} day${days === 1 ? '' : 's'} ago`
}

function fmtDuration(ms: number | null): string {
  if (ms == null) return '—'
  return ms < 1000 ? `${ms} ms` : ms < 60_000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms / 60_000)} min`
}

const num = (v: unknown) => (typeof v === 'number' ? v : undefined)
const agentsCount = (s: Record<string, unknown>) => (typeof s.agents === 'number' ? s.agents : undefined)

// The few numbers that say what a run achieved, per job.
function keyFacts(job: JobName, s: Record<string, unknown>): string[] {
  const agents = Array.isArray(s.agents) ? s.agents.length : undefined
  const totals = (s.totals && typeof s.totals === 'object' ? s.totals : {}) as Record<string, unknown>
  const facts: (string | false | undefined)[] =
    job === 'record_autofill' ? [agentsCount(s) != null && `${agentsCount(s)} agents checked`, num(s.fields) != null && `${num(s.fields)} fields filled in`, num(s.failed) ? `${num(s.failed)} could not be read` : false]
    : job === 'insight_refresh' ? [num(s.insights) != null && `${num(s.insights)} insights written`, agentsCount(s) != null && `${agentsCount(s)} agents`, num(s.unavailable) ? `${num(s.unavailable)} not written` : false]
    : job === 'phoenix_discovery' ? [num(s.projects) != null && `${num(s.projects)} projects`, num(s.new) != null && `${num(s.new)} new`, num(s.stale) != null && `${num(s.stale)} stale`]
    : job === 'usage_ingestion' ? [num(s.calls) != null && `${num(s.calls)!.toLocaleString()} LLM calls`, num(s.rows) != null && `${num(s.rows)} usage rows`, agents != null && `${agents} agent${agents === 1 ? '' : 's'}`]
      : job === 'cost_rollup' ? [num(s.agents_rolled_up) != null && `${num(s.agents_rolled_up)} rolled up`, num(s.agents_skipped) != null && `${num(s.agents_skipped)} skipped`, num(s.anomalies_opened) != null && `${num(s.anomalies_opened)} anomalies opened`]
        : job === 'risk_scan' ? [num(s.agentCount) != null && `${num(s.agentCount)} agent${num(s.agentCount) === 1 ? '' : 's'} scanned`, num(totals.inserted) != null && `${num(totals.inserted)} new findings`, num(totals.resolved) != null && `${num(totals.resolved)} resolved`]
          : Object.entries(s).filter(([, v]) => typeof v === 'number').slice(0, 3).map(([k, v]) => `${v} ${k.replace(/_/g, ' ')}`)
  return facts.filter((f): f is string => Boolean(f))
}

// Pipelines: the background jobs that keep the registry's numbers current —
// what each does, when it last ran, whether it worked, and a way to run it.
export default function PipelinesPage() {
  const [timeMode] = useTimeMode()
  const [data, setData] = useState<JobsResponse | null>(null)
  const [runs, setRuns] = useState<JobRun[]>([])
  const [names, setNames] = useState<Map<string, string>>(new Map())
  const [selected, setSelected] = useState<JobName>('usage_ingestion')
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [jobs, recent] = await Promise.all([getJobs(), getJobRuns({ limit: 200 })])
      setData(jobs.data)
      setRuns(recent.data.runs.filter(r => r.job !== 'refresh'))
      setError(null)
    } catch (e) {
      setError(errorMessage(e, 'Could not load the pipelines'))
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    getAgents(1, 100).then(r => setNames(new Map(r.data.data.map(a => [a.id, a.name])))).catch(() => setNames(new Map()))
  }, [])

  const jobs = data?.jobs || []
  const job = jobs.find(j => j.job === selected) || jobs[0]
  const counts = useMemo(() => ({
    healthy: jobs.filter(j => health(dailyRun(j))[1] === 'ok').length,
    failed: jobs.filter(j => health(dailyRun(j))[1] === 'failed').length,
    never: jobs.filter(j => !dailyRun(j)).length,
  }), [jobs])

  if (error && !data) return <div className="p-8 text-center text-rose-500">Error: {error}</div>
  if (!data || !job) return <div className="p-8 text-center text-slate-600">Loading…</div>
  const sched = data.scheduler

  return (
    <div className="space-y-5 animate-fade-in max-w-6xl">
      <div>
        <h1 className="text-2xl font-bold gradient-text">Pipelines</h1>
        <p className="text-slate-600 mt-0.5">The background jobs that keep the registry’s numbers current — what each one does, when it last ran and whether it worked.</p>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-[13px]" data-testid="scheduler-line">
        <CalendarClock size={16} className={sched.enabled ? 'text-emerald-600' : 'text-slate-500'} />
        {sched.enabled ? (
          <span className="text-slate-700"><span className="font-semibold text-emerald-700">Scheduler on</span> — jobs run daily in order{sched.nextRunAt ? `; next run ${timeMode === 'utc' ? `${new Date(sched.nextRunAt).toLocaleString('en-GB', { timeZone: 'UTC' })} UTC` : new Date(sched.nextRunAt).toLocaleString()}` : ''}.</span>
        ) : (
          <span className="text-slate-700"><span className="font-semibold text-slate-800">Scheduler off <InfoTip term="scheduler" /></span> — jobs run only when started here or from an agent page. Turn it on with <code className="font-mono text-[12px]">SCHEDULER_ENABLED=true</code>.</span>
        )}
        <span className="ml-auto"><TimeModeToggle /></span>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4" data-testid="pipeline-kpis">
        <Kpi label="Daily jobs" value={jobs.length} sub="run in the order shown below" />
        <Kpi label="Last run OK" value={`${counts.healthy}/${jobs.length}`} sub="finished without problems" accent="text-emerald-600" />
        <Kpi label="Needs attention" value={counts.failed} sub="last run failed" accent={counts.failed ? 'text-rose-600' : undefined} />
        <Kpi label="Never run" value={counts.never} sub="no run recorded yet" accent={counts.never ? 'text-amber-600' : undefined} />
      </div>

      <section className="card p-5" data-testid="pipeline-flow">
        <div className="mb-4 flex items-start gap-2.5">
          <span className="mt-1 h-4 w-1 shrink-0 rounded-full bg-gradient-to-b from-zen-400 to-zen-700" aria-hidden />
          <div>
            <h2 className="text-[16px] font-extrabold text-slate-900">Daily pipeline</h2>
            <p className="text-[13px] text-slate-600">Each job feeds the next: usage becomes cost, cost and traces become risk findings. Click a job to see what it does.</p>
          </div>
        </div>
        <ol className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {jobs.map((j, i) => {
            const m = META[j.job]
            const Icon = m?.icon || Workflow
            const active = j.job === job.job
            return (
              <li key={j.job} className="relative">
                <button type="button" onClick={() => setSelected(j.job)} aria-pressed={active} data-testid={`step-${j.job}`}
                  className={`flex h-full w-full flex-col gap-2 rounded-xl border bg-white p-3.5 text-left transition-shadow hover:shadow-md ${
                    active ? 'border-zen-300 ring-2 ring-zen-300 shadow-md' : 'border-slate-200'}`}>
                  <div className="flex items-center justify-between">
                    <span className={`grid h-9 w-9 place-items-center rounded-lg ${m?.tone || 'bg-slate-100 text-slate-700'}`}><Icon size={18} /></span>
                    <span className="text-[12px] font-bold text-slate-500">STEP {i + 1} · {clockTime(j.dailyAt, timeMode)}</span>
                  </div>
                  <div className="text-[14px] font-bold leading-tight text-slate-900">{j.label}</div>
                  <div className="mt-auto flex flex-wrap items-center gap-1.5">
                    <StatusPill run={dailyRun(j)} />
                    <span className="text-[12.5px] text-slate-600">{dailyRun(j) ? ago(dailyRun(j)!.startedAt) : ''}</span>
                  </div>
                </button>
                {i < jobs.length - 1 && (
                  <ChevronRight size={18} className="absolute -right-3 top-1/2 z-10 hidden -translate-y-1/2 rounded-full bg-white text-slate-400 md:block" aria-hidden />
                )}
              </li>
            )
          })}
        </ol>
      </section>

      <JobDetail key={job.job} job={job} runs={runs.filter(r => r.job === job.job).slice(0, 10)} names={names} onRan={load} />

      <OnDemand />
    </div>
  )
}

function Kpi({ label, value, sub, accent }: { label: string; value: string | number; sub: string; accent?: string }) {
  return (
    <div className="card p-4">
      <div className="text-xs text-slate-600 uppercase tracking-wide">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${accent || 'text-slate-900'}`}>{value}</div>
      <div className="text-xs text-slate-500 mt-1">{sub}</div>
    </div>
  )
}

function Chip({ children, tone = 'slate' }: { children: React.ReactNode; tone?: 'slate' | 'zen' }) {
  return <span className={`rounded-md px-2 py-0.5 text-[12px] font-medium ring-1 ${tone === 'zen' ? 'bg-zen-50 text-zen-700 ring-zen-200' : 'bg-slate-50 text-slate-700 ring-slate-200'}`}>{children}</span>
}

function JobDetail({ job, runs, names, onRan }: { job: JobListItem; runs: JobRun[]; names: Map<string, string>; onRan: () => Promise<void> }) {
  const [timeMode] = useTimeMode()
  const m = META[job.job]
  const last = dailyRun(job)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState<JobRun | null>(null)
  const [error, setError] = useState<string | null>(null)
  // An agent deleted since the run has no name left; say so rather than show a bare id.
  const scope = (r: JobRun) => (!r.agentId ? 'All agents' : names.get(r.agentId) || `${r.agentId} (removed)`)

  async function run() {
    setBusy(true)
    setError(null)
    setOutcome(null)
    try {
      setOutcome((await runJob(job.job)).data)
      setConfirming(false)
      await onRan()
    } catch (e) {
      setError(errorMessage(e, 'The job could not be started'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card overflow-hidden" data-testid="job-detail">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-100 bg-gradient-to-r from-zen-50 via-white to-white px-5 py-4">
        <span className={`grid h-10 w-10 place-items-center rounded-xl ${m?.tone || 'bg-slate-100 text-slate-700'}`}>{m ? <m.icon size={20} /> : <Workflow size={20} />}</span>
        <div className="flex-1 min-w-0">
          <h2 className="text-[17px] font-extrabold text-slate-900 flex items-center gap-1">{job.label} {job.job in GLOSSARY ? <InfoTip term={job.job as GlossaryKey} /> : null}</h2>
          <p className="text-[12.5px] text-slate-600">Daily {clockTime(job.dailyAt, timeMode)}{job.adminOnly ? ' · admins only' : ''}</p>
        </div>
        {!job.available ? (
          <span className="text-[12.5px] text-rose-700">Unavailable: {job.unavailableReason}</span>
        ) : !confirming ? (
          <button type="button" className="btn-primary btn-sm flex items-center gap-1.5" onClick={() => { setConfirming(true); setOutcome(null) }} disabled={busy} data-testid="run-now">
            <Play size={14} /> Run now
          </button>
        ) : (
          <div className="flex flex-wrap items-center gap-2" data-testid="run-confirm">
            <span className="text-[12.5px] text-slate-700">Runs for every agent{job.job === 'insight_refresh' ? ' with real traces and calls the AI model — can take several minutes' : job.job === 'record_autofill' ? ' it can read something about, and wakes each app to read its API description — can take a few minutes' : job.job === 'usage_ingestion' || job.job === 'risk_scan' || job.job === 'phoenix_discovery' ? ' and reads Phoenix — can take a few minutes' : ''}.</span>
            <button type="button" className="btn-primary btn-sm flex items-center gap-1.5" onClick={run} disabled={busy}>
              {busy ? <><Loader2 size={14} className="animate-spin" /> Running…</> : <>Start</>}
            </button>
            <button type="button" className="btn-ghost btn-sm" onClick={() => setConfirming(false)} disabled={busy}>Cancel</button>
          </div>
        )}
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 p-5">
        <div className="space-y-3">
          <div className="text-[12px] font-bold uppercase tracking-[.05em] text-slate-600">What it does</div>
          <p className="text-[14px] text-slate-700 leading-relaxed">{m?.does || job.label}</p>
          {m && (
            <div className="grid grid-cols-[auto_1fr] items-start gap-x-3 gap-y-2 text-[13px]">
              <span className="pt-0.5 font-semibold text-slate-600">Reads</span>
              <div className="flex flex-wrap gap-1.5">{m.reads.map(r => <Chip key={r}>{r}</Chip>)}</div>
              <span className="pt-0.5 font-semibold text-slate-600">Writes</span>
              <div className="flex flex-wrap gap-1.5">{m.writes.map(w => <Chip key={w}>{w}</Chip>)}</div>
              <span className="pt-0.5 font-semibold text-slate-600">Shows in</span>
              <div className="flex flex-wrap gap-1.5">
                {m.feeds.map(f => f.to
                  ? <Link key={f.label} to={f.to} className="rounded-md bg-zen-50 px-2 py-0.5 text-[12px] font-semibold text-zen-700 ring-1 ring-zen-200 hover:bg-zen-100">{f.label}</Link>
                  : <Chip key={f.label} tone="zen">{f.label}</Chip>)}
              </div>
            </div>
          )}
          {m?.needs && <p className="text-[12.5px] text-slate-600"><span className="font-semibold text-slate-700">Needs:</span> {m.needs}</p>}
          {m?.alsoFrom && <p className="text-[12.5px] text-slate-600"><span className="font-semibold text-slate-700">Also runs from:</span> {m.alsoFrom}</p>}
        </div>

        <div className="space-y-3">
          <div className="text-[12px] font-bold uppercase tracking-[.05em] text-slate-600">Last run</div>
          {!last ? (
            <p className="text-[13.5px] text-slate-700">No run recorded yet. Use <span className="font-semibold">Run now</span> to run it once.</p>
          ) : (
            <div className="rounded-xl bg-slate-50/80 p-4 ring-1 ring-slate-100 space-y-2" data-testid="last-run">
              <div className="flex flex-wrap items-center gap-2">
                <StatusPill run={last} />
                <span className="text-[13px] text-slate-700">{ago(last.startedAt)} · {last.trigger === 'scheduled' ? 'scheduled' : 'started by hand'} · {scope(last)} · {fmtDuration(last.durationMs)}</span>
              </div>
              {keyFacts(job.job, last.summary).length > 0 && (
                <div className="flex flex-wrap gap-1.5">{keyFacts(job.job, last.summary).map(f => <Chip key={f}>{f}</Chip>)}</div>
              )}
              {last.error && <ErrorNote message={last.error} />}
            </div>
          )}
          {outcome && (
            <div className="flex items-center gap-2 rounded-lg bg-emerald-50 px-3 py-2 text-[13px] text-emerald-800 ring-1 ring-emerald-200" role="status" data-testid="run-outcome">
              <CheckCircle2 size={15} /> Finished: {health(outcome)[0]} in {fmtDuration(outcome.durationMs)}.
            </div>
          )}
          {error && <ErrorNote message={error} onDismiss={() => setError(null)} />}
        </div>
      </div>

      <div className="border-t border-slate-100 px-5 py-4">
        <div className="mb-2 text-[12px] font-bold uppercase tracking-[.05em] text-slate-600">Recent runs</div>
        {runs.length === 0 ? (
          <p className="text-[13px] text-slate-600">No runs yet.</p>
        ) : (
          <table className="w-full text-[13px]" data-testid="recent-runs">
            <thead>
              <tr className="text-left text-[12px] font-bold uppercase tracking-wide text-slate-600">
                <th className="py-1.5 pr-3">When</th><th className="py-1.5 pr-3">Status</th><th className="py-1.5 pr-3">Scope</th>
                <th className="py-1.5 pr-3">Started by</th><th className="py-1.5 text-right">Duration</th>
              </tr>
            </thead>
            <tbody>
              {runs.map(r => (
                <tr key={r.runId || r.startedAt} className="border-t border-slate-100">
                  <td className="py-1.5 pr-3 text-slate-700" title={r.startedAt || ''}>{r.startedAt ? new Date(r.startedAt).toLocaleString() : '—'}</td>
                  <td className="py-1.5 pr-3"><StatusPill run={r} /></td>
                  <td className="py-1.5 pr-3 text-slate-700">{scope(r)}</td>
                  <td className="py-1.5 pr-3 text-slate-600">{r.trigger === 'scheduled' ? 'Scheduler' : 'By hand'}</td>
                  <td className="py-1.5 text-right font-mono text-slate-700">{fmtDuration(r.durationMs)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}

// Analyses that run when someone asks, not on a schedule.
const ON_DEMAND: { title: string; does: string; where: string; to: string; icon: typeof Activity }[] = [
  { title: 'Refresh one agent’s usage', does: 'Reads that agent’s latest calls from Phoenix, then rolls up its cost.', where: 'Agent → Tokenomics → Refresh from Phoenix', to: '/agents', icon: Activity },
  { title: 'Risk scan for one agent', does: 'Re-scores one agent’s risks straight away.', where: 'Agent → Risk → Scan now', to: '/agents', icon: ShieldAlert },
  { title: 'Rule-check proposal', does: 'Rule checks propose a decision for all three reviews. Nothing is saved until a reviewer accepts it with a reason.', where: 'Governance → Propose by rules', to: '/governance', icon: ShieldCheck },
  { title: 'Blast radius', does: 'What breaks, and whose value is at risk, if an agent or system goes down.', where: 'All Agents Graph → click an item', to: '/dependencies', icon: Workflow },
  { title: 'API operations', does: 'Reads a backend’s own openapi.json so Try it can call a real path.', where: 'Agent → Integrate → Load API operations', to: '/agents', icon: Database },
]

function OnDemand() {
  return (
    <section className="card p-5" data-testid="on-demand">
      <div className="mb-3 flex items-start gap-2.5">
        <span className="mt-1 h-4 w-1 shrink-0 rounded-full bg-gradient-to-b from-zen-400 to-zen-700" aria-hidden />
        <div>
          <h2 className="text-[16px] font-extrabold text-slate-900">On-demand analyses</h2>
          <p className="text-[13px] text-slate-600">These run only when someone asks, from the page shown.</p>
        </div>
      </div>
      <ul className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {ON_DEMAND.map(o => (
          <li key={o.title} className="flex gap-3 rounded-xl border border-slate-200 bg-white p-3.5">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-700"><o.icon size={16} /></span>
            <div className="min-w-0">
              <div className="text-[14px] font-bold text-slate-900">{o.title}</div>
              <p className="text-[12.5px] text-slate-700">{o.does}</p>
              <Link to={o.to} className="mt-1 inline-flex items-center gap-1 text-[12px] font-semibold text-zen-700 hover:underline">{o.where} <ArrowRight size={12} /></Link>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
