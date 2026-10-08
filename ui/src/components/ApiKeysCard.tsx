import { useEffect, useState } from 'react'
import { KeyRound } from 'lucide-react'
import { issueApiKey, listApiKeys, revokeApiKey, type ApiKeyRow } from '../services/ops/apiKeys'
import { errorMessage } from '../pages/agent/shared'

const SCOPES: { id: string; label: string }[] = [
  { id: 'register', label: 'register — create or update agents from a pipeline' },
  { id: 'certify_check', label: 'certify_check — ask whether an agent is approved for a stage (this is not the reuse certification)' },
  { id: 'read', label: 'read — read the registry' },
]

const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : '—')

// Settings → API keys for pipelines and scripts. A key is shown once.
export default function ApiKeysCard() {
  const [rows, setRows] = useState<ApiKeyRow[] | null>(null)
  const [label, setLabel] = useState('')
  const [scopes, setScopes] = useState<string[]>(['register', 'certify_check'])
  const [days, setDays] = useState('')
  const [fresh, setFresh] = useState<{ key: string; label: string } | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const load = () => listApiKeys().then(r => setRows(r.data)).catch(e => setMsg(errorMessage(e, 'Could not load keys')))
  useEffect(() => { load() }, [])

  async function issue() {
    setBusy(true)
    try {
      const r = (await issueApiKey({ label: label.trim(), scopes, expiresInDays: days ? Number(days) : null })).data
      setFresh({ key: r.key, label: r.label }); setLabel(''); setMsg(null); await load()
    } catch (e) { setMsg(errorMessage(e, 'The key was not issued')) } finally { setBusy(false) }
  }

  return (
    <div className="card p-6 space-y-3" data-testid="api-keys">
      <div className="flex items-start gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-indigo-50 text-indigo-600"><KeyRound size={20} /></div>
        <div>
          <h3 className="text-[16px] font-extrabold text-slate-900">API keys</h3>
          <p className="text-[13px] text-slate-600">For build pipelines and scripts: register agents and stop a release that is not approved for its stage. Use with <code className="font-mono">tools/registry_cli.py</code>. A key never decides a review.</p>
        </div>
      </div>
      {fresh && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[13px] text-emerald-900" role="status" data-testid="new-key">
          <p className="font-semibold">Key for “{fresh.label}”. Copy it now: it is not shown again.</p>
          <div className="mt-1 flex items-center gap-2">
            <code className="flex-1 break-all rounded bg-white px-2 py-1 font-mono text-[12.5px] ring-1 ring-emerald-200">{fresh.key}</code>
            <button type="button" className="btn-secondary btn-sm" onClick={() => navigator.clipboard?.writeText(fresh.key)}>Copy</button>
            <button type="button" className="btn-secondary btn-sm" onClick={() => setFresh(null)}>Done</button>
          </div>
        </div>
      )}
      <div className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200 space-y-2">
        <div className="flex flex-wrap gap-2">
          <input className="input !w-64" placeholder="What it is for, e.g. payments CI" value={label} onChange={e => setLabel(e.target.value)} />
          <input className="input !w-40" placeholder="Expires in days (optional)" inputMode="numeric" value={days} onChange={e => setDays(e.target.value.replace(/\D/g, ''))} />
          <button type="button" className="btn-primary btn-sm" disabled={busy || label.trim().length < 3 || scopes.length === 0} onClick={issue} data-testid="issue-key">Issue key</button>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          {SCOPES.map(s => (
            <label key={s.id} className="flex items-center gap-1.5 text-[12.5px] text-slate-700">
              <input type="checkbox" checked={scopes.includes(s.id)} onChange={e => setScopes(v => e.target.checked ? [...v, s.id] : v.filter(x => x !== s.id))} />{s.label}
            </label>
          ))}
        </div>
      </div>
      {msg && <p className="text-[13px] text-rose-700">{msg}</p>}
      {rows && rows.length > 0 && (
        <table className="w-full text-[13px]">
          <thead><tr className="text-left text-slate-600 border-b"><th className="py-1.5">Label</th><th>Key</th><th>Scopes</th><th>Issued</th><th>Last used</th><th>Expires</th><th /></tr></thead>
          <tbody>
            {rows.map(k => (
              <tr key={k.id} className="border-b last:border-0">
                <td className="py-1.5 font-medium text-slate-900">{k.label}</td>
                <td className="font-mono text-[12px]">{k.prefix}…</td>
                <td>{k.scopes.join(', ')}</td>
                <td>{day(k.createdAt)}</td>
                <td>{day(k.lastUsedAt)}</td>
                <td>{day(k.expiresAt)}</td>
                <td className="text-right">{k.active
                  ? <button type="button" className="btn-secondary btn-sm" onClick={() => revokeApiKey(k.id).then(load).catch(e => setMsg(errorMessage(e, 'Not revoked')))}>Revoke</button>
                  : <span className="text-slate-500">{k.revokedAt ? `Revoked ${day(k.revokedAt)}` : 'Expired'}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
