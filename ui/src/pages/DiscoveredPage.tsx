import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { CalendarClock, CheckCircle2, EyeOff, Loader2, Radar, RefreshCw, Undo2, Wrench } from 'lucide-react'
import {
  DISCOVERY_CHANGED, dismissProject, getPhoenixInbox, getPhoenixPrefill, mergeProject, restoreProject, scanPhoenix, splitProject, triageProject,
  type Activity, type InboxRow, type PhoenixInbox, type PhoenixProjectRow, type Prefill,
} from '../services/ops/discovery'
import { getDirectory } from '../services/api'
import { dismissFinding, findingPrefill, getFindings, linkFinding, restoreFinding, type FindingRow } from '../services/ops/connectors'
import { can, useMe } from '../lib/me'
import { getJobs, refreshAgent, type SchedulerStatus } from '../services/ops/jobs'
import OnboardingModal from '../components/OnboardingModal'
import ErrorNote from '../components/ErrorNote'
import InfoTip from '../components/InfoTip'
import { STAGE_PILL, errorMessage } from './agent/shared'

type View = 'inbox' | 'registered' | 'dismissed' | 'evaluation' | 'other'

const ACTIVITY: Record<Activity, { label: string; cls: string }> = {
  active: { label: 'Active', cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  quiet: { label: 'Quiet', cls: 'bg-amber-50 text-amber-700 ring-amber-200' },
  stale: { label: 'Stale', cls: 'bg-rose-50 text-rose-700 ring-rose-200' },
  none: { label: 'No calls', cls: 'bg-slate-100 text-slate-700 ring-slate-200' },
}

function ago(iso: string | null): string {
  if (!iso) return 'never'
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000))
  if (mins < 2) return 'just now'
  if (mins < 90) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 36) return `${hours} h ago`
  return `${Math.round(hours / 24)} days ago`
}

function ActivityPill({ activity }: { activity: Activity }) {
  const a = ACTIVITY[activity]
  return <span className={`rounded-full px-2 py-0.5 text-[12px] font-bold ring-1 ${a.cls}`}>{a.label}</span>
}

function Chips({ items, tone }: { items: string[]; tone: string }) {
  if (!items.length) return null
  return (
    <>
      {items.slice(0, 5).map(i => <span key={i} className={`rounded-md px-1.5 py-0.5 text-[12.5px] font-medium ${tone}`}>{i}</span>)}
      {items.length > 5 && <span className="text-[12.5px] text-slate-500">+{items.length - 5} more</span>}
    </>
  )
}

// Phoenix projects that no agent is linked to, found by the daily scan. A
// person registers one (the form opens prefilled from its traces) or dismisses
// it. Nothing is registered automatically.
const CONFIDENCE: Record<string, string> = {
  high: 'bg-emerald-50 text-emerald-700 ring-emerald-200', medium: 'bg-amber-50 text-amber-700 ring-amber-200', low: 'bg-slate-100 text-slate-700 ring-slate-200',
}

