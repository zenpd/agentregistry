import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { getAgents, getConcentrationRisk, getGraphV2, type Agent } from '../services/api'
import InfoTip from '../components/InfoTip'
import type { GlossaryKey } from '../lib/glossary'
import type { TraceNode, TraceEdge } from '../components/TraceNetworkGraph'

export default function PlatformView() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [concentrationRisk, setConcentrationRisk] = useState<{ name: string; count: number }[]>([])
  const [graph, setGraph] = useState<{ nodes: TraceNode[]; edges: TraceEdge[] } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { fetchData() }, [])

  async function fetchData() {
    try {
      setLoading(true)
      const [agentsRes, riskRes, graphRes] = await Promise.all([
        getAgents(1, 100),
        getConcentrationRisk(),
        getGraphV2(),
      ])
      setAgents(agentsRes.data.data)
      setConcentrationRisk(riskRes.data)
      // Agent-to-agent handoffs only (the CALLS edge type) — the systems,
      // databases, knowledge bases and MCP servers each agent uses are
      // already covered by the cards and matrix below, and by /dependencies.
      // The old build here read the legacy /graph/ endpoint, which never
      // walked agent.calls at all, so every row it drew mislabeled a
      // system/database/MCP server as an agent "receiving a handoff."
      const v2 = graphRes.data
      const agentNodes = v2.nodes.filter(n => n.kind.startsWith('group:'))
      const callEdges = v2.edges.filter(e => e.type === 'CALLS')
      // A CALLS edge can target an agent id that isn't registered — someone
      // typed a name into another agent's "calls" field that doesn't match
      // any real agent — which the graph builder represents as an
      // `external` node. Carry those along too so the table/graph show that
      // agent's actual name instead of falling back to its raw "ext:…" id.
      const calledIds = new Set(callEdges.map(e => e.to))
      const externalNodes = v2.nodes.filter(n => n.kind === 'external' && calledIds.has(n.id))
      setGraph({
        // count/errorCount are uniform (1/0): this is the declared "calls"
        // relationship, not a traced call volume, so there is no real
        // busier-vs-quieter signal to size nodes by — every agent is drawn
        // the same size rather than implying a distinction that isn't there.
        nodes: [
          ...agentNodes.map(n => ({ id: n.id, name: n.name, kind: 'agent', count: 1, errorCount: 0 })),
          ...externalNodes.map(n => ({ id: n.id, name: n.name, kind: 'external', count: 1, errorCount: 0 })),
        ],
        edges: callEdges.map(e => ({ from: e.from, to: e.to, kind: 'calls' as const })),
      })
      setError(null)
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Failed to fetch')
    } finally {
      setLoading(false)
    }
  }

  const maxConcentration = Math.max(1, ...concentrationRisk.map(r => r.count))

  // Aggregate systems, databases, MCP servers, knowledge bases
  const systems: Record<string, number> = {}
  const databases: Record<string, number> = {}
  const mcpServers: Record<string, number> = {}
  const knowledgeBases: Record<string, number> = {}

  agents.forEach(a => {
    ;(a.enterpriseSystems || []).forEach(s => { systems[s] = (systems[s] || 0) + 1 })
    ;(a.databases || []).forEach(d => { databases[d] = (databases[d] || 0) + 1 })
    ;(a.mcpServers || []).forEach(m => { mcpServers[m] = (mcpServers[m] || 0) + 1 })
    ;(a.knowledgeBases || []).forEach(k => { knowledgeBases[k] = (knowledgeBases[k] || 0) + 1 })
  })

  if (loading) return <div className="p-8 text-center text-slate-600">Loading...</div>
  if (error) return <div className="p-8 text-center text-red-500">Error: {error}</div>

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold gradient-text">Platform</h1>
        <p className="text-slate-600 mt-0.5">Every system, database, MCP server and knowledge base the AI fleet uses, and where dependency is concentrated.</p>
      </div>

      {/* Mini Cards Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MiniCard title="Enterprise Systems" items={systems} color="#3DDBD9" />
        <MiniCard title="Databases" items={databases} color="#8C7CF0" />
        <MiniCard title="MCP Servers" tip="mcp_servers" items={mcpServers} color="#F0A85A" />
        <MiniCard title="Knowledge Bases" items={knowledgeBases} color="#57C785" />
      </div>

      {/* Concentration Risk */}
      {concentrationRisk.length > 0 && (
        <div className="card p-4">
          <h2 className="font-semibold mb-3">Concentration Risk <InfoTip term="concentration_risk" /></h2>
          <p className="text-xs text-slate-500 mb-3">
            Systems, databases, knowledge bases and MCP servers shared by 3 or more agents — bar length is relative
            to the most-shared resource below, not an absolute scale.
          </p>
          <div className="space-y-2">
            {concentrationRisk.map(risk => (
              <div key={risk.name} className="flex items-center gap-3">
                <div className="flex-1">
                  <div className="text-sm font-medium">{risk.name}</div>
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className="bg-red-500 h-2 rounded-full"
                      style={{ width: `${Math.max(15, Math.round((risk.count / maxConcentration) * 100))}%` }}
                    />
                  </div>
                </div>
                <span className="text-sm text-slate-600">{risk.count} agents</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Agent → system matrix */}
      {graph && graph.nodes.length > 0 && (
        <div className="card p-4">
          {/* Initiative -> Integration Matrix */}
          <div>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-semibold">Which systems and databases each agent uses <InfoTip term="dependency_graph" /></h2>
              {/* The agent-to-agent call graph lives on one page only. */}
              <Link to="/dependencies" className="text-[13px] font-semibold text-zen-700 hover:underline" data-testid="to-dependencies">Which agents call which: open Dependencies</Link>
            </div>
            {(() => {
              const cols = [
                ...Object.keys(systems).sort((a, b) => systems[b] - systems[a]).map(name => ({ name, kind: 'system' as const })),
                ...Object.keys(databases).sort((a, b) => databases[b] - databases[a]).map(name => ({ name, kind: 'database' as const })),
              ]
              const uses = (a: Agent, c: { name: string; kind: 'system' | 'database' }) =>
                (c.kind === 'system' ? a.enterpriseSystems : a.databases)?.includes(c.name)
              const rows = agents.filter(a => cols.some(c => uses(a, c)))
              const left = agents.length - rows.length
              return (
                <>
                  <p className="text-xs text-slate-500 mb-2">
                    Which enterprise systems (teal) and databases (violet) each agent integrates with.
                    {left > 0 && ` ${left} agent${left === 1 ? '' : 's'} with no system or database integration ${left === 1 ? 'is' : 'are'} not listed.`}
                  </p>
                  <div className="overflow-x-auto">
                    <table className="text-xs border-collapse">
                      <thead>
                        <tr>
                          <th className="border p-1.5 bg-gray-50 text-left align-bottom">Agent</th>
                          {cols.map(c => (
                            <th key={c.kind + c.name} className="border p-1.5 bg-gray-50 text-center align-bottom font-medium text-slate-700 min-w-[64px] max-w-[88px] leading-tight"
                              style={{ borderTop: `3px solid ${c.kind === 'system' ? '#3DDBD9' : '#8C7CF0'}` }}>
                              {c.name}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map(a => (
                          <tr key={a.id}>
                            <td className="border p-1.5 font-medium whitespace-nowrap">{a.name}</td>
                            {cols.map(c => (
                              <td key={c.kind + c.name} className="border p-1 text-center">
                                {uses(a, c)
                                  ? <span style={{ color: c.kind === 'system' ? '#0e9f9d' : '#6d5ce0' }} title={`${a.name} uses ${c.name}`}>●</span>
                                  : <span className="text-slate-400">—</span>}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )
            })()}
          </div>
        </div>
      )}
    </div>
  )
}

function MiniCard({ title, items, color, tip }: { title: string; items: Record<string, number>; color: string; tip?: GlossaryKey }) {
  const sorted = Object.entries(items).sort((a, b) => b[1] - a[1])
  return (
    <div className="card p-4">
      <div className="flex items-center gap-2">
        <div className="w-3 h-3 rounded-full" style={{ backgroundColor: color }} />
        <h3 className="font-semibold text-sm">{title}</h3>
        {tip && <InfoTip term={tip} />}
      </div>
      <div className="mt-1 mb-2 flex justify-between text-[12px] text-slate-500">
        <span>{sorted.length} in use</span>
        <span>agents using it</span>
      </div>
      {/* Six 20px rows plus gaps, so the scroll edge never cuts a row in half. */}
      <div className="space-y-1 max-h-[140px] overflow-y-auto pr-1">
        {sorted.map(([name, count]) => (
          <div key={name} className="flex justify-between gap-2 text-xs leading-5">
            <span className="truncate" title={name}>{name}</span>
            <span className="text-slate-600 tabular-nums">{count}</span>
          </div>
        ))}
      </div>
      {sorted.length > 6 && <div className="mt-1 text-[12px] text-slate-500">Scroll for all {sorted.length}</div>}
    </div>
  )
}
