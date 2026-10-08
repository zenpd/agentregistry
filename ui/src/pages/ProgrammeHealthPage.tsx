import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, Clock, Download, Recycle, Search, UserCheck } from 'lucide-react'
import { chargebackCsvUrl, getPortfolioChargeback, getProgrammeHealth, type ProgrammeHealth } from '../services/ops/reuse'
import InfoTip from '../components/InfoTip'
import api from '../services/api'
import { errorMessage } from './agent/shared'

const usd = (c: number) => `$${(c / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const thisMonth = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}` }

function Tile({ icon, label, value, sub, testId }: { icon: React.ReactNode; label: string; value: string; sub: string; testId: string }) {
  return (
    <div className="card p-4" data-testid={testId}>
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-600">{icon}{label}</div>
      <div className="mt-1 text-2xl font-bold text-slate-900">{value}</div>
      <div className="mt-1 text-xs text-slate-600">{sub}</div>
    </div>
  )
}

// Programme health: how many agents are known, who owns them, how fast reviews are
// decided, how much agents are reused, what people searched for and did not find,
// and who pays for shared agents.
export default function ProgrammeHealthPage() {
  const [h, setH] = useState<ProgrammeHealth | null>(null)
  const [cb, setCb] = useState<Awaited<ReturnType<typeof getPortfolioChargeback>>['data'] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [month] = useState(thisMonth())
  useEffect(() => {
    getProgrammeHealth().then(r => setH(r.data)).catch(e => setError(errorMessage(e, 'Could not load programme health')))
    getPortfolioChargeback(month).then(r => setCb(r.data)).catch(() => setCb(null))
  }, [month])

  async function downloadCsv() {
    const r = await api.get(chargebackCsvUrl(month).replace('/api/v1', ''), { responseType: 'blob' })
    const url = URL.createObjectURL(r.data as Blob)
    const link = document.createElement('a')
    link.href = url; link.download = `chargeback-${month}.csv`; link.click()
    URL.revokeObjectURL(url)
  }

  if (error) return <div className="p-8 text-center text-rose-600">{error}</div>
  if (!h) return <div className="p-8 text-center text-slate-600">Loading…</div>
  const r = h.reuse
  return (
    <div className="space-y-5 animate-fade-in max-w-6xl" data-testid="programme-health">
      <div>
        <h1 className="text-2xl font-bold gradient-text">Programme health <InfoTip term="programme_health" /></h1>
        <p className="text-slate-600 mt-0.5">How the registry programme is doing, from the registry's own records. Retired agents are left out.</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Tile testId="tile-known" icon={<Activity size={14} />} label="Known agents that are registered" value={h.known.share === null ? '—' : `${h.known.share}%`}
          sub={`${h.known.registered} registered, ${h.known.foundNotRegistered} found but not registered (Discovered page).`} />
        <Tile testId="tile-owners" icon={<UserCheck size={14} />} label="Owned by a person" value={h.owners.share === null ? '—' : `${h.owners.share}%`}
          sub={`${h.owners.person} of ${h.owners.total} have an owner with an account (${h.owners.withBackup} with a backup). ${h.owners.nameOnly} have only a name, ${h.owners.none} none.`} />
        <Tile testId="tile-speed" icon={<Clock size={14} />} label="Median time to decide a review" value={h.approvalSpeed.medianDays === null ? '—' : `${h.approvalSpeed.medianDays} days`}
          sub={`${h.approvalSpeed.text} ${h.approvalSpeed.decisions} decisions. ${h.overdueReviews.count} overdue now (over ${h.overdueReviews.slaDays} days).`} />
        <Tile testId="tile-reuse" icon={<Recycle size={14} />} label="Reuse rate" value={r.reuseRate === null ? '—' : `${r.reuseRate}%`}
          sub={`${r.reusedAgents} of ${r.productionAgents} Production agents have an approved consumer team. ${r.buildsAvoided} builds avoided${h.reuseSavings.cents !== null ? `, worth ${usd(h.reuseSavings.cents)} at ${usd(h.reuseSavings.buildCostCents || 0)} a build` : ' (set an agreed build cost in Settings to value them)'}.`} />
      </div>

      {h.overdueReviews.count > 0 && (
        <div className="card p-5">
          <h2 className="font-semibold text-slate-900 mb-2">Overdue reviews</h2>
          <ul className="space-y-1 text-[13px]">
            {h.overdueReviews.items.map(o => (
              <li key={`${o.agentId}-${o.gate}`}><Link to={`/agents/${o.agentId}?tab=governance`} className="text-zen-700 hover:underline">{o.agentName}</Link> · {o.gate} · waiting {o.days} days</li>
            ))}
          </ul>
        </div>
      )}

      <div className="card p-5 space-y-2" data-testid="reuse-by-unit">
        <h2 className="font-semibold text-slate-900">Reuse by unit</h2>
        <p className="text-[13px] text-slate-600">
          Builds avoided: approved access grants, each a team that uses an existing agent instead of building one. Time to first call: median days from the approval
          to the first call seen from that team in traces ({r.firstCallsMeasured} measured so far). Teams are recognised by the team name callers put in their traces (the attribute consumer.team).
        </p>
        <table className="w-full text-[13px]">
          <thead><tr className="text-left text-slate-600 border-b"><th className="py-1.5">Unit</th><th>Production agents</th><th>Reused</th><th>Reuse rate</th><th>Builds avoided</th><th>Time to first call</th></tr></thead>
          <tbody>
            {h.reuseByUnit.map(u => (
              <tr key={u.unit} className="border-b border-slate-100">
                <td className="py-1.5 font-medium text-slate-900">{u.unit}</td><td>{u.productionAgents}</td><td>{u.reusedAgents}</td>
                <td>{u.reuseRate === null ? '—' : `${u.reuseRate}%`}</td><td>{u.buildsAvoided}</td>
                <td>{u.medianDaysToFirstCall === null ? 'Not measured' : `${u.medianDaysToFirstCall} days`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card p-5 space-y-2" data-testid="search-gaps">
        <h2 className="font-semibold text-slate-900 flex items-center gap-2"><Search size={16} /> Searched for and not found <InfoTip term="search_gap" /></h2>
        <p className="text-[13px] text-slate-600">Searches on the AI Registry page that found no agent in the last 90 days, most people first.</p>
        {h.searchGaps.length === 0
          ? <p className="text-[13px] text-slate-500">No search came back empty.</p>
          : (
            <ul className="text-[13px] space-y-1">
              {h.searchGaps.map(g => (
                <li key={g.term}><b>{g.term}</b> · {g.people} {g.people === 1 ? 'person' : 'people'}, {g.times} time{g.times === 1 ? '' : 's'}, last {new Date(g.lastAt).toLocaleDateString()}</li>
              ))}
            </ul>
          )}
      </div>

      {cb && (
        <div className="card p-5 space-y-2" data-testid="portfolio-chargeback">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-semibold text-slate-900">Chargeback, {cb.month} <InfoTip term="chargeback" /></h2>
            <button type="button" className="btn-secondary btn-sm" onClick={downloadCsv} data-testid="chargeback-csv"><Download size={14} /> CSV</button>
          </div>
          <p className="text-[13px] text-slate-600">Token cost of every agent with cost this month, split across the teams with approved access by the calls seen. Each agent's split is on its Tokenomics tab.</p>
          {cb.payers.length === 0
            ? <p className="text-[13px] text-slate-500">No priced token cost this month.</p>
            : (
              <table className="w-full text-[13px]">
                <thead><tr className="text-left text-slate-600 border-b"><th className="py-1.5">Team charged</th><th>Amount</th></tr></thead>
                <tbody>{cb.payers.map(p => <tr key={p.payer} className="border-b border-slate-100"><td className="py-1.5">{p.payer}</td><td>{usd(p.cents)}</td></tr>)}</tbody>
              </table>
            )}
        </div>
      )}
    </div>
  )
}
