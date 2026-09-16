import { useState, useEffect } from 'react'
import {
  createAgent, getAgents, getGraphV2, getReconstructedGraph, getPhoenixProjects, updateAgent,
  getAgentRisks, scanAgentRisks, getAgentEconomics,
  type Agent, type GraphV2Response, type ReconstructedGraph, type RiskFinding, type AgentEconomics,
} from '../services/api'
import NetworkGraph from './NetworkGraph'

const SEVERITY_PILL: Record<string, string> = {
  LOW: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  MEDIUM: 'bg-amber-50 text-amber-700 ring-amber-200',
  HIGH: 'bg-orange-50 text-orange-700 ring-orange-200',
  CRITICAL: 'bg-rose-50 text-rose-700 ring-rose-200',
}

function fmtCents(c: number): string {
  const n = c / 100
  if (Math.abs(n) >= 1000) return '$' + Math.round(n / 1000) + 'K'
  return '$' + n.toFixed(n % 1 === 0 ? 0 : 2)
}

// Risk findings + revenue/expenditure for one agent — real signals (governance
// gates, reconstructed-trace error rate, waste/cost-anomaly rows), not a
// placeholder. Lives in the Overview tab since both are "current state of
// this app", same as the fields above it.
function RisksAndEconomicsPanel({ agentId }: { agentId: string }) {
  const [findings, setFindings] = useState<RiskFinding[] | null>(null)
  const [econ, setEcon] = useState<AgentEconomics | null>(null)
  const [scanning, setScanning] = useState(false)

  async function load() {
    const [riskRes, econRes] = await Promise.all([
      getAgentRisks(agentId).catch(() => null),
      getAgentEconomics(agentId).catch(() => null),
    ])
    setFindings(riskRes?.data.findings ?? [])
    setEcon(econRes?.data ?? null)
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

  return (
    <div className="mt-4 border-t border-gray-100 pt-4 space-y-4">
      {econ && (
        <div>
          <span className="text-xs text-gray-400">Economics</span>
          <div className="grid grid-cols-3 gap-3 mt-1">
            <div className="text-center rounded-lg bg-gray-50 py-2">
              <div className="text-sm font-bold text-emerald-600">{fmtCents(econ.revenueCents)}</div>
              <div className="text-[10px] text-gray-400 uppercase">Revenue</div>
            </div>
            <div className="text-center rounded-lg bg-gray-50 py-2">
              <div className="text-sm font-bold text-rose-600">{fmtCents(econ.expenditureCents)}</div>
              <div className="text-[10px] text-gray-400 uppercase">Expenditure</div>
            </div>
            <div className="text-center rounded-lg bg-gray-50 py-2">
              <div className={`text-sm font-bold ${econ.netCents >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>{fmtCents(econ.netCents)}</div>
              <div className="text-[10px] text-gray-400 uppercase">Net</div>
            </div>
          </div>
          <p className="text-[11px] text-gray-400 mt-1">Token cost {fmtCents(econ.tokenCostCents)} + estimated infra {fmtCents(econ.estimatedInfraCostCents)}</p>
        </div>
      )}

      <div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400">Risk findings</span>
          <button onClick={scan} disabled={scanning} className="text-xs text-teal-600 hover:text-teal-700 disabled:opacity-50">
            {scanning ? 'Scanning…' : '🔍 Scan now'}
          </button>
        </div>
        {findings === null ? (
          <p className="text-xs text-gray-400 mt-1">Loading…</p>
        ) : findings.length === 0 ? (
          <p className="text-xs text-gray-400 mt-1">No open findings.</p>
        ) : (
          <div className="mt-1 space-y-1">
            {findings.map((f, i) => (
              <div key={f.id || i} className="flex items-start gap-2 text-xs">
                <span className={`px-1.5 py-0.5 rounded-full ring-1 flex-shrink-0 ${SEVERITY_PILL[f.severity] || 'bg-gray-50 text-gray-600 ring-gray-200'}`}>{f.severity}</span>
                <div>
                  <span className="text-gray-700 font-medium">{f.title}</span>
                  <span className="text-gray-400"> · {f.category.replace('_', ' ')}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

interface Props {
  agentId: string
  onClose: () => void
  onSaved?: () => void
}

const AI_TYPES = [
  'Autonomous Agent', 'Copilot / Assistant', 'Predictive / ML Model',
  'Generative AI Feature', 'Conversational AI / Chatbot', 'Computer Vision Model',
]
const STAGES = ['Ideation', 'Development', 'Testing', 'Production', 'Deprecated']
const DEPTS = ['dept-finance', 'dept-cx', 'dept-hr', 'dept-it-ops', 'dept-sales', 'dept-marketing', 'dept-legal', 'dept-supply-chain', 'dept-engineering']

interface FormState {
  name: string
  dept: string
  owner: string
  stage: string
  ai_type: string
  description: string
  business_outcome: string
  value_amount: number
  hours_saved_monthly: number
  model_name: string
  api_endpoint: string
  phoenix_project: string
  phoenix_endpoint_mode: 'common' | 'custom'
  phoenix_endpoint: string
  enterprise_systems: string
  databases: string
  knowledge_bases: string
  mcp_servers: string
  calls: string
  consumers: string
}

const INITIAL_FORM: FormState = {
  name: '', dept: 'dept-finance', owner: '', stage: 'Ideation',
  ai_type: 'Autonomous Agent', description: '', business_outcome: '',
  value_amount: 0, hours_saved_monthly: 0, model_name: 'GPT-5', api_endpoint: '',
  phoenix_project: '', phoenix_endpoint_mode: 'common', phoenix_endpoint: '',
  enterprise_systems: '', databases: '', knowledge_bases: '', mcp_servers: '',
  calls: '', consumers: '',
}

// Shared by the onboarding form and the "link an existing agent" control in
// the Diagram tab — a text input backed by a <datalist> of REAL Phoenix
// project names (discovered live, not typed blind), with manual entry still
// allowed since a not-yet-instrumented app has no project to discover yet.
function PhoenixProjectPicker({ value, onChange, id }: { value: string; onChange: (v: string) => void; id: string }) {
  const [projects, setProjects] = useState<string[] | null>(null)
  const [reachable, setReachable] = useState(true)
  const [loading, setLoading] = useState(false)

  async function discover() {
    setLoading(true)
    try {
      const resp = await getPhoenixProjects()
      setReachable(resp.data.reachable)
      setProjects(resp.data.projects)
    } catch {
      setReachable(false)
      setProjects([])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div className="flex gap-2">
        <input
          className="input"
          list={id}
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder="e.g. retail-onboarding"
        />
        <button type="button" onClick={discover} disabled={loading} className="btn-secondary btn-sm whitespace-nowrap">
          {loading ? 'Looking…' : '🔍 Discover'}
        </button>
      </div>
      {projects !== null && (
        <datalist id={id}>
          {projects.map(p => <option key={p} value={p} />)}
        </datalist>
      )}
      {projects !== null && !reachable && (
        <p className="text-xs text-rose-600 mt-1">Could not reach Phoenix — enter the project name manually if you know it.</p>
      )}
      {projects !== null && reachable && projects.length === 0 && (
        <p className="text-xs text-gray-400 mt-1">Phoenix has no projects yet.</p>
      )}
      {projects !== null && reachable && projects.length > 0 && (
        <p className="text-xs text-gray-400 mt-1">{projects.length} project(s) found — pick from the list or type your own.</p>
      )}
    </div>
  )
}

function OnboardingForm({ onClose, onSaved }: { onClose: () => void; onSaved?: () => void }) {
  const [form, setForm] = useState<FormState>(INITIAL_FORM)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm(prev => ({ ...prev, [key]: value }))
  }

  function splitTags(value: string): string[] {
    return value.split(',').map(s => s.trim()).filter(Boolean)
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!form.name.trim()) { setError('Name is required'); return }
    setSaving(true)
    setError(null)
    try {
      await createAgent({
        name: form.name.trim(),
        dept: form.dept,
        owner: form.owner,
        stage: form.stage,
        ai_type: form.ai_type,
        description: form.description,
        business_outcome: form.business_outcome,
        value_amount: Number(form.value_amount) || 0,
        hours_saved_monthly: Number(form.hours_saved_monthly) || 0,
        model_name: form.model_name,
        api_endpoint: form.api_endpoint,
        phoenix_project: form.phoenix_project.trim(),
        phoenix_endpoint: form.phoenix_endpoint_mode === 'custom' ? form.phoenix_endpoint.trim() : '',
        enterprise_systems: splitTags(form.enterprise_systems),
        databases: splitTags(form.databases),
        knowledge_bases: splitTags(form.knowledge_bases),
        mcp_servers: splitTags(form.mcp_servers),
        calls: splitTags(form.calls),
        consumers: splitTags(form.consumers),
      } as any)
      onSaved?.()
      onClose()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setError(typeof detail === 'string' ? detail : JSON.stringify(detail) || e.message || 'Failed to register agent')
    } finally {
      setSaving(false)
    }
  }

  const label = 'block text-xs font-semibold uppercase text-gray-500 mb-1 tracking-wide'

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl border border-gray-100 shadow-card-hover max-w-3xl w-full max-h-[90vh] overflow-y-auto animate-slide-up" onClick={e => e.stopPropagation()}>
        <form onSubmit={submit} className="p-6 space-y-4">
          <div className="flex justify-between items-start mb-2">
            <div>
              <h2 className="text-xl font-bold text-gray-900">Register a new AI application</h2>
              <p className="text-sm text-gray-500 mt-0.5">It enters the registry at the Ideation stage with all governance gates pending.</p>
            </div>
            <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-700 text-2xl leading-none">&times;</button>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={label}>Name *</label>
              <input className="input" value={form.name} onChange={e => set('name', e.target.value)} placeholder="e.g. Invoice Reconciliation Agent" required />
            </div>
            <div>
              <label className={label}>Owner</label>
              <input className="input" value={form.owner} onChange={e => set('owner', e.target.value)} placeholder="e.g. Finance Ops" />
            </div>
            <div>
              <label className={label}>Department</label>
              <select className="input" value={form.dept} onChange={e => set('dept', e.target.value)}>
                {DEPTS.map(d => <option key={d} value={d}>{d.replace('dept-', '')}</option>)}
              </select>
            </div>
            <div>
              <label className={label}>Lifecycle stage</label>
              <select className="input" value={form.stage} onChange={e => set('stage', e.target.value)}>
                {STAGES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className={label}>AI type</label>
              <select className="input" value={form.ai_type} onChange={e => set('ai_type', e.target.value)}>
                {AI_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className={label}>Model</label>
              <input className="input" value={form.model_name} onChange={e => set('model_name', e.target.value)} />
            </div>
          </div>

          <div>
            <label className={label}>Description</label>
            <textarea className="input" rows={2} value={form.description} onChange={e => set('description', e.target.value)} placeholder="What does this agent do?" />
          </div>
          <div>
            <label className={label}>Business outcome</label>
            <input className="input" value={form.business_outcome} onChange={e => set('business_outcome', e.target.value)} placeholder="e.g. 40% faster invoice processing" />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={label}>Value ($/mo)</label>
              <input type="number" className="input" value={form.value_amount} onChange={e => set('value_amount', Number(e.target.value))} />
            </div>
            <div>
              <label className={label}>Hours saved / month</label>
              <input type="number" className="input" value={form.hours_saved_monthly} onChange={e => set('hours_saved_monthly', Number(e.target.value))} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={label}>Enterprise systems (comma-separated)</label>
              <input className="input" value={form.enterprise_systems} onChange={e => set('enterprise_systems', e.target.value)} placeholder="SAP, Salesforce" />
            </div>
            <div>
              <label className={label}>Databases (comma-separated)</label>
              <input className="input" value={form.databases} onChange={e => set('databases', e.target.value)} placeholder="Snowflake, Databricks" />
            </div>
            <div>
              <label className={label}>Knowledge bases (comma-separated)</label>
              <input className="input" value={form.knowledge_bases} onChange={e => set('knowledge_bases', e.target.value)} placeholder="AP Policy KB" />
            </div>
            <div>
              <label className={label}>MCP servers (comma-separated)</label>
              <input className="input" value={form.mcp_servers} onChange={e => set('mcp_servers', e.target.value)} placeholder="SAP MCP Server" />
            </div>
            <div>
              <label className={label}>Calls agents (comma-separated)</label>
              <input className="input" value={form.calls} onChange={e => set('calls', e.target.value)} placeholder="other agent ids" />
            </div>
            <div>
              <label className={label}>Consumers (comma-separated)</label>
              <input className="input" value={form.consumers} onChange={e => set('consumers', e.target.value)} placeholder="Dashboards, queues" />
            </div>
          </div>

          <div>
            <label className={label}>API endpoint</label>
            <input className="input" value={form.api_endpoint} onChange={e => set('api_endpoint', e.target.value)} placeholder="https://…" />
          </div>

          <div className="rounded-xl border border-gray-100 bg-gray-50/60 p-3 space-y-3">
            <label className={label}>Tracing endpoint (optional — links real traces for the Diagram tab)</label>
            <select className="input" value={form.phoenix_endpoint_mode} onChange={e => set('phoenix_endpoint_mode', e.target.value as 'common' | 'custom')}>
              <option value="common">Use common endpoint (configured in Settings)</option>
              <option value="custom">Custom endpoint for this app</option>
            </select>
            {form.phoenix_endpoint_mode === 'custom' && (
              <div>
                <label className={label}>Custom Phoenix/OTel endpoint URL</label>
                <input className="input" value={form.phoenix_endpoint} onChange={e => set('phoenix_endpoint', e.target.value)} placeholder="https://your-phoenix-instance.example.com" />
                <p className="text-xs text-gray-400 mt-1">This app's own tracing backend, if it isn't on the shared org Phoenix instance.</p>
              </div>
            )}
            <div>
              <label className={label}>Phoenix project name</label>
              <PhoenixProjectPicker id="onboard-phoenix-projects" value={form.phoenix_project} onChange={v => set('phoenix_project', v)} />
              {form.phoenix_endpoint_mode === 'custom' && (
                <p className="text-xs text-gray-400 mt-1">Discovery above always checks the common endpoint — for a custom endpoint, type the project name directly.</p>
              )}
            </div>
          </div>

          {error && <div className="rounded-xl bg-rose-50 border border-rose-200 px-3 py-2 text-xs text-rose-700">{error}</div>}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="btn-secondary btn-sm">
              Cancel
            </button>
            <button type="submit" disabled={saving} className="btn-primary btn-sm">
              {saving ? 'Registering…' : 'Register application'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Diagram tab — reconstructed from real Phoenix traces, not the agent's
// hand-declared calls/consumers fields (that's the Overview tab / the
// separate /graph endpoint). Four distinct states, never collapsed into one
// generic "no data": not linked to a project, Phoenix unreachable, linked
// but zero traces seen yet, and a real reconstructed diagram. ──────────────
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
        <NetworkGraph nodes={nwNodes} edges={nwEdges} width={520} height={360} />
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

export default function AgentDetailModal({ agentId, onClose, onSaved }: Props) {
  const isOnboarding = agentId === 'new'
  const [agent, setAgent] = useState<Agent | null>(null)
  const [graph, setGraph] = useState<GraphV2Response | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<'overview' | 'diagram'>('overview')

  useEffect(() => {
    if (isOnboarding) { setLoading(false); return }
    setTab('overview')
    async function load() {
      try {
        const [agentRes, graphRes] = await Promise.all([
          getAgents(1, 100, { q: undefined }),
          getGraphV2()
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
  }, [agentId, isOnboarding])

  if (isOnboarding) return <OnboardingForm onClose={onClose} onSaved={onSaved} />
  if (loading) return null
  if (!agent) return null

  const deps = graph ? graph.edges.filter(e => e.from === agentId || e.to === agentId) : []

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl border border-gray-100 shadow-card-hover max-w-2xl w-full max-h-[90vh] overflow-y-auto animate-slide-up" onClick={e => e.stopPropagation()}>
        <div className="p-6">
          <div className="flex justify-between items-start mb-3">
            <div>
              <h2 className="text-xl font-bold text-gray-900">{agent.name}</h2>
              <p className="text-sm text-gray-500 mt-0.5">{agent.aiType} · {agent.dept || 'No department'} · {agent.stage}</p>
            </div>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-2xl leading-none">&times;</button>
          </div>

          {/* Tabs */}
          <div className="flex gap-1 border-b border-gray-100 mb-4">
            {(['overview', 'diagram'] as const).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                  tab === t ? 'border-teal-600 text-teal-700' : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                {t === 'overview' ? 'Overview' : 'Diagram'}
              </button>
            ))}
          </div>

          {tab === 'diagram' && (
            <DiagramTab agent={agent} onLinked={() => setAgent(prev => prev ? { ...prev } : prev)} />
          )}

          {tab === 'overview' && (
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
            <div>
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

          {agent.reviews && Object.keys(agent.reviews).length > 0 && (
            <div className="mt-4">
              <span className="text-xs text-gray-400">Governance</span>
              <div className="flex gap-2 mt-1">
                {Object.entries(agent.reviews).map(([gate, status]) => (
                  <span key={gate} className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-700">
                    {gate}: {status}
                  </span>
                ))}
              </div>
            </div>
          )}

          <RisksAndEconomicsPanel agentId={agent.id} />
          </>
          )}
        </div>
      </div>
    </div>
  )
}