export default function DiscoveredPage() {
  const me = useMe()
  const [people, setPeople] = useState<{ id: string; name: string }[]>([])
  const [findings, setFindings] = useState<FindingRow[]>([])
  const loadFindings = useCallback(() => getFindings().then(r => setFindings(r.data.findings)).catch(() => setFindings([])), [])
  // A finding being registered: after the form saves, the new agent is linked to it.
  const [registerFinding, setRegisterFinding] = useState<{ finding: FindingRow; prefill: Prefill } | null>(null)
  const [data, setData] = useState<PhoenixInbox | null>(null)
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<View>('inbox')
  const [scanning, setScanning] = useState(false)
  const [register, setRegister] = useState<{ name: string; prefill: Prefill; findApp: boolean } | null>(null)
  // The agent just registered from this page, and whether its usage has been read yet.
  const [done, setDone] = useState<{ id: string; name: string; usage: 'reading' | 'ready' | 'failed' } | null>(null)
  const [dismissing, setDismissing] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  // Projects with no calls in the scan window are usually old experiments, so they start hidden.
  const [showQuiet, setShowQuiet] = useState(false)

  const changed = useCallback(() => window.dispatchEvent(new Event(DISCOVERY_CHANGED)), [])

  // Only the newest answer is shown, so a slow older request cannot overwrite fresher data.
  const latest = useRef(0)
  const load = useCallback(async () => {
    const mine = ++latest.current
    try {
      const fresh = (await getPhoenixInbox()).data
      if (mine !== latest.current) return
      setData(fresh)
      setError(null)
    } catch (e) {
      setError(errorMessage(e, 'Could not load discovered projects'))
    }
  }, [])

  useEffect(() => {
    load()
    getJobs().then(r => setScheduler(r.data.scheduler)).catch(() => setScheduler(null))
    getDirectory().then(r => setPeople(r.data)).catch(() => setPeople([]))
    loadFindings()
  }, [load, loadFindings])

  async function act(key: string, fn: () => Promise<unknown>, after?: () => void) {
    setBusy(key)
    setError(null)
    try { await fn(); after?.(); await load(); changed() } catch (e) { setError(errorMessage(e, 'The change was not saved')) } finally { setBusy(null) }
  }

  // The scan runs on the server in the background: start it, then watch the page's own data
  // until it reports that the scan has ended.
  async function scan() {
    setScanning(true)
    setError(null)
    try {
      await scanPhoenix()
      await load()
    } catch (e) {
      setError(errorMessage(e, 'The scan could not start'))
      setScanning(false)
    }
  }

  const wasScanning = useRef(false)
  useEffect(() => {
    if (!data) return
    if (data.scanning) {
      wasScanning.current = true
      const timer = setTimeout(load, 2000)
      return () => clearTimeout(timer)
    }
    if (wasScanning.current || scanning) {
      wasScanning.current = false
      setScanning(false)
      changed()
    }
  }, [data, scanning, load, changed])

  async function openRegister(name: string) {
    setBusy(name)
    try {
      const r = (await getPhoenixPrefill(name)).data
      setRegister({ name, prefill: { fields: r.fields, sources: r.sources }, findApp: r.canFindApp })
    } catch (e) {
      setError(errorMessage(e, 'Could not prepare the form'))
    } finally {
      setBusy(null)
    }
  }

  // The new agent is linked to its Phoenix project, so its usage, cost and risk can be read straight away.
  async function registered(id: string, name: string) {
    setDone({ id, name, usage: 'reading' })
    await load()
    changed()
    try {
      await refreshAgent(id)
      setDone(d => (d && d.id === id ? { ...d, usage: 'ready' } : d))
    } catch {
      setDone(d => (d && d.id === id ? { ...d, usage: 'failed' } : d))
    }
  }

  async function dismiss(name: string) {
    if (!reason.trim()) return
    setBusy(name)
    try {
      await dismissProject(name, reason.trim())
      setDismissing(null)
      setReason('')
      await load()
      changed()
    } catch (e) {
      setError(errorMessage(e, 'Could not dismiss'))
    } finally {
      setBusy(null)
    }
  }

  async function restore(name: string) {
    setBusy(name)
    try {
      await restoreProject(name)
      await load()
      changed()
    } catch (e) {
      setError(errorMessage(e, 'Could not restore'))
    } finally {
      setBusy(null)
    }
  }

  if (!data) return error ? <div className="p-8 text-center text-rose-500">Error: {error}</div> : <div className="p-8 text-center text-slate-600">Loading…</div>

  const scan_ = data.lastScan
  const scanStatus = scan_?.status
  const scanReason = (scan_?.summary?.reason as string | undefined) ?? scan_?.error ?? undefined
  const scanFailed = scanStatus && !['ok', 'partial', 'running'].includes(scanStatus)
  const { summary } = data
  const inboxRows = showQuiet ? data.inbox : data.inbox.filter(p => p.activity === 'active')

  return (
    <div className="space-y-5 animate-fade-in max-w-5xl">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold gradient-text flex items-center gap-1.5">Discovered <InfoTip term="discovered" /></h1>
          <p className="text-slate-600 mt-0.5">
            Agents sending traces to Phoenix that are not in the registry yet. Review each one, then register it or dismiss it.
          </p>
        </div>
        <button type="button" className="btn-primary btn-sm" onClick={scan} disabled={scanning || data.scanning || !data.configured} data-testid="scan-now">
          {scanning || data.scanning ? <><Loader2 size={14} className="animate-spin" /> Scanning…</> : <><RefreshCw size={14} /> Scan now</>}
        </button>
      </div>

      {!data.configured && (
        <div className="card p-6 flex items-start gap-3" data-testid="not-configured">
          <Wrench size={20} className="mt-0.5 text-amber-600 shrink-0" />
          <div>
            <p className="font-semibold text-slate-900">Phoenix is not connected</p>
            <p className="text-sm text-slate-600">Add the Phoenix address and a read-only key, and discovery fills this page by itself.</p>
            <Link to="/settings" className="mt-2 inline-block text-sm font-semibold text-zen-700 hover:underline">Open Settings → Common tracing endpoint</Link>
          </div>
        </div>
      )}

      {data.configured && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[13px] text-slate-700" data-testid="scan-status">
          <span className="inline-flex items-center gap-1.5">
            <Radar size={14} className="text-zen-600" />
            {scan_ ? <>Last scan {ago(scan_.finishedAt ?? scan_.startedAt)} <InfoTip term="phoenix_scan" /></> : <>Not scanned yet <InfoTip term="phoenix_scan" /></>}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <CalendarClock size={14} className="text-zen-600" />
            {scheduler?.enabled
              ? 'Scans automatically every day'
              : <>Automatic scan is off — it only runs when you press Scan now <InfoTip term="scheduler" /></>}
          </span>
        </div>
      )}

      {scanFailed && <ErrorNote message={scanReason || `The last scan ended as ${scanStatus}.`} testId="scan-error" />}
      {error && <ErrorNote message={error} onDismiss={() => setError(null)} />}
      {done && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[13px] text-emerald-900" role="status" data-testid="registered-note">
          <CheckCircle2 size={15} className="text-emerald-600" />
          <span><span className="font-semibold">{done.name}</span> is registered.{' '}
            {done.usage === 'reading' ? 'Reading its usage from Phoenix and completing its record…'
              : done.usage === 'ready' ? 'Its usage, cost and risk have been read, and its record filled in where the registry could.'
              : 'Its usage could not be read just now; the registry tries again when its page is opened.'}</span>
          {done.usage === 'reading' && <Loader2 size={13} className="animate-spin" />}
          <Link to={`/agents/${done.id}`} className="ml-auto font-semibold text-emerald-800 hover:underline">Open the agent →</Link>
        </div>
      )}

      <div className="grid grid-cols-5 gap-3">
        {([
          ['inbox', 'New', summary.new, `${summary.newActive} active · ${summary.assigned} assigned${summary.overdue ? ` · ${summary.overdue} overdue` : ''}`, 'text-zen-700'],
          ['registered', 'Registered', summary.registered, summary.quiet ? `${summary.quiet} gone quiet` : 'All active', summary.quiet ? 'text-amber-700' : 'text-emerald-700'],
          ['dismissed', 'Dismissed', summary.dismissed, 'Hidden from New', 'text-slate-700'],
          ['evaluation', 'Evaluation runs', summary.evaluation, 'AssureAI experiment projects, not agents', 'text-slate-700'],
          ['other', 'Other sources', findings.filter(f => f.state === 'new').length, 'Langfuse, GitHub and Azure (Settings → Connectors)', 'text-violet-700'],
        ] as [View, string, number, string, string][]).map(([key, label, count, sub, tone]) => (
          <button key={key} type="button" onClick={() => setView(key)} data-testid={`tile-${key}`}
            className={`card p-4 text-left transition ${view === key ? 'ring-2 ring-zen-400' : 'hover:shadow-card-hover'}`}>
            <div className="text-[12px] font-bold uppercase tracking-wide text-slate-500">{label}</div>
            <div className={`text-3xl font-extrabold ${tone}`}>{count}</div>
            <div className="text-xs text-slate-600">{sub}</div>
          </button>
        ))}
      </div>

      {view === 'inbox' && (
        <ul className="space-y-3" data-testid="inbox-list">
          {data.inbox.length > summary.newActive && (
            <li className="flex flex-wrap items-center justify-between gap-2 text-[13px] text-slate-700">
              <span>{showQuiet ? 'Showing every unregistered project.' : `Showing the ${summary.newActive} projects with calls in the last ${data.windowDays} days.`}</span>
              <button type="button" className="font-semibold text-zen-700 hover:underline" onClick={() => setShowQuiet(!showQuiet)} data-testid="toggle-quiet">
                {showQuiet ? 'Show active only' : `Also show ${data.inbox.length - summary.newActive} without recent calls`}
              </button>
            </li>
          )}
          {inboxRows.length === 0 && (
            <li className="card p-10 text-center">
              <CheckCircle2 size={34} className="mx-auto text-emerald-500" />
              <p className="mt-3 text-lg font-bold text-slate-900">{data.needsScan ? 'Nothing read from Phoenix yet' : data.inbox.length ? 'No active projects waiting' : 'Every Phoenix project is accounted for'}</p>
              <p className="text-sm text-slate-600">{data.needsScan ? 'Press Scan now to read Phoenix. This also applies after the Phoenix address is changed in Settings.' : 'New projects will appear here after the next scan.'}</p>
            </li>
          )}
          {inboxRows.map(p => (
            <li key={p.name} className="rounded-xl border border-slate-200 bg-white px-4 py-3" data-testid="inbox-row">
              <div className="flex flex-wrap items-center gap-3">
                <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-zen-50 text-zen-600"><Radar size={18} /></div>
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-slate-900">{p.name}</span>
                    <ActivityPill activity={p.activity} />
                    <InfoTip term="discovery_activity" />
                  </div>
                  <div className="mt-0.5 text-[13px] text-slate-600">
                    {p.spanCount > 0
                      ? <>{p.spanCount.toLocaleString()}{p.spanCount >= data.sampleCap ? '+' : ''} traced steps in the last {p.windowDays} days · last seen {ago(p.lastSeen)}</>
                      : p.lastSeen ? <>No calls in the last {p.windowDays} days · last seen {ago(p.lastSeen)}</> : <>No calls in the last {p.windowDays} days</>}
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    <Chips items={p.agentNames} tone="bg-emerald-50 text-emerald-700" />
                    <Chips items={p.models} tone="bg-indigo-50 text-indigo-700" />
                    <Chips items={p.mcpServers} tone="bg-violet-50 text-violet-700" />
                    <Chips items={p.tools} tone="bg-slate-100 text-slate-700" />
                  </div>
                  {p.scanError && <div className="mt-1 text-xs text-amber-700">Could not read its traces: {p.scanError}</div>}
                  <Candidate row={p} people={people} canEdit={can(me, 'update')} busy={busy}
                    onMerge={(agentId, agentName) => act(`merge:${p.name}`, () => mergeProject(p.name, agentId), () => setDone({ id: agentId, name: `${p.name} → ${agentName}`, usage: 'ready' }))}
                    onTriage={body => act(`triage:${p.name}`, () => triageProject(p.name, body))} />
                </div>
                <div className="flex items-center gap-2">
                  <button type="button" className="btn-primary btn-sm" disabled={busy === p.name} onClick={() => openRegister(p.name)} data-testid="register-btn">
                    {busy === p.name ? 'Opening…' : 'Register'}
                  </button>
                  <button type="button" className="btn-secondary btn-sm" onClick={() => { setDismissing(dismissing === p.name ? null : p.name); setReason('') }}>
                    <EyeOff size={14} /> Dismiss
                  </button>
                </div>
              </div>
              {dismissing === p.name && (
                <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
                  <input className="input flex-1 min-w-[220px]" autoFocus value={reason} onChange={e => setReason(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') dismiss(p.name) }}
                    placeholder="Why? e.g. test run, not an agent, duplicate" aria-label="Reason for dismissing" />
                  <InfoTip term="discovery_dismiss" />
                  <button type="button" className="btn-secondary btn-sm" disabled={!reason.trim() || busy === p.name} onClick={() => dismiss(p.name)}>Dismiss</button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {view === 'registered' && (
        <div className="card overflow-hidden" data-testid="registered-list">
          <div className="px-4 py-3 border-b border-slate-100 text-sm text-slate-600">
            Registered agents linked to a Phoenix project, and whether they are still sending traces. A quiet agent may be idle, retired, or broken.
          </div>
          {data.registered.length === 0 ? <p className="p-8 text-center text-sm text-slate-600">No registered agent is linked to a Phoenix project yet.</p> : (
            <table className="w-full text-sm">
              <thead><tr className="text-left text-[12px] uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2">Agent</th><th className="px-4 py-2">Phoenix project</th><th className="px-4 py-2">Activity</th><th className="px-4 py-2">Last seen</th>
              </tr></thead>
              <tbody>
                {data.registered.map(r => (
                  <tr key={r.agentId} className="border-t border-slate-100">
                    <td className="px-4 py-2.5">
                      <Link to={`/agents/${r.agentId}`} className="font-semibold text-slate-900 hover:text-zen-700">{r.agentName}</Link>
                      <span className={`ml-2 ${STAGE_PILL[r.stage] || 'status-pending'}`}>{r.stage}</span>
                    </td>
                    <td className="px-4 py-2.5 text-slate-700">
                      {r.name}
                      {r.sharedWith.length > 0 && <div className="text-[12px] text-amber-700" data-testid="shared-project">Also linked: {r.sharedWith.map(o => o.name).join(', ')}</div>}
                      {can(me, 'update') && (
                        <button type="button" className="ml-2 text-[12px] font-semibold text-slate-600 hover:text-rose-700" disabled={busy === `split:${r.agentId}`}
                          title="This agent is not this project: unlink them. The project goes back to New."
                          onClick={() => act(`split:${r.agentId}`, () => splitProject(r.agentId))}>Unlink</button>
                      )}
                    </td>
                    <td className="px-4 py-2.5"><ActivityPill activity={r.activity} /></td>
                    <td className="px-4 py-2.5 text-slate-700">{ago(r.lastSeen)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {view === 'dismissed' && (
        <ul className="space-y-3" data-testid="dismissed-list">
          {data.dismissed.length === 0 && <li className="card p-8 text-center text-sm text-slate-600">Nothing has been dismissed.</li>}
          {data.dismissed.map(p => (
            <li key={p.name} className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3">
              <div className="flex-1 min-w-0">
                <span className="font-semibold text-slate-900">{p.name}</span>
                <div className="text-[13px] text-slate-600">Dismissed: {p.dismissReason}</div>
              </div>
              <button type="button" className="btn-secondary btn-sm" disabled={busy === p.name} onClick={() => restore(p.name)}>
                <Undo2 size={14} /> Bring back
              </button>
            </li>
          ))}
        </ul>
      )}

      {view === 'evaluation' && (
        <div className="card p-4 space-y-2" data-testid="evaluation-list">
          <p className="text-sm text-slate-600">AssureAI creates one Phoenix project for each experiment run. They hold evaluation traffic, not an agent, so they are kept out of New and out of usage and cost.</p>
          {data.evaluation.length === 0 ? <p className="text-sm text-slate-600">None found.</p>
            : <ul className="flex flex-wrap gap-1.5">{data.evaluation.map(p => <li key={p.name} className="rounded-md bg-slate-100 px-2 py-0.5 text-[12.5px] text-slate-700">{p.name}</li>)}</ul>}
        </div>
      )}

      {view === 'other' && (
        <OtherSources findings={findings} canEdit={can(me, 'update')} busy={busy}
          onRegister={async f => {
            setBusy(`f:${f.id}`)
            try { const r = (await findingPrefill(f.id)).data; setRegisterFinding({ finding: f, prefill: { fields: r.fields, sources: r.sources } }) }
            catch (e) { setError(errorMessage(e, 'Could not prepare the form')) } finally { setBusy(null) }
          }}
          onLink={(f, agentId) => act(`f:${f.id}`, () => linkFinding(f.id, agentId), loadFindings)}
          onDismiss={(f, reason) => act(`f:${f.id}`, () => dismissFinding(f.id, reason), loadFindings)}
          onRestore={f => act(`f:${f.id}`, () => restoreFinding(f.id), loadFindings)} />
      )}

      {registerFinding && (
        <OnboardingModal
          title={`Register “${registerFinding.finding.name}”`}
          prefill={registerFinding.prefill}
          onClose={() => setRegisterFinding(null)}
          onSaved={async id => {
            const f = registerFinding.finding
            setRegisterFinding(null)
            await act(`f:${f.id}`, () => linkFinding(f.id, id), loadFindings)
            setDone({ id, name: f.name, usage: 'ready' })
          }}
        />
      )}

      {register && (
        <OnboardingModal
          title={`Register “${register.name}”`}
          prefill={register.prefill}
          findAppFor={register.findApp ? register.name : undefined}
          onClose={() => setRegister(null)}
          onSaved={id => { registered(id, register.name) }}
        />
      )}
    </div>
  )
}

// What the registry can tell about one candidate: which record it may be, who
// probably owns it, what looks odd, and who triages it by when.
function Candidate({ row: p, people, canEdit, busy, onMerge, onTriage }: {
  row: InboxRow
  people: { id: string; name: string }[]
  canEdit: boolean
  busy: string | null
  onMerge: (agentId: string, agentName: string) => void
  onTriage: (body: { assigneeUserId?: string | null; dueDate?: string | null }) => void
}) {
  return (
    <div className="mt-2 space-y-1.5" data-testid="candidate">
      {p.errorShare != null && p.errorShare > 0 && (
        <div className="text-[12.5px] text-slate-700">{Math.round(p.errorShare * 100)}% of the sampled steps ended in an error.</div>
      )}
      {p.hygiene.map(h => <div key={h.code} className="text-[12.5px] text-amber-800" data-testid="hygiene">{h.text}</div>)}
      {p.ownerGuess && (
        <div className="text-[12.5px] text-slate-700" data-testid="owner-guess">Probable owner: <span className="font-semibold text-slate-900">{p.ownerGuess.value}</span> <span className="text-slate-500">({p.ownerGuess.confidence} confidence: {p.ownerGuess.reason})</span></div>
      )}
      {p.matches.length > 0 && (
        <div className="rounded-lg bg-slate-50 px-3 py-2 ring-1 ring-slate-200" data-testid="matches">
          <div className="text-[12px] font-semibold uppercase tracking-wide text-slate-600">May already be registered as</div>
          <ul className="mt-1 space-y-1">
            {p.matches.map(m => (
              <li key={m.agentId} className="flex flex-wrap items-center gap-2 text-[13px]">
                <Link to={`/agents/${m.agentId}`} className="font-semibold text-slate-900 hover:text-zen-700">{m.name}</Link>
                <span className={`rounded-full px-2 py-0.5 text-[11.5px] font-bold ring-1 ${CONFIDENCE[m.confidence]}`}>{m.confidence} match</span>
                <span className="text-slate-600">{m.reason}</span>
                {canEdit && (m.linkedProject
                  ? <span className="text-[12px] text-slate-500">already linked to {m.linkedProject}</span>
                  : <button type="button" className="btn-secondary btn-sm !py-0.5" disabled={busy === `merge:${p.name}`}
                      title={`Link this project to ${m.name}. Its usage and record are then read from this project.`}
                      onClick={() => onMerge(m.agentId, m.name)} data-testid="merge-btn">Link to this agent</button>)}
              </li>
            ))}
          </ul>
        </div>
      )}
      {canEdit && (
        <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-slate-700" data-testid="triage">
          <span>Triage:</span>
          <select className="input !w-auto !py-0.5 text-[12.5px]" value={p.assigneeUserId || ''} aria-label="Assigned to"
            onChange={e => onTriage({ assigneeUserId: e.target.value || null })}>
            <option value="">Not assigned</option>
            {people.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
          <label className="flex items-center gap-1">by <input type="date" className="input !w-auto !py-0.5 text-[12.5px]" value={p.dueDate || ''}
            onChange={e => onTriage({ dueDate: e.target.value || null })} aria-label="Due date" /></label>
          {p.overdue && <span className="rounded-full bg-rose-50 px-2 py-0.5 text-[11.5px] font-bold text-rose-700 ring-1 ring-rose-200">Overdue</span>}
        </div>
      )}
    </div>
  )
}

const FINDING_KIND: Record<FindingRow['kind'], string> = {
  trace_project: 'Langfuse project', code_repo: 'Code repository', cloud_deployment: 'Model deployment', cloud_agent: 'Foundry agent',
}

function findingFacts(f: FindingRow): string {
  const d = f.details
  if (f.kind === 'code_repo') return [d.frameworks?.length ? `Frameworks: ${d.frameworks.join(', ')}` : '', d.mcpServer ? 'builds an MCP server' : '',
    d.mcpConfigs?.length ? `MCP configuration: ${d.mcpConfigs.join(', ')}` : '', d.agentCard ? 'has an agent card' : '', d.tracing?.length ? `traced with ${d.tracing.join(', ')}` : '',
    d.archived ? 'archived' : ''].filter(Boolean).join(' · ')
  if (f.kind === 'trace_project') return `${d.traces} traces and ${d.generations} model calls in the last ${d.windowDays} days · models: ${(d.models || []).join(', ') || 'none'}`
  if (f.kind === 'cloud_deployment') return `Model ${d.model}${d.modelVersion ? ` (${d.modelVersion})` : ''} in ${d.account} · ${d.sku || ''}${d.capacity ? ` capacity ${d.capacity}` : ''} · ${d.location || ''}`
  return `Model ${d.model || 'not stated'} in project ${d.project} of ${d.account}`
}

// What the connectors found outside Phoenix.
function OtherSources({ findings, canEdit, busy, onRegister, onLink, onDismiss, onRestore }: {
  findings: FindingRow[]; canEdit: boolean; busy: string | null
  onRegister: (f: FindingRow) => void; onLink: (f: FindingRow, agentId: string) => void
  onDismiss: (f: FindingRow, reason: string) => void; onRestore: (f: FindingRow) => void
}) {
  const [dismissing, setDismissing] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  if (findings.length === 0) {
    return <div className="card p-8 text-center text-sm text-slate-600" data-testid="other-sources">Nothing found outside Phoenix yet. Add a connector in <Link to="/settings" className="font-semibold text-zen-700 hover:underline">Settings → Connectors</Link> (Langfuse, GitHub or Azure).</div>
  }
  return (
    <ul className="space-y-3" data-testid="other-sources">
      {findings.map(f => (
        <li key={f.id} className={`rounded-xl border border-slate-200 bg-white px-4 py-3 ${f.state !== 'new' ? 'opacity-75' : ''}`} data-testid="finding-row">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-slate-900">{f.name}</span>
            <span className="rounded-full bg-violet-50 px-2 py-0.5 text-[12px] font-semibold text-violet-700 ring-1 ring-violet-200">{FINDING_KIND[f.kind]}</span>
            <span className="text-[12px] text-slate-500">from {f.connector?.label}</span>
            {f.url && <a href={f.url} target="_blank" rel="noreferrer" className="text-[12px] text-zen-700 hover:underline">open</a>}
            {f.state === 'linked' && f.linkedAgentId && <Link to={`/agents/${f.linkedAgentId}`} className="rounded-full bg-emerald-50 px-2 py-0.5 text-[12px] font-semibold text-emerald-700 ring-1 ring-emerald-200">Linked to a record</Link>}
            {f.state === 'dismissed' && <span className="text-[12px] text-slate-600">Dismissed: {f.dismissReason}</span>}
            {canEdit && f.state === 'new' && (
              <span className="ml-auto flex gap-1.5">
                <button type="button" className="btn-primary btn-sm" disabled={busy === `f:${f.id}`} onClick={() => onRegister(f)}>Register</button>
                <button type="button" className="btn-secondary btn-sm" onClick={() => { setDismissing(dismissing === f.id ? null : f.id); setReason('') }}>Dismiss</button>
              </span>
            )}
            {canEdit && f.state !== 'new' && <button type="button" className="ml-auto btn-secondary btn-sm" disabled={busy === `f:${f.id}`} onClick={() => onRestore(f)}>Bring back</button>}
          </div>
          <div className="mt-1 text-[13px] text-slate-700">{findingFacts(f)}</div>
          {f.details.description && <div className="text-[13px] text-slate-600">{f.details.description}</div>}
          {f.state === 'new' && (f.matches?.length ?? 0) > 0 && (
            <div className="mt-2 rounded-lg bg-slate-50 px-3 py-2 ring-1 ring-slate-200">
              <div className="text-[12px] font-semibold uppercase tracking-wide text-slate-600">May already be registered as</div>
              {f.matches!.map(m => (
                <div key={m.agentId} className="flex flex-wrap items-center gap-2 text-[13px]">
                  <Link to={`/agents/${m.agentId}`} className="font-semibold text-slate-900 hover:text-zen-700">{m.name}</Link>
                  <span className={`rounded-full px-2 py-0.5 text-[11.5px] font-bold ring-1 ${CONFIDENCE[m.confidence]}`}>{m.confidence} match</span>
                  <span className="text-slate-600">{m.reason}</span>
                  {canEdit && <button type="button" className="btn-secondary btn-sm !py-0.5" disabled={busy === `f:${f.id}`} onClick={() => onLink(f, m.agentId)}>Link to this agent</button>}
                </div>
              ))}
            </div>
          )}
          {dismissing === f.id && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <input className="input flex-1 min-w-[220px]" autoFocus value={reason} onChange={e => setReason(e.target.value)} placeholder="Why? e.g. a library, not an agent" aria-label="Reason for dismissing" />
              <button type="button" className="btn-secondary btn-sm" disabled={reason.trim().length < 3} onClick={() => { onDismiss(f, reason.trim()); setDismissing(null) }}>Dismiss</button>
            </div>
          )}
        </li>
      ))}
    </ul>
  )
}
