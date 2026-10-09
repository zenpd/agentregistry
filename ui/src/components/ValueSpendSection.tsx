import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Download } from 'lucide-react'
import { getScenario, getSpendReview, scorecardPdf, type Scenario, type SpendReview, VALUE_STATE_SHORT } from '../services/ops/value'
import InfoTip from './InfoTip'
import { fmtCents } from '../pages/agent/shared'

// Business Impact → value and spend: what moving the pipeline to Production would
// change, money spent on idle or duplicate agents, and the one-page scorecard.
// unitAgentIds: the agents of the chosen business unit, or null for every unit. Every figure here follows that choice.
export default function ValueSpendSection({ unitKey, unitLabel, unitAgentIds }: { unitKey: string | null; unitLabel: string; unitAgentIds: string[] | null }) {
  const [scenario, setScenario] = useState<Scenario | null>(null)
  const [picked, setPicked] = useState<string[] | null>(null)
  const [spend, setSpend] = useState<SpendReview | null>(null)
  const [busy, setBusy] = useState(false)
  // Every agent not yet in Production, from the first read: the list to tick from.
  const [full, setFull] = useState<Scenario['agents']>([])
  useEffect(() => { getSpendReview().then(r => setSpend(r.data)).catch(() => setSpend(null)) }, [])
  const unitIds = unitAgentIds ? unitAgentIds.join(',') : null
  // A different unit starts again with every one of its agents ticked.
  useEffect(() => { setPicked(null); setFull([]) }, [unitIds])
  useEffect(() => {
    // An empty list means "every agent" to the API, so a unit with no agents asks for an id that matches none.
    const ask = picked ?? (unitIds === null ? [] : unitIds ? unitIds.split(',') : ['none'])
    getScenario(ask).then(r => { setScenario(r.data); if (picked === null) setFull(r.data.agents) }).catch(() => setScenario(null))
  }, [picked, unitIds])
  const inUnit = (id: string) => !unitAgentIds || unitAgentIds.includes(id)
  const idle = (spend?.idle || []).filter(i => inUnit(i.agentId))
  const duplicates = (spend?.duplicates || []).filter(d => d.agents.some(x => inUnit(x.id)))

  async function download() {
    setBusy(true)
    try {
      const r = await scorecardPdf(unitKey || undefined)
      const url = URL.createObjectURL(r.data as Blob)
      const link = document.createElement('a')
      link.href = url; link.download = `scorecard-${(unitKey || 'all-units').toLowerCase()}.pdf`; link.click()
      URL.revokeObjectURL(url)
    } finally { setBusy(false) }
  }
  const all = full
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" data-testid="value-spend">
      <div className="card p-5 space-y-2" data-testid="scenario">
        <h2 className="font-semibold text-slate-900">If these agents move to Production <InfoTip term="scenario" /></h2>
        {scenario && (
          <>
            <p className="text-[13px] text-slate-700">
              Value going live: <b className="text-emerald-700">{fmtCents(scenario.valueCents)}/mo</b>
              {scenario.attestedShare !== null && ` (${scenario.attestedShare}% attested by finance)`}. Cost it brings: <b className="text-rose-600">{fmtCents(scenario.costCents)}/mo</b>.
              Net: <b>{fmtCents(scenario.netCents)}/mo</b>.
            </p>
            <p className="text-[12px] text-slate-500">{scenario.caveat}</p>
            <ul className="max-h-56 overflow-y-auto divide-y divide-slate-100 text-[13px]">
              {all.map(a => (
                <li key={a.agentId} className="flex items-center gap-2 py-1">
                  <input type="checkbox" checked={picked === null || picked.includes(a.agentId)} aria-label={`Include ${a.name}`}
                    onChange={e => {
                      const base = picked ?? all.map(x => x.agentId)
                      const next = e.target.checked ? [...base, a.agentId] : base.filter(x => x !== a.agentId)
                      setPicked(next.length === all.length ? null : next.length ? next : ['none'])
                    }} />
                  <Link to={`/agents/${a.agentId}?tab=revenue`} className="flex-1 text-slate-800 hover:text-zen-700">{a.name}</Link>
                  <span className="text-slate-500">{a.stage}</span>
                  <span className="w-28 text-right text-emerald-700">{fmtCents(a.valueCents)}{a.valueCents ? ` · ${VALUE_STATE_SHORT[a.valueState]}` : ''}</span>
                  <span className="w-20 text-right text-rose-600">{fmtCents(a.tokenCents + a.infraCents)}</span>
                </li>
              ))}
            </ul>
            {picked !== null && <button type="button" className="text-[12.5px] text-zen-700 hover:underline" onClick={() => setPicked(null)}>Include every agent not in Production{unitAgentIds ? ` in ${unitLabel}` : ''}</button>}
          </>
        )}
      </div>

      <div className="space-y-4">
        <div className="card p-5 space-y-2" data-testid="spend-review">
          <h2 className="font-semibold text-slate-900">Idle and duplicate spend <InfoTip term="idle_spend" /></h2>
          {!spend ? <p className="text-[13px] text-slate-500">Loading…</p> : (idle.length + duplicates.length) === 0
            ? <p className="text-[13px] text-slate-600">No Production agent is idle while costing money, and no two agents that cost money look like they do the same job.</p>
            : (
              <ul className="space-y-1.5 text-[13px] text-slate-700">
                {idle.map(i => <li key={i.agentId}><Link to={`/agents/${i.agentId}?tab=revenue`} className="font-medium text-zen-700 hover:underline">{i.name}</Link>: {i.text}</li>)}
                {duplicates.map((d, n) => <li key={n}>{d.text}</li>)}
              </ul>
            )}
          <p className="text-[12px] text-slate-500">Checked daily by the spend review job, which also lists these as financial risks on each agent.</p>
        </div>
        <div className="card p-5 space-y-2" data-testid="scorecard">
          <h2 className="font-semibold text-slate-900">Scorecard</h2>
          <p className="text-[13px] text-slate-600">One page for {unitLabel}: agents, value and whether finance attested it, cost, return, open high risks and reuse.</p>
          <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={download} data-testid="scorecard-pdf"><Download size={14} /> {busy ? 'Preparing…' : 'Download PDF'}</button>
        </div>
      </div>
    </div>
  )
}
