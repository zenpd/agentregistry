import { useEffect, useRef, useState } from 'react'
import { BadgeCheck, Link2, Loader2 } from 'lucide-react'
import { createAgent, findSimilarAgents, type SimilarAgent } from '../services/api'
import { findApp, prefillFromUrl, type Prefill, type UrlPrefill } from '../services/ops/discovery'
import PhoenixProjectPicker from './PhoenixProjectPicker'
import InfoTip from './InfoTip'
import DraftCoach from './DraftCoach'
import ErrorNote from './ErrorNote'
import type { GlossaryKey } from '../lib/glossary'

export const AI_TYPES = [
  'Autonomous Agent', 'Copilot / Assistant', 'Predictive / ML Model',
  'Generative AI Feature', 'Conversational AI / Chatbot', 'Computer Vision Model',
]
const STAGES = ['Ideation', 'Development', 'Testing', 'Production', 'Deprecated']
export const DEPTS = ['dept-finance', 'dept-cx', 'dept-hr', 'dept-it-ops', 'dept-sales', 'dept-marketing', 'dept-legal', 'dept-supply-chain', 'dept-engineering']

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
  capabilities: string
  inputs: string
  outputs: string
  sla: string
  rate_limit: string
  owner_contact: string
  reuse_justification: string
}

// Must match MIN_REUSE_JUSTIFICATION_CHARS in api/routers/registry.py.
const MIN_JUSTIFICATION = 20

const INITIAL_FORM: FormState = {
  name: '', dept: 'dept-finance', owner: '', stage: 'Ideation',
  ai_type: 'Autonomous Agent', description: '', business_outcome: '',
  value_amount: 0, hours_saved_monthly: 0, model_name: '', api_endpoint: '',
  phoenix_project: '', phoenix_endpoint_mode: 'common', phoenix_endpoint: '',
  context_md: '',
  enterprise_systems: '', databases: '', knowledge_bases: '', mcp_servers: '',
  calls: '', consumers: '',
  capabilities: '', inputs: '', outputs: '', sla: '', rate_limit: '', owner_contact: '', reuse_justification: '',
}

const LIST_LINES = new Set(['capabilities', 'inputs', 'outputs'])
const LIST_TAGS = new Set(['mcp_servers', 'enterprise_systems', 'databases', 'knowledge_bases', 'calls', 'consumers'])

// Prefill values arrive keyed like the form; lists become the form's text boxes.
function applyFields(base: FormState, fields: Prefill['fields']): FormState {
  const next: Record<string, unknown> = { ...base }
  for (const [key, value] of Object.entries(fields)) {
    if (!(key in INITIAL_FORM) || value == null || value === '') continue
    next[key] = Array.isArray(value) ? value.join(LIST_LINES.has(key) ? '\n' : ', ') : value
  }
  return next as unknown as FormState
}

interface Props {
  onClose: () => void
  onSaved?: (agentId: string) => void
  // A Phoenix project whose app should be looked for at the address pattern from Settings.
  findAppFor?: string
  // Starting values with where each came from (a Phoenix project or an app address).
  prefill?: Prefill
  title?: string
}

