import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  getTokenomics,
  refreshUsage,
  resolveCostAnomaly,
  updateBudget,
  type BudgetView,
  type CostAnomaly,
  type DailyUsage,
  type Tokenomics,
  type UsageRefreshResult,
} from '../../services/ops/tokenomics'
import { Loading, MiniStat, SectionLabel, SEVERITY_PILL, SourceBadge, fmtNumber, type TabProps } from './shared'

const WINDOWS = [30, 90] as const

// Chart palette: validated categorical slots 1-3 (blue, aqua, orange) for the
// token stack; the cost line is its own panel, so it keeps the app's teal.
const SERIES = {
  input: '#2a78d6',
  cached: '#1baf7a',
  output: '#eb6834',
  cost: '#0f766e',
  spike: '#e34948',
}

const USAGE_STATUS_TEXT: Record<string, string> = {
  unreachable: 'Phoenix could not be reached (VPN down or host unreachable).',
  auth_failed: 'Phoenix rejected the API key.',
  not_configured: 'No Phoenix endpoint is configured.',
  partial: 'Phoenix returned only part of the window.',
  error: 'Reading Phoenix failed.',
  skipped: 'Nothing to read.',
}

const BUDGET_STATE: Record<string, { label: string; icon: string; text: string; bar: string }> = {
  on_track: { label: 'On track', icon: '✓', text: 'text-teal-700', bar: 'bg-teal-500' },
  at_threshold: { label: 'Alert threshold reached', icon: '⚠', text: 'text-amber-700', bar: 'bg-amber-500' },
  over_budget: { label: 'Over budget', icon: '⚠', text: 'text-rose-700', bar: 'bg-rose-500' },
}

const ANOMALY_LABEL: Record<string, string> = {
  spend_spike: 'Spend spike',
  budget_threshold: 'Budget alert threshold',
  over_budget: 'Over budget',
  cost_per_call_jump: 'Cost per call jump',
  unpriced_model: 'Unpriced model',
  undeclared_model: 'Undeclared model',
  error_burn: 'Error burn',
}

// ── Formatting ───────────────────────────────────────────────────────────────

function errorMessage(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d: any) => d.msg || String(d)).join('; ')
  return e?.message || fallback
}

// Token costs are often fractions of a cent, so small amounts keep 3 significant digits.
function fmtCost(cents: number | null | undefined): string {
  if (cents == null) return '—'
  const n = cents / 100
  const abs = Math.abs(n)
  if (abs === 0) return '$0.00'
  if (abs >= 1000) return '$' + (n / 1000).toFixed(1) + 'K'
  if (abs >= 1) return '$' + n.toFixed(2)
  if (abs < 0.000001) return '<$0.000001'
  return '$' + Number(n.toPrecision(3)).toString()
}

function fmtCompact(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(n >= 10_000 ? 0 : 1) + 'K'
  return String(Math.round(n))
}

function utcDay(date: string): Date {
  return new Date(date + 'T00:00:00Z')
}

function fmtDay(date: string, withYear = false): string {
  return utcDay(date).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', timeZone: 'UTC', ...(withYear ? { year: 'numeric' } : {}),
  })
}

