import { Fragment, useCallback, useEffect, useState } from 'react'
import { VALUE_STATE_SHORT } from '../services/ops/value'
import ValueSpendSection from '../components/ValueSpendSection'
import { Link, useSearchParams } from 'react-router-dom'
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, CircleDashed, Coins, Hourglass, Pencil, Rocket, TrendingUp, X, ChevronRight } from 'lucide-react'
import { getAgents, getTaxonomy, getGovernanceSummary, getPortfolioEconomics, requiredReviewsOf, type AgentEconomics, type GovernanceSummary, type RegistryAgent } from '../services/api'
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
// What the page hands to the widgets placed in its slots: the agents of the chosen business unit.
export interface UnitContext {
  unitKey: string            // '' for every unit, a department id, or '__none__'
  unitLabel: string
  list: RegistryAgent[]      // every agent of the unit, retired ones included
  running: RegistryAgent[]   // without the retired ones
  valueOf: (a: RegistryAgent) => number
}
// Places for other widgets inside the page, so one filter drives them all.
export interface PageSlots {
  // The Total agents card opens a list on the page that embeds this view.
  agentsCard?: { open: boolean; toggle: () => void }
  kpis?: (c: UnitContext) => React.ReactNode
  afterKpis?: (c: UnitContext) => React.ReactNode
  pipeline?: (c: UnitContext) => React.ReactNode
  risk?: (c: UnitContext) => React.ReactNode
  mix?: (c: UnitContext) => React.ReactNode
  end?: (c: UnitContext) => React.ReactNode
}

