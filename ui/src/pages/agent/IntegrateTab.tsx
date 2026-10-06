import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Pencil } from 'lucide-react'
import { getMe } from '../../services/api'
import {
  decideAccess, getIntegration, requestAccess, updateContract,
  type AccessDecision, type AccessRequest, type AccessStatus, type Integration,
} from '../../services/ops/integrate'
import InfoTip from '../../components/InfoTip'
import type { GlossaryKey } from '../../lib/glossary'
import TryItPanel from '../../components/TryItPanel'
import Disclosure from '../../components/Disclosure'
import ReuseChecklist from '../../components/ReuseChecklist'
import { errorMessage, Loading, type TabProps, useReloadOn } from './shared'

const ACCESS_PILL: Record<AccessStatus, string> = {
  pending: 'status-review', approved: 'status-complete', rejected: 'status-rejected', revoked: 'status-pending',
}
const ENDPOINT_WARNING: Record<string, string> = {
  missing: 'No endpoint recorded.',
  observability: 'This is a tracing URL (e.g. Phoenix), not the agent’s own API.',
  invalid: 'Not an http(s) URL or path.',
}

function fmtDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—'
}

function lines(value: string): string[] {
  return value.split('\n').map(s => s.trim()).filter(Boolean)
}

function Section({ title, tip, hint, action, children }: {
  title: string; tip?: GlossaryKey; hint?: string; action?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <section className="rounded-2xl border border-slate-200/80 bg-white p-5 space-y-3 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <span className="mt-1 h-4 w-1 shrink-0 rounded-full bg-gradient-to-b from-zen-400 to-zen-700" aria-hidden />
          <div>
            <h3 className="text-[16px] font-extrabold text-slate-900">{title}{tip && <> <InfoTip term={tip} /></>}</h3>
            {hint && <p className="text-[13px] text-slate-600 mt-0.5">{hint}</p>}
          </div>
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

function Chips({ items, empty, tone = 'gray' }: { items: string[]; empty: string; tone?: 'gray' | 'teal' | 'emerald' }) {
  if (!items.length) return <span className="text-xs text-slate-500">{empty}</span>
  const cls = {
    gray: 'bg-gray-50 text-slate-700 ring-gray-200',
    teal: 'bg-teal-50 text-teal-700 ring-teal-200',
    emerald: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  }[tone]
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map(i => <span key={i} className={`text-xs px-2 py-0.5 rounded ring-1 ${cls}`}>{i}</span>)}
    </div>
  )
}

