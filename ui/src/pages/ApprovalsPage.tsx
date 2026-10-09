import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight, BadgeCheck, CheckCircle2, Clock, History, KeyRound, Radar, ShieldAlert, ShieldCheck,
} from 'lucide-react'
import {
  APPROVALS_CHANGED, getApprovalHistory, getApprovals, type ApprovalAccessRequest, type ApprovalReview, type Approvals, type DecisionRow,
} from '../services/ops/approvals'
import { decideAccess } from '../services/ops/integrate'
import { dismissDiscovery } from '../services/api'
import InfoTip from '../components/InfoTip'
import type { GlossaryKey } from '../lib/glossary'
import { STAGE_PILL, errorMessage } from './agent/shared'

type Queue = 'all' | 'access' | 'reviews' | 'discoveries'

function fmtDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—'
}

// "waiting 3 days": how long something has been waiting is what an approver sorts by.
function waiting(iso: string | null): string {
  if (!iso) return ''
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
  return days <= 0 ? 'requested today' : days === 1 ? 'waiting 1 day' : `waiting ${days} days`
}

// Everything waiting for a decision across the registry. Access requests are
// decided here; gates and discoveries open where their full workflow lives.
export default function ApprovalsPage() {
  const [data, setData] = useState<Approvals | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [queue, setQueue] = useState<Queue>('all')
  const [view, setView] = useState<'waiting' | 'decided'>('waiting')

  const load = useCallback(async () => {
    try {
      setData((await getApprovals()).data)
      setError(null)
    } catch (e) {
      setError(errorMessage(e, 'Could not load approvals'))
    }
  }, [])

  useEffect(() => { load() }, [load])

  const decided = useCallback(async () => {
    await load()
    window.dispatchEvent(new Event(APPROVALS_CHANGED))
  }, [load])

  if (error && !data) return <div className="p-8 text-center text-rose-500">Error: {error}</div>
  if (!data) return <div className="p-8 text-center text-slate-600">Loading…</div>

  const { counts } = data
  const show = (q: Queue) => queue === 'all' || queue === q

  return (
    <div className="space-y-5 animate-fade-in max-w-5xl">
      <div>
        <h1 className="text-2xl font-bold gradient-text">Approvals <InfoTip term="approvals_inbox" /></h1>
        <p className="text-slate-600 mt-0.5">
          Everything waiting for a decision across the registry: requests to use an agent, reviews submitted for a decision,
          and governance findings on registered agents.
        </p>
      </div>

      <div className="inline-flex rounded-full bg-slate-100 p-1" role="tablist" aria-label="Waiting or decided">
        {([['waiting', 'Waiting for a decision'], ['decided', 'Decided']] as const).map(([k, label]) => (
          <button key={k} type="button" role="tab" aria-selected={view === k} onClick={() => setView(k)} data-testid={`view-${k}`}
            className={`rounded-full px-4 py-1.5 text-[13px] font-semibold ${view === k ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'}`}>
            {label}
          </button>
        ))}
      </div>

      {view === 'decided' && <DecidedList />}

      {view === 'waiting' && <>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4" role="tablist" aria-label="Approval queues">
        <QueueTile active={queue === 'access'} onClick={() => setQueue(queue === 'access' ? 'all' : 'access')}
          icon={<KeyRound size={20} />} tone="indigo" count={counts.accessRequests}
          label="Access requests" sub="Teams waiting to use an agent" testId="queue-access" />
        <QueueTile active={queue === 'reviews'} onClick={() => setQueue(queue === 'reviews' ? 'all' : 'reviews')}
          icon={<ShieldCheck size={20} />} tone="amber" count={counts.reviews + counts.classifications}
          label="Reviews awaiting decision" sub="Reviews and classifications" testId="queue-reviews" />
        <QueueTile active={queue === 'discoveries'} onClick={() => setQueue(queue === 'discoveries' ? 'all' : 'discoveries')}
          icon={<Radar size={20} />} tone="orange" count={counts.discoveries}
          label="Governance findings" sub="Checks on registered agents" testId="queue-discoveries" />
      </div>

      {counts.total === 0 && (
        <div className="card p-10 text-center" data-testid="all-clear">
          <CheckCircle2 size={36} className="mx-auto text-emerald-500" />
          <p className="mt-3 text-lg font-bold text-slate-900">All caught up</p>
          <p className="text-sm text-slate-600">Nothing is waiting for a decision.</p>
        </div>
      )}

      {counts.total > 0 && queue !== 'all' && (
        <button type="button" onClick={() => setQueue('all')} className="text-sm font-medium text-zen-700 hover:underline">
          ← Show every queue
        </button>
      )}

      {show('access') && counts.total > 0 && (
        <QueueSection title="Access requests" tip="access_request" count={counts.accessRequests}
          hint={`A team asks to consume an agent. Approving adds the team to the agent's consumers.${
            data.selfApprovalAllowed ? '' : ' You cannot approve a request you raised.'}`}
          empty="No access requests waiting." testId="section-access">
          {data.accessRequests.map(r => <AccessRequestRow key={r.id} req={r} selfAllowed={data.selfApprovalAllowed} onDecided={decided} />)}
        </QueueSection>
      )}

      {show('reviews') && counts.total > 0 && (
        <QueueSection title="Reviews awaiting decision" tip="gate" count={counts.reviews + counts.classifications}
          hint={`Reviews the owner has submitted, in this order: open critical findings first, then open high findings, then risk level (high first), then the longest wait. A review is overdue after ${data.reviews[0]?.slaDays ?? 5} days. The reviewer decides on the agent's Governance tab, where the evidence and checklist are.`}
          empty="No reviews waiting." testId="section-reviews">
          {data.reviews.map(g => <ReviewRow key={`${g.agentId}-${g.gate}`} g={g} />)}
          {data.classifications.map(c => (
            <li key={c.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-violet-200 bg-white px-4 py-3" data-testid="classification-row">
              <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-violet-50 text-violet-600"><ShieldCheck size={18} /></div>
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-slate-900">Classification</span>
                  <span className="text-slate-500">·</span>
                  <Link to={`/agents/${c.agentId}`} className="font-medium text-slate-700 hover:text-zen-700">{c.agentName}</Link>
                </div>
                <div className="mt-0.5 text-[13px] text-slate-600">
                  Proposed {c.category}, risk level {c.riskLevel}, by {c.proposedBy || 'the owner'} ·{' '}
                  {c.daysWaiting ? `waiting ${c.daysWaiting} day${c.daysWaiting === 1 ? '' : 's'}` : 'since today'}. Needs confirmation from an Architect Steward, Data Protection Officer or Registry Admin.
                </div>
              </div>
              <Link to={`/agents/${c.agentId}?tab=governance`}
                className="inline-flex items-center gap-1 rounded-full border border-zen-200 bg-zen-50 px-3 py-1.5 text-[13px] font-semibold text-zen-700 hover:bg-zen-100">
                Open classification <ArrowRight size={14} />
              </Link>
            </li>
          ))}
        </QueueSection>
      )}

      {show('discoveries') && counts.total > 0 && (
        <QueueSection title="Governance findings" tip="governance_findings" count={counts.discoveries}
          hint="Checks on registered agents that look off (for example stalled or unreviewed). AI found in Phoenix is on the Discovered page."
          empty="No governance findings waiting." testId="section-discoveries">
          {data.discoveries.map(d => (
            <li key={d.id} className="flex flex-wrap items-start gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3" data-testid="discovery-row">
              <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-orange-50 text-orange-600"><Radar size={18} /></div>
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-slate-900">{d.suspectedName}</span>
                  <span className={`rounded-full px-2 py-0.5 text-[12px] font-bold ring-1 ${
                    d.confidence >= 85 ? 'bg-rose-50 text-rose-700 ring-rose-200' : d.confidence >= 70 ? 'bg-amber-50 text-amber-700 ring-amber-200' : 'bg-slate-100 text-slate-700 ring-slate-200'
                  }`}>{d.confidence}% sure this needs action</span>
                </div>
                <div className="mt-0.5 text-[13px] text-slate-600">
                  {d.suspectedDept || 'No business unit'} · raised by {d.source} · first raised {fmtDate(d.firstSeen)}
                </div>
                {d.signal && <p className="mt-1 text-[13px] text-slate-700">{d.signal}</p>}
              </div>
              <div className="flex items-center gap-2">
                {d.agentId && (
                  <Link to={`/agents/${d.agentId}?tab=governance`} data-testid="finding-open"
                    className="inline-flex items-center gap-1 rounded-full border border-zen-200 bg-zen-50 px-3 py-1.5 text-[13px] font-semibold text-zen-700 hover:bg-zen-100">
                    Open the agent <ArrowRight size={14} />
                  </Link>
                )}
                <button type="button" className="btn-secondary btn-sm" data-testid="finding-dismiss"
                  onClick={async () => { try { await dismissDiscovery(d.id); await load() } catch (e) { setError(errorMessage(e, 'The finding was not dismissed')) } }}>
                  Dismiss
                </button>
              </div>
            </li>
          ))}
        </QueueSection>
      )}
      </>}
    </div>
  )
}

const TIER_PILL: Record<string, string> = {
  HIGH: 'bg-rose-50 text-rose-700 ring-rose-200',
  MEDIUM: 'bg-amber-50 text-amber-700 ring-amber-200',
  LOW: 'bg-slate-100 text-slate-700 ring-slate-200',
}

function ReviewRow({ g }: { g: ApprovalReview }) {
  const days = g.daysWaiting
  const waited = days === null ? '' : days <= 0 ? 'in review since today' : `in review for ${days} day${days === 1 ? '' : 's'}`
  const nobody = g.deciders.available.length === 0
  return (
    <li className={`flex flex-wrap items-start gap-3 rounded-xl border bg-white px-4 py-3 ${g.overdue ? 'border-rose-200' : 'border-slate-200'}`} data-testid="review-row">
      <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-amber-50 text-amber-600"><ShieldAlert size={18} /></div>
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-slate-900">{g.gateLabel}</span>
          <span className="text-slate-500">·</span>
          <Link to={`/agents/${g.agentId}`} className="font-medium text-slate-700 hover:text-zen-700">{g.agentName}</Link>
          <span className={STAGE_PILL[g.agentStage] || 'status-pending'}>{g.agentStage}</span>
          <span className={`rounded-full px-2 py-0.5 text-[12px] font-bold ring-1 ${TIER_PILL[g.riskTier] || TIER_PILL.LOW}`}>{g.riskTier} risk tier</span>
          {g.criticalFindings > 0 && (
            <span className="rounded-full bg-rose-600 px-2 py-0.5 text-[12px] font-bold text-white" data-testid="critical-findings">
              {g.criticalFindings} open critical finding{g.criticalFindings === 1 ? '' : 's'}
            </span>
          )}
          {g.highFindings > 0 && (
            <span className="rounded-full bg-rose-50 px-2 py-0.5 text-[12px] font-bold text-rose-700 ring-1 ring-rose-200">
              {g.highFindings} open high finding{g.highFindings === 1 ? '' : 's'}
            </span>
          )}
          {g.overdue && (
            <span className="inline-flex items-center gap-1 rounded-full bg-rose-50 px-2 py-0.5 text-[12px] font-bold text-rose-700 ring-1 ring-rose-200" data-testid="overdue">
              <Clock size={12} /> Overdue: more than {g.slaDays} days
            </span>
          )}
        </div>
        <div className="mt-0.5 text-[13px] text-slate-600">
          To be decided by {g.reviewerRole || 'the reviewer'}{g.reviewer ? ` (${g.reviewer})` : ''} · {waited}
        </div>
        <div className="mt-0.5 text-[13px] text-slate-600" data-testid="deciders">
          {nobody
            ? <span className="text-rose-700">No {g.reviewerRole || 'reviewer'} is available. A Registry Admin can decide.</span>
            : <>Can decide now: {g.deciders.available.join(', ')}</>}
          {g.deciders.away.map(a => (
            <span key={a.name} className="ml-2 text-amber-800">
              · {a.name} is away until {fmtDate(a.until)}{a.deputy ? `, deputy ${a.deputy}` : ', no deputy set'}
            </span>
          ))}
        </div>
      </div>
      <Link to={`/agents/${g.agentId}?tab=governance`}
        className="inline-flex items-center gap-1 rounded-full border border-zen-200 bg-zen-50 px-3 py-1.5 text-[13px] font-semibold text-zen-700 hover:bg-zen-100">
        Open review <ArrowRight size={14} />
      </Link>
    </li>
  )
}

// Decisions already made, newest first, from the audit trail.
function DecidedList() {
  const [rows, setRows] = useState<DecisionRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    getApprovalHistory(100).then(r => setRows(r.data.rows)).catch(e => setError(errorMessage(e, 'Could not load decisions')))
  }, [])
  if (error) return <p className="text-sm text-rose-700">{error}</p>
  if (!rows) return <p className="text-sm text-slate-600">Loading…</p>
  return (
    <section className="rounded-2xl border border-slate-200/80 bg-slate-50/60 p-5 shadow-sm" data-testid="section-decided">
      <div className="flex items-center gap-2">
        <History size={16} className="text-slate-600" />
        <h2 className="text-[16px] font-extrabold text-slate-900">Decided</h2>
        <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[12px] font-bold text-slate-700">{rows.length}</span>
      </div>
      <p className="mt-0.5 text-[13px] text-slate-600">
        Gate decisions, access decisions, waivers and stage changes, newest first: the last 100. The Audit Trail page has every event.
      </p>
      {rows.length === 0
        ? <p className="mt-3 text-sm text-slate-600">No decisions recorded yet.</p>
        : (
          <ul className="mt-3 divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white">
            {rows.map((r, i) => (
              <li key={i} className="flex flex-wrap items-start gap-x-3 gap-y-0.5 px-4 py-2.5 text-[13px]" data-testid="decided-row">
                <span className="w-36 shrink-0 text-slate-500">{r.at ? new Date(r.at).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'}</span>
                <span className="w-32 shrink-0 font-medium text-slate-800">{r.actor}</span>
                <span className="w-40 shrink-0 font-semibold text-slate-900">{r.action}</span>
                <span className="flex-1 min-w-[200px] text-slate-700">
                  {r.agentId && r.agentName && <Link to={`/agents/${r.agentId}`} className="font-medium text-zen-700 hover:underline">{r.agentName}</Link>}
                  {r.agentName && r.summary ? ': ' : ''}{r.summary}
                </span>
              </li>
            ))}
          </ul>
        )}
    </section>
  )
}

