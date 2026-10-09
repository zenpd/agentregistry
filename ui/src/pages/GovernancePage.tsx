import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  getAgents, getGovernanceOverview, getDiscoveries, getGovernanceSummary, requiredReviewsOf,
  type Agent, type GovernanceOverview, type Discovery, type GovernanceSummary
} from '../services/api'
import { applyRuleProposal, getRuleProposal, type GateKey, type RuleProposal } from '../services/ops/governance'
import InfoTip from '../components/InfoTip'
import { can, useMe } from '../lib/me'
import { errorMessage } from './agent/shared'

export default function GovernancePage() {
  const me = useMe()
  const [agents, setAgents] = useState<Agent[]>([])
  const [overview, setOverview] = useState<GovernanceOverview | null>(null)
  const [discoveries, setDiscoveries] = useState<Discovery[]>([])
  const [summary, setSummary] = useState<GovernanceSummary | null>(null)
  // A tile that was clicked: the table then lists only the agents its count is made of.
  const [only, setOnly] = useState<'cleared' | 'blocked' | 'in_review' | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState<string | null>(null)
  // Outcome of the last gate change or auto-review, shown instead of only logged.
  const [notice, setNotice] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)

  useEffect(() => { fetchData() }, [])

  async function fetchData() {
    try {
      setLoading(true)
      const [agentsRes, overviewRes, discRes, summaryRes] = await Promise.all([
        getAgents(1, 100),
        getGovernanceOverview(),
        getDiscoveries(),
        getGovernanceSummary()
      ])
      setAgents(agentsRes.data.data)
      setOverview(overviewRes.data)
      setDiscoveries(discRes.data)
      setSummary(summaryRes.data)
      setError(null)
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Failed to fetch')
    } finally {
      setLoading(false)
    }
  }

  // Reviews are decided in one place, the agent's Governance tab, where the checklist and evidence are.
  const [proposal, setProposal] = useState<RuleProposal | null>(null)
  const [proposalReason, setProposalReason] = useState('')

  async function handleRunGovernance(agentId: string) {
    const name = agents.find(a => a.id === agentId)?.name || agentId
    setRunning(agentId)
    setNotice(null)
    try {
      setProposalReason('')
      setProposal((await getRuleProposal(agentId)).data)
    } catch (e: any) {
      setNotice({ tone: 'error', text: `Rule checks for ${name} failed — ${errorMessage(e, 'the request failed')}` })
    } finally {
      setRunning(null)
    }
  }

  async function acceptProposal() {
    if (!proposal) return
    const name = agents.find(a => a.id === proposal.agentId)?.name || proposal.agentId
    try {
      await applyRuleProposal(proposal.agentId, proposalReason.trim())
      setProposal(null)
      await fetchData()
      setNotice({ tone: 'ok', text: `${name}: the rule-check proposal was recorded in your name. Approvals from it expire in ${proposal.validityDays} days, so a full review follows.` })
    } catch (e: any) {
      setNotice({ tone: 'error', text: `${name}: the proposal was not saved — ${errorMessage(e, 'the request failed')}` })
    }
  }

  const gates: GateKey[] = ['arb', 'security', 'dp']
  const gateLabels: Record<string, string> = { arb: 'Architecture Review Board', security: 'Security Review', dp: 'Data Protection Review' }
  const pendingDiscs = discoveries.filter(d => d.status === 'pending')

  const STATUS_PILL: Record<string, string> = {
    'Approved': 'bg-emerald-50 text-emerald-700 ring-emerald-200', 'Approved with Conditions': 'bg-emerald-50 text-emerald-700 ring-emerald-200',
    'In Review': 'bg-amber-50 text-amber-700 ring-amber-200', 'Changes Requested': 'bg-rose-50 text-rose-700 ring-rose-200',
    'Not Submitted': 'bg-slate-100 text-slate-700 ring-slate-200',
  }

  if (loading) return <div className="p-8 text-center text-slate-600">Loading...</div>
  if (error) return <div className="p-8 text-center text-red-500">Error: {error}</div>

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold gradient-text">Governance</h1>
        <p className="text-slate-600 mt-0.5">Which reviews each agent has passed: architecture, security and data protection. An agent needs the reviews of its risk level before it runs in Production. Click a status to open that review on the agent.</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-4">
        <button type="button" onClick={() => setOnly(only === 'cleared' ? null : 'cleared')} aria-pressed={only === 'cleared'} data-testid="filter-cleared"
          className={`card p-4 text-left hover:ring-2 hover:ring-zen-200 ${only === 'cleared' ? 'ring-2 ring-zen-400' : ''}`}>
          <div className="text-2xl font-bold text-green-600" data-testid="tile-cleared">{summary?.cleared ?? "—"}</div>
          <div className="text-xs font-medium text-slate-700">Cleared for production</div>
          <div className="text-[12px] text-slate-500 mt-0.5">Every review its risk level requires is approved (with or without conditions)</div>
        </button>
        <button type="button" onClick={() => setOnly(only === 'blocked' ? null : 'blocked')} aria-pressed={only === 'blocked'} data-testid="filter-blocked"
          className={`card p-4 text-left hover:ring-2 hover:ring-zen-200 ${only === 'blocked' ? 'ring-2 ring-zen-400' : ''}`}>
          <div className="text-2xl font-bold text-red-600">{summary?.blocked ?? "—"}</div>
          <div className="text-xs font-medium text-slate-700">Blocked</div>
          <div className="text-[12px] text-slate-500 mt-0.5">Changes requested on a required review</div>
        </button>
        <button type="button" onClick={() => setOnly(only === 'in_review' ? null : 'in_review')} aria-pressed={only === 'in_review'} data-testid="filter-in-review"
          className={`card p-4 text-left hover:ring-2 hover:ring-zen-200 ${only === 'in_review' ? 'ring-2 ring-zen-400' : ''}`}>
          <div className="text-2xl font-bold text-amber-600">{summary?.inReview ?? "—"}</div>
          <div className="text-xs font-medium text-slate-700">In active review</div>
          <div className="text-[12px] text-slate-500 mt-0.5">A required review awaits a decision</div>
        </button>
        <Link to="/approvals" className="card p-4 block hover:ring-2 hover:ring-zen-200" data-testid="findings-tile">
          <div className="text-2xl font-bold text-orange-600">{pendingDiscs.length}</div>
          <div className="text-xs font-medium text-slate-700 flex items-center">Governance findings <InfoTip term="governance_findings" className="ml-1" /></div>
          <div className="text-[12px] text-slate-500 mt-0.5">Checks on registered agents, waiting on Integration Approval</div>
        </Link>
      </div>

      {/* Gate Breakdown */}
      {overview && (
        <div className="grid grid-cols-3 gap-4">
          {gates.map(gate => (
            <div key={gate} className="card p-4">
              <h3 className="font-semibold text-sm mb-2">{gateLabels[gate]}</h3>
              <div className="space-y-1">
                {Object.entries(overview[gate] || {}).map(([status, count]) => (
                  <div key={status} className="flex justify-between text-xs">
                    <span className="text-slate-700">{status}</span>
                    <span className="font-mono">{count}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {notice && (
        <div className={`flex items-start justify-between gap-3 rounded-lg border px-3 py-2 text-sm ${notice.tone === 'ok' ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-rose-200 bg-rose-50 text-rose-700'}`} role="status">
          <span>{notice.text}</span>
          <button type="button" onClick={() => setNotice(null)} className="text-xs opacity-70 hover:opacity-100" aria-label="Dismiss">✕</button>
        </div>
      )}

      {proposal && (
        <div className="card p-4 space-y-3 border-zen-200" data-testid="rule-proposal">
          <div>
            <p className="text-sm font-semibold text-slate-900">Rule-check proposal for {agents.find(a => a.id === proposal.agentId)?.name} — not saved</p>
            <p className="text-[13px] text-slate-700">The registry checked fixed rules against this record (model, systems, service level, owner, risk level, databases). Accepting records these decisions in your name, marked as rule-proposed, and any approval expires in {proposal.validityDays} days so a full review follows.</p>
          </div>
          <ul className="space-y-1.5">
            {proposal.gates.map(g => (
              <li key={g.gate} className="text-[13px]"><span className="font-semibold text-slate-900">{g.label}: {g.status}</span> <span className="text-slate-700">— {g.note}</span></li>
            ))}
          </ul>
          <textarea className="input text-sm" rows={2} placeholder="Why you accept this proposal (at least 20 characters) — required"
            value={proposalReason} onChange={e => setProposalReason(e.target.value)} />
          <div className="flex gap-2">
            <button className="btn-primary btn-sm" disabled={proposalReason.trim().length < 20} onClick={acceptProposal}>Accept and record</button>
            <button className="btn-secondary btn-sm" onClick={() => setProposal(null)}>Discard</button>
          </div>
        </div>
      )}

      {/* Review Status Table */}
      {only && (
        <p className="text-[13px] text-slate-700" data-testid="filter-note">
          Showing the {agents.filter(a => summary?.positions[a.id] === only).length} agent{agents.filter(a => summary?.positions[a.id] === only).length === 1 ? '' : 's'} counted as
          {' '}<b>{only === 'cleared' ? 'cleared for production' : only === 'blocked' ? 'blocked' : 'in active review'}</b>.{' '}
          <button type="button" className="font-semibold text-zen-700 hover:underline" onClick={() => setOnly(null)}>Show every agent</button>
        </p>
      )}
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-600 border-b">
              <th className="p-3">Agent</th>
              <th className="p-3">Stage</th>
              {gates.map(g => <th key={g} className="p-3">{gateLabels[g]}</th>)}
              <th className="p-3" title="Rule checks propose a decision for all three reviews. Nothing is saved until you accept it with a reason.">Actions</th>
            </tr>
          </thead>
          <tbody>
            {agents.filter(a => !only || summary?.positions[a.id] === only).map(a => (
              <tr key={a.id} className="border-b last:border-0">
                <td className="p-3 font-medium"><Link to={`/agents/${a.id}?tab=governance`} className="hover:underline">{a.name}</Link></td>
                <td className="p-3">{a.stage}</td>
                {gates.map(g => {
                  const status = a.reviews?.[g] || 'Not Submitted'
                  const needed = requiredReviewsOf(summary, a.riskLevel).includes(g)
                  return (
                    <td key={g} className="p-3">
                      {!needed && status === 'Not Submitted'
                        ? <span className="text-xs text-slate-500" title={`Not required for ${a.riskLevel || 'LOW'} risk (Settings → Governance rules)`}>Not required</span>
                        : <Link to={`/agents/${a.id}?tab=governance`} data-testid="review-status"
                            className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ring-1 hover:underline ${STATUS_PILL[status] || STATUS_PILL['Not Submitted']}`}>{status}</Link>}
                    </td>
                  )
                })}
                <td className="p-3">
                  <button
                    onClick={() => handleRunGovernance(a.id)}
                    disabled={running === a.id || !can(me, 'update')}
                    className="btn-secondary btn-sm whitespace-nowrap"
                    title="Rule checks propose a decision for all three reviews. Nothing is saved until you accept it with a reason."
                  >
                    {running === a.id ? 'Checking…' : 'Propose by rules'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

    </div>
  )
}