import { useState } from 'react'
import { createAgent } from '../services/api'
import PhoenixProjectPicker from './PhoenixProjectPicker'

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
  context_md: string
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
  context_md: '',
  enterprise_systems: '', databases: '', knowledge_bases: '', mcp_servers: '',
  calls: '', consumers: '',
}

export default function OnboardingModal({ onClose, onSaved }: { onClose: () => void; onSaved?: () => void }) {
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
        context_md: form.context_md.trim(),
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

          <div>
            <label className={label}>Context notes (Markdown, optional)</label>
            <textarea
              className="input font-mono text-xs"
              rows={5}
              value={form.context_md}
              onChange={e => set('context_md', e.target.value)}
              placeholder={'# What this app does\n\nArchitecture notes, gotchas, runbook links — anything future readers of this registry entry should know, in your own words.'}
            />
            <p className="text-xs text-gray-400 mt-1">Shown as-is on the agent's own page. Not required to register.</p>
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