function ContractSection({ agentId, data, onSaved }: { agentId: string; data: Integration; onSaved: () => Promise<void> }) {
  const c = data.contract
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState({
    api_endpoint: '', capabilities: '', inputs: '', outputs: '', sla: '', rate_limit: '', owner_contact: '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // The contract as it was when the form was opened, in the shape that is saved.
  const opened = useRef<Record<string, unknown> | null>(null)

  function startEdit() {
    setForm({
      api_endpoint: c.apiEndpoint || '', capabilities: c.capabilities.join('\n'), inputs: c.inputs.join('\n'),
      outputs: c.outputs.join('\n'), sla: c.sla || '', rate_limit: c.rateLimit || '', owner_contact: c.ownerContact || '',
    })
    opened.current = {
      api_endpoint: c.apiEndpoint || '', capabilities: lines(c.capabilities.join('\n')), inputs: lines(c.inputs.join('\n')),
      outputs: lines(c.outputs.join('\n')), sla: c.sla || '', rate_limit: c.rateLimit || '', owner_contact: c.ownerContact || '',
    }
    setError(null)
    setEditing(true)
  }

  async function save() {
    setSaving(true)
    setError(null)
    try {
      // Only what the person changed is sent: a field the registry filled in while the form was open is not wiped.
      const now = {
        api_endpoint: form.api_endpoint, capabilities: lines(form.capabilities), inputs: lines(form.inputs),
        outputs: lines(form.outputs), sla: form.sla, rate_limit: form.rate_limit, owner_contact: form.owner_contact,
      }
      const was = opened.current ?? {}
      const changed = Object.fromEntries(Object.entries(now).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify((was as Record<string, unknown>)[k])))
      if (Object.keys(changed).length) await updateContract(agentId, changed)
      // Reload before closing, so the view never flashes the old values.
      await onSaved()
      setEditing(false)
    } catch (e) {
      setError(errorMessage(e, 'Could not save the contract'))
    } finally {
      setSaving(false)
    }
  }

  const label = 'block text-xs font-semibold uppercase text-slate-600 mb-1 tracking-wide'
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }))

  if (editing) {
    return (
      <Section title="Contract" tip="contract" hint="What a consuming team needs to call this agent. One entry per line for lists.">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="md:col-span-2">
            <div className="flex items-center gap-1">
              <label className={label}>API endpoint</label>
              <InfoTip term="api_endpoint" className="-my-0.5 mb-1" />
            </div>
            <input className="input font-mono text-xs" value={form.api_endpoint} onChange={set('api_endpoint')} placeholder="https://… or /agents/v1/…" />
          </div>
          <div className="md:col-span-2">
            <div className="flex items-center gap-1">
              <label className={label}>Capabilities</label>
              <InfoTip term="capabilities" className="-my-0.5 mb-1" />
            </div>
            <textarea className="input text-xs" rows={3} value={form.capabilities} onChange={set('capabilities')} placeholder={'KYC document extraction\nAddress verification'} />
          </div>
          <div>
            <label className={label}>Inputs</label>
            <textarea className="input text-xs" rows={3} value={form.inputs} onChange={set('inputs')} placeholder="Vendor invoice (PDF)" />
          </div>
          <div>
            <label className={label}>Outputs</label>
            <textarea className="input text-xs" rows={3} value={form.outputs} onChange={set('outputs')} placeholder="Match disposition" />
          </div>
          <div>
            <div className="flex items-center gap-1">
              <label className={label}>SLA</label>
              <InfoTip term="sla" className="-my-0.5 mb-1" />
            </div>
            <input className="input text-xs" value={form.sla} onChange={set('sla')} placeholder="99.5% uptime, P95 < 2s" />
          </div>
          <div>
            <label className={label}>Rate limit</label>
            <input className="input text-xs" value={form.rate_limit} onChange={set('rate_limit')} placeholder="10 requests/second per team" />
          </div>
          <div className="md:col-span-2">
            <label className={label}>Owner contact</label>
            <input className="input text-xs" value={form.owner_contact} onChange={set('owner_contact')} placeholder="team-channel or email" />
          </div>
        </div>
        {error && <div className="rounded-xl bg-rose-50 border border-rose-200 px-3 py-2 text-xs text-rose-700">{error}</div>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-secondary btn-sm" onClick={() => setEditing(false)}>Cancel</button>
          <button type="button" className="btn-primary btn-sm" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save contract'}</button>
        </div>
      </Section>
    )
  }

  return (
    <Section
      title="Contract"
      tip="contract"
      hint="What a consuming team needs to call this agent."
      action={<button type="button" className="btn-ghost btn-sm flex items-center gap-1" onClick={startEdit}><Pencil size={13} /> Edit</button>}
    >
      <dl className="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-x-4 gap-y-2.5 text-sm" data-testid="contract">
        <dt className="text-xs font-semibold uppercase text-slate-500 pt-0.5">Endpoint</dt>
        <dd>
          {c.apiEndpoint ? <code className="font-mono text-xs text-slate-800 break-all">{c.apiEndpoint}</code> : <span className="text-slate-500 text-xs">Not recorded</span>}
          {c.endpointKind !== 'app' && c.apiEndpoint && <div className="text-xs text-amber-700 mt-0.5">{ENDPOINT_WARNING[c.endpointKind]}</div>}
          {c.endpointAdvice && (
            <div className="mt-1"><Disclosure tone="warn" testId="endpoint-advice"
              summary={c.endpointAdvice.looksLike === 'frontend' ? 'Looks like the app’s web page, not its API.' : 'This is a tracing URL, not the agent’s API.'}>
              <p>{c.endpointAdvice.message}</p>
              <div className="mt-1.5 font-medium">Where to get the right one:</div>
              <ul className="list-disc pl-4 mt-0.5 space-y-0.5">
                {c.endpointAdvice.where.map(w => <li key={w}>{w}</li>)}
              </ul>
            </Disclosure></div>
          )}
        </dd>
        <dt className="text-xs font-semibold uppercase text-slate-500 pt-0.5">Capabilities</dt>
        <dd><Chips items={c.capabilities} empty="None listed" tone="teal" /></dd>
        <dt className="text-xs font-semibold uppercase text-slate-500 pt-0.5">Input</dt>
        <dd><Chips items={c.inputs} empty="Not described" /></dd>
        <dt className="text-xs font-semibold uppercase text-slate-500 pt-0.5">Output</dt>
        <dd><Chips items={c.outputs} empty="Not described" /></dd>
        <dt className="text-xs font-semibold uppercase text-slate-500 pt-0.5">SLA</dt>
        <dd className="text-slate-700">{c.sla || <span className="text-slate-500 text-xs">Not recorded</span>}</dd>
        <dt className="text-xs font-semibold uppercase text-slate-500 pt-0.5">Rate limit</dt>
        <dd className="text-slate-700">{c.rateLimit || <span className="text-slate-500 text-xs">Not recorded</span>}</dd>
        <dt className="text-xs font-semibold uppercase text-slate-500 pt-0.5">Owner</dt>
        <dd className="text-slate-700">{c.owner || '—'}{c.ownerContact && <span className="text-slate-600"> · {c.ownerContact}</span>}</dd>
      </dl>
      {data.gaps.length > 0 && (
        <div className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-slate-700" data-testid="contract-gaps">
          <span className="font-semibold text-slate-700">Missing from the contract:</span>
          <ul className="list-disc pl-4 mt-1 space-y-0.5">{data.gaps.map(g => <li key={g}>{g}</li>)}</ul>
        </div>
      )}
    </Section>
  )
}