export default function BusinessView({ embedded = false, slots = {} }: { embedded?: boolean; slots?: PageSlots }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const dept = searchParams.get('dept') || ''
  const [agents, setAgents] = useState<RegistryAgent[]>([])
  const [econ, setEcon] = useState<Map<string, AgentEconomics>>(new Map())
  const [rules, setRules] = useState<GovernanceSummary | null>(null)
  const [departments, setDepartments] = useState<{ id: string; name: string }[]>([])
  const [showCost, setShowCost] = useState(false)
  const [showValue, setShowValue] = useState(false)
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
  useEffect(() => { getTaxonomy().then(r => setDepartments(r.data.departments || [])).catch(() => setDepartments([])) }, [])
  // A different unit starts with the full list and nothing expanded.
  useEffect(() => { setFocus(null); setOpen(null) }, [dept])

  if (loading) return <div className="p-8 text-center text-slate-600">Loading…</div>
  if (error) return <div className="p-8 text-center text-rose-500">Error: {error}</div>

  // Every business unit is offered, also one with no agent yet.
  const units = [...agents.reduce((m, a) => {
    const u = m.get(deptKey(a)) || { key: deptKey(a), label: deptLabel(a), count: 0 }
    u.count += 1
    return m.set(u.key, u)
  }, new Map<string, { key: string; label: string; count: number }>(departments.map(d => [d.id, { key: d.id, label: d.name, count: 0 }]))).values()]
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

  const ctx: UnitContext = { unitKey: unit ? unit.key : '', unitLabel: unit ? unit.label : 'all business units', list, running, valueOf }

  return (
    <div className="space-y-5 animate-fade-in" id={embedded ? 'business-impact' : undefined}>
      {!embedded && (
        <div>
          <h1 className="text-2xl font-bold gradient-text">Business Impact</h1>
          <p className="text-slate-600 mt-0.5">What each business unit is running, the outcomes it produces and what it costs. Filter to your team. Click a figure to see how it is made up.</p>
        </div>
      )}

      <div className="flex gap-2 flex-wrap" role="group" aria-label="Business unit" data-testid="bu-chips">
        <button type="button" onClick={() => select('')} aria-pressed={!unit} className={chip(!unit)}>
          All business units <span className="opacity-70">{agents.length}</span>
        </button>
        {units.map(u => (
          <button key={u.key} type="button" onClick={() => select(u.key)} aria-pressed={unit?.key === u.key}
            className={`${chip(unit?.key === u.key)} ${u.count === 0 && unit?.key !== u.key ? 'opacity-60' : ''}`} title={u.count === 0 ? `No agent is registered for ${u.label} yet` : undefined}>
            {u.label} <span className="opacity-70">{u.count}</span>
          </button>
        ))}
      </div>

      <div className="space-y-4" data-testid="bu-kpis">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Kpi label="Total agents" tip="total_agents" value={running.length.toLocaleString()} testId="kpi-agents"
          sub={`${live.length} in Production · ${running.filter(isPipeline).length} in pipeline${list.length > running.length ? ` · ${list.length - running.length} retired, not counted` : ''}`}
          open={slots.agentsCard?.open} onOpen={slots.agentsCard ? slots.agentsCard.toggle : () => document.getElementById('bu-agents')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
          hint={slots.agentsCard ? 'The agents in the pipeline' : 'Go to the list of agents'} />
        <Kpi label="Value / month" tip="declared_value" value={fmtMoney(realized + projected)} accent="text-zen-600" testId="value-breakdown-toggle"
          sub={`${fmtMoney(realized)} in Production · ${fmtMoney(projected)} not yet in Production · ${hours.toLocaleString()} h saved (≈ ${Math.round(hours / FTE_HOURS_PER_MONTH)} FTE)`}
          open={showValue} onOpen={() => setShowValue(v => !v)} hint="How the value is calculated" />
        <Kpi label="Cost to run / month" tip="cost_and_return" value={`${costUnknown ? '≥' : ''}${fmtCents(costCents)}`} accent="text-rose-600" testId="cost-breakdown-toggle"
          sub={`tokens + hosting · ${costCents > 0 && valueCents > 0 ? `return on cost ${fmtTimes(valueCents / costCents)} (${fmtMoney(valueCents / 100)} ÷ ${fmtCents(costCents)})` : valueCents > 0 ? 'no cost recorded yet' : 'no value declared yet, so no return on cost'}${costUnknown ? ` · ${costUnknown} agent${costUnknown === 1 ? '' : 's'} with no usage data` : ''}`}
          open={showCost} onOpen={() => setShowCost(v => !v)} hint="How the cost is calculated" />
        {slots.kpis?.(ctx)}
      </div>
      </div>
      {slots.afterKpis?.(ctx)}

      {showValue && <ValueBreakdown agents={running} econ={econ} valueOf={valueOf} unitLabel={unit ? unit.label : 'all business units'} />}
      {showCost && <CostBreakdown agents={running} econ={econ} totalCents={costCents} unknown={costUnknown} unitLabel={unit ? unit.label : 'all business units'} />}

      {slots.risk?.(ctx)}

      {slots.pipeline?.(ctx)}

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
              Reviewers decide these in Integration Approval <ArrowRight size={13} />
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


      <ValueSpendSection unitKey={unit && unit.key !== UNASSIGNED ? unit.key : null} unitLabel={unit ? unit.label : 'all business units'}
        unitAgentIds={unit ? list.map(a => a.id) : null} />

      {slots.mix?.(ctx)}

      <div className="card p-5" id="bu-agents">
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

      {slots.end?.(ctx)}

      {fixing && (
        <EditAgentModal agent={fixing} onClose={() => setFixing(null)} onSaved={() => { setFixing(null); reload() }} />
      )}
    </div>
  )
}

// A figure on a card. The whole card is clickable: it opens the working behind the figure, or goes to the list.
export function Kpi({ label, value, sub, accent, tip, onOpen, open, hint, testId }: {
  label: string; value: string; sub: string; accent?: string; tip?: GlossaryKey; onOpen?: () => void; open?: boolean; hint?: string; testId?: string
}) {
  const body = (
    <>
      <div className="text-xs text-slate-600 uppercase tracking-wide">{label}{tip && <> <InfoTip term={tip} /></>}</div>
      <div className={`text-2xl font-bold mt-1 ${accent || 'text-slate-900'}`}>{value}</div>
      <div className="text-xs text-slate-500 mt-1">{sub}</div>
    </>
  )
  if (!onOpen) return <div className="card p-4">{body}</div>
  return (
    <div className={`card p-4 cursor-pointer transition hover:shadow-card-hover ${open ? 'ring-2 ring-zen-400' : ''}`} role="button" tabIndex={0} title={hint}
      aria-expanded={open} data-testid={testId} onClick={onOpen} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen() } }}>
      {body}
    </div>
  )
}

const WHOSE: Record<string, string> = {
  declared: 'Declared by the owner', attested: 'Confirmed by finance', adjusted: 'Adjusted by finance',
  stale: 'Declared again by the owner, finance has not confirmed the new figure', none: 'Not declared',
}

