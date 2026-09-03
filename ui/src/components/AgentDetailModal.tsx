import { useState, useEffect } from 'react'
import { getAgents, getGraph, type Agent, type GraphData } from '../services/api'

interface Props {
  agentId: string
  onClose: () => void
}

export default function AgentDetailModal({ agentId, onClose }: Props) {
  const [agent, setAgent] = useState<Agent | null>(null)
  const [graph, setGraph] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const [agentRes, graphRes] = await Promise.all([
          getAgents(1, 100, { q: undefined }),
          getGraph()
        ])
        const found = agentRes.data.data.find(a => a.id === agentId)
        setAgent(found || null)
        setGraph(graphRes.data)
      } catch (e) {
        console.error('Failed to load agent detail:', e)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [agentId])

  if (loading) return null
  if (!agent) return null

  const deps = graph ? graph.edges.filter(e => e.from === agentId || e.to === agentId) : []

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-gray-900 rounded-lg border border-gray-700 max-w-2xl w-full max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="p-6">
          <div className="flex justify-between items-start mb-4">
            <div>
              <h2 className="text-xl font-bold">{agent.name}</h2>
              <p className="text-sm text-gray-400">{agent.aiType} · {agent.dept} · {agent.stage}</p>
            </div>
            <button onClick={onClose} className="text-gray-400 hover:text-white text-2xl leading-none">&times;</button>
          </div>

          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <span className="text-xs text-gray-500">Owner</span>
              <p className="text-sm">{agent.owner || 'Unassigned'}</p>
            </div>
            <div>
              <span className="text-xs text-gray-500">Value</span>
              <p className="text-sm font-mono">${(agent.valueAmount / 1000).toFixed(0)}K/mo</p>
            </div>
            <div>
              <span className="text-xs text-gray-500">API Endpoint</span>
              <p className="text-sm font-mono">{agent.apiEndpoint || 'N/A'}</p>
            </div>
            <div>
              <span className="text-xs text-gray-500">Risk</span>
              <p className="text-sm">{agent.riskLevel || 'LOW'}</p>
            </div>
          </div>

          {agent.description && (
            <div className="mb-4">
              <span className="text-xs text-gray-500">Description</span>
              <p className="text-sm text-gray-300">{agent.description}</p>
            </div>
          )}

          {agent.businessOutcome && (
            <div className="mb-4">
              <span className="text-xs text-gray-500">Business Outcome</span>
              <p className="text-sm text-gray-300">{agent.businessOutcome}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4 mb-4">
            {agent.enterpriseSystems && agent.enterpriseSystems.length > 0 && (
              <div>
                <span className="text-xs text-gray-500">Enterprise Systems</span>
                <div className="flex flex-wrap gap-1 mt-1">
                  {agent.enterpriseSystems.map(s => (
                    <span key={s} className="text-xs bg-teal-900/30 text-teal-300 px-2 py-0.5 rounded">{s}</span>
                  ))}
                </div>
              </div>
            )}
            {agent.databases && agent.databases.length > 0 && (
              <div>
                <span className="text-xs text-gray-500">Databases</span>
                <div className="flex flex-wrap gap-1 mt-1">
                  {agent.databases.map(d => (
                    <span key={d} className="text-xs bg-amber-900/30 text-amber-300 px-2 py-0.5 rounded">{d}</span>
                  ))}
                </div>
              </div>
            )}
            {agent.mcpServers && agent.mcpServers.length > 0 && (
              <div>
                <span className="text-xs text-gray-500">MCP Servers</span>
                <div className="flex flex-wrap gap-1 mt-1">
                  {agent.mcpServers.map(m => (
                    <span key={m} className="text-xs bg-purple-900/30 text-purple-300 px-2 py-0.5 rounded">{m}</span>
                  ))}
                </div>
              </div>
            )}
            {agent.knowledgeBases && agent.knowledgeBases.length > 0 && (
              <div>
                <span className="text-xs text-gray-500">Knowledge Bases</span>
                <div className="flex flex-wrap gap-1 mt-1">
                  {agent.knowledgeBases.map(k => (
                    <span key={k} className="text-xs bg-green-900/30 text-green-300 px-2 py-0.5 rounded">{k}</span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {deps.length > 0 && (
            <div>
              <span className="text-xs text-gray-500">Dependencies</span>
              <div className="mt-2 space-y-1">
                {deps.map((e, i) => {
                  const other = e.from === agentId ? e.to : e.from
                  const direction = e.from === agentId ? 'calls' : 'called by'
                  return (
                    <div key={i} className="text-xs flex gap-2">
                      <span className="text-gray-500">{direction}</span>
                      <span className="font-mono text-teal-400">{other}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {agent.reviews && Object.keys(agent.reviews).length > 0 && (
            <div className="mt-4">
              <span className="text-xs text-gray-500">Governance</span>
              <div className="flex gap-2 mt-1">
                {Object.entries(agent.reviews).map(([gate, status]) => (
                  <span key={gate} className="text-xs px-2 py-0.5 rounded bg-gray-800">
                    {gate}: {status}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}