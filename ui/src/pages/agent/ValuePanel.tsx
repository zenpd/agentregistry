import { useCallback, useEffect, useState } from 'react'
import { attestValue, declareValue, getValue, VALUE_STATE_PILL, type ValueView } from '../../services/ops/value'
import { can, notAllowed, useMe } from '../../lib/me'
import { SectionLabel, fmtCents } from './shared'

function errorMessage(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  return typeof detail === 'string' ? detail : e?.message || fallback
}
const fmtDate = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })

// Revenue tab → Value: the owner declares a monthly value with its method and how it
// is worked out, and a finance reviewer attests it or adjusts it.
export default function ValuePanel({ agentId, onChanged }: { agentId: string; onChanged: () => void }) {
  const me = useMe()
  const [v, setV] = useState<ValueView | null>(null)
  const [mode, setMode] = useState<'view' | 'declare' | 'attest'>('view')
  const [form, setForm] = useState({ method: '', basis: '', amount: '', hours: '', rate: '' })
  const [att, setAtt] = useState({ status: 'attested' as 'attested' | 'adjusted', note: '', amount: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => getValue(agentId).then(r => setV(r.data)).catch(e => setError(errorMessage(e, 'Could not load the value'))), [agentId])
  useEffect(() => { load() }, [load])

  function startDeclare() {
    if (!v) return
    setForm({ method: v.method || 'cost_avoidance', basis: v.basis || '', amount: v.declaredCents ? String(v.declaredCents / 100) : '',
              hours: v.hoursSavedMonthly ? String(v.hoursSavedMonthly) : '', rate: String(v.hourlyRateCents / 100) })
    setError(null); setMode('declare')
  }
  async function run(fn: () => Promise<{ data: ValueView }>) {
    setBusy(true); setError(null)
    try { setV((await fn()).data); setMode('view'); onChanged() } catch (e) { setError(errorMessage(e, 'The value was not saved')) } finally { setBusy(false) }
  }
  if (!v) return error ? <p className="text-sm text-rose-600">{error}</p> : null
  const s = v.state
  const timeSaved = form.method === 'time_saved'
  return (
    <section className="space-y-2" data-testid="value-panel">
      <SectionLabel tip="declared_value">Value and how it is worked out</SectionLabel>
      <div className="rounded-lg ring-1 ring-gray-100 px-3 py-2.5 text-sm space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <b className="text-slate-900">{s.cents ? `${fmtCents(s.cents)}/mo` : 'No value declared'}</b>
          <span className={`rounded-full px-2 py-0.5 text-[12px] font-semibold ring-1 ${VALUE_STATE_PILL[s.state]}`} data-testid="value-state">{s.label}</span>
          {v.methodLabel && <span className="text-[13px] text-slate-600">Method: {v.methodLabel}{!v.methodSet && ' (taken from the record: the owner has not chosen a method yet)'}</span>}
        </div>
        {s.state === 'adjusted' && <p className="text-[13px] text-slate-600">The owner declared {fmtCents(v.declaredCents)}/mo. Finance set {fmtCents(s.cents)}/mo, which is the figure used.</p>}
        {v.basis ? <p className="text-[13px] text-slate-700">How it is worked out: {v.basis}</p>
          : <p className="text-[13px] text-amber-800">How the figure is worked out is not recorded.</p>}
        {v.attestations[0] && (
          <p className="text-[13px] text-slate-600">Last finance check: {v.attestations[0].status === 'attested' ? 'confirmed as declared' : `adjusted to ${fmtCents(v.attestations[0].attestedCents)}/mo`} by {v.attestations[0].attestedBy} on {fmtDate(v.attestations[0].attestedAt)}: {v.attestations[0].note}</p>
        )}
        {mode === 'view' && (
          <div className="flex flex-wrap gap-2 pt-1">
            {can(me, 'update') ? <button type="button" className="btn-secondary btn-sm" onClick={startDeclare} data-testid="declare-value">Declare the value</button>
              : me && <span className="text-[12.5px] text-slate-500">{notAllowed(me, 'declare the value')}</span>}
            {v.canAttest && s.state !== 'none' && (
              <button type="button" className="btn-secondary btn-sm" onClick={() => { setAtt({ status: 'attested', note: '', amount: '' }); setMode('attest') }} data-testid="attest-value">
                Finance check (attest or adjust)
              </button>
            )}
          </div>
        )}
      </div>

      {mode === 'declare' && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 space-y-2">
          <div className="grid gap-1 sm:grid-cols-2">
            {v.methods.map(m => (
              <label key={m.value} className="flex items-start gap-1.5 text-sm">
                <input type="radio" className="mt-1" name="value-method" checked={form.method === m.value} onChange={() => setForm({ ...form, method: m.value })} />
                <span><b>{m.label}</b><span className="block text-[12px] text-slate-600">{m.help}</span></span>
              </label>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            {timeSaved ? (
              <>
                <label className="text-[12.5px] text-slate-600">Hours saved a month
                  <input className="input mt-0.5 !w-32 text-sm" type="number" min={0} value={form.hours} onChange={e => setForm({ ...form, hours: e.target.value })} data-testid="value-hours" />
                </label>
                <label className="text-[12.5px] text-slate-600">Hourly rate ($)
                  <input className="input mt-0.5 !w-28 text-sm" type="number" min={0} value={form.rate} onChange={e => setForm({ ...form, rate: e.target.value })} />
                </label>
                <span className="self-end text-[13px] text-slate-700">= {fmtCents(Math.round(Number(form.hours || 0) * Number(form.rate || 0) * 100))}/mo</span>
              </>
            ) : (
              <label className="text-[12.5px] text-slate-600">Monthly value ($)
                <input className="input mt-0.5 !w-40 text-sm" type="number" min={0} value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} data-testid="value-amount" />
              </label>
            )}
            <label className="flex-1 min-w-[260px] text-[12.5px] text-slate-600">How it is worked out (at least 20 characters)
              <input className="input mt-0.5 text-sm" value={form.basis} onChange={e => setForm({ ...form, basis: e.target.value })} data-testid="value-basis" />
            </label>
          </div>
          <div className="flex gap-2">
            <button type="button" className="btn-primary btn-sm" disabled={busy || form.basis.trim().length < 20} data-testid="save-value"
              onClick={() => run(() => declareValue(agentId, timeSaved
                ? { method: form.method, basis: form.basis, hoursSavedMonthly: Number(form.hours || 0), hourlyRateCents: Math.round(Number(form.rate || 0) * 100) }
                : { method: form.method, basis: form.basis, amountDollars: Math.round(Number(form.amount || 0)) }))}>Save</button>
            <button type="button" className="btn-ghost btn-sm" onClick={() => setMode('view')}>Cancel</button>
          </div>
          {v.attestations.length > 0 && <p className="text-[12.5px] text-amber-800">Changing the figure or the method means finance checks it again.</p>}
        </div>
      )}

      {mode === 'attest' && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50/40 p-3 space-y-2">
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-1.5"><input type="radio" checked={att.status === 'attested'} onChange={() => setAtt({ ...att, status: 'attested' })} /> Confirm {fmtCents(v.declaredCents)}/mo as declared</label>
            <label className="flex items-center gap-1.5"><input type="radio" checked={att.status === 'adjusted'} onChange={() => setAtt({ ...att, status: 'adjusted' })} data-testid="attest-adjust" /> Adjust to another figure</label>
          </div>
          <div className="flex flex-wrap gap-2">
            {att.status === 'adjusted' && (
              <label className="text-[12.5px] text-slate-600">Monthly value ($)
                <input className="input mt-0.5 !w-40 text-sm" type="number" min={0} value={att.amount} onChange={e => setAtt({ ...att, amount: e.target.value })} data-testid="attest-amount" />
              </label>
            )}
            <label className="flex-1 min-w-[260px] text-[12.5px] text-slate-600">What you checked (at least 20 characters)
              <input className="input mt-0.5 text-sm" value={att.note} onChange={e => setAtt({ ...att, note: e.target.value })} data-testid="attest-note" />
            </label>
          </div>
          <div className="flex gap-2">
            <button type="button" className="btn-primary btn-sm" disabled={busy || att.note.trim().length < 20 || (att.status === 'adjusted' && !att.amount)} data-testid="save-attest"
              onClick={() => run(() => attestValue(agentId, { status: att.status, note: att.note, ...(att.status === 'adjusted' ? { amountDollars: Math.round(Number(att.amount)) } : {}) }))}>
              Record the finance check
            </button>
            <button type="button" className="btn-ghost btn-sm" onClick={() => setMode('view')}>Cancel</button>
          </div>
        </div>
      )}
      {error && <p className="text-[13px] text-rose-700">{error}</p>}
    </section>
  )
}