// How "Value / month" is made up: one row per agent with its value and who stands behind the figure.
function ValueBreakdown({ agents, econ, valueOf, unitLabel }: {
  agents: RegistryAgent[]; econ: Map<string, AgentEconomics>; valueOf: (a: RegistryAgent) => number; unitLabel: string
}) {
  const rows = agents.map(a => ({ a, e: econ.get(a.id), value: valueOf(a) })).sort((x, y) => y.value - x.value)
  const live = rows.filter(r => r.a.stage === 'Production').reduce((s, r) => s + r.value, 0)
  const total = rows.reduce((s, r) => s + r.value, 0)
  const withValue = rows.filter(r => r.value > 0).length
  return (
    <section className="card p-5 space-y-3" data-testid="value-breakdown">
      <div>
        <h2 className="font-semibold text-slate-900">How the value is calculated</h2>
        <p className="text-[13px] text-slate-700">
          Value a month = the value of each agent of {unitLabel} that is not retired, added up: <b>{fmtMoney(live)}</b> from agents in Production + <b>{fmtMoney(total - live)}</b> from
          agents not yet in Production = <b className="text-zen-700">{fmtMoney(total)}</b>. {withValue} of {rows.length} agent{rows.length === 1 ? ' has' : 's have'} a value.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-left text-slate-600 border-b">
              <th className="py-1.5 pr-3">Agent</th><th className="pr-3">Stage</th><th className="pr-3 text-right">Value a month</th>
              <th className="pr-3">Whose figure</th><th className="pr-3">How it was worked out</th><th>Counted as</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ a, e, value }) => {
              const state = value > 0 ? (e?.valueState || 'declared') : 'none'
              const owners = e?.valueDeclaredCents
              return (
                <tr key={a.id} className="border-b border-slate-100 last:border-0" data-testid="value-row">
                  <td className="py-1.5 pr-3"><Link to={`/agents/${a.id}?tab=revenue`} className="font-medium text-zen-700 hover:underline">{a.name}</Link></td>
                  <td className="pr-3 text-slate-600">{a.stage}</td>
                  <td className="pr-3 text-right font-mono text-slate-900">{value > 0 ? fmtMoney(value) : <span className="text-slate-500">none</span>}</td>
                  <td className="pr-3">{WHOSE[state] || state}{state === 'adjusted' && owners ? ` (the owner declared ${fmtCents(owners)})` : ''}</td>
                  <td className="pr-3 text-slate-600">{value > 0 ? (e?.valueMethodLabel || 'Not stated') : ''}</td>
                  <td className="text-slate-600">{value > 0 ? (a.stage === 'Production' ? 'In Production' : 'Not yet in Production') : 'Adds nothing'}</td>
                </tr>
              )
            })}
            <tr className="font-semibold text-slate-900"><td className="py-1.5 pr-3" colSpan={2}>Total</td><td className="pr-3 text-right font-mono text-zen-700">{fmtMoney(total)}</td><td colSpan={3} /></tr>
          </tbody>
        </table>
      </div>
      <p className="text-[12.5px] text-slate-600">The value of an agent is the figure finance confirmed or adjusted. When finance has not looked at it, it is the figure the owner declared. Open an agent to see or change its value.</p>
    </section>
  )
}

const usd = (cents: number | null | undefined, digits = 2) => cents == null ? 'not known' : `$${(cents / 100).toFixed(digits)}`

