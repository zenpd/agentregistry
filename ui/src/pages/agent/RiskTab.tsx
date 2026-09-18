import { useCallback, useEffect, useMemo, useState } from 'react'
import RiskPie from '../../components/RiskPie'
import RiskHeatmap from '../../components/RiskHeatmap'
import {
  ACTIVE_STATUSES,
  RISK_CATEGORIES,
  RISK_SEVERITIES,
  createAgentRisk,
  getAgentRiskRegister,
  scanAgentRiskRegister,
  updateAgentRisk,
  type AgentRisksResponse,
  type FinancialFinding,
  type LastRiskScan,
  type RiskAction,
  type RiskActionPayload,
  type RiskCategory,
  type RiskRegisterFinding,
  type RiskScanResult,
  type RiskSeverity,
  type RiskStatus,
} from '../../services/ops/risk'
import {
  CATEGORY_COLORS, CATEGORY_LABELS, Loading, MiniStat, SectionLabel, SEVERITIES, SEVERITY_PILL, SOURCE_BADGE,
  SourceBadge, type TabProps,
} from './shared'

const STATUS_PILL: Record<RiskStatus, string> = {
  open: 'bg-rose-50 text-rose-700 ring-rose-200',
  acknowledged: 'bg-violet-50 text-violet-700 ring-violet-200',
  mitigating: 'bg-sky-50 text-sky-700 ring-sky-200',
  accepted: 'bg-amber-50 text-amber-700 ring-amber-200',
  resolved: 'bg-teal-50 text-teal-700 ring-teal-200',
}

const STATUS_LABEL: Record<RiskStatus, string> = {
  open: 'Open', acknowledged: 'Acknowledged', mitigating: 'Mitigating', accepted: 'Accepted', resolved: 'Resolved',
}

const ACTION_LABEL: Record<RiskAction, string> = {
  acknowledge: 'Acknowledge', mitigate: 'Mitigate', resolve: 'Resolve', accept: 'Accept risk', reopen: 'Reopen', update: 'Edit',
}

const ACTIONS_BY_STATUS: Record<RiskStatus, RiskAction[]> = {
  open: ['acknowledge', 'mitigate', 'resolve', 'accept'],
  acknowledged: ['mitigate', 'resolve', 'accept'],
  mitigating: ['resolve', 'accept'],
  accepted: ['reopen'],
  resolved: ['reopen'],
}

const ORIGIN_LABEL: Record<string, string> = {
  economics: 'Revenue & Expenditure rule',
  cost_anomalies: 'Cost anomaly',
  waste_findings: 'Waste finding',
}

const SOURCE_LABEL: Record<string, string> = { manual: 'Added by a person', context: 'From context.md' }

const TRACE_RULES_TEXT = 'error rate, PII in traces, prompt injection, p95 latency vs SLA and undeclared dependencies'
const MIN_STABLE_TRACES = 50

type StatusFilter = 'active' | 'all' | RiskStatus

const PILL = 'text-[10px] px-1.5 py-0.5 rounded-full ring-1 whitespace-nowrap'
const TEXTAREA = 'input w-full text-xs min-h-[56px]'

function errorMessage(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d: any) => d.msg || String(d)).join('; ')
  return e?.message || fallback
}

function isDateOnly(iso: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(iso)
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const dateOnly = isDateOnly(iso)
  return new Date(dateOnly ? `${iso}T00:00:00Z` : iso).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', timeZone: dateOnly ? 'UTC' : undefined,
  })
}

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function relative(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours} h ago`
  return `${Math.round(hours / 24)} days ago`
}

function addDays(isoDate: string, days: number): string {
  const d = new Date(`${isoDate}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

function SeverityPill({ severity }: { severity: string }) {
  return <span className={`${PILL} ${SEVERITY_PILL[severity] || 'bg-gray-50 text-gray-600 ring-gray-200'}`}>{severity}</span>
}

