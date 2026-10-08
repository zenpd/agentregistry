import { useCallback, useEffect, useState } from 'react'
import { ExternalLink, Siren } from 'lucide-react'
import { acknowledgeStop, getIncidents, linkIncident, requestStop, resolveIncident, type IncidentRow } from '../../services/ops/compliance'
import { can, useMe } from '../../lib/me'
import { SectionLabel } from './shared'

function errorMessage(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  return typeof detail === 'string' ? detail : e?.message || fallback
}
const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—')
const SEV: Record<string, string> = {
  critical: 'bg-rose-600 text-white', high: 'bg-rose-50 text-rose-700 ring-1 ring-rose-200',
  medium: 'bg-amber-50 text-amber-800 ring-1 ring-amber-200', low: 'bg-slate-100 text-slate-700 ring-1 ring-slate-200',
}

// Risk tab → Incidents and stop requests: incidents linked from PagerDuty, ServiceNow or
// typed in, a request to the owner to stop the agent, and the agent's incident and change history.
export default function IncidentsPanel({ agentId, ownerUserId, backupOwnerUserId }: { agentId: string; ownerUserId?: string | null; backupOwnerUserId?: string | null }) {
  const me = useMe()
  const [d, setD] = useState<Awaited<ReturnType<typeof getIncidents>>['data'] | null>(null)
  const [form, setForm] = useState({ title: '', url: '', severity: 'medium' })
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const load = useCallback(() => getIncidents(agentId).then(r => setD(r.data)).catch(() => setD(null)), [agentId])
  useEffect(() => { load() }, [load])
  const isOwner = !!me && (me.user_id === ownerUserId || me.user_id === backupOwnerUserId || can(me, 'admin'))

  async function run(fn: () => Promise<unknown>, done: string) {
    setBusy(true); setMsg(null)
    try { await fn(); setMsg(done); await load() } catch (e) { setMsg(errorMessage(e, 'The incident change was not saved')) } finally { setBusy(false) }
  }
  if (!d) return null
  return (
    <section className="space-y-2 rounded-xl ring-1 ring-gray-100 p-4" data-testid="incidents">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2"><Siren size={16} className="text-rose-600" /><SectionLabel tip="incident">Incidents and stop requests</SectionLabel></div>
        {can(me, 'update') && !adding && <button type="button" className="btn-secondary btn-sm" onClick={() => setAdding(true)} data-testid="link-incident">Link an incident</button>}
      </div>
      {adding && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 flex flex-wrap items-end gap-2 text-[12.5px] text-slate-600">
          <label className="flex-1 min-w-[220px]">What happened<input className="input mt-0.5 text-sm" value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} data-testid="incident-title" /></label>
          <label className="flex-1 min-w-[260px]">Link to it in PagerDuty or ServiceNow (optional)<input className="input mt-0.5 text-sm" value={form.url} onChange={e => setForm({ ...form, url: e.target.value })} placeholder="https://acme.pagerduty.com/incidents/Q1W2E3" /></label>
          <label>Severity<select className="input mt-0.5 !w-32 text-sm" value={form.severity} onChange={e => setForm({ ...form, severity: e.target.value })} data-testid="incident-severity">
            {['low', 'medium', 'high', 'critical'].map(s => <option key={s} value={s}>{s}</option>)}</select></label>
          <button type="button" className="btn-primary btn-sm" disabled={busy || form.title.trim().length < 3} data-testid="save-incident"
            onClick={() => run(async () => { await linkIncident(agentId, { title: form.title.trim(), url: form.url.trim() || undefined, severity: form.severity }); setForm({ title: '', url: '', severity: 'medium' }); setAdding(false) },
              form.severity === 'high' || form.severity === 'critical' ? 'Linked. The owner and the backup owner were told.' : 'Linked.')}>Link</button>
          <button type="button" className="btn-ghost btn-sm" onClick={() => setAdding(false)}>Cancel</button>
          <span className="w-full text-[12px] text-slate-500">The registry does not read PagerDuty or ServiceNow. Their automation can send incidents to POST /api/v1/incidents/inbound with a registry API key.</span>
        </div>
      )}
      {d.incidents.length === 0 ? <p className="text-[13px] text-slate-500">No incident linked.</p> : (
        <ul className="space-y-2">
          {d.incidents.map((i: IncidentRow) => (
            <li key={i.id} className={`rounded-lg border px-3 py-2 text-[13px] ${i.status === 'open' ? 'border-rose-200 bg-rose-50/30' : 'border-slate-200'}`} data-testid="incident-row">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded-full px-2 py-0.5 text-[12px] font-bold ${SEV[i.severity]}`}>{i.severity}</span>
                <b className="text-slate-900">{i.title}</b>
                <span className="text-slate-500">{i.status === 'open' ? `open since ${fmt(i.openedAt)}` : `resolved ${fmt(i.resolvedAt)}`}</span>
                {i.url && <a href={i.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-zen-700 hover:underline">{i.source === 'pagerduty' ? 'PagerDuty' : i.source === 'servicenow' ? 'ServiceNow' : 'Open'} {i.externalId}<ExternalLink size={12} /></a>}
              </div>
              {i.resolution && <p className="text-slate-600">Resolution: {i.resolution}</p>}
              {i.stop && (
                <p className={i.stop.acknowledgedAt ? 'text-slate-700' : 'font-semibold text-rose-700'} data-testid="stop-state">
                  {i.stop.requestedBy} asked the owner to stop the agent on {fmt(i.stop.requestedAt)}: {i.stop.reason}
                  {i.stop.acknowledgedAt ? ` Acknowledged by ${i.stop.acknowledgedBy} on ${fmt(i.stop.acknowledgedAt)}: ${i.stop.note}` : ' Waiting for the owner.'}
                </p>
              )}
              {can(me, 'update') && (
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <input className="input !w-80 !py-1 text-xs" placeholder="Reason, or what was done (20 characters or more for a stop request, 5 to resolve)" value={notes[i.id] || ''} onChange={e => setNotes({ ...notes, [i.id]: e.target.value })} />
                  {(!i.stop || i.stop.acknowledgedAt) && i.status === 'open' && (
                    <button type="button" className="btn-danger btn-sm" disabled={busy || (notes[i.id] || '').trim().length < 20} data-testid="request-stop"
                      onClick={() => run(async () => { const r = (await requestStop(agentId, i.id, notes[i.id])).data; setNotes({ ...notes, [i.id]: '' }); return r },
                        'The owner was asked to stop the agent.')}>Ask the owner to stop it</button>
                  )}
                  {i.stop && !i.stop.acknowledgedAt && isOwner && (
                    <button type="button" className="btn-primary btn-sm" disabled={busy || (notes[i.id] || '').trim().length < 20} data-testid="ack-stop"
                      onClick={() => run(() => acknowledgeStop(agentId, i.id, notes[i.id]), 'Acknowledged.')}>Acknowledge the stop request</button>
                  )}
                  {i.status === 'open' && (
                    <button type="button" className="btn-secondary btn-sm" disabled={busy || (notes[i.id] || '').trim().length < 5}
                      onClick={() => run(() => resolveIncident(agentId, i.id, notes[i.id]), 'Resolved.')}>Mark resolved</button>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {d.history.length > 0 && (
        <details className="text-[13px]">
          <summary className="cursor-pointer text-slate-600">Incident and change history ({d.history.length})</summary>
          <ul className="mt-1 space-y-0.5">
            {d.history.map((h, n) => <li key={n} className="text-slate-700"><span className="text-slate-500">{fmt(h.at)}</span> · {h.text}{h.by ? ` · ${h.by}` : ''}</li>)}
          </ul>
        </details>
      )}
      {msg && <p className="text-[13px] text-slate-700" role="status">{msg}</p>}
    </section>
  )
}