const TONE = {
  indigo: { tile: 'bg-zen-50 text-zen-600', ring: 'ring-zen-400' },
  amber: { tile: 'bg-amber-50 text-amber-600', ring: 'ring-amber-400' },
  orange: { tile: 'bg-orange-50 text-orange-600', ring: 'ring-orange-400' },
}

function QueueTile({ active, onClick, icon, tone, count, label, sub, testId }: {
  active: boolean; onClick: () => void; icon: React.ReactNode; tone: keyof typeof TONE
  count: number; label: string; sub: string; testId: string
}) {
  return (
    <button type="button" role="tab" aria-selected={active} onClick={onClick} data-testid={testId}
      className={`flex items-center gap-3.5 rounded-2xl bg-white p-4 text-left shadow-sm ring-1 transition-shadow hover:shadow-md ${
        active ? `ring-2 ${TONE[tone].ring}` : 'ring-slate-200/80'
      }`}>
      <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${TONE[tone].tile}`}>{icon}</div>
      <div className="min-w-0">
        <div className="text-[28px] font-extrabold leading-none text-slate-900">{count}</div>
        <div className="mt-1 text-sm font-semibold text-slate-800">{label}</div>
        <div className="text-[12px] text-slate-600">{sub}</div>
      </div>
    </button>
  )
}

function QueueSection({ title, tip, count, hint, empty, testId, children }: {
  title: string; tip?: GlossaryKey; count: number; hint: string; empty: string; testId: string; children: React.ReactNode
}) {
  return (
    <section className="rounded-2xl border border-slate-200/80 bg-slate-50/60 p-5 shadow-sm" data-testid={testId}>
      <div className="flex items-start gap-2.5">
        <span className="mt-1 h-4 w-1 shrink-0 rounded-full bg-gradient-to-b from-zen-400 to-zen-700" aria-hidden />
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h2 className="text-[16px] font-extrabold text-slate-900">{title}{tip && <> <InfoTip term={tip} /></>}</h2>
            <span className={`rounded-full px-2 py-0.5 text-[12px] font-bold ${count ? 'bg-zen-600 text-white' : 'bg-slate-200 text-slate-700'}`}>{count}</span>
          </div>
          <p className="mt-0.5 text-[13px] text-slate-600">{hint}</p>
        </div>
      </div>
      {count === 0
        ? <p className="mt-3 flex items-center gap-2 text-sm text-slate-600"><CheckCircle2 size={16} className="text-emerald-500" /> {empty}</p>
        : <ul className="mt-3 space-y-2">{children}</ul>}
    </section>
  )
}

function AccessRequestRow({ req: r, selfAllowed, onDecided }: { req: ApprovalAccessRequest; selfAllowed: boolean; onDecided: () => Promise<void> }) {
  const blocked = r.mine && !selfAllowed
  const [rejecting, setRejecting] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function decide(decision: 'approve' | 'reject') {
    setBusy(true)
    setError(null)
    try {
      await decideAccess(r.agentId, r.id, decision, decision === 'reject' ? note.trim() : undefined)
      await onDecided()
    } catch (e) {
      setError(errorMessage(e, 'The decision was not recorded'))
      setBusy(false)
    }
  }

  return (
    <li className="rounded-xl border border-slate-200 bg-white px-4 py-3" data-testid="access-row">
      <div className="flex flex-wrap items-start gap-3">
        <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-zen-50 text-zen-600"><KeyRound size={18} /></div>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[15px]">
            <span className="font-semibold text-slate-900">{r.team}</span>
            <span className="text-slate-600">wants to use</span>
            <Link to={`/agents/${r.agentId}?tab=integrate`} className="font-semibold text-zen-700 hover:underline">{r.agentName}</Link>
            {r.agentStage && <span className={STAGE_PILL[r.agentStage] || 'status-pending'}>{r.agentStage}</span>}
            {r.certified
              ? <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[12px] font-bold text-emerald-700 ring-1 ring-emerald-200"><BadgeCheck size={12} /> Certified for reuse</span>
              : <Link to={`/agents/${r.agentId}?tab=integrate`} className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[12px] font-bold text-amber-800 ring-1 ring-amber-200 hover:bg-amber-100"
                  title="See why on the agent's Integrate tab"><ShieldAlert size={12} /> Not certified for reuse</Link>}
          </div>
          <p className="mt-1 text-[14px] text-slate-700">“{r.purpose}”</p>
          <p className="mt-0.5 text-[12.5px] text-slate-600">
            Requested by {r.requesterName || r.requesterId} · {fmtDate(r.createdAt)} · {waiting(r.createdAt)}
          </p>
        </div>
        {!rejecting && (
          <div className="flex shrink-0 items-center gap-2">
            <button type="button" className="btn-success btn-sm" disabled={busy || blocked} onClick={() => decide('approve')}
              title={blocked ? 'You raised this request — someone else must approve it' : undefined} data-testid="approve">
              Approve
            </button>
            <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={() => setRejecting(true)} data-testid="reject">
              Reject
            </button>
          </div>
        )}
      </div>
      {blocked && !rejecting && (
        <p className="mt-2 ml-12 text-[12.5px] text-slate-600">You raised this request, so another approver has to approve it. You can still reject (withdraw) it.</p>
      )}
      {rejecting && (
        <div className="mt-3 ml-12 flex flex-wrap gap-2">
          <input className="input text-sm flex-1 min-w-[240px]" autoFocus value={note} onChange={e => setNote(e.target.value)}
            placeholder="Why is this rejected? (required — the team sees it)" aria-label="Reason for rejecting" />
          <button type="button" className="btn-danger btn-sm" disabled={busy || !note.trim()} onClick={() => decide('reject')} data-testid="confirm-reject">
            {busy ? 'Rejecting…' : 'Reject request'}
          </button>
          <button type="button" className="btn-ghost btn-sm" disabled={busy} onClick={() => { setRejecting(false); setNote('') }}>Cancel</button>
        </div>
      )}
      {error && <p className="mt-2 ml-12 text-[13px] text-rose-700">{error}</p>}
    </li>
  )
}
