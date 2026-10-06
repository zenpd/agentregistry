import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  getAgents, getRiskSummary, getPortfolioEconomics,
  type Agent, type PaginationInfo, type RiskSummary, type PortfolioEconomics,
} from '../services/api'
import InfoTip from '../components/InfoTip'
import type { GlossaryKey } from '../lib/glossary'
import BarChart from '../components/BarChart'
import RiskPie from '../components/RiskPie'
import RiskHeatmap from '../components/RiskHeatmap'
import { fmtMoney, STAGE_PILL, TypeBadge } from './agent/shared'

const STAGE_COLORS: Record<string, string> = {
  Ideation: '#6E7B8F',
  Development: '#8C7CF0',
  Testing: '#F0A85A',
  Production: '#3DDBD9',
  Deprecated: '#E06B85',
}

const CATEGORY_COLORS: Record<string, string> = {
  SECURITY: '#e11d48',
  DATA_PRIVACY: '#8b5cf6',
  OPERATIONAL: '#f59e0b',
  FINANCIAL: '#3DDBD9',
  COMPLIANCE: '#6366f1',
  REPUTATIONAL: '#f472b6',
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

  if (loading) return <div className="p-8 text-center text-slate-600">Loading...</div>
  if (error) return <div className="p-8 text-center text-rose-500">Error: {error}</div>

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold gradient-text">Executive Overview</h1>
        <p className="text-slate-600 mt-0.5">AI portfolio health, risk, and economics at a glance.</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        <KPICard label="Total Agents" value={agents.length.toString()} sub={`${inProd.length} in production`} />
        <KPICard label="Monthly Value" tip="declared_value" value={fmtMoney(monthlyValue)} sub="Realized from production" color="#059669" />
        <KPICard label="In Pipeline" value={pipelineAgents.length.toString()} sub="Ideation → Testing" />
        <KPICard label="At Risk" value={atRisk.length.toString()} sub="Flagged for attention" color={atRisk.length > 0 ? '#E06B85' : undefined} />
        <KPICard label="Open Findings" tip="risk_register" value={(risks?.totalFindings ?? 0).toString()} sub="Across all risk categories" color={risks && risks.totalFindings > 0 ? '#f59e0b' : undefined} />
      </div>

      {/* Revenue vs Expenditure */}
      {economics && (
        <div className="card p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-slate-900">Revenue vs Expenditure</h2>
            <span className="text-xs text-slate-500">Token/LLM cost is measured; infra cost is an estimate by lifecycle stage</span>
          </div>
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div>
              <div className="text-xs text-slate-600 uppercase tracking-wide">Revenue (declared value / mo)</div>
              <div className="text-2xl font-bold text-emerald-600 mt-1">{fmtMoney(economics.totalRevenueCents / 100)}</div>
              {/* Says why this differs from the Monthly Value KPI above (production only),
                  split the same way that KPI and Business Impact count it. */}
              <div className="text-xs text-slate-500 mt-0.5">
                {fmtMoney(monthlyValue)} realized in production + {fmtMoney(economics.totalRevenueCents / 100 - monthlyValue)} projected
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-600 uppercase tracking-wide">Expenditure (token + infra)</div>
              <div className="text-2xl font-bold text-rose-600 mt-1">{fmtMoney(economics.totalExpenditureCents / 100)}</div>
            </div>
            <div>
              <div className="text-xs text-slate-600 uppercase tracking-wide">Net</div>
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
          <div className="flex justify-between text-xs text-slate-500 mt-1">
            <span>revenue</span>
            <span>{economics.totalExpenditureCents > 0 ? `${((economics.totalExpenditureCents / economics.totalRevenueCents) * 100).toFixed(2)}% spent on cost` : 'no measured expenditure yet'}</span>
          </div>
        </div>
      )}

      {/* Risk pie + heatmap */}
      {risks && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="card p-5">
            <h2 className="font-semibold text-slate-900 mb-3">Risk Findings by Category</h2>
            <RiskPie
              data={risks.byCategory.map(c => ({ label: c.label, count: c.count, color: CATEGORY_COLORS[c.category] || '#6b7280' }))}
            />
          </div>
          <div className="card p-5">
            <h2 className="font-semibold text-slate-900 mb-3">Risk Heatmap — Category × Severity <InfoTip term="severity" /></h2>
            <RiskHeatmap rows={risks.heatmap} severities={risks.severities} />
          </div>
        </div>
      )}

      {/* Pipeline Rail - clickable chips */}
      <div className="card p-5">
        <h2 className="font-semibold text-slate-900 mb-3">Pipeline <InfoTip term="stage" /></h2>
        <div className="grid grid-cols-5 gap-2">
          {['Ideation', 'Development', 'Testing', 'Production', 'Deprecated'].map(stage => {
            const stageAgents = agents.filter(a => a.stage === stage)
            return (
              <div key={stage} className="text-center p-3 rounded-xl" style={{ backgroundColor: STAGE_COLORS[stage] + '15' }}>
                <div className="text-2xl font-bold" style={{ color: STAGE_COLORS[stage] }}>{stageAgents.length}</div>
                <div className="text-xs text-slate-700 mb-2">{stage}</div>
                <div className="space-y-1">
                  {stageAgents.slice(0, 3).map(a => (
                    <Link
                      key={a.id}
                      to={`/agents/${a.id}`}
                      className="block text-xs bg-white/70 rounded px-1 py-0.5 truncate text-slate-700 hover:bg-white hover:text-slate-900"
                      title={`${a.name} — open`}
                    >
                      {a.name}
                    </Link>
                  ))}
                  {stageAgents.length > 3 && (
                    <div className="text-[12px] text-slate-600" title={stageAgents.slice(3).map(a => a.name).join('\n')}>
                      +{stageAgents.length - 3} more
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Portfolio Mix by AI Type + Value by Business Unit */}
      <div className="grid grid-cols-2 gap-4">
        <div className="card p-5">
          <h2 className="font-semibold text-slate-900 mb-3">Portfolio Mix by AI Type</h2>
          <BarChart
            label="Agents by AI type"
            format={n => `${n} agent${n === 1 ? '' : 's'}`}
            data={Object.entries(
              agents.reduce((acc, a) => {
                acc[a.aiType] = (acc[a.aiType] || 0) + 1
                return acc
              }, {} as Record<string, number>)
            ).map(([label, value]) => ({ label, value }))}
          />
        </div>
        <div className="card p-5">
          <h2 className="font-semibold text-slate-900">Value by Business Unit</h2>
          <p className="text-xs text-slate-500 mb-3">Declared value per month, realized + projected</p>
          <BarChart
            label="Declared value per month by business unit"
            format={fmtMoney}
            data={Object.entries(
              agents.reduce((acc, a) => {
                const dept = a.deptName || a.dept || 'Unassigned'
                acc[dept] = (acc[dept] || 0) + (a.valueAmount || 0)
                return acc
              }, {} as Record<string, number>)
            ).map(([label, value]) => ({ label, value }))}
          />
        </div>
      </div>

      {/* Top Agents */}
      <div className="card p-5">
        <h2 className="font-semibold text-slate-900 mb-3">Top Agents by Value</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-600 border-b">
              <th className="pb-2">Agent</th>
              <th className="pb-2">Type <InfoTip term="ai_type" /></th>
              <th className="pb-2">Department <InfoTip term="department" /></th>
              <th className="pb-2">Stage <InfoTip term="stage" /></th>
              <th className="pb-2 text-right">Value/mo</th>
              <th className="pb-2">Basis</th>
            </tr>
          </thead>
          <tbody>
            {[...agents].sort((a, b) => b.valueAmount - a.valueAmount).slice(0, 5).map(a => (
              <tr key={a.id} className="border-b last:border-0">
                <td className="py-2"><Link to={`/agents/${a.id}`} className="text-slate-900 hover:text-zen-700">{a.name}</Link></td>
                <td className="py-2"><TypeBadge type={a.aiType} /></td>
                <td className="py-2 text-slate-700">{a.deptName || a.dept || 'Unassigned'}</td>
                <td className="py-2"><span className={STAGE_PILL[a.stage] || 'status-pending'}>{a.stage}</span></td>
                <td className="py-2 text-right font-mono text-slate-900">{fmtMoney(a.valueAmount)}</td>
                <td className="py-2 text-xs text-slate-600">{a.valueType || 'Not quantified'}</td>
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
                <div className="font-medium text-slate-900">{a.name}</div>
                <div className="text-sm text-rose-600">{a.riskNote || 'Flagged as at-risk'}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function KPICard({ label, value, sub, color, tip }: { label: string; value: string; sub: string; color?: string; tip?: GlossaryKey }) {
  return (
    <div className="card p-4">
      <div className="text-xs text-slate-600 uppercase tracking-wide">{label}{tip && <> <InfoTip term={tip} /></>}</div>
      <div className="text-2xl font-bold mt-1" style={{ color: color || '#111827' }}>{value}</div>
      <div className="text-xs text-slate-500 mt-1">{sub}</div>
    </div>
  )
}
