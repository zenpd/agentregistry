import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, Clock, Download, Recycle, Search, UserCheck } from 'lucide-react'
import { chargebackCsvUrl, getPortfolioChargeback, getProgrammeHealth, type ProgrammeHealth } from '../services/ops/reuse'
import InfoTip from '../components/InfoTip'
import api from '../services/api'
import { errorMessage } from './agent/shared'

const usd = (c: number) => `$${(c / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const thisMonth = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}` }

function Tile({ icon, label, value, sub, testId, open, onOpen }: { icon: React.ReactNode; label: string; value: string; sub: string; testId: string; open?: boolean; onOpen?: () => void }) {
  const body = (
    <>
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-600">{icon}{label}</div>
      <div className="mt-1 text-2xl font-bold text-slate-900">{value}</div>
      <div className="mt-1 text-xs text-slate-600">{sub}</div>
    </>
  )
  // The whole card is clickable and opens the rows the figure is counted from.
  if (!onOpen) return <div className="card p-4" data-testid={testId}>{body}</div>
  return (
    <div className={`card p-4 cursor-pointer transition hover:shadow-card-hover ${open ? 'ring-2 ring-zen-400' : ''}`} role="button" tabIndex={0} aria-expanded={!!open}
      title="Click to see what is counted" data-testid={testId} onClick={onOpen} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen() } }}>
      {body}
    </div>
  )
}

const agentLink = (id: string, name: string, tab = 'overview') => <Link to={`/agents/${id}?tab=${tab}`} className="font-medium text-zen-700 hover:underline">{name}</Link>
const lines = (items: React.ReactNode[], empty: string) => items.length
  ? <ul className="grid grid-cols-1 md:grid-cols-2 gap-x-6 text-[13px]">{items.map((x, i) => <li key={i} className="flex justify-between gap-3 border-b border-slate-100 py-1">{x}</li>)}</ul>
  : <p className="text-[13px] text-slate-600">{empty}</p>

