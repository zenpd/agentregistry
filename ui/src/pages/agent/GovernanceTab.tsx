import { useCallback, useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  LIFECYCLE_STAGES,
  changeStage,
  createGovernanceException,
  draftReviewNotes,
  getGovernance,
  getStageReadiness,
  recertifyGates,
  updateGateReview,
  type DraftNotes,
  type EvidenceLink,
  type GateKey,
  type GateReview,
  type GateReviewUpdate,
  type GateStatus,
  type GovernanceException,
  type GovernanceState,
  type GovernanceWarning,
  type StageBlockedDetail,
  type StageChangeResult,
  type StageReadiness,
  type Tick,
} from '../../services/ops/governance'
import { Loading, SectionLabel, SourceBadge, STAGE_PILL, fmtNumber, type TabProps } from './shared'

const STATUS_PILL: Record<GateStatus, string> = {
  'Not Submitted': 'bg-gray-100 text-gray-600 ring-gray-200',
  'In Review': 'bg-violet-50 text-violet-700 ring-violet-200',
  'Changes Requested': 'bg-rose-50 text-rose-700 ring-rose-200',
  'Approved with Conditions': 'bg-amber-50 text-amber-700 ring-amber-200',
  Approved: 'bg-teal-50 text-teal-700 ring-teal-200',
}

const RESULT_STYLE: Record<string, { icon: string; className: string; label: string }> = {
  pass: { icon: '✓', className: 'text-teal-600', label: 'Pass' },
  fail: { icon: '✗', className: 'text-rose-600', label: 'Fail' },
  'n/a': { icon: '–', className: 'text-gray-400', label: 'N/A' },
  pending: { icon: '?', className: 'text-amber-600', label: 'To confirm' },
}

const APPROVED: GateStatus[] = ['Approved', 'Approved with Conditions']
const MARKDOWN_CLASS =
  'text-xs text-gray-600 space-y-1 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:list-decimal [&_ol]:pl-4 ' +
  '[&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold [&_h1]:text-gray-700 [&_h2]:text-gray-700 ' +
  '[&_h3]:text-gray-700 [&_strong]:text-gray-700 [&_a]:text-teal-600 [&_a]:underline'

function errorMessage(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d: any) => d.msg || String(d)).join('; ')
  if (detail?.message) return detail.message
  return e?.message || fallback
}

// Expiry and exception dates are whole UTC days on the server; showing them in
// local time would move an end-of-day expiry onto the next date.
function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' })
}

function daysUntil(iso: string): number {
  return Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000)
}

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function Markdown({ text }: { text: string }) {
  return (
    <div className={MARKDOWN_CLASS}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  )
}

function ErrorLine({ text }: { text: string | null }) {
  if (!text) return null
  return <p className="text-xs text-rose-600">{text}</p>
}

function WarningList({ warnings }: { warnings: GovernanceWarning[] }) {
  return (
    <ul className="space-y-1">
      {warnings.map((w, i) => (
        <li key={`${w.code}-${i}`} className="flex items-start gap-1.5 text-xs text-gray-600">
          <span className={w.blocking === false ? 'text-gray-400' : 'text-amber-600'}>{w.blocking === false ? 'ℹ' : '⚠'}</span>
          <span>{w.message}</span>
        </li>
      ))}
    </ul>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function GovernanceTab({ agentId, onChanged }: TabProps) {
  const [state, setState] = useState<GovernanceState | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const res = await getGovernance(agentId)
      setState(res.data)
      setError(null)
    } catch (e) {
      setError(errorMessage(e, 'Could not load governance'))
    }
  }, [agentId])

  useEffect(() => {
    setState(null)
    load()
  }, [load])

  const refresh = useCallback(async () => {
    await load()
    onChanged()
  }, [load, onChanged])

  if (error && !state) {
    return (
      <div className="py-8 text-center space-y-2">
        <p className="text-sm text-rose-600">{error}</p>
        <button onClick={load} className="btn-secondary btn-sm">Retry</button>
      </div>
    )
  }
  if (!state) return <Loading text="Loading governance…" />

  return (
    <div className="space-y-5">
      <EnforcementBanner state={state} />
      {error && <ErrorLine text={`Refresh failed: ${error}`} />}
      <EvidenceSignals state={state} />
      <RecertificationBox state={state} agentId={agentId} onDone={refresh} />
      <ReadinessPanel state={state} agentId={agentId} onDone={refresh} />
      <div className="space-y-3">
        {state.gates.map(g => (
          <GateCard key={g.gate} gate={g} agentId={agentId} onDone={refresh} />
        ))}
      </div>
      <ExceptionsPanel state={state} agentId={agentId} onDone={refresh} />
      <HistoryPanel history={state.history} />
    </div>
  )
}

