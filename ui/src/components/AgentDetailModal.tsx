import { useState, useEffect } from 'react'
import { createAgent, getAgents, getGraphV2, type Agent, type GraphV2Response } from '../services/api'

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
  enterprise_systems: '', databases: '', knowledge_bases: '', mcp_servers: '',
  calls: '', consumers: '',
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

  const input = 'w-full border rounded px-3 py-2 text-sm bg-gray-800 border-gray-600 text-gray-100'
  const label = 'block text-xs font-semibold uppercase text-gray-500 mb-1'

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-gray-900 rounded-lg border border-gray-700 max-w-3xl w-full max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <form onSubmit={submit} className="p-6 space-y-4">
          <div className="flex justify-between items-start mb-2">
            <div>
              <h2 className="text-xl font-bold">Register a new AI application</h2>
              <p className="text-sm text-gray-400">It enters the registry at the Ideation stage with all governance gates pending.</p>
            </div>
            <button type="button" onClick={onClose} className="text-gray-400 hover:text-white text-2xl leading-none">&times;</button>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={label}>Name *</label>
              <input className={input} value={form.name} onChange={e => set('name', e.target.value)} placeholder="e.g. Invoice Reconciliation Agent" required />
            </div>
            <div>
              <label className={label}>Owner</label>
              <input className={input} value={form.owner} onChange={e => set('owner', e.target.value)} placeholder="e.g. Finance Ops" />
            </div>
            <div>
              <label className={label}>Department</label>
              <select className={input} value={form.dept} onChange={e => set('dept', e.target.value)}>
                {DEPTS.map(d => <option key={d} value={d}>{d.replace('dept-', '')}</option>)}
              </select>
            </div>
            <div>
              <label className={label}>Lifecycle stage</label>
              <select className={input} value={form.stage} onChange={e => set('stage', e.target.value)}>
                {STAGES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className={label}>AI type</label>
              <select className={input} value={form.ai_type} onChange={e => set('ai_type', e.target.value)}>
                {AI_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className={label}>Model</label>
              <input className={input} value={form.model_name} onChange={e => set('model_name', e.target.value)} />
            </div>
          </div>

          <div>
            <label className={label}>Description</label>
            <textarea className={input} rows={2} value={form.description} onChange={e => set('description', e.target.value)} placeholder="What does this agent do?" />
          </div>
          <div>
            <label className={label}>Business outcome</label>
            <input className={input} value={form.business_outcome} onChange={e => set('business_outcome', e.target.value)} placeholder="e.g. 40% faster invoice processing" />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={label}>Value ($/mo)</label>
              <input type="number" className={input} value={form.value_amount} onChange={e => set('value_amount', Number(e.target.value))} />
            </div>
            <div>
              <label className={label}>Hours saved / month</label>
              <input type="number" className={input} value={form.hours_saved_monthly} onChange={e => set('hours_saved_monthly', Number(e.target.value))} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={label}>Enterprise systems (comma-separated)</label>
              <input className={input} value={form.enterprise_systems} onChange={e => set('enterprise_systems', e.target.value)} placeholder="SAP, Salesforce" />
            </div>
            <div>
              <label className={label}>Databases (comma-separated)</label>
              <input className={input} value={form.databases} onChange={e => set('databases', e.target.value)} placeholder="Snowflake, Databricks" />
            </div>
            <div>
              <label className={label}>Knowledge bases (comma-separated)</label>
              <input className={input} value={form.knowledge_bases} onChange={e => set('knowledge_bases', e.target.value)} placeholder="AP Policy KB" />
            </div>
            <div>
              <label className={label}>MCP servers (comma-separated)</label>
              <input className={input} value={form.mcp_servers} onChange={e => set('mcp_servers', e.target.value)} placeholder="SAP MCP Server" />
            </div>
            <div>
              <label className={label}>Calls agents (comma-separated)</label>
              <input className={input} value={form.calls} onChange={e => set('calls', e.target.value)} placeholder="other agent ids" />
            </div>
            <div>
              <label className={label}>Consumers (comma-separated)</label>
              <input className={input} value={form.consumers} onChange={e => set('consumers', e.target.value)} placeholder="Dashboards, queues" />
            </div>
          </div>

          <div>
            <label className={label}>API endpoint</label>
            <input className={input} value={form.api_endpoint} onChange={e => set('api_endpoint', e.target.value)} placeholder="https://…" />
          </div>

          {error && <div className="rounded bg-red-900/40 border border-red-700 px-3 py-2 text-xs text-red-300">{error}</div>}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="rounded border border-gray-600 px-4 py-2 text-sm text-gray-300 hover:bg-gray-800">
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="rounded bg-teal-600 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-700 disabled:opacity-50"
            >
              {saving ? 'Registering…' : 'Register application'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function AgentDetailModal({ agentId, onClose, onSaved }: Props) {
  const isOnboarding = agentId === 'new'
  const [agent, setAgent] = useState<Agent | null>(null)
  const [graph, setGraph] = useState<GraphV2Response | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (isOnboarding) { setLoading(false); return }
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
                  const otherId = e.from === agentId ? e.to : e.from
                  const otherName = graph?.nodes.find(n => n.id === otherId)?.name ?? otherId
                  const typeLabel = e.type === 'CALLS' ? 'calls' : e.type === 'CONSUMED_BY' ? 'feeds' : e.type === 'ACCESSES' ? 'accesses' : e.type === 'USES_KB' ? 'knowledge' : 'tool'
                  const direction = e.from === agentId ? typeLabel : 'needed by'
                  return (
                    <div key={i} className="text-xs flex gap-2">
                      <span className="text-gray-500">{direction}</span>
                      <span className="font-mono text-teal-400">{otherName}</span>
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