import { Fragment, useCallback, useEffect, useState } from 'react'
import { VALUE_STATE_SHORT } from '../services/ops/value'
import ValueSpendSection from '../components/ValueSpendSection'
import { Link, useSearchParams } from 'react-router-dom'
import {
  AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, CircleDashed, Coins, Hourglass, Pencil, Rocket, TrendingUp, X,
} from 'lucide-react'
import { getAgents, getGovernanceSummary, getPortfolioEconomics, requiredReviewsOf, type AgentEconomics, type GovernanceSummary, type RegistryAgent } from '../services/api'
import InfoTip from '../components/InfoTip'
import type { GlossaryKey } from '../lib/glossary'
import EditAgentModal from '../components/EditAgentModal'
import { STAGE_PILL, SourceBadge, TypeBadge, errorMessage, fmtCents, fmtMoney } from './agent/shared'

const UNASSIGNED = '__none__'
const PAGE = 100
// A full-time month: 40 h x 52 weeks / 12.
const FTE_HOURS_PER_MONTH = 173

// Every registered agent, across as many pages as the registry has; the
// totals here are only right if nothing is left out.
async function loadAllAgents(): Promise<RegistryAgent[]> {
  const first = (await getAgents(1, PAGE)).data
  const rest = await Promise.all(
    Array.from({ length: Math.max(0, first.pagination.pages - 1) }, (_, i) => getAgents(i + 2, PAGE)),
  )
  return [...first.data, ...rest.flatMap(r => r.data.data)]
}

const deptKey = (a: RegistryAgent) => a.dept || UNASSIGNED
const deptLabel = (a: RegistryAgent) => a.deptName || a.dept || 'Unassigned'

// "2,056×" / "3.4×": how many times its running cost the declared value is.
function fmtTimes(x: number): string {
  return x >= 10 ? `${Math.round(x).toLocaleString()}×` : `${x.toFixed(1)}×`
}

// ── What stands between projected value and Production ─────────────────────

type Blocker = 'changes' | 'reviewing' | 'unsubmitted' | 'ready'
const GATES = ['arb', 'security', 'dp'] as const
const GATE_NAME: Record<string, string> = { arb: 'Architecture', security: 'Security', dp: 'Data protection' }
const APPROVED = ['Approved', 'Approved with Conditions']

// Status colours ride with an icon and a label, never alone.
const BLOCKER: Record<Blocker, { label: string; icon: typeof Hourglass; iconClass: string }> = {
  changes: { label: 'Changes requested', icon: AlertTriangle, iconClass: 'text-rose-600 bg-rose-50' },
  reviewing: { label: 'Waiting on a reviewer', icon: Hourglass, iconClass: 'text-amber-600 bg-amber-50' },
  unsubmitted: { label: 'Reviews not submitted', icon: CircleDashed, iconClass: 'text-slate-600 bg-slate-100' },
  ready: { label: 'Approved, ready to promote', icon: CheckCircle2, iconClass: 'text-emerald-600 bg-emerald-50' },
}
const ORDER: Blocker[] = ['changes', 'reviewing', 'unsubmitted', 'ready']

// The single thing most in the way, so each agent's value is counted once.
// Review expiry is not in the registry list, so an expired approval reads as approved here.
// Only the reviews the agent's risk level requires (Settings → Governance rules) can hold it back.
function blockerOf(a: RegistryAgent, rules: GovernanceSummary | null): { kind: Blocker; detail: string } {
  const status = (g: string) => a.reviews?.[g] || 'Not Submitted'
  const required = requiredReviewsOf(rules, a.riskLevel)
  const named = (test: (s: string) => boolean) => GATES.filter(g => required.includes(g) && test(status(g))).map(g => GATE_NAME[g])
  const changes = named(s => s === 'Changes Requested')
  if (changes.length) return { kind: 'changes', detail: `${changes.join(', ')} review: changes requested` }
  const reviewing = named(s => s === 'In Review')
  if (reviewing.length) return { kind: 'reviewing', detail: `${reviewing.join(', ')} review: in review` }
  const open = named(s => !APPROVED.includes(s))
  if (open.length) return { kind: 'unsubmitted', detail: `${open.join(', ')} review: not submitted` }
  return { kind: 'ready', detail: required.length === GATES.length ? 'All three reviews approved' : 'Every required review approved' }
}

// ── Numbers the owners have not filled in ───────────────────────────────────

