import { useState, useEffect } from 'react'
import { getAgents, type Agent } from '../services/api'

interface SecurityFinding {
  category: string
  severity: 'high' | 'medium' | 'low'
  agent: string
  description: string
}

export default function SecurityView() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { fetchData() }, [])

  async function fetchData() {
    try {
      setLoading(true)
      const resp = await getAgents(1, 100)
      setAgents(resp.data.data)
      setError(null)
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Failed to fetch')
    } finally {
      setLoading(false)
    }
  }

  // Generate security findings from agent data
  const findings: SecurityFinding[] = []
  agents.forEach(agent => {
    // HIGH: Risk level HIGH
    if (agent.riskLevel === 'HIGH') {
      findings.push({
        category: 'Data Risk',
        severity: 'high',
        agent: agent.name,
        description: 'High-risk agent — requires encryption at rest and access logging',
      })
    }
    // HIGH: No governance
    if (!agent.reviews || Object.keys(agent.reviews).length === 0) {
      findings.push({
        category: 'Governance',
        severity: 'high',
        agent: agent.name,
        description: 'Agent has no governance reviews',
      })
    }
    // MEDIUM: External model provider
    const externalModels = ['GPT-5', 'GPT-5-mini', 'GPT-5-nano', 'Claude Sonnet 4.5', 'Claude Haiku 4.5']
    if (agent.modelName && externalModels.includes(agent.modelName)) {
      findings.push({
        category: 'Data Residency',
        severity: 'medium',
        agent: agent.name,
        description: `External model provider (${agent.modelName}) — ensure data residency compliance`,
      })
    }
    // MEDIUM: Many MCP servers
    if (agent.mcpServers && agent.mcpServers.length > 3) {
      findings.push({
        category: 'Attack Surface',
        severity: 'medium',
        agent: agent.name,
        description: `Many MCP server integrations (${agent.mcpServers.length}) — review tool permissions`,
      })
    }
    // LOW: Frontier model on simple task
    const frontierModels = ['GPT-5', 'Claude Opus 4.8']
    const simpleTasks = ['Conversational AI / Chatbot', 'Copilot / Assistant']
    if (agent.modelName && frontierModels.includes(agent.modelName) && simpleTasks.includes(agent.aiType)) {
      findings.push({
        category: 'Cost Efficiency',
        severity: 'low',
        agent: agent.name,
        description: `Frontier model on simple task — consider downgrade`,
      })
    }
  })

  const highCount = findings.filter(f => f.severity === 'high').length
  const mediumCount = findings.filter(f => f.severity === 'medium').length
  const lowCount = findings.filter(f => f.severity === 'low').length

  if (loading) return <div className="p-8 text-center text-gray-500">Loading...</div>
  if (error) return <div className="p-8 text-center text-red-500">Error: {error}</div>

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Security & Compliance</h1>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-red-50 rounded-lg border border-red-200 p-4">
          <div className="text-xs text-red-600 uppercase">High Severity</div>
          <div className="text-2xl font-bold text-red-700">{highCount}</div>
        </div>
        <div className="bg-yellow-50 rounded-lg border border-yellow-200 p-4">
          <div className="text-xs text-yellow-600 uppercase">Medium Severity</div>
          <div className="text-2xl font-bold text-yellow-700">{mediumCount}</div>
        </div>
        <div className="bg-blue-50 rounded-lg border border-blue-200 p-4">
          <div className="text-xs text-blue-600 uppercase">Low Severity</div>
          <div className="text-2xl font-bold text-blue-700">{lowCount}</div>
        </div>
        <div className="bg-green-50 rounded-lg border border-green-200 p-4">
          <div className="text-xs text-green-600 uppercase">Agents Reviewed</div>
          <div className="text-2xl font-bold text-green-700">{agents.length}</div>
        </div>
      </div>

      {/* Findings Table */}
      <div className="bg-white rounded-lg border overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b">
              <th className="p-3">Severity</th>
              <th className="p-3">Category</th>
              <th className="p-3">Agent</th>
              <th className="p-3">Description</th>
            </tr>
          </thead>
          <tbody>
            {findings.map((f, i) => (
              <tr key={i} className="border-b last:border-0">
                <td className="p-3">
                  <span className={`px-2 py-0.5 rounded text-xs ${
                    f.severity === 'high' ? 'bg-red-100 text-red-700' :
                    f.severity === 'medium' ? 'bg-yellow-100 text-yellow-700' :
                    'bg-blue-100 text-blue-700'
                  }`}>
                    {f.severity}
                  </span>
                </td>
                <td className="p-3">{f.category}</td>
                <td className="p-3 font-medium">{f.agent}</td>
                <td className="p-3">{f.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Decommissioning */}
      <div className="bg-white rounded-lg border p-4">
        <h2 className="font-semibold mb-3">Decommissioning Candidates</h2>
        <div className="space-y-2">
          {agents.filter(a => a.stage === 'Deprecated').map(a => (
            <div key={a.id} className="flex items-center gap-3 p-2 bg-gray-50 rounded">
              <div className="w-2 h-2 rounded-full bg-red-500" />
              <span className="font-medium">{a.name}</span>
              <span className="text-sm text-gray-500">{a.riskNote || 'Scheduled for shutdown'}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
