import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { getRiskSummary, type RegistryAgent, type RiskSummary } from '../services/api'
import InfoTip from '../components/InfoTip'
import BarChart from '../components/BarChart'
import RiskPie from '../components/RiskPie'
import RiskHeatmap from '../components/RiskHeatmap'
import { getPortfolioAttention, type PortfolioAttention } from '../services/ops/overview'
import BusinessView, { Kpi, type UnitContext } from './BusinessView'

const STAGES = ['Ideation', 'Development', 'Testing', 'Production', 'Deprecated']
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

type Behind = 'agents' | 'findings'
const isPipeline = (a: RegistryAgent) => ['Ideation', 'Development', 'Testing'].includes(a.stage)

// One page for the whole portfolio. The business unit filter at the top drives every figure, chart and list:
// agents, value and cost, the pipeline, risks, what is waiting to go live and the agent table.
export default function ExecutivePage() {
  const [searchParams] = useSearchParams()
  const dept = searchParams.get('dept') || ''
  const [risks, setRisks] = useState<RiskSummary | null>(null)
  const [attention, setAttention] = useState<PortfolioAttention | null>(null)
  // The card that was clicked: the agents its number is made of are listed under the cards.
  const [behind, setBehind] = useState<Behind | null>(null)
  const toggle = (k: Behind) => setBehind(behind === k ? null : k)

  // Risk findings of the chosen business unit. The earlier figures stay on screen until the new ones arrive.
  useEffect(() => { getRiskSummary(dept || undefined).then(r => setRisks(r.data)).catch(() => setRisks(null)) }, [dept])
  useEffect(() => { getPortfolioAttention().then(r => setAttention(r.data)).catch(() => setAttention(null)) }, [])
  useEffect(() => { setBehind(null) }, [dept])

  // /#business-impact (the earlier Business Impact address) lands on this page.
  useEffect(() => {
    if (window.location.hash === '#business-impact') setTimeout(() => document.getElementById('business-impact')?.scrollIntoView({ behavior: 'smooth' }), 600)
  }, [])

  return (
    <div className="space-y-5 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold gradient-text">Executive Overview</h1>
        <p className="text-slate-600 mt-0.5">All agents in one view: how many are live, what they are worth and what they cost, what is waiting to go live and where the risks are. Choose a business unit to see that unit alone. Click a card to see what is counted.</p>
      </div>

      <BusinessView embedded slots={{
        agentsCard: { open: behind === 'agents', toggle: () => toggle('agents') },
        kpis: c => {
          const atRisk = c.running.filter(a => a.atRisk).length
          return (
            <Kpi label="Open risk findings" tip="open_risk_findings" value={(risks?.totalFindings ?? 0).toLocaleString()}
              sub={`Across all risk categories · ${atRisk} agent${atRisk === 1 ? '' : 's'} marked at risk`}
              accent={risks && risks.totalFindings > 0 ? 'text-amber-600' : undefined} testId="kpi-open-risk-findings"
              open={behind === 'findings'} onOpen={() => toggle('findings')} hint="The agents the findings are on" />
          )
        },
        afterKpis: c => behind && <BehindPanel behind={behind} c={c} risks={risks} />,
        pipeline: c => <PipelineRail agents={c.list} />,
        risk: () => risks && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" data-testid="risk-charts">
            <div className="card p-5">
              <h2 className="font-semibold text-slate-900 mb-3">Risk findings by category</h2>
              <RiskPie data={risks.byCategory.map(x => ({ label: x.label, count: x.count, color: CATEGORY_COLORS[x.category] || '#6b7280' }))} />
            </div>
            <div className="card p-5">
              <h2 className="font-semibold text-slate-900 mb-3">Risk findings by category and severity <InfoTip term="severity" /></h2>
              <RiskHeatmap rows={risks.heatmap} severities={risks.severities} />
            </div>
          </div>
        ),
        mix: c => (
          <div className="card p-5" data-testid="ai-type-mix">
            <h2 className="font-semibold text-slate-900 mb-3">Agents by AI type</h2>
            <BarChart label="Agents by AI type" format={n => `${n} agent${n === 1 ? '' : 's'}`}
              data={Object.entries(c.running.reduce((acc, a) => { acc[a.aiType] = (acc[a.aiType] || 0) + 1; return acc }, {} as Record<string, number>)).map(([label, value]) => ({ label, value }))} />
          </div>
        ),
        end: c => <AttentionLists c={c} attention={attention} />,
      }} />
    </div>
  )
}

