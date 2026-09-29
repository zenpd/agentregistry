import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { BadgeCheck, Pencil, Trash2 } from 'lucide-react'
import { getAgents, getTaxonomy, type RegistryAgent, type Taxonomy } from '../services/api'
import OnboardingModal from '../components/OnboardingModal'
import EditAgentModal from '../components/EditAgentModal'
import DeleteAgentDialog from '../components/DeleteAgentDialog'
import { fmtCostPerCall } from './agent/shared'

const STAGE_PILL: Record<string, string> = {
  Ideation: 'status-pending',
  Development: 'status-active',
  Testing: 'status-review',
  Production: 'status-complete',
  Deprecated: 'status-failed',
}

// Chip label -> the dependency list it filters on.
const CATEGORIES: { label: string; key: string; has: (a: RegistryAgent) => boolean }[] = [
  { label: 'MCP', key: 'mcp', has: a => !!a.mcpServers?.length },
  { label: 'Systems', key: 'sys', has: a => !!a.enterpriseSystems?.length },
  { label: 'Databases', key: 'db', has: a => !!a.databases?.length },
  { label: 'Knowledge', key: 'kb', has: a => !!a.knowledgeBases?.length },
  { label: 'Agent calls', key: 'agents', has: a => !!a.calls?.length },
]

function CostPerCall({ agent }: { agent: RegistryAgent }) {
  const { costPerCallCents, source, pricing } = agent.card
  if (costPerCallCents == null) {
    return (
      <span className="text-gray-400" title={pricing === 'missing'
        ? 'The model this agent runs on has no price recorded, so cost per call is unknown.'
        : 'No usage recorded yet.'}>— /call</span>
    )
  }
  const title = [
    'Average token cost per call over the last 30 days, as on the Tokenomics tab.',
    source === 'seed' ? 'Demo data: no real traces ingested yet.' : '',
    pricing === 'partial' ? 'Some calls used a model with no price, so this is a lower bound.' : '',
  ].filter(Boolean).join(' ')
  return (
    <span title={title}>
      <span className="font-mono">{pricing === 'partial' && '≥'}{fmtCostPerCall(costPerCallCents)}</span>/call
      {source === 'seed' && <span className="ml-1 text-[10px] uppercase text-gray-400">demo</span>}
    </span>
  )
}

