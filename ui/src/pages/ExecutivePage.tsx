import { useState, useEffect } from 'react'
import { getAgents, type Agent, type PaginationInfo } from '../services/api'
import BarChart from '../components/BarChart'

const STAGE_COLORS: Record<string, string> = {
  Ideation: '#6E7B8F',
  Development: '#8C7CF0',
  Testing: '#F0A85A',
  Production: '#3DDBD9',
  Deprecated: '#E06B85',
}

const TYPE_COLORS: Record<string, string> = {
  'Autonomous Agent': '#3DDBD9',
  'Copilot / Assistant': '#8C7CF0',
  'Predictive / ML Model': '#F0A85A',
  'Generative AI Feature': '#F2A6D8',
  'Conversational AI / Chatbot': '#6EA8FE',
  'Computer Vision Model': '#57C785',
}

export default function ExecutivePage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [pagination, setPagination] = useState<PaginationInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchAgents()
  }, [])

  async function fetchAgents() {
    try {
      setLoading(true)
      const resp = await getAgents(1, 100)
      setAgents(resp.data.data)
      setPagination(resp.data.pagination)
      setError(null)
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Failed to fetch agents')
    } finally {
      setLoading(false)
    }
  }

  const inProd = agents.filter(a => a.stage === 'Production')
  const monthlyValue = inProd.reduce((s, a) => s + (a.valueAmount || 0), 0)
  const atRisk = agents.filter(a => a.atRisk)
  const pipelineAgents = agents.filter(a => ['Ideation', 'Development', 'Testing'].includes(a.stage))

  function fmtMoney(n: number): string {
    if (n >= 1000000) return '$' + (n / 1000000).toFixed(1) + 'M'
    if (n >= 1000) return '$' + Math.round(n / 1000) + 'K'
    return '$' + n
  }

  if (loading) return <div className="p-8 text-center text-gray-500">Loading...</div>
  if (error) return <div className="p-8 text-center text-red-500">Error: {error}</div>

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Executive Overview</h1>
      <p className="text-gray-600">AI portfolio health at a glance.</p>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        <KPICard label="Total Agents" value={agents.length.toString()} sub={`${inProd.length} in production`} />
        <KPICard label="Monthly Value" value={fmtMoney(monthlyValue)} sub="Realized from production" color="#3DDBD9" />
        <KPICard label="In Pipeline" value={pipelineAgents.length.toString()} sub="Ideation → Testing" />
        <KPICard label="At Risk" value={atRisk.length.toString()} sub="Flagged for attention" color={atRisk.length > 0 ? '#E06B85' : undefined} />
        <KPICard label="AI Types" value={[...new Set(agents.map(a => a.aiType))].length.toString()} sub="Different categories" />
      </div>

      {/* Pipeline Rail - clickable chips */}
      <div className="bg-white rounded-lg border p-4">
        <h2 className="font-semibold mb-3">Pipeline</h2>
        <div className="grid grid-cols-5 gap-2">
          {['Ideation', 'Development', 'Testing', 'Production', 'Deprecated'].map(stage => {
            const stageAgents = agents.filter(a => a.stage === stage)
            return (
              <div key={stage} className="text-center p-3 rounded" style={{ backgroundColor: STAGE_COLORS[stage] + '15' }}>
                <div className="text-2xl font-bold" style={{ color: STAGE_COLORS[stage] }}>{stageAgents.length}</div>
                <div className="text-xs text-gray-600 mb-2">{stage}</div>
                <div className="space-y-1">
                  {stageAgents.slice(0, 3).map(a => (
                    <div
                      key={a.id}
                      className="text-xs bg-white/60 rounded px-1 py-0.5 truncate cursor-pointer hover:bg-white"
                      title={a.name}
                    >
                      {a.name}
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Portfolio Mix by AI Type + Value by Business Unit */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-white rounded-lg border p-4">
          <h2 className="font-semibold mb-3">Portfolio Mix by AI Type</h2>
          <BarChart
            data={Object.entries(
              agents.reduce((acc, a) => {
                acc[a.aiType] = (acc[a.aiType] || 0) + 1
                return acc
              }, {} as Record<string, number>)
            ).map(([label, value], i) => ({ label, value, color: TYPE_COLORS[label] || '#6E7B8F' }))}
          />
        </div>
        <div className="bg-white rounded-lg border p-4">
          <h2 className="font-semibold mb-3">Value by Business Unit</h2>
          <BarChart
            data={Object.entries(
              agents.reduce((acc, a) => {
                const dept = a.dept || 'Unknown'
                acc[dept] = (acc[dept] || 0) + (a.valueAmount || 0)
                return acc
              }, {} as Record<string, number>)
            ).map(([label, value]) => ({ label, value }))}
          />
        </div>
      </div>

      {/* Top Agents */}
      <div className="bg-white rounded-lg border p-4">
        <h2 className="font-semibold mb-3">Top Agents by Value</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b">
              <th className="pb-2">Agent</th>
              <th className="pb-2">Type</th>
              <th className="pb-2">Department</th>
              <th className="pb-2">Stage</th>
              <th className="pb-2 text-right">Value/mo</th>
              <th className="pb-2">Basis</th>
            </tr>
          </thead>
          <tbody>
            {agents.sort((a, b) => b.valueAmount - a.valueAmount).slice(0, 5).map(a => (
              <tr key={a.id} className="border-b last:border-0">
                <td className="py-2">{a.name}</td>
                <td className="py-2">
                  <span className="px-2 py-0.5 rounded text-xs" style={{ backgroundColor: (TYPE_COLORS[a.aiType] || '#6E7B8F') + '20', color: TYPE_COLORS[a.aiType] || '#6E7B8F' }}>
                    {a.aiType}
                  </span>
                </td>
                <td className="py-2 text-gray-600">{a.dept}</td>
                <td className="py-2">
                  <span className="px-2 py-0.5 rounded text-xs" style={{ backgroundColor: STAGE_COLORS[a.stage] + '20', color: STAGE_COLORS[a.stage] }}>
                    {a.stage}
                  </span>
                </td>
                <td className="py-2 text-right font-mono">{fmtMoney(a.valueAmount)}</td>
                <td className="py-2 text-xs text-gray-500">{a.valueType || 'Not quantified'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* At Risk */}
      {atRisk.length > 0 && (
        <div className="bg-red-50 rounded-lg border border-red-200 p-4">
          <h2 className="font-semibold text-red-800 mb-3">Needs Attention</h2>
          {atRisk.map(a => (
            <div key={a.id} className="flex items-start gap-3 py-2">
              <div className="w-2 h-2 rounded-full bg-red-500 mt-2" />
              <div>
                <div className="font-medium">{a.name}</div>
                <div className="text-sm text-red-600">{a.riskNote || 'Flagged as at-risk'}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function KPICard({ label, value, sub, color }: { label: string; value: string; sub: string; color?: string }) {
  return (
    <div className="bg-white rounded-lg border p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wide">{label}</div>
      <div className="text-2xl font-bold mt-1" style={{ color: color || '#111827' }}>{value}</div>
      <div className="text-xs text-gray-400 mt-1">{sub}</div>
    </div>
  )
}