// The working behind one agent's two figures: token cost from tokens and days, hosting cost from its source.
function CostWorking({ agent: a, e }: { agent: RegistryAgent; e: AgentEconomics | undefined }) {
  const t = e?.token, h = e?.infra, days = e?.period
  if (!e || !t || !h) return <p className="text-[12.5px] text-slate-600">No cost figures for this agent yet.</p>
  const rest = t.dailyAvg14Cents != null && t.daysLeft != null ? t.dailyAvg14Cents * t.daysLeft : null
  const stages = Object.entries(h.estimateByStage || {}).filter(([st]) => st !== 'Deprecated')
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 text-[12.5px] text-slate-700" data-testid="cost-working">
      <div className="space-y-1.5">
        <div className="font-semibold text-slate-900">Token cost: {e.tokenCostCents == null ? 'not known' : `${usd(e.tokenCostCents)} a month`}</div>
        {t.projectedCents == null ? (
          <p>{t.status === 'unlinked' ? 'No tracing is linked and no usage was entered by hand, so there is nothing to price.' : t.unpricedModels.length ? `Its calls use a model with no price in the price list (${t.unpricedModels.join(', ')}), so the cost cannot be worked out.` : 'No usage has been read for this agent yet.'}</p>
        ) : (
          <>
            <p>Spent so far this month ({days?.daysElapsed} day{days?.daysElapsed === 1 ? '' : 's'}): <b>{usd(t.monthToDateCents, 4)}</b>.<br />
              Rest of the month: average of the last 14 days <b>{usd(t.dailyAvg14Cents, 4)}</b> a day × <b>{t.daysLeft}</b> day{t.daysLeft === 1 ? '' : 's'} left = <b>{usd(rest, 4)}</b>.<br />
              {usd(t.monthToDateCents, 4)} + {usd(rest, 4)} = <b className="text-slate-900">{usd(t.projectedCents, 4)}</b> for the full month.</p>
            {(t.modelsThisMonth || []).length > 0 ? (
              <table className="w-full">
                <thead><tr className="text-left text-slate-500"><th className="font-medium">Model (this month so far)</th><th className="font-medium text-right">Calls</th><th className="font-medium text-right">Tokens in</th><th className="font-medium text-right">Tokens out</th><th className="font-medium text-right">Cost</th></tr></thead>
                <tbody>{t.modelsThisMonth!.map(m => (
                  <tr key={m.model}><td>{m.model}{!m.priced && <span className="text-amber-700"> (no price)</span>}</td><td className="text-right">{m.calls.toLocaleString()}</td>
                    <td className="text-right">{m.inputTokens.toLocaleString()}</td><td className="text-right">{m.outputTokens.toLocaleString()}</td><td className="text-right font-mono">{usd(m.costCents, 4)}</td></tr>
                ))}</tbody>
              </table>
            ) : <p>No calls this month so far.</p>}
            <p className="text-slate-500">Each model's cost is its tokens times the price per token in the model price list. The day-by-day figures are on the agent's <Link to={`/agents/${a.id}?tab=tokenomics`} className="text-zen-700 hover:underline">Tokenomics tab</Link>.</p>
          </>
        )}
      </div>
      <div className="space-y-1.5">
        <div className="font-semibold text-slate-900">Hosting cost: {usd(h.cents)} a month</div>
        {h.source === 'metered' && (
          <>
            <p>Measured by Azure Cost Management. Billed so far this month, up to {h.meteredThrough}: <b>{usd(h.meteredMonthToDateCents)}</b>, scaled to the {h.daysInPeriod} days of the month = <b className="text-slate-900">{usd(h.cents)}</b>.</p>
            <table className="w-full"><thead><tr className="text-left text-slate-500"><th className="font-medium">Azure resource</th><th className="font-medium">Service</th><th className="font-medium text-right">Billed so far</th></tr></thead>
              <tbody>{h.byResource.map(r => <tr key={r.resourceId}><td className="break-all">{r.resourceId.split('/').pop()}</td><td>{r.serviceName || ''}</td><td className="text-right font-mono">{usd(r.cents)}</td></tr>)}</tbody></table>
          </>
        )}
        {h.source === 'declared' && (
          <>
            <p>Declared by the owner{h.declaredFrom ? ` from ${h.declaredFrom}` : ''}: <b className="text-slate-900">{usd(h.declaredMonthlyCents)}</b> a month. It is the owner's figure, not a measured one.</p>
            {h.components.length > 0 && <ul className="list-disc pl-5">{h.components.map(c => <li key={c.name}>{c.name}{c.costCents != null ? `: ${usd(c.costCents)}${c.recurring ? ' a month' : ' once'}` : ''}</li>)}</ul>}
          </>
        )}
        {h.source === 'estimate' && (
          <>
            <p>Not measured and not declared. The registry uses one fixed figure per stage: {stages.map(([st, c]) => `${st} ${usd(c, 0)}`).join(', ')}. This agent is in <b>{a.stage}</b>, so <b className="text-slate-900">{usd(h.cents, 0)}</b>.</p>
            <p>It is the same for every agent in that stage and is not a measured cost.</p>
            <p>To replace it with a real figure: declare the hosting cost on the agent's <Link to={`/agents/${a.id}?tab=revenue`} className="text-zen-700 hover:underline">Revenue &amp; Expenditure tab</Link>, or connect Azure Cost Management in Settings → Cost settings.</p>
          </>
        )}
      </div>
    </div>
  )
}

