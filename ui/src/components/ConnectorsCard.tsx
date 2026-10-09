import { useEffect, useState } from 'react'
import { Plug } from 'lucide-react'
import { createConnector, deleteConnector, listConnectors, syncConnector, testConnector, updateConnector, type ConnectorKind, type ConnectorRow } from '../services/ops/connectors'
import { errorMessage } from '../pages/agent/shared'

// What each kind of connector asks for. Secret fields are stored encrypted and never shown again.
const FORMS: Record<ConnectorKind, { label: string; help: string; fields: { key: string; label: string; secret?: boolean; list?: boolean; placeholder?: string }[] }> = {
  langfuse: {
    label: 'Langfuse project', help: 'One connector per Langfuse project (its key pair). Finds the project and reads daily token usage for an agent linked to it.',
    fields: [{ key: 'host', label: 'Langfuse address', placeholder: 'https://cloud.langfuse.com' }, { key: 'public_key', label: 'Public key', secret: true }, { key: 'secret_key', label: 'Secret key', secret: true }],
  },
  github: {
    label: 'GitHub organisation', help: 'Finds repositories that build agents (agent frameworks, MCP servers, agent cards). Reads only dependency files and cards, never source code. Adding a read-only token lets GitHub answer more requests an hour.',
    fields: [{ key: 'orgs', label: 'Organisations or users (comma separated)', list: true, placeholder: 'acme, acme-labs' }, { key: 'apiUrl', label: 'API address (GitHub Enterprise only)', placeholder: 'https://api.github.com' }, { key: 'token', label: 'Token (read-only)', secret: true }],
  },
  azure: {
    label: 'Azure subscription', help: 'Lists Azure OpenAI and AI Services model deployments, and Foundry agents where allowed. Needs a service principal with Reader on the subscriptions.',
    fields: [{ key: 'tenantId', label: 'Tenant id' }, { key: 'clientId', label: 'Client id' }, { key: 'subscriptions', label: 'Subscription ids (comma separated)', list: true }, { key: 'clientSecret', label: 'Client secret', secret: true }],
  },
  assureai: {
    label: 'AssureAI application (verdicts only)', help: 'Reads the pass or fail verdict of an AssureAI evaluation run with the application\'s run key, for the evidence line on the Governance tab. Copies no scores and finds no agents, so Scan now finds nothing.',
    fields: [{ key: 'baseUrl', label: 'AssureAI API address', placeholder: 'https://assureai.example.com/api' }, { key: 'linkTemplate', label: 'Link to a run in AssureAI (optional, {runId} is replaced)', placeholder: 'https://assureai.example.com/runs/{runId}' }, { key: 'runKey', label: 'Run key of the application', secret: true }],
  },
}

const STATUS_TONE: Record<string, string> = { ok: 'text-emerald-700', unauthorized: 'text-rose-700', unreachable: 'text-rose-700', failed: 'text-rose-700', not_configured: 'text-amber-700' }

