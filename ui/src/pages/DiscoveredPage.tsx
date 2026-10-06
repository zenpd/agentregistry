import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { CalendarClock, CheckCircle2, EyeOff, Loader2, Radar, RefreshCw, Undo2, Wrench } from 'lucide-react'
import {
  DISCOVERY_CHANGED, dismissProject, getPhoenixInbox, getPhoenixPrefill, restoreProject, scanPhoenix,
  type Activity, type PhoenixInbox, type PhoenixProjectRow, type Prefill,
} from '../services/ops/discovery'
import { getJobs, refreshAgent, type SchedulerStatus } from '../services/ops/jobs'
import OnboardingModal from '../components/OnboardingModal'
import ErrorNote from '../components/ErrorNote'
import InfoTip from '../components/InfoTip'
import { STAGE_PILL, errorMessage } from './agent/shared'

type View = 'inbox' | 'registered' | 'dismissed'

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
export default function DiscoveredPage() {
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
  }, [load])

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
            AI applications sending traces to Phoenix that are not in the registry yet. Review each one, then register it or dismiss it.
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
            <Link to="/settings" className="mt-2 inline-block text-sm font-semibold text-zen-700 hover:underline">Open Settings → Phoenix</Link>
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

      <div className="grid grid-cols-3 gap-4">
        {([
          ['inbox', 'New', summary.new, `${summary.newActive} active in the last ${data.windowDays} days`, 'text-zen-700'],
          ['registered', 'Registered', summary.registered, summary.quiet ? `${summary.quiet} gone quiet` : 'All active', summary.quiet ? 'text-amber-700' : 'text-emerald-700'],
          ['dismissed', 'Dismissed', summary.dismissed, 'Hidden from New', 'text-slate-700'],
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
                    <td className="px-4 py-2.5 text-slate-700">{r.name}</td>
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
