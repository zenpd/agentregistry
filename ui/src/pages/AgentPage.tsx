import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  getAgent, getGraphV2, getReconstructedGraph, updateAgent,
  getAgentRisks, scanAgentRisks, getAgentEconomics,
  getAgentTokenSummary, getAgentTokenTrend, getAgentCost, getAgentCostForecast, getAgentBudget, getCostPerOutcome,
  type Agent, type GraphV2Response, type ReconstructedGraph, type RiskFinding, type AgentEconomics,
  type AgentTokenSummary, type TokenTrendPoint, type AgentCost, type CostForecast, type AgentBudgetStatus, type CostPerOutcome,
} from '../services/api'
import NetworkGraph from '../components/NetworkGraph'
import PhoenixProjectPicker from '../components/PhoenixProjectPicker'
import BarChart from '../components/BarChart'
import RiskPie from '../components/RiskPie'
import RiskHeatmap from '../components/RiskHeatmap'

const SEVERITY_PILL: Record<string, string> = {
  LOW: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  MEDIUM: 'bg-amber-50 text-amber-700 ring-amber-200',
  HIGH: 'bg-orange-50 text-orange-700 ring-orange-200',
  CRITICAL: 'bg-rose-50 text-rose-700 ring-rose-200',
}

const CATEGORY_LABELS: Record<string, string> = {
  SECURITY: 'Security',
  DATA_PRIVACY: 'Data Privacy',
  OPERATIONAL: 'Operational',
  FINANCIAL: 'Financial',
  COMPLIANCE: 'Compliance',
  REPUTATIONAL: 'Reputational',
}

const CATEGORY_COLORS: Record<string, string> = {
  SECURITY: '#e11d48',
  DATA_PRIVACY: '#8b5cf6',
  OPERATIONAL: '#f59e0b',
  FINANCIAL: '#3DDBD9',
  COMPLIANCE: '#6366f1',
  REPUTATIONAL: '#f472b6',
}

const SEVERITIES = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

const STAGE_PILL: Record<string, string> = {
  Ideation: 'status-pending',
  Development: 'status-active',
  Testing: 'status-review',
  Production: 'status-complete',
  Deprecated: 'status-failed',
}

function fmtCents(c: number): string {
  const n = c / 100
  if (Math.abs(n) >= 1000) return '$' + Math.round(n / 1000) + 'K'
  return '$' + n.toFixed(n % 1 === 0 ? 0 : 2)
}

function fmtDollars(n: number): string {
  if (Math.abs(n) >= 1000) return '$' + (n / 1000).toFixed(1) + 'K'
  return '$' + n.toFixed(2)
}

const TABS = ['overview', 'diagram', 'governance', 'tokenomics', 'revenue', 'risk'] as const
type Tab = typeof TABS[number]
const TAB_LABEL: Record<Tab, string> = {
  overview: 'Overview', diagram: 'Diagram', governance: 'Governance',
  tokenomics: 'Tokenomics', revenue: 'Revenue & Expenditure', risk: 'Risk',
}

// This entire page is scoped to one agent id (from the route) — every tab
// below fetches only this agent's data, never the portfolio-wide lists used
// by the Executive/Registry pages.
export default function AgentPage() {
  const { id } = useParams<{ id: string }>()
  const [agent, setAgent] = useState<Agent | null>(null)
  const [graph, setGraph] = useState<GraphV2Response | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('overview')

  useEffect(() => {
    if (!id) return
    setTab('overview')
    load(id)
  }, [id])

  async function load(agentId: string) {
    setLoading(true)
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
  }

  if (loading) return <div className="p-8 text-center text-gray-500">Loading…</div>
  if (error || !agent || !id) return (
    <div className="p-8 text-center text-rose-500">
      {error || 'Agent not found'} — <Link to="/agents" className="text-teal-600 underline">back to registry</Link>
    </div>
  )

  const deps = graph ? graph.edges.filter(e => e.from === id || e.to === id) : []

  return (
    <div className="space-y-4 animate-fade-in max-w-4xl">
      <Link to="/agents" className="text-sm text-gray-400 hover:text-gray-600">&larr; AI Registry</Link>

      <div className="card p-6">
        <div className="flex justify-between items-start mb-3">
          <div>
            <h1 className="text-xl font-bold text-gray-900">{agent.name}</h1>
            <p className="text-sm text-gray-500 mt-0.5">{agent.aiType} · {agent.dept || 'No department'}</p>
          </div>
          <span className={STAGE_PILL[agent.stage] || 'status-pending'}>{agent.stage}</span>
        </div>

        <div className="flex gap-1 border-b border-gray-100 mb-4 overflow-x-auto">
          {TABS.map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px whitespace-nowrap transition-colors ${
                tab === t ? 'border-teal-600 text-teal-700' : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {TAB_LABEL[t]}
            </button>
          ))}
        </div>

        {tab === 'overview' && <OverviewTab agent={agent} deps={deps} graph={graph} agentId={id} />}
        {tab === 'diagram' && <DiagramTab agent={agent} onLinked={() => load(id)} />}
        {tab === 'governance' && <GovernanceTab agent={agent} />}
        {tab === 'tokenomics' && <TokenomicsTab agentId={id} />}
        {tab === 'revenue' && <RevenueTab agentId={id} />}
        {tab === 'risk' && <RiskTab agentId={id} />}
      </div>
    </div>
  )
}

