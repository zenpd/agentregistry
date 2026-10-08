import { useCallback, useEffect, useState } from 'react'
import { Archive, CheckCircle2, Circle, Clock, HelpCircle } from 'lucide-react'
import { getAgents } from '../../services/api'
import {
  cancelRetirement, confirmRetirementStep, finishRetirement, getRetirement, revokeForRetirement, startRetirement,
  type Retirement, type RetirementStep,
} from '../../services/ops/lifecycleSteps'
import { can, notAllowed, useMe } from '../../lib/me'
import { SectionLabel } from './shared'

function errorMessage(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  return typeof detail === 'string' ? detail : e?.message || fallback
}

const ICON: Record<RetirementStep['state'], JSX.Element> = {
  done: <CheckCircle2 size={16} className="text-emerald-600" />,
  waiting: <Clock size={16} className="text-amber-600" />,
  needs_confirmation: <HelpCircle size={16} className="text-violet-600" />,
  todo: <Circle size={16} className="text-slate-400" />,
}

// Governance tab → Retire this agent: checked steps, each recorded. The stage
// becomes Deprecated only here.
export default function RetirementPanel({ agentId, onDone }: { agentId: string; onDone: () => Promise<void> }) {
  const me = useMe()
  const [r, setR] = useState<Retirement | null>(null)
  const [agents, setAgents] = useState<{ id: string; name: string }[]>([])
  const [starting, setStarting] = useState(false)
  const [reason, setReason] = useState('')
  const [replacement, setReplacement] = useState('')
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => getRetirement(agentId).then(x => setR(x.data)).catch(e => setError(errorMessage(e, 'Could not load the retirement steps'))), [agentId])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (starting && agents.length === 0) getAgents(1, 100).then(x => setAgents(x.data.data.filter(a => a.id !== agentId && a.stage !== 'Deprecated'))).catch(() => setAgents([]))
  }, [starting, agents.length, agentId])

  async function act(fn: () => Promise<{ data: Retirement }>, refreshAgent = false) {
    setBusy(true); setError(null)
    try { setR((await fn()).data); if (refreshAgent) await onDone() } catch (e) { setError(errorMessage(e, 'The retirement step was not saved')) } finally { setBusy(false) }
  }
  if (!r) return error ? <p className="text-sm text-rose-600">{error}</p> : null
  const allowed = can(me, 'update')

  return (
    <div className="rounded-xl ring-1 ring-gray-100 p-4 space-y-3" id="retirement" data-testid="retirement">
      <div className="flex items-center gap-2">
        <Archive size={16} className="text-slate-600" />
        <SectionLabel tip="retirement">Retire this agent</SectionLabel>
      </div>

      {r.stage === 'Deprecated' && !r.active && <p className="text-sm text-slate-700">This agent is retired (stage Deprecated).</p>}

      {r.stage !== 'Deprecated' && !r.active && !starting && (
        <div className="text-[13px] text-slate-600 space-y-2">
          <p>
            Retiring runs four checked steps: no calls for {r.quietDays} days, consumers told, keys and access revoked, then the stage is set to Deprecated.
            Each step is recorded with who and when.
          </p>
          {allowed
            ? <button type="button" className="btn-secondary btn-sm" onClick={() => setStarting(true)} data-testid="start-retirement">Start retiring this agent</button>
            : me && <p className="text-slate-500">{notAllowed(me, 'retire an agent')}</p>}
        </div>
      )}

      {starting && !r.active && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 space-y-2">
          <label className="block text-[12.5px] text-slate-600">Why is it retired? (at least 20 characters, sent to the teams that use it)
            <input className="input mt-0.5 text-sm" value={reason} onChange={e => setReason(e.target.value)} data-testid="retire-reason" />
          </label>
          <label className="block text-[12.5px] text-slate-600">Replaced by (optional)
            <select className="input mt-0.5 text-sm" value={replacement} onChange={e => setReplacement(e.target.value)}>
              <option value="">No replacement</option>
              {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </label>
          <div className="flex gap-2">
            <button type="button" className="btn-primary btn-sm" disabled={busy || reason.trim().length < 20}
              onClick={() => act(() => startRetirement(agentId, reason.trim(), replacement)).then(() => setStarting(false))} data-testid="confirm-start">
              Start and tell the consumers
            </button>
            <button type="button" className="btn-ghost btn-sm" onClick={() => setStarting(false)}>Cancel</button>
          </div>
        </div>
      )}

      {r.active && (
        <div className="space-y-2">
          <p className="text-[13px] text-slate-700">
            Started by {r.active.startedBy} on {r.active.startedAt ? new Date(r.active.startedAt).toLocaleDateString() : '—'}: {r.active.reason}
            {r.active.replacement && <> Replaced by <b>{r.active.replacement.name}</b>.</>}
          </p>
          <ol className="space-y-2">
            {r.active.steps.map((s, i) => (
              <li key={s.key} className="flex items-start gap-2" data-testid={`step-${s.key}`}>
                <span className="mt-0.5">{ICON[s.state]}</span>
                <div className="flex-1 text-[13px]">
                  <span className="font-semibold text-slate-900">{i + 1}. {s.label}</span>
                  <span className="ml-2 text-slate-600">{s.detail}</span>
                  {s.state === 'needs_confirmation' && allowed && (s.key === 'traffic' || s.key === 'consumers') && (
                    <span className="mt-1 flex flex-wrap gap-1.5">
                      <input className="input !w-96 !py-1 text-xs" placeholder="How you checked (at least 20 characters)" value={notes[s.key] || ''}
                        onChange={e => setNotes({ ...notes, [s.key]: e.target.value })} />
                      <button type="button" className="btn-secondary btn-sm" disabled={busy || (notes[s.key] || '').trim().length < 20}
                        onClick={() => act(() => confirmRetirementStep(agentId, s.key as 'traffic' | 'consumers', notes[s.key]))}>Confirm</button>
                    </span>
                  )}
                  {s.key === 'access' && s.state === 'todo' && allowed && (
                    <button type="button" className="ml-2 btn-secondary btn-sm" disabled={busy} onClick={() => act(() => revokeForRetirement(agentId))} data-testid="revoke">
                      Revoke keys and access
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ol>
          {allowed && (
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn-danger btn-sm" disabled={busy || !r.active.canFinish} onClick={() => act(() => finishRetirement(agentId), true)} data-testid="finish-retirement">
                Finish: set the stage to Deprecated
              </button>
              <button type="button" className="btn-ghost btn-sm" disabled={busy}
                onClick={() => act(() => cancelRetirement(agentId, 'Cancelled from the Governance tab'))}>Cancel the retirement</button>
            </div>
          )}
        </div>
      )}
      {r.history.length > 0 && (
        <p className="text-[12.5px] text-slate-500">
          Earlier: {r.history.map(h => `${h.status === 'done' ? 'retired' : 'cancelled'} ${h.completedAt ? new Date(h.completedAt).toLocaleDateString() : ''} (${h.reason})`).join(' · ')}
        </p>
      )}
      {error && <p className="text-[13px] text-rose-700">{error}</p>}
    </div>
  )
}
