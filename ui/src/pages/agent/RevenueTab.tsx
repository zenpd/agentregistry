import { useCallback, useEffect, useRef, useState } from 'react'
import {
  addResourceLink,
  collectInfraCosts,
  deleteResourceLink,
  getCostPerOutcome,
  getEconomics,
  getInfraCostStatus,
  getInfraProfile,
  getResourceLinks,
  saveInfraProfile,
  type AgentEconomicsDetail,
  type CostPerOutcome,
  type InfraComponent,
  type InfraCostStatus,
  type InfraProfile,
  type JobRunSummary,
  type ResourceLink,
  type TrendMonth,
} from '../../services/ops/economics'
import { Loading, SectionLabel, SEVERITY_PILL, SourceBadge, fmtCents, fmtNumber, type TabProps } from './shared'

// Validated categorical slots 1-2 (blue, orange); value is neutral ink, not a series hue.
const SERIES = { token: '#2a78d6', infra: '#eb6834', value: '#374151' }

const RATING: Record<string, { label: string; className: string; text: string }> = {
  efficient: { label: 'Efficient', className: 'bg-teal-50 text-teal-700 ring-teal-200', text: 'under $0.10 per $1 of value' },
  moderate: { label: 'Moderate', className: 'bg-sky-50 text-sky-700 ring-sky-200', text: '$0.10–$0.27 per $1 of value' },
  below_average: { label: 'Below average', className: 'bg-amber-50 text-amber-700 ring-amber-200', text: '$0.27–$1.00 per $1 of value' },
  inefficient: { label: 'Costs more than its value', className: 'bg-rose-50 text-rose-700 ring-rose-200', text: '$1.00 or more per $1 of value' },
}

const RUN_STATUS_TEXT: Record<string, string> = {
  ok: 'Collected',
  partial: 'Collected — some cost could not be allocated to an agent',
  not_configured: 'Not configured',
  forbidden: 'Azure refused access (check the service principal and its Cost Management Reader role)',
  throttled: 'Azure throttled the request — try again later',
  unreachable: 'Azure could not be reached',
  error: 'Failed',
  skipped: 'Skipped',
  running: 'Running',
}

// ── Formatting ───────────────────────────────────────────────────────────────

function errorMessage(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d: any) => String(d.msg || d).replace(/^Value error, /, '')).join('; ')
  return e?.message || fallback
}

// Token costs are often fractions of a cent, so small amounts keep 3 significant digits.
function fmtCost(cents: number | null | undefined): string {
  if (cents == null) return '—'
  const n = cents / 100
  const abs = Math.abs(n)
  if (abs === 0) return '$0.00'
  if (abs >= 1) return fmtCents(cents)
  if (abs < 0.0001) return '<$0.0001'
  return '$' + Number(n.toPrecision(3)).toString()
}

function fmtSigned(cents: number): string {
  return (cents < 0 ? '−' : '+') + fmtCents(Math.abs(cents))
}

function fmtMonth(month: string): string {
  const [y, m] = month.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })
}

function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

function Banner({ tone, children }: { tone: 'teal' | 'amber' | 'rose' | 'gray'; children: React.ReactNode }) {
  const style = {
    teal: 'bg-teal-50 text-teal-800 border-teal-100',
    amber: 'bg-amber-50 text-amber-800 border-amber-100',
    rose: 'bg-rose-50 text-rose-700 border-rose-100',
    gray: 'bg-gray-50 text-gray-600 border-gray-100',
  }[tone]
  return <div className={`rounded-lg border px-3 py-2 text-xs ${style}`}>{children}</div>
}

function Tile({ label, value, sub, accent, muted }: {
  label: string
  value: React.ReactNode
  sub?: React.ReactNode
  accent?: string
  muted?: boolean
}) {
  return (
    <div className="rounded-lg bg-gray-50 px-3 py-2 min-w-0">
      <div className="text-[10px] text-gray-400 uppercase tracking-wide">{label}</div>
      <div className={`mt-0.5 ${muted ? 'text-sm font-medium text-gray-400' : `text-base font-bold ${accent || 'text-gray-900'}`}`}>{value}</div>
      {sub && <div className="text-[11px] text-gray-500 mt-0.5 flex flex-wrap items-center gap-1">{sub}</div>}
    </div>
  )
}

function Swatch({ color }: { color: string }) {
  return <span className="inline-block h-2.5 w-2.5 rounded-sm shrink-0" style={{ background: color }} aria-hidden />
}

// ── Tab ──────────────────────────────────────────────────────────────────────