function OverviewTab({ agent, deps, graph, agentId }: { agent: Agent; deps: any[]; graph: GraphV2Response | null; agentId: string }) {
  return (
    <>
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <span className="text-xs text-gray-400">Owner</span>
          <p className="text-sm text-gray-900">{agent.owner || 'Unassigned'}</p>
        </div>
        <div>
          <span className="text-xs text-gray-400">Value</span>
          <p className="text-sm font-mono text-gray-900">${(agent.valueAmount / 1000).toFixed(0)}K/mo</p>
        </div>
        <div>
          <span className="text-xs text-gray-400">API Endpoint</span>
          <p className="text-sm font-mono text-gray-700 break-all">{agent.apiEndpoint || 'N/A'}</p>
        </div>
        <div>
          <span className="text-xs text-gray-400">Risk</span>
          <p className="text-sm text-gray-900">{agent.riskLevel || 'LOW'}</p>
        </div>
      </div>

      {agent.description && (
        <div className="mb-4">
          <span className="text-xs text-gray-400">Description</span>
          <p className="text-sm text-gray-700">{agent.description}</p>
        </div>
      )}

      {agent.businessOutcome && (
        <div className="mb-4">
          <span className="text-xs text-gray-400">Business Outcome</span>
          <p className="text-sm text-gray-700">{agent.businessOutcome}</p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 mb-4">
        {agent.enterpriseSystems && agent.enterpriseSystems.length > 0 && (
          <div>
            <span className="text-xs text-gray-400">Enterprise Systems</span>
            <div className="flex flex-wrap gap-1 mt-1">
              {agent.enterpriseSystems.map(s => (
                <span key={s} className="text-xs bg-teal-50 text-teal-700 ring-1 ring-teal-200 px-2 py-0.5 rounded-full">{s}</span>
              ))}
            </div>
          </div>
        )}
        {agent.databases && agent.databases.length > 0 && (
          <div>
            <span className="text-xs text-gray-400">Databases</span>
            <div className="flex flex-wrap gap-1 mt-1">
              {agent.databases.map(d => (
                <span key={d} className="text-xs bg-amber-50 text-amber-700 ring-1 ring-amber-200 px-2 py-0.5 rounded-full">{d}</span>
              ))}
            </div>
          </div>
        )}
        {agent.mcpServers && agent.mcpServers.length > 0 && (
          <div>
            <span className="text-xs text-gray-400">MCP Servers</span>
            <div className="flex flex-wrap gap-1 mt-1">
              {agent.mcpServers.map(m => (
                <span key={m} className="text-xs bg-purple-50 text-purple-700 ring-1 ring-purple-200 px-2 py-0.5 rounded-full">{m}</span>
              ))}
            </div>
          </div>
        )}
        {agent.knowledgeBases && agent.knowledgeBases.length > 0 && (
          <div>
            <span className="text-xs text-gray-400">Knowledge Bases</span>
            <div className="flex flex-wrap gap-1 mt-1">
              {agent.knowledgeBases.map(k => (
                <span key={k} className="text-xs bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 px-2 py-0.5 rounded-full">{k}</span>
              ))}
            </div>
          </div>
        )}
      </div>

      {deps.length > 0 && (
        <div className="mb-4">
          <span className="text-xs text-gray-400">Dependencies</span>
          <div className="mt-2 space-y-1">
            {deps.map((e, i) => {
              const otherId = e.from === agentId ? e.to : e.from
              const otherName = graph?.nodes.find(n => n.id === otherId)?.name ?? otherId
              const typeLabel = e.type === 'CALLS' ? 'calls' : e.type === 'CONSUMED_BY' ? 'feeds' : e.type === 'ACCESSES' ? 'accesses' : e.type === 'USES_KB' ? 'knowledge' : 'tool'
              const direction = e.from === agentId ? typeLabel : 'needed by'
              return (
                <div key={i} className="text-xs flex gap-2">
                  <span className="text-gray-400">{direction}</span>
                  <span className="font-mono text-teal-600">{otherName}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {agent.contextMd && (
        <div>
          <span className="text-xs text-gray-400">Context notes</span>
          <pre className="mt-1 text-xs text-gray-700 whitespace-pre-wrap bg-gray-50 rounded-lg p-3 border border-gray-100 font-mono">{agent.contextMd}</pre>
        </div>
      )}
    </>
  )
}

// Reconstructed from real Phoenix traces, not the agent's hand-declared
// calls/consumers fields (that's the Overview tab / the separate /graph
// endpoint). Four distinct states, never collapsed into one generic "no
// data": not linked to a project, Phoenix unreachable, linked but zero
// traces seen yet, and a real reconstructed diagram.
function DiagramTab({ agent, onLinked }: { agent: Agent; onLinked: () => void }) {
  const [graph, setGraph] = useState<ReconstructedGraph | null>(null)
  const [loading, setLoading] = useState(true)
  const [linkValue, setLinkValue] = useState('')
  const [linking, setLinking] = useState(false)

  async function load() {
    setLoading(true)
    try {
      const resp = await getReconstructedGraph(agent.id)
      setGraph(resp.data)
    } catch (e: any) {
      setGraph({ status: 'phoenix_unreachable', project: agent.phoenixProject ?? null, reason: e.message, spanCount: 0, traceCount: 0, nodes: [], edges: [] })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [agent.id])

  async function linkProject() {
    if (!linkValue.trim()) return
    setLinking(true)
    try {
      await updateAgent(agent.id, { phoenixProject: linkValue.trim() } as any)
      onLinked()
      await load()
    } finally {
      setLinking(false)
    }
  }

  if (loading) return <div className="py-10 text-center text-sm text-gray-400">Reconstructing from traces…</div>
  if (!graph) return null

  if (graph.status === 'not_linked') {
    return (
      <div className="py-4">
        <p className="text-sm text-gray-500 mb-3">This agent isn't linked to a Phoenix project yet — link one to reconstruct its real dependency diagram from actual traces.</p>
        <div className="flex gap-2 items-start">
          <div className="flex-1">
            <PhoenixProjectPicker id="link-phoenix-projects" value={linkValue} onChange={setLinkValue} />
          </div>
          <button onClick={linkProject} disabled={linking || !linkValue.trim()} className="btn-primary btn-sm whitespace-nowrap">
            {linking ? 'Linking…' : 'Link'}
          </button>
        </div>
      </div>
    )
  }

  if (graph.status === 'phoenix_unreachable') {
    return (
      <div className="py-6 text-center">
        <p className="text-sm text-gray-500">Linked to <span className="font-mono text-gray-700">{graph.project}</span>, but Phoenix couldn't be reached.</p>
        {graph.reason && <p className="text-xs text-gray-400 mt-1 break-all">{graph.reason}</p>}
        <button onClick={load} className="btn-secondary btn-sm mt-3">Retry</button>
      </div>
    )
  }

  if (graph.status === 'no_traces_yet') {
    return (
      <div className="py-6 text-center">
        <p className="text-sm text-gray-500">Linked to <span className="font-mono text-gray-700">{graph.project}</span> — no traces seen yet.</p>
        <p className="text-xs text-gray-400 mt-1">Once this app runs and exports real traces, its diagram reconstructs here automatically.</p>
        <button onClick={load} className="btn-secondary btn-sm mt-3">Refresh</button>
      </div>
    )
  }

  const nwNodes = graph.nodes.map(n => ({ id: n.id, name: n.name, type: n.kind }))
  const nwEdges = graph.edges.map(e => ({ from: e.from, to: e.to }))
  const errorNodes = graph.nodes.filter(n => n.errorCount > 0)

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs text-gray-500">
          Reconstructed from <b className="text-gray-700">{graph.spanCount}</b> span(s) across <b className="text-gray-700">{graph.traceCount}</b> trace(s) —
          project <span className="font-mono">{graph.project}</span>
        </p>
        <button onClick={load} className="text-xs text-teal-600 hover:text-teal-700">↻ Refresh</button>
      </div>
      <div className="rounded-xl border border-gray-100 bg-gray-900/95 overflow-hidden flex justify-center">
        <NetworkGraph nodes={nwNodes} edges={nwEdges} width={720} height={420} />
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {graph.nodes.map(n => (
          <span key={n.id} className={`text-xs px-2 py-0.5 rounded-full ring-1 ${n.errorCount > 0 ? 'bg-rose-50 text-rose-700 ring-rose-200' : 'bg-gray-50 text-gray-600 ring-gray-200'}`}>
            {n.name} <span className="text-gray-400">· {n.kind} · ×{n.count}</span>{n.avgLatencyMs != null ? ` · ${Math.round(n.avgLatencyMs)}ms` : ''}
          </span>
        ))}
      </div>
      {errorNodes.length > 0 && (
        <p className="text-xs text-rose-600 mt-2">{errorNodes.length} step(s) recorded at least one error in this sample.</p>
      )}
    </div>
  )
}

// Governance gate status for this one agent — arb/security/dp review state.
function GovernanceTab({ agent }: { agent: Agent }) {
  const gates = agent.reviews ? Object.entries(agent.reviews) : []
  if (gates.length === 0) return <p className="text-sm text-gray-400 py-4">No governance gates recorded for this agent.</p>
  return (
    <div className="space-y-2">
      {gates.map(([gate, status]) => (
        <div key={gate} className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2">
          <span className="text-sm text-gray-700 uppercase tracking-wide font-medium">{gate}</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-white ring-1 ring-gray-200 text-gray-600">{status}</span>
        </div>
      ))}
    </div>
  )
}

// Token usage, real model cost, forecast and budget for this one agent — the
// mechanics that make up the "expenditure" side of the Revenue tab. Reads
// live from agent_token_usage / model_token_prices / agent_budgets, never a
// placeholder number.
function TokenomicsTab({ agentId }: { agentId: string }) {
  const [summary, setSummary] = useState<AgentTokenSummary | null>(null)
  const [trend, setTrend] = useState<TokenTrendPoint[] | null>(null)
  const [cost, setCost] = useState<AgentCost | null>(null)
  const [forecast, setForecast] = useState<CostForecast | null>(null)
  const [budget, setBudget] = useState<AgentBudgetStatus | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      getAgentTokenSummary(agentId).catch(() => null),
      getAgentTokenTrend(agentId, 30).catch(() => null),
      getAgentCost(agentId).catch(() => null),
      getAgentCostForecast(agentId, 3).catch(() => null),
      getAgentBudget(agentId).catch(() => null),
    ]).then(([s, t, c, f, b]) => {
      setSummary(s?.data ?? null)
      setTrend(t?.data.trend ?? null)
      setCost(c?.data ?? null)
      setForecast(f?.data ?? null)
      setBudget(b?.data ?? null)
      setLoading(false)
    })
  }, [agentId])

  if (loading) return <div className="py-10 text-center text-sm text-gray-400">Loading tokenomics…</div>

  const hasUsage = summary && summary.invocations > 0

  return (
    <div className="space-y-5">
      <div>
        <span className="text-xs text-gray-400">Token usage (all time)</span>
        {!hasUsage ? (
          <p className="text-sm text-gray-400 mt-1">No token usage recorded yet for this agent.</p>
        ) : (
          <div className="grid grid-cols-4 gap-3 mt-1">
            <MiniStat label="Input tokens" value={summary!.inputTokens.toLocaleString()} />
            <MiniStat label="Output tokens" value={summary!.outputTokens.toLocaleString()} />
            <MiniStat label="Cached tokens" value={summary!.cachedTokens.toLocaleString()} />
            <MiniStat label="Invocations" value={summary!.invocations.toLocaleString()} />
          </div>
        )}
      </div>

      {hasUsage && (
        <div className="grid grid-cols-3 gap-3">
          <MiniStat label="Total token cost" value={fmtCents(summary!.costCents)} accent="text-rose-600" />
          <MiniStat label="Cost / invocation" value={'$' + summary!.costPerInvocation.toFixed(4)} accent="text-rose-600" />
          <MiniStat label="Modeled monthly cost" value={cost ? fmtDollars(cost.monthlyCost) : '—'} accent="text-rose-600" />
        </div>
      )}

      {trend && trend.length > 0 && (
        <div>
          <span className="text-xs text-gray-400">Daily invocations (last 30 days)</span>
          <div className="mt-2">
            <BarChart data={trend.slice(-10).map(t => ({ label: t.date, value: t.invocations }))} width={520} />
          </div>
        </div>
      )}

      {forecast && (
        <div>
          <span className="text-xs text-gray-400">Cost forecast (5% monthly growth assumption)</span>
          <div className="flex gap-3 mt-2">
            {forecast.forecast.map(f => (
              <div key={f.month} className="flex-1 text-center rounded-lg bg-gray-50 py-2">
                <div className="text-sm font-bold text-gray-900">{fmtDollars(f.projectedCost)}</div>
                <div className="text-[10px] text-gray-400 uppercase">Month +{f.month}</div>
              </div>
            ))}
          </div>
          <p className="text-[11px] text-gray-400 mt-1">Current monthly avg {fmtDollars(forecast.currentMonthlyAvg)} · projected total {fmtDollars(forecast.totalProjected)}</p>
        </div>
      )}

      {budget && budget.monthlyBudget > 0 && (
        <div>
          <span className="text-xs text-gray-400">Budget</span>
          <div className="mt-1 h-2.5 rounded-full bg-gray-100 overflow-hidden">
            <div
              className={`h-full ${budget.budgetUsagePct >= 100 ? 'bg-rose-500' : budget.budgetUsagePct >= 80 ? 'bg-amber-500' : 'bg-emerald-500'}`}
              style={{ width: `${Math.min(100, budget.budgetUsagePct)}%` }}
            />
          </div>
          <p className="text-xs text-gray-500 mt-1">
            {fmtDollars(budget.currentSpend)} of {fmtDollars(budget.monthlyBudget)} spent ({budget.budgetUsagePct.toFixed(1)}%) — {fmtDollars(budget.remaining)} remaining
          </p>
        </div>
      )}
      {budget && budget.monthlyBudget === 0 && (
        <p className="text-xs text-gray-400">No monthly budget set for this agent.</p>
      )}
    </div>
  )
}

function MiniStat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="text-center rounded-lg bg-gray-50 py-2 px-1">
      <div className={`text-sm font-bold ${accent || 'text-gray-900'}`}>{value}</div>
      <div className="text-[10px] text-gray-400 uppercase">{label}</div>
    </div>
  )
}

// Revenue vs expenditure detail for this one agent — same categories as the
// Executive dashboard's portfolio roll-up (declared value vs measured token
// cost + estimated infra cost), plus cost-per-business-outcome efficiency.
function RevenueTab({ agentId }: { agentId: string }) {
  const [econ, setEcon] = useState<AgentEconomics | null>(null)
  const [outcome, setOutcome] = useState<CostPerOutcome | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      getAgentEconomics(agentId).catch(() => null),
      getCostPerOutcome(agentId).catch(() => null),
    ]).then(([e, o]) => {
      setEcon(e?.data ?? null)
      setOutcome(o?.data ?? null)
      setLoading(false)
    })
  }, [agentId])

  if (loading) return <div className="py-10 text-center text-sm text-gray-400">Loading economics…</div>
  if (!econ) return <p className="text-sm text-gray-400 py-4">Economics unavailable for this agent.</p>

  const total = Math.max(econ.revenueCents, econ.expenditureCents, 1)

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-3 gap-3">
        <MiniStat label="Revenue" value={fmtCents(econ.revenueCents)} accent="text-emerald-600" />
        <MiniStat label="Expenditure" value={fmtCents(econ.expenditureCents)} accent="text-rose-600" />
        <MiniStat label="Net" value={fmtCents(econ.netCents)} accent={econ.netCents >= 0 ? 'text-emerald-600' : 'text-rose-600'} />
      </div>

      <div>
        <span className="text-xs text-gray-400">Expenditure breakdown</span>
        <div className="h-3 rounded-full bg-gray-100 overflow-hidden flex mt-1">
          <div className="h-full bg-rose-400" style={{ width: `${(econ.tokenCostCents / total) * 100}%` }} title="Token cost" />
          <div className="h-full bg-orange-300" style={{ width: `${(econ.estimatedInfraCostCents / total) * 100}%` }} title="Estimated infra" />
        </div>
        <div className="flex justify-between text-xs text-gray-500 mt-1">
          <span>Token cost: {fmtCents(econ.tokenCostCents)} (measured)</span>
          <span>Estimated infra ({econ.stage}): {fmtCents(econ.estimatedInfraCostCents)}</span>
        </div>
      </div>

      <div>
        <span className="text-xs text-gray-400">Revenue vs expenditure</span>
        <div className="h-3 rounded-full bg-gray-100 overflow-hidden flex mt-1">
          <div className="h-full bg-emerald-400" style={{ width: `${(econ.revenueCents / total) * 100}%` }} />
        </div>
        <p className="text-xs text-gray-400 mt-1">
          {econ.expenditureCents > 0 ? `${((econ.expenditureCents / Math.max(econ.revenueCents, 1)) * 100).toFixed(2)}% of revenue spent on cost` : 'No measured expenditure yet'}
        </p>
      </div>

      {outcome && outcome.business_outcome > 0 && (
        <div>
          <span className="text-xs text-gray-400">Cost-per-business-outcome efficiency</span>
          <div className="grid grid-cols-3 gap-3 mt-1">
            <MiniStat label="Total cost" value={fmtDollars(outcome.total_cost)} accent="text-rose-600" />
            <MiniStat label="Business outcome ($)" value={fmtDollars(outcome.business_outcome)} accent="text-emerald-600" />
            <MiniStat label="Cost / outcome" value={outcome.cost_per_outcome.toFixed(3)} />
          </div>
          <p className="text-xs text-gray-500 mt-1">Efficiency rating: <span className="font-medium text-gray-700">{outcome.efficiency_rating}</span></p>
        </div>
      )}
    </div>
  )
}

