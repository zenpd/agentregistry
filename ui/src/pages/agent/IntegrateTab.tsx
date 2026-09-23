import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, AlertTriangle, Pencil } from 'lucide-react'
import { getMe, type ReuseStatus } from '../../services/api'
import {
  decideAccess, getIntegration, requestAccess, updateContract,
  type AccessDecision, type AccessRequest, type AccessStatus, type Integration,
} from '../../services/ops/integrate'
import TryItPanel from '../../components/TryItPanel'
import { errorMessage, Loading, type TabProps } from './shared'

const GATE_LABEL: Record<string, string> = {
  arb: 'Architecture Review Board', security: 'Security Review', dp: 'Data Protection Review',
}
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

function Section({ title, hint, action, children }: {
  title: string; hint?: string; action?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <section className="rounded-xl border border-gray-100 p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
          {hint && <p className="text-xs text-gray-500 mt-0.5">{hint}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

function Chips({ items, empty, tone = 'gray' }: { items: string[]; empty: string; tone?: 'gray' | 'teal' | 'emerald' }) {
  if (!items.length) return <span className="text-xs text-gray-400">{empty}</span>
  const cls = {
    gray: 'bg-gray-50 text-gray-700 ring-gray-200',
    teal: 'bg-teal-50 text-teal-700 ring-teal-200',
    emerald: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  }[tone]
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map(i => <span key={i} className={`text-xs px-2 py-0.5 rounded ring-1 ${cls}`}>{i}</span>)}
    </div>
  )
}

export function ReuseBanner({ reuse }: { reuse: ReuseStatus }) {
  if (reuse.certified) {
    return (
      <div className="flex items-start gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3" data-testid="reuse-banner">
        <CheckCircle2 size={18} className="text-emerald-600 mt-0.5 shrink-0" />
        <div className="text-sm">
          <div className="font-semibold text-emerald-800">Certified for reuse</div>
          <div className="text-emerald-700 text-xs mt-0.5">
            In Production, every governance gate approved, and no HIGH or CRITICAL risk open.
            {reuse.withConditions.length > 0 && (
              <> Approved with conditions: {reuse.withConditions.map(g => GATE_LABEL[g] || g).join(', ')}. Check
              the Governance tab before relying on it.</>
            )}
          </div>
        </div>
      </div>
    )
  }
  return (
    <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3" data-testid="reuse-banner">
      <AlertTriangle size={18} className="text-amber-600 mt-0.5 shrink-0" />
      <div className="text-sm">
        <div className="font-semibold text-amber-800">Not certified for reuse</div>
        <ul className="text-amber-800 text-xs mt-1 list-disc pl-4 space-y-0.5">
          {reuse.unmet.map((u, i) => <li key={i}>{u.message}</li>)}
        </ul>
      </div>
    </div>
  )
}

function ContractSection({ agentId, data, onSaved }: { agentId: string; data: Integration; onSaved: () => void }) {
  const c = data.contract
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState({
    api_endpoint: '', capabilities: '', inputs: '', outputs: '', sla: '', rate_limit: '', owner_contact: '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function startEdit() {
    setForm({
      api_endpoint: c.apiEndpoint || '', capabilities: c.capabilities.join('\n'), inputs: c.inputs.join('\n'),
      outputs: c.outputs.join('\n'), sla: c.sla || '', rate_limit: c.rateLimit || '', owner_contact: c.ownerContact || '',
    })
    setError(null)
    setEditing(true)
  }

  async function save() {
    setSaving(true)
    setError(null)
    try {
      await updateContract(agentId, {
        api_endpoint: form.api_endpoint, capabilities: lines(form.capabilities), inputs: lines(form.inputs),
        outputs: lines(form.outputs), sla: form.sla, rate_limit: form.rate_limit, owner_contact: form.owner_contact,
      })
      setEditing(false)
      onSaved()
    } catch (e) {
      setError(errorMessage(e, 'Could not save the contract'))
    } finally {
      setSaving(false)
    }
  }

  const label = 'block text-xs font-semibold uppercase text-gray-500 mb-1 tracking-wide'
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }))

  if (editing) {
    return (
      <Section title="Contract" hint="What a consuming team needs to call this agent. One entry per line for lists.">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="md:col-span-2">
            <label className={label}>API endpoint</label>
            <input className="input font-mono text-xs" value={form.api_endpoint} onChange={set('api_endpoint')} placeholder="https://… or /agents/v1/…" />
          </div>
          <div className="md:col-span-2">
            <label className={label}>Capabilities</label>
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
            <label className={label}>SLA</label>
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
      hint="What a consuming team needs to call this agent."
      action={<button type="button" className="btn-ghost btn-sm flex items-center gap-1" onClick={startEdit}><Pencil size={13} /> Edit</button>}
    >
      <dl className="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-x-4 gap-y-2.5 text-sm" data-testid="contract">
        <dt className="text-xs font-semibold uppercase text-gray-400 pt-0.5">Endpoint</dt>
        <dd>
          {c.apiEndpoint ? <code className="font-mono text-xs text-gray-800 break-all">{c.apiEndpoint}</code> : <span className="text-gray-400 text-xs">Not recorded</span>}
          {c.endpointKind !== 'app' && c.apiEndpoint && <div className="text-xs text-amber-700 mt-0.5">{ENDPOINT_WARNING[c.endpointKind]}</div>}
          {c.endpointAdvice && (
            <div className="mt-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900" data-testid="endpoint-advice">
              <div className="font-medium">
                {c.endpointAdvice.looksLike === 'frontend' ? 'This does not look like an API endpoint.' : 'This is a tracing endpoint, not an API.'}
              </div>
              <p className="mt-0.5">{c.endpointAdvice.message}</p>
              <div className="mt-1.5 font-medium">Where to get the right one:</div>
              <ul className="list-disc pl-4 mt-0.5 space-y-0.5">
                {c.endpointAdvice.where.map(w => <li key={w}>{w}</li>)}
              </ul>
            </div>
          )}
        </dd>
        <dt className="text-xs font-semibold uppercase text-gray-400 pt-0.5">Capabilities</dt>
        <dd><Chips items={c.capabilities} empty="None listed" tone="teal" /></dd>
        <dt className="text-xs font-semibold uppercase text-gray-400 pt-0.5">Input</dt>
        <dd><Chips items={c.inputs} empty="Not described" /></dd>
        <dt className="text-xs font-semibold uppercase text-gray-400 pt-0.5">Output</dt>
        <dd><Chips items={c.outputs} empty="Not described" /></dd>
        <dt className="text-xs font-semibold uppercase text-gray-400 pt-0.5">SLA</dt>
        <dd className="text-gray-700">{c.sla || <span className="text-gray-400 text-xs">Not recorded</span>}</dd>
        <dt className="text-xs font-semibold uppercase text-gray-400 pt-0.5">Rate limit</dt>
        <dd className="text-gray-700">{c.rateLimit || <span className="text-gray-400 text-xs">Not recorded</span>}</dd>
        <dt className="text-xs font-semibold uppercase text-gray-400 pt-0.5">Owner</dt>
        <dd className="text-gray-700">{c.owner || '—'}{c.ownerContact && <span className="text-gray-500"> · {c.ownerContact}</span>}</dd>
      </dl>
      {data.gaps.length > 0 && (
        <div className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600" data-testid="contract-gaps">
          <span className="font-semibold text-gray-700">Missing from the contract:</span>
          <ul className="list-disc pl-4 mt-1 space-y-0.5">{data.gaps.map(g => <li key={g}>{g}</li>)}</ul>
        </div>
      )}
    </Section>
  )
}