function ErrorLine({ text }: { text: string | null }) {
  return text ? <p className="text-xs text-rose-600">{text}</p> : null
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function RiskTab({ agentId }: TabProps) {
  const [data, setData] = useState<AgentRisksResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('active')
  const [categoryFilter, setCategoryFilter] = useState<'all' | RiskCategory>('all')
  const [showAdd, setShowAdd] = useState(false)

  // Always fetch every status: the filters are client-side and the charts need the active subset.
  const load = useCallback(async () => {
    try {
      const res = await getAgentRiskRegister(agentId, 'all')
      setData(res.data)
      setError(null)
    } catch (e) {
      setError(errorMessage(e, 'Could not load risk findings'))
    }
  }, [agentId])

  useEffect(() => {
    setData(null)
    setError(null)
    load()
  }, [load])

  if (error && !data) {
    return (
      <div className="py-8 text-center space-y-2">
        <p className="text-sm text-rose-600">{error}</p>
        <button onClick={load} className="btn-secondary btn-sm">Retry</button>
      </div>
    )
  }
  if (!data) return <Loading text="Loading risk findings…" />

  const active = data.findings.filter(f => ACTIVE_STATUSES.includes(f.status))
  const listed = data.findings.filter(f =>
    (statusFilter === 'all' || (statusFilter === 'active' ? ACTIVE_STATUSES.includes(f.status) : f.status === statusFilter))
    && (categoryFilter === 'all' || f.category === categoryFilter),
  )

  return (
    <div className="space-y-5">
      {error && <ErrorLine text={`Refresh failed: ${error}`} />}
      <ScoreHeader data={data} agentId={agentId} onScanned={load} />
      <TraceSignalsPanel data={data} />
      <Charts active={active} financial={data.financial} />

      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <SectionLabel>Risk register · showing {listed.length} of {data.findings.length}</SectionLabel>
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Filter by status"
              className="input text-xs py-1 w-auto"
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value as StatusFilter)}
            >
              <option value="active">Active (open, acknowledged, mitigating, accepted)</option>
              {(Object.keys(STATUS_LABEL) as RiskStatus[]).map(s => (
                <option key={s} value={s}>{STATUS_LABEL[s]} ({data.findings.filter(f => f.status === s).length})</option>
              ))}
              <option value="all">All statuses</option>
            </select>
            <select
              aria-label="Filter by category"
              className="input text-xs py-1 w-auto"
              value={categoryFilter}
              onChange={e => setCategoryFilter(e.target.value as 'all' | RiskCategory)}
            >
              <option value="all">All categories</option>
              {RISK_CATEGORIES.map(c => (
                <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>
              ))}
            </select>
            <button onClick={() => setShowAdd(v => !v)} className="btn-secondary btn-sm">
              {showAdd ? 'Cancel' : '+ Add risk'}
            </button>
          </div>
        </div>

        {showAdd && (
          <AddRiskForm agentId={agentId} today={data.today} onDone={async () => { setShowAdd(false); await load() }} />
        )}

        {listed.length === 0 ? (
          <RegisterEmpty data={data} filtered={data.findings.length > 0} />
        ) : (
          <div className="space-y-2">
            {listed.map(f => (
              <FindingRow key={f.id} finding={f} agentId={agentId} data={data} onChanged={load} />
            ))}
          </div>
        )}
      </div>

      <FinancialSection financial={data.financial} />
    </div>
  )
}

// ── Header: score + scan ─────────────────────────────────────────────────────

