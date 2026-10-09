import { useCallback, useEffect, useState } from 'react'
import { Wrench } from 'lucide-react'
import {
  addApprovedTool, getApprovedTools, removeApprovedTool, updateApprovedTool, type Level,
} from '../services/ops/classification'
import { errorMessage } from '../pages/agent/shared'

type Data = Awaited<ReturnType<typeof getApprovedTools>>['data']

// Settings → Approved tools: each tool, system, database or knowledge base an agent
// may use, with a risk class. An agent's tool class is the highest class among the
// tools it declares, and the classification suggestion is never below it.
export default function ApprovedToolsCard({ canEdit }: { canEdit: boolean }) {
  const [data, setData] = useState<Data | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [form, setForm] = useState({ name: '', kind: 'mcp', riskClass: 'MEDIUM' as Level, note: '' })
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => getApprovedTools().then(r => setData(r.data)).catch(e => setMsg(errorMessage(e, 'Could not load the tool list'))), [])
  useEffect(() => { load() }, [load])
  // Opened from a link to Settings#approved-tools: scroll here once the list is shown.
  useEffect(() => {
    if (data && window.location.hash === '#approved-tools') document.getElementById('approved-tools')?.scrollIntoView({ block: 'start' })
  }, [data])

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true); setMsg(null)
    try { await action(); setMsg(done); await load() } catch (e) { setMsg(errorMessage(e, 'Not saved')) } finally { setBusy(false) }
  }
  if (!data) return <div className="card p-6 text-sm text-slate-600">{msg ?? 'Loading approved tools…'}</div>

  return (
    <div className="card p-6 space-y-4" id="approved-tools" data-testid="approved-tools">
      <div className="flex items-start gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-teal-50 text-teal-600"><Wrench size={20} /></div>
        <div>
          <h3 className="text-[16px] font-extrabold text-slate-900">Approved tools</h3>
          <p className="text-[13px] text-slate-600">
            Tools, systems, databases and knowledge bases agents may use, each with a risk class (LOW, MEDIUM or HIGH).
            An agent's tool class is the highest class among the tools it declares, and its classification suggestion is never below that class.
            Names match what agents declare, ignoring capitals and extra spaces.
          </p>
        </div>
      </div>

      {data.tools.length === 0
        ? <p className="text-sm text-slate-600">The list is empty. {canEdit ? 'Add the tools below, starting from those agents already declare.' : 'A Registry Admin builds it.'}</p>
        : (
          <table className="w-full text-[13px]">
            <thead><tr className="text-left text-slate-600 border-b"><th className="py-1.5">Name</th><th>Kind</th><th>Risk class</th><th>Used by</th><th>Note</th>{canEdit && <th />}</tr></thead>
            <tbody>
              {data.tools.map(t => (
                <tr key={t.id} className="border-b border-slate-100" data-testid="tool-row">
                  <td className="py-1.5 font-medium text-slate-900">{t.name}</td>
                  <td>{t.kindLabel}</td>
                  <td>
                    {canEdit
                      ? <select className="input !w-28 !py-0.5 text-[12.5px]" value={t.riskClass} disabled={busy} aria-label={`Risk class of ${t.name}`}
                          onChange={e => run(() => updateApprovedTool(t.id, { riskClass: e.target.value as Level }), `${t.name} is now ${e.target.value}.`)}>
                          {data.classes.map(c => <option key={c} value={c}>{c}</option>)}
                        </select>
                      : t.riskClass}
                  </td>
                  <td className="text-slate-600">{t.usedBy.length ? `${t.usedBy.length} agent${t.usedBy.length === 1 ? '' : 's'}` : 'No agent declares it'}</td>
                  <td className="text-slate-600">{t.note || '—'}</td>
                  {canEdit && (
                    <td className="text-right">
                      <button type="button" className="btn-ghost btn-sm" disabled={busy}
                        onClick={() => run(() => removeApprovedTool(t.id), `${t.name} is off the list. Agents that declare it show it as not on the approved list.`)}>Remove</button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}

      {canEdit && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-[12.5px] text-slate-600">Name
            <input className="input mt-0.5 !w-56 text-sm" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} data-testid="tool-name" />
          </label>
          <label className="text-[12.5px] text-slate-600">Kind
            <select className="input mt-0.5 !w-48 text-sm" value={form.kind} onChange={e => setForm({ ...form, kind: e.target.value })}>
              {data.kinds.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
            </select>
          </label>
          <label className="text-[12.5px] text-slate-600">Risk class
            <select className="input mt-0.5 !w-28 text-sm" value={form.riskClass} onChange={e => setForm({ ...form, riskClass: e.target.value as Level })} data-testid="tool-class">
              {data.classes.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label className="flex-1 min-w-[180px] text-[12.5px] text-slate-600">Note (optional)
            <input className="input mt-0.5 text-sm" value={form.note} onChange={e => setForm({ ...form, note: e.target.value })} />
          </label>
          <button type="button" className="btn-primary btn-sm" disabled={busy || !form.name.trim()} data-testid="add-tool"
            onClick={() => run(() => addApprovedTool(form), `${form.name.trim()} added as ${form.riskClass}.`).then(() => setForm({ name: '', kind: 'mcp', riskClass: 'MEDIUM', note: '' }))}>
            Add to the list
          </button>
        </div>
      )}

      {canEdit && data.candidates.length > 0 && (
        <div data-testid="tool-candidates">
          <p className="text-[13px] font-semibold text-slate-800">Declared by agents but not on the list ({data.candidates.length})</p>
          <ul className="mt-1 flex flex-wrap gap-1.5">
            {data.candidates.map(c => (
              <li key={c.name}>
                <button type="button" className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[12.5px] text-slate-700 hover:border-zen-300 hover:text-zen-700"
                  title={`Declared by ${c.agents.join(', ')}`} onClick={() => setForm({ ...form, name: c.name, kind: c.kind })}>
                  {c.name} · {c.agents.length} agent{c.agents.length === 1 ? '' : 's'}
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-1 text-[12px] text-slate-500">Pick one to fill the form, choose its risk class, then add it.</p>
        </div>
      )}
      {msg && <p className="text-[13px] text-slate-700" role="status">{msg}</p>}
    </div>
  )
}