function RequestRow({ agentId, req, me, selfAllowed, onDone }: {
  agentId: string; req: AccessRequest; me: string | null; selfAllowed: boolean; onDone: () => void
}) {
  const [pending, setPending] = useState<AccessDecision | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const own = me != null && req.requesterId === me
  const blocked = own && !selfAllowed

  async function decide(decision: AccessDecision) {
    setBusy(true)
    setError(null)
    try {
      await decideAccess(agentId, req.id, decision, note.trim() || undefined)
      setPending(null)
      setNote('')
      onDone()
    } catch (e) {
      setError(errorMessage(e, 'Could not record the decision'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="py-3 space-y-1.5" data-testid="access-request">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-slate-900 text-sm">{req.team}</span>
        <span className={ACCESS_PILL[req.status]}>{req.status}</span>
        <span className="text-xs text-slate-500">requested by {req.requesterName || req.requesterId} · {fmtDate(req.createdAt)}</span>
        <div className="ml-auto flex gap-1.5">
          {req.status === 'pending' && (
            <>
              <button type="button" className="btn-success btn-sm" disabled={busy || blocked}
                title={blocked ? 'You cannot approve your own request' : undefined} onClick={() => decide('approve')}>Approve</button>
              <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={() => setPending('reject')}>Reject</button>
            </>
          )}
          {req.status === 'approved' && (
            <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={() => setPending('revoke')}>Revoke</button>
          )}
        </div>
      </div>
      <p className="text-xs text-slate-700">{req.purpose}</p>
      {own && req.status === 'pending' && !selfAllowed && (
        <p className="text-xs text-slate-500">Awaiting a decision from someone other than you.</p>
      )}
      {req.decidedBy && (
        <p className="text-xs text-slate-600">
          {req.status === 'approved' ? 'Approved' : req.status === 'rejected' ? 'Rejected' : 'Revoked'} by {req.decidedBy} · {fmtDate(req.decidedAt)}
          {req.decisionNote && <> — “{req.decisionNote}”</>}
        </p>
      )}
      {pending && (
        <div className="flex gap-2 pt-1">
          <input className="input text-xs flex-1" autoFocus value={note} onChange={e => setNote(e.target.value)}
            placeholder={pending === 'reject' ? 'Why is this rejected? (required)' : 'Why is access revoked? (required)'} />
          <button type="button" className="btn-danger btn-sm" disabled={busy || !note.trim()} onClick={() => decide(pending)}>
            {pending === 'reject' ? 'Reject' : 'Revoke'}
          </button>
          <button type="button" className="btn-ghost btn-sm" onClick={() => { setPending(null); setNote('') }}>Cancel</button>
        </div>
      )}
      {error && <p className="text-xs text-rose-700">{error}</p>}
    </li>
  )
}

function AccessSection({ agentId, data, deprecated, me, onChanged }: {
  agentId: string; data: Integration; deprecated: boolean; me: string | null; onChanged: () => void
}) {
  const [team, setTeam] = useState('')
  const [purpose, setPurpose] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await requestAccess(agentId, team.trim(), purpose.trim())
      setTeam('')
      setPurpose('')
      onChanged()
    } catch (err) {
      setError(errorMessage(err, 'Could not submit the request'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Section title="Access" tip="access_request" hint="Teams ask to consume this agent; the owner approves. An approved team is added to the agent's consumers.">
      {deprecated ? (
        <p className="text-xs text-slate-600">This agent is deprecated and is not taking new consumers.</p>
      ) : (
        <form onSubmit={submit} className="grid grid-cols-1 md:grid-cols-[1fr_2fr_auto] gap-2 items-start" data-testid="request-access-form">
          <input className="input text-sm" value={team} onChange={e => setTeam(e.target.value)} placeholder="Your team" aria-label="Team" />
          <input className="input text-sm" value={purpose} onChange={e => setPurpose(e.target.value)} placeholder="What will you use it for? (at least 10 characters)" aria-label="Purpose" />
          <button type="submit" className="btn-primary btn-sm h-full" disabled={busy || team.trim().length < 2 || purpose.trim().length < 10}>
            {busy ? 'Sending…' : 'Request access'}
          </button>
        </form>
      )}
      {error && <div className="rounded-xl bg-rose-50 border border-rose-200 px-3 py-2 text-xs text-rose-700">{error}</div>}
      {data.accessRequests.length === 0
        ? <p className="text-xs text-slate-500">No access requests yet.</p>
        : <ul className="divide-y divide-gray-100">{data.accessRequests.map(r =>
            <RequestRow key={r.id} agentId={agentId} req={r} me={me} selfAllowed={data.selfApprovalAllowed} onDone={onChanged} />)}</ul>}
    </Section>
  )
}

export default function IntegrateTab({ agent, agentId, onChanged, dataVersion }: TabProps) {
  const [data, setData] = useState<Integration | null>(null)
  const [me, setMe] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const loaded = useRef(false)

  const load = useCallback(async () => {
    try {
      setData((await getIntegration(agentId)).data)
      loaded.current = true
      setError(null)
    } catch (e) {
      // Once the tab is showing, a failed reload keeps it (and any open form) rather than replacing it.
      if (!loaded.current) setError(errorMessage(e, 'Could not load the integration details'))
    }
  }, [agentId])

  useEffect(() => { load() }, [load])
  useReloadOn(dataVersion, load)
  useEffect(() => { getMe().then(r => setMe(r.data.user_id)).catch(() => setMe(null)) }, [])

  if (error) return <div className="rounded-xl bg-rose-50 border border-rose-200 px-3 py-2 text-sm text-rose-700">{error}</div>
  if (!data) return <Loading text="Loading integration details…" />

  // Consumers appear on the agent header, Overview and graphs, so those reload too.
  const changed = async () => { onChanged(); await load() }

  return (
    <div className="space-y-4" data-testid="integrate-tab">
      {agent.stage !== 'Deprecated' && <ReuseChecklist reuse={data.reuse} agentId={agentId} />}


      <ContractSection agentId={agentId} data={data} onSaved={changed} />

      <Section title="Try it" tip="try_it" hint="Call this agent with your own input before asking for access.">
        <TryItPanel agentId={agentId} tryIt={data.tryIt} endpointAdvice={data.contract.endpointAdvice} onEndpointSaved={changed} />
      </Section>

      <AccessSection agentId={agentId} data={data} deprecated={agent.stage === 'Deprecated'} me={me} onChanged={changed} />

      <Section title="Consumers" tip="consumers" hint="Everyone consuming this agent. Each one appears in the dependency graph and counts toward its blast radius.">
        <div className="space-y-2 text-sm">
          <div>
            <div className="text-xs font-semibold uppercase text-slate-500 mb-1">Approved teams</div>
            <Chips items={data.consumers.approvedTeams} empty="None yet" tone="emerald" />
          </div>
          <div>
            <div className="text-xs font-semibold uppercase text-slate-500 mb-1">Declared by the owner</div>
            <Chips items={data.consumers.declared} empty="None declared" />
          </div>
          <Link to="/dependencies" className="inline-block text-xs text-zen-700 hover:underline">Open the dependency graph →</Link>
        </div>
      </Section>

      {data.reuseCheck.checked.length > 0 && (
        <Section title="Reuse check at registration" tip="similar_agents" hint="Similar agents shown to the team that registered this one, and why none of them fit.">
          <ul className="text-sm space-y-1">
            {data.reuseCheck.checked.map(c => (
              <li key={c.id} className="flex items-center gap-2">
                <Link to={`/agents/${c.id}`} className="text-zen-700 hover:underline">{c.name}</Link>
                <span className="text-xs text-slate-500">{Math.round(c.score * 100)}% match</span>
                {c.certified && <span className="status-complete">Certified</span>}
              </li>
            ))}
          </ul>
          <blockquote className="border-l-2 border-gray-200 pl-3 text-sm text-slate-700">{data.reuseCheck.justification}</blockquote>
        </Section>
      )}
    </div>
  )
}
