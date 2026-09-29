import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight, BadgeCheck, CheckCircle2, KeyRound, Radar, ShieldAlert, ShieldCheck,
} from 'lucide-react'
import { APPROVALS_CHANGED, getApprovals, type ApprovalAccessRequest, type Approvals } from '../services/ops/approvals'
import { decideAccess } from '../services/ops/integrate'
import { STAGE_PILL, errorMessage } from './agent/shared'

type Queue = 'all' | 'access' | 'reviews' | 'discoveries'

function fmtDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—'
}

// "waiting 3 days": how long something has been waiting is what an approver sorts by.
function waiting(iso: string | null): string {
  if (!iso) return ''
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
  return days <= 0 ? 'today' : days === 1 ? 'waiting 1 day' : `waiting ${days} days`
}

// Everything waiting for a decision across the registry. Access requests are
// decided here; gates and discoveries open where their full workflow lives.
export default function ApprovalsPage() {
  const [data, setData] = useState<Approvals | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [queue, setQueue] = useState<Queue>('all')

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
  if (!data) return <div className="p-8 text-center text-gray-500">Loading…</div>

  const { counts } = data
  const show = (q: Queue) => queue === 'all' || queue === q

  return (
    <div className="space-y-5 animate-fade-in max-w-5xl">
      <div>
        <h1 className="text-2xl font-bold gradient-text">Approvals</h1>
        <p className="text-gray-500 mt-0.5">
          Everything waiting for a decision across the registry — who may use an agent, governance reviews in
          progress, and AI found running without being registered.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4" role="tablist" aria-label="Approval queues">
        <QueueTile active={queue === 'access'} onClick={() => setQueue(queue === 'access' ? 'all' : 'access')}
          icon={<KeyRound size={20} />} tone="indigo" count={counts.accessRequests}
          label="Access requests" sub="Teams waiting to use an agent" testId="queue-access" />
        <QueueTile active={queue === 'reviews'} onClick={() => setQueue(queue === 'reviews' ? 'all' : 'reviews')}
          icon={<ShieldCheck size={20} />} tone="amber" count={counts.reviews}
          label="Reviews awaiting decision" sub="Governance gates in review" testId="queue-reviews" />
        <QueueTile active={queue === 'discoveries'} onClick={() => setQueue(queue === 'discoveries' ? 'all' : 'discoveries')}
          icon={<Radar size={20} />} tone="orange" count={counts.discoveries}
          label="Discovered AI" sub="Running, not yet registered" testId="queue-discoveries" />
      </div>

      {counts.total === 0 && (
        <div className="card p-10 text-center" data-testid="all-clear">
          <CheckCircle2 size={36} className="mx-auto text-emerald-500" />
          <p className="mt-3 text-lg font-bold text-slate-900">All caught up</p>
          <p className="text-sm text-slate-500">Nothing is waiting for a decision.</p>
        </div>
      )}

      {counts.total > 0 && queue !== 'all' && (
        <button type="button" onClick={() => setQueue('all')} className="text-sm font-medium text-zen-700 hover:underline">
          ← Show every queue
        </button>
      )}

      {show('access') && counts.total > 0 && (
        <QueueSection title="Access requests" count={counts.accessRequests}
          hint={`A team asks to consume an agent. Approving adds the team to the agent's consumers.${
            data.selfApprovalAllowed ? '' : ' You cannot approve a request you raised.'}`}
          empty="No access requests waiting." testId="section-access">
          {data.accessRequests.map(r => <AccessRequestRow key={r.id} req={r} selfAllowed={data.selfApprovalAllowed} onDecided={decided} />)}
        </QueueSection>
      )}

      {show('reviews') && counts.total > 0 && (
        <QueueSection title="Reviews awaiting decision" count={counts.reviews}
          hint="Governance gates the owner has submitted. The reviewer decides on the agent's Governance tab, where the evidence and checklist are."
          empty="No reviews waiting." testId="section-reviews">
          {data.reviews.map(g => (
            <li key={`${g.agentId}-${g.gate}`} className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3" data-testid="review-row">
              <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-amber-50 text-amber-600"><ShieldAlert size={18} /></div>
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-slate-900">{g.gateLabel}</span>
                  <span className="text-slate-400">·</span>
                  <Link to={`/agents/${g.agentId}`} className="font-medium text-slate-700 hover:text-zen-700">{g.agentName}</Link>
                  <span className={STAGE_PILL[g.agentStage] || 'status-pending'}>{g.agentStage}</span>
                </div>
                <div className="mt-0.5 text-[13px] text-slate-500">
                  Decided by {g.reviewerRole || 'the reviewer'}{g.reviewer ? ` (${g.reviewer})` : ''} · in review {waiting(g.since).replace('waiting ', 'for ')}
                </div>
              </div>
              <Link to={`/agents/${g.agentId}?tab=governance`}
                className="inline-flex items-center gap-1 rounded-full border border-zen-200 bg-zen-50 px-3 py-1.5 text-[13px] font-semibold text-zen-700 hover:bg-zen-100">
                Open review <ArrowRight size={14} />
              </Link>
            </li>
          ))}
        </QueueSection>
      )}

      {show('discoveries') && counts.total > 0 && (
        <QueueSection title="Discovered AI" count={counts.discoveries}
          hint="AI found running in the enterprise that is not in the registry. Register it or dismiss it as a false positive on the Governance page."
          empty="Nothing new discovered." testId="section-discoveries">
          {data.discoveries.map(d => (
            <li key={d.id} className="flex flex-wrap items-start gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3" data-testid="discovery-row">
              <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-orange-50 text-orange-600"><Radar size={18} /></div>
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-slate-900">{d.suspectedName}</span>
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ring-1 ${
                    d.confidence >= 85 ? 'bg-rose-50 text-rose-700 ring-rose-200' : d.confidence >= 70 ? 'bg-amber-50 text-amber-700 ring-amber-200' : 'bg-slate-100 text-slate-600 ring-slate-200'
                  }`}>{d.confidence}% confidence</span>
                </div>
                <div className="mt-0.5 text-[13px] text-slate-500">
                  {d.suspectedDept || 'Unknown unit'} · found via {d.source} · first seen {fmtDate(d.firstSeen)}
                </div>
                {d.signal && <p className="mt-1 text-[13px] text-slate-600">{d.signal}</p>}
              </div>
              <Link to="/governance"
                className="inline-flex items-center gap-1 rounded-full border border-zen-200 bg-zen-50 px-3 py-1.5 text-[13px] font-semibold text-zen-700 hover:bg-zen-100">
                Register or dismiss <ArrowRight size={14} />
              </Link>
            </li>
          ))}
        </QueueSection>
      )}
    </div>
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
        <div className="text-[12px] text-slate-500">{sub}</div>
      </div>
    </button>
  )
}

function QueueSection({ title, count, hint, empty, testId, children }: {
  title: string; count: number; hint: string; empty: string; testId: string; children: React.ReactNode
}) {
  return (
    <section className="rounded-2xl border border-slate-200/80 bg-slate-50/60 p-5 shadow-sm" data-testid={testId}>
      <div className="flex items-start gap-2.5">
        <span className="mt-1 h-4 w-1 shrink-0 rounded-full bg-gradient-to-b from-zen-400 to-zen-700" aria-hidden />
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h2 className="text-[16px] font-extrabold text-slate-900">{title}</h2>
            <span className={`rounded-full px-2 py-0.5 text-[12px] font-bold ${count ? 'bg-zen-600 text-white' : 'bg-slate-200 text-slate-600'}`}>{count}</span>
          </div>
          <p className="mt-0.5 text-[13px] text-slate-500">{hint}</p>
        </div>
      </div>
      {count === 0
        ? <p className="mt-3 flex items-center gap-2 text-sm text-slate-500"><CheckCircle2 size={16} className="text-emerald-500" /> {empty}</p>
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
            <span className="text-slate-500">wants to use</span>
            <Link to={`/agents/${r.agentId}?tab=integrate`} className="font-semibold text-zen-700 hover:underline">{r.agentName}</Link>
            {r.agentStage && <span className={STAGE_PILL[r.agentStage] || 'status-pending'}>{r.agentStage}</span>}
            {r.certified
              ? <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-bold text-emerald-700 ring-1 ring-emerald-200"><BadgeCheck size={12} /> Certified for reuse</span>
              : <Link to={`/agents/${r.agentId}?tab=integrate`} className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-bold text-amber-800 ring-1 ring-amber-200 hover:bg-amber-100"
                  title="See why on the agent's Integrate tab"><ShieldAlert size={12} /> Not certified for reuse</Link>}
          </div>
          <p className="mt-1 text-[14px] text-slate-700">“{r.purpose}”</p>
          <p className="mt-0.5 text-[12.5px] text-slate-500">
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
        <p className="mt-2 ml-12 text-[12.5px] text-slate-500">You raised this request, so another approver has to approve it. You can still reject (withdraw) it.</p>
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