export default function ConnectorsCard() {
  const [rows, setRows] = useState<ConnectorRow[] | null>(null)
  const [kind, setKind] = useState<ConnectorKind | ''>('')
  const [values, setValues] = useState<Record<string, string>>({})
  const [label, setLabel] = useState('')
  const [msg, setMsg] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const load = () => listConnectors().then(r => setRows(r.data.connectors)).catch(() => setRows([]))
  useEffect(() => { load() }, [])

  async function add() {
    if (!kind) return
    const form = FORMS[kind]
    const settings: Record<string, unknown> = {}
    const secret: Record<string, string> = {}
    for (const f of form.fields) {
      const v = (values[f.key] || '').trim()
      if (!v) continue
      if (f.secret) secret[f.key] = v
      else settings[f.key] = f.list ? v.split(',').map(x => x.trim()).filter(Boolean) : v
    }
    setBusy('add')
    try {
      await createConnector({ kind, label: label.trim() || form.label, settings, secret })
      setKind(''); setValues({}); setLabel(''); await load()
    } catch (e) { setMsg({ add: errorMessage(e, 'Not saved') }) } finally { setBusy(null) }
  }

  async function run(id: string, what: 'test' | 'sync') {
    setBusy(`${what}:${id}`)
    try {
      const r = what === 'test' ? (await testConnector(id)).data : (await syncConnector(id)).data
      setMsg(m => ({ ...m, [id]: r.message }))
      await load()
    } catch (e) { setMsg(m => ({ ...m, [id]: errorMessage(e, 'It did not run') })) } finally { setBusy(null) }
  }

  return (
    <div className="card p-6 space-y-3" data-testid="connectors">
      <div className="flex items-start gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-violet-50 text-violet-600"><Plug size={20} /></div>
        <div>
          <h3 className="text-[16px] font-extrabold text-slate-900">Connectors</h3>
          <p className="text-[13px] text-slate-600">Other places the registry looks for agents, read-only. What they find appears on Discovered → Other sources. They are scanned every day (Pipelines → Connector scan).</p>
        </div>
      </div>
      {rows && rows.length > 0 && (
        <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200">
          {rows.map(c => (
            <li key={c.id} className="px-4 py-3 space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-slate-900">{c.label}</span>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[12px] font-semibold text-slate-700">{c.kindLabel}</span>
                {!c.enabled && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[12px] font-semibold text-amber-800">Off</span>}
                <span className="ml-auto flex gap-1.5">
                  <button type="button" className="btn-secondary btn-sm" disabled={!!busy} onClick={() => run(c.id, 'test')}>{busy === `test:${c.id}` ? 'Testing…' : 'Test'}</button>
                  <button type="button" className="btn-secondary btn-sm" disabled={!!busy} onClick={() => run(c.id, 'sync')}>{busy === `sync:${c.id}` ? 'Scanning…' : 'Scan now'}</button>
                  <button type="button" className="btn-secondary btn-sm" disabled={!!busy} onClick={() => updateConnector(c.id, { enabled: !c.enabled }).then(load)}>{c.enabled ? 'Turn off' : 'Turn on'}</button>
                  <button type="button" className="btn-ghost btn-sm" disabled={!!busy} onClick={() => deleteConnector(c.id).then(load)}>Remove</button>
                </span>
              </div>
              <div className="text-[12.5px] text-slate-600">
                Secret set: {c.secretSet.length ? c.secretSet.join(', ') : 'none'} · Last scan: {c.lastSyncAt ? new Date(c.lastSyncAt).toLocaleString() : 'never'}
                {c.lastStatus && <> · <span className={STATUS_TONE[c.lastStatus] || 'text-slate-700'}>{c.lastStatus.replace('_', ' ')}</span>: {c.lastMessage}</>}
              </div>
              {msg[c.id] && <div className="text-[12.5px] text-slate-800" role="status">{msg[c.id]}</div>}
            </li>
          ))}
        </ul>
      )}
      <div className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <select className="input !w-auto" value={kind} onChange={e => { setKind(e.target.value as ConnectorKind | ''); setValues({}) }} aria-label="Connector kind" data-testid="connector-kind">
            <option value="">Add a connector…</option>
            {(Object.keys(FORMS) as ConnectorKind[]).map(k => <option key={k} value={k}>{FORMS[k].label}</option>)}
          </select>
          {kind && <input className="input !w-64" placeholder="Name, e.g. Payments GitHub" value={label} onChange={e => setLabel(e.target.value)} />}
        </div>
        {kind && (
          <>
            <p className="text-[12.5px] text-slate-600">{FORMS[kind].help}</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {FORMS[kind].fields.map(f => (
                <label key={f.key} className="text-[12.5px] text-slate-700">{f.label}
                  <input className="input mt-0.5" type={f.secret ? 'password' : 'text'} placeholder={f.placeholder} value={values[f.key] || ''}
                    onChange={e => setValues(v => ({ ...v, [f.key]: e.target.value }))} autoComplete="off" />
                </label>
              ))}
            </div>
            <button type="button" className="btn-primary btn-sm" disabled={busy === 'add'} onClick={add} data-testid="connector-add">Add connector</button>
            {msg.add && <p className="text-[12.5px] text-rose-700">{msg.add}</p>}
          </>
        )}
      </div>
    </div>
  )
}