const GAPS = ['No value', 'No outcome', 'No owner'] as const
type Gap = typeof GAPS[number]
function gapsOf(a: RegistryAgent): Gap[] {
  return GAPS.filter(g =>
    g === 'No value' ? !a.valueAmount
      : g === 'No outcome' ? !(a.businessOutcome || '').trim()
        : !a.owner || a.owner === 'Unassigned')
}

const isPipeline = (a: RegistryAgent) => a.stage !== 'Production' && a.stage !== 'Deprecated'

// What the agent table is narrowed to after clicking a summary.
type Focus = { kind: 'blocker'; blocker: Blocker } | { kind: 'gap'; gap: Gap } | null

// Business Impact: what each business unit is running, what it produces and
// what it costs. Summaries stay small; one agent's detail opens on click.
// The unit filter lives in the URL (?dept=...), so a BU owner can bookmark it.
export default function BusinessView() {
  const [searchParams, setSearchParams] = useSearchParams()
  const dept = searchParams.get('dept') || ''
  const [agents, setAgents] = useState<RegistryAgent[]>([])
  const [econ, setEcon] = useState<Map<string, AgentEconomics>>(new Map())
  const [rules, setRules] = useState<GovernanceSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [focus, setFocus] = useState<Focus>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [fixing, setFixing] = useState<RegistryAgent | null>(null)

  const reload = useCallback(() => Promise.all([loadAllAgents(), getPortfolioEconomics().catch(() => null), getGovernanceSummary().catch(() => null)])
    .then(([list, e, g]) => {
      setAgents(list)
      setRules(g?.data ?? null)
      setEcon(new Map((e?.data.agents || []).map(x => [x.agentId, x])))
      setError(null)
    })
    .catch(e => setError(errorMessage(e, 'Could not load the registry')))
    .finally(() => setLoading(false)), [])

  useEffect(() => { reload() }, [reload])
  // A different unit starts with the full list and nothing expanded.
  useEffect(() => { setFocus(null); setOpen(null) }, [dept])

  if (loading) return <div className="p-8 text-center text-slate-600">Loading…</div>
  if (error) return <div className="p-8 text-center text-rose-500">Error: {error}</div>

  const units = [...agents.reduce((m, a) => {
    const u = m.get(deptKey(a)) || { key: deptKey(a), label: deptLabel(a), count: 0 }
    u.count += 1
    return m.set(u.key, u)
  }, new Map<string, { key: string; label: string; count: number }>()).values()]
    .sort((a, b) => (a.key === UNASSIGNED ? 1 : b.key === UNASSIGNED ? -1 : a.label.localeCompare(b.label)))
  const unit = units.find(u => u.key === dept)
  const list = unit ? agents.filter(a => deptKey(a) === unit.key) : agents

  // The value used everywhere: attested or adjusted by finance when checked, else declared (dollars a month).
  const valueOf = (a: RegistryAgent) => { const v = econ.get(a.id)?.valueCents; return v != null ? v / 100 : (a.valueAmount || 0) }

  // Retired agents stay in the table but produce and cost nothing now.
  const running = list.filter(a => a.stage !== 'Deprecated')
  const live = running.filter(a => a.stage === 'Production')
  const realized = live.reduce((s, a) => s + valueOf(a), 0)
  const projected = running.filter(isPipeline).reduce((s, a) => s + valueOf(a), 0)
  const hours = live.reduce((s, a) => s + (a.hoursSavedMonthly || 0), 0)
  const costCents = running.reduce((s, a) => s + (econ.get(a.id)?.totalCostCents || 0), 0)
  const costUnknown = running.filter(a => econ.get(a.id)?.costComplete === false).length
  const valueCents = (realized + projected) * 100

  const pipeline = running.filter(isPipeline).map(a => ({ a, ...blockerOf(a, rules) }))
  const pipelineValue = pipeline.reduce((s, r) => s + valueOf(r.a), 0)
  const groups = ORDER.map(kind => {
    const inKind = pipeline.filter(r => r.kind === kind)
    return { kind, count: inKind.length, value: inKind.reduce((s, r) => s + valueOf(r.a), 0) }
  }).filter(g => g.count)
  const gapCount = (g: Gap) => running.filter(a => gapsOf(a).includes(g)).length

  const shown = list.filter(a =>
    !focus ? true
      : focus.kind === 'blocker' ? isPipeline(a) && blockerOf(a, rules).kind === focus.blocker
        : a.stage !== 'Deprecated' && gapsOf(a).includes(focus.gap))
  const focusLabel = !focus ? '' : focus.kind === 'blocker' ? BLOCKER[focus.blocker].label.toLowerCase() : focus.gap.toLowerCase()

  const select = (key: string) => setSearchParams(key ? { dept: key } : {}, { replace: true })
  const chip = (active: boolean) => `text-xs px-3 py-1 rounded-full border transition-colors ${
    active ? 'bg-zen-600 text-white border-zen-600' : 'bg-white text-slate-700 border-gray-200 hover:border-gray-300 hover:text-slate-800'
  }`

  return (
    <div className="space-y-5 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold gradient-text">Business Impact</h1>
        <p className="text-slate-600 mt-0.5">What each business unit is running, the outcomes it produces and what it costs. Filter to your team.</p>
      </div>

      <div className="flex gap-2 flex-wrap" role="group" aria-label="Business unit" data-testid="bu-chips">
        <button type="button" onClick={() => select('')} aria-pressed={!unit} className={chip(!unit)}>
          All business units <span className="opacity-70">{agents.length}</span>
        </button>
        {units.map(u => (
          <button key={u.key} type="button" onClick={() => select(u.key)} aria-pressed={unit?.key === u.key} className={chip(unit?.key === u.key)}>
            {u.label} <span className="opacity-70">{u.count}</span>
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4" data-testid="bu-kpis">
        <Kpi label="Agents running" value={running.length.toLocaleString()}
          sub={`${live.length} live in production${list.length > running.length ? ` · ${list.length - running.length} retired (Deprecated) not counted` : ''}`} />
        <Kpi label="Value / month" tip="declared_value" value={fmtMoney(realized + projected)} accent="text-zen-600"
          sub={`${fmtMoney(realized)} from agents in Production · ${fmtMoney(projected)} from agents not yet in Production`} />
        <Kpi label="Cost to run / month" tip="cost_to_run" value={`${costUnknown ? '≥' : ''}${fmtCents(costCents)}`} accent="text-rose-600"
          sub={`tokens + hosting${costUnknown ? ` · ${costUnknown} agent${costUnknown === 1 ? '' : 's'} with no usage data` : ''}`} />
        <Kpi label="Return on cost" tip="return_on_cost" accent="text-zen-700"
          value={costCents > 0 && valueCents > 0 ? fmtTimes(valueCents / costCents) : '—'}
          sub={costCents > 0 && valueCents > 0 ? `value ÷ cost to run · ${hours.toLocaleString()} h saved (≈ ${Math.round(hours / FTE_HOURS_PER_MONTH)} FTE)`
            : valueCents > 0 ? 'no cost recorded yet' : 'no value declared yet'} />
      </div>

      <ValueSpendSection unitKey={unit && unit.key !== UNASSIGNED ? unit.key : null} unitLabel={unit ? unit.label : 'all business units'}
        unitAgentIds={unit ? list.map(a => a.id) : null} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-stretch">
        <SummaryCard icon={<Rocket size={18} />} tone="bg-zen-50 text-zen-600" title="Value waiting to go live" tip="value_waiting"
          sub="Projected value not yet in Production, by what is holding it back. Click one to see those agents."
          figure={fmtMoney(pipelineValue)} figureSub={`${pipeline.length} agent${pipeline.length === 1 ? '' : 's'} in the pipeline`} testId="pipeline-summary">
          {groups.length === 0 ? <p className="text-sm text-slate-600">Nothing in the pipeline for this unit.</p> : (
            <ul className="space-y-1">
              {groups.map(g => {
                const b = BLOCKER[g.kind]
                const Icon = b.icon
                const active = focus?.kind === 'blocker' && focus.blocker === g.kind
                return (
                  <li key={g.kind}>
                    <button type="button" onClick={() => { setFocus(active ? null : { kind: 'blocker', blocker: g.kind }); setOpen(null) }}
                      aria-pressed={active} data-testid={`blocker-${g.kind}`}
                      className={`flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors ${active ? 'bg-zen-50 ring-1 ring-zen-300' : 'hover:bg-slate-50'}`}>
                      <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-md ${b.iconClass}`}><Icon size={14} /></span>
                      <span className="flex-1 text-[13.5px] font-semibold text-slate-800">{b.label} <span className="font-normal text-slate-600">· {g.count}</span></span>
                      <span className="font-mono text-[12.5px] tabular-nums text-slate-900">{fmtMoney(g.value)}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
          {groups.some(g => g.kind === 'reviewing') && (
            <Link to="/approvals" className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-zen-700 hover:underline">
              Reviewers decide these in Approvals <ArrowRight size={13} />
            </Link>
          )}
        </SummaryCard>

        <SummaryCard icon={<AlertTriangle size={18} />} tone="bg-amber-50 text-amber-600" title="Missing details" tip="missing_numbers"
          sub="Agents with no value, outcome or owner recorded. An agent with no value adds nothing to the totals above. Click one to see which agents."
          figure={String(running.filter(a => gapsOf(a).length).length)} figureSub="agents with gaps" testId="gaps-summary">
          {GAPS.every(g => !gapCount(g)) ? (
            <p className="flex items-center gap-2 text-sm text-slate-700"><CheckCircle2 size={16} className="text-emerald-500" /> Every agent here has a value, an outcome and an owner.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {GAPS.filter(gapCount).map(g => {
                const active = focus?.kind === 'gap' && focus.gap === g
                return (
                  <button key={g} type="button" onClick={() => { setFocus(active ? null : { kind: 'gap', gap: g }); setOpen(null) }}
                    aria-pressed={active} data-testid={`gap-${g}`}
                    className={`rounded-full px-3 py-1 text-[12.5px] font-semibold ring-1 transition-colors ${
                      active ? 'bg-amber-500 text-white ring-amber-500' : 'bg-amber-50 text-amber-800 ring-amber-200 hover:bg-amber-100'}`}>
                    {gapCount(g)} with {g.toLowerCase()}
                  </button>
                )
              })}
            </div>
          )}
          {GAPS.some(gapCount) && (
            <p className="flex items-center gap-2 text-[12.5px] text-slate-600">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden />
              Agents with gaps carry this dot in the list below; open one to fill them in.
            </p>
          )}
        </SummaryCard>
      </div>

      <div className="card p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
          <div>
            <h2 className="text-[16px] font-extrabold text-slate-900">Agents in {unit ? unit.label : 'every business unit'}</h2>
            <p className="text-[13px] text-slate-600">Highest value first. Click an agent for its value, cost and what it still needs.</p>
          </div>
          {focus && (
            <button type="button" onClick={() => setFocus(null)} data-testid="clear-focus"
              className="inline-flex items-center gap-1.5 rounded-full bg-zen-50 px-3 py-1 text-[12.5px] font-semibold text-zen-700 ring-1 ring-zen-200 hover:bg-zen-100">
              Showing {shown.length}: {focusLabel} <X size={13} />
            </button>
          )}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="bu-table">
            <thead>
              <tr className="text-left text-[12.5px] font-bold uppercase tracking-[.06em] text-slate-700 whitespace-nowrap bg-gradient-to-r from-zen-50 to-slate-50">
                <th className="py-3 pl-3 pr-3 rounded-l-lg">Agent</th>
                <th className="py-3 pr-3">AI type <InfoTip term="ai_type" /></th>
                <th className="py-3 pr-3">Owner</th>
                <th className="py-3 pr-3">Stage <InfoTip term="stage" /></th>
                <th className="py-3 pr-3 text-right text-emerald-700">Value / mo <InfoTip term="declared_value" /></th>
                <th className="py-3 pr-3 text-right text-rose-700">Cost / mo <InfoTip term="cost_to_run" /></th>
                <th className="py-3 pr-3 w-8 rounded-r-lg" aria-label="Details" />
              </tr>
            </thead>
            <tbody>
              {shown.map(a => {
                const isOpen = open === a.id
                const e = econ.get(a.id)
                const gaps = a.stage === 'Deprecated' ? [] : gapsOf(a)
                return (
                  <Fragment key={a.id}>
                    <tr onClick={() => setOpen(isOpen ? null : a.id)} data-testid="bu-row"
                      className={`cursor-pointer border-b border-slate-100 align-top transition-colors ${isOpen ? 'bg-zen-50/60 shadow-[inset_3px_0_0_#6366f1]' : 'hover:bg-zen-50/30 hover:shadow-[inset_3px_0_0_#c7d2fe]'}`}>
                      <td className="py-3 pl-3 pr-3">
                        <div className="flex items-center gap-1.5">
                          <span className="text-[14.5px] font-bold text-slate-900">{a.name}</span>
                          {gaps.length > 0 && <span className="h-1.5 w-1.5 rounded-full bg-amber-500" title={`Missing: ${gaps.join(', ').toLowerCase()}`} />}
                        </div>
                        <div className="mt-0.5 text-[12.5px] text-slate-700 line-clamp-1 max-w-[360px]">
                          {!unit && <span className="font-semibold text-zen-600">{deptLabel(a)} · </span>}
                          {a.businessOutcome || <span className="text-slate-500">No outcome stated</span>}
                        </div>
                      </td>
                      <td className="py-3 pr-3"><TypeBadge type={a.aiType} /></td>
                      <td className="py-3 pr-3 text-[13px] text-slate-700">{a.owner && a.owner !== 'Unassigned' ? a.owner : <span className="text-slate-500">—</span>}</td>
                      <td className="py-3 pr-3"><span className={STAGE_PILL[a.stage] || 'status-pending'}>{a.stage}</span></td>
                      <td className="py-3 pr-3 text-right font-mono text-[14px] font-bold text-emerald-700">
                        {valueOf(a) ? fmtMoney(valueOf(a)) : '—'}
                        {e?.valueState && e.valueState !== 'none' && (
                          <span className={`block font-sans text-[11px] font-semibold ${e.valueState === 'attested' || e.valueState === 'adjusted' ? 'text-emerald-700' : 'text-slate-500'}`}>
                            {VALUE_STATE_SHORT[e.valueState]}
                          </span>
                        )}
                      </td>
                      <td className="py-3 pr-3 text-right font-mono text-[13.5px] font-semibold text-rose-600">{e?.totalCostCents != null ? fmtCents(e.totalCostCents) : '—'}</td>
                      <td className="py-3 pr-3 text-slate-500">
                        <button type="button" aria-expanded={isOpen} aria-label={`${isOpen ? 'Hide' : 'Show'} details for ${a.name}`}
                          onClick={ev => { ev.stopPropagation(); setOpen(isOpen ? null : a.id) }}>
                          <ChevronDown size={16} className={`transition-transform ${isOpen ? 'rotate-180 text-zen-600' : ''}`} />
                        </button>
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="bg-zen-50/40" data-testid="bu-detail">
                        <td colSpan={7} className="px-3 pb-4 pt-1">
                          <AgentDetail agent={a} econ={e} gaps={gaps} rules={rules} onFix={() => setFixing(a)} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
          {shown.length === 0 && <p className="py-6 text-center text-sm text-slate-500">No agents here.</p>}
        </div>
      </div>

      {fixing && (
        <EditAgentModal agent={fixing} onClose={() => setFixing(null)} onSaved={() => { setFixing(null); reload() }} />
      )}
    </div>
  )
}

function Kpi({ label, value, sub, accent, tip }: { label: string; value: string; sub: string; accent?: string; tip?: GlossaryKey }) {
  return (
    <div className="card p-4">
      <div className="text-xs text-slate-600 uppercase tracking-wide">{label}{tip && <> <InfoTip term={tip} /></>}</div>
      <div className={`text-2xl font-bold mt-1 ${accent || 'text-slate-900'}`}>{value}</div>
      <div className="text-xs text-slate-500 mt-1">{sub}</div>
    </div>
  )
}

function SummaryCard({ icon, tone, title, tip, sub, figure, figureSub, testId, children }: {
  icon: React.ReactNode; tone: string; title: string; tip?: GlossaryKey; sub: string; figure: string; figureSub: string; testId: string; children: React.ReactNode
}) {
  return (
    <section className="card p-5 space-y-3" data-testid={testId}>
      <div className="flex items-start gap-3">
        <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${tone}`}>{icon}</div>
        <div className="flex-1 min-w-0">
          <h2 className="text-[16px] font-extrabold text-slate-900">{title}{tip && <> <InfoTip term={tip} /></>}</h2>
          <p className="text-[12.5px] text-slate-600">{sub}</p>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-[22px] font-extrabold leading-none text-slate-900">{figure}</div>
          <div className="mt-1 text-[12.5px] text-slate-600">{figureSub}</div>
        </div>
      </div>
      {children}
    </section>
  )
}

// One agent, opened from the table: value against cost, what is holding it
// back, and what its owner still has to fill in.
function AgentDetail({ agent: a, econ: e, gaps, rules, onFix }: {
  agent: RegistryAgent; econ: AgentEconomics | undefined; gaps: Gap[]; rules: GovernanceSummary | null; onFix: () => void
}) {
  const value = e?.valueCents ?? (a.valueAmount || 0) * 100
  const cost = e?.totalCostCents
  const blocker = isPipeline(a) ? blockerOf(a, rules) : null
  const B = blocker ? BLOCKER[blocker.kind] : null
  return (
    <div className="rounded-xl border border-zen-100 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[15px] font-extrabold text-slate-900">{a.name}</div>
          <div className="text-[12.5px] text-slate-600">{deptLabel(a)} · {a.stage}{a.hoursSavedMonthly ? ` · ${a.hoursSavedMonthly.toLocaleString()} h saved / mo` : ''}</div>
        </div>
        <Link to={`/agents/${a.id}?tab=revenue`} data-testid="go-to-agent"
          className="inline-flex items-center gap-1.5 rounded-full bg-gradient-zen px-4 py-1.5 text-[13px] font-semibold text-white shadow-sm hover:brightness-110">
          Go to the agent <ArrowRight size={14} />
        </Link>
      </div>

      <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
        <DetailBlock icon={<Coins size={15} />} title="Value vs cost">
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[13px]">
            <dt className="text-slate-600">{e?.valueState === 'attested' || e?.valueState === 'adjusted' ? 'Attested value' : 'Declared value'} <InfoTip term="declared_value" /></dt>
            <dd className="text-right font-semibold text-slate-900">{value ? `${fmtMoney(value / 100)}/mo` : '—'}</dd>
            <dt className="text-slate-600 flex items-center gap-1">Token {e?.tokenSource && <SourceBadge source={e.tokenSource} />}</dt>
            <dd className="text-right text-slate-900">{e?.tokenCostCents != null ? fmtCents(e.tokenCostCents) : 'unknown'}</dd>
            <dt className="text-slate-600 flex items-center gap-1">Hosting {e?.infraSource && <SourceBadge source={e.infraSource} />}</dt>
            <dd className="text-right text-slate-900">{e?.infraCostCents != null ? fmtCents(e.infraCostCents) : '—'}</dd>
            <dt className="text-slate-600">Return <InfoTip term="return_on_cost" /></dt>
            <dd className="text-right font-semibold text-zen-700">{value > 0 && cost ? fmtTimes(value / cost) : '—'}</dd>
          </dl>
        </DetailBlock>

        <DetailBlock icon={<TrendingUp size={15} />} title={blocker ? 'What is holding it back' : 'Status'}>
          {B && blocker ? (
            <div className="flex items-start gap-2">
              <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-md ${B.iconClass}`}><B.icon size={14} /></span>
              <div className="text-[13px]">
                <div className="font-semibold text-slate-800">{B.label}</div>
                <div className="text-slate-600">{blocker.detail}</div>
                <Link to={`/agents/${a.id}?tab=governance`} className="mt-1 inline-block font-semibold text-zen-700 hover:underline">Open Governance</Link>
              </div>
            </div>
          ) : (
            <p className="flex items-center gap-2 text-[13px] text-slate-700">
              <CheckCircle2 size={15} className="text-emerald-500" /> {a.stage === 'Deprecated' ? 'Retired' : 'Live in production'}
            </p>
          )}
        </DetailBlock>

        <DetailBlock icon={<AlertTriangle size={15} />} title="Missing details">
          {gaps.length === 0 ? (
            <p className="flex items-center gap-2 text-[13px] text-slate-700"><CheckCircle2 size={15} className="text-emerald-500" /> Value, outcome and owner declared</p>
          ) : (
            <div className="space-y-2">
              <div className="flex flex-wrap gap-1">
                {gaps.map(g => <span key={g} className="rounded bg-amber-50 px-1.5 py-0.5 text-[12.5px] font-semibold text-amber-800 ring-1 ring-amber-200">{g}</span>)}
              </div>
              <button type="button" onClick={onFix} className="btn-secondary btn-sm flex items-center gap-1" data-testid="fix-gaps">
                <Pencil size={13} /> Fill them in
              </button>
            </div>
          )}
        </DetailBlock>
      </div>
    </div>
  )
}

function DetailBlock({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg bg-slate-50/80 p-3 ring-1 ring-slate-100">
      <div className="mb-2 flex items-center gap-1.5 text-[12px] font-bold uppercase tracking-[.05em] text-slate-600">
        <span className="text-zen-500">{icon}</span>{title}
      </div>
      {children}
    </div>
  )
}
