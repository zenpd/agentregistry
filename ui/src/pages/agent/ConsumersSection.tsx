import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getConsumers, observeConsumers, type Consumers } from '../../services/ops/reuse'
import { can, useMe } from '../../lib/me'
import InfoTip from '../../components/InfoTip'

const PILL: Record<string, string> = {
  both: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  approved_not_calling: 'bg-amber-50 text-amber-800 ring-amber-200',
  calling_not_approved: 'bg-rose-50 text-rose-700 ring-rose-200',
  declared_only: 'bg-slate-100 text-slate-700 ring-slate-200',
}
const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—')

// Integrate tab → Consumers: every consumer as approved, seen in traces or both,
// with the calls seen, and the teams that call without approval.
export default function ConsumersSection({ agentId, dataVersion }: { agentId: string; dataVersion: number }) {
  const me = useMe()
  const [d, setD] = useState<Consumers | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const load = useCallback(() => getConsumers(agentId).then(r => setD(r.data)).catch(() => setD(null)), [agentId])
  useEffect(() => { load() }, [load, dataVersion])

  async function observe() {
    setBusy(true); setMsg(null)
    try {
      const r = (await observeConsumers(agentId)).data
      setMsg(r.status === 'ok' ? 'Callers read from the latest traces.' : `Not read: ${r.error || (r.summary as { reason?: string } | undefined)?.reason || r.status}.`)
      await load()
    } catch (e: any) { setMsg(e?.response?.data?.detail || 'Not read') } finally { setBusy(false) }
  }
  if (!d) return null
  return (
    <section className="rounded-2xl border border-slate-200/80 bg-white p-5 space-y-3 shadow-sm" data-testid="consumers">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <span className="mt-1 h-4 w-1 shrink-0 rounded-full bg-gradient-to-b from-zen-400 to-zen-700" aria-hidden />
          <div>
            <h3 className="text-[16px] font-extrabold text-slate-900">Consumers <InfoTip term="consumers" /></h3>
            <p className="text-[13px] text-slate-600 mt-0.5">
              Teams and agents that use this one: approved through an access request, declared by the owner, or seen calling it in the traces. A calling team is recognised when it sets the
              span attribute <code className="font-mono text-zen-700">{d.attribute}</code> to its name. Another registered agent is recognised when its traces call this one by name.
              {d.observedAt ? ` Callers last read ${fmt(d.observedAt)}, from the latest trace sample.` : d.linked ? ' Callers have not been read yet.' : ' No Phoenix project is linked, so no call can be seen.'}
            </p>
          </div>
        </div>
        {can(me, 'update') && d.linked && (
          <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={observe} data-testid="observe-consumers">{busy ? 'Reading…' : 'Read callers now'}</button>
        )}
      </div>
      <div className="flex flex-wrap gap-4 text-[13px] text-slate-700">
        <span><b>{d.buildsAvoided}</b> team{d.buildsAvoided === 1 ? '' : 's'} reuse it instead of building their own (approved access).</span>
        <span>Time to first call: <b>{d.medianDaysToFirstCall === null ? 'not measured yet' : `${d.medianDaysToFirstCall} days`}</b> (median, from approval to the first call seen).</span>
        {d.startedFrom && <span>Started from the certified agent <Link to={`/agents/${d.startedFrom.id}`} className="text-zen-700 hover:underline">{d.startedFrom.name}</Link>.</span>}
      </div>
      {d.consumers.length === 0
        ? <p className="text-[13px] text-slate-500">No consumer is approved, declared or seen yet.</p>
        : (
          <table className="w-full text-[13px]">
            <thead><tr className="text-left text-slate-600 border-b"><th className="py-1.5">Consumer</th><th>Status</th><th>Calls in the latest sample</th><th>Last call seen</th><th>Approved</th></tr></thead>
            <tbody>
              {d.consumers.map(c => (
                <tr key={c.name} className="border-b border-slate-100" data-testid="consumer-row">
                  <td className="py-1.5 font-medium text-slate-900">
                    {c.callerAgentId ? <Link to={`/agents/${c.callerAgentId}`} className="text-zen-700 hover:underline">{c.name}</Link> : c.name}
                    {c.kind === 'agent' && <span className="ml-1 text-[12px] text-slate-500">(agent)</span>}
                  </td>
                  <td><span className={`rounded-full px-2 py-0.5 text-[12px] font-semibold ring-1 ${PILL[c.status]}`}>{c.statusText}</span></td>
                  <td>{c.seen ? c.calls ?? 0 : '—'}</td>
                  <td>{fmt(c.lastSeen)}</td>
                  <td>{c.approved ? fmt(c.approvedAt) : c.declared ? 'Declared only' : 'No'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      {d.callingNotApproved.length > 0 && (
        <p className="text-[13px] text-rose-700">Calling without approval: {d.callingNotApproved.join(', ')}. Ask them to request access.</p>
      )}
      <Link to="/dependencies" className="inline-block text-xs text-zen-700 hover:underline">Open the dependency graph →</Link>
      {msg && <p className="text-[13px] text-slate-700" role="status">{msg}</p>}
    </section>
  )
}
