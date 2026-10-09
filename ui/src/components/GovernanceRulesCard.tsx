import { useEffect, useState } from 'react'
import { Scale } from 'lucide-react'
import { getGovernanceSettings, updateGovernanceSettings, type GovernanceSettings } from '../services/ops/governance'
import { errorMessage } from '../pages/agent/shared'

const GATES = [{ id: 'arb', label: 'Architecture' }, { id: 'security', label: 'Security' }, { id: 'dp', label: 'Data Protection' }] as const
const TIERS = ['LOW', 'MEDIUM', 'HIGH'] as const
const STAGES = ['Development', 'Testing', 'Production'] as const
const STALL = ['Ideation', 'Development', 'Testing'] as const

// Settings → Governance rules: which reviews each risk tier needs, how long an
// approval lasts, warn or block, the fields each stage requires, and when a stage counts as stalled.
export default function GovernanceRulesCard({ canEdit }: { canEdit: boolean }) {
  const [s, setS] = useState<GovernanceSettings | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { getGovernanceSettings().then(r => setS(r.data)).catch(e => setMsg(errorMessage(e, 'Could not load the rules'))) }, [])
  if (!s) return <div className="card p-6 text-sm text-slate-600">{msg ?? 'Loading governance rules…'}</div>

  const setTier = (tier: typeof TIERS[number], patch: Partial<GovernanceSettings['templates']['LOW']>) =>
    setS({ ...s, templates: { ...s.templates, [tier]: { ...s.templates[tier], ...patch } } })
  async function save() {
    setBusy(true)
    try { setS((await updateGovernanceSettings({ templates: s!.templates, requiredFields: s!.requiredFields, stallWeeks: s!.stallWeeks, assureaiRequired: s!.assureaiRequired })).data); setMsg('Saved. The rules apply at once to every stage change and new approval.') }
    catch (e) { setMsg(errorMessage(e, 'Not saved')) } finally { setBusy(false) }
  }

  return (
    <div className="card p-6 space-y-4" data-testid="governance-rules">
      <div className="flex items-start gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-amber-50 text-amber-600"><Scale size={20} /></div>
        <div>
          <h3 className="text-[16px] font-extrabold text-slate-900">Governance rules</h3>
          <p className="text-[13px] text-slate-600">By risk level: the reviews needed before Production, how long an approval lasts, and whether a broken rule warns or blocks a stage change. The Architecture Review Board is always needed, and already before Testing. The other ticked reviews are needed before Production.</p>
        </div>
      </div>
      <table className="w-full text-[13px]">
        <thead><tr className="text-left text-slate-600 border-b"><th className="py-1.5">Risk level</th><th>Reviews before Production</th><th>Approval lasts (days)</th><th>Broken rule</th></tr></thead>
        <tbody>
          {TIERS.map(t => (
            <tr key={t} className="border-b last:border-0">
              <td className="py-2 font-semibold text-slate-900">{t}</td>
              <td>{GATES.map(g => (
                <label key={g.id} className="mr-3 inline-flex items-center gap-1">
                  <input type="checkbox" disabled={!canEdit || g.id === 'arb'} checked={s.templates[t].gates.includes(g.id)}
                    onChange={e => setTier(t, { gates: e.target.checked ? [...s.templates[t].gates, g.id] : s.templates[t].gates.filter(x => x !== g.id) })} />{g.label}
                </label>))}</td>
              <td><input className="input !w-24 !py-1" type="number" min={30} max={730} disabled={!canEdit} value={s.templates[t].validityDays}
                onChange={e => setTier(t, { validityDays: Number(e.target.value) })} /></td>
              <td><select className="input !w-auto !py-1" disabled={!canEdit} value={s.templates[t].mode} onChange={e => setTier(t, { mode: e.target.value as 'warn' | 'block' })}>
                <option value="warn">warns</option><option value="block">blocks</option></select></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div>
        <div className="text-[13px] font-semibold text-slate-900 mb-1">Fields required before each stage (cumulative)</div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {STAGES.map(st => (
            <div key={st} className="rounded-lg bg-slate-50 p-2 ring-1 ring-slate-200">
              <div className="text-[12.5px] font-semibold text-slate-800 mb-1">{st}</div>
              {s.requirable.map(f => (
                <label key={f.key} className="flex items-center gap-1.5 text-[12.5px] text-slate-700">
                  <input type="checkbox" disabled={!canEdit} checked={(s.requiredFields[st] || []).includes(f.key)}
                    onChange={e => setS({ ...s, requiredFields: { ...s.requiredFields, [st]: e.target.checked ? [...(s.requiredFields[st] || []), f.key] : (s.requiredFields[st] || []).filter(x => x !== f.key) } })} />{f.label}
                </label>
              ))}
            </div>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-[13px] text-slate-700">
        <span className="font-semibold text-slate-900">Stalled after (weeks):</span>
        {STALL.map(st => (
          <label key={st} className="flex items-center gap-1">{st}
            <input className="input !w-16 !py-1" type="number" min={1} disabled={!canEdit} value={s.stallWeeks[st]}
              onChange={e => setS({ ...s, stallWeeks: { ...s.stallWeeks, [st]: Number(e.target.value) } })} /></label>
        ))}
      </div>
      <label className="flex items-start gap-2 text-[13px] text-slate-700">
        <input type="checkbox" className="mt-0.5" disabled={!canEdit} checked={s.assureaiRequired}
          onChange={e => setS({ ...s, assureaiRequired: e.target.checked })} data-testid="assureai-required" />
        <span><span className="font-semibold text-slate-900">AssureAI verdict before Production.</span> AssureAI is the testing tool linked in Settings → Connectors. An agent with no AssureAI verdict, or a failed one, gets a warning before Production or is blocked, like the other rules of its risk level.</span>
      </label>
      {canEdit && <button type="button" className="btn-primary btn-sm" disabled={busy} onClick={save} data-testid="save-governance-rules">{busy ? 'Saving…' : 'Save the rules'}</button>}
      {msg && <p className="text-[13px] text-slate-700" role="status">{msg}</p>}
    </div>
  )
}
