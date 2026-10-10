import { useEffect, useState } from 'react'
import { Cpu } from 'lucide-react'
import { checkAiModel, getAiUsage, runAiOffCheck, setAiCap, setAiSwitch, type AiUsage } from '../services/ops/aiUsage'
import { errorMessage } from '../pages/agent/shared'

const usd = (cents: number | null | undefined) => cents == null ? '—' : `$${(cents / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

// Settings → the registry's own AI: what each AI function cost in the last 30
// days, its switch, the monthly cap, recent runs, and the AI-off check.
export default function RegistryAiCard({ canEdit }: { canEdit: boolean }) {
  const [data, setData] = useState<AiUsage | null>(null)
  const [cap, setCap] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [showRuns, setShowRuns] = useState(false)
  const [check, setCheck] = useState<Awaited<ReturnType<typeof runAiOffCheck>>['data'] | null>(null)
  const [model, setModel] = useState<{ ok: boolean; message: string } | null>(null)
  const [testing, setTesting] = useState(false)

  const load = () => getAiUsage().then(r => { setData(r.data); setCap(r.data.monthlyCapCents ? String(r.data.monthlyCapCents / 100) : '') }).catch(e => setMsg(errorMessage(e, 'Could not load AI usage')))
  useEffect(() => { load() }, [])

  async function act(fn: () => Promise<unknown>, done: string) {
    setBusy(true)
    try { await fn(); setMsg(done); await load() } catch (e) { setMsg(errorMessage(e, 'Not saved')) } finally { setBusy(false) }
  }

  if (!data) return <div className="card p-6 text-sm text-slate-600">{msg ?? 'Loading the registry’s AI use…'}</div>
  const total30 = data.functions.reduce((s, f) => s + f.costCents30d, 0)
  return (
    <div className="card p-6 space-y-4" data-testid="registry-ai">
      <div className="flex items-start gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-zen-50 text-zen-600"><Cpu size={20} /></div>
        <div>
          <h3 className="text-[16px] font-extrabold text-slate-900">The registry’s own AI</h3>
          <p className="text-[13px] text-slate-600">Every AI call the registry makes is recorded with its model, prompt version, tokens and cost. A switched-off function answers without AI, and says so.</p>
        </div>
      </div>

      <div className={`rounded-lg p-3 ring-1 text-[13px] ${data.model.configured ? 'bg-emerald-50 ring-emerald-200 text-emerald-900' : 'bg-amber-50 ring-amber-200 text-amber-900'}`} data-testid="ai-model">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <span className="font-semibold">AI model: </span>
            {data.model.configured
              ? <>{data.model.deployment} at {data.model.endpointHost}. The key comes from {data.model.keyFrom}.</>
              : <>{data.model.problem}</>}
          </div>
          {canEdit && <button type="button" className="btn-secondary btn-sm" disabled={testing} data-testid="ai-model-test"
            onClick={async () => { setTesting(true); setModel(null); try { setModel((await checkAiModel()).data) } catch (e) { setModel({ ok: false, message: errorMessage(e, 'The test did not run') }) } finally { setTesting(false) } }}>
            {testing ? 'Testing…' : 'Test the connection'}</button>}
        </div>
        {model && <p className={`mt-1 font-medium ${model.ok ? 'text-emerald-800' : 'text-rose-700'}`} role="status">{model.ok ? '✓ ' : '✗ '}{model.message}</p>}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
          <div className="text-[12px] font-semibold uppercase tracking-wide text-slate-600">Spent this month</div>
          <div className="text-xl font-bold text-slate-900">{usd(data.spentThisMonthCents)}</div>
          <div className="text-[12px] text-slate-600">since {data.monthStart}</div>
        </div>
        <div className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
          <div className="text-[12px] font-semibold uppercase tracking-wide text-slate-600">Monthly cap</div>
          <div className={`text-xl font-bold ${data.capState === 'reached' ? 'text-rose-700' : 'text-slate-900'}`}>{data.monthlyCapCents ? usd(data.monthlyCapCents) : 'No cap'}</div>
          <div className="text-[12px] text-slate-600">{data.capState === 'reached' ? 'Reached: scheduled AI work has stopped' : data.monthlyCapCents ? `AI that a person starts with a button continues up to ${data.interactiveCeiling}× the cap` : 'Set one below'}</div>
        </div>
        <div className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
          <div className="text-[12px] font-semibold uppercase tracking-wide text-slate-600">Last 30 days</div>
          <div className="text-xl font-bold text-slate-900">{usd(total30)}</div>
          <div className="text-[12px] text-slate-600">{data.functions.reduce((s, f) => s + f.runs30d, 0)} runs</div>
        </div>
      </div>

      <table className="w-full text-[13px]">
        <thead><tr className="text-left text-slate-600 border-b"><th className="py-2">Function</th><th>Runs (30 d)</th><th>Tokens in / out</th><th>Cost</th><th>Model · prompt version</th><th className="text-right">Switch</th></tr></thead>
        <tbody>
          {data.functions.map(f => (
            <tr key={f.function} className="border-b last:border-0">
              <td className="py-2 font-medium text-slate-900">{f.label}{f.refused30d > 0 && <div className="text-[12px] text-amber-700">{f.refused30d} refused (switched off or cap)</div>}</td>
              <td>{f.runs30d}</td>
              <td>{f.inputTokens30d.toLocaleString()} / {f.outputTokens30d.toLocaleString()}</td>
              <td>{usd(f.costCents30d)}</td>
              <td className="text-slate-600">{f.lastModel ? `${f.lastModel}${f.lastPromptVersion ? ` · ${f.lastPromptVersion}` : ''}` : '—'}</td>
              <td className="text-right">
                <label className="inline-flex items-center gap-1.5">
                  <input type="checkbox" checked={f.enabled} disabled={!canEdit || busy} aria-label={`${f.label} switch`}
                    onChange={e => act(() => setAiSwitch(f.function, e.target.checked), `${f.label} is now ${e.target.checked ? 'on' : 'off'}.`)} />
                  <span className={f.enabled ? 'text-emerald-700 font-semibold' : 'text-slate-600'}>{f.enabled ? 'On' : 'Off'}</span>
                </label>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {canEdit && (
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-[13px] text-slate-700">Monthly cap (USD, empty for none)
            <input className="input !w-32 mt-1" inputMode="decimal" value={cap} onChange={e => setCap(e.target.value)} />
          </label>
          <button type="button" className="btn-secondary btn-sm" disabled={busy || (cap !== '' && !(Number(cap) >= 0))}
            onClick={() => act(() => setAiCap(cap === '' ? null : Math.round(Number(cap) * 100)), cap === '' ? 'Cap removed.' : `Cap set to $${Number(cap).toFixed(2)} a month.`)}>Save cap</button>
          <button type="button" className="btn-secondary btn-sm" disabled={busy} data-testid="ai-off-check"
            onClick={() => act(async () => setCheck((await runAiOffCheck()).data), 'AI-off check finished.')}>Run the AI-off check</button>
        </div>
      )}
      {msg && <p className="text-[13px] text-slate-700" role="status">{msg}</p>}
      {check && (
        <div className={`rounded-lg border px-3 py-2 text-[13px] ${check.passed ? 'border-emerald-200 bg-emerald-50 text-emerald-900' : 'border-rose-200 bg-rose-50 text-rose-800'}`} data-testid="ai-off-result">
          <p className="font-semibold">{check.passed ? 'With AI off, every function still answers.' : 'Some functions failed with AI off.'}</p>
          <ul className="mt-1 space-y-0.5">{check.checks.map((c, i) => <li key={i}>{c.passed ? '✓' : '✗'} {c.kind || c.function}: {c.shows}</li>)}</ul>
        </div>
      )}

      <button type="button" className="text-[13px] font-semibold text-slate-700 hover:underline" onClick={() => setShowRuns(v => !v)}>
        {showRuns ? 'Hide' : 'Show'} the latest {data.recent.length} runs
      </button>
      {showRuns && (
        <table className="w-full text-[12.5px]">
          <thead><tr className="text-left text-slate-600 border-b"><th className="py-1.5">When</th><th>Function</th><th>Model · prompt version</th><th>Tokens</th><th>Cost</th><th>Time</th><th>Result</th></tr></thead>
          <tbody>
            {data.recent.map((r, i) => (
              <tr key={i} className="border-b last:border-0 align-top">
                <td className="py-1.5 whitespace-nowrap">{r.at ? new Date(r.at).toLocaleString() : ''}</td>
                <td>{r.kind || r.function}{r.scheduled && <span className="text-slate-500"> (scheduled)</span>}</td>
                <td>{r.model}{r.promptVersion ? ` · ${r.promptVersion}` : ''}</td>
                <td>{r.inputTokens.toLocaleString()} / {r.outputTokens.toLocaleString()}</td>
                <td>{usd(r.costCents)}</td>
                <td>{(r.durationMs / 1000).toFixed(1)} s</td>
                <td className={r.status === 'ok' ? 'text-emerald-700' : 'text-amber-700'}>{r.status}{r.reason ? ` — ${r.reason}` : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
