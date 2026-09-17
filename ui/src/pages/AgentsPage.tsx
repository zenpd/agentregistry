import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getAgents, getTaxonomy, type Agent, type Taxonomy } from '../services/api'
import OnboardingModal from '../components/OnboardingModal'

const STAGE_PILL: Record<string, string> = {
  Ideation: 'status-pending',
  Development: 'status-active',
  Testing: 'status-review',
  Production: 'status-complete',
  Deprecated: 'status-failed',
}

export default function AgentsPage() {
  const navigate = useNavigate()
  const [agents, setAgents] = useState<Agent[]>([])
  const [taxonomy, setTaxonomy] = useState<Taxonomy | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [stageFilter, setStageFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [deptFilter, setDeptFilter] = useState('')
  const [catFilter, setCatFilter] = useState('')
  const [showOnboarding, setShowOnboarding] = useState(false)

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
  if (error) return <div className="p-8 text-center text-rose-500">Error: {error}</div>

  return (
    <div className="space-y-4 animate-fade-in">
      <div className="page-header">
        <h1 className="page-title text-2xl">AI Registry</h1>
        <button onClick={() => setShowOnboarding(true)} className="btn-primary">
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
          className="input flex-1 min-w-[200px]"
        />
        <select value={stageFilter} onChange={e => setStageFilter(e.target.value)} className="input w-auto">
          <option value="">All stages</option>
          <option value="Ideation">Ideation</option>
          <option value="Development">Development</option>
          <option value="Testing">Testing</option>
          <option value="Production">Production</option>
          <option value="Deprecated">Deprecated</option>
        </select>
        <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)} className="input w-auto">
          <option value="">All types</option>
          {types.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={deptFilter} onChange={e => setDeptFilter(e.target.value)} className="input w-auto">
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
            className={`text-xs px-3 py-1 rounded-full border transition-colors ${
              (cat === 'All' && !catFilter) || (cat !== 'All' && catFilter === cat.toLowerCase())
                ? 'bg-teal-600 text-white border-teal-600'
                : 'bg-white text-gray-500 border-gray-200 hover:border-gray-300 hover:text-gray-700'
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
            onClick={() => navigate(`/agents/${a.id}`)}
            className="card-hover p-4"
          >
            <div className="flex justify-between items-start gap-2">
              <h3 className="font-semibold text-gray-900">{a.name}</h3>
              <span className={`shrink-0 ${STAGE_PILL[a.stage] || 'status-pending'}`}>{a.stage}</span>
            </div>
            <p className="text-sm text-gray-500 mt-2 line-clamp-2">{a.description || 'No description yet.'}</p>

            {/* Dependency badges */}
            <div className="mt-2 flex flex-wrap gap-1">
              {a.enterpriseSystems?.slice(0, 2).map(s => (
                <span key={s} className="text-xs bg-teal-50 text-teal-700 ring-1 ring-teal-200 px-1.5 py-0.5 rounded">{s}</span>
              ))}
              {a.databases?.slice(0, 1).map(d => (
                <span key={d} className="text-xs bg-amber-50 text-amber-700 ring-1 ring-amber-200 px-1.5 py-0.5 rounded">{d}</span>
              ))}
              {a.mcpServers?.slice(0, 1).map(m => (
                <span key={m} className="text-xs bg-purple-50 text-purple-700 ring-1 ring-purple-200 px-1.5 py-0.5 rounded">{m}</span>
              ))}
              {a.calls?.length > 0 && (
                <span className="text-xs bg-blue-50 text-blue-700 ring-1 ring-blue-200 px-1.5 py-0.5 rounded">calls {a.calls.length}</span>
              )}
            </div>

            <div className="mt-3 flex justify-between text-xs text-gray-500">
              <span>{a.aiType}</span>
              <span className="font-mono">${(a.valueAmount / 1000).toFixed(0)}K/mo</span>
            </div>
          </div>
        ))}
      </div>

      {showOnboarding && (
        <OnboardingModal
          onClose={() => setShowOnboarding(false)}
          onSaved={() => { setShowOnboarding(false); fetchData() }}
        />
      )}
    </div>
  )
}