function ScoreHeader({ data, agentId, onScanned }: { data: AgentRisksResponse; agentId: string; onScanned: () => Promise<void> }) {
  const [scanning, setScanning] = useState(false)
  const [result, setResult] = useState<RiskScanResult | null>(null)
  const [scanError, setScanError] = useState<string | null>(null)
  const { score } = data

  async function scan() {
    setScanning(true)
    setScanError(null)
    try {
      const res = await scanAgentRiskRegister(agentId)
      setResult(res.data)
      await onScanned()
    } catch (e) {
      setScanError(errorMessage(e, 'Risk scan failed'))
    } finally {
      setScanning(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <SectionLabel>Current risk</SectionLabel>
          <div className="flex items-center gap-2">
            {score.worst ? (
              <>
                <span className={`text-xs px-2 py-0.5 rounded-full ring-1 font-semibold ${SEVERITY_PILL[score.worst]}`}>{score.worst}</span>
                <span className="text-xs text-gray-500">worst active severity · {score.total} active finding(s)</span>
              </>
            ) : (
              <span className="text-xs text-gray-500">No active findings</span>
            )}
          </div>
        </div>
        <div className="text-right space-y-1">
          <button onClick={scan} disabled={scanning} className="btn-primary btn-sm disabled:opacity-50">
            {scanning ? 'Scanning…' : 'Scan now'}
          </button>
          <LastScanLine lastScan={data.lastScan} />
        </div>
      </div>

      <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
        {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as RiskSeverity[]).map(s => (
          <MiniStat
            key={s}
            label={s}
            value={String(score.countsBySeverity[s] ?? 0)}
            accent={score.countsBySeverity[s] ? SEVERITY_TEXT[s] : 'text-gray-300'}
          />
        ))}
        <MiniStat label="Overdue" value={String(score.overdue)} accent={score.overdue ? 'text-rose-600' : 'text-gray-300'} hint="Past the due date and not yet resolved or accepted" />
        <MiniStat label="Resolved" value={String(score.resolved)} accent="text-teal-600" />
      </div>

      {scanError && <ErrorLine text={scanError} />}
      {result && <ScanResultLine result={result} />}
    </div>
  )
}

const SEVERITY_TEXT: Record<RiskSeverity, string> = {
  CRITICAL: 'text-rose-600', HIGH: 'text-orange-600', MEDIUM: 'text-amber-600', LOW: 'text-emerald-600',
}

function LastScanLine({ lastScan }: { lastScan: LastRiskScan | null }) {
  if (!lastScan) return <p className="text-[11px] text-gray-400">Never scanned</p>
  const when = lastScan.finishedAt || lastScan.startedAt
  const failed = !['ok', 'partial', 'running'].includes(lastScan.status)
  return (
    <p className={`text-[11px] ${failed ? 'text-rose-600' : 'text-gray-400'}`} title={when ? fmtDateTime(when) : undefined}>
      {lastScan.status === 'running' ? 'Scan running' : failed ? `Last scan ${lastScan.status}` : 'Last scanned'}
      {when && ` ${relative(when)}`}
      {` · ${lastScan.trigger}${lastScan.scope === 'all' ? ', all agents' : ''}`}
      {failed && lastScan.error && <span className="block">{lastScan.error}</span>}
    </p>
  )
}

function ScanResultLine({ result }: { result: RiskScanResult }) {
  const c = result.reconcile
  const parts = c ? [
    `${c.inserted} new`,
    `${c.updated} still present`,
    c.reopened ? `${c.reopened} reopened` : null,
    c.resolved ? `${c.resolved} auto-resolved` : null,
    c.acceptanceExpired ? `${c.acceptanceExpired} acceptance(s) expired` : null,
    c.backfilled ? `${c.backfilled} older finding(s) matched to a rule` : null,
  ].filter(Boolean) : []
  return (
    <div className="rounded-lg bg-teal-50/60 ring-1 ring-teal-100 px-3 py-2 text-xs text-teal-800 space-y-0.5">
      <p>Scan complete: {result.findingCount} condition(s) detected{parts.length ? ` — ${parts.join(' · ')}` : ''}.</p>
      {result.uncheckedRules.length > 0 && (
        <p className="text-teal-700/80">
          Not checked this time (input missing): {result.uncheckedRules.join(', ')}. Their stored findings were left as they were.
        </p>
      )}
    </div>
  )
}

// ── Trace signals ────────────────────────────────────────────────────────────

function TraceSignalsPanel({ data }: { data: AgentRisksResponse }) {
  const scan = data.lastScan
  const windowDays = scan?.traceWindowDays ?? 7

  if (!data.phoenixLinked) {
    return (
      <Notice tone="gray">
        Trace-based rules ({TRACE_RULES_TEXT}) need a linked Phoenix project. None is linked, so they are not
        checked. That means no trace data, not a clean result. Link a project on the Overview tab.
      </Notice>
    )
  }
  if (!scan || !scan.traceSignals) {
    return (
      <Notice tone="gray">
        Trace rules read the last {windowDays} days of Phoenix project <span className="font-mono">{data.phoenixProject}</span> when
        you run a scan.
      </Notice>
    )
  }
  if (scan.traceSignals === 'unavailable') {
    return (
      <Notice tone="amber">
        Phoenix was not reachable on the last scan{scan.traceReason ? ` (${scan.traceReason})` : ''}. Trace rules were
        skipped and their stored findings were left unchanged.
      </Notice>
    )
  }
  if (scan.traceSignals === 'no_traces' || !scan.kri) {
    return (
      <Notice tone="amber">
        Phoenix project <span className="font-mono">{data.phoenixProject}</span> recorded no spans in the last {windowDays} days,
        so there was nothing to measure.
      </Notice>
    )
  }

  const kri = scan.kri
  const smallSample = kri.trace_count < MIN_STABLE_TRACES
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <SectionLabel>Trace signals · last {windowDays} days · {data.phoenixProject}</SectionLabel>
        <SourceBadge source="phoenix" />
        {smallSample && <span className={`${PILL} bg-amber-50 text-amber-700 ring-amber-200`}>Small sample</span>}
      </div>
      <div className="grid grid-cols-3 sm:grid-cols-7 gap-2">
        <MiniStat label="Traces" value={kri.trace_count.toLocaleString()} />
        <MiniStat label="Spans" value={kri.span_count.toLocaleString()} />
        <MiniStat
          label="Error rate"
          value={kri.error_rate == null ? '—' : `${(kri.error_rate * 100).toFixed(1)}%`}
          hint={kri.worst_error_span ? `Worst step: ${kri.worst_error_span.name} (${kri.worst_error_span.errors})` : undefined}
          accent={kri.error_spans ? 'text-amber-600' : undefined}
        />
        <MiniStat label="p95 latency" value={kri.p95_latency_ms == null ? '—' : `${Math.round(kri.p95_latency_ms).toLocaleString()} ms`} hint="Whole-trace duration" />
        <MiniStat label="PII spans" value={String(kri.pii_spans)} accent={kri.pii_spans ? 'text-rose-600' : undefined} hint="Spans with pii.detected=true" />
        <MiniStat label="Injection" value={String(kri.injection_spans)} accent={kri.injection_spans ? 'text-rose-600' : undefined} hint="Spans with guardrail.injection_detected=true" />
        <MiniStat label="LLM calls" value={kri.llm_calls.toLocaleString()} />
      </div>
      {(smallSample || scan.sampleCapped) && (
        <p className="text-[11px] text-gray-400">
          {smallSample && `Fewer than ${MIN_STABLE_TRACES} traces, so rates swing on a handful of spans. `}
          {scan.sampleCapped && 'The sample hit the 5,000-span cap (newest first), so older spans in the window were not read.'}
        </p>
      )}
    </div>
  )
}