export default function RevenueTab({ agentId }: TabProps) {
  const [econ, setEcon] = useState<AgentEconomicsDetail | null>(null)
  const [outcome, setOutcome] = useState<CostPerOutcome | null>(null)
  const [error, setError] = useState<string | null>(null)
  const request = useRef(0)

  const load = useCallback(async () => {
    const id = ++request.current
    try {
      const [e, o] = await Promise.all([getEconomics(agentId), getCostPerOutcome(agentId).catch(() => null)])
      if (id !== request.current) return
      setEcon(e.data)
      setOutcome(o?.data ?? null)
      setError(null)
    } catch (e) {
      if (id === request.current) setError(errorMessage(e, 'Could not load economics'))
    }
  }, [agentId])

  useEffect(() => {
    setEcon(null)
    setOutcome(null)
    load()
  }, [load])

  if (error && !econ) {
    return (
      <div className="py-8 text-center space-y-2">
        <p className="text-sm text-rose-600">{error}</p>
        <button onClick={load} className="btn-secondary btn-sm">Retry</button>
      </div>
    )
  }
  if (!econ) return <Loading text="Loading economics…" />

  const nothingKnown = !econ.valueDeclared && econ.tokenCostCents == null && econ.hoursSavedMonthly <= 0

  return (
    <div className="space-y-5">
      <PeriodStrip econ={econ} />
      {error && <p className="text-xs text-rose-600">Reload failed: {error}</p>}
      {econ.tokenSource === 'seed' && (
        <Banner tone="gray">
          <span className="font-semibold text-gray-700">Demo data.</span> The token cost comes from sample usage rows
          seeded with the registry, not from this agent's traces.{' '}
          {econ.token.phoenixLinked ? 'Refresh from Phoenix on the Tokenomics tab to replace it.' : 'Link a Phoenix project on the Diagram tab to measure it.'}
        </Banner>
      )}
      {nothingKnown && (
        <Banner tone="gray">
          <span className="font-semibold text-gray-700">Nothing to compare yet.</span> This agent has no declared business
          value and no usage data. Declare its monthly value (and hours saved) on the agent record and link a Phoenix
          project to see value against cost. Hosting cost below uses {econ.infraSource === 'estimate' ? 'the stage estimate' : `the ${econ.infraSource} figure`} until then.
        </Banner>
      )}

      <Headline econ={econ} />
      <CostBreakdown econ={econ} />
      <Trend econ={econ} />
      <FlagList econ={econ} />
      <OutcomePanel econ={econ} outcome={outcome} />
      <InfraPanel agentId={agentId} econ={econ} onChanged={load} />
    </div>
  )
}

function PeriodStrip({ econ }: { econ: AgentEconomicsDetail }) {
  const p = econ.period
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
      <span className="font-medium text-gray-700">{fmtMonth(p.month)}</span>
      <span>· day {p.daysElapsed} of {p.daysInPeriod}</span>
      <span title="Month to date projected to month end, so it compares with the monthly value">· monthly run rate</span>
      <span>· visibility only — nothing here pauses or changes the agent</span>
    </div>
  )
}

// ── Headline ─────────────────────────────────────────────────────────────────

function TokenTile({ econ }: { econ: AgentEconomicsDetail }) {
  const t = econ.token
  if (econ.tokenCostCents != null) {
    return (
      <Tile
        label="Token cost"
        value={fmtCost(econ.tokenCostCents)}
        sub={
          <>
            <SourceBadge source={econ.tokenSource} />
            {t.status === 'no_calls'
              ? <span>no LLM calls read this month</span>
              : <span>{fmtCost(t.monthToDateCents)} so far</span>}
            {t.pricing === 'partial' && <span className="text-amber-700">excludes unpriced {t.unpricedModels.join(', ')}</span>}
          </>
        }
      />
    )
  }
  if (t.pricing === 'missing') {
    return <Tile label="Token cost" muted value="Pricing not configured"
      sub={<><SourceBadge source={econ.tokenSource} /><span>no price for {t.unpricedModels.join(', ') || 'this model'}</span></>} />
  }
  if (t.status === 'awaiting_ingestion') {
    return <Tile label="Token cost" muted value="No usage data yet"
      sub={<span>Phoenix project <span className="font-mono">{t.phoenixProject}</span> not read yet — refresh on the Tokenomics tab</span>} />
  }
  return <Tile label="Token cost" muted value="No usage data" sub={<span>No Phoenix project linked</span>} />
}

