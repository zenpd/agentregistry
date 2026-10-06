import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  getAgents, getGovernanceOverview, updateGate, getDiscoveries,
  registerDiscovery, dismissDiscovery, runGovernance,
  type Agent, type GovernanceOverview, type Discovery
} from '../services/api'
import InfoTip from '../components/InfoTip'
import { errorMessage } from './agent/shared'

export default function GovernancePage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [overview, setOverview] = useState<GovernanceOverview | null>(null)
  const [discoveries, setDiscoveries] = useState<Discovery[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState<string | null>(null)
  // Outcome of the last gate change or auto-review, shown instead of only logged.
  const [notice, setNotice] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)

  useEffect(() => { fetchData() }, [])

  async function fetchData() {
    try {
      setLoading(true)
      const [agentsRes, overviewRes, discRes] = await Promise.all([
        getAgents(1, 100),
        getGovernanceOverview(),
        getDiscoveries()
      ])
      setAgents(agentsRes.data.data)
      setOverview(overviewRes.data)
      setDiscoveries(discRes.data)
      setError(null)
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Failed to fetch')
    } finally {
      setLoading(false)
    }
  }

  async function handleUpdateGate(agentId: string, gate: string, status: string) {
    const name = agents.find(a => a.id === agentId)?.name || agentId
    try {
      await updateGate(agentId, gate, status)
      await fetchData()
      setNotice({ tone: 'ok', text: `${name}: ${gateLabels[gate]} set to ${status}.` })
    } catch (e: any) {
      setNotice({ tone: 'error', text: `${name}: ${gateLabels[gate]} was not changed — ${errorMessage(e, 'the update failed')}` })
    }
  }

  async function handleRunGovernance(agentId: string) {
    const name = agents.find(a => a.id === agentId)?.name || agentId
    setRunning(agentId)
    try {
      const res = (await runGovernance(agentId)).data as { status?: string; message?: string; reviews?: Record<string, string> }
      await fetchData()
      if (res?.reviews) {
        const set = gates.map(g => `${gateLabels[g]}: ${res.reviews![g]}`).join(' · ')
        setNotice({ tone: 'ok', text: `Auto-review of ${name} set ${set}.` })
      } else {
        setNotice({ tone: 'error', text: `Auto-review of ${name} did not run — ${res?.message || 'no result returned'}.` })
      }
    } catch (e: any) {
      setNotice({ tone: 'error', text: `Auto-review of ${name} failed — ${errorMessage(e, 'the request failed')}` })
    } finally {
      setRunning(null)
    }
  }

  async function handleRegister(disc: Discovery) {
    try {
      await registerDiscovery(disc.id)
      await fetchData()
    } catch (e: any) {
      console.error('Register failed:', e)
    }
  }

  async function handleDismiss(disc: Discovery) {
    try {
      await dismissDiscovery(disc.id)
      await fetchData()
    } catch (e: any) {
      console.error('Dismiss failed:', e)
    }
  }

  const gates = ['arb', 'security', 'dp']
  const gateLabels: Record<string, string> = { arb: 'Architecture Review Board', security: 'Security Review', dp: 'Data Protection Review' }
  const statuses = ['Not Submitted', 'In Review', 'Changes Requested', 'Approved with Conditions', 'Approved']
  const pendingDiscs = discoveries.filter(d => d.status === 'pending')

  // KPI calculations
  // Approved with conditions is still approved, as on the reuse checklist and in the prototype.
  const cleared = agents.filter(a => ['arb', 'security', 'dp'].every(g => ['Approved', 'Approved with Conditions'].includes(a.reviews?.[g] || ''))).length
  const blocked = agents.filter(a => ['arb', 'security', 'dp'].some(g => a.reviews?.[g] === 'Changes Requested')).length
  const inReview = agents.filter(a => ['arb', 'security', 'dp'].some(g => a.reviews?.[g] === 'In Review')).length

  if (loading) return <div className="p-8 text-center text-slate-600">Loading...</div>
  if (error) return <div className="p-8 text-center text-red-500">Error: {error}</div>

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold gradient-text">Governance</h1>
        <p className="text-slate-600 mt-0.5">Every agent’s path through Architecture, Security and Data Protection review, plus checks on registered agents that look off. New AI found in Phoenix is on the <Link to="/discovered" className="font-medium text-zen-700 hover:underline">Discovered</Link> page.</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-4">
        <div className="card p-4">
          <div className="text-2xl font-bold text-green-600">{cleared}</div>
          <div className="text-xs font-medium text-slate-700">Cleared for production</div>
          <div className="text-[12px] text-slate-500 mt-0.5">All three reviews approved (with or without conditions)</div>
        </div>
        <div className="card p-4">
          <div className="text-2xl font-bold text-red-600">{blocked}</div>
          <div className="text-xs font-medium text-slate-700">Blocked</div>
          <div className="text-[12px] text-slate-500 mt-0.5">Changes requested on at least one review</div>
        </div>
        <div className="card p-4">
          <div className="text-2xl font-bold text-amber-600">{inReview}</div>
          <div className="text-xs font-medium text-slate-700">In active review</div>
          <div className="text-[12px] text-slate-500 mt-0.5">At least one review awaiting a decision</div>
        </div>
        <div className="card p-4">
          <div className="text-2xl font-bold text-orange-600">{pendingDiscs.length}</div>
          <div className="text-xs font-medium text-slate-700 flex items-center">Governance findings <InfoTip term="governance_findings" className="ml-1" /></div>
          <div className="text-[12px] text-slate-500 mt-0.5">Checks on registered agents, waiting for a decision</div>
        </div>
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

      {/* Review Status Table */}
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-600 border-b">
              <th className="p-3">Agent</th>
              <th className="p-3">Stage</th>
              {gates.map(g => <th key={g} className="p-3">{gateLabels[g]}</th>)}
              <th className="p-3" title="Auto-review runs rule checks and overwrites all three review statuses with its result">Actions</th>
            </tr>
          </thead>
          <tbody>
            {agents.map(a => (
              <tr key={a.id} className="border-b last:border-0">
                <td className="p-3 font-medium">{a.name}</td>
                <td className="p-3">{a.stage}</td>
                {gates.map(g => (
                  <td key={g} className="p-3">
                    <select
                      value={a.reviews?.[g] || 'Not Submitted'}
                      onChange={e => handleUpdateGate(a.id, g, e.target.value)}
                      className="border rounded px-2 py-1 text-xs"
                    >
                      {statuses.map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </td>
                ))}
                <td className="p-3">
                  <button
                    onClick={() => handleRunGovernance(a.id)}
                    disabled={running === a.id}
                    className="btn-secondary btn-sm whitespace-nowrap"
                    title="Runs rule-based checks and overwrites all three review statuses with the result"
                  >
                    {running === a.id ? 'Running…' : 'Run auto-review'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Discovery Feed */}
      {pendingDiscs.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-3 flex items-center">Governance findings <InfoTip term="governance_findings" className="ml-1" /></h2>
          <div className="grid grid-cols-2 gap-4">
            {pendingDiscs.map(d => (
              <div key={d.id} className="card p-4">
                <div className="flex justify-between items-start">
                  <div>
                    <div className="font-medium">{d.suspectedName}</div>
                    <div className="text-xs text-slate-600 mt-1">{d.suspectedDept} · {d.source}</div>
                  </div>
                  <span className={`text-xs px-2 py-1 rounded border ${
                    d.confidence >= 85 ? 'bg-green-50 text-green-700 border-green-200' :
                    d.confidence >= 70 ? 'bg-amber-50 text-amber-700 border-amber-200' :
                    'bg-red-50 text-red-700 border-red-200'
                  }`}>
                    {d.confidence}% confidence
                  </span>
                </div>
                {d.signal && <div className="text-xs text-slate-700 mt-2">{d.signal}</div>}
                <div className="flex gap-2 mt-3">
                  <button
                    onClick={() => handleRegister(d)}
                    className="text-xs bg-zen-600 text-white px-3 py-1.5 rounded hover:bg-zen-700"
                  >
                    Register agent
                  </button>
                  <button
                    onClick={() => handleDismiss(d)}
                    className="text-xs bg-gray-100 text-slate-700 px-3 py-1.5 rounded hover:bg-gray-200"
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}