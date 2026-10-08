import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Download, ScrollText } from 'lucide-react'
import { downloadAuditCsv, getAuditOptions, getAuditTrail, type AuditFilter, type AuditRow } from '../services/ops/audit'
import { errorMessage } from './agent/shared'
import { can, notAllowed, useMe } from '../lib/me'

const KINDS: { id: NonNullable<AuditFilter['kind']>; label: string }[] = [
  { id: 'people', label: 'By people' },
  { id: 'machine', label: 'By the registry' },
  { id: 'all', label: 'Everything' },
]

function when(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })} ${d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`
}

// Every recorded change, decision and automatic action. The filter lives in the
// address bar, so an agent page can link to "its" trail and a view can be shared.
export default function AuditPage() {
  const me = useMe()
  const [params, setParams] = useSearchParams()
  const filter: AuditFilter = {
    kind: (params.get('kind') as AuditFilter['kind']) || 'people',
    category: params.get('category') || '', actor: params.get('actor') || '', action: params.get('action') || '',
    entity: params.get('entity') || '', from: params.get('from') || '', to: params.get('to') || '', q: params.get('q') || '',
  }
  const key = params.toString()
  const [rows, setRows] = useState<AuditRow[] | null>(null)
  const [total, setTotal] = useState(0)
  const [next, setNext] = useState<number | null>(null)
  const [options, setOptions] = useState<{ actors: { id: string; label: string }[]; actions: { id: string; label: string }[]; categories: string[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [q, setQ] = useState(filter.q || '')

  const set = (k: keyof AuditFilter, v: string) => {
    const p = new URLSearchParams(params)
    v ? p.set(k, v) : p.delete(k)
    setParams(p, { replace: true })
  }

  const load = useCallback(async (more: boolean) => {
    setBusy(true)
    try {
      const r = (await getAuditTrail(filter, more ? next : null)).data
      setRows(prev => (more && prev ? [...prev, ...r.rows] : r.rows))
      setTotal(r.total)
      setNext(r.nextBeforeId)
      setError(null)
    } catch (e) {
      setError(errorMessage(e, 'Could not load the audit trail'))
    } finally {
      setBusy(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, next])

  useEffect(() => { if (me && can(me, 'audit')) load(false) }, [key, me]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (me && can(me, 'audit')) getAuditOptions().then(r => setOptions(r.data)).catch(() => {}) }, [me])
  useEffect(() => { const t = setTimeout(() => { if (q !== (filter.q || '')) set('q', q) }, 350); return () => clearTimeout(t) }, [q]) // eslint-disable-line react-hooks/exhaustive-deps

  if (me && !can(me, 'audit')) {
    return <div className="card p-6 text-sm text-slate-700">{notAllowed(me, 'open the audit trail')} A Registry Admin or an Auditor can.</div>
  }

  const sel = 'input !w-auto !py-1.5 text-[13px]'
  return (
    <div className="space-y-4 animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="text-2xl font-bold gradient-text flex items-center gap-2"><ScrollText size={22} className="text-zen-600" /> Audit Trail</h1>
          <p className="text-slate-600 mt-0.5">Every change, decision and automatic action the registry recorded. Nothing here can be edited.</p>
        </div>
        <button type="button" className="btn-secondary flex items-center gap-1.5" disabled={busy}
          onClick={() => downloadAuditCsv(filter).catch(e => setError(errorMessage(e, 'The export failed')))} data-testid="audit-export"
          title="Downloads the rows that match the current filter (at most 20,000). The export itself is recorded.">
          <Download size={16} /> Export CSV
        </button>
      </div>

      <div className="card p-3 flex flex-wrap items-center gap-2" data-testid="audit-filters">
        <div className="flex rounded-lg bg-slate-100 p-0.5">
          {KINDS.map(k => (
            <button key={k.id} type="button" onClick={() => set('kind', k.id)}
              className={`rounded-md px-3 py-1 text-[13px] font-semibold ${filter.kind === k.id ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'}`}>{k.label}</button>
          ))}
        </div>
        <select className={sel} value={filter.category} onChange={e => set('category', e.target.value)} aria-label="Category">
          <option value="">All categories</option>
          {options?.categories.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <select className={sel} value={filter.actor} onChange={e => set('actor', e.target.value)} aria-label="Who">
          <option value="">Anyone</option>
          {options?.actors.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}
        </select>
        <select className={sel} value={filter.action} onChange={e => set('action', e.target.value)} aria-label="Action">
          <option value="">Any action</option>
          {options?.actions.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}
        </select>
        <label className="text-[13px] text-slate-600">From <input type="date" className={sel} value={filter.from} onChange={e => set('from', e.target.value)} /></label>
        <label className="text-[13px] text-slate-600">To <input type="date" className={sel} value={filter.to} onChange={e => set('to', e.target.value)} /></label>
        <input className="input !w-48 !py-1.5 text-[13px]" placeholder="Search action or id" value={q} onChange={e => setQ(e.target.value)} />
        {filter.entity && (
          <span className="rounded-full bg-zen-50 px-2.5 py-1 text-[12.5px] font-semibold text-zen-700 ring-1 ring-zen-200">
            Only {rows?.find(r => r.entityId === filter.entity)?.entityName || filter.entity}
            <button type="button" className="ml-1.5 opacity-70 hover:opacity-100" onClick={() => set('entity', '')} aria-label="Clear">✕</button>
          </span>
        )}
      </div>

      {error && <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[13px] text-rose-700">{error}</div>}

      <div className="card overflow-x-auto">
        <div className="px-4 pt-3 text-[13px] text-slate-600" data-testid="audit-count">
          {rows === null ? 'Loading…' : `Showing ${rows.length} of ${total.toLocaleString()} matching event${total === 1 ? '' : 's'}, newest first.`}
        </div>
        <table className="w-full text-sm mt-2" data-testid="audit-table">
          <thead>
            <tr className="text-left text-slate-600 border-b">
              <th className="p-3 whitespace-nowrap">When</th><th className="p-3">Who</th><th className="p-3">Category</th>
              <th className="p-3">What</th><th className="p-3">Record</th><th className="p-3">Details</th>
            </tr>
          </thead>
          <tbody>
            {rows?.map(r => (
              <tr key={r.id} className="border-b last:border-0 align-top">
                <td className="p-3 whitespace-nowrap text-slate-700">{when(r.at)}</td>
                <td className="p-3">
                  <div className="font-medium text-slate-900">{r.actor}</div>
                  {r.kind === 'machine' && <div className="text-[12px] text-slate-500">automatic</div>}
                </td>
                <td className="p-3"><span className="whitespace-nowrap rounded-full bg-slate-100 px-2 py-0.5 text-[12px] font-semibold text-slate-700">{r.category}</span></td>
                <td className="p-3 text-slate-900">{r.actionLabel}</td>
                <td className="p-3">
                  {r.entityType === 'agent' && r.entityId
                    ? <Link to={`/agents/${r.entityId}`} className="text-zen-700 hover:underline">{r.entityName || r.entityId}</Link>
                    : <span className="text-slate-700">{r.entityType}{r.entityId ? ` · ${r.entityId}` : ''}</span>}
                </td>
                <td className="p-3 text-slate-700 max-w-[360px] break-words">{r.summary}</td>
              </tr>
            ))}
            {rows && rows.length === 0 && (
              <tr><td colSpan={6} className="p-6 text-center text-slate-600">No recorded events match this filter.</td></tr>
            )}
          </tbody>
        </table>
        {next && (
          <div className="p-3 text-center">
            <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={() => load(true)}>{busy ? 'Loading…' : 'Load more'}</button>
          </div>
        )}
      </div>
    </div>
  )
}
