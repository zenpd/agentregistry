import { useState, useEffect, useCallback } from 'react'
import { useParams, useSearchParams, Link } from 'react-router-dom'
import { AlertTriangle, Bot, Building2, Coins, LayoutDashboard, Plug, ShieldCheck, Tag, TrendingUp, User, Waypoints } from 'lucide-react'
import { getAgent, getGraphV2, type Agent, type GraphV2Response } from '../services/api'
import InfoTip from '../components/InfoTip'
import TabInsights from '../components/TabInsights'
import { STAGE_PILL, TypeBadge } from './agent/shared'
import OverviewTab from './agent/OverviewTab'
import DiagramTab from './agent/DiagramTab'
import GovernanceTab from './agent/GovernanceTab'
import TokenomicsTab from './agent/TokenomicsTab'
import RevenueTab from './agent/RevenueTab'
import RiskTab from './agent/RiskTab'
import IntegrateTab from './agent/IntegrateTab'

const TABS = ['overview', 'diagram', 'governance', 'tokenomics', 'revenue', 'risk', 'integrate'] as const
type Tab = typeof TABS[number]
const TAB_ICON: Record<Tab, typeof Bot> = {
  overview: LayoutDashboard, diagram: Waypoints, governance: ShieldCheck,
  tokenomics: Coins, revenue: TrendingUp, risk: AlertTriangle, integrate: Plug,
}
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
  // Goes up when the registry has updated the record or its figures, so the open tab reloads them in place.
  const [dataVersion, setDataVersion] = useState(0)

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
      // A background reload that fails leaves the page as it is, with whatever a person has open.
      if (!quiet) setError(e.response?.data?.detail || e.message || 'Agent not found')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (id) load(id)
  }, [id, load])

  if (loading) return <div className="p-8 text-center text-slate-600">Loading…</div>
  if (error || !agent || !id) return (
    <div className="p-8 text-center text-rose-500">
      {error || 'Agent not found'} — <Link to="/agents" className="text-zen-600 underline">back to registry</Link>
    </div>
  )

  const onChanged = () => load(id, true)
  const tabProps = { agent, agentId: id, onChanged, dataVersion }
  const recordChanged = () => { load(id, true); setDataVersion(v => v + 1) }

  return (
    <div className="space-y-4 animate-fade-in max-w-5xl">
      <Link to="/agents" className="text-sm text-slate-500 hover:text-slate-700">&larr; AI Registry</Link>

      <div className="card p-0 overflow-hidden">
        <header className="px-6 pt-5 pb-4 bg-gradient-to-r from-zen-50 via-white to-white border-b border-slate-100">
          <div className="flex items-start gap-4">
            <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-gradient-zen text-white shadow-glow-zen">
              <Bot size={24} />
            </div>
            <div className="flex-1 min-w-0">
              <h1 className="text-2xl font-extrabold text-slate-900 leading-tight">{agent.name}</h1>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <TypeBadge type={agent.aiType} />
                <MetaChip icon={<Building2 size={12} />}>{agent.deptName || agent.dept || 'No department'}</MetaChip>
                {agent.owner && agent.owner !== 'Unassigned'
                  ? <MetaChip icon={<User size={12} />}>{agent.owner}</MetaChip>
                  : <MetaChip icon={<User size={12} />} warn>No owner</MetaChip>}
                {agent.version && <MetaChip icon={<Tag size={12} />}>{agent.version}</MetaChip>}
                {agent.sourceRepo && (
                  <a href={agent.sourceRepo} target="_blank" rel="noreferrer" className="rounded-full bg-slate-50 px-2.5 py-0.5 text-[12px] font-semibold text-slate-700 ring-1 ring-slate-200 hover:text-zen-700" data-testid="repo-chip">Code repository</a>
                )}
                {agent.cloudResourceId && (
                  <span className="rounded-full bg-slate-50 px-2.5 py-0.5 text-[12px] font-semibold text-slate-700 ring-1 ring-slate-200" title={agent.cloudResourceId}>Azure resource linked</span>
                )}
                {agent.traceConnectorId && (
                  <span className="rounded-full bg-teal-50 px-2.5 py-0.5 text-[12px] font-semibold text-teal-700 ring-1 ring-teal-200">Traces in Langfuse</span>
                )}
                {(agent.sharedProject?.length ?? 0) > 0 && (
                  <span className="rounded-full bg-amber-50 px-2.5 py-0.5 text-[12px] font-semibold text-amber-800 ring-1 ring-amber-300" data-testid="shared-project-badge"
                    title="Another record is linked to the same Phoenix project. Usually the same app registered twice: keep one, or split the project from the wrong record on the Discovered page.">
                    Same Phoenix project as {agent.sharedProject!.map(o => o.name).join(', ')}
                  </span>
                )}
                {agent.isDemo && (
                  <span className="rounded-full bg-amber-50 px-2.5 py-0.5 text-[12px] font-semibold text-amber-800 ring-1 ring-amber-300" data-testid="demo-badge"
                    title="A seeded example agent. Its numbers are demo data. Settings → Demo agents hides the demo agents from every page.">Demo agent</span>
                )}
                {agent.archivedAt && (
                  <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[12px] font-semibold text-slate-700 ring-1 ring-slate-300" data-testid="archived-badge"
                    title="Left out of every page, count and job, but kept in the database. Settings → Demo agents brings it back.">Archived</span>
                )}
              </div>
            </div>
            <span className="inline-flex items-center gap-1">
              <span className={`${STAGE_PILL[agent.stage] || 'status-pending'} !text-[13px] !px-3 !py-1`}>{agent.stage}</span>
              <InfoTip term="stage" />
            </span>
          </div>

          <div className="mt-4 flex gap-1 overflow-x-auto rounded-xl bg-slate-100/80 p-1" role="tablist">
            {TABS.map(t => {
              const Icon = TAB_ICON[t]
              return (
                <button
                  key={t}
                  role="tab"
                  aria-selected={tab === t}
                  data-tab={t}
                  onClick={() => setTab(t)}
                  className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm whitespace-nowrap transition-colors ${
                    tab === t
                      ? 'bg-white font-semibold text-zen-700 shadow-sm ring-1 ring-slate-200'
                      : 'font-medium text-slate-700 hover:bg-white/60 hover:text-slate-900'
                  }`}
                >
                  <Icon size={15} className={tab === t ? 'text-zen-600' : 'text-slate-500'} />
                  {TAB_LABEL[t]}
                </button>
              )
            })}
          </div>
        </header>

        <div className="p-6">
        {tab === 'overview' && <OverviewTab {...tabProps} graph={graph} />}
        {tab === 'diagram' && <DiagramTab {...tabProps} />}
        {tab === 'governance' && <GovernanceTab {...tabProps} />}
        {tab === 'tokenomics' && <TokenomicsTab {...tabProps} />}
        {tab === 'revenue' && <RevenueTab {...tabProps} />}
        {tab === 'risk' && <RiskTab {...tabProps} />}
        {tab === 'integrate' && <IntegrateTab {...tabProps} />}
        <TabInsights key={`${id}:${tab}`} agentId={id} tab={tab} onRecordChanged={recordChanged} />
        </div>
      </div>
    </div>
  )
}

function MetaChip({ icon, warn, children }: { icon: React.ReactNode; warn?: boolean; children: React.ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs whitespace-nowrap ${
      warn ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-slate-200 bg-white text-slate-700'
    }`}>
      <span className={warn ? 'text-amber-500' : 'text-slate-500'}>{icon}</span>
      {children}
    </span>
  )
}