export default function AgentsPage() {
  const navigate = useNavigate()
  const [agents, setAgents] = useState<RegistryAgent[]>([])
  const [taxonomy, setTaxonomy] = useState<Taxonomy | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [stageFilter, setStageFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [deptFilter, setDeptFilter] = useState('')
  const [catFilter, setCatFilter] = useState('')
  const [certifiedOnly, setCertifiedOnly] = useState(false)
  const [showOnboarding, setShowOnboarding] = useState(false)
  const [editing, setEditing] = useState<RegistryAgent | null>(null)
  const [deleting, setDeleting] = useState<RegistryAgent | null>(null)

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

  // Only the search and stage go to the server; the other filters work on the loaded list.
  useEffect(() => {
    const timer = setTimeout(() => { fetchData() }, 300)
    return () => clearTimeout(timer)
  }, [search, stageFilter])

  const depts = [...new Set(agents.map(a => a.dept).filter(Boolean))].sort()
  const types = taxonomy?.aiTypes || [...new Set(agents.map(a => a.aiType).filter(Boolean))].sort()
  const category = CATEGORIES.find(c => c.key === catFilter)

  const filtered = agents.filter(a => {
    if (typeFilter && a.aiType !== typeFilter) return false
    if (deptFilter && a.dept !== deptFilter) return false
    if (category && !category.has(a)) return false
    if (certifiedOnly && !a.reuse.certified) return false
    return true
  })
  const certifiedCount = agents.filter(a => a.reuse.certified).length

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
          placeholder="Search by what you need, e.g. reconcile invoices"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="input flex-1 min-w-[200px]"
          aria-label="Search agents"
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
      <div className="flex gap-2 flex-wrap items-center">
        <button
          onClick={() => setCertifiedOnly(v => !v)}
          aria-pressed={certifiedOnly}
          data-testid="certified-filter"
          title="Production, every governance gate approved, and no HIGH or CRITICAL risk open"
          className={`text-xs px-3 py-1 rounded-full border transition-colors flex items-center gap-1 ${
            certifiedOnly
              ? 'bg-emerald-600 text-white border-emerald-600'
              : 'bg-white text-emerald-700 border-emerald-200 hover:border-emerald-300'
          }`}
        >
          <BadgeCheck size={13} /> Certified for reuse ({certifiedCount})
        </button>
        <span className="w-px h-4 bg-gray-200" />
        {[{ label: 'All', key: '' }, ...CATEGORIES].map(cat => (
          <button
            key={cat.label}
            onClick={() => setCatFilter(cat.key)}
            className={`text-xs px-3 py-1 rounded-full border transition-colors ${
              catFilter === cat.key
                ? 'bg-teal-600 text-white border-teal-600'
                : 'bg-white text-gray-500 border-gray-200 hover:border-gray-300 hover:text-gray-700'
            }`}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {search.trim() && (
        <p className="text-xs text-gray-500" data-testid="search-summary">
          {filtered.length} agent{filtered.length === 1 ? '' : 's'} match “{search.trim()}”, best match first.
          {filtered.length === 0 && ' Nothing registered does this yet, so registering a new application is justified.'}
        </p>
      )}

      {/* Registry cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.map(a => (
          <div
            key={a.id}
            onClick={() => navigate(`/agents/${a.id}`)}
            className="card-hover p-4 flex flex-col"
            data-testid="registry-card"
          >
            <div className="flex justify-between items-start gap-2">
              <h3 className="font-semibold text-gray-900">{a.name}</h3>
              <span className={`shrink-0 ${STAGE_PILL[a.stage] || 'status-pending'}`}>{a.stage}</span>
            </div>
            {a.reuse.certified ? (
              <span className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-emerald-700" data-testid="certified-badge">
                <BadgeCheck size={13} /> Certified for reuse
              </span>
            ) : a.stage === 'Production' && (
              <span className="mt-1 text-xs text-amber-700" title={a.reuse.unmet.map(u => u.message).join('\n')}>
                Not certified: {a.reuse.unmet[0]?.message}
              </span>
            )}
            <p className="text-sm text-gray-500 mt-2 line-clamp-2">{a.description || 'No description yet.'}</p>

            {a.capabilities?.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {a.capabilities.slice(0, 3).map(c => (
                  <span key={c} className="text-xs bg-teal-50 text-teal-700 ring-1 ring-teal-200 px-1.5 py-0.5 rounded">{c}</span>
                ))}
              </div>
            )}

            {/* Dependency badges */}
            <div className="mt-2 flex flex-wrap gap-1">
              {a.enterpriseSystems?.slice(0, 2).map(s => (
                <span key={s} className="text-xs bg-slate-50 text-slate-600 ring-1 ring-slate-200 px-1.5 py-0.5 rounded">{s}</span>
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

            {a.matchedTerms.length > 0 && (
              <p className="mt-2 text-xs text-gray-400">Matched: {a.matchedTerms.join(', ')}</p>
            )}

            <div className="mt-auto pt-3 space-y-1 text-xs text-gray-500">
              <div className="flex items-center justify-between gap-2">
                <span>{a.aiType}</span>
                {/* stopPropagation: the tile itself opens the agent. */}
                <span className="flex gap-1 shrink-0" onClick={e => e.stopPropagation()}>
                  <button type="button" onClick={() => setEditing(a)} aria-label={`Edit ${a.name}`} title="Edit"
                    className="p-1.5 rounded-lg text-gray-400 hover:text-teal-700 hover:bg-teal-50 transition-colors">
                    <Pencil size={14} />
                  </button>
                  <button type="button" onClick={() => setDeleting(a)} aria-label={`Delete ${a.name}`} title="Delete"
                    className="p-1.5 rounded-lg text-gray-400 hover:text-rose-700 hover:bg-rose-50 transition-colors">
                    <Trash2 size={14} />
                  </button>
                </span>
              </div>
              <div className="flex justify-between gap-2 border-t border-gray-100 pt-1.5">
                <CostPerCall agent={a} />
                <span title="Teams and systems consuming this agent">{a.card.consumerCount} consumer{a.card.consumerCount === 1 ? '' : 's'}</span>
                {a.valueAmount ? (
                  <span className="font-mono" title="Declared value per month">${(a.valueAmount / 1000).toFixed(0)}K/mo</span>
                ) : (
                  <span className="text-gray-400" title="No monthly value declared on the agent record">Not declared</span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {editing && (
        <EditAgentModal
          agent={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); fetchData() }}
        />
      )}
      {deleting && (
        <DeleteAgentDialog
          agent={deleting}
          callers={agents.filter(o => o.id !== deleting.id && o.calls?.some(c => c === deleting.id || c === deleting.name)).map(o => o.name)}
          onClose={() => setDeleting(null)}
          onDeleted={() => { setDeleting(null); fetchData() }}
        />
      )}
      {showOnboarding && (
        <OnboardingModal
          onClose={() => setShowOnboarding(false)}
          onSaved={() => { setShowOnboarding(false); fetchData() }}
        />
      )}
    </div>
  )
}