function Headline({ econ }: { econ: AgentEconomicsDetail }) {
  const infraNote = econ.infraSource === 'estimate' ? `${econ.stage} stage` : econ.infraSource === 'metered' ? 'Azure run rate' : 'owner figure'
  return (
    <section className="space-y-2">
      <SectionLabel>Value vs cost of ownership (per month)</SectionLabel>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {econ.valueDeclared
          ? <Tile label="Declared value" value={`${fmtCents(econ.valueCents)}/mo`} sub={<span>{econ.valueType || 'Basis not set'}</span>} />
          : <Tile label="Declared value" muted value="Not declared" sub={<span>No monthly value on the agent record</span>} />}
        {econ.hoursSavedMonthly > 0
          ? <Tile label="Realized value" value={`${fmtCents(econ.realizedValueCents)}/mo`}
              sub={<span>{fmtNumber(econ.hoursSavedMonthly)} h saved × ${econ.hourlyRate}/h</span>} />
          : <Tile label="Realized value" muted value="Not declared" sub={<span>No hours saved declared</span>} />}
        <TokenTile econ={econ} />
        <Tile label="Infra cost" value={`${fmtCents(econ.infraCostCents)}/mo`}
          sub={<><SourceBadge source={econ.infraSource} /><span>{infraNote}</span></>} />
        <Tile label="Total cost" value={fmtCost(econ.totalCostCents)}
          sub={<span>{econ.costComplete ? 'token + infra' : 'infra only — token cost unknown'}</span>} />
        {econ.netAvailable
          ? <Tile label="Net" value={fmtSigned(econ.netCents)} accent={econ.netCents >= 0 ? 'text-emerald-700' : 'text-rose-700'}
              sub={<span>declared value − total cost{econ.costComplete ? '' : ' (incomplete)'}</span>} />
          : <Tile label="Net" muted value="—" sub={<span>Value not declared</span>} />}
        {econ.roiPct != null
          ? <Tile label="ROI" value={`${econ.roiPct.toLocaleString()}%`}
              sub={<span>{econ.paybackMonths != null ? `payback ${econ.paybackMonths} mo on ${fmtCents(econ.oneTimeCostCents)} one-time` : '(value − cost) ÷ cost'}</span>} />
          : <Tile label="ROI" muted value="—" sub={<span>{econ.valueDeclared ? 'No cost to compare' : 'Value not declared'}</span>} />}
        {econ.costToValuePct != null
          ? <Tile label="Cost to value" value={`${econ.costToValuePct.toLocaleString()}%`} sub={<span>of declared value spent running it</span>} />
          : <Tile label="Cost to value" muted value="—" sub={<span>Value not declared</span>} />}
      </div>
    </section>
  )
}

// ── Cost breakdown ───────────────────────────────────────────────────────────