// Programme health: how many agents are known, who owns them, how fast reviews are
// decided, how much agents are reused, what people searched for and did not find,
// and who pays for shared agents.
export default function ProgrammeHealthPage() {
  const [h, setH] = useState<ProgrammeHealth | null>(null)
  const [cb, setCb] = useState<Awaited<ReturnType<typeof getPortfolioChargeback>>['data'] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [month] = useState(thisMonth())
  // The score that was clicked: the rows it is counted from are listed under the tiles.
  const [behind, setBehind] = useState<'known' | 'owners' | 'speed' | 'reuse' | null>(null)
  const toggle = (k: 'known' | 'owners' | 'speed' | 'reuse') => setBehind(behind === k ? null : k)
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
        <h1 className="text-2xl font-bold gradient-text">Programme Health <InfoTip term="programme_health" /></h1>
        <p className="text-slate-600 mt-0.5">How well the AI programme is run: how many known agents are registered, how many have an owner, how fast reviews are decided and how much agents are reused. Retired agents are left out.</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Tile testId="tile-known" icon={<Activity size={14} />} label="Known agents that are registered" value={h.known.share === null ? '—' : `${h.known.share}%`}
          sub={`${h.known.registered} registered, ${h.known.foundNotRegistered} found but not registered (Discovered Agents page).`} open={behind === 'known'} onOpen={() => toggle('known')} />
        <Tile testId="tile-owners" icon={<UserCheck size={14} />} label="Owned by a person" value={h.owners.share === null ? '—' : `${h.owners.share}%`}
          sub={`${h.owners.person} of ${h.owners.total} have an owner with an account (${h.owners.withBackup} with a backup). ${h.owners.nameOnly} have only a name, ${h.owners.none} none.`} open={behind === 'owners'} onOpen={() => toggle('owners')} />
        <Tile testId="tile-speed" icon={<Clock size={14} />} label="Median time to decide a review" value={h.approvalSpeed.medianDays === null ? '—' : `${h.approvalSpeed.medianDays} days`}
          sub={`${h.approvalSpeed.text} ${h.approvalSpeed.decisions} decisions. ${h.overdueReviews.count} overdue now (over ${h.overdueReviews.slaDays} days).`} open={behind === 'speed'} onOpen={() => toggle('speed')} />
        <Tile testId="tile-reuse" icon={<Recycle size={14} />} label="Reuse rate" value={r.reuseRate === null ? '—' : `${r.reuseRate}%`}
          sub={`${r.reusedAgents} of ${r.productionAgents} Production agents have an approved consumer team. ${r.buildsAvoided} builds avoided${h.reuseSavings.cents !== null ? `, worth ${usd(h.reuseSavings.cents)} at ${usd(h.reuseSavings.buildCostCents || 0)} a build` : ' (set an agreed build cost in Settings to value them)'}.`} open={behind === 'reuse'} onOpen={() => toggle('reuse')} />
      </div>

      {behind && (
        <div className="card p-5 space-y-2" data-testid="score-behind">
          {behind === 'known' && <>
            <h2 className="font-semibold text-slate-900">What "Known agents that are registered" counts</h2>
            <p className="text-[13px] text-slate-700">{h.known.registered} registered agents ÷ ({h.known.registered} registered + {h.known.foundNotRegistered} found but not registered) = <b>{h.known.share ?? '—'}%</b>. The {h.known.foundNotRegistered} not registered are {h.behind.notRegistered.phoenixProjects.length} Phoenix project{h.behind.notRegistered.phoenixProjects.length === 1 ? '' : 's'} and {h.behind.notRegistered.connectorFindings} finding{h.behind.notRegistered.connectorFindings === 1 ? '' : 's'} from connectors. <Link to="/discovered" className="font-semibold text-zen-700 hover:underline">Open Discovered Agents</Link></p>
            {lines(h.behind.notRegistered.phoenixProjects.map(n => <span className="text-slate-800">{n}</span>), 'No Phoenix project is waiting to be registered.')}
          </>}
          {behind === 'owners' && <>
            <h2 className="font-semibold text-slate-900">What "Owned by a person" counts</h2>
            <p className="text-[13px] text-slate-700">{h.owners.person} agents whose owner is a person with an active account ÷ {h.owners.total} agents that are not retired = <b>{h.owners.share ?? '—'}%</b>.</p>
            <p className="text-[13px] font-semibold text-slate-900">Owner is a person with an account ({h.behind.ownerPerson.length})</p>
            {lines(h.behind.ownerPerson.map(a => <>{agentLink(a.agentId, a.name)}<span className="text-slate-600">{a.owner}{a.backup ? ', with a backup owner' : ', no backup owner'}</span></>), 'None.')}
            <p className="text-[13px] font-semibold text-slate-900">Owner is only a name, with no account ({h.behind.ownerNameOnly.length})</p>
            {lines(h.behind.ownerNameOnly.map(a => <>{agentLink(a.agentId, a.name)}<span className="text-slate-600">{a.owner}</span></>), 'None.')}
            <p className="text-[13px] font-semibold text-slate-900">No owner ({h.behind.ownerNone.length})</p>
            {lines(h.behind.ownerNone.map(a => <>{agentLink(a.agentId, a.name)}<span className="text-slate-600">no owner recorded</span></>), 'None.')}
          </>}
          {behind === 'speed' && <>
            <h2 className="font-semibold text-slate-900">What "Median time to decide a review" counts</h2>
            <p className="text-[13px] text-slate-700">The {h.behind.decisions.length} review{h.behind.decisions.length === 1 ? '' : 's'} decided in the last {h.approvalSpeed.days} days, each from the day it was submitted to the day it was decided. The median is the middle value when they are put in order: <b>{h.approvalSpeed.medianDays ?? '—'} days</b>.</p>
            {lines(h.behind.decisions.map(d => <>{agentLink(d.agentId, d.name, 'governance')}<span className="text-right text-slate-600">{d.review}: submitted {d.submitted}, {d.decision.toLowerCase()} {d.decided} = <b>{d.days}</b> day{d.days === 1 ? '' : 's'}</span></>), `No review was decided in the last ${h.approvalSpeed.days} days, so there is no figure.`)}
          </>}
          {behind === 'reuse' && <>
            <h2 className="font-semibold text-slate-900">What "Reuse rate" counts</h2>
            <p className="text-[13px] text-slate-700">{r.reusedAgents} Production agent{r.reusedAgents === 1 ? '' : 's'} with at least one approved consumer team ÷ {r.productionAgents} Production agent{r.productionAgents === 1 ? '' : 's'} = <b>{r.reuseRate ?? '—'}%</b>. Each approved team counts as one build avoided: {r.buildsAvoided} in total.</p>
            {lines(h.behind.productionAgents.map(a => <>{agentLink(a.agentId, a.name, 'integrate')}<span className="text-slate-600">{a.teams ? `${a.teams} approved team${a.teams === 1 ? '' : 's'}` : 'no approved team'}</span></>), 'No agent is in Production.')}
          </>}
        </div>
      )}

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
        <p className="text-[13px] text-slate-600">Searches on the Agent Registry page that found no agent in the last 90 days, most people first.</p>
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
