import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import InfoTip from '../../components/InfoTip'
import MonthPicker, { isMonthKey, monthLabel } from '../../components/MonthPicker'
import { getCostPerOutcome, getEconomics, type AgentEconomicsDetail, type CostPerOutcome, type TrendMonth } from '../../services/ops/economics'
import { Loading, SectionLabel, SEVERITY_PILL, SourceBadge, fmtCents, fmtNumber, type TabProps, useReloadOn } from './shared'
import ValuePanel from './ValuePanel'
import { MeasuredOutcomes } from './ValueExtras'
import { Banner, SERIES, Swatch, Tile, errorMessage, fmtCost, fmtDollarsExact, fmtMonth, fmtRoi, fmtSigned, fmtSmallPct } from './costUi'

// Business Value: what the agent is worth against what it costs, per month. One total cost figure here,
// and the token and hosting detail on the Tokenomics tab.

const RATING: Record<string, { label: string; className: string; text: string }> = {
  efficient: { label: 'Efficient', className: 'bg-teal-50 text-teal-700 ring-teal-200', text: 'under $0.10 per $1 of value' },
  moderate: { label: 'Moderate', className: 'bg-sky-50 text-sky-700 ring-sky-200', text: '$0.10–$0.27 per $1 of value' },
  below_average: { label: 'Below average', className: 'bg-amber-50 text-amber-700 ring-amber-200', text: '$0.27–$1.00 per $1 of value' },
  inefficient: { label: 'Costs more than its value', className: 'bg-rose-50 text-rose-700 ring-rose-200', text: '$1.00 or more per $1 of value' },
}

// ── Tab ──────────────────────────────────────────────────────────────────────

export default function RevenueTab({ agentId, dataVersion }: TabProps) {
  const [econ, setEcon] = useState<AgentEconomicsDetail | null>(null)
  const [outcome, setOutcome] = useState<CostPerOutcome | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [period, setPeriod] = useState<string>('current')   // 'current' for this month, or YYYY-MM
  const month = isMonthKey(period) ? period : null
  const [loading, setLoading] = useState(false)
  const request = useRef(0)

  const load = useCallback(async () => {
    const id = ++request.current
    setLoading(true)
    try {
      const [e, o] = await Promise.all([getEconomics(agentId, month), month ? Promise.resolve(null) : getCostPerOutcome(agentId).catch(() => null)])
      if (id !== request.current) return
      setEcon(e.data)
      setOutcome(o?.data ?? null)
      setError(null)
    } catch (e) {
      if (id === request.current) setError(errorMessage(e, 'Could not load economics'))
    } finally {
      if (id === request.current) setLoading(false)
    }
  }, [agentId, month])

  // A different agent starts empty. A different period keeps the figures on screen until the new ones arrive,
  // so the page does not blank out and the period control keeps its place.
  useEffect(() => {
    setEcon(null)
    setOutcome(null)
  }, [agentId])
  useEffect(() => { load() }, [load])
  useReloadOn(dataVersion, load)

  if (error && !econ) {
    return (
      <div className="py-8 text-center space-y-2">
        <p className="text-sm text-rose-600">{error}</p>
        <button onClick={load} className="btn-secondary btn-sm">Retry</button>
      </div>
    )
  }
  if (!econ) return <Loading text="Loading economics…" />

  const nothingKnown = !econ.valueDeclared && econ.totalCostCents <= 0 && econ.hoursSavedMonthly <= 0

  return (
    <div className="space-y-5">
      <PeriodStrip econ={econ} period={period} onPeriod={setPeriod} />
      {error && <p className="text-xs text-rose-600">Reload failed: {error}</p>}
      {nothingKnown && (
        <Banner tone="gray">
          <span className="font-semibold text-slate-700">Nothing to compare yet.</span> This agent has no declared value and no cost
          figures. Declare the value below, under Value. Token and hosting cost are on the <Link to={`/agents/${agentId}?tab=tokenomics`} className="text-zen-700 hover:underline">Tokenomics tab</Link>.
        </Banner>
      )}

      <div className={`transition-opacity duration-150 ${loading ? 'opacity-60' : ''}`} aria-busy={loading}><Headline agentId={agentId} econ={econ} /></div>
      <ValuePanel agentId={agentId} onChanged={load} />
      <div className={`transition-opacity duration-150 ${loading ? 'opacity-60' : ''}`}><Trend econ={econ} /></div>
      <FlagList econ={econ} />
      {!month && <OutcomePanel econ={econ} outcome={outcome} />}
      <MeasuredOutcomes agentId={agentId} />
    </div>
  )
}