function CostBreakdown({ econ }: { econ: AgentEconomicsDetail }) {
  const token = econ.tokenCostCents ?? 0
  const infra = econ.infraCostCents
  const cost = token + infra
  const scale = Math.max(cost, econ.valueDeclared ? econ.valueCents : 0, 1)
  const parts = [
    { key: 'token', label: 'Token cost', cents: token, color: SERIES.token, known: econ.tokenCostCents != null, source: econ.tokenSource },
    { key: 'infra', label: 'Infra cost', cents: infra, color: SERIES.infra, known: true, source: econ.infraSource },
  ]
  return (
    <section className="space-y-2">
      <SectionLabel>Where the money goes</SectionLabel>
      {cost <= 0 ? (
        <p className="text-xs text-gray-400">No cost recorded this month{econ.tokenCostCents == null ? ' (token cost unknown)' : ''}.</p>
      ) : (
        <div className="space-y-1.5">
          <BarRow label="Cost">
            {parts.filter(p => p.cents > 0).map(p => (
              <div key={p.key} className="h-full first:rounded-l last:rounded-r" title={`${p.label}: ${fmtCost(p.cents)}`}
                style={{ width: `${(p.cents / scale) * 100}%`, background: p.color }} />
            ))}
          </BarRow>
          {econ.valueDeclared && (
            <BarRow label="Value">
              <div className="h-full rounded" style={{ width: `${(econ.valueCents / scale) * 100}%`, background: SERIES.value }}
                title={`Declared value: ${fmtCents(econ.valueCents)}`} />
            </BarRow>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-600">
        {parts.map(p => (
          <span key={p.key} className="inline-flex items-center gap-1.5">
            <Swatch color={p.color} />
            {p.label} <span className="font-medium text-gray-900">{p.known ? fmtCost(p.cents) : 'unknown'}</span>
            {cost > 0 && p.known && <span className="text-gray-400">({Math.round((p.cents / cost) * 100)}%)</span>}
            <SourceBadge source={p.source} />
          </span>
        ))}
        {econ.valueDeclared && (
          <span className="inline-flex items-center gap-1.5">
            <Swatch color={SERIES.value} /> Declared value <span className="font-medium text-gray-900">{fmtCents(econ.valueCents)}</span>
          </span>
        )}
      </div>
    </section>
  )
}

function BarRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-10 shrink-0 text-[10px] uppercase text-gray-400">{label}</span>
      <div className="h-3 flex-1 rounded bg-gray-100 overflow-hidden flex gap-[2px]">{children}</div>
    </div>
  )
}

// ── Six-month trend ──────────────────────────────────────────────────────────

function Trend({ econ }: { econ: AgentEconomicsDetail }) {
  const [hover, setHover] = useState<number | null>(null)
  const months = econ.trend
  const known = months.some(m => m.totalCostCents != null || m.valueCents != null)
  // 10% headroom keeps the value line off the chart's top edge.
  const max = 1.1 * Math.max(1, ...months.map(m => Math.max(m.totalCostCents ?? 0, m.valueCents ?? 0)))
  const focus: TrendMonth | undefined = months[hover ?? months.length - 1]

  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SectionLabel>Last 6 months</SectionLabel>
        <div className="flex flex-wrap gap-3 text-[11px] text-gray-500">
          <span className="inline-flex items-center gap-1"><Swatch color={SERIES.token} />Token</span>
          <span className="inline-flex items-center gap-1"><Swatch color={SERIES.infra} />Infra</span>
          <span className="inline-flex items-center gap-1">
            <span className="inline-block w-3 border-t-2" style={{ borderColor: SERIES.value }} aria-hidden />Declared value
          </span>
          <span>* month to date, as run rate</span>
        </div>
      </div>
      {!known ? (
        <p className="text-xs text-gray-400">No monthly history yet.</p>
      ) : (
        <>
          <div className="grid grid-cols-6 gap-2 h-28 items-end" onMouseLeave={() => setHover(null)}>
            {months.map((m, i) => {
              const tokenH = ((m.tokenCostCents ?? 0) / max) * 100
              const infraH = ((m.infraCostCents ?? 0) / max) * 100
              const valueH = m.valueCents != null ? (m.valueCents / max) * 100 : null
              return (
                <button
                  key={m.month}
                  type="button"
                  onMouseEnter={() => setHover(i)}
                  onFocus={() => setHover(i)}
                  aria-label={`${fmtMonth(m.month)}: cost ${fmtCost(m.totalCostCents)}, value ${fmtCents(m.valueCents)}`}
                  className={`relative h-full flex flex-col justify-end items-stretch rounded-sm px-2 ${hover === i ? 'bg-gray-50' : ''}`}
                >
                  {m.totalCostCents == null && <span className="text-[10px] text-gray-300 text-center pb-1">no data</span>}
                  <div className={`flex flex-col justify-end gap-[2px] ${m.partial ? 'opacity-60' : ''}`} style={{ height: `${tokenH + infraH}%` }}>
                    {tokenH > 0 && <div className="rounded-t" style={{ height: `${(tokenH / (tokenH + infraH)) * 100}%`, background: SERIES.token, minHeight: 2 }} />}
                    {infraH > 0 && <div className={tokenH > 0 ? '' : 'rounded-t'} style={{ height: `${(infraH / (tokenH + infraH)) * 100}%`, background: SERIES.infra, minHeight: 2 }} />}
                  </div>
                  {valueH != null && (
                    <div className="absolute left-0.5 right-0.5 border-t-2" style={{ bottom: `${Math.min(valueH, 100)}%`, borderColor: SERIES.value }} />
                  )}
                </button>
              )
            })}
          </div>
          <div className="grid grid-cols-6 gap-2 text-center text-[10px] text-gray-400">
            {months.map(m => <span key={m.month}>{fmtMonth(m.month)}{m.partial ? ' *' : ''}</span>)}
          </div>
          {focus && (
            <p className="text-xs text-gray-600" aria-live="polite">
              <span className="font-medium text-gray-800">{fmtMonth(focus.month)}{focus.partial ? ' (run rate)' : ''}</span>
              {' '}— token {fmtCost(focus.tokenCostCents)}, infra {fmtCents(focus.infraCostCents)}
              {focus.infraSource ? ` (${focus.infraSource})` : ''}, value {fmtCents(focus.valueCents)}
              {focus.netCents != null && <>, net {fmtSigned(focus.netCents)}</>}
              {focus.roiPct != null && <>, ROI {focus.roiPct}%</>}
            </p>
          )}
        </>
      )}
      <TrendTable months={months} />
    </section>
  )
}

function TrendTable({ months }: { months: TrendMonth[] }) {
  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-gray-500 hover:text-gray-700">Table view</summary>
      <div className="overflow-x-auto mt-2">
        <table className="w-full text-left">
          <thead className="text-[10px] uppercase text-gray-400">
            <tr>
              {['Month', 'Token', 'Infra', 'Total', 'Value', 'Net', 'ROI'].map(h => <th key={h} className="py-1 pr-3 font-medium">{h}</th>)}
            </tr>
          </thead>
          <tbody className="text-gray-700">
            {months.map(m => (
              <tr key={m.month} className="border-t border-gray-100">
                <td className="py-1 pr-3 whitespace-nowrap">{fmtMonth(m.month)}{m.partial ? ' (run rate)' : ''}</td>
                <td className="py-1 pr-3">{fmtCost(m.tokenCostCents)}</td>
                <td className="py-1 pr-3 whitespace-nowrap">{fmtCents(m.infraCostCents)}{m.infraSource && <span className="text-gray-400"> · {m.infraSource}</span>}</td>
                <td className="py-1 pr-3">{fmtCost(m.totalCostCents)}</td>
                <td className="py-1 pr-3">{fmtCents(m.valueCents)}</td>
                <td className="py-1 pr-3">{m.netCents == null ? '—' : fmtSigned(m.netCents)}</td>
                <td className="py-1 pr-3">{m.roiPct == null ? '—' : `${m.roiPct}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}

// ── Flags and efficiency ─────────────────────────────────────────────────────

function FlagList({ econ }: { econ: AgentEconomicsDetail }) {
  return (
    <section className="space-y-2">
      <SectionLabel>Financial flags</SectionLabel>
      {econ.stage !== 'Production' ? (
        <p className="text-xs text-gray-400">Financial flags apply to Production agents.</p>
      ) : econ.financialFlags.length === 0 ? (
        <p className="text-xs text-gray-400">No financial flags.</p>
      ) : (
        <ul className="space-y-1.5">
          {econ.financialFlags.map(f => (
            <li key={f.rule_id} className="rounded-lg border border-gray-100 px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full ring-1 ${SEVERITY_PILL[f.severity] || SEVERITY_PILL.LOW}`}>⚠ {f.severity}</span>
                <span className="text-sm font-medium text-gray-800">{f.title}</span>
                {f.source === 'seed' && <SourceBadge source="seed" />}
              </div>
              <p className="text-xs text-gray-500 mt-1">{f.description}</p>
            </li>
          ))}
        </ul>
      )}
      <p className="text-[11px] text-gray-400">Flags are for review only; the registry never stops, pauses or throttles an agent.</p>
    </section>
  )
}