function Notice({ tone, children }: { tone: 'gray' | 'amber'; children: React.ReactNode }) {
  const cls = tone === 'amber' ? 'bg-amber-50 ring-amber-100 text-amber-800' : 'bg-gray-50 ring-gray-100 text-gray-600'
  return <div className={`rounded-lg ring-1 px-3 py-2 text-xs ${cls}`}>{children}</div>
}

// ── Charts ───────────────────────────────────────────────────────────────────

function Charts({ active, financial }: { active: RiskRegisterFinding[]; financial: FinancialFinding[] }) {
  const all = useMemo(
    () => [...active.map(f => ({ category: f.category, severity: f.severity })), ...financial],
    [active, financial],
  )
  if (all.length === 0) return null

  const pie = RISK_CATEGORIES
    .map(c => ({ label: CATEGORY_LABELS[c], count: all.filter(f => f.category === c).length, color: CATEGORY_COLORS[c] }))
    .filter(s => s.count > 0)
  const heatmap = RISK_CATEGORIES
    .map(c => {
      const counts: Record<string, number> = {}
      for (const s of SEVERITIES) counts[s] = all.filter(f => f.category === c && f.severity === s).length
      return { category: c, label: CATEGORY_LABELS[c], counts }
    })
    .filter(row => Object.values(row.counts).some(n => n > 0))

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div>
        <span className="text-xs text-gray-400 mb-2 block">Active findings by category</span>
        <RiskPie data={pie} size={150} />
      </div>
      <div>
        <span className="text-xs text-gray-400 mb-2 block">Category × severity</span>
        <RiskHeatmap rows={heatmap} severities={SEVERITIES} />
      </div>
    </div>
  )
}

// ── Register ─────────────────────────────────────────────────────────────────

function RegisterEmpty({ data, filtered }: { data: AgentRisksResponse; filtered: boolean }) {
  if (filtered) return <p className="text-sm text-gray-400 py-4 text-center">No findings match these filters.</p>
  if (!data.lastScan) {
    return (
      <p className="text-sm text-gray-400 py-4 text-center">
        No findings yet. This agent has never been scanned. Click Scan now, or add a risk by hand.
      </p>
    )
  }
  return <p className="text-sm text-gray-400 py-4 text-center">No findings for this agent.</p>
}

