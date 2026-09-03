import { useState, useEffect } from 'react'
import { getAgents, getConcentrationRisk, getGraph, type Agent } from '../services/api'
import NetworkGraph from '../components/NetworkGraph'

export default function PlatformView() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [concentrationRisk, setConcentrationRisk] = useState<{ name: string; count: number }[]>([])
  const [graph, setGraph] = useState<{ nodes: { id: string; name: string; type: string }[]; edges: { from: string; to: string }[] } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { fetchData() }, [])

  async function fetchData() {
    try {
      setLoading(true)
      const [agentsRes, riskRes, graphRes] = await Promise.all([
        getAgents(1, 100),
        getConcentrationRisk(),
        getGraph(),
      ])
      setAgents(agentsRes.data.data)
      setConcentrationRisk(riskRes.data)
      setGraph(graphRes.data)
      setError(null)
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Failed to fetch')
    } finally {
      setLoading(false)
    }
  }

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
          <div className="space-y-2">
            {concentrationRisk.map(risk => (
              <div key={risk.name} className="flex items-center gap-3">
                <div className="flex-1">
                  <div className="text-sm font-medium">{risk.name}</div>
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className="bg-red-500 h-2 rounded-full"
                      style={{ width: `${Math.min(100, risk.count * 20)}%` }}
                    />
                  </div>
                </div>
                <span className="text-sm text-gray-500">{risk.count} agents</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Cross-AI Call Network SVG Graph */}
      {graph && graph.nodes.length > 0 && (
        <div className="bg-white rounded-lg border p-4">
          <h2 className="font-semibold mb-3">Cross-AI Call Network</h2>
          <div className="flex justify-center">
            <NetworkGraph nodes={graph.nodes} edges={graph.edges} width={500} height={400} />
          </div>

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