function OutcomePanel({ econ, outcome }: { econ: AgentEconomicsDetail; outcome: CostPerOutcome | null }) {
  const rating = outcome ? RATING[outcome.efficiency_rating] : undefined
  return (
    <section className="space-y-2">
      <SectionLabel>Cost per $1 of declared value</SectionLabel>
      {!outcome ? (
        <p className="text-xs text-gray-400">Unavailable.</p>
      ) : outcome.cost_per_outcome == null ? (
        <p className="text-xs text-gray-400">
          {outcome.efficiency_rating === 'not_declared'
            ? 'Declare a monthly business value to compute this.'
            : 'Token cost is unknown, so the cost per outcome would be understated.'}
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-base font-bold text-gray-900">${outcome.cost_per_outcome.toFixed(4)}</span>
          {rating && <span className={`text-[10px] px-1.5 py-0.5 rounded-full ring-1 ${rating.className}`}>{rating.label}</span>}
          <span className="text-xs text-gray-500">
            {fmtDollarsExact(outcome.total_cost)} per month for {fmtCents(econ.valueCents)} of value
            {rating && <> · {rating.text}</>}
          </span>
        </div>
      )}
      <p className="text-[11px] text-gray-400">
        Bands are an org convention, not an industry standard (McKinsey reports about $3.70 of value per $1 spent on gen AI on average).
      </p>
    </section>
  )
}

function fmtDollarsExact(dollars: number): string {
  return fmtCents(Math.round(dollars * 100))
}

// ── Hosting & infrastructure ─────────────────────────────────────────────────

function InfraPanel({ agentId, econ, onChanged }: { agentId: string; econ: AgentEconomicsDetail; onChanged: () => void }) {
  const [status, setStatus] = useState<InfraCostStatus | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)

  const loadStatus = useCallback(() => {
    getInfraCostStatus()
      .then(r => { setStatus(r.data); setStatusError(null) })
      .catch(e => setStatusError(errorMessage(e, 'Could not load the collector status')))
  }, [])

  useEffect(() => { loadStatus() }, [loadStatus])

  return (
    <section className="rounded-lg border border-gray-100 p-4 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-gray-900">Hosting &amp; infrastructure</h3>
        <span className="text-[11px] text-gray-400">Used: metered (Azure) › declared by owner › stage estimate</span>
      </div>
      <p className="text-xs text-gray-600 flex flex-wrap items-center gap-1.5">
        This month: <span className="font-semibold text-gray-900">{fmtCents(econ.infraCostCents)}/mo</span>
        <SourceBadge source={econ.infraSource} />
        {econ.infraSource === 'metered' && econ.infra.meteredThrough && (
          <span className="text-gray-400">({fmtCents(econ.infra.meteredMonthToDateCents)} through {econ.infra.meteredThrough})</span>
        )}
        {econ.infraSource === 'estimate' && <span className="text-gray-400">flat {econ.stage} estimate — declare or meter the real cost</span>}
      </p>
      <CollectorStatus agentId={agentId} status={status} error={statusError} onCollected={() => { loadStatus(); onChanged() }} />
      {econ.infra.byResource.length > 0 && <MeteredResources econ={econ} />}
      <DeclaredInfraForm agentId={agentId} stage={econ.stage} estimateCents={econ.infra.estimateCents} onSaved={onChanged} />
      <ResourceLinks agentId={agentId} tagKey={status?.tagKey || 'agent-id'} />
    </section>
  )
}