function RequestRow({ agentId, req, me, onDone }: { agentId: string; req: AccessRequest; me: string | null; onDone: () => void }) {
  const [pending, setPending] = useState<AccessDecision | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const own = me != null && req.requesterId === me

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
        <span className="font-medium text-gray-900 text-sm">{req.team}</span>
        <span className={ACCESS_PILL[req.status]}>{req.status}</span>
        <span className="text-xs text-gray-400">requested by {req.requesterName || req.requesterId} · {fmtDate(req.createdAt)}</span>
        <div className="ml-auto flex gap-1.5">
          {req.status === 'pending' && (
            <>
              <button type="button" className="btn-success btn-sm" disabled={busy || own}
                title={own ? 'You cannot approve your own request' : undefined} onClick={() => decide('approve')}>Approve</button>
              <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={() => setPending('reject')}>Reject</button>
            </>
          )}
          {req.status === 'approved' && (
            <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={() => setPending('revoke')}>Revoke</button>
          )}
        </div>
      </div>
      <p className="text-xs text-gray-600">{req.purpose}</p>
      {own && req.status === 'pending' && <p className="text-xs text-gray-400">Awaiting a decision from someone other than you.</p>}
      {req.decidedBy && (
        <p className="text-xs text-gray-500">
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
    <Section title="Access" hint="Teams ask to consume this agent; the owner approves. An approved team is added to the agent's consumers.">
      {deprecated ? (
        <p className="text-xs text-gray-500">This agent is deprecated and is not taking new consumers.</p>
      ) : (
        <form onSubmit={submit} className="grid grid-cols-1 md:grid-cols-[1fr_2fr_auto] gap-2 items-start" data-testid="request-access-form">
          <input className="input text-sm" value={team} onChange={e => setTeam(e.target.value)} placeholder="Your team" aria-label="Team" />
          <input className="input text-sm" value={purpose} onChange={e => setPurpose(e.target.value)} placeholder="What will you use it for? (at least 10 characters)" aria-label="Purpose" />
          <button type="submit" className="btn-primary btn-sm h-full" disabled={busy || team.trim().length < 2 || purpose.trim().length < 10}>
            {busy ? 'Sending…' : 'Request access'}
          </button>
        </form>
      )}
      {!deprecated && !data.reuse.certified && (
        <p className="text-xs text-amber-700">This agent is not certified for reuse yet (see above). You can still ask; the owner decides.</p>
      )}
      {error && <div className="rounded-xl bg-rose-50 border border-rose-200 px-3 py-2 text-xs text-rose-700">{error}</div>}
      {data.accessRequests.length === 0
        ? <p className="text-xs text-gray-400">No access requests yet.</p>
        : <ul className="divide-y divide-gray-100">{data.accessRequests.map(r =>
            <RequestRow key={r.id} agentId={agentId} req={r} me={me} onDone={onChanged} />)}</ul>}
    </Section>
  )
}

export default function IntegrateTab({ agent, agentId, onChanged }: TabProps) {
  const [data, setData] = useState<Integration | null>(null)
  const [me, setMe] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setData((await getIntegration(agentId)).data)
      setError(null)
    } catch (e) {
      setError(errorMessage(e, 'Could not load the integration details'))
    }
  }, [agentId])

  useEffect(() => { load() }, [load])
  useEffect(() => { getMe().then(r => setMe(r.data.user_id)).catch(() => setMe(null)) }, [])

  if (error) return <div className="rounded-xl bg-rose-50 border border-rose-200 px-3 py-2 text-sm text-rose-700">{error}</div>
  if (!data) return <Loading text="Loading integration details…" />

  // Consumers appear on the agent header, Overview and graphs, so those reload too.
  const changed = () => { load(); onChanged() }

  return (
    <div className="space-y-4" data-testid="integrate-tab">
      <ReuseBanner reuse={data.reuse} />

      <ContractSection agentId={agentId} data={data} onSaved={changed} />

      <Section title="Try it" hint="Call this agent with your own input before asking for access.">
        <TryItPanel agentId={agentId} tryIt={data.tryIt} endpointAdvice={data.contract.endpointAdvice} />
      </Section>

      <AccessSection agentId={agentId} data={data} deprecated={agent.stage === 'Deprecated'} me={me} onChanged={changed} />

      <Section title="Consumers" hint="Everyone consuming this agent. Each one appears in the dependency graph and counts toward its blast radius.">
        <div className="space-y-2 text-sm">
          <div>
            <div className="text-xs font-semibold uppercase text-gray-400 mb-1">Approved teams</div>
            <Chips items={data.consumers.approvedTeams} empty="None yet" tone="emerald" />
          </div>
          <div>
            <div className="text-xs font-semibold uppercase text-gray-400 mb-1">Declared by the owner</div>
            <Chips items={data.consumers.declared} empty="None declared" />
          </div>
          <Link to="/dependencies" className="inline-block text-xs text-teal-700 hover:underline">Open the dependency graph →</Link>
        </div>
      </Section>

      {data.reuseCheck.checked.length > 0 && (
        <Section title="Reuse check at registration" hint="Similar agents shown to the team that registered this one, and why none of them fit.">
          <ul className="text-sm space-y-1">
            {data.reuseCheck.checked.map(c => (
              <li key={c.id} className="flex items-center gap-2">
                <Link to={`/agents/${c.id}`} className="text-teal-700 hover:underline">{c.name}</Link>
                <span className="text-xs text-gray-400">{Math.round(c.score * 100)}% match</span>
                {c.certified && <span className="status-complete">Certified</span>}
              </li>
            ))}
          </ul>
          <blockquote className="border-l-2 border-gray-200 pl-3 text-sm text-gray-700">{data.reuseCheck.justification}</blockquote>
        </Section>
      )}
    </div>
  )
}
