import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getEvidence, getToolCallShare, recordAssureRun, type Evidence, type ToolCallShare } from '../../services/ops/lifecycleSteps'
import { can, useMe } from '../../lib/me'

function errorMessage(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  return typeof detail === 'string' ? detail : e?.message || fallback
}

function fmtDate(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : 'an unknown date'
}

// Governance tab → evidence: the AssureAI verdict of the latest recorded run.
// The verdict, its date and a link only: no scores are copied.
export function AssureAiLine({ agentId, onRecorded }: { agentId: string; onRecorded: () => Promise<void> }) {
  const me = useMe()
  const [ev, setEv] = useState<Evidence | null>(null)
  const [runId, setRunId] = useState('')
  const [connectorId, setConnectorId] = useState('')
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const load = useCallback(() => getEvidence(agentId).then(r => setEv(r.data)).catch(() => setEv(null)), [agentId])
  useEffect(() => { load() }, [load])

  async function record() {
    setBusy(true); setMsg(null)
    try {
      const r = (await recordAssureRun(agentId, runId.trim(), connectorId || undefined)).data
      setMsg(r.verdict ? `Recorded: ${r.verdict}.` : `Recorded the run, without a verdict yet: ${r.error}. The daily connector job reads it again.`)
      setRunId(''); setAdding(false); await load(); await onRecorded()
    } catch (e) { setMsg(errorMessage(e, 'Not recorded')) } finally { setBusy(false) }
  }
  if (!ev) return null
  const l = ev.latest
  const pending = ev.runs.filter(r => !r.verdict)
  return (
    <div className="flex flex-wrap items-baseline gap-x-2" data-testid="assureai-line">
      <span className="text-slate-500 w-20 shrink-0">AssureAI</span>
      <span className="text-slate-600 flex-1 min-w-[240px]">
        {l ? (
          <>
            <span className={`mr-1 rounded-full px-2 py-0.5 font-bold ring-1 ${l.verdict === 'pass' ? 'bg-emerald-50 text-emerald-700 ring-emerald-200' : 'bg-rose-50 text-rose-700 ring-rose-200'}`}>
              {l.verdict === 'pass' ? 'Pass' : 'Fail'}
            </span>
            run completed {fmtDate(l.completedAt)}{l.application ? `, AssureAI application ${l.application}` : ''}.{' '}
            {l.url && <a href={l.url} target="_blank" rel="noreferrer" className="text-zen-700 hover:underline">Open the run in AssureAI</a>}
          </>
        ) : 'No AssureAI verdict recorded (AssureAI is the testing tool for AI applications).'}
        {ev.requiredForProduction && (!l || l.verdict !== 'pass') && <span className="ml-1 font-semibold text-amber-800">Production needs a pass verdict.</span>}
        {pending.length > 0 && <span className="block text-amber-800">Waiting for a verdict: {pending.map(p => `run ${p.runId.slice(0, 8)}… (${p.error})`).join(', ')}</span>}
        {ev.connectors.length === 0 && (
          <span className="block">{can(me, 'admin') ? <><Link to="/settings" className="text-zen-700 hover:underline">Add an AssureAI connector in Settings</Link> with the application's run key to read verdicts.</> : 'A Registry Admin adds an AssureAI connector in Settings to read verdicts.'}</span>
        )}
        {ev.connectors.length > 0 && can(me, 'update') && !adding && (
          <button type="button" className="ml-1 text-zen-700 hover:underline" onClick={() => setAdding(true)} data-testid="record-run">Record a run</button>
        )}
        {adding && (
          <span className="mt-1 flex flex-wrap items-center gap-1.5">
            <input className="input !w-80 !py-1 text-xs" value={runId} onChange={e => setRunId(e.target.value)} placeholder="AssureAI run id" data-testid="run-id" />
            {ev.connectors.length > 1 && (
              <select className="input !w-48 !py-1 text-xs" value={connectorId} onChange={e => setConnectorId(e.target.value)}>
                <option value="">Which AssureAI application?</option>
                {ev.connectors.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            )}
            <button type="button" className="btn-primary btn-sm" disabled={busy || !runId.trim() || (ev.connectors.length > 1 && !connectorId)} onClick={record} data-testid="save-run">Record the run</button>
            <button type="button" className="btn-ghost btn-sm" onClick={() => setAdding(false)}>Cancel</button>
            <span className="w-full text-[12px] text-slate-500">A CI pipeline records it with POST /api/v1/agents/{agentId}/evidence/assureai and a registry API key that has the register permission.</span>
          </span>
        )}
        {msg && <span className="block text-slate-700" role="status">{msg}</span>}
      </span>
    </div>
  )
}

// Governance tab → evidence: the share of traced tool calls that go to tools
// approved at the last Security Review.
export function ToolCallsLine({ agentId }: { agentId: string }) {
  const [d, setD] = useState<ToolCallShare | null>(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback((refresh = false) => {
    setBusy(true)
    return getToolCallShare(agentId, refresh).then(r => setD(r.data)).catch(() => setD(null)).finally(() => setBusy(false))
  }, [agentId])
  useEffect(() => { load() }, [load])
  if (!d) return null
  return (
    <div className="flex flex-wrap items-baseline gap-x-2" data-testid="tool-calls-line">
      <span className="text-slate-500 w-20 shrink-0">Tool calls</span>
      <span className="text-slate-600 flex-1 min-w-[240px]">
        {d.status === 'ok' ? (
          <>
            <b className={d.share === 100 ? 'text-emerald-700' : 'text-amber-800'}>{d.share}%</b> of {d.total} traced tool calls
            ({d.approved} calls) went to tools or MCP servers approved at the last Security Review
            {d.approvedAt ? ` (${fmtDate(d.approvedAt)})` : ''}. Read from the latest {d.sampleLimit} spans
            {d.sampleWindow?.from ? `, ${fmtDate(d.sampleWindow.from)} to ${fmtDate(d.sampleWindow.to)}` : ''}.
            {d.notApproved && d.notApproved.length > 0 && (
              <span className="block text-amber-800">Not approved: {d.notApproved.map(n => `${n.name} (${n.count})`).join(', ')}.</span>
            )}
          </>
        ) : d.status === 'no_tool_calls'
          ? <>No tool call in the latest {d.sampleLimit} traced spans.</>
          : d.message}
        <button type="button" className="ml-1 text-zen-700 hover:underline" disabled={busy} onClick={() => load(true)}>{busy ? 'Reading…' : 'Read again'}</button>
      </span>
    </div>
  )
}
