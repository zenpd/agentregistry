import { useState, useEffect } from 'react'
import {
  getAgents, getGovernanceOverview, updateGate, getDiscoveries,
  registerDiscovery, dismissDiscovery, runGovernance,
  type Agent, type GovernanceOverview, type Discovery
} from '../services/api'

export default function GovernancePage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [overview, setOverview] = useState<GovernanceOverview | null>(null)
  const [discoveries, setDiscoveries] = useState<Discovery[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState<string | null>(null)

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
    try {
      await updateGate(agentId, gate, status)
      await fetchData()
    } catch (e: any) {
      console.error('Failed to update gate:', e)
    }
  }

  async function handleRunGovernance(agentId: string) {
    setRunning(agentId)
    try {
      await runGovernance(agentId)
      await fetchData()
    } catch (e: any) {
      console.error('Governance run failed:', e)
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
  const gateLabels: Record<string, string> = { arb: 'Architecture Review', security: 'Security Review', dp: 'Data Protection' }
  const statuses = ['Not Submitted', 'In Review', 'Changes Requested', 'Approved with Conditions', 'Approved']
  const pendingDiscs = discoveries.filter(d => d.status === 'pending')

  // KPI calculations
  const cleared = agents.filter(a => ['arb', 'security', 'dp'].every(g => a.reviews?.[g] === 'Approved')).length
  const blocked = agents.filter(a => ['arb', 'security', 'dp'].some(g => a.reviews?.[g] === 'Changes Requested')).length
  const inReview = agents.filter(a => ['arb', 'security', 'dp'].some(g => a.reviews?.[g] === 'In Review')).length

  if (loading) return <div className="p-8 text-center text-gray-500">Loading...</div>
  if (error) return <div className="p-8 text-center text-red-500">Error: {error}</div>

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Governance & Discovery</h1>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-white rounded-lg border p-4">
          <div className="text-2xl font-bold text-green-600">{cleared}</div>
          <div className="text-xs text-gray-500">Cleared for production</div>
        </div>
        <div className="bg-white rounded-lg border p-4">
          <div className="text-2xl font-bold text-red-600">{blocked}</div>
          <div className="text-xs text-gray-500">Blocked</div>
        </div>
        <div className="bg-white rounded-lg border p-4">
          <div className="text-2xl font-bold text-amber-600">{inReview}</div>
          <div className="text-xs text-gray-500">In active review</div>
        </div>
        <div className="bg-white rounded-lg border p-4">
          <div className="text-2xl font-bold text-coral-600">{pendingDiscs.length}</div>
          <div className="text-xs text-gray-500">Unregistered AI apps found</div>
        </div>
      </div>

      {/* Gate Breakdown */}
      {overview && (
        <div className="grid grid-cols-3 gap-4">
          {gates.map(gate => (
            <div key={gate} className="bg-white rounded-lg border p-4">
              <h3 className="font-semibold text-sm mb-2">{gateLabels[gate]}</h3>
              <div className="space-y-1">
                {Object.entries(overview[gate] || {}).map(([status, count]) => (
                  <div key={status} className="flex justify-between text-xs">
                    <span className="text-gray-600">{status}</span>
                    <span className="font-mono">{count}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Review Status Table */}
      <div className="bg-white rounded-lg border overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b">
              <th className="p-3">Agent</th>
              <th className="p-3">Stage</th>
              {gates.map(g => <th key={g} className="p-3">{gateLabels[g]}</th>)}
              <th className="p-3">Actions</th>
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
                    className="text-xs bg-teal-50 text-teal-700 px-2 py-1 rounded hover:bg-teal-100 disabled:opacity-50"
                  >
                    {running === a.id ? 'Running...' : 'Run review'}
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
          <h2 className="text-lg font-semibold mb-3">Auto-discovered unregistered AI</h2>
          <div className="grid grid-cols-2 gap-4">
            {pendingDiscs.map(d => (
              <div key={d.id} className="bg-white rounded-lg border p-4">
                <div className="flex justify-between items-start">
                  <div>
                    <div className="font-medium">{d.suspectedName}</div>
                    <div className="text-xs text-gray-500 mt-1">{d.suspectedDept} · {d.source}</div>
                  </div>
                  <span className={`text-xs px-2 py-1 rounded border ${
                    d.confidence >= 85 ? 'bg-green-50 text-green-700 border-green-200' :
                    d.confidence >= 70 ? 'bg-amber-50 text-amber-700 border-amber-200' :
                    'bg-red-50 text-red-700 border-red-200'
                  }`}>
                    {d.confidence}%
                  </span>
                </div>
                {d.signal && <div className="text-xs text-gray-600 mt-2">{d.signal}</div>}
                <div className="flex gap-2 mt-3">
                  <button
                    onClick={() => handleRegister(d)}
                    className="text-xs bg-teal-600 text-white px-3 py-1.5 rounded hover:bg-teal-700"
                  >
                    Register agent
                  </button>
                  <button
                    onClick={() => handleDismiss(d)}
                    className="text-xs bg-gray-100 text-gray-700 px-3 py-1.5 rounded hover:bg-gray-200"
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