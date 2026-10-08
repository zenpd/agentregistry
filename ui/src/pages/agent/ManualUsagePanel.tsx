import { useCallback, useEffect, useState } from 'react'
import { addManualUsage, deleteManualUsage, getManualUsage, importManualUsage, type ManualUsageRow } from '../../services/ops/value'
import { can, useMe } from '../../lib/me'
import { SectionLabel, fmtNumber } from './shared'

function errorMessage(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  return typeof detail === 'string' ? detail : e?.message || fallback
}

// Tokenomics tab → Usage entered by hand: for an agent without tracing, daily calls and
// tokens per model, typed in or imported, so its cost is known. Shown only when no tracing is linked.
export default function ManualUsagePanel({ agentId, onChanged }: { agentId: string; onChanged: () => void }) {
  const me = useMe()
  const [d, setD] = useState<{ allowed: boolean; rows: ManualUsageRow[] } | null>(null)
  const [f, setF] = useState({ day: new Date().toISOString().slice(0, 10), model: '', calls: '', inputTokens: '', outputTokens: '' })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const load = useCallback(() => getManualUsage(agentId).then(r => setD(r.data)).catch(() => setD(null)), [agentId])
  useEffect(() => { load() }, [load])
  async function run(fn: () => Promise<unknown>, done: string) {
    setBusy(true); setMsg(null)
    try { await fn(); setMsg(done); await load(); onChanged() } catch (e) { setMsg(errorMessage(e, 'The usage was not saved')) } finally { setBusy(false) }
  }
  if (!d || !d.allowed) return null
  return (
    <section className="space-y-2 rounded-lg bg-indigo-50/40 px-4 py-3" data-testid="manual-usage">
      <SectionLabel>Usage entered by hand</SectionLabel>
      <p className="text-[13px] text-slate-600">This agent has no tracing link, so the registry cannot read its calls. Enter the daily calls and tokens per model, or import them, and the cost is worked out from the model prices. Linking tracing later replaces these figures.</p>
      {d.rows.length > 0 && (
        <table className="w-full text-[13px]">
          <thead><tr className="text-left text-slate-600 border-b"><th className="py-1">Day</th><th>Model</th><th>Calls</th><th>Input tokens</th><th>Output tokens</th><th /></tr></thead>
          <tbody>
            {d.rows.map(r => (
              <tr key={`${r.day}-${r.model}`} className="border-b border-slate-100" data-testid="manual-row">
                <td className="py-1">{r.day}</td><td>{r.model}</td><td>{fmtNumber(r.calls)}</td><td>{fmtNumber(r.inputTokens)}</td><td>{fmtNumber(r.outputTokens)}</td>
                <td className="text-right">{can(me, 'update') && <button type="button" className="btn-ghost btn-sm" disabled={busy} onClick={() => run(() => deleteManualUsage(agentId, r.day, r.model), 'Row removed.')}>Remove</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {can(me, 'update') && (
        <div className="flex flex-wrap items-end gap-2 text-[12.5px] text-slate-600">
          <label>Day<input type="date" className="input mt-0.5 !w-40 text-sm" value={f.day} onChange={e => setF({ ...f, day: e.target.value })} /></label>
          <label>Model<input className="input mt-0.5 !w-40 text-sm" value={f.model} onChange={e => setF({ ...f, model: e.target.value })} placeholder="gpt-4.1-mini" data-testid="manual-model" /></label>
          <label>Calls<input type="number" min={0} className="input mt-0.5 !w-24 text-sm" value={f.calls} onChange={e => setF({ ...f, calls: e.target.value })} data-testid="manual-calls" /></label>
          <label>Input tokens<input type="number" min={0} className="input mt-0.5 !w-32 text-sm" value={f.inputTokens} onChange={e => setF({ ...f, inputTokens: e.target.value })} /></label>
          <label>Output tokens<input type="number" min={0} className="input mt-0.5 !w-32 text-sm" value={f.outputTokens} onChange={e => setF({ ...f, outputTokens: e.target.value })} /></label>
          <button type="button" className="btn-secondary btn-sm" disabled={busy || !f.model.trim() || f.calls === ''} data-testid="manual-add"
            onClick={() => run(() => addManualUsage(agentId, { day: f.day, model: f.model.trim(), calls: Number(f.calls), inputTokens: Number(f.inputTokens || 0), outputTokens: Number(f.outputTokens || 0) }), 'Saved.')}>Add</button>
          <label className="btn-ghost btn-sm cursor-pointer">Import CSV (day,model,calls,input_tokens,output_tokens)
            <input type="file" accept=".csv,text/csv" className="hidden" onChange={async e => { const file = e.target.files?.[0]; if (file) await run(async () => importManualUsage(agentId, await file.text()), 'Imported.') }} />
          </label>
        </div>
      )}
      {msg && <p className="text-[13px] text-slate-700" role="status">{msg}</p>}
    </section>
  )
}