function FindingRow({ finding: f, agentId, data, onChanged }: {
  finding: RiskRegisterFinding; agentId: string; data: AgentRisksResponse; onChanged: () => Promise<void>
}) {
  const [action, setAction] = useState<RiskAction | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const actions = ACTIONS_BY_STATUS[f.status] || []
  const muted = f.status === 'resolved'

  return (
    <div className={`rounded-lg border border-gray-100 p-3 space-y-2 ${muted ? 'bg-gray-50/60' : ''}`}>
      <div className="flex items-start gap-2">
        <SeverityPill severity={f.severity} />
        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className={`text-sm font-medium ${muted ? 'text-gray-500' : 'text-gray-800'}`}>{f.title}</span>
            <span className={`${PILL} ${STATUS_PILL[f.status]}`}>{STATUS_LABEL[f.status] || f.status}</span>
            {f.overdue && <span className={`${PILL} bg-rose-600 text-white ring-rose-600`}>Overdue</span>}
            {SOURCE_LABEL[f.source] && <span className={`${PILL} bg-gray-50 text-gray-500 ring-gray-200`}>{SOURCE_LABEL[f.source]}</span>}
          </div>
          <p className="text-[11px] text-gray-400">
            {CATEGORY_LABELS[f.category] || f.category}
            {f.detectedAt && ` · first detected ${fmtDate(f.detectedAt)}`}
            {f.lastDetectedAt && f.source === 'auto' && ` · last seen ${fmtDate(f.lastDetectedAt)}`}
            {f.resolvedAt && f.status === 'resolved' && ` · resolved ${fmtDate(f.resolvedAt)}`}
            {f.ruleId && <span className="font-mono"> · {f.ruleId}</span>}
          </p>
          {f.description && <p className="text-xs text-gray-600">{f.description}</p>}
          <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-gray-500">
            <span><span className="text-gray-400">Owner:</span> {f.owner || <span className="text-gray-400">unassigned</span>}</span>
            <span className={f.overdue ? 'text-rose-600 font-medium' : ''}><span className="text-gray-400">Due:</span> {fmtDate(f.dueDate)}</span>
            {f.status === 'accepted' && (
              <span><span className="text-gray-400">Accepted until</span> {fmtDate(f.acceptedUntil)}{f.acceptedBy && ` by ${f.acceptedBy}`}</span>
            )}
          </div>
          {f.mitigation && (
            <p className="text-xs text-gray-600"><span className="text-gray-400">Mitigation:</span> {f.mitigation}</p>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {actions.map(a => (
          <button
            key={a}
            onClick={() => setAction(action === a ? null : a)}
            className={`btn-sm ${action === a ? 'btn-primary' : 'btn-secondary'}`}
          >
            {ACTION_LABEL[a]}
          </button>
        ))}
        <button onClick={() => setAction(action === 'update' ? null : 'update')} className={`btn-sm ${action === 'update' ? 'btn-primary' : 'btn-secondary'}`}>
          Edit owner / due date
        </button>
        <button onClick={() => setShowHistory(v => !v)} className="text-xs text-teal-600 hover:text-teal-700 ml-auto">
          {showHistory ? 'Hide history' : `History (${f.history.length})`}
        </button>
      </div>

      {action && (
        <ActionForm
          key={action}
          finding={f}
          action={action}
          today={data.today}
          maxDays={data.maxAcceptanceDays}
          onCancel={() => setAction(null)}
          onSubmit={async payload => {
            await updateAgentRisk(agentId, f.id, payload)
            setAction(null)
            await onChanged()
          }}
        />
      )}
      {showHistory && <History entries={f.history} />}
    </div>
  )
}

function ActionForm({ finding, action, today, maxDays, onCancel, onSubmit }: {
  finding: RiskRegisterFinding
  action: RiskAction
  today: string
  maxDays: number
  onCancel: () => void
  onSubmit: (payload: RiskActionPayload) => Promise<void>
}) {
  const [owner, setOwner] = useState(finding.owner || '')
  const [dueDate, setDueDate] = useState(finding.dueDate || '')
  const [mitigation, setMitigation] = useState(finding.mitigation || '')
  const [acceptedUntil, setAcceptedUntil] = useState(addDays(today, 90))
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const maxDate = addDays(today, maxDays)

  function payload(): RiskActionPayload | string {
    const out: RiskActionPayload = { action }
    const trimmedNote = note.trim()
    if (trimmedNote) out.note = trimmedNote
    if ((action === 'acknowledge' || action === 'update') && owner.trim() !== (finding.owner || '')) {
      out.owner = owner.trim() || null
    }
    if (action === 'update' && dueDate !== (finding.dueDate || '')) out.dueDate = dueDate || null
    if ((action === 'mitigate' || action === 'update') && mitigation.trim() !== (finding.mitigation || '')) {
      out.mitigation = mitigation.trim() || null
    }
    if (action === 'mitigate' && !mitigation.trim()) return 'Describe the mitigation being worked on.'
    if (action === 'accept') {
      if (!acceptedUntil) return 'Choose the date the acceptance expires.'
      if (acceptedUntil < today || acceptedUntil > maxDate) return `The expiry must be between today and ${fmtDate(maxDate)}.`
      if (!trimmedNote) return 'Record why this risk is being accepted.'
      out.acceptedUntil = acceptedUntil
    }
    if (action === 'update' && Object.keys(out).length === 1) return 'Nothing has changed.'
    return out
  }

  async function submit() {
    const p = payload()
    if (typeof p === 'string') {
      setError(p)
      return
    }
    setSaving(true)
    setError(null)
    try {
      await onSubmit(p)
    } catch (e) {
      setError(errorMessage(e, 'Could not save'))
      setSaving(false)
    }
  }

  const noteLabel = action === 'accept' ? 'Rationale (required, kept in history)' : 'Note (optional, kept in history)'

  return (
    <div className="rounded-lg bg-gray-50 p-3 space-y-2">
      {action === 'resolve' && finding.source === 'auto' && (
        <p className="text-[11px] text-gray-500">If the condition is still true, the next scan reopens this finding.</p>
      )}
      {action === 'accept' && (
        <p className="text-[11px] text-gray-500">
          Accepting records that you have decided to live with this risk until a date. It reopens automatically when
          that date passes. Maximum {maxDays} days.
        </p>
      )}

      {(action === 'acknowledge' || action === 'update') && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <label className="text-xs text-gray-500 space-y-1 block">
            <span>Owner</span>
            <input className="input w-full text-xs" value={owner} onChange={e => setOwner(e.target.value)} placeholder="Name or team" />
          </label>
          {action === 'update' && (
            <label className="text-xs text-gray-500 space-y-1 block">
              <span>Due date</span>
              <input type="date" className="input w-full text-xs" value={dueDate} onChange={e => setDueDate(e.target.value)} />
            </label>
          )}
        </div>
      )}

      {(action === 'mitigate' || action === 'update') && (
        <label className="text-xs text-gray-500 space-y-1 block">
          <span>Mitigation plan{action === 'mitigate' ? ' (required)' : ''}</span>
          <textarea className={TEXTAREA} value={mitigation} onChange={e => setMitigation(e.target.value)} placeholder="What is being done to reduce this risk" />
        </label>
      )}

      {action === 'accept' && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-gray-500 space-y-1 block">
            <span>Accepted until</span>
            <input type="date" className="input text-xs" min={today} max={maxDate} value={acceptedUntil} onChange={e => setAcceptedUntil(e.target.value)} />
          </label>
          {[30, 90, 180, maxDays].map(days => (
            <button key={days} type="button" onClick={() => setAcceptedUntil(addDays(today, days))} className="btn-secondary btn-sm">
              {days === 365 ? '1 year' : `${days} days`}
            </button>
          ))}
        </div>
      )}

      <label className="text-xs text-gray-500 space-y-1 block">
        <span>{noteLabel}</span>
        <textarea className={TEXTAREA} value={note} onChange={e => setNote(e.target.value)} />
      </label>

      <ErrorLine text={error} />
      <div className="flex gap-2">
        <button onClick={submit} disabled={saving} className="btn-primary btn-sm disabled:opacity-50">
          {saving ? 'Saving…' : ACTION_LABEL[action] === 'Edit' ? 'Save changes' : ACTION_LABEL[action]}
        </button>
        <button onClick={onCancel} disabled={saving} className="btn-secondary btn-sm">Cancel</button>
      </div>
    </div>
  )
}