function fmtAgo(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} h ago`
  return `${Math.floor(seconds / 86_400)} d ago`
}

function fmtTime(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : ''
}

function niceCeil(value: number): number {
  if (value <= 0) return 1
  const pow = 10 ** Math.floor(Math.log10(value))
  for (const m of [1, 2, 2.5, 5, 10]) if (m * pow >= value) return m * pow
  return 10 * pow
}

function describeAnomaly(a: CostAnomaly): string {
  const d = a.details || {}
  switch (a.type) {
    case 'spend_spike':
      return `Spend on ${d.date ? fmtDay(d.date) : 'a recent day'} was ${fmtCost(d.cost_cents)} against a typical ` +
        `${fmtCost(d.baseline_cents)} (+${d.impact_pct}%).`
    case 'budget_threshold':
      return `Spend this period reached ${d.used_pct}% of the budget (alert at ${d.alert_pct}%).`
    case 'over_budget':
      return `Spend this period is ${d.used_pct}% of the budget.`
    case 'cost_per_call_jump':
      return `Cost per call over the last 7 days is ${d.ratio}× the 30 days before ` +
        `(${fmtCost(d.recent_cost_per_call_cents)} vs ${fmtCost(d.prior_cost_per_call_cents)}).`
    case 'unpriced_model':
      return `No price for ${(d.models || []).join(', ')}; its tokens are not counted in cost.`
    case 'undeclared_model':
      return `Traces use ${(d.models || []).join(', ')} but the declared model is ${d.declared_model || 'not set'}.`
    case 'error_burn':
      return `${d.error_rate_pct}% of ${d.calls} LLM calls failed on ${d.date ? fmtDay(d.date) : 'a recent day'}.`
    default:
      return JSON.stringify(d)
  }
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function TokenomicsTab({ agentId }: TabProps) {
  const [days, setDays] = useState<number>(30)
  const [data, setData] = useState<Tokenomics | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshResult, setRefreshResult] = useState<UsageRefreshResult | null>(null)
  const [refreshError, setRefreshError] = useState<string | null>(null)
  const request = useRef(0)

  const load = useCallback(async () => {
    const id = ++request.current
    try {
      const res = await getTokenomics(agentId, days)
      if (id !== request.current) return
      setData(res.data)
      setError(null)
    } catch (e) {
      if (id === request.current) setError(errorMessage(e, 'Could not load tokenomics'))
    }
  }, [agentId, days])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    setData(null)
    setRefreshResult(null)
    setRefreshError(null)
  }, [agentId])

  const refresh = async () => {
    setRefreshing(true)
    setRefreshError(null)
    try {
      const res = await refreshUsage(agentId)
      setRefreshResult(res.data)
      await load()
    } catch (e) {
      setRefreshError(errorMessage(e, 'Refresh failed'))
    } finally {
      setRefreshing(false)
    }
  }

  if (error && !data) {
    return (
      <div className="py-8 text-center space-y-2">
        <p className="text-sm text-rose-600">{error}</p>
        <button onClick={load} className="btn-secondary btn-sm">Retry</button>
      </div>
    )
  }
  if (!data) return <Loading text="Loading tokenomics…" />

  const hasData = data.source !== 'none'

  return (
    <div className="space-y-5">
      <StatusStrip data={data} refreshing={refreshing} onRefresh={refresh} />
      {error && <p className="text-xs text-rose-600">Reload failed: {error}</p>}
      <RefreshNotice data={data} result={refreshResult} error={refreshError} refreshing={refreshing} />
      {data.source === 'seed' && <DemoNotice linked={data.linked} />}
      {!hasData && <EmptyState data={data} />}

      {hasData && (
        <>
          <Headline data={data} />
          <section className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <SectionLabel>Daily usage — last {data.days} days (UTC)</SectionLabel>
              <div className="flex gap-1" role="group" aria-label="Chart window">
                {WINDOWS.map(w => (
                  <button
                    key={w}
                    onClick={() => setDays(w)}
                    aria-pressed={days === w}
                    className={`px-2 py-0.5 text-xs rounded-md border transition-colors ${
                      days === w ? 'border-teal-600 bg-teal-50 text-teal-700' : 'border-gray-200 text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    {w} days
                  </button>
                ))}
              </div>
            </div>
            <DailyUsageChart daily={data.daily} />
          </section>
          <ModelTable data={data} />
          <ForecastPanel data={data} />
        </>
      )}

      <AnomalyList data={data} onChanged={load} />
      <BudgetEditor agentId={agentId} budget={data.budget} onSaved={load} />
    </div>
  )
}

// ── Source, refresh and empty states ─────────────────────────────────────────

function StatusStrip({ data, refreshing, onRefresh }: { data: Tokenomics; refreshing: boolean; onRefresh: () => void }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
        <SourceBadge source={data.source} />
        {data.phoenixProject
          ? <span>Phoenix project <span className="font-mono text-gray-700">{data.phoenixProject}</span></span>
          : <span>No Phoenix project linked</span>}
        {data.source === 'phoenix' && (
          <span title={fmtTime(data.lastIngestedAt)}>· Updated {fmtAgo(data.lastIngestedAt)}</span>
        )}
      </div>
      <button
        onClick={onRefresh}
        disabled={!data.linked || refreshing}
        title={data.linked ? 'Read LLM spans from Phoenix and recompute cost' : 'Link a Phoenix project on the Diagram tab first'}
        className="btn-secondary btn-sm"
      >
        {refreshing ? 'Reading Phoenix…' : 'Refresh from Phoenix'}
      </button>
    </div>
  )
}