// How "Cost to run / month" is made up: one row per agent, token cost plus hosting cost, each with where
// the figure comes from. The rows add up to the figure on the tile.
function CostBreakdown({ agents, econ, totalCents, unknown, unitLabel }: {
  agents: RegistryAgent[]; econ: Map<string, AgentEconomics>; totalCents: number; unknown: number; unitLabel: string
}) {
  const rows = agents.map(a => {
    const e = econ.get(a.id)
    return { a, e, token: e?.tokenCostCents ?? null, hosting: e?.infraCostCents ?? 0, total: e?.totalCostCents || 0 }
  }).sort((x, y) => y.total - x.total)
  const max = Math.max(1, ...rows.map(r => r.total))
  const [openId, setOpenId] = useState<string | null>(null)
  const tokenSum = rows.reduce((s, r) => s + (r.token || 0), 0)
  const hostingSum = rows.reduce((s, r) => s + r.hosting, 0)
  return (
    <section className="card p-5 space-y-3" data-testid="cost-breakdown">
      <div>
        <h2 className="font-semibold text-slate-900">How the cost to run is calculated</h2>
        <p className="text-[13px] text-slate-700">
          Cost to run a month = token cost + hosting cost, added up over the {rows.length} agent{rows.length === 1 ? '' : 's'} of {unitLabel} that are not retired:
          {' '}<b>{fmtCents(tokenSum)}</b> tokens + <b>{fmtCents(hostingSum)}</b> hosting = <b className="text-rose-600">{unknown ? '≥' : ''}{fmtCents(totalCents)}</b>.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-left text-slate-600 border-b">
              <th className="py-1.5 pr-3">Agent (click a row for its working)</th><th className="pr-3">Stage</th>
              <th className="pr-3">Token cost</th><th className="pr-3">Hosting cost</th><th className="pr-3 text-right">Total a month</th><th className="w-[26%]">Share</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ a, e, token, hosting, total }) => (
              <Fragment key={a.id}>
              <tr className="border-b border-slate-100 last:border-0 cursor-pointer hover:bg-slate-50" data-testid="cost-row" onClick={() => setOpenId(openId === a.id ? null : a.id)}>
                <td className="py-1.5 pr-3"><span className="inline-flex items-center gap-1">
                  {openId === a.id ? <ChevronDown size={14} className="text-slate-500" /> : <ChevronRight size={14} className="text-slate-500" />}
                  <Link to={`/agents/${a.id}?tab=revenue`} onClick={ev => ev.stopPropagation()} className="font-medium text-zen-700 hover:underline">{a.name}</Link></span></td>
                <td className="pr-3 text-slate-600">{a.stage}</td>
                <td className="pr-3 whitespace-nowrap">{token == null ? <span className="text-slate-500">not known</span> : fmtCents(token)} {e?.tokenSource && <SourceBadge source={e.tokenSource} />}</td>
                <td className="pr-3 whitespace-nowrap">{fmtCents(hosting)} {e?.infraSource && <SourceBadge source={e.infraSource} />}</td>
                <td className="pr-3 text-right font-mono text-slate-900">{fmtCents(total)}</td>
                <td>
                  <div className="flex h-2.5 overflow-hidden rounded-full bg-slate-100" title={`Tokens ${fmtCents(token || 0)}, hosting ${fmtCents(hosting)}`}>
                    <div className="h-full bg-sky-400" style={{ width: `${((token || 0) / max) * 100}%` }} />
                    <div className="h-full bg-rose-300" style={{ width: `${(hosting / max) * 100}%` }} />
                  </div>
                </td>
              </tr>
              {openId === a.id && <tr className="border-b border-slate-100 bg-slate-50/60"><td colSpan={6} className="px-4 py-3"><CostWorking agent={a} e={e} /></td></tr>}
              </Fragment>
            ))}
            <tr className="font-semibold text-slate-900">
              <td className="py-1.5 pr-3" colSpan={2}>Total</td>
              <td className="pr-3">{fmtCents(tokenSum)}</td><td className="pr-3">{fmtCents(hostingSum)}</td>
              <td className="pr-3 text-right font-mono text-rose-600">{unknown ? '≥' : ''}{fmtCents(totalCents)}</td><td />
            </tr>
          </tbody>
        </table>
      </div>
      <ul className="text-[12.5px] text-slate-600 space-y-0.5">
        <li><span className="inline-block h-2 w-2 rounded-full bg-sky-400 mr-1.5" />Token cost: what the agent's model calls cost so far this month, projected to the full month. It comes from the agent's traces or from usage entered by hand.</li>
        <li><span className="inline-block h-2 w-2 rounded-full bg-rose-300 mr-1.5" />Hosting cost: the metered Azure figure when one exists, otherwise the figure the owner declared, otherwise the registry's estimate for the agent's stage.</li>
        {unknown > 0 && <li>{unknown} agent{unknown === 1 ? ' has' : 's have'} no usage data, so {unknown === 1 ? 'its' : 'their'} token cost is not known and counts as nothing here. That is why the total is shown as "at least" (≥).</li>}
      </ul>
    </section>
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