function History({ entries }: { entries: RiskRegisterFinding['history'] }) {
  if (entries.length === 0) return <p className="text-[11px] text-gray-400">No history recorded (finding predates change tracking).</p>
  return (
    <ol className="border-l border-gray-200 ml-1 pl-3 space-y-1">
      {[...entries].reverse().map((h, i) => (
        <li key={`${h.at}-${i}`} className="text-[11px] text-gray-500">
          <span className="text-gray-400">{fmtDateTime(h.at)}</span>
          {' · '}<span className="text-gray-600">{h.by}</span>
          {' · '}<span className="font-medium text-gray-700">{h.action}</span>
          {h.note && <span> — {h.note}</span>}
        </li>
      ))}
    </ol>
  )
}

// ── Add risk ─────────────────────────────────────────────────────────────────

function AddRiskForm({ agentId, today, onDone }: { agentId: string; today: string; onDone: () => Promise<void> }) {
  const [category, setCategory] = useState<RiskCategory>('OPERATIONAL')
  const [severity, setSeverity] = useState<RiskSeverity>('MEDIUM')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [owner, setOwner] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (!title.trim()) {
      setError('Give the risk a title.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      await createAgentRisk(agentId, {
        category, severity, title: title.trim(),
        description: description.trim() || undefined,
        owner: owner.trim() || undefined,
        dueDate: dueDate || undefined,
      })
      await onDone()
    } catch (e) {
      setError(errorMessage(e, 'Could not add the risk'))
      setSaving(false)
    }
  }

  return (
    <div className="card p-4 space-y-2">
      <p className="text-xs text-gray-500">
        Risks added here are never changed or closed by a scan. Only a person moves them through the lifecycle.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <label className="text-xs text-gray-500 space-y-1 block">
          <span>Category</span>
          <select className="input w-full text-xs" value={category} onChange={e => setCategory(e.target.value as RiskCategory)}>
            {RISK_CATEGORIES.map(c => <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>)}
          </select>
        </label>
        <label className="text-xs text-gray-500 space-y-1 block">
          <span>Severity</span>
          <select className="input w-full text-xs" value={severity} onChange={e => setSeverity(e.target.value as RiskSeverity)}>
            {RISK_SEVERITIES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
      </div>
      <label className="text-xs text-gray-500 space-y-1 block">
        <span>Title</span>
        <input className="input w-full text-xs" value={title} maxLength={255} onChange={e => setTitle(e.target.value)} />
      </label>
      <label className="text-xs text-gray-500 space-y-1 block">
        <span>Description</span>
        <textarea className={TEXTAREA} value={description} onChange={e => setDescription(e.target.value)} />
      </label>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <label className="text-xs text-gray-500 space-y-1 block">
          <span>Owner</span>
          <input className="input w-full text-xs" value={owner} onChange={e => setOwner(e.target.value)} placeholder="Name or team" />
        </label>
        <label className="text-xs text-gray-500 space-y-1 block">
          <span>Due date</span>
          <input type="date" className="input w-full text-xs" min={today} value={dueDate} onChange={e => setDueDate(e.target.value)} />
        </label>
      </div>
      <ErrorLine text={error} />
      <button onClick={submit} disabled={saving} className="btn-primary btn-sm disabled:opacity-50">
        {saving ? 'Adding…' : 'Add to register'}
      </button>
    </div>
  )
}