function RefreshNotice({ data, result, error, refreshing }: {
  data: Tokenomics
  result: UsageRefreshResult | null
  error: string | null
  refreshing: boolean
}) {
  if (refreshing) {
    return (
      <p className="text-xs text-gray-500">
        Reading LLM spans from Phoenix… the first read covers 30 days and can take a minute.
      </p>
    )
  }
  if (error) return <Banner tone="rose">Refresh failed: {error}</Banner>

  if (result?.ingestion.locked) {
    return <Banner tone="amber">A usage read is already running for this agent. Try again shortly.</Banner>
  }
  // Without any usage data the empty state already explains the last read.
  if (result && data.source !== 'none') {
    const u = result.usage
    if (u.status === 'ok') {
      return (
        <Banner tone="teal">
          Read {fmtNumber(u.calls)} LLM calls over the last {u.days} days from Phoenix
          {u.unpricedModels.length > 0 && <> — no price for {u.unpricedModels.join(', ')}</>}.
        </Banner>
      )
    }
    return (
      <Banner tone={u.status === 'partial' ? 'amber' : 'rose'}>
        {u.reason || USAGE_STATUS_TEXT[u.status] || `Refresh ended with status ${u.status}.`}
        {data.source === 'phoenix' && u.status !== 'partial' && <> Showing usage collected {fmtAgo(data.lastIngestedAt)}.</>}
        {data.source === 'seed' && <> Still showing demo data.</>}
      </Banner>
    )
  }

  // A scheduled read that failed since the data shown was collected.
  const last = data.lastRefresh
  if (data.source === 'phoenix' && last && !['ok', 'skipped'].includes(last.status)) {
    return (
      <Banner tone="amber">
        The last read from Phoenix ({fmtAgo(last.at)}) did not complete: {last.reason || USAGE_STATUS_TEXT[last.status] || last.status}
        {' '}Showing usage collected {fmtAgo(data.lastIngestedAt)}.
      </Banner>
    )
  }
  return null
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

function DemoNotice({ linked }: { linked: boolean }) {
  return (
    <Banner tone="gray">
      <span className="font-semibold text-gray-700">Demo data.</span> These figures come from sample rows seeded with the
      registry, not from this agent's traces.{' '}
      {linked
        ? 'Refresh from Phoenix to replace them with measured usage.'
        : 'Link a Phoenix project on the Diagram tab to see measured usage.'}
    </Banner>
  )
}

function EmptyState({ data }: { data: Tokenomics }) {
  const last = data.lastRefresh
  let title = 'No usage data'
  let detail: string
  if (!data.linked) {
    title = 'No usage data — link a Phoenix project on the Diagram tab'
    detail = 'Usage and cost come only from this agent’s Phoenix traces, so nothing is shown until a project is linked.'
  } else if (!last) {
    detail = 'Usage has not been read from Phoenix yet. Refresh from Phoenix to read the last 30 days of LLM spans.'
  } else if (last.status === 'ok') {
    detail = last.reason || `Phoenix has no LLM spans for this project in the last ${last.days ?? 30} days.`
  } else {
    title = {
      unreachable: 'No usage data — Phoenix could not be reached',
      auth_failed: 'No usage data — Phoenix key rejected',
    }[last.status as string] || 'No usage data — Phoenix not read'
    detail = last.reason || USAGE_STATUS_TEXT[last.status] || `The last read ended with status ${last.status}.`
  }
  return (
    <div className="rounded-lg border border-dashed border-gray-200 px-4 py-6 text-center">
      <p className="text-sm font-medium text-gray-600">{title}</p>
      <p className="text-xs text-gray-400 mt-1 max-w-md mx-auto">{detail}</p>
    </div>
  )
}

// ── Headline ─────────────────────────────────────────────────────────────────

function Headline({ data }: { data: Tokenomics }) {
  const b = data.budget
  return (
    <section className="space-y-3">
      <BudgetBar budget={b} />
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <MiniStat label="Spend this period" value={fmtCost(data.monthToDateCents)}
          hint={`Token cost ${fmtDay(b.periodStart)} – today (UTC)`} />
        <MiniStat label="Projected period end" value={fmtCost(data.projectedPeriodEndCents)}
          accent={b.projectedOverBudget ? 'text-rose-600' : undefined}
          hint={`Spend so far + 14-day daily average × days left until ${fmtDay(b.periodEnd)}`} />
        <MiniStat label="Cost / call" value={fmtCost(data.costPerCallCents)} hint={`Average over the last ${data.days} days`} />
        <MiniStat label={`LLM calls (${data.days}d)`} value={fmtNumber(data.totals.calls)}
          hint={`${fmtNumber(data.totals.errors)} failed · ${fmtNumber(data.totals.runs)} traces`} />
        <MiniStat label={`Token cost (${data.days}d)`} value={fmtCost(data.totals.costCents)} />
      </div>
    </section>
  )
}

function BudgetBar({ budget: b }: { budget: BudgetView }) {
  if (!b.monthlyBudgetCents) {
    return (
      <p className="text-xs text-gray-400">
        No monthly budget set — spend this period is {fmtCost(b.monthToDateCents)}. Set one below to track it.
      </p>
    )
  }
  const used = b.usedPct ?? 0
  const projectedPct = b.projectedPeriodEndCents != null ? (b.projectedPeriodEndCents / b.monthlyBudgetCents) * 100 : used
  const state = BUDGET_STATE[b.state] || BUDGET_STATE.on_track
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
        <span className="text-gray-500">
          <span className="font-semibold text-gray-900">{fmtCost(b.monthToDateCents)}</span> of {fmtCost(b.monthlyBudgetCents)} budget
          {' '}({used.toFixed(1)}%) · period {fmtDay(b.periodStart)} – {fmtDay(b.periodEnd)}
        </span>
        <span className={`font-medium ${state.text}`}>{state.icon} {state.label}</span>
      </div>
      <div
        className="relative mt-1.5 h-2.5 rounded-full bg-gray-100"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(used)}
        aria-label="Budget used this period"
      >
        <div className={`absolute inset-y-0 left-0 rounded-full opacity-25 ${state.bar}`} style={{ width: `${Math.min(100, projectedPct)}%` }} />
        <div className={`absolute inset-y-0 left-0 rounded-full ${state.bar}`} style={{ width: `${Math.min(100, used)}%` }} />
        <div
          className="absolute -top-1 -bottom-1 w-0.5 bg-gray-700"
          style={{ left: `${Math.min(100, b.alertThresholdPct)}%` }}
          title={`Alert threshold ${b.alertThresholdPct}%`}
        />
      </div>
      <p className="text-[11px] text-gray-400 mt-1">
        Marker = alert at {b.alertThresholdPct}% · light bar = projected period end
        {b.projectedOverBudget && <span className="text-rose-600"> · projected to exceed the budget</span>}
      </p>
    </div>
  )
}

