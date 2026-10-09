import { useCallback, useEffect, useState } from 'react'
import { getOutcomes, getWhatIf, importOutcomes, recordOutcome, type Outcomes, type WhatIf } from '../../services/ops/value'
import { can, useMe } from '../../lib/me'
import { SectionLabel, fmtCents, fmtNumber } from './shared'

function errorMessage(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  return typeof detail === 'string' ? detail : e?.message || fallback
}

// Revenue tab → Measured outcomes: counts from a CSV file, a webhook or typed in,
// and the cost of each outcome over the last 30 days.
export function MeasuredOutcomes({ agentId }: { agentId: string }) {
  const me = useMe()
  const [d, setD] = useState<Outcomes | null>(null)
  const [form, setForm] = useState({ outcome: '', count: '', day: '' })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const load = useCallback(() => getOutcomes(agentId).then(r => setD(r.data)).catch(() => setD(null)), [agentId])
  useEffect(() => { load() }, [load])

  async function add() {
    setBusy(true); setMsg(null)
    try { await recordOutcome(agentId, form.outcome.trim(), Number(form.count), form.day || undefined); setForm({ outcome: '', count: '', day: '' }); await load() }
    catch (e) { setMsg(errorMessage(e, 'The outcome was not saved')) } finally { setBusy(false) }
  }
  async function upload(file: File) {
    setBusy(true); setMsg(null)
    try { const r = await importOutcomes(agentId, await file.text()); setMsg(`${r.data.stored} rows imported.`); await load() }
    catch (e) { setMsg(errorMessage(e, 'Not imported')) } finally { setBusy(false) }
  }
  if (!d) return null
  return (
    <section className="space-y-2" data-testid="measured-outcomes">
      <SectionLabel tip="measured_outcome">Measured outcomes and cost per outcome</SectionLabel>
      <p className="text-[13px] text-slate-600">
        Counts of what the agent achieved, such as invoices matched, from {d.from} to {d.to}. Cost per outcome is the token cost of these days
        ({d.tokenCostCents === null ? 'unknown' : fmtCents(d.tokenCostCents)}) plus hosting for the same share of the month ({fmtCents(d.infraCostCents)}),
        divided by the count.
      </p>
      {d.outcomes.length === 0
        ? <p className="text-[13px] text-slate-500">No outcome recorded in the last {d.days} days.</p>
        : (
          <table className="w-full text-[13px]">
            <thead><tr className="text-left text-slate-600 border-b"><th className="py-1">Outcome</th><th>Count</th><th>Cost per outcome</th></tr></thead>
            <tbody>
              {d.outcomes.map(o => (
                <tr key={o.outcome} className="border-b border-slate-100" data-testid="outcome-row">
                  <td className="py-1 font-medium text-slate-900">{o.outcome}</td><td>{fmtNumber(o.count)}</td>
                  <td>{o.costPerOutcomeCents === null ? 'Cost unknown' : fmtCents(o.costPerOutcomeCents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      {can(me, 'update') && (
        <div className="flex flex-wrap items-end gap-2 text-[12.5px] text-slate-600">
          <label>Outcome<input className="input mt-0.5 !w-48 text-sm" value={form.outcome} onChange={e => setForm({ ...form, outcome: e.target.value })} placeholder="invoice matched" data-testid="outcome-name" /></label>
          <label>Count<input className="input mt-0.5 !w-24 text-sm" type="number" min={0} value={form.count} onChange={e => setForm({ ...form, count: e.target.value })} data-testid="outcome-count" /></label>
          <label>Day (empty: today)<input className="input mt-0.5 !w-40 text-sm" type="date" value={form.day} onChange={e => setForm({ ...form, day: e.target.value })} /></label>
          <button type="button" className="btn-secondary btn-sm" disabled={busy || !form.outcome.trim() || form.count === ''} onClick={add} data-testid="add-outcome">Add</button>
          <label className="btn-ghost btn-sm cursor-pointer">Import CSV (day,outcome,count)
            <input type="file" accept=".csv,text/csv" className="hidden" onChange={e => e.target.files?.[0] && upload(e.target.files[0])} data-testid="outcome-csv" />
          </label>
        </div>
      )}
      <p className="text-[12px] text-slate-500">An app can send counts itself: POST /api/v1/agents/{agentId}/outcomes with {'{"outcome": "invoice matched", "count": 120}'} and a registry API key that has the register permission.</p>
      {msg && <p className="text-[13px] text-slate-700" role="status">{msg}</p>}
    </section>
  )
}

// Revenue tab → Other models: the last 30 days of tokens priced at every model in the price list.
export function ModelWhatIf({ agentId }: { agentId: string }) {
  const [pct, setPct] = useState(0)
  const [d, setD] = useState<WhatIf | null>(null)
  useEffect(() => { getWhatIf(agentId, pct).then(r => setD(r.data)).catch(() => setD(null)) }, [agentId, pct])
  if (!d) return null
  if (d.source === 'none' || (d.tokens.input + d.tokens.output) === 0) {
    return (
      <section className="space-y-1" data-testid="model-whatif">
        <SectionLabel>The same work on other models</SectionLabel>
        <p className="text-[13px] text-slate-500">No token usage in the last {d.days} days to price.</p>
      </section>
    )
  }
  return (
    <section className="space-y-2" data-testid="model-whatif">
      <SectionLabel>The same work on other models</SectionLabel>
      <p className="text-[13px] text-slate-600">
        The last {d.days} days used {fmtNumber(d.tokens.input)} input and {fmtNumber(d.tokens.output)} output tokens on {d.modelsUsed.join(', ')}, costing {fmtCents(d.currentCents)}.
        Below, the same tokens at each model's list price. <b>{d.caveat}</b>
      </p>
      <label className="flex items-center gap-2 text-[13px] text-slate-700">
        Price change for every model: <input type="range" min={-50} max={50} step={5} value={pct} onChange={e => setPct(Number(e.target.value))} aria-label="Price change" />
        <span className="w-14">{pct > 0 ? '+' : ''}{pct}%</span>
        {pct !== 0 && <span>Current cost would be {fmtCents(d.currentAfterChangeCents)}.</span>}
      </label>
      <table className="w-full text-[13px]">
        <thead><tr className="text-left text-slate-600 border-b"><th className="py-1">Model</th><th>Cost of the same tokens</th><th>Against today</th></tr></thead>
        <tbody>
          {d.models.map(m => (
            <tr key={m.model} className={`border-b border-slate-100 ${d.modelsUsed.includes(m.model) ? 'font-semibold' : ''}`}>
              <td className="py-1">{m.model}{d.modelsUsed.includes(m.model) && ' (used now)'}</td><td>{fmtCents(m.cents)}</td>
              <td className={m.changePct !== null && m.changePct < 0 ? 'text-emerald-700' : 'text-slate-700'}>{m.changePct === null ? '—' : `${m.changePct > 0 ? '+' : ''}${m.changePct}%`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {d.unpricedModels.length > 0 && <p className="text-[12.5px] text-amber-800">Without a price (left out of today's cost): {d.unpricedModels.join(', ')}.</p>}
    </section>
  )
}