// ── Financial (live) ─────────────────────────────────────────────────────────

function FinancialSection({ financial }: { financial: FinancialFinding[] }) {
  const hasDemo = financial.some(f => f.dataSource === 'seed')
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <SectionLabel>Financial findings (live)</SectionLabel>
        {hasDemo && <SourceBadge source="seed" />}
      </div>
      <p className="text-[11px] text-gray-400">
        Read live from cost anomalies, waste findings and the Revenue & Expenditure rules each time this tab loads.
        They are not stored in the register and clear when the underlying condition clears. Visibility only: nothing
        here pauses or limits the agent.
      </p>
      {financial.length === 0 ? (
        <p className="text-xs text-gray-400">No financial findings.</p>
      ) : (
        <div className="space-y-1.5">
          {financial.map((f, i) => (
            <div key={`${f.ruleId}-${f.sourceId ?? i}`} className="flex items-start gap-2 text-xs">
              <SeverityPill severity={f.severity} />
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-gray-700 font-medium">{f.title}</span>
                  <span className="text-gray-400">· {ORIGIN_LABEL[f.origin] || f.origin}</span>
                  {f.dataSource && f.dataSource in SOURCE_BADGE && <SourceBadge source={f.dataSource} />}
                </div>
                {f.description && <p className="text-gray-500">{f.description}</p>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