// ── Daily chart ──────────────────────────────────────────────────────────────

const CHART = { left: 52, right: 12, top: 18, costH: 84, gap: 30, tokenH: 110, axis: 20 }

function useWidth<T extends HTMLElement>(fallback: number) {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(fallback)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(entries => setWidth(Math.max(280, Math.floor(entries[0].contentRect.width))))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  return [ref, width] as const
}

function topRoundedBar(x: number, y: number, w: number, h: number, r: number): string {
  const rr = Math.max(0, Math.min(r, w / 2, h))
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`
}

function DailyUsageChart({ daily }: { daily: DailyUsage[] }) {
  const [ref, width] = useWidth<HTMLDivElement>(640)
  const [hover, setHover] = useState<number | null>(null)
  useEffect(() => setHover(null), [daily])

  const n = daily.length
  const plotW = width - CHART.left - CHART.right
  const col = plotW / Math.max(n, 1)
  const barW = Math.max(1, col - Math.min(4, col * 0.3))
  const costTop = CHART.top
  const tokenTop = costTop + CHART.costH + CHART.gap
  const height = tokenTop + CHART.tokenH + CHART.axis

  const costMax = niceCeil(Math.max(...daily.map(d => d.costCents), 0))
  const tokenMax = niceCeil(Math.max(...daily.map(d => d.inputTokens + d.outputTokens), 0))
  const cx = (i: number) => CHART.left + col * i + col / 2
  const costY = (v: number) => costTop + CHART.costH - (v / costMax) * CHART.costH
  const tokenY = (v: number) => tokenTop + CHART.tokenH - (v / tokenMax) * CHART.tokenH

  const labelStep = n <= 31 ? 7 : 15
  const labelled = daily.map((_, i) => i).filter(i => (n - 1 - i) % labelStep === 0)
  const costPath = daily.map((d, i) => `${i ? 'L' : 'M'}${cx(i).toFixed(1)},${costY(d.costCents).toFixed(1)}`).join('')
  const active = hover != null ? daily[hover] : null
  const activeDays = daily.filter(d => d.calls > 0 || d.costCents > 0)

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-gray-500">
        <LegendSwatch color={SERIES.input} label="Input tokens (uncached)" />
        <LegendSwatch color={SERIES.cached} label="Cached input tokens" />
        <LegendSwatch color={SERIES.output} label="Output tokens" />
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block w-4 h-0.5" style={{ background: SERIES.cost }} />Cost per day
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: SERIES.spike }} />Spend spike
        </span>
      </div>
      <div ref={ref} className="relative" onMouseLeave={() => setHover(null)}>
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`Daily cost and tokens for ${n} days; ${activeDays.length} days with usage`}
          className="block"
        >
          <text x={CHART.left} y={costTop - 6} fontSize={10} fill="#9ca3af">Cost per day (USD)</text>
          <text x={CHART.left} y={tokenTop - 6} fontSize={10} fill="#9ca3af">Tokens per day</text>

          {[0, 0.5, 1].map(f => (
            <g key={`c${f}`}>
              <line x1={CHART.left} x2={width - CHART.right} y1={costY(costMax * f)} y2={costY(costMax * f)}
                stroke={f === 0 ? '#e5e7eb' : '#f3f4f6'} />
              <text x={CHART.left - 6} y={costY(costMax * f) + 3} fontSize={10} fill="#9ca3af" textAnchor="end">
                {fmtCost(costMax * f)}
              </text>
            </g>
          ))}
          {[0, 0.5, 1].map(f => (
            <g key={`t${f}`}>
              <line x1={CHART.left} x2={width - CHART.right} y1={tokenY(tokenMax * f)} y2={tokenY(tokenMax * f)}
                stroke={f === 0 ? '#e5e7eb' : '#f3f4f6'} />
              <text x={CHART.left - 6} y={tokenY(tokenMax * f) + 3} fontSize={10} fill="#9ca3af" textAnchor="end">
                {fmtCompact(tokenMax * f)}
              </text>
            </g>
          ))}

          {hover != null && (
            <line x1={cx(hover)} x2={cx(hover)} y1={costTop} y2={tokenTop + CHART.tokenH} stroke="#9ca3af" strokeDasharray="3 3" />
          )}

          {daily.map((d, i) => {
            const uncached = Math.max(d.inputTokens - d.cachedTokens, 0)
            const cached = Math.min(d.cachedTokens, d.inputTokens)
            const segments = [
              { value: uncached, color: SERIES.input },
              { value: cached, color: SERIES.cached },
              { value: d.outputTokens, color: SERIES.output },
            ].filter(s => s.value > 0)
            let base = 0
            const x = cx(i) - barW / 2
            return (
              <g key={d.date} opacity={hover == null || hover === i ? 1 : 0.55}>
                {segments.map((s, k) => {
                  const y0 = tokenY(base)
                  base += s.value
                  const y1 = tokenY(base)
                  const top = k === segments.length - 1
                  // 2px surface gap between stacked segments, when they are tall enough to spare it.
                  const h = Math.max(top ? y0 - y1 : y0 - y1 - (y0 - y1 > 4 ? 2 : 0), 0.5)
                  return top
                    ? <path key={k} d={topRoundedBar(x, y1, barW, h, 3)} fill={s.color} />
                    : <rect key={k} x={x} y={y0 - h} width={barW} height={h} fill={s.color} />
                })}
              </g>
            )
          })}

          <path d={costPath} fill="none" stroke={SERIES.cost} strokeWidth={2} strokeLinejoin="round" />
          {daily.map((d, i) => d.spike && (
            <circle key={`s${d.date}`} cx={cx(i)} cy={costY(d.costCents)} r={4.5} fill={SERIES.spike} stroke="#fff" strokeWidth={2} />
          ))}
          {active && hover != null && (
            <circle cx={cx(hover)} cy={costY(active.costCents)} r={4} fill={SERIES.cost} stroke="#fff" strokeWidth={2} />
          )}

          {labelled.map(i => (
            <text key={`x${i}`} x={cx(i)} y={height - 5} fontSize={10} fill="#9ca3af" textAnchor="middle">
              {fmtDay(daily[i].date)}
            </text>
          ))}

          {daily.map((d, i) => (
            <rect
              key={`h${d.date}`}
              x={CHART.left + col * i}
              y={costTop}
              width={col}
              height={tokenTop + CHART.tokenH - costTop}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
              onClick={() => setHover(i)}
            />
          ))}
        </svg>
        {active && hover != null && <ChartTooltip day={active} x={cx(hover)} width={width} />}
      </div>
      <details className="text-xs text-gray-500">
        <summary className="cursor-pointer select-none text-gray-400 hover:text-gray-600">Show as table</summary>
        {activeDays.length === 0 ? (
          <p className="mt-2 text-gray-400">No LLM calls in this window.</p>
        ) : (
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-gray-400">
                <tr className="text-right">
                  <th className="text-left font-normal py-1">Day (UTC)</th>
                  <th className="font-normal">Calls</th><th className="font-normal">Errors</th>
                  <th className="font-normal">Input</th><th className="font-normal">Cached</th>
                  <th className="font-normal">Output</th><th className="font-normal">Cost</th>
                </tr>
              </thead>
              <tbody className="text-gray-700">
                {activeDays.map(d => (
                  <tr key={d.date} className="text-right border-t border-gray-50">
                    <td className="text-left py-1">{fmtDay(d.date, true)}{d.spike && <span className="text-rose-600"> · spike</span>}</td>
                    <td>{fmtNumber(d.calls)}</td><td>{fmtNumber(d.errors)}</td>
                    <td>{fmtNumber(d.inputTokens)}</td><td>{fmtNumber(d.cachedTokens)}</td>
                    <td>{fmtNumber(d.outputTokens)}</td><td>{fmtCost(d.costCents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </details>
    </div>
  )
}

function LegendSwatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: color }} />{label}
    </span>
  )
}

function ChartTooltip({ day, x, width }: { day: DailyUsage; x: number; width: number }) {
  const TIP_W = 190
  const left = x + 12 + TIP_W > width ? Math.max(x - 12 - TIP_W, 0) : x + 12
  return (
    <div
      className="pointer-events-none absolute top-2 rounded-lg border border-gray-200 bg-white/95 px-3 py-2 text-[11px] text-gray-600 shadow-sm"
      style={{ left, width: TIP_W }}
    >
      <div className="font-semibold text-gray-900 mb-1">{fmtDay(day.date, true)}</div>
      <TipRow label="Cost" value={fmtCost(day.costCents)} />
      <TipRow label="LLM calls" value={`${fmtNumber(day.calls)}${day.errors ? ` (${day.errors} failed)` : ''}`} />
      <TipRow label="Input tokens" value={fmtNumber(day.inputTokens)} color={SERIES.input} />
      <TipRow label="of which cached" value={fmtNumber(day.cachedTokens)} color={SERIES.cached} />
      <TipRow label="Output tokens" value={fmtNumber(day.outputTokens)} color={SERIES.output} />
      {day.spike && <div className="mt-1 text-rose-600">Spend spike against the trailing median</div>}
    </div>
  )
}

function TipRow({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="inline-flex items-center gap-1.5">
        {color && <span className="inline-block w-2 h-2 rounded-sm" style={{ background: color }} />}{label}
      </span>
      <span className="font-mono text-gray-900">{value}</span>
    </div>
  )
}

// ── By model ─────────────────────────────────────────────────────────────────

function ModelTable({ data }: { data: Tokenomics }) {
  const unpriced = data.byModel.filter(m => !m.priced).map(m => m.model)
  if (data.byModel.length === 0) return null
  return (
    <section className="space-y-2">
      <SectionLabel>By model — last {data.days} days</SectionLabel>
      {unpriced.length > 0 && (
        <Banner tone="amber">
          No price for {unpriced.join(', ')} — {unpriced.length === 1 ? 'its' : 'their'} tokens are counted but not costed,
          so the totals above are a lower bound. An admin can map the name to a priced model (model aliases).
        </Banner>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-gray-400">
            <tr className="text-right">
              <th className="text-left font-normal py-1">Model</th>
              <th className="font-normal">Calls</th>
              <th className="font-normal">Input</th>
              <th className="font-normal">Cached</th>
              <th className="font-normal">Output</th>
              <th className="font-normal">Cost</th>
              <th className="font-normal">Share</th>
            </tr>
          </thead>
          <tbody className="text-gray-700">
            {data.byModel.map(m => (
              <tr key={m.model} className="text-right border-t border-gray-50">
                <td className="text-left py-1.5">
                  <span className="font-mono">{m.model}</span>
                  {!m.priced && <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full ring-1 bg-amber-50 text-amber-700 ring-amber-200">unpriced</span>}
                </td>
                <td>{fmtNumber(m.calls)}</td>
                <td>{fmtNumber(m.inputTokens)}</td>
                <td>{fmtNumber(m.cachedTokens)}</td>
                <td>{fmtNumber(m.outputTokens)}</td>
                <td>{m.priced ? fmtCost(m.costCents) : '—'}</td>
                <td>{m.priced ? `${m.sharePct}%` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.declaredModel && <p className="text-[11px] text-gray-400">Declared model: {data.declaredModel}</p>}
    </section>
  )
}

// ── Forecast ─────────────────────────────────────────────────────────────────

function ForecastPanel({ data }: { data: Tokenomics }) {
  const f = data.forecast
  return (
    <section className="space-y-2">
      <SectionLabel>Token cost forecast</SectionLabel>
      {f.status !== 'ok' ? (
        <p className="text-xs text-gray-400">
          Not enough history yet ({Math.min(f.daysWithUsage, f.minDays)} of {f.minDays} days with usage in the last 30 days).
        </p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3">
            {f.months.map(m => (
              <MiniStat key={m.month} label={`Days ${30 * (m.month - 1) + 1}–${30 * m.month}`} value={fmtCost(m.projectedCents)} />
            ))}
          </div>
          <p className="text-[11px] text-gray-400">
            {f.method}; each month is 30 days
            {f.dailySlopeCents != null && <> · trend {f.dailySlopeCents >= 0 ? '+' : '−'}{fmtCost(Math.abs(f.dailySlopeCents))} per day</>}
            {data.source === 'seed' && <> · based on demo data</>}
          </p>
        </>
      )}
    </section>
  )
}

// ── Anomalies ────────────────────────────────────────────────────────────────

const SHARE_BAND: Record<string, string> = {
  green: 'text-teal-700',
  yellow: 'text-amber-700',
  red: 'text-rose-700',
}

function AnomalyList({ data, onChanged }: { data: Tokenomics; onChanged: () => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const share = data.anomalyCostShare

  if (data.source !== 'phoenix' && data.anomalies.length === 0) return null

  const resolve = async (id: string) => {
    setBusy(id)
    setError(null)
    try {
      await resolveCostAnomaly(id)
      await onChanged()
    } catch (e) {
      setError(errorMessage(e, 'Could not resolve'))
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <SectionLabel>Cost anomalies</SectionLabel>
        {share && (
          <span className="text-[11px] text-gray-400" title="Spike impact ÷ total spend (FinOps Foundation): under 2% healthy, 2–7% warning, over 7% critical">
            Anomaly cost share <span className={`font-semibold ${SHARE_BAND[share.band] || ''}`}>{share.pct}%</span> of spend over {share.evaluatedDays} evaluated days
          </span>
        )}
      </div>
      {error && <p className="text-xs text-rose-600">{error}</p>}
      {data.anomalies.length === 0 ? (
        <p className="text-xs text-gray-400">No open cost anomalies.</p>
      ) : (
        <ul className="space-y-2">
          {data.anomalies.map(a => (
            <li key={a.id} className="flex items-start justify-between gap-3 rounded-lg border border-gray-100 px-3 py-2">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full ring-1 ${SEVERITY_PILL[a.severity] || SEVERITY_PILL.LOW}`}>{a.severity}</span>
                  <span className="text-sm font-medium text-gray-800">{ANOMALY_LABEL[a.type] || a.type}</span>
                  {a.detectedAt && <span className="text-[11px] text-gray-400" title={fmtTime(a.detectedAt)}>detected {fmtAgo(a.detectedAt)}</span>}
                </div>
                <p className="text-xs text-gray-500 mt-0.5">{describeAnomaly(a)}</p>
              </div>
              <button onClick={() => resolve(a.id)} disabled={busy != null} className="btn-secondary btn-sm shrink-0">
                {busy === a.id ? 'Resolving…' : 'Resolve'}
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="text-[11px] text-gray-400">
        Found by the daily cost rollup. Budget and model conditions close on their own once they clear; spikes and error bursts stay open until a person resolves them.
      </p>
    </section>
  )
}