// Risk findings for this one agent, broken down as a pie + heatmap using the
// same 6-category / 4-severity taxonomy as the Executive dashboard's
// portfolio-wide view — just filtered down to a single agent's findings.
function RiskTab({ agentId }: { agentId: string }) {
  const [findings, setFindings] = useState<RiskFinding[] | null>(null)
  const [scanning, setScanning] = useState(false)

  async function load() {
    const res = await getAgentRisks(agentId).catch(() => null)
    setFindings(res?.data.findings ?? [])
  }

  useEffect(() => { load() }, [agentId])

  async function scan() {
    setScanning(true)
    try {
      await scanAgentRisks(agentId)
      await load()
    } finally {
      setScanning(false)
    }
  }

  if (findings === null) return <div className="py-10 text-center text-sm text-gray-400">Loading risk findings…</div>

  const byCategory = Object.entries(
    findings.reduce((acc, f) => { acc[f.category] = (acc[f.category] || 0) + 1; return acc }, {} as Record<string, number>)
  ).map(([category, count]) => ({ label: CATEGORY_LABELS[category] || category, count, color: CATEGORY_COLORS[category] || '#6b7280' }))

  const categories = Object.keys(CATEGORY_LABELS)
  const heatmapRows = categories
    .map(category => {
      const counts: Record<string, number> = {}
      for (const s of SEVERITIES) counts[s] = findings.filter(f => f.category === category && f.severity === s).length
      return { category, label: CATEGORY_LABELS[category], counts }
    })
    .filter(row => Object.values(row.counts).some(c => c > 0))

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-400">{findings.length} open finding(s)</span>
        <button onClick={scan} disabled={scanning} className="text-xs text-teal-600 hover:text-teal-700 disabled:opacity-50">
          {scanning ? 'Scanning…' : '🔍 Scan now'}
        </button>
      </div>

      {findings.length === 0 ? (
        <p className="text-sm text-gray-400">No open findings for this agent.</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <span className="text-xs text-gray-400 mb-2 block">By category</span>
              <RiskPie data={byCategory} size={160} />
            </div>
            <div>
              <span className="text-xs text-gray-400 mb-2 block">Category × severity</span>
              <RiskHeatmap rows={heatmapRows} severities={SEVERITIES} />
            </div>
          </div>

          <div>
            <span className="text-xs text-gray-400">Findings</span>
            <div className="mt-1 space-y-1">
              {findings.map((f, i) => (
                <div key={f.id || i} className="flex items-start gap-2 text-xs">
                  <span className={`px-1.5 py-0.5 rounded-full ring-1 flex-shrink-0 ${SEVERITY_PILL[f.severity] || 'bg-gray-50 text-gray-600 ring-gray-200'}`}>{f.severity}</span>
                  <div>
                    <span className="text-gray-700 font-medium">{f.title}</span>
                    <span className="text-gray-400"> · {CATEGORY_LABELS[f.category] || f.category}</span>
                    {f.description && <p className="text-gray-500">{f.description}</p>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