export default function OnboardingModal({ onClose, onSaved, prefill, title, findAppFor }: Props) {
  const [form, setForm] = useState<FormState>(() =>
    prefill ? applyFields(INITIAL_FORM, prefill.fields) : INITIAL_FORM)
  // Where each prefilled field came from; a field you edit stops being attributed.
  const [sources, setSources] = useState<Record<string, string>>(prefill?.sources ?? {})
  const [address, setAddress] = useState('')
  const [looking, setLooking] = useState(false)
  const [lookup, setLookup] = useState<UrlPrefill | null>(null)
  const [lookupError, setLookupError] = useState<{ message: string; hint?: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [similar, setSimilar] = useState<SimilarAgent[]>([])

  // What the person has typed or has chosen: a lookup that finishes later must not replace it.
  const touched = useRef(new Set<string>())
  const addressTouched = useRef(false)
  const formRef = useRef(form)
  formRef.current = form
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    touched.current.add(key as string)
    setForm(prev => ({ ...prev, [key]: value }))
    setSources(prev => {
      if (!(key in prev)) return prev
      const { [key]: _gone, ...rest } = prev
      return rest
    })
  }

  // Fills what is still empty from what the app says about itself (never overwrites typing).
  // `auto` is the lookup made from the project name; it never replaces the address either.
  function applyLookup(r: UrlPrefill, auto = false) {
    setLookup(r)
    const fresh: Record<string, string | string[]> = {}
    for (const [key, value] of Object.entries(r.fields ?? {})) {
      if (touched.current.has(key)) continue
      const current = (formRef.current as unknown as Record<string, unknown>)[key]
      const empty = current == null || current === ''
      if (empty || (key === 'api_endpoint' && !auto)) fresh[key] = value
    }
    setForm(prev => applyFields(prev, fresh))
    setSources(s => ({ ...s, ...Object.fromEntries(Object.keys(fresh).map(k => [k, r.sources?.[k] ?? 'The app'])) }))
  }

  // Registering a discovered project: look for its app at the saved address pattern, once.
  const [autoNote, setAutoNote] = useState<string | null>(null)
  const lookedUpFor = useRef<string | null>(null)
  useEffect(() => {
    // Once per project, even when development mode runs this effect twice.
    if (!findAppFor || lookedUpFor.current === findAppFor) return
    lookedUpFor.current = findAppFor
    setLooking(true)
    findApp(findAppFor)
      .then(({ data }) => {
        if (!mounted.current || addressTouched.current) return   // the person has taken over
        if (data.found && data.ok) {
          setAddress(prev => prev || (data.base ?? ''))
          applyLookup(data as UrlPrefill, true)
          setAutoNote('Found the app from the project name. Check the address is the right one.')
        } else if (data.reason === 'no_answer') {
          setAutoNote('No app answered at the address pattern for this project. Paste its address to fill the rest.')
        }
      })
      .catch(() => { /* the address box still works by hand */ })
      .finally(() => { if (mounted.current) setLooking(false) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [findAppFor])

  async function fillFromAddress() {
    if (!address.trim()) return
    addressTouched.current = true
    setLooking(true)
    setLookupError(null)
    setLookup(null)
    setAutoNote(null)
    try {
      const r = (await prefillFromUrl(address.trim())).data
      if (!r.ok) {
        setLookupError({ message: r.error || 'Could not read that address', hint: r.hint })
        return
      }
      applyLookup(r)
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setLookupError({ message: typeof detail === 'string' ? detail : 'Could not read that address' })
    } finally {
      setLooking(false)
    }
  }

  // "from Agent card" under a field that was prefilled; hidden once edited.
  const from = (key: string) => sources[key] ? <span className="ml-1.5 normal-case font-medium tracking-normal text-emerald-700" data-testid={`source-${key}`}>· from {sources[key]}</span> : null
  const tip = (term: GlossaryKey) => <InfoTip term={term} className="ml-1 -mt-0.5" />

  function splitTags(value: string): string[] {
    return value.split(',').map(s => s.trim()).filter(Boolean)
  }

  function splitLines(value: string): string[] {
    return value.split('\n').map(s => s.trim()).filter(Boolean)
  }

  // Look for agents that already do this while the team is still describing it.
  useEffect(() => {
    if (!form.name.trim() && !form.description.trim() && !form.capabilities.trim()) {
      setSimilar([])
      return
    }
    let cancelled = false
    const timer = setTimeout(() => {
      findSimilarAgents({
        name: form.name, description: form.description, business_outcome: form.business_outcome,
        capabilities: splitLines(form.capabilities), api_endpoint: form.api_endpoint,
      })
        .then(r => { if (!cancelled) setSimilar(r.data.similar) })
        .catch(() => { /* the server repeats this check on submit */ })
    }, 400)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [form.name, form.description, form.business_outcome, form.capabilities, form.api_endpoint])

  const needsReason = similar.length > 0
  const reasonShort = needsReason && form.reuse_justification.trim().length < MIN_JUSTIFICATION

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!form.name.trim()) { setError('Name is required'); return }
    if (reasonShort) {
      setError(`Similar agents already exist. Say why none of them fit (at least ${MIN_JUSTIFICATION} characters).`)
      return
    }
    setSaving(true)
    setError(null)
    try {
      const created = await createAgent({
        name: form.name.trim(),
        dept: form.dept,
        owner: form.owner,
        owner_contact: form.owner_contact.trim(),
        stage: form.stage,
        ai_type: form.ai_type,
        description: form.description,
        business_outcome: form.business_outcome,
        value_amount: Number(form.value_amount) || 0,
        hours_saved_monthly: Number(form.hours_saved_monthly) || 0,
        model_name: form.model_name,
        api_endpoint: form.api_endpoint,
        sla: form.sla.trim(),
        rate_limit: form.rate_limit.trim(),
        capabilities: splitLines(form.capabilities),
        inputs: splitLines(form.inputs),
        outputs: splitLines(form.outputs),
        reuse_justification: needsReason ? form.reuse_justification.trim() : '',
        phoenix_project: form.phoenix_project.trim(),
        phoenix_endpoint: form.phoenix_endpoint_mode === 'custom' ? form.phoenix_endpoint.trim() : '',
        context_md: form.context_md.trim(),
        enterprise_systems: splitTags(form.enterprise_systems),
        databases: splitTags(form.databases),
        knowledge_bases: splitTags(form.knowledge_bases),
        mcp_servers: splitTags(form.mcp_servers),
        calls: splitTags(form.calls),
        consumers: splitTags(form.consumers),
      })
      onSaved?.(created.data.id)
      onClose()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      if (detail?.code === 'similar_agents_exist') {
        // The server found look-alikes this form had not shown yet.
        setSimilar(detail.similar)
        setError(detail.message)
        return
      }
      // Field validation arrives as a list; show the first problem in words.
      const first = Array.isArray(detail) ? detail[0] : null
      setError(typeof detail === 'string' ? detail
        : first ? `${String(first.loc?.slice(-1)[0] ?? 'A field').replace(/_/g, ' ')}: ${String(first.msg || '').replace('Value error, ', '')}`
        : e.message || 'Failed to register agent')
    } finally {
      setSaving(false)
    }
  }

  const label = 'block text-xs font-semibold uppercase text-slate-600 mb-1 tracking-wide'

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl border border-gray-100 shadow-card-hover max-w-3xl w-full max-h-[90vh] overflow-y-auto animate-slide-up" onClick={e => e.stopPropagation()}>
        <form onSubmit={submit} className="p-6 space-y-4">
          <div className="flex justify-between items-start mb-2">
            <div>
              <h2 className="text-xl font-bold text-slate-900">{title ?? 'Register a new AI application'}</h2>
              <p className="text-sm text-slate-600 mt-0.5">It enters the registry at the Ideation stage with all governance gates pending.</p>
            </div>
            <button type="button" onClick={onClose} className="text-slate-500 hover:text-slate-700 text-2xl leading-none">&times;</button>
          </div>

          <div className="rounded-xl border border-zen-100 bg-zen-50/60 p-3 space-y-2" data-testid="prefill-url">
            <div className="flex items-center gap-1 text-xs font-bold uppercase tracking-wide text-zen-700">
              <Link2 size={13} /> Fill from the app’s address <span className="font-medium normal-case tracking-normal text-slate-500">(optional)</span>
              <InfoTip term="prefill_url" className="ml-0.5" />
            </div>
            <div className="flex gap-2">
              <input className="input flex-1" value={address} onChange={e => { addressTouched.current = true; setAddress(e.target.value) }}
                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); fillFromAddress() } }}
                placeholder="https://my-agent-be.<environment>.azurecontainerapps.io" aria-label="App address" />
              <button type="button" className="btn-secondary btn-sm shrink-0" disabled={!address.trim() || (looking && !addressTouched.current)} onClick={fillFromAddress}>
                {looking ? <><Loader2 size={14} className="animate-spin" /> Reading…</> : 'Fill form'}
              </button>
            </div>
            {autoNote && <p className="text-xs font-medium text-zen-700" data-testid="auto-note">{autoNote}</p>}
            {lookup && (
              <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-700" data-testid="prefill-result">
                <li>{lookup.card.found
                  ? <>Agent card found{lookup.card.legacyPath ? ' (old path)' : ''}{lookup.card.conformant ? '' : ` — incomplete: ${(lookup.card.problems ?? []).join(', ')}`}</>
                  : 'No agent card'}</li>
                <li>{lookup.openapi.found ? `OpenAPI: ${lookup.openapi.operations} operations` : 'No OpenAPI document'}</li>
                <li>{lookup.health.ok ? 'Health check answers' : 'No health check'}</li>
                {lookup.usedSibling && <li>Read from the API host (-be)</li>}
              </ul>
            )}
            {lookupError && <ErrorNote message={lookupError.message} hint={lookupError.hint} onDismiss={() => setLookupError(null)} />}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={label}>Name *{from('name')}</label>
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
              <div className="flex items-center mb-1"><label className={`${label} !mb-0`}>Lifecycle stage</label>{tip('stage')}</div>
              <select className="input" value={form.stage} onChange={e => set('stage', e.target.value)}>
                {STAGES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <div className="flex items-center mb-1"><label className={`${label} !mb-0`}>AI type{from('ai_type')}</label>{tip('ai_type')}</div>
              <select className="input" value={form.ai_type} onChange={e => set('ai_type', e.target.value)}>
                {AI_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className={label}>Model{from('model_name')}</label>
              <input className="input" value={form.model_name} onChange={e => set('model_name', e.target.value)}
                placeholder="Leave empty: filled in from real usage" />
            </div>
          </div>

          <div>
            <label className={label}>Description{from('description')}</label>
            <textarea className="input" rows={2} value={form.description} onChange={e => set('description', e.target.value)} placeholder="What does this agent do?" />
          </div>
          <div>
            <div className="flex items-center mb-1"><label className={`${label} !mb-0`}>Business outcome</label>{tip('business_outcome')}</div>
            <input className="input" value={form.business_outcome} onChange={e => set('business_outcome', e.target.value)} placeholder="e.g. 40% faster invoice processing" />
          </div>
          <div>
            <div className="flex items-center mb-1"><label className={`${label} !mb-0`}>Capabilities (one per line){from('capabilities')}</label>{tip('capabilities')}</div>
            <textarea className="input" rows={2} value={form.capabilities} onChange={e => set('capabilities', e.target.value)} placeholder={'e.g. Invoice matching\nPO lookup'} />
            <p className="text-xs text-slate-500 mt-1">What other teams would search for to find this agent.</p>
          </div>

          {similar.length > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 space-y-2" data-testid="similar-agents">
              <div className="text-sm font-semibold text-amber-900">
                {similar.length === 1 ? 'An agent that may already do this is' : `${similar.length} agents that may already do this are`} registered
              </div>
              <p className="text-xs text-amber-800">Consider reusing one instead. Each opens in a new tab so this form is kept.</p>
              <ul className="space-y-1.5">
                {similar.map(m => (
                  <li key={m.id} className="rounded-lg bg-white/70 px-3 py-2 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <a href={`/agents/${m.id}?tab=integrate`} target="_blank" rel="noreferrer" className="font-medium text-zen-700 hover:underline">{m.name}</a>
                      <span className="text-xs text-slate-600">{m.stage} · {m.owner}</span>
                      {m.certified && <span className="inline-flex items-center gap-0.5 text-xs text-emerald-700"><BadgeCheck size={12} /> Certified for reuse</span>}
                      <span className="ml-auto text-xs text-slate-500">{Math.round(m.score * 100)}% match</span>
                    </div>
                    <div className="text-xs text-slate-600 mt-0.5">
                      {m.sameEndpoint && 'Same API endpoint. '}
                      {m.sharedCapabilities.length > 0 && `Shared capability: ${m.sharedCapabilities.join(', ')}. `}
                      {m.matchedTerms.length > 0 && `Shared terms: ${m.matchedTerms.slice(0, 6).join(', ')}`}
                    </div>
                  </li>
                ))}
              </ul>
              <div>
                <label className={label}>Why doesn’t an existing agent fit? *</label>
                <textarea
                  className="input"
                  rows={2}
                  value={form.reuse_justification}
                  onChange={e => set('reuse_justification', e.target.value)}
                  placeholder="e.g. Needs multi-currency line matching, which the existing agent does not support"
                  aria-label="Reason for building new"
                />
                <p className={`text-xs mt-1 ${reasonShort ? 'text-amber-700' : 'text-slate-500'}`}>
                  Required to register. Stored with this agent for the governance reviewers
                  ({form.reuse_justification.trim().length}/{MIN_JUSTIFICATION} characters minimum).
                </p>
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="flex items-center mb-1"><label className={`${label} !mb-0`}>Value ($/mo)</label>{tip('declared_value')}</div>
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
              <label className={label}>Knowledge bases (comma-separated){from('knowledge_bases')}</label>
              <input className="input" value={form.knowledge_bases} onChange={e => set('knowledge_bases', e.target.value)} placeholder="AP Policy KB" />
            </div>
            <div>
              <div className="flex items-center mb-1"><label className={`${label} !mb-0`}>MCP servers and tools (comma-separated){from('mcp_servers')}</label>{tip('mcp_servers')}</div>
              <input className="input" value={form.mcp_servers} onChange={e => set('mcp_servers', e.target.value)} placeholder="SAP MCP Server" />
            </div>
            <div>
              <label className={label}>Calls agents (comma-separated){from('calls')}</label>
              <input className="input" value={form.calls} onChange={e => set('calls', e.target.value)} placeholder="other agent ids" />
            </div>
            <div>
              <div className="flex items-center mb-1"><label className={`${label} !mb-0`}>Consumers (comma-separated)</label>{tip('consumers')}</div>
              <input className="input" value={form.consumers} onChange={e => set('consumers', e.target.value)} placeholder="Dashboards, queues" />
            </div>
          </div>

          <div className="rounded-xl border border-gray-100 bg-gray-50/60 p-3 space-y-3">
            <label className={label}>How other teams call it (shown on the agent's Integrate tab)</label>
            <div>
              <div className="flex items-center mb-1"><label className={`${label} !mb-0`}>API endpoint{from('api_endpoint')}</label>{tip('api_endpoint')}</div>
              <input className="input" value={form.api_endpoint} onChange={e => set('api_endpoint', e.target.value)} placeholder="https://… or /agents/v1/…" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={label}>Inputs (one per line){from('inputs')}</label>
                <textarea className="input" rows={2} value={form.inputs} onChange={e => set('inputs', e.target.value)} placeholder="Vendor invoice (PDF)" />
              </div>
              <div>
                <label className={label}>Outputs (one per line){from('outputs')}</label>
                <textarea className="input" rows={2} value={form.outputs} onChange={e => set('outputs', e.target.value)} placeholder="Match disposition" />
              </div>
              <div>
                <div className="flex items-center mb-1"><label className={`${label} !mb-0`}>SLA</label>{tip('sla')}</div>
                <input className="input" value={form.sla} onChange={e => set('sla', e.target.value)} placeholder="99.5% uptime" />
              </div>
              <div>
                <label className={label}>Rate limit</label>
                <input className="input" value={form.rate_limit} onChange={e => set('rate_limit', e.target.value)} placeholder="10 requests/second" />
              </div>
              <div className="col-span-2">
                <label className={label}>Owner contact</label>
                <input className="input" value={form.owner_contact} onChange={e => set('owner_contact', e.target.value)} placeholder="team email or channel" />
              </div>
            </div>
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
                <p className="text-xs text-slate-500 mt-1">This app's own tracing backend, if it isn't on the shared org Phoenix instance.</p>
              </div>
            )}
            <div>
              <div className="flex items-center mb-1"><label className={`${label} !mb-0`}>Phoenix project name{from('phoenix_project')}</label>{tip('phoenix_project')}</div>
              <PhoenixProjectPicker id="onboard-phoenix-projects" value={form.phoenix_project} onChange={v => set('phoenix_project', v)} />
              {form.phoenix_endpoint_mode === 'custom' && (
                <p className="text-xs text-slate-500 mt-1">Discovery above always checks the common endpoint — for a custom endpoint, type the project name directly.</p>
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
            <p className="text-xs text-slate-500 mt-1">Shown as-is on the agent's own page. Not required to register.</p>
          </div>

          <DraftCoach draft={() => ({
            name: form.name, description: form.description, business_outcome: form.business_outcome,
            capabilities: splitLines(form.capabilities), ai_type: form.ai_type, owner_recorded: !!form.owner.trim(),
            value_amount: Number(form.value_amount) || 0, inputs: splitLines(form.inputs), outputs: splitLines(form.outputs),
            model_name: form.model_name,
          })} />

          {error && <div className="rounded-xl bg-rose-50 border border-rose-200 px-3 py-2 text-xs text-rose-700">{error}</div>}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="btn-secondary btn-sm">
              Cancel
            </button>
            <button type="submit" disabled={saving || reasonShort} className="btn-primary btn-sm"
              title={reasonShort ? 'Say why none of the similar agents fit first' : undefined}>
              {saving ? 'Registering…' : 'Register application'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
