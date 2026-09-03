import { useState, useEffect } from 'react'
import { getAgents, getValueByDepartment, type Agent } from '../services/api'

export default function BusinessView() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [deptValues, setDeptValues] = useState<{ department: string; agentCount: number; totalValue: number }[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedDept, setSelectedDept] = useState('')

  useEffect(() => { fetchData() }, [])

  async function fetchData() {
    try {
      setLoading(true)
      const [agentsRes, valuesRes] = await Promise.all([
        getAgents(1, 100),
        getValueByDepartment(),
      ])
      setAgents(agentsRes.data.data)
      setDeptValues(valuesRes.data)
      setError(null)
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Failed to fetch')
    } finally {
      setLoading(false)
    }
  }

  const departments = [...new Set(agents.map(a => a.dept).filter((d): d is string => Boolean(d)))]
  const filtered = selectedDept ? agents.filter(a => a.dept === selectedDept) : agents
  const inProd = agents.filter(a => a.stage === 'Production')
  const totalValue = inProd.reduce((s, a) => s + (a.valueAmount || 0), 0)
  const totalHours = agents.reduce((s, a) => s + (a.hoursSavedMonthly || 0), 0)

  if (loading) return <div className="p-8 text-center text-gray-500">Loading...</div>
  if (error) return <div className="p-8 text-center text-red-500">Error: {error}</div>

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Business Impact</h1>

      {/* Department Filter */}
      <div className="flex gap-2 flex-wrap">
        <button
          onClick={() => setSelectedDept('')}
          className={`px-3 py-1 rounded text-sm ${!selectedDept ? 'bg-blue-600 text-white' : 'bg-gray-200'}`}
        >
          All
        </button>
        {departments.map(dept => (
          <button
            key={dept}
            onClick={() => setSelectedDept(dept)}
            className={`px-3 py-1 rounded text-sm ${selectedDept === dept ? 'bg-blue-600 text-white' : 'bg-gray-200'}`}
          >
            {dept}
          </button>
        ))}
      </div>

      {/* 3 KPI Cards */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white rounded-lg border p-4">
          <div className="text-xs text-gray-500 uppercase">Agents Running</div>
          <div className="text-2xl font-bold">{inProd.length}</div>
          <div className="text-xs text-gray-400">In production</div>
        </div>
        <div className="bg-white rounded-lg border p-4">
          <div className="text-xs text-gray-500 uppercase">Value/Month</div>
          <div className="text-2xl font-bold">${(totalValue / 1000).toFixed(0)}K</div>
          <div className="text-xs text-gray-400">Realized</div>
        </div>
        <div className="bg-white rounded-lg border p-4">
          <div className="text-xs text-gray-500 uppercase">Hours Saved/Month</div>
          <div className="text-2xl font-bold">{totalHours}</div>
          <div className="text-xs text-gray-400">≈ {Math.round(totalHours / 173)} FTE</div>
        </div>
      </div>

      {/* Value by Department */}
      <div className="grid grid-cols-3 gap-4">
        {deptValues.map(dv => (
          <div key={dv.department} className="bg-white rounded-lg border p-4">
            <div className="text-sm text-gray-500">{dv.department}</div>
            <div className="text-xl font-bold">${(dv.totalValue / 1000).toFixed(0)}K/mo</div>
            <div className="text-xs text-gray-400">{dv.agentCount} agents</div>
          </div>
        ))}
      </div>

      {/* Agent Table */}
      <div className="bg-white rounded-lg border overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b">
              <th className="p-3">Agent</th>
              <th className="p-3">Department</th>
              <th className="p-3">AI Type</th>
              <th className="p-3">Stage</th>
              <th className="p-3">Owner</th>
              <th className="p-3">Outcome</th>
              <th className="p-3 text-right">Value/mo</th>
              <th className="p-3 text-right">Hours Saved</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(a => (
              <tr key={a.id} className="border-b last:border-0">
                <td className="p-3 font-medium">{a.name}</td>
                <td className="p-3">{a.dept || '—'}</td>
                <td className="p-3 text-xs text-gray-600">{a.aiType}</td>
                <td className="p-3">
                  <span className="text-xs px-2 py-0.5 rounded bg-gray-100">{a.stage}</span>
                </td>
                <td className="p-3">{a.owner}</td>
                <td className="p-3 truncate max-w-xs">{a.businessOutcome}</td>
                <td className="p-3 text-right font-mono">${(a.valueAmount / 1000).toFixed(0)}K</td>
                <td className="p-3 text-right">{a.hoursSavedMonthly}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
