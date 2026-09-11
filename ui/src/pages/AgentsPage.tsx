import { useState, useEffect } from 'react'
import { getAgents, getTaxonomy, type Agent, type Taxonomy } from '../services/api'
import AgentDetailModal from '../components/AgentDetailModal'

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [taxonomy, setTaxonomy] = useState<Taxonomy | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [stageFilter, setStageFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [deptFilter, setDeptFilter] = useState('')
  const [catFilter, setCatFilter] = useState('')
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null)

  useEffect(() => { fetchData() }, [])

  async function fetchData() {
    try {
      setLoading(true)
      const [resp, taxRes] = await Promise.all([
        getAgents(1, 100, { q: search || undefined, stage: stageFilter || undefined }),
        getTaxonomy()
      ])
      setAgents(resp.data.data)
      setTaxonomy(taxRes.data)
      setError(null)
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Failed to fetch')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const timer = setTimeout(() => { fetchData() }, 300)
    return () => clearTimeout(timer)
  }, [search, stageFilter, typeFilter, deptFilter, catFilter])

  const depts = [...new Set(agents.map(a => a.dept).filter(Boolean))].sort()
  const types = taxonomy?.aiTypes || [...new Set(agents.map(a => a.aiType).filter(Boolean))].sort()

  // Filter by type, dept, category
  const filtered = agents.filter(a => {
    if (typeFilter && a.aiType !== typeFilter) return false
    if (deptFilter && a.dept !== deptFilter) return false
    if (catFilter) {
      const cats: string[] = []
      if (a.enterpriseSystems?.length) cats.push('sys')
      if (a.databases?.length) cats.push('db')
      if (a.mcpServers?.length) cats.push('mcp')
      if (a.knowledgeBases?.length) cats.push('kb')
      if (a.calls?.length) cats.push('agents')
      if (!cats.includes(catFilter)) return false
    }
    return true
  })

  if (loading && agents.length === 0) return <div className="p-8 text-center text-gray-500">Loading...</div>
  if (error) return <div className="p-8 text-center text-red-500">Error: {error}</div>

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold">AI Registry</h1>
        <button
          onClick={() => setSelectedAgent('new')}
          className="bg-teal-600 text-white px-4 py-2 rounded text-sm hover:bg-teal-700"
        >
          + Register new AI application
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <input
          type="text"
          placeholder="Search agents..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="border rounded px-3 py-2 text-sm flex-1 min-w-[200px]"
        />
        <select value={stageFilter} onChange={e => setStageFilter(e.target.value)} className="border rounded px-3 py-2 text-sm">
          <option value="">All stages</option>
          <option value="Ideation">Ideation</option>
          <option value="Development">Development</option>
          <option value="Testing">Testing</option>
          <option value="Production">Production</option>
          <option value="Deprecated">Deprecated</option>
        </select>
        <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)} className="border rounded px-3 py-2 text-sm">
          <option value="">All types</option>
          {types.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={deptFilter} onChange={e => setDeptFilter(e.target.value)} className="border rounded px-3 py-2 text-sm">
          <option value="">All departments</option>
          {depts.map(d => <option key={d} value={d}>{d}</option>)}
        </select>
      </div>

      {/* Category chips */}
      <div className="flex gap-2">
        {['All', 'MCP', 'Systems', 'Databases', 'Knowledge', 'Agent calls'].map(cat => (
          <button
            key={cat}
            onClick={() => setCatFilter(cat === 'All' ? '' : cat.toLowerCase())}
            className={`text-xs px-3 py-1 rounded border ${
              (cat === 'All' && !catFilter) || (cat !== 'All' && catFilter === cat.toLowerCase())
                ? 'bg-teal-600 text-white border-teal-600'
                : 'bg-transparent text-gray-400 border-gray-700 hover:border-gray-500'
            }`}
          >
            {cat}
          </button>
        ))}
      </div>

      {/* Registry cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.map(a => (
          <div
            key={a.id}
            onClick={() => setSelectedAgent(a.id)}
            className="bg-gray-900 rounded-lg border border-gray-700 p-4 hover:border-teal-500 cursor-pointer transition"
          >
            <div className="flex justify-between items-start">
              <h3 className="font-semibold">{a.name}</h3>
              <span className="text-xs px-2 py-0.5 rounded bg-gray-800">{a.stage}</span>
            </div>
            <p className="text-sm text-gray-400 mt-2 line-clamp-2">{a.description}</p>

            {/* Dependency badges */}
            <div className="mt-2 flex flex-wrap gap-1">
              {a.enterpriseSystems?.slice(0, 2).map(s => (
                <span key={s} className="text-xs bg-teal-900/30 text-teal-300 px-1.5 py-0.5 rounded">{s}</span>
              ))}
              {a.databases?.slice(0, 1).map(d => (
                <span key={d} className="text-xs bg-amber-900/30 text-amber-300 px-1.5 py-0.5 rounded">{d}</span>
              ))}
              {a.mcpServers?.slice(0, 1).map(m => (
                <span key={m} className="text-xs bg-purple-900/30 text-purple-300 px-1.5 py-0.5 rounded">{m}</span>
              ))}
              {a.calls?.length > 0 && (
                <span className="text-xs bg-blue-900/30 text-blue-300 px-1.5 py-0.5 rounded">calls {a.calls.length}</span>
              )}
            </div>

            <div className="mt-3 flex justify-between text-xs text-gray-500">
              <span>{a.aiType}</span>
              <span className="font-mono">${(a.valueAmount / 1000).toFixed(0)}K/mo</span>
            </div>
          </div>
        ))}
      </div>

      {selectedAgent && (
        <AgentDetailModal
          agentId={selectedAgent}
          onClose={() => setSelectedAgent(null)}
          onSaved={() => { setSelectedAgent(null); fetchData() }}
        />
      )}
    </div>
  )
}