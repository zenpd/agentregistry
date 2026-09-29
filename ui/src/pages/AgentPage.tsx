import { useState, useEffect, useCallback } from 'react'
import { useParams, useSearchParams, Link } from 'react-router-dom'
import { getAgent, getGraphV2, type Agent, type GraphV2Response } from '../services/api'
import { STAGE_PILL } from './agent/shared'
import OverviewTab from './agent/OverviewTab'
import DiagramTab from './agent/DiagramTab'
import GovernanceTab from './agent/GovernanceTab'
import TokenomicsTab from './agent/TokenomicsTab'
import RevenueTab from './agent/RevenueTab'
import RiskTab from './agent/RiskTab'
import IntegrateTab from './agent/IntegrateTab'

const TABS = ['overview', 'diagram', 'governance', 'tokenomics', 'revenue', 'risk', 'integrate'] as const
type Tab = typeof TABS[number]
const TAB_LABEL: Record<Tab, string> = {
  overview: 'Overview', diagram: 'Diagram', governance: 'Governance',
  tokenomics: 'Tokenomics', revenue: 'Revenue & Expenditure', risk: 'Risk', integrate: 'Integrate',
}

// Every tab is scoped to the agent id in the route.
export default function AgentPage() {
  const { id } = useParams<{ id: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const [agent, setAgent] = useState<Agent | null>(null)
  const [graph, setGraph] = useState<GraphV2Response | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const requested = searchParams.get('tab') as Tab | null
  const tab: Tab = requested && (TABS as readonly string[]).includes(requested) ? requested : 'overview'
  const setTab = (t: Tab) => setSearchParams(t === 'overview' ? {} : { tab: t }, { replace: true })

  const load = useCallback(async (agentId: string, quiet = false) => {
    if (!quiet) setLoading(true)
    try {
      const [agentRes, graphRes] = await Promise.all([getAgent(agentId), getGraphV2()])
      setAgent(agentRes.data)
      setGraph(graphRes.data)
      setError(null)
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Agent not found')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (id) load(id)
  }, [id, load])

  if (loading) return <div className="p-8 text-center text-gray-500">Loading…</div>
  if (error || !agent || !id) return (
    <div className="p-8 text-center text-rose-500">
      {error || 'Agent not found'} — <Link to="/agents" className="text-teal-600 underline">back to registry</Link>
    </div>
  )

  const onChanged = () => load(id, true)
  const tabProps = { agent, agentId: id, onChanged }

  return (
    <div className="space-y-4 animate-fade-in max-w-5xl">
      <Link to="/agents" className="text-sm text-gray-400 hover:text-gray-600">&larr; AI Registry</Link>

      <div className="card p-6">
        <div className="flex justify-between items-start mb-3">
          <div>
            <h1 className="text-xl font-bold text-gray-900">{agent.name}</h1>
            <p className="text-sm text-gray-500 mt-0.5">{agent.aiType} · {agent.deptName || agent.dept || 'No department'} · {agent.owner || 'No owner'}</p>
          </div>
          <span className={STAGE_PILL[agent.stage] || 'status-pending'}>{agent.stage}</span>
        </div>

        <div className="flex gap-1 border-b border-gray-100 mb-4 overflow-x-auto" role="tablist">
          {TABS.map(t => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              data-tab={t}
              onClick={() => setTab(t)}
              className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px whitespace-nowrap transition-colors ${
                tab === t ? 'border-teal-600 text-teal-700' : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {TAB_LABEL[t]}
            </button>
          ))}
        </div>

        {tab === 'overview' && <OverviewTab {...tabProps} graph={graph} />}
        {tab === 'diagram' && <DiagramTab {...tabProps} />}
        {tab === 'governance' && <GovernanceTab {...tabProps} />}
        {tab === 'tokenomics' && <TokenomicsTab {...tabProps} />}
        {tab === 'revenue' && <RevenueTab {...tabProps} />}
        {tab === 'risk' && <RiskTab {...tabProps} />}
        {tab === 'integrate' && <IntegrateTab {...tabProps} />}
      </div>
    </div>
  )
}
