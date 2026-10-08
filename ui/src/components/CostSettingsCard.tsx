import { useEffect, useState } from 'react'
import { Cloud } from 'lucide-react'
import { collectInfraCosts, getInfraCostStatus, saveInfraCostConfig, testInfraCostConfig, type InfraCostStatus } from '../services/ops/economics'
import { getValueSettings, updateValueSettings } from '../services/ops/value'
import { errorMessage } from '../pages/agent/shared'

// Settings → Cost settings: the Azure Cost Management connection (metered hosting
// cost per agent) with a test, and the agreed cost of building an agent (reuse savings).
export default function CostSettingsCard({ canEdit }: { canEdit: boolean }) {
  const [st, setSt] = useState<InfraCostStatus | null>(null)
  const [f, setF] = useState({ tenantId: '', clientId: '', clientSecret: '', scope: '', tagKey: 'agent-id' })
  const [build, setBuild] = useState('')
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    getInfraCostStatus().then(r => { setSt(r.data); setF(x => ({ ...x, tenantId: r.data.tenantId || '', clientId: r.data.clientId || '', tagKey: r.data.tagKey || 'agent-id' })) }).catch(() => setSt(null))
    getValueSettings().then(r => setBuild(r.data.buildCostCents ? String(r.data.buildCostCents / 100) : '')).catch(() => {})
  }, [])
  async function run(fn: () => Promise<{ ok: boolean; text: string }>) {
    setBusy(true); setMsg(null)
    try { setMsg(await fn()) } catch (e) { setMsg({ ok: false, text: errorMessage(e, 'It did not work') }) } finally { setBusy(false) }
  }
  if (!st) return null
  return (
    <div className="card p-6 space-y-4" data-testid="cost-settings">
      <div className="flex items-start gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-sky-50 text-sky-600"><Cloud size={20} /></div>
        <div>
          <h3 className="text-[16px] font-extrabold text-slate-900">Cost settings</h3>
          <p className="text-[13px] text-slate-600">
            Azure Cost Management gives the metered hosting cost of each agent: a resource tagged {st.tagKey}=&lt;agent id&gt;, or linked on the agent's Revenue & Expenditure tab,
            counts for that agent. The service principal needs the {st.requiredRole} role on the scope.
            {' '}Now: <b data-testid="azure-state">{st.configured ? `set up (${st.configSource === 'settings' ? 'saved here' : 'from the backend environment'}), scope ${st.scope}` : `not set up, missing ${st.missing.join(', ')}`}</b>.
            {st.lastRun && ` Last pull: ${st.lastRun.status} on ${new Date(st.lastRun.startedAt || '').toLocaleString()}.`}
          </p>
        </div>
      </div>
      {canEdit && (
        <>
          <div className="grid gap-2 sm:grid-cols-2 text-[12.5px] text-slate-600">
            <label>Tenant id<input className="input mt-0.5 text-sm" value={f.tenantId} onChange={e => setF({ ...f, tenantId: e.target.value })} data-testid="azure-tenant" /></label>
            <label>Client id<input className="input mt-0.5 text-sm" value={f.clientId} onChange={e => setF({ ...f, clientId: e.target.value })} /></label>
            <label>Client secret {st.secretSet && <span className="text-emerald-700">(saved, leave empty to keep it)</span>}
              <input className="input mt-0.5 text-sm" type="password" autoComplete="new-password" value={f.clientSecret} onChange={e => setF({ ...f, clientSecret: e.target.value })} /></label>
            <label>Scope (for example /subscriptions/&lt;id&gt; or a resource group)
              <input className="input mt-0.5 text-sm" value={f.scope} onChange={e => setF({ ...f, scope: e.target.value })} placeholder={st.scope || '/subscriptions/…'} data-testid="azure-scope" /></label>
            <label>Tag that names the agent<input className="input mt-0.5 text-sm" value={f.tagKey} onChange={e => setF({ ...f, tagKey: e.target.value })} /></label>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-primary btn-sm" disabled={busy || !f.tenantId || !f.clientId || !(f.scope || st.scope)} data-testid="azure-save"
              onClick={() => run(async () => { const r = (await saveInfraCostConfig({ ...f, scope: f.scope || st.scope || '', clientSecret: f.clientSecret || undefined })).data; setSt(r); setF(x => ({ ...x, clientSecret: '' })); return { ok: true, text: 'Saved. Test the connection next.' } })}>Save</button>
            <button type="button" className="btn-secondary btn-sm" disabled={busy || !st.configured} data-testid="azure-test"
              onClick={() => run(async () => { const r = (await testInfraCostConfig()).data; return { ok: r.ok, text: r.message } })}>Test the connection</button>
            <button type="button" className="btn-secondary btn-sm" disabled={busy || !st.configured}
              onClick={() => run(async () => { const r = (await collectInfraCosts(undefined, 7)).data; return { ok: r.status === 'ok' || r.status === 'partial', text: `Pull of the last 7 days: ${r.status}${r.reason ? `, ${r.reason}` : ''}.` } })}>Pull the last 7 days now</button>
          </div>
        </>
      )}
      <div className="flex flex-wrap items-end gap-2 border-t border-slate-100 pt-3 text-[12.5px] text-slate-600">
        <label>Agreed cost of building an agent ($), for reuse savings
          <input className="input mt-0.5 !w-40 text-sm" type="number" min={0} value={build} disabled={!canEdit} onChange={e => setBuild(e.target.value)} data-testid="build-cost" /></label>
        {canEdit && <button type="button" className="btn-secondary btn-sm" disabled={busy}
          onClick={() => run(async () => { await updateValueSettings(build ? Math.round(Number(build) * 100) : null); return { ok: true, text: build ? `Reuse savings now count $${Number(build).toLocaleString()} per build avoided.` : 'Cleared: reuse savings are not valued.' } })}>Save</button>}
      </div>
      {msg && <p className={`text-[13px] ${msg.ok ? 'text-emerald-700' : 'text-rose-700'}`} role="status">{msg.text}</p>}
    </div>
  )
}