// The agents behind the Total agents card or the Open risk findings card, each a link to the agent.
function BehindPanel({ behind, c, risks }: { behind: Behind; c: UnitContext; risks: RiskSummary | null }) {
  const pipeline = c.running.filter(isPipeline), atRisk = c.running.filter(a => a.atRisk)
  return (
    <div className="card p-5 space-y-2" data-testid="tile-behind">
      {behind === 'agents' && <>
        <h2 className="font-semibold text-slate-900">The {pipeline.length} agent{pipeline.length === 1 ? '' : 's'} in the pipeline</h2>
        <p className="text-[13px] text-slate-700">{c.running.length} agents = {c.running.length - pipeline.length} in Production + {pipeline.length} in the pipeline ({['Ideation', 'Development', 'Testing'].map(st => `${pipeline.filter(a => a.stage === st).length} in ${st}`).join(' + ')}).</p>
        <AgentLines tab="governance" rows={pipeline.map(a => ({ id: a.id, name: a.name, note: a.stage }))} empty="No agent is waiting to go live." />
      </>}
      {behind === 'findings' && risks && <>
        <h2 className="font-semibold text-slate-900">The {risks.totalFindings} open risk finding{risks.totalFindings === 1 ? '' : 's'}</h2>
        <p className="text-[13px] text-slate-700">{risks.storedFindings ?? 0} finding{risks.storedFindings === 1 ? '' : 's'} from the risk scan and from people, on the agents below, + {risks.financialFindings ?? 0} cost and spend finding{risks.financialFindings === 1 ? '' : 's'} (listed on each agent's Risk tab) = <b>{risks.totalFindings}</b>.</p>
        <AgentLines tab="risk" rows={(risks.byAgent || []).map(r => ({ id: r.agentId, name: r.name, note: `${r.count} finding${r.count === 1 ? '' : 's'}, worst is ${r.worst}` }))} empty="No finding from the risk scan or from people is open." />
        <h3 className="pt-2 text-[13px] font-semibold text-slate-900">{atRisk.length} agent{atRisk.length === 1 ? '' : 's'} marked at risk</h3>
        <p className="text-[13px] text-slate-700">An agent counts here when a person marked it at risk on its record.</p>
        <AgentLines tab="risk" rows={atRisk.map(a => ({ id: a.id, name: a.name, note: a.riskNote || 'no note given' }))} empty="No agent is marked at risk." />
      </>}
    </div>
  )
}

function AgentLines({ rows, tab, empty }: { rows: { id: string; name: string; note: string }[]; tab?: string; empty?: string }) {
  if (!rows.length) return <p className="text-[13px] text-slate-600">{empty || 'None.'}</p>
  return (
    <ul className="grid grid-cols-1 md:grid-cols-2 gap-x-6 text-[13px]">
      {rows.map(r => (
        <li key={r.id} className="flex justify-between gap-3 border-b border-slate-100 py-1">
          <Link to={`/agents/${r.id}${tab ? `?tab=${tab}` : ''}`} className="font-medium text-zen-700 hover:underline">{r.name}</Link>
          <span className="text-right text-slate-600">{r.note}</span>
        </li>
      ))}
    </ul>
  )
}

// One tile per stage. The count opens the agent list on that stage.
function PipelineRail({ agents }: { agents: RegistryAgent[] }) {
  return (
    <div className="card p-5" data-testid="pipeline-rail">
      <h2 className="font-semibold text-slate-900 mb-3">Agents by stage <InfoTip term="stage" /></h2>
      <div className="grid grid-cols-5 gap-2">
        {STAGES.map(stage => {
          const inStage = agents.filter(a => a.stage === stage)
          return (
            <div key={stage} className="text-center p-3 rounded-xl" style={{ backgroundColor: STAGE_COLORS[stage] + '15' }}>
              <Link to={`/agents?stage=${stage}`} className="block rounded-lg hover:bg-white/60" data-testid={`stage-${stage}`} title={`Open the ${inStage.length} agent${inStage.length === 1 ? '' : 's'} in ${stage}`}>
                <div className="text-2xl font-bold" style={{ color: STAGE_COLORS[stage] }}>{inStage.length}</div>
                <div className="text-xs text-slate-700 mb-2">{stage}</div>
              </Link>
              <div className="space-y-1">
                {inStage.slice(0, 3).map(a => (
                  <Link key={a.id} to={`/agents/${a.id}`} title={`${a.name}: open`}
                    className="block text-xs bg-white/70 rounded px-1 py-0.5 truncate text-slate-700 hover:bg-white hover:text-slate-900">{a.name}</Link>
                ))}
                {inStage.length > 3 && <div className="text-[12px] text-slate-600" title={inStage.slice(3).map(a => a.name).join('\n')}>+{inStage.length - 3} more</div>}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// Agents of the chosen unit that look idle, ownerless or stuck, and the ones marked at risk.
function AttentionLists({ c, attention }: { c: UnitContext; attention: PortfolioAttention | null }) {
  const ids = new Set(c.list.map(a => a.id))
  const atRisk = c.running.filter(a => a.atRisk)
  const rows = !attention ? [] : [
    ...attention.silent.map(x => ({ ...x, label: `Silent in Production (no call for ${attention.silentDays}+ days)` })),
    ...attention.runningAfterRetirement.map(x => ({ ...x, label: 'Retired but still called' })),
    ...attention.callsRetired.map(x => ({ ...x, label: 'Declared to call a retired agent' })),
    ...attention.stalled.map(x => ({ ...x, label: `Stalled in ${x.stage}` })),
    ...attention.stopWaiting.map(x => ({ ...x, label: 'Stop requested, the owner has not acknowledged' })),
    ...attention.ownerless.map(x => ({ ...x, label: 'No owner' })),
  ].filter(x => ids.has(x.agentId))
  return (
    <>
      {rows.length > 0 && (
        <div className="bg-amber-50 rounded-2xl border border-amber-200 p-5" data-testid="lifecycle-attention">
          <h2 className="font-semibold text-amber-900 mb-1">Agents that look idle, ownerless or stuck</h2>
          <p className="text-[13px] text-amber-900/80 mb-2">From the records and from the usage the registry reads from Phoenix. A silent Production agent may be idle, broken or replaced. A retired agent with calls is still in use. An agent without an owner has nobody to answer for it.</p>
          {rows.map((x, i) => (
            <div key={`${x.agentId}-${i}`} className="flex items-start gap-3 py-1.5">
              <div className="w-2 h-2 rounded-full bg-amber-500 mt-2" />
              <div>
                <Link to={`/agents/${x.agentId}`} className="font-medium text-slate-900 hover:text-zen-700">{x.name}</Link>
                <span className="ml-2 text-[12px] font-semibold text-amber-800">{x.label}</span>
                <div className="text-sm text-slate-700">{x.text}</div>
              </div>
            </div>
          ))}
        </div>
      )}
      {atRisk.length > 0 && (
        <div className="bg-rose-50 rounded-2xl border border-rose-200 p-5">
          <h2 className="font-semibold text-rose-800 mb-3">Agents at risk</h2>
          {atRisk.map(a => (
            <div key={a.id} className="flex items-start gap-3 py-2">
              <div className="w-2 h-2 rounded-full bg-rose-500 mt-2" />
              <div>
                <Link to={`/agents/${a.id}?tab=risk`} className="font-medium text-slate-900 hover:text-zen-700">{a.name}</Link>
                <div className="text-sm text-rose-600">{a.riskNote || 'Marked at risk, no note given'}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  )
}
