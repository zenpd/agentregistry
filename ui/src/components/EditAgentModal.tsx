import { useState } from 'react'
import InfoTip from './InfoTip'
import { Link } from 'react-router-dom'
import { updateAgent, type Agent } from '../services/api'
import { errorMessage } from '../pages/agent/shared'
import { AI_TYPES, DEPTS } from './OnboardingModal'

export default function EditAgentModal({ agent, onClose, onSaved }: {
  agent: Agent; onClose: () => void; onSaved: () => void
}) {
  const [initial] = useState({
    name: agent.name,
    owner_contact: agent.ownerContact || '',
    dept: agent.dept || '',
    ai_type: agent.aiType,
    description: agent.description || '',
    business_outcome: agent.businessOutcome || '',
    hours_saved_monthly: agent.hoursSavedMonthly || 0,
  })
  const [form, setForm] = useState(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => setForm(f => ({ ...f, [key]: value }))
  // A department outside the standard list (e.g. from discovery) stays selectable.
  const depts = form.dept && !DEPTS.includes(form.dept) ? [form.dept, ...DEPTS] : DEPTS

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!form.name.trim()) { setError('Name is required'); return }
    if (form.hours_saved_monthly < 0) { setError('Hours cannot be negative'); return }
    const cleaned = {
      ...form,
      name: form.name.trim(),
      owner_contact: form.owner_contact.trim(),
      hours_saved_monthly: Number(form.hours_saved_monthly) || 0,
    }
    // Only what changed, so the audit log records real edits.
    const changes = Object.fromEntries(
      Object.entries(cleaned).filter(([k, v]) => v !== initial[k as keyof typeof initial]),
    ) as Partial<typeof cleaned>
    if (Object.keys(changes).length === 0) { onClose(); return }
    setSaving(true)
    setError(null)
    try {
      await updateAgent(agent.id, changes)
      onSaved()
    } catch (err) {
      setError(errorMessage(err, 'Could not save the changes'))
    } finally {
      setSaving(false)
    }
  }

  const label = 'block text-xs font-semibold uppercase text-slate-600 mb-1 tracking-wide'

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="edit-agent-title"
        className="bg-white rounded-2xl border border-gray-100 shadow-card-hover max-w-2xl w-full max-h-[90vh] overflow-y-auto animate-slide-up"
        onClick={e => e.stopPropagation()}>
        <form onSubmit={submit} className="p-6 space-y-4" data-testid="edit-agent-form">
          <div className="flex justify-between items-start">
            <div>
              <h2 id="edit-agent-title" className="text-xl font-bold text-slate-900">Edit {agent.name}</h2>
              <p className="text-sm text-slate-600 mt-0.5">
                Stage changes go through the <Link to={`/agents/${agent.id}?tab=governance`} className="text-zen-700 hover:underline">Governance tab</Link>;
                endpoint, capabilities and contract through the <Link to={`/agents/${agent.id}?tab=integrate`} className="text-zen-700 hover:underline">Integrate tab</Link>.
              </p>
            </div>
            <button type="button" onClick={onClose} aria-label="Close" className="text-slate-500 hover:text-slate-700 text-2xl leading-none">&times;</button>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className={label} htmlFor="edit-name">Name *</label>
              <input id="edit-name" className="input" value={form.name} onChange={e => set('name', e.target.value)} required />
            </div>
            <div>
              <div className="flex items-center gap-1">
                <span className={label}>Owner</span>
                <InfoTip term="owner" className="-my-0.5 mb-1" />
              </div>
              {/* The owner is changed in one place, with a reason, so the change is on record. */}
              <div className="input bg-slate-50 flex items-center justify-between gap-2" data-testid="edit-owner">
                <span className="truncate text-slate-800">{agent.owner || 'No owner'}</span>
                <Link to={`/agents/${agent.id}?tab=overview`} className="shrink-0 text-xs font-semibold text-zen-700 hover:underline">Change on Overview</Link>
              </div>
            </div>
            <div>
              <label className={label} htmlFor="edit-contact">Owner contact</label>
              <input id="edit-contact" className="input" value={form.owner_contact} onChange={e => set('owner_contact', e.target.value)} placeholder="team email or channel" />
            </div>
            <div>
              <div className="flex items-center gap-1">
                <label className={label} htmlFor="edit-dept">Department</label>
                <InfoTip term="department" className="-my-0.5 mb-1" />
              </div>
              <select id="edit-dept" className="input" value={form.dept} onChange={e => set('dept', e.target.value)}>
                <option value="">No department</option>
                {depts.map(d => <option key={d} value={d}>{d.replace('dept-', '')}</option>)}
              </select>
            </div>
            <div>
              <div className="flex items-center gap-1">
                <label className={label} htmlFor="edit-type">AI type</label>
                <InfoTip term="ai_type" className="-my-0.5 mb-1" />
              </div>
              <select id="edit-type" className="input" value={form.ai_type} onChange={e => set('ai_type', e.target.value)}>
                {AI_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
          </div>

          <div>
            <label className={label} htmlFor="edit-description">Description</label>
            <textarea id="edit-description" className="input" rows={3} value={form.description} onChange={e => set('description', e.target.value)} />
          </div>
          <div>
            <div className="flex items-center gap-1">
                <label className={label} htmlFor="edit-outcome">Business outcome</label>
                <InfoTip term="business_outcome" className="-my-0.5 mb-1" />
              </div>
            <input id="edit-outcome" className="input" value={form.business_outcome} onChange={e => set('business_outcome', e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="flex items-center gap-1">
                <span className={label}>Declared value ($ a month)</span>
                <InfoTip term="declared_value" className="-my-0.5 mb-1" />
              </div>
              {/* The value is declared in one place, with its method and basis, and finance checks it there. */}
              <div className="input bg-slate-50 flex items-center justify-between gap-2" data-testid="edit-value">
                <span className="text-slate-800">{agent.valueAmount ? `$${agent.valueAmount.toLocaleString()}` : 'Not declared'}</span>
                <Link to={`/agents/${agent.id}?tab=revenue`} className="shrink-0 text-xs font-semibold text-zen-700 hover:underline">Declare on Revenue &amp; Expenditure</Link>
              </div>
            </div>
            <div>
              <div className="flex items-center gap-1">
                <label className={label} htmlFor="edit-hours">Hours saved / month</label>
                <InfoTip term="hours_saved" className="-my-0.5 mb-1" />
              </div>
              <input id="edit-hours" type="number" min={0} className="input" value={form.hours_saved_monthly} onChange={e => set('hours_saved_monthly', Number(e.target.value))} />
            </div>
          </div>

          {error && <div className="rounded-xl bg-rose-50 border border-rose-200 px-3 py-2 text-xs text-rose-700">{error}</div>}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="btn-secondary btn-sm">Cancel</button>
            <button type="submit" disabled={saving} className="btn-primary btn-sm">{saving ? 'Saving…' : 'Save changes'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}