function CollectorStatus({ agentId, status, error, onCollected }: {
  agentId: string
  status: InfraCostStatus | null
  error: string | null
  onCollected: () => void
}) {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<(JobRunSummary & { reason?: string }) | null>(null)
  const [runError, setRunError] = useState<string | null>(null)

  if (error) return <Banner tone="rose">{error}</Banner>
  if (!status) return <p className="text-xs text-gray-400">Loading collector status…</p>

  if (!status.configured) {
    return (
      <Banner tone="gray">
        <p><span className="font-semibold text-gray-700">Metered cost (Azure Cost Management): not configured.</span> Until it is,
          infra cost is the owner's declared figure, else the stage estimate.</p>
        <ol className="list-decimal ml-4 mt-1.5 space-y-0.5 break-words">
          {status.setup.map(s => <li key={s}>{s}</li>)}
        </ol>
        {status.missing.length > 0 && (
          <p className="mt-1.5 break-all">Missing: {status.missing.map(m => <code key={m} className="mr-1.5 font-mono text-gray-700">{m}</code>)}</p>
        )}
      </Banner>
    )
  }

  const collect = async () => {
    setRunning(true)
    setRunError(null)
    try {
      const r = await collectInfraCosts(agentId)
      setResult(r.data)
      onCollected()
    } catch (e) {
      setRunError(errorMessage(e, 'Collection failed'))
    } finally {
      setRunning(false)
    }
  }

  const last = result || status.lastRun
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-gray-600">
        <span>
          Azure Cost Management · scope <span className="font-mono text-gray-700">{status.scope}</span> · tag{' '}
          <span className="font-mono text-gray-700">{status.tagKey}</span>
        </span>
        <button onClick={collect} disabled={running} className="btn-secondary btn-sm"
          title="Read the last 7 days of actual cost for this agent (admin)">
          {running ? 'Collecting…' : 'Collect now'}
        </button>
      </div>
      {runError && <Banner tone="rose">{runError}</Banner>}
      {last ? (
        <p className="text-xs text-gray-500">
          Last run {fmtWhen(last.finishedAt || last.startedAt)}: {RUN_STATUS_TEXT[last.status] || last.status}
          {typeof last.summary?.reason === 'string' && <> — {last.summary.reason}</>}
          {typeof last.summary?.unallocated_cents === 'number' && last.summary.unallocated_cents > 0 &&
            <> · {fmtCents(last.summary.unallocated_cents)} unallocated</>}
        </p>
      ) : (
        <p className="text-xs text-gray-400">Not collected yet. The daily job reads cost once a day; Azure data lags 8–72 hours.</p>
      )}
    </div>
  )
}