// ── Budget editor ────────────────────────────────────────────────────────────

function BudgetEditor({ agentId, budget, onSaved }: { agentId: string; budget: BudgetView; onSaved: () => Promise<void> }) {
  const initial = useMemo(() => ({
    amount: budget.monthlyBudgetCents ? (budget.monthlyBudgetCents / 100).toFixed(2) : '',
    alert: String(budget.alertThresholdPct),
    reset: String(budget.budgetResetDay),
  }), [budget.monthlyBudgetCents, budget.alertThresholdPct, budget.budgetResetDay])
  const [form, setForm] = useState(initial)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => setForm(initial), [initial])

  const amount = form.amount.trim() === '' ? 0 : Number(form.amount)
  const alert = Number(form.alert)
  const reset = Number(form.reset)
  const invalid =
    !Number.isFinite(amount) || amount < 0 || amount > 20_000_000 ? 'Budget must be between $0 and $20,000,000.'
    : !Number.isInteger(alert) || alert < 1 || alert > 100 ? 'Alert threshold must be a whole number from 1 to 100.'
    : !Number.isInteger(reset) || reset < 1 || reset > 28 ? 'Reset day must be a whole number from 1 to 28.'
    : null
  const changed = form.amount !== initial.amount || form.alert !== initial.alert || form.reset !== initial.reset

  const save = async () => {
    if (invalid) return
    setSaving(true)
    setMessage(null)
    try {
      await updateBudget(agentId, {
        monthlyBudgetCents: Math.round(amount * 100),
        alertThresholdPct: alert,
        budgetResetDay: reset,
      })
      await onSaved()
      setMessage({ ok: true, text: 'Budget saved.' })
    } catch (e) {
      setMessage({ ok: false, text: errorMessage(e, 'Could not save the budget') })
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="space-y-2 rounded-lg bg-gray-50 px-4 py-3">
      <SectionLabel>Monthly token budget</SectionLabel>
      <div className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_1fr_auto] gap-3 items-end">
        <label className="text-xs text-gray-500 space-y-1">
          <span>Amount (USD)</span>
          <input
            className="input" type="number" min={0} step="0.01" inputMode="decimal" placeholder="No budget"
            value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })}
          />
        </label>
        <label className="text-xs text-gray-500 space-y-1">
          <span>Alert at (% of budget)</span>
          <input
            className="input" type="number" min={1} max={100} step={1}
            value={form.alert} onChange={e => setForm({ ...form, alert: e.target.value })}
          />
        </label>
        <label className="text-xs text-gray-500 space-y-1">
          <span>Period starts on day</span>
          <input
            className="input" type="number" min={1} max={28} step={1}
            value={form.reset} onChange={e => setForm({ ...form, reset: e.target.value })}
          />
        </label>
        <button onClick={save} disabled={!changed || !!invalid || saving} className="btn-primary btn-sm">
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
      {changed && invalid && <p className="text-xs text-rose-600">{invalid}</p>}
      {message && <p className={`text-xs ${message.ok ? 'text-teal-700' : 'text-rose-600'}`}>{message.text}</p>}
      <p className="text-[11px] text-gray-400">
        Informational only — the registry never pauses or stops an agent. Leave the amount empty or 0 for no budget.
      </p>
    </section>
  )
}
