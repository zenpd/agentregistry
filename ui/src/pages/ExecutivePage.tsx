import { useState, useEffect } from 'react'
import {
  getAgents, getRiskSummary, getPortfolioEconomics,
  type Agent, type PaginationInfo, type RiskSummary, type PortfolioEconomics,
} from '../services/api'
import BarChart from '../components/BarChart'
import RiskPie from '../components/RiskPie'
import RiskHeatmap from '../components/RiskHeatmap'

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

const CATEGORY_COLORS: Record<string, string> = {
  SECURITY: '#e11d48',
  DATA_PRIVACY: '#8b5cf6',
  OPERATIONAL: '#f59e0b',
  FINANCIAL: '#3DDBD9',
  COMPLIANCE: '#6366f1',
  REPUTATIONAL: '#f472b6',
}

function fmtMoney(n: number): string {
  if (Math.abs(n) >= 1000000) return '$' + (n / 1000000).toFixed(1) + 'M'
  if (Math.abs(n) >= 1000) return '$' + Math.round(n / 1000) + 'K'
  return '$' + Math.round(n)
}

export default function ExecutivePage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [, setPagination] = useState<PaginationInfo | null>(null)
  const [risks, setRisks] = useState<RiskSummary | null>(null)
  const [economics, setEconomics] = useState<PortfolioEconomics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { fetchAll() }, [])

  async function fetchAll() {
    try {
      setLoading(true)
      const [agentsRes, riskRes, econRes] = await Promise.all([
        getAgents(1, 100),
        getRiskSummary().catch(() => null),
        getPortfolioEconomics().catch(() => null),
      ])
      setAgents(agentsRes.data.data)
      setPagination(agentsRes.data.pagination)
      setRisks(riskRes?.data ?? null)
      setEconomics(econRes?.data ?? null)
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

  if (loading) return <div className="p-8 text-center text-gray-500">Loading...</div>
  if (error) return <div className="p-8 text-center text-rose-500">Error: {error}</div>

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold gradient-text">Executive Overview</h1>
        <p className="text-gray-500 mt-0.5">AI portfolio health, risk, and economics at a glance.</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        <KPICard label="Total Agents" value={agents.length.toString()} sub={`${inProd.length} in production`} />
        <KPICard label="Monthly Value" value={fmtMoney(monthlyValue)} sub="Realized from production" color="#3DDBD9" />
        <KPICard label="In Pipeline" value={pipelineAgents.length.toString()} sub="Ideation → Testing" />
        <KPICard label="At Risk" value={atRisk.length.toString()} sub="Flagged for attention" color={atRisk.length > 0 ? '#E06B85' : undefined} />
        <KPICard label="Open Findings" value={(risks?.totalFindings ?? 0).toString()} sub="Across all risk categories" color={risks && risks.totalFindings > 0 ? '#f59e0b' : undefined} />
      </div>

      {/* Revenue vs Expenditure */}
      {economics && (
        <div className="card p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-gray-900">Revenue vs Expenditure</h2>
            <span className="text-xs text-gray-400">Token/LLM cost is measured; infra cost is an estimate by lifecycle stage</span>
          </div>
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div>
              <div className="text-xs text-gray-500 uppercase tracking-wide">Revenue (declared value)</div>
              <div className="text-2xl font-bold text-emerald-600 mt-1">{fmtMoney(economics.totalRevenueCents / 100)}</div>
            </div>
            <div>
              <div className="text-xs text-gray-500 uppercase tracking-wide">Expenditure (token + infra)</div>
              <div className="text-2xl font-bold text-rose-600 mt-1">{fmtMoney(economics.totalExpenditureCents / 100)}</div>
            </div>
            <div>
              <div className="text-xs text-gray-500 uppercase tracking-wide">Net</div>
              <div className={`text-2xl font-bold mt-1 ${economics.totalNetCents >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>{fmtMoney(economics.totalNetCents / 100)}</div>
            </div>
          </div>
          {/* Stacked comparison bar */}
          <div className="h-3 rounded-full bg-gray-100 overflow-hidden flex">
            {(() => {
              const total = Math.max(economics.totalRevenueCents, economics.totalExpenditureCents, 1)
              return (
                <>
                  <div className="h-full bg-emerald-400" style={{ width: `${(economics.totalRevenueCents / total) * 100}%` }} />
                </>
              )
            })()}
          </div>
          <div className="flex justify-between text-xs text-gray-400 mt-1">
            <span>revenue</span>
            <span>{economics.totalExpenditureCents > 0 ? `${((economics.totalExpenditureCents / economics.totalRevenueCents) * 100).toFixed(2)}% spent on cost` : 'no measured expenditure yet'}</span>
          </div>
        </div>
      )}

      {/* Risk pie + heatmap */}
      {risks && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="card p-5">
            <h2 className="font-semibold text-gray-900 mb-3">Risk Findings by Category</h2>
            <RiskPie
              data={risks.byCategory.map(c => ({ label: c.label, count: c.count, color: CATEGORY_COLORS[c.category] || '#6b7280' }))}
            />
          </div>
          <div className="card p-5">
            <h2 className="font-semibold text-gray-900 mb-3">Risk Heatmap — Category × Severity</h2>
            <RiskHeatmap rows={risks.heatmap} severities={risks.severities} />
          </div>
        </div>
      )}

      {/* Pipeline Rail - clickable chips */}
      <div className="card p-5">
        <h2 className="font-semibold text-gray-900 mb-3">Pipeline</h2>
        <div className="grid grid-cols-5 gap-2">
          {['Ideation', 'Development', 'Testing', 'Production', 'Deprecated'].map(stage => {
            const stageAgents = agents.filter(a => a.stage === stage)
            return (
              <div key={stage} className="text-center p-3 rounded-xl" style={{ backgroundColor: STAGE_COLORS[stage] + '15' }}>
                <div className="text-2xl font-bold" style={{ color: STAGE_COLORS[stage] }}>{stageAgents.length}</div>
                <div className="text-xs text-gray-600 mb-2">{stage}</div>
                <div className="space-y-1">
                  {stageAgents.slice(0, 3).map(a => (
                    <div
                      key={a.id}
                      className="text-xs bg-white/70 rounded px-1 py-0.5 truncate cursor-pointer hover:bg-white"
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
        <div className="card p-5">
          <h2 className="font-semibold text-gray-900 mb-3">Portfolio Mix by AI Type</h2>
          <BarChart
            data={Object.entries(
              agents.reduce((acc, a) => {
                acc[a.aiType] = (acc[a.aiType] || 0) + 1
                return acc
              }, {} as Record<string, number>)
            ).map(([label, value]) => ({ label, value, color: TYPE_COLORS[label] || '#6E7B8F' }))}
          />
        </div>
        <div className="card p-5">
          <h2 className="font-semibold text-gray-900 mb-3">Value by Business Unit</h2>
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
      <div className="card p-5">
        <h2 className="font-semibold text-gray-900 mb-3">Top Agents by Value</h2>
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
            {[...agents].sort((a, b) => b.valueAmount - a.valueAmount).slice(0, 5).map(a => (
              <tr key={a.id} className="border-b last:border-0">
                <td className="py-2 text-gray-900">{a.name}</td>
                <td className="py-2">
                  <span className="px-2 py-0.5 rounded-full text-xs" style={{ backgroundColor: (TYPE_COLORS[a.aiType] || '#6E7B8F') + '20', color: TYPE_COLORS[a.aiType] || '#6E7B8F' }}>
                    {a.aiType}
                  </span>
                </td>
                <td className="py-2 text-gray-600">{a.dept}</td>
                <td className="py-2">
                  <span className="px-2 py-0.5 rounded-full text-xs" style={{ backgroundColor: STAGE_COLORS[a.stage] + '20', color: STAGE_COLORS[a.stage] }}>
                    {a.stage}
                  </span>
                </td>
                <td className="py-2 text-right font-mono text-gray-900">{fmtMoney(a.valueAmount)}</td>
                <td className="py-2 text-xs text-gray-500">{a.valueType || 'Not quantified'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* At Risk */}
      {atRisk.length > 0 && (
        <div className="bg-rose-50 rounded-2xl border border-rose-200 p-5">
          <h2 className="font-semibold text-rose-800 mb-3">Needs Attention</h2>
          {atRisk.map(a => (
            <div key={a.id} className="flex items-start gap-3 py-2">
              <div className="w-2 h-2 rounded-full bg-rose-500 mt-2" />
              <div>
                <div className="font-medium text-gray-900">{a.name}</div>
                <div className="text-sm text-rose-600">{a.riskNote || 'Flagged as at-risk'}</div>
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
    <div className="card p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wide">{label}</div>
      <div className="text-2xl font-bold mt-1" style={{ color: color || '#111827' }}>{value}</div>
      <div className="text-xs text-gray-400 mt-1">{sub}</div>
    </div>
  )
}
