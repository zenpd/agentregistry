import { useCallback, useEffect, useState } from 'react'
import { getVersions, releaseVersion, setConsumerVersion, type Versions } from '../../services/ops/lifecycleSteps'
import { can, notAllowed, useMe } from '../../lib/me'
import InfoTip from '../../components/InfoTip'

function errorMessage(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  return typeof detail === 'string' ? detail : e?.message || fallback
}

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—')

// Integrate tab → Versions: released versions with their changelog, and the
// version each team with approved access uses.
export default function VersionsSection({ agentId, onChanged }: { agentId: string; onChanged: () => void }) {
  const me = useMe()
  const [v, setV] = useState<Versions | null>(null)
  const [form, setForm] = useState({ version: '', changelog: '' })
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const load = useCallback(() => getVersions(agentId).then(r => setV(r.data)).catch(e => setMsg(errorMessage(e, 'Could not load versions'))), [agentId])
  useEffect(() => { load() }, [load])

  async function release() {
    setBusy(true); setMsg(null)
    try {
      const r = (await releaseVersion(agentId, form.version.trim(), form.changelog.trim())).data
      setMsg(`Version ${r.version} released. ${r.told ? `${r.told} team contact${r.told === 1 ? ' was' : 's were'} told.` : 'No team with approved access to tell.'}`)
      setForm({ version: '', changelog: '' }); setOpen(false); await load(); onChanged()
    } catch (e) { setMsg(errorMessage(e, 'Not released')) } finally { setBusy(false) }
  }
  async function move(requestId: string, version: string) {
    setBusy(true); setMsg(null)
    try { await setConsumerVersion(agentId, requestId, version); await load() } catch (e) { setMsg(errorMessage(e, 'Not changed')) } finally { setBusy(false) }
  }
  if (!v) return msg ? <p className="text-sm text-rose-600">{msg}</p> : null

  return (
    <section className="rounded-2xl border border-slate-200/80 bg-white p-5 space-y-3 shadow-sm" data-testid="versions">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <span className="mt-1 h-4 w-1 shrink-0 rounded-full bg-gradient-to-b from-zen-400 to-zen-700" aria-hidden />
          <div>
            <h3 className="text-[16px] font-extrabold text-slate-900">Versions <InfoTip term="versions" /></h3>
            <p className="text-[13px] text-slate-600 mt-0.5">
              Current version: <b>{v.current || 'not recorded'}</b>.
              {v.versions.length === 0 && v.current && ' It was entered at registration. Release it to record a changelog.'}
            </p>
          </div>
        </div>
        {can(me, 'update') && !open && (
          <button type="button" className="btn-secondary btn-sm" onClick={() => { setForm({ version: v.versions.length ? '' : v.current || '', changelog: '' }); setOpen(true) }} data-testid="release-version">
            Release a version
          </button>
        )}
      </div>

      {open && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 space-y-2">
          <div className="flex flex-wrap gap-2">
            <label className="text-[12.5px] text-slate-600">Version
              <input className="input mt-0.5 !w-32 text-sm" value={form.version} onChange={e => setForm({ ...form, version: e.target.value })} placeholder="2.1.0" data-testid="version-input" />
            </label>
            <label className="flex-1 min-w-[260px] text-[12.5px] text-slate-600">What changed (sent to the teams that use it)
              <input className="input mt-0.5 text-sm" value={form.changelog} onChange={e => setForm({ ...form, changelog: e.target.value })} data-testid="changelog-input" />
            </label>
          </div>
          <p className="text-[12px] text-slate-500">The registry also keeps the model, tools and endpoint at release, and shows what changed between versions.</p>
          <div className="flex gap-2">
            <button type="button" className="btn-primary btn-sm" disabled={busy || !form.version.trim() || form.changelog.trim().length < 10} onClick={release} data-testid="confirm-release">Release</button>
            <button type="button" className="btn-ghost btn-sm" onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </div>
      )}
      {!can(me, 'update') && me && <p className="text-[12.5px] text-slate-500">{notAllowed(me, 'release a version')}</p>}

      {v.versions.length > 0 && (
        <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 text-[13px]">
          {v.versions.map(x => (
            <li key={x.version} className="px-3 py-2" data-testid="version-row">
              <span className="font-semibold text-slate-900">{x.version}</span>
              <span className="ml-2 text-slate-500">{fmt(x.releasedAt)} · {x.releasedBy}</span>
              <span className="block text-slate-700">{x.changelog}</span>
              {x.structuralChanges && <span className="block text-amber-800">Changed since the previous version: {x.structuralChanges}</span>}
            </li>
          ))}
        </ul>
      )}

      <div>
        <div className="text-xs font-semibold uppercase text-slate-500 mb-1">Version each team uses</div>
        {v.consumers.length === 0
          ? <p className="text-[13px] text-slate-500">No team has approved access yet.</p>
          : (
            <ul className="space-y-1 text-[13px]">
              {v.consumers.map(c => (
                <li key={c.requestId} className="flex flex-wrap items-center gap-2" data-testid="consumer-version">
                  <span className="font-medium text-slate-900">{c.team}</span>
                  <span className="text-slate-600">uses {c.version || 'a version not recorded'}</span>
                  {c.behind ? <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[12px] font-semibold text-amber-800 ring-1 ring-amber-200">{c.behind} version{c.behind === 1 ? '' : 's'} behind</span> : null}
                  {c.changedSince && <span className="text-slate-600">Since then: {c.changedSince}</span>}
                  {can(me, 'update') && v.versions.length > 0 && (
                    <select className="input !w-auto !py-0.5 text-[12.5px]" value={c.version || ''} disabled={busy} aria-label={`Version ${c.team} uses`}
                      onChange={e => move(c.requestId, e.target.value)}>
                      {!c.version && <option value="">Not recorded</option>}
                      {v.versions.map(x => <option key={x.version} value={x.version}>{x.version}</option>)}
                    </select>
                  )}
                </li>
              ))}
            </ul>
          )}
        {v.consumersWithoutGrant.length > 0 && (
          <p className="mt-1 text-[12.5px] text-slate-500">Declared by the owner without an access grant, so no version is recorded: {v.consumersWithoutGrant.join(', ')}.</p>
        )}
      </div>
      {msg && <p className="text-[13px] text-slate-700" role="status">{msg}</p>}
    </section>
  )
}