function PeriodStrip({ econ, period, onPeriod }: { econ: AgentEconomicsDetail; period: string; onPeriod: (p: string) => void }) {
  const p = econ.period
  const whole = p.daysElapsed >= p.daysInPeriod
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-600">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-slate-700">{monthLabel(p.month)}</span>
        <span>· {whole ? `the whole month, ${p.daysInPeriod} days` : `day ${p.daysElapsed} of ${p.daysInPeriod}, cost projected to the full month`}</span>
        <span>· for information only: nothing here pauses or changes the agent</span>
      </div>
      <MonthPicker value={period} onChange={onPeriod} presets={[{ key: 'current', label: 'This month' }]} testId="value-month" />
    </div>
  )
}

// ── Headline ─────────────────────────────────────────────────────────────────

function Headline({ agentId, econ }: { agentId: string; econ: AgentEconomicsDetail }) {
  return (
    <section className="space-y-2">
      <SectionLabel>Value against cost (per month)</SectionLabel>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
        {econ.valueDeclared
          ? <Tile label={econ.valueState === 'attested' || econ.valueState === 'adjusted' ? 'Attested value' : 'Declared value'} value={`${fmtCents(econ.valueCents)}/mo`}
              sub={<span>{econ.valueStateLabel}{econ.valueMethodLabel ? ` · ${econ.valueMethodLabel}` : ''}</span>} />
          : <Tile label="Declared value" muted value="Not declared" sub={<span>Declare it below, under Value</span>} />}
        {econ.hoursSavedMonthly > 0
          ? <Tile label="Value of hours saved" value={`${fmtCents(econ.realizedValueCents)}/mo`}
              sub={<span>{fmtNumber(econ.hoursSavedMonthly)} h saved × ${econ.hourlyRate}/h</span>} />
          : <Tile label="Value of hours saved" muted value="Not declared" sub={<span>No hours saved declared</span>} />}
        <Tile label="Total cost" value={fmtCost(econ.totalCostCents)}
          sub={<span>{econ.costComplete ? 'tokens + hosting' : 'hosting only, token cost unknown'} · <Link to={`/agents/${agentId}?tab=tokenomics`} className="text-zen-700 hover:underline" data-testid="to-tokenomics">see the breakdown on Tokenomics</Link></span>} />
        {econ.netAvailable
          ? <Tile label="Net" value={fmtSigned(econ.netCents)} accent={econ.netCents >= 0 ? 'text-emerald-700' : 'text-rose-700'}
              sub={<span>value − total cost{econ.costComplete ? '' : ' (incomplete)'}</span>} />
          : <Tile label="Net" muted value="—" sub={<span>Value not declared</span>} />}
        {econ.roiPct != null
          ? <Tile label="ROI" value={fmtRoi(econ.roiPct)}
              sub={<span>{econ.paybackMonths != null ? `payback ${econ.paybackMonths} mo on ${fmtCents(econ.oneTimeCostCents)} one-time`
                : Math.abs(econ.roiPct) >= 1000 ? `value vs cost · ROI ${econ.roiPct.toLocaleString()}%` : '(value − cost) ÷ cost'}</span>} />
          : <Tile label="ROI" muted value="—" sub={<span>{econ.valueDeclared ? 'No cost to compare' : 'Value not declared'}</span>} />}
        {econ.costToValuePct != null
          ? <Tile label="Cost to value" value={fmtSmallPct(econ.costToValuePct, econ.totalCostCents > 0)} sub={<span>of the value spent running it</span>} />
          : <Tile label="Cost to value" muted value="—" sub={<span>Value not declared</span>} />}
      </div>
    </section>
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
        <SectionLabel>Six months up to {fmtMonth(months[months.length - 1]?.month || '')}</SectionLabel>
        <div className="flex flex-wrap gap-3 text-[12px] text-slate-600">
          <span className="inline-flex items-center gap-1"><Swatch color={SERIES.infra} />Total cost (tokens + hosting)</span>
          <span className="inline-flex items-center gap-1">
            <span className="inline-block w-3 border-t-2" style={{ borderColor: SERIES.value }} aria-hidden />Value used
          </span>
          <span>* month to date, as run rate</span>
        </div>
      </div>
      {!known ? (
        <p className="text-xs text-slate-500">No monthly history yet.</p>
      ) : (
        <>
          <div className="grid grid-cols-6 gap-2 h-28 items-end" onMouseLeave={() => setHover(null)}>
            {months.map((m, i) => {
              const costH = ((m.totalCostCents ?? 0) / max) * 100
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
                  {m.totalCostCents == null && <span className="text-[12px] text-slate-400 text-center pb-1">no data</span>}
                  <div className={`flex flex-col justify-end ${m.partial ? 'opacity-60' : ''}`} style={{ height: `${costH}%` }}>
                    {costH > 0 && <div className="rounded-t h-full" style={{ background: SERIES.infra, minHeight: 2 }} />}
                  </div>
                  {valueH != null && (
                    <div className="absolute left-0.5 right-0.5 border-t-2" style={{ bottom: `${Math.min(valueH, 100)}%`, borderColor: SERIES.value }} />
                  )}
                </button>
              )
            })}
          </div>
          <div className="grid grid-cols-6 gap-2 text-center text-[12px] text-slate-500">
            {months.map(m => <span key={m.month}>{fmtMonth(m.month)}{m.partial ? ' *' : ''}</span>)}
          </div>
          {focus && (
            <p className="text-xs text-slate-700" aria-live="polite">
              <span className="font-medium text-slate-800">{fmtMonth(focus.month)}{focus.partial ? ' (run rate)' : ''}</span>
              {' '}— cost {fmtCost(focus.totalCostCents)}, value {fmtCents(focus.valueCents)}
              {focus.netCents != null && <>, net {fmtSigned(focus.netCents)}</>}
              {focus.roiPct != null && <>, ROI {fmtRoi(focus.roiPct)}</>}
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
      <summary className="cursor-pointer text-slate-600 hover:text-slate-700">Table view</summary>
      <div className="overflow-x-auto mt-2">
        <table className="w-full text-left">
          <thead className="text-[12px] uppercase text-slate-500">
            <tr>
              {['Month', 'Total cost', 'Value', 'Net', 'ROI'].map(h => <th key={h} className="py-1 pr-3 font-medium">{h}{h === 'ROI' && <> <InfoTip term="return_on_cost" /></>}</th>)}
            </tr>
          </thead>
          <tbody className="text-slate-700">
            {months.map(m => (
              <tr key={m.month} className="border-t border-gray-100">
                <td className="py-1 pr-3 whitespace-nowrap">{fmtMonth(m.month)}{m.partial ? ' (run rate)' : ''}</td>
                <td className="py-1 pr-3">{fmtCost(m.totalCostCents)}</td>
                <td className="py-1 pr-3">{fmtCents(m.valueCents)}</td>
                <td className="py-1 pr-3">{m.netCents == null ? '—' : fmtSigned(m.netCents)}</td>
                <td className="py-1 pr-3">{m.roiPct == null ? '—' : fmtRoi(m.roiPct)}</td>
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
        <p className="text-xs text-slate-500">Financial flags apply to Production agents.</p>
      ) : econ.financialFlags.length === 0 ? (
        <p className="text-xs text-slate-500">No financial flags.</p>
      ) : (
        <ul className="space-y-1.5">
          {econ.financialFlags.map(f => (
            <li key={f.rule_id} className="rounded-lg border border-gray-100 px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`text-[12px] px-1.5 py-0.5 rounded-full ring-1 ${SEVERITY_PILL[f.severity] || SEVERITY_PILL.LOW}`}>⚠ {f.severity}</span>
                <span className="text-sm font-medium text-slate-800">{f.title}</span>
                {f.source === 'seed' && <SourceBadge source="seed" />}
              </div>
              <p className="text-xs text-slate-600 mt-1">{f.description}</p>
            </li>
          ))}
        </ul>
      )}
      <p className="text-[12px] text-slate-500">Flags are for review only; the registry never stops, pauses or throttles an agent.</p>
    </section>
  )
}

function OutcomePanel({ econ, outcome }: { econ: AgentEconomicsDetail; outcome: CostPerOutcome | null }) {
  const rating = outcome ? RATING[outcome.efficiency_rating] : undefined
  return (
    <section className="space-y-2">
      <SectionLabel tip="declared_value">Cost per $1 of value</SectionLabel>
      {!outcome ? (
        <p className="text-xs text-slate-500">Could not load the cost per $1 of value.</p>
      ) : outcome.cost_per_outcome == null ? (
        <p className="text-xs text-slate-500">
          {outcome.efficiency_rating === 'not_declared'
            ? 'Declare a monthly business value to compute this.'
            : 'Token cost is unknown, so this figure would be understated.'}
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-base font-bold text-slate-900">${outcome.cost_per_outcome.toFixed(4)}</span>
          {rating && <span className={`text-[12px] px-1.5 py-0.5 rounded-full ring-1 ${rating.className}`}>{rating.label}</span>}
          <span className="text-xs text-slate-600">
            {fmtDollarsExact(outcome.total_cost)} per month for {fmtCents(econ.valueCents)} of value
            {rating && <> · {rating.text}</>}
          </span>
        </div>
      )}
      <p className="text-[12px] text-slate-500">
        Bands are an org convention, not an industry standard (McKinsey reports about $3.70 of value per $1 spent on gen AI on average).
      </p>
    </section>
  )
}

