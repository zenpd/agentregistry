import { useState, useEffect } from 'react'
import { getAgents, type Agent } from '../services/api'

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [stageFilter, setStageFilter] = useState('')

  useEffect(() => { fetchAgents() }, [])

  async function fetchAgents() {
    try {
      setLoading(true)
      const resp = await getAgents(1, 100, { q: search || undefined, stage: stageFilter || undefined })
      setAgents(resp.data.data)
      setError(null)
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Failed to fetch')
    } finally {
      setLoading(false)
    }
  }

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => { fetchAgents() }, 300)
    return () => clearTimeout(timer)
  }, [search, stageFilter])

  if (loading && agents.length === 0) return <div className="p-8 text-center text-gray-500">Loading...</div>
  if (error) return <div className="p-8 text-center text-red-500">Error: {error}</div>

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">AI Registry</h1>
      <div className="flex gap-3">
        <input
          type="text"
          placeholder="Search agents..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="border rounded px-3 py-2 text-sm flex-1"
        />
        <select value={stageFilter} onChange={e => setStageFilter(e.target.value)} className="border rounded px-3 py-2 text-sm">
          <option value="">All stages</option>
          <option value="Ideation">Ideation</option>
          <option value="Development">Development</option>
          <option value="Testing">Testing</option>
          <option value="Production">Production</option>
          <option value="Deprecated">Deprecated</option>
        </select>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {agents.map(a => (
          <div key={a.id} className="bg-white rounded-lg border p-4 hover:shadow-md transition">
            <div className="flex justify-between items-start">
              <h3 className="font-semibold">{a.name}</h3>
              <span className="text-xs px-2 py-0.5 rounded bg-gray-100">{a.stage}</span>
            </div>
            <p className="text-sm text-gray-600 mt-2 line-clamp-2">{a.description}</p>
            <div className="mt-3 flex justify-between text-xs text-gray-500">
              <span>{a.aiType}</span>
              <span className="font-mono">${(a.valueAmount / 1000).toFixed(0)}K/mo</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
