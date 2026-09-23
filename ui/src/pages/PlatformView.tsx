import { useState, useEffect, useMemo } from 'react'
import { getAgents, getConcentrationRisk, getGraphV2, type Agent } from '../services/api'
import TraceNetworkGraph, { type TraceNode, type TraceEdge } from '../components/TraceNetworkGraph'

export default function PlatformView() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [concentrationRisk, setConcentrationRisk] = useState<{ name: string; count: number }[]>([])
  const [graph, setGraph] = useState<{ nodes: TraceNode[]; edges: TraceEdge[] } | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
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

  const selectedNode = useMemo(
    () => (graph && selectedId ? graph.nodes.find(n => n.id === selectedId) ?? null : null),
    [graph, selectedId],
  )
  const selectedAgent = useMemo(
    () => (selectedId ? agents.find(a => a.id === selectedId) ?? null : null),
    [agents, selectedId],
  )
  const calls = useMemo(
    () => (graph && selectedId ? graph.edges.filter(e => e.from === selectedId).map(e => e.to) : []),
    [graph, selectedId],
  )
  const calledBy = useMemo(
    () => (graph && selectedId ? graph.edges.filter(e => e.to === selectedId).map(e => e.from) : []),
    [graph, selectedId],
  )

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

  if (loading) return <div className="p-8 text-center text-gray-500">Loading...</div>
  if (error) return <div className="p-8 text-center text-red-500">Error: {error}</div>

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Platform & Dependencies</h1>

      {/* Mini Cards Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MiniCard title="Enterprise Systems" items={systems} color="#3DDBD9" />
        <MiniCard title="Databases" items={databases} color="#8C7CF0" />
        <MiniCard title="MCP Servers" items={mcpServers} color="#F0A85A" />
        <MiniCard title="Knowledge Bases" items={knowledgeBases} color="#57C785" />
      </div>

      {/* Concentration Risk */}
      {concentrationRisk.length > 0 && (
        <div className="bg-white rounded-lg border p-4">
          <h2 className="font-semibold mb-3">Concentration Risk</h2>
          <p className="text-xs text-gray-400 mb-3">
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
                <span className="text-sm text-gray-500">{risk.count} agents</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Cross-AI Call Network */}
      {graph && graph.nodes.length > 0 && (
        <div className="bg-white rounded-lg border p-4">
          <h2 className="font-semibold mb-3">Cross-AI Call Network</h2>
          <p className="text-xs text-gray-400 mb-3">
            Agent-to-agent handoffs only — every registered agent is plotted, most have none. The systems,
            databases and MCP servers each agent uses are in the cards above and the matrix below. Drag, scroll to
            zoom, click a node for its detail.
          </p>
          <div className="relative rounded-lg border border-gray-100 overflow-hidden">
            <TraceNetworkGraph
              nodes={graph.nodes}
              edges={graph.edges}
              height={420}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          </div>
          {selectedNode && (
            <div className="mt-3 rounded-lg border border-gray-100 bg-gray-50 p-3 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-gray-800">{selectedNode.name}</span>
                {selectedNode.kind === 'external' ? (
                  <span className="rounded-full bg-violet-50 px-2 py-0.5 text-violet-700 ring-1 ring-violet-200">
                    Not registered
                  </span>
                ) : selectedAgent ? (
                  <span className="text-gray-400">{selectedAgent.aiType} · {selectedAgent.stage}</span>
                ) : null}
              </div>
              <div className="mt-1.5 grid grid-cols-2 gap-2 text-gray-500">
                <div>
                  <div className="text-[10px] uppercase text-gray-400">Calls</div>
                  {calls.length ? calls.map(n => (
                    <div key={n}>→ {graph.nodes.find(x => x.id === n)?.name || n}</div>
                  )) : <div>—</div>}
                </div>
                <div>
                  <div className="text-[10px] uppercase text-gray-400">Called by</div>
                  {calledBy.length ? calledBy.map(n => (
                    <div key={n}>← {graph.nodes.find(x => x.id === n)?.name || n}</div>
                  )) : <div>—</div>}
                </div>
              </div>
              {selectedNode.kind === 'external' && (
                <p className="mt-1.5 text-gray-400">
                  Referenced by another agent's declared "calls" but not itself registered — a shadow-AI candidate.
                </p>
              )}
            </div>
          )}

          {/* Edge Table */}
          {graph.edges.length > 0 && (
            <div className="mt-4">
              <h3 className="text-sm font-medium text-gray-600 mb-2">Agent Call Edges</h3>
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-gray-500 border-b">
                    <th className="pb-1">Caller</th>
                    <th className="pb-1"></th>
                    <th className="pb-1">Callee</th>
                    <th className="pb-1">Why</th>
                  </tr>
                </thead>
                <tbody>
                  {graph.edges.map((e, i) => {
                    const caller = graph.nodes.find(n => n.id === e.from)?.name || e.from
                    const callee = graph.nodes.find(n => n.id === e.to)?.name || e.to
                    return (
                      <tr key={i} className="border-b last:border-0">
                        <td className="py-1 font-medium">{caller}</td>
                        <td className="py-1 text-gray-400">→</td>
                        <td className="py-1 font-mono text-teal-600">{callee}</td>
                        <td className="py-1 text-gray-500">Hands off work to this agent</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Initiative -> Integration Matrix */}
          <div className="mt-4">
            <h3 className="text-sm font-medium text-gray-600 mb-2">Initiative → Integration Dependency Matrix</h3>
            <div className="overflow-x-auto">
              <table className="text-xs border-collapse">
                <thead>
                  <tr>
                    <th className="border p-1 bg-gray-50 text-left">Initiative</th>
                    {Object.keys(systems).slice(0, 6).map(s => (
                      <th key={s} className="border p-1 bg-gray-50 text-center" title={s}>{s.slice(0, 8)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {agents.slice(0, 10).map(a => (
                    <tr key={a.id}>
                      <td className="border p-1 font-medium truncate max-w-[120px]">{a.name}</td>
                      {Object.keys(systems).slice(0, 6).map(s => (
                        <td key={s} className="border p-1 text-center">
                          {a.enterpriseSystems?.includes(s) ? '●' : '—'}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function MiniCard({ title, items, color }: { title: string; items: Record<string, number>; color: string }) {
  const sorted = Object.entries(items).sort((a, b) => b[1] - a[1])
  return (
    <div className="bg-white rounded-lg border p-4">
      <div className="flex items-center gap-2 mb-2">
        <div className="w-3 h-3 rounded-full" style={{ backgroundColor: color }} />
        <h3 className="font-semibold text-sm">{title}</h3>
        <span className="text-xs text-gray-400 ml-auto">{sorted.length}</span>
      </div>
      <div className="space-y-1 max-h-32 overflow-y-auto">
        {sorted.slice(0, 8).map(([name, count]) => (
          <div key={name} className="flex justify-between text-xs">
            <span className="truncate">{name}</span>
            <span className="text-gray-400">{count}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
