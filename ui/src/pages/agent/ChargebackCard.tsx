import { useEffect, useState } from 'react'
import { getAgentChargeback, type AgentChargeback } from '../../services/ops/reuse'
import { SectionLabel } from './shared'

const usd = (c: number) => `$${(c / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

function months(): string[] {
  const out: string[] = []
  const d = new Date()
  for (let i = 0; i < 6; i++) {
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
    d.setMonth(d.getMonth() - 1)
  }
  return out
}

// Tokenomics tab → Chargeback: this agent's token cost for a month, split across
// the teams with approved access by the calls seen in traces.
export default function ChargebackCard({ agentId }: { agentId: string }) {
  const [month, setMonth] = useState(months()[0])
  const [d, setD] = useState<AgentChargeback | null>(null)
  useEffect(() => { getAgentChargeback(agentId, month).then(r => setD(r.data)).catch(() => setD(null)) }, [agentId, month])
  if (!d) return null
  return (
    <section className="space-y-2" data-testid="chargeback">
      <div className="flex items-center justify-between gap-2">
        <SectionLabel tip="chargeback">Chargeback</SectionLabel>
        <select className="input !w-auto !py-0.5 text-xs" value={month} onChange={e => setMonth(e.target.value)} aria-label="Month">
          {months().map(m => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>
      <p className="text-[13px] text-slate-600">
        Token cost in {d.month}: <b>{usd(d.costCents)}</b>{d.costSource === 'seed' ? ' (demo usage, not real)' : ''}.
        {d.unpriced.length > 0 && ` Models without a price are left out: ${d.unpriced.join(', ')}.`} {d.basisText}
      </p>
      {d.costCents > 0 && (
        <table className="w-full text-[13px]">
          <thead><tr className="text-left text-slate-600 border-b"><th className="py-1">Pays</th><th>Share</th><th>Amount</th></tr></thead>
          <tbody>
            {d.shares.map(s => (
              <tr key={s.payer} className="border-b border-slate-100">
                <td className="py-1 font-medium text-slate-900">{s.payer}{s.payer === d.ownerUnit && <span className="ml-1 text-[12px] text-slate-500">(owner's unit)</span>}</td>
                <td>{s.share}%</td><td>{usd(s.cents)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