function MeteredResources({ econ }: { econ: AgentEconomicsDetail }) {
  return (
    <div className="space-y-1">
      <SectionLabel>Metered this month, by resource</SectionLabel>
      <ul className="divide-y divide-gray-100 text-xs">
        {econ.infra.byResource.map(r => (
          <li key={r.resourceId} className="flex items-center justify-between gap-3 py-1">
            <span className="min-w-0 truncate font-mono text-gray-600" title={r.resourceId}>{r.resourceId.split('/').slice(-1)[0]}</span>
            <span className="shrink-0 text-gray-400">{r.serviceName || ''} · {r.allocation === 'link' ? 'linked' : 'tagged'}</span>
            <span className="shrink-0 font-medium text-gray-800">{fmtCents(r.cents)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ── Declared hosting cost ────────────────────────────────────────────────────

interface ComponentDraft { name: string; dollars: string; recurring: boolean }

function DeclaredInfraForm({ agentId, stage, estimateCents, onSaved }: {
  agentId: string
  stage: string
  estimateCents: number
  onSaved: () => void
}) {
  const [profile, setProfile] = useState<InfraProfile | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [platform, setPlatform] = useState('')
  const [resourceGroup, setResourceGroup] = useState('')
  const [monthly, setMonthly] = useState('')
  const [effectiveFrom, setEffectiveFrom] = useState('')
  const [components, setComponents] = useState<ComponentDraft[]>([])
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ tone: 'teal' | 'rose'; text: string } | null>(null)

  const fill = (p: InfraProfile) => {
    setProfile(p)
    setPlatform(p.platform || '')
    setResourceGroup(p.resourceGroup || '')
    setMonthly(p.declared && p.monthlyCostCents ? String(p.monthlyCostCents / 100) : '')
    setEffectiveFrom(p.effectiveFrom || '')
    setComponents(p.components.map(c => ({ name: c.name, dollars: c.costCents != null ? String(c.costCents / 100) : '', recurring: c.recurring })))
  }

  useEffect(() => {
    setProfile(null)
    getInfraProfile(agentId).then(r => { fill(r.data); setLoadError(null) }).catch(e => setLoadError(errorMessage(e, 'Could not load the hosting profile')))
  }, [agentId])

  const toCents = (text: string): number | null | 'invalid' => {
    if (!text.trim()) return null
    const n = Number(text)
    return Number.isFinite(n) && n >= 0 ? Math.round(n * 100) : 'invalid'
  }

  const save = async () => {
    const cents = toCents(monthly)
    const parts: InfraComponent[] = []
    for (const c of components) {
      if (!c.name.trim()) continue
      const cc = toCents(c.dollars)
      if (cc === 'invalid') return setMessage({ tone: 'rose', text: `"${c.name}": enter a cost of 0 or more.` })
      parts.push({ name: c.name.trim(), costCents: cc, recurring: c.recurring })
    }
    if (cents === 'invalid') return setMessage({ tone: 'rose', text: 'Monthly cost must be a number of 0 or more.' })
    setSaving(true)
    setMessage(null)
    try {
      const r = await saveInfraProfile(agentId, {
        platform: platform.trim() || null, resourceGroup: resourceGroup.trim() || null,
        monthlyCostCents: cents, components: parts, effectiveFrom: effectiveFrom || null,
      })
      fill(r.data)
      setMessage({ tone: 'teal', text: r.data.declared ? 'Saved. The declared cost is used when no metered cost exists.' : 'Saved. No monthly cost declared, so the stage estimate still applies.' })
      onSaved()
    } catch (e) {
      setMessage({ tone: 'rose', text: errorMessage(e, 'Save failed') })
    } finally {
      setSaving(false)
    }
  }

  const setComponent = (i: number, patch: Partial<ComponentDraft>) =>
    setComponents(cs => cs.map((c, j) => (j === i ? { ...c, ...patch } : c)))

  if (loadError) return <Banner tone="rose">{loadError}</Banner>
  if (!profile) return <p className="text-xs text-gray-400">Loading hosting profile…</p>

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SectionLabel>Declared by owner</SectionLabel>
        <span className="text-[11px] text-gray-400">
          {profile.declared
            ? `${fmtCents(profile.monthlyCostCents)}/mo declared${profile.updatedBy ? ` by ${profile.updatedBy}` : ''}`
            : `Not declared — ${stage} estimate ${fmtCents(estimateCents)}/mo applies`}
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
        <label className="text-xs text-gray-500 space-y-1">
          <span>Platform</span>
          <input className="input w-full" value={platform} onChange={e => setPlatform(e.target.value)} placeholder="Azure Container Apps" maxLength={100} />
        </label>
        <label className="text-xs text-gray-500 space-y-1">
          <span>Resource group</span>
          <input className="input w-full" value={resourceGroup} onChange={e => setResourceGroup(e.target.value)} placeholder="rg-onboarding" maxLength={255} />
        </label>
        <label className="text-xs text-gray-500 space-y-1">
          <span>Monthly cost ($)</span>
          <input className="input w-full" type="number" min={0} step="0.01" value={monthly} onChange={e => setMonthly(e.target.value)} placeholder="blank = not declared" />
        </label>
        <label className="text-xs text-gray-500 space-y-1">
          <span>Effective from</span>
          <input className="input w-full" type="date" value={effectiveFrom} onChange={e => setEffectiveFrom(e.target.value)} />
        </label>
      </div>
      <div className="space-y-1">
        <span className="text-xs text-gray-500">Components</span>
        {components.length === 0 && <p className="text-[11px] text-gray-400">None listed.</p>}
        {components.map((c, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <input className="input flex-1 min-w-[10rem]" value={c.name} onChange={e => setComponent(i, { name: e.target.value })} placeholder="Component (e.g. Cosmos DB)" aria-label="Component name" maxLength={200} />
            <input className="input w-28" type="number" min={0} step="0.01" value={c.dollars} onChange={e => setComponent(i, { dollars: e.target.value })} placeholder="$" aria-label="Component cost in dollars" />
            <label className="text-xs text-gray-500 inline-flex items-center gap-1">
              <input type="checkbox" checked={!c.recurring} onChange={e => setComponent(i, { recurring: !e.target.checked })} /> one-time
            </label>
            <button type="button" className="text-xs text-gray-400 hover:text-rose-600" onClick={() => setComponents(cs => cs.filter((_, j) => j !== i))}>Remove</button>
          </div>
        ))}
        <button type="button" className="text-xs text-teal-700 hover:text-teal-800" onClick={() => setComponents(cs => [...cs, { name: '', dollars: '', recurring: true }])}>+ Add component</button>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={save} disabled={saving} className="btn-primary btn-sm">{saving ? 'Saving…' : 'Save hosting cost'}</button>
        <span className="text-[11px] text-gray-400">One-time components give the payback period; recurring ones are informational — the monthly cost is what counts.</span>
      </div>
      {message && <Banner tone={message.tone}>{message.text}</Banner>}
    </div>
  )
}

// ── Azure resource links ─────────────────────────────────────────────────────

const LINK_KIND: Record<string, string> = { subscription: 'Subscription', resource_group: 'Resource group', resource: 'Resource' }

function ResourceLinks({ agentId, tagKey }: { agentId: string; tagKey: string }) {
  const [links, setLinks] = useState<ResourceLink[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [resourceId, setResourceId] = useState('')
  const [share, setShare] = useState('100')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ tone: 'amber' | 'rose'; text: string } | null>(null)

  const load = useCallback(() => {
    getResourceLinks(agentId).then(r => { setLinks(r.data.links); setLoadError(null) })
      .catch(e => setLoadError(errorMessage(e, 'Could not load resource links')))
  }, [agentId])

  useEffect(() => { setLinks(null); load() }, [load])

  const add = async () => {
    const pct = Number(share)
    if (!resourceId.trim().toLowerCase().startsWith('/subscriptions/')) {
      return setMessage({ tone: 'rose', text: 'Paste a full Azure resource id starting with /subscriptions/.' })
    }
    if (!Number.isInteger(pct) || pct < 1 || pct > 100) return setMessage({ tone: 'rose', text: 'Share must be a whole number from 1 to 100.' })
    setBusy(true)
    setMessage(null)
    try {
      const r = await addResourceLink(agentId, resourceId.trim(), pct)
      setResourceId('')
      setShare('100')
      if (r.data.warning) setMessage({ tone: 'amber', text: r.data.warning })
      load()
    } catch (e) {
      setMessage({ tone: 'rose', text: errorMessage(e, 'Could not add the link') })
    } finally {
      setBusy(false)
    }
  }

  const remove = async (link: ResourceLink) => {
    if (!window.confirm(`Remove the link to ${link.resourceId}?`)) return
    setBusy(true)
    try {
      await deleteResourceLink(agentId, link.id)
      setMessage(null)
      load()
    } catch (e) {
      setMessage({ tone: 'rose', text: errorMessage(e, 'Could not remove the link') })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SectionLabel>Linked Azure resources</SectionLabel>
        <span className="text-[11px] text-gray-400">
          Resources tagged <span className="font-mono">{tagKey}={agentId}</span> are found without a link; link shared ones with a share %.
        </span>
      </div>
      {loadError && <Banner tone="rose">{loadError}</Banner>}
      {!links && !loadError && <p className="text-xs text-gray-400">Loading…</p>}
      {links && links.length === 0 && <p className="text-xs text-gray-400">No linked resources.</p>}
      {links && links.length > 0 && (
        <ul className="divide-y divide-gray-100 text-xs">
          {links.map(l => (
            <li key={l.id} className="flex flex-wrap items-center gap-2 py-1.5">
              <span className="text-[10px] px-1.5 py-0.5 rounded-full ring-1 bg-gray-50 text-gray-600 ring-gray-200">{LINK_KIND[l.kind] || l.kind}</span>
              <span className="min-w-0 flex-1 truncate font-mono text-gray-700" title={l.resourceId}>{l.resourceId}</span>
              <span className="text-gray-800 font-medium">{l.sharePct}%</span>
              {l.totalClaimedPct > 100 && (
                <span className="text-amber-700" title="Shares are scaled down so no more than the real cost is allocated">⚠ {l.totalClaimedPct}% claimed in total</span>
              )}
              <button type="button" disabled={busy} className="text-gray-400 hover:text-rose-600" onClick={() => remove(l)}>Remove</button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <input className="input flex-1 min-w-[16rem] font-mono text-xs" value={resourceId} onChange={e => setResourceId(e.target.value)}
          placeholder="/subscriptions/<id>/resourceGroups/<rg>[/providers/…]" aria-label="Azure resource id" maxLength={500} />
        <input className="input w-20" type="number" min={1} max={100} step={1} value={share} onChange={e => setShare(e.target.value)} aria-label="Share percent" />
        <span className="text-xs text-gray-400">%</span>
        <button onClick={add} disabled={busy || !resourceId.trim()} className="btn-secondary btn-sm">Link resource</button>
      </div>
      {message && <Banner tone={message.tone}>{message.text}</Banner>}
    </div>
  )
}
