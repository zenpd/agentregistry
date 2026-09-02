import { useState, useEffect } from 'react'
import { getAgents, getGovernanceOverview, updateGate, type Agent, type GovernanceOverview } from '../services/api'

export default function GovernancePage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [overview, setOverview] = useState<GovernanceOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { fetchData() }, [])

  async function fetchData() {
    try {
      setLoading(true)
      const [agentsRes, overviewRes] = await Promise.all([
        getAgents(1, 100),
        getGovernanceOverview()
      ])
      setAgents(agentsRes.data.data)
      setOverview(overviewRes.data)
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

  const gates = ['arb', 'security', 'dp']
  const gateLabels: Record<string, string> = { arb: 'Architecture Review', security: 'Security Review', dp: 'Data Protection' }
  const statuses = ['Not Submitted', 'In Review', 'Changes Requested', 'Approved with Conditions', 'Approved']

  if (loading) return <div className="p-8 text-center text-gray-500">Loading...</div>
  if (error) return <div className="p-8 text-center text-red-500">Error: {error}</div>

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Governance & Discovery</h1>

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
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