// ── Evidence signals, history ───────────────────────────────────────────────

function TelemetryLine({ telemetry }: { telemetry: GovernanceState['telemetry'] }) {
  const { phoenixProject, usage, usageSource } = telemetry
  const demoNote = usageSource === 'seed' && (
    <span className="inline-flex items-center gap-1 text-gray-400"><SourceBadge source="seed" /> ignored as evidence</span>
  )
  if (!phoenixProject) {
    return <span className="text-gray-500">No usage data — no Phoenix project linked. {demoNote}</span>
  }
  if (!usage) {
    return (
      <span className="text-gray-500">
        No usage ingested yet from Phoenix project <span className="font-mono">{phoenixProject}</span>. {demoNote}
      </span>
    )
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 text-gray-600">
      <SourceBadge source="phoenix" />
      <span>
        {fmtNumber(usage.calls)} LLM calls in {fmtNumber(usage.runs)} runs, {fmtNumber(usage.errors)} errors, last {usage.days} days;
        most-used model <span className="font-mono">{usage.topModel}</span>
      </span>
    </span>
  )
}

function EvidenceSignals({ state }: { state: GovernanceState }) {
  return (
    <div className="rounded-xl ring-1 ring-gray-100 px-3 py-2.5 space-y-1 text-xs">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-gray-400 w-20 shrink-0">Telemetry</span>
        <TelemetryLine telemetry={state.telemetry} />
      </div>
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-gray-400 w-20 shrink-0">context.md</span>
        <span className="text-gray-500">
          {state.contextPresent
            ? 'Present. Review-note drafts read it as data only; nothing in it changes a gate.'
            : 'Not provided (optional). Checklists and drafts work without it.'}
        </span>
      </div>
    </div>
  )
}

function HistoryPanel({ history }: { history: GovernanceState['history'] }) {
  const [open, setOpen] = useState(false)
  if (history.length === 0) {
    return <p className="text-xs text-gray-400">No governance decisions recorded for this agent yet.</p>
  }
  return (
    <div className="space-y-1.5">
      <button onClick={() => setOpen(v => !v)} className="text-xs text-gray-500 hover:text-gray-700">
        {open ? '▾' : '▸'} Decision history (latest {history.length})
      </button>
      {open && (
        <ul className="divide-y divide-gray-50">
          {history.map((h, i) => (
            <li key={`${h.at}-${i}`} className="flex items-start gap-3 py-1.5 text-xs">
              <span className="text-gray-400 whitespace-nowrap w-24 shrink-0">{fmtDate(h.at)}</span>
              <span className={`flex-1 ${h.action === 'stage_change_blocked' ? 'text-rose-700' : 'text-gray-700'}`}>{h.summary}</span>
              <span className="text-gray-400 truncate max-w-[10rem]" title={h.actor}>{h.actor}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ── Banner, recertification ─────────────────────────────────────────────────

function EnforcementBanner({ state }: { state: GovernanceState }) {
  const warn = state.enforcement === 'warn'
  return (
    <div className={`rounded-xl px-4 py-3 text-xs ring-1 ${warn ? 'bg-sky-50 text-sky-800 ring-sky-200' : 'bg-amber-50 text-amber-800 ring-amber-200'}`}>
      <p className="font-semibold">
        {warn ? 'Stage rules run in warn mode' : 'Stage rules run in block mode'}
      </p>
      <p className="mt-0.5">
        {warn
          ? 'Gaps are reported as warnings; a stage change still goes ahead. Set GOVERNANCE_ENFORCEMENT=block to require the rules (an admin can then override with a reason).'
          : 'A stage change that breaks an entry rule is refused unless an admin gives an override reason.'}
        {' '}Approvals stay valid for {state.validityDays} days (risk tier {state.riskTier}). Every decision here is made by a person; the registry never approves, pauses or stops an agent.
      </p>
    </div>
  )
}

function RecertificationBox({ state, agentId, onDone }: { state: GovernanceState; agentId: string; onDone: () => Promise<void> }) {
  const [confirming, setConfirming] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const { due, reasons } = state.recertification

  async function submit() {
    setBusy(true)
    setErr(null)
    try {
      await recertifyGates(agentId, reason.trim())
      setConfirming(false)
      setReason('')
      await onDone()
    } catch (e) {
      setErr(errorMessage(e, 'Recertify failed'))
    } finally {
      setBusy(false)
    }
  }

  if (!due && !confirming) {
    return (
      <div className="flex items-center justify-between text-xs text-gray-400">
        <span>Recertification: not due.</span>
        <button onClick={() => setConfirming(true)} className="text-teal-600 hover:text-teal-700">Recertify now</button>
      </div>
    )
  }

  return (
    <div className={`rounded-xl px-4 py-3 ring-1 space-y-2 ${due ? 'bg-amber-50 ring-amber-200' : 'bg-gray-50 ring-gray-200'}`}>
      {due && (
        <>
          <p className="text-xs font-semibold text-amber-800">Recertification due</p>
          <ul className="space-y-0.5">
            {reasons.map((r, i) => (
              <li key={`${r.code}-${i}`} className="text-xs text-amber-900">• {r.message}</li>
            ))}
          </ul>
        </>
      )}
      {confirming ? (
        <div className="space-y-2">
          <p className="text-xs text-gray-600">Recertify moves all three gates back to In Review and clears their approval expiry dates. Reviewers then decide again.</p>
          <input className="input text-xs" placeholder="Reason (optional)" value={reason} onChange={e => setReason(e.target.value)} />
          <div className="flex gap-2">
            <button onClick={submit} disabled={busy} className="btn-primary btn-sm">{busy ? 'Recertifying…' : 'Confirm recertify'}</button>
            <button onClick={() => setConfirming(false)} disabled={busy} className="btn-secondary btn-sm">Cancel</button>
          </div>
        </div>
      ) : (
        <button onClick={() => setConfirming(true)} className="btn-secondary btn-sm">Recertify</button>
      )}
      <ErrorLine text={err} />
    </div>
  )
}

// ── Stage readiness ─────────────────────────────────────────────────────────

function ReadinessSummary({ title, readiness }: { title: string; readiness: StageReadiness }) {
  return (
    <div className="rounded-xl bg-gray-50 px-3 py-2.5 space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-gray-700">{title}</span>
        {readiness.ready
          ? <span className="text-[10px] px-1.5 py-0.5 rounded-full ring-1 bg-teal-50 text-teal-700 ring-teal-200">Entry rules met</span>
          : <span className="text-[10px] px-1.5 py-0.5 rounded-full ring-1 bg-amber-50 text-amber-700 ring-amber-200">{readiness.warnings.length} gap(s)</span>}
      </div>
      {readiness.warnings.length > 0 && <WarningList warnings={readiness.warnings} />}
      {readiness.exceptionsApplied.length > 0 && (
        <p className="text-[11px] text-gray-500">Covered by an active exception: {readiness.exceptionsApplied.map(g => g.toUpperCase()).join(', ')}</p>
      )}
    </div>
  )
}

function ReadinessPanel({ state, agentId, onDone }: { state: GovernanceState; agentId: string; onDone: () => Promise<void> }) {
  const { current, next, production } = state.readiness
  const [target, setTarget] = useState('')
  const [preview, setPreview] = useState<StageReadiness | null>(null)
  const [override, setOverride] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [result, setResult] = useState<StageChangeResult | null>(null)
  const [blocked, setBlocked] = useState<StageBlockedDetail | null>(null)

  async function check(stage: string) {
    setTarget(stage)
    setPreview(null)
    setResult(null)
    setBlocked(null)
    setErr(null)
    if (!stage) return
    setBusy(true)
    try {
      setPreview((await getStageReadiness(agentId, stage)).data)
    } catch (e) {
      setErr(errorMessage(e, 'Could not check readiness'))
    } finally {
      setBusy(false)
    }
  }

  async function confirm() {
    setBusy(true)
    setErr(null)
    setBlocked(null)
    try {
      const res = await changeStage(agentId, target, override.trim())
      setResult(res.data)
      setPreview(null)
      setTarget('')
      setOverride('')
      await onDone()
    } catch (e: any) {
      if (e?.response?.status === 409 && e.response.data?.detail?.warnings) setBlocked(e.response.data.detail)
      else setErr(errorMessage(e, 'Stage change failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <SectionLabel>Stage readiness</SectionLabel>
        <span className={STAGE_PILL[current] || 'status-pending'}>{current}</span>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {next && next.target !== 'Production' && <ReadinessSummary title={`Next: ${next.target}`} readiness={next} />}
        <ReadinessSummary title={current === 'Production' ? 'Production (current stage)' : 'Production'} readiness={production} />
      </div>

      <div className="rounded-xl ring-1 ring-gray-100 px-3 py-2.5 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-gray-500">Change stage to</span>
          <select className="input !w-auto text-xs py-1" value={target} onChange={e => check(e.target.value)} disabled={busy}>
            <option value="">Select…</option>
            {LIFECYCLE_STAGES.filter(s => s !== current).map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          {busy && !preview && <span className="text-xs text-gray-400">Checking…</span>}
        </div>

        {preview && (
          <div className="space-y-2">
            {preview.warnings.length === 0
              ? <p className="text-xs text-teal-700">All entry rules for {preview.target} are met.</p>
              : (
                <div className="space-y-1">
                  <p className="text-xs text-gray-600">
                    {preview.blocked
                      ? `Moving to ${preview.target} is blocked until these are resolved (or an admin overrides):`
                      : `Moving to ${preview.target} will go ahead with these warnings:`}
                  </p>
                  <WarningList warnings={preview.warnings} />
                </div>
              )}
            {preview.blocked && (
              <input className="input text-xs" placeholder="Override reason (admin; recorded in the audit log)" value={override} onChange={e => setOverride(e.target.value)} />
            )}
            <div className="flex gap-2">
              <button onClick={confirm} disabled={busy || (preview.blocked && !override.trim())} className="btn-primary btn-sm">
                {busy ? 'Saving…' : `Confirm move to ${preview.target}`}
              </button>
              <button onClick={() => check('')} disabled={busy} className="btn-secondary btn-sm">Cancel</button>
            </div>
          </div>
        )}

        {blocked && (
          <div className="rounded-lg bg-rose-50 px-3 py-2 space-y-1">
            <p className="text-xs text-rose-700">{blocked.message}</p>
            <WarningList warnings={blocked.warnings} />
          </div>
        )}
        {result && (
          <div className="rounded-lg bg-teal-50 px-3 py-2 space-y-1">
            <p className="text-xs text-teal-800">
              Stage changed from {result.from} to {result.to}
              {result.warnings.length > 0 ? ` with ${result.warnings.length} warning(s):` : '.'}
            </p>
            {result.warnings.length > 0 && <WarningList warnings={result.warnings} />}
          </div>
        )}
        <ErrorLine text={err} />
      </div>
    </div>
  )
}

// ── Gate card ───────────────────────────────────────────────────────────────

function ExpiryBadge({ gate }: { gate: GateReview }) {
  if (!APPROVED.includes(gate.status)) return null
  if (!gate.reviewedAt && !gate.expiresAt) {
    return (
      <span title="Approved before review records existed (seeded or legacy data): no reviewer date or expiry on file"
        className="text-[10px] px-1.5 py-0.5 rounded-full ring-1 bg-gray-100 text-gray-600 ring-gray-300">No review record</span>
    )
  }
  if (gate.expiryState === 'expired') {
    return <span className="text-[10px] px-1.5 py-0.5 rounded-full ring-1 bg-rose-50 text-rose-700 ring-rose-200">Expired</span>
  }
  if (gate.expiryState === 'expiring' && gate.expiresAt) {
    return <span className="text-[10px] px-1.5 py-0.5 rounded-full ring-1 bg-amber-50 text-amber-700 ring-amber-200">Expires in {Math.max(0, daysUntil(gate.expiresAt))} d</span>
  }
  return null
}

type Decision = 'approve' | 'conditions' | 'changes'

const DECISION: Record<Decision, { status: GateStatus; label: string }> = {
  approve: { status: 'Approved', label: 'Approve' },
  conditions: { status: 'Approved with Conditions', label: 'Approve with conditions' },
  changes: { status: 'Changes Requested', label: 'Request changes' },
}

function GateCard({ gate, agentId, onDone }: { gate: GateReview; agentId: string; onDone: () => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [decision, setDecision] = useState<Decision | null>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<DraftNotes | null>(null)
  const [showChecklist, setShowChecklist] = useState(false)
  const [approvalWarnings, setApprovalWarnings] = useState<GovernanceWarning[]>([])

  async function save(body: GateReviewUpdate, key: string): Promise<boolean> {
    setBusy(key)
    setErr(null)
    try {
      const res = await updateGateReview(agentId, gate.gate, body)
      setApprovalWarnings(res.data.warnings)
      await onDone()
      return true
    } catch (e) {
      setErr(errorMessage(e, 'Save failed'))
      return false
    } finally {
      setBusy(null)
    }
  }

  async function requestDraft() {
    setBusy('draft')
    setErr(null)
    try {
      setDraft((await draftReviewNotes(agentId, gate.gate)).data)
    } catch (e) {
      setErr(errorMessage(e, 'Could not draft notes'))
    } finally {
      setBusy(null)
    }
  }

  const approved = APPROVED.includes(gate.status)
  const renewable = approved && (gate.expiryState === 'expiring' || gate.expiryState === 'expired' || !gate.expiresAt)
  const s = gate.checklistSummary

  return (
    <div className="rounded-xl ring-1 ring-gray-100 px-4 py-3 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-gray-800">{gate.label}</p>
          <p className="text-[11px] text-gray-400">Accountable: {gate.reviewerRole}</p>
        </div>
        <div className="flex items-center gap-1.5">
          <ExpiryBadge gate={gate} />
          <span className={`text-xs px-2 py-0.5 rounded-full ring-1 font-medium ${STATUS_PILL[gate.status] || STATUS_PILL['Not Submitted']}`}>{gate.status}</span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 text-xs">
        <div><span className="text-gray-400 block">Reviewer</span><span className="text-gray-700">{gate.reviewer || '—'}</span></div>
        <div><span className="text-gray-400 block">Reviewed</span><span className="text-gray-700">{fmtDate(gate.reviewedAt)}</span></div>
        <div>
          <span className="text-gray-400 block">Approval expires</span>
          <span className={gate.expiryState === 'expired' ? 'text-rose-600' : gate.expiryState === 'expiring' ? 'text-amber-700' : 'text-gray-700'}>{fmtDate(gate.expiresAt)}</span>
        </div>
      </div>

      {gate.conditions && (
        <div className="rounded-lg bg-amber-50 px-3 py-2">
          <span className="text-[11px] font-medium text-amber-800">Conditions</span>
          <p className="text-xs text-amber-900 whitespace-pre-wrap">{gate.conditions}</p>
        </div>
      )}
      {gate.notes && (
        <div>
          <SectionLabel>Review notes</SectionLabel>
          <Markdown text={gate.notes} />
        </div>
      )}
      {gate.evidence.length > 0 && (
        <div>
          <SectionLabel>Evidence</SectionLabel>
          <ul className="mt-0.5 space-y-0.5">
            {gate.evidence.map((ev, i) => (
              <li key={i} className="text-xs">
                <a href={ev.url} target="_blank" rel="noopener noreferrer" className="text-teal-600 hover:underline">{ev.label}</a>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <button onClick={() => setShowChecklist(v => !v)} className="flex items-center gap-2 text-xs text-gray-500 hover:text-gray-700">
          <span>{showChecklist ? '▾' : '▸'} Evidence checklist</span>
          <span className="text-gray-400">{s.passed}/{s.total} pass · {s.failed} failing · {s.pending} to confirm · {s.notApplicable} n/a</span>
        </button>
        <div className="mt-1 h-1.5 rounded-full bg-gray-100 overflow-hidden flex">
          <div className="bg-teal-500" style={{ width: `${(100 * s.passed) / Math.max(1, s.total)}%` }} />
          <div className="bg-gray-300" style={{ width: `${(100 * s.notApplicable) / Math.max(1, s.total)}%` }} />
          <div className="bg-rose-400" style={{ width: `${(100 * s.failed) / Math.max(1, s.total)}%` }} />
        </div>
        {showChecklist && (
          <ul className="mt-2 divide-y divide-gray-50">
            {gate.checklist.map(item => {
              const r = RESULT_STYLE[item.result] || RESULT_STYLE.pending
              return (
                <li key={item.id} className="flex items-start gap-2 py-1.5">
                  <span className={`w-4 text-center text-sm leading-4 ${r.className}`} title={r.label}>{r.icon}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-gray-700">{item.label}</p>
                    <p className="text-[11px] text-gray-400">
                      {item.auto === 'manual' ? 'Reviewer confirms' : `Auto check: ${item.auto}`}
                      {item.detail ? ` — ${item.detail}` : ''}
                    </p>
                    <p className="text-[10px] text-gray-300">{item.ref}</p>
                  </div>
                  <select
                    aria-label={`Reviewer tick for ${item.label}`}
                    className="text-[11px] rounded-md border border-gray-200 bg-white px-1 py-0.5 text-gray-600"
                    value={item.tick || ''}
                    disabled={busy !== null}
                    onChange={e => save({ checklist: { [item.id]: (e.target.value || null) as Tick | null } }, 'tick')}
                  >
                    <option value="">{item.auto === 'manual' ? 'Not ticked' : 'Use auto'}</option>
                    <option value="pass">Pass</option>
                    <option value="fail">Fail</option>
                    <option value="n/a">N/A</option>
                  </select>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {approvalWarnings.length > 0 && (
        <div className="rounded-lg bg-gray-50 px-3 py-2 space-y-1">
          <p className="text-[11px] text-gray-500">Recorded. Checklist items still open at approval:</p>
          <WarningList warnings={approvalWarnings} />
        </div>
      )}

      {decision && (
        <DecisionForm gate={gate} decision={decision} busy={busy !== null}
          onCancel={() => setDecision(null)}
          onSubmit={async body => { if (await save(body, 'decision')) setDecision(null) }} />
      )}
      {editing && (
        <EditForm gate={gate} busy={busy !== null}
          onCancel={() => setEditing(false)}
          onSubmit={async body => { if (await save(body, 'edit')) setEditing(false) }} />
      )}
      {draft && (
        <DraftForm draft={draft} busy={busy !== null}
          onDiscard={() => setDraft(null)}
          onSave={async notes => { if (await save({ notes }, 'draft-save')) setDraft(null) }} />
      )}

      {!decision && !editing && (
        <div className="flex flex-wrap gap-1.5">
          {(gate.status === 'Not Submitted' || gate.status === 'Changes Requested') && (
            <button onClick={() => save({ status: 'In Review' }, 'submit')} disabled={busy !== null} className="btn-secondary btn-sm">
              {busy === 'submit' ? 'Submitting…' : 'Submit for review'}
            </button>
          )}
          {(!approved || renewable) && (
            <button onClick={() => setDecision('approve')} disabled={busy !== null} className="btn-secondary btn-sm">
              {renewable ? 'Renew approval' : 'Approve'}
            </button>
          )}
          {gate.status !== 'Approved with Conditions' && (
            <button onClick={() => setDecision('conditions')} disabled={busy !== null} className="btn-secondary btn-sm">Approve with conditions</button>
          )}
          {gate.status !== 'Changes Requested' && (
            <button onClick={() => setDecision('changes')} disabled={busy !== null} className="btn-secondary btn-sm">Request changes</button>
          )}
          <button onClick={() => setEditing(true)} disabled={busy !== null} className="btn-ghost btn-sm">Edit details</button>
          <button onClick={requestDraft} disabled={busy !== null} className="btn-ghost btn-sm">
            {busy === 'draft' ? 'Drafting…' : 'Draft review notes'}
          </button>
        </div>
      )}
      <ErrorLine text={err} />
    </div>
  )
}

function DecisionForm({ gate, decision, busy, onCancel, onSubmit }: {
  gate: GateReview
  decision: Decision
  busy: boolean
  onCancel: () => void
  onSubmit: (body: GateReviewUpdate) => void
}) {
  const [reviewer, setReviewer] = useState(gate.reviewer || '')
  const [conditions, setConditions] = useState(gate.conditions || '')
  const [notes, setNotes] = useState(gate.notes || '')
  const d = DECISION[decision]
  const needsReviewer = decision !== 'changes'
  const invalid = (needsReviewer && !reviewer.trim()) || (decision === 'conditions' && !conditions.trim())

  function submit() {
    const body: GateReviewUpdate = { status: d.status, reviewer: reviewer.trim(), notes }
    if (decision === 'conditions') body.conditions = conditions.trim()
    onSubmit(body)
  }

  return (
    <div className="rounded-lg bg-gray-50 px-3 py-2.5 space-y-2">
      <p className="text-xs font-medium text-gray-700">{d.label} — {gate.label}</p>
      <input className="input text-xs" placeholder={`Accountable reviewer (${gate.reviewerRole})${needsReviewer ? ' — required' : ''}`}
        value={reviewer} onChange={e => setReviewer(e.target.value)} />
      {decision === 'conditions' && (
        <textarea className="input text-xs" rows={3} placeholder="Conditions the owner must meet — required"
          value={conditions} onChange={e => setConditions(e.target.value)} />
      )}
      <textarea className="input text-xs" rows={3} placeholder="Review notes (markdown)" value={notes} onChange={e => setNotes(e.target.value)} />
      {decision !== 'changes' && (
        <p className="text-[11px] text-gray-400">The approval gets an expiry date from the agent's risk tier. Open checklist items are listed after saving; they do not stop the decision.</p>
      )}
      <div className="flex gap-2">
        <button onClick={submit} disabled={busy || invalid} className="btn-primary btn-sm">{busy ? 'Saving…' : `Confirm: ${d.label.toLowerCase()}`}</button>
        <button onClick={onCancel} disabled={busy} className="btn-secondary btn-sm">Cancel</button>
      </div>
    </div>
  )
}

function EditForm({ gate, busy, onCancel, onSubmit }: {
  gate: GateReview
  busy: boolean
  onCancel: () => void
  onSubmit: (body: GateReviewUpdate) => void
}) {
  const [reviewer, setReviewer] = useState(gate.reviewer || '')
  const [notes, setNotes] = useState(gate.notes || '')
  const [conditions, setConditions] = useState(gate.conditions || '')
  const [evidence, setEvidence] = useState<EvidenceLink[]>(gate.evidence)

  const setRow = (i: number, patch: Partial<EvidenceLink>) =>
    setEvidence(rows => rows.map((row, j) => (j === i ? { ...row, ...patch } : row)))
  const cleaned = evidence.filter(ev => ev.label.trim() || ev.url.trim())
  const badUrl = cleaned.some(ev => !/^https?:\/\/\S+$/i.test(ev.url.trim()) || !ev.label.trim())

  function submit() {
    const body: GateReviewUpdate = {
      reviewer: reviewer.trim(),
      notes,
      evidence: cleaned.map(ev => ({ label: ev.label.trim(), url: ev.url.trim() })),
    }
    if (gate.status === 'Approved with Conditions' || gate.conditions) body.conditions = conditions
    onSubmit(body)
  }

  return (
    <div className="rounded-lg bg-gray-50 px-3 py-2.5 space-y-2">
      <p className="text-xs font-medium text-gray-700">Edit {gate.label} details (status unchanged)</p>
      <input className="input text-xs" placeholder={`Reviewer (${gate.reviewerRole})`} value={reviewer} onChange={e => setReviewer(e.target.value)} />
      <textarea className="input text-xs" rows={4} placeholder="Review notes (markdown)" value={notes} onChange={e => setNotes(e.target.value)} />
      {(gate.status === 'Approved with Conditions' || gate.conditions) && (
        <textarea className="input text-xs" rows={2} placeholder="Conditions" value={conditions} onChange={e => setConditions(e.target.value)} />
      )}
      <div className="space-y-1">
        <SectionLabel>Evidence links</SectionLabel>
        {evidence.map((ev, i) => (
          <div key={i} className="flex gap-1.5">
            <input className="input text-xs !w-2/5" placeholder="Label" value={ev.label} onChange={e => setRow(i, { label: e.target.value })} />
            <input className="input text-xs flex-1" placeholder="https://…" value={ev.url} onChange={e => setRow(i, { url: e.target.value })} />
            <button onClick={() => setEvidence(rows => rows.filter((_, j) => j !== i))} className="text-xs text-gray-400 hover:text-rose-600 px-1" aria-label="Remove link">✕</button>
          </div>
        ))}
        <button onClick={() => setEvidence(rows => [...rows, { label: '', url: '' }])} className="text-xs text-teal-600 hover:text-teal-700">+ Add link</button>
        {badUrl && <p className="text-[11px] text-rose-600">Each link needs a label and an http(s) URL.</p>}
      </div>
      <div className="flex gap-2">
        <button onClick={submit} disabled={busy || badUrl} className="btn-primary btn-sm">{busy ? 'Saving…' : 'Save'}</button>
        <button onClick={onCancel} disabled={busy} className="btn-secondary btn-sm">Cancel</button>
      </div>
    </div>
  )
}

function DraftForm({ draft, busy, onDiscard, onSave }: {
  draft: DraftNotes
  busy: boolean
  onDiscard: () => void
  onSave: (notes: string) => void
}) {
  const [text, setText] = useState(draft.draft)
  return (
    <div className="rounded-lg bg-gray-50 px-3 py-2.5 space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs font-medium text-gray-700">Draft review notes</span>
        {draft.llmStatus === 'ok'
          ? <span className="text-[10px] px-1.5 py-0.5 rounded-full ring-1 bg-teal-50 text-teal-700 ring-teal-200">LLM draft</span>
          : <span className="text-[10px] px-1.5 py-0.5 rounded-full ring-1 bg-amber-50 text-amber-700 ring-amber-200" title="Azure OpenAI could not be reached; this draft is built from the checklist and findings">LLM unavailable — rule-based draft</span>}
        {draft.usedContext && <span className="text-[10px] px-1.5 py-0.5 rounded-full ring-1 bg-indigo-50 text-indigo-700 ring-indigo-200">Uses context.md</span>}
      </div>
      <p className="text-[11px] text-gray-400">Not saved yet. Edit it, then save it as this gate's review notes (replaces the current notes).</p>
      <textarea className="input text-xs font-mono" rows={10} value={text} onChange={e => setText(e.target.value)} />
      <div className="flex gap-2">
        <button onClick={() => onSave(text)} disabled={busy || !text.trim()} className="btn-primary btn-sm">{busy ? 'Saving…' : 'Save as review notes'}</button>
        <button onClick={onDiscard} disabled={busy} className="btn-secondary btn-sm">Discard</button>
      </div>
    </div>
  )
}

// ── Exceptions ──────────────────────────────────────────────────────────────

function ExceptionRow({ exc }: { exc: GovernanceException }) {
  const soon = exc.daysLeft !== null && exc.daysLeft < 14
  return (
    <li className="flex items-start justify-between gap-2 py-1.5">
      <div className="min-w-0">
        <p className="text-xs text-gray-700"><span className="font-medium">{exc.gateLabel}</span> — {exc.reason}</p>
        <p className="text-[11px] text-gray-400">Approved by {exc.approvedBy || '—'} · until {fmtDate(exc.expiresAt)}</p>
      </div>
      <span className={`text-[10px] px-1.5 py-0.5 rounded-full ring-1 whitespace-nowrap ${soon ? 'bg-amber-50 text-amber-700 ring-amber-200' : 'bg-gray-50 text-gray-600 ring-gray-200'}`}>
        {exc.daysLeft ?? '—'} d left
      </span>
    </li>
  )
}

function ExceptionsPanel({ state, agentId, onDone }: { state: GovernanceState; agentId: string; onDone: () => Promise<void> }) {
  const today = new Date()
  const maxDate = isoDate(new Date(today.getTime() + state.maxExceptionDays * 86_400_000))
  const minDate = isoDate(new Date(today.getTime() + 86_400_000))
  const [open, setOpen] = useState(false)
  const [gate, setGate] = useState<GateKey>('arb')
  const [reason, setReason] = useState('')
  const [expiresAt, setExpiresAt] = useState(isoDate(new Date(today.getTime() + 30 * 86_400_000)))
  const [approvedBy, setApprovedBy] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function submit() {
    setBusy(true)
    setErr(null)
    try {
      await createGovernanceException(agentId, { gate, reason: reason.trim(), expiresAt, approvedBy: approvedBy.trim() })
      setOpen(false)
      setReason('')
      setApprovedBy('')
      await onDone()
    } catch (e) {
      setErr(errorMessage(e, 'Could not add exception'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <SectionLabel>Active exceptions</SectionLabel>
        {!open && <button onClick={() => setOpen(true)} className="text-xs text-teal-600 hover:text-teal-700">+ Add exception</button>}
      </div>
      {state.exceptions.length === 0
        ? <p className="text-xs text-gray-400">No active exceptions. An exception lets one gate count as met for stage rules, for at most {state.maxExceptionDays} days.</p>
        : <ul className="divide-y divide-gray-50">{state.exceptions.map(e => <ExceptionRow key={e.id} exc={e} />)}</ul>}

      {open && (
        <div className="rounded-lg bg-gray-50 px-3 py-2.5 space-y-2">
          <div className="grid gap-2 sm:grid-cols-3">
            <select className="input text-xs" value={gate} onChange={e => setGate(e.target.value as GateKey)}>
              {state.gates.map(g => <option key={g.gate} value={g.gate}>{g.label}</option>)}
            </select>
            <input type="date" className="input text-xs" min={minDate} max={maxDate} value={expiresAt} onChange={e => setExpiresAt(e.target.value)} />
            <input className="input text-xs" placeholder="Approved by — required" value={approvedBy} onChange={e => setApprovedBy(e.target.value)} />
          </div>
          <textarea className="input text-xs" rows={2} placeholder="Why the gate is waived and what closes it — required" value={reason} onChange={e => setReason(e.target.value)} />
          <p className="text-[11px] text-gray-400">Expires at the end of the chosen day (UTC); at most {state.maxExceptionDays} days from today. The gate itself stays open on the Risk tab.</p>
          <div className="flex gap-2">
            <button onClick={submit} disabled={busy || !reason.trim() || !approvedBy.trim() || !expiresAt} className="btn-primary btn-sm">{busy ? 'Saving…' : 'Add exception'}</button>
            <button onClick={() => setOpen(false)} disabled={busy} className="btn-secondary btn-sm">Cancel</button>
          </div>
          <ErrorLine text={err} />
        </div>
      )}
    </div>
  )
}
