import { useCallback, useEffect, useId, useRef, useState } from 'react'
import {
  getAgentJobs, refreshAgent,
  type AgentJobItem, type JobRun, type RefreshResult, type SchedulerStatus,
} from '../services/ops/jobs'

// The API rate limit is shared by everyone behind one IP, so polling starts slow and backs off.
const POLL_START_MS = 5000
const POLL_MAX_MS = 20000
const DEFAULT_LOCK_MINUTES = 30

const DOT: Record<string, string> = {
  ok: 'bg-emerald-500',
  partial: 'bg-amber-400',
  skipped: 'bg-gray-300',
  not_configured: 'bg-gray-300',
  unreachable: 'bg-orange-400',
  error: 'bg-rose-500',
  stale: 'bg-rose-300',
  cancelled: 'bg-gray-400',
  unavailable: 'bg-white border border-gray-300',
  running: 'bg-teal-500 animate-pulse',
}
const NEVER_DOT = 'bg-white border border-dashed border-gray-300'

const STATUS_LABEL: Record<string, string> = {
  ok: 'OK',
  partial: 'partial',
  skipped: 'skipped',
  not_configured: 'not configured',
  unreachable: 'source unreachable',
  error: 'failed',
  stale: 'did not finish',
  cancelled: 'cancelled',
  unavailable: 'not available yet',
  running: 'running',
}

const RESULT_TONE: Record<RefreshResult['status'], string> = {
  ok: 'text-emerald-700',
  partial: 'text-amber-700',
  skipped: 'text-amber-700',
  error: 'text-rose-600',
}

function statusLabel(s: string) {
  return STATUS_LABEL[s] || s.replace(/_/g, ' ')
}

function ago(iso: string | null): string {
  if (!iso) return ''
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

function errorText(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  return typeof detail === 'string' ? detail : e?.message || fallback
}

function isLive(run: JobRun | null, lockMinutes: number): boolean {
  if (!run || run.status !== 'running' || !run.startedAt) return false
  const beat = run.summary?.heartbeatAt
  const alive = Math.max(Date.parse(run.startedAt), typeof beat === 'string' ? Date.parse(beat) : 0)
  return Date.now() - alive < lockMinutes * 60_000
}

// A 'running' row with no sign of life is shown as not finished; the server marks it stale on the next run.
function shownStatus(run: JobRun, lockMinutes: number): string {
  return run.status === 'running' && !isLive(run, lockMinutes) ? 'stale' : run.status
}

function statusText(run: JobRun, lockMinutes: number): string {
  const jobStatus = run.summary?.jobStatus
  const label = statusLabel(shownStatus(run, lockMinutes))
  return typeof jobStatus === 'string' ? `${label} (${jobStatus.replace(/_/g, ' ')})` : label
}

function runReason(run: JobRun): string | null {
  const summary = run.summary || {}
  const fromSummary = [summary.reason, summary.message, summary.detail].find(v => typeof v === 'string') as string | undefined
  return run.reason || fromSummary || run.error || null
}

function countBy(results: JobRun[]): string {
  const counts = new Map<string, number>()
  results.forEach(r => counts.set(r.status, (counts.get(r.status) || 0) + 1))
  return [...counts.entries()].map(([s, n]) => `${n} ${statusLabel(s)}`).join(', ')
}

function detailLines(item: AgentJobItem, scheduler: SchedulerStatus | null, lockMinutes: number): string[] {
  const run = item.lastRun
  const lines: string[] = []
  if (run) {
    const scope = run.agentId ? 'this agent' : 'all agents'
    lines.push(`Last run: ${statusText(run, lockMinutes)} · ${ago(run.startedAt)} · ${run.trigger} · ${scope}`)
    if (run.startedAt) lines.push(`Started ${new Date(run.startedAt).toLocaleString()}`)
    const reason = runReason(run)
    if (reason) lines.push(reason)
  } else {
    lines.push('Never run')
  }
  lines.push(`${item.schedule}${scheduler && !scheduler.enabled ? ' (scheduler off)' : ''}`)
  if (!item.inRefresh) lines.push('Not part of "Refresh all data": runs once a day for all agents.')
  if (!item.available) lines.push(`The job code is not available: ${item.unavailableReason || 'not deployed yet'}.`)
  return lines
}

function JobChip({ item, scheduler, lockMinutes, open, controls, onToggle }: {
  item: AgentJobItem
  scheduler: SchedulerStatus | null
  lockMinutes: number
  open: boolean
  controls: string
  onToggle: () => void
}) {
  const run = item.lastRun
  const status = run ? shownStatus(run, lockMinutes) : null
  const dot = status ? DOT[status] || 'bg-gray-300' : NEVER_DOT
  const detail = !run
    ? 'never'
    : status === 'running'
      ? 'running…'
      : status === 'ok' ? ago(run.startedAt) : `${ago(run.startedAt)} · ${statusText(run, lockMinutes)}`
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      aria-controls={controls}
      title={detailLines(item, scheduler, lockMinutes).join('\n')}
      data-job={item.job}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded px-1 -mx-1 hover:bg-white focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${open ? 'bg-white' : ''}`}
    >
      <span className={`h-2 w-2 rounded-full shrink-0 ${dot}`} aria-hidden />
      <span className="text-gray-600">{item.shortLabel}</span>
      <span className={status && status !== 'ok' && status !== 'running' ? 'text-amber-700' : 'text-gray-400'}>{detail}</span>
    </button>
  )
}

export default function JobStatusBar({ agentId, onRefreshed }: { agentId: string; onRefreshed?: () => void }) {
  const [jobs, setJobs] = useState<AgentJobItem[] | null>(null)
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  // The refresh request timed out or lost its connection; the server may still be running it.
  const [detached, setDetached] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [result, setResult] = useState<RefreshResult | null>(null)
  const [refreshError, setRefreshError] = useState<string | null>(null)
  const [openJob, setOpenJob] = useState<string | null>(null)
  const detailId = useId()
  const currentAgent = useRef<string | null>(agentId)
  const loadSeq = useRef(0)
  const appliedSeq = useRef(0)
  const detachedAtSeq = useRef(0)
  const loading = useRef(false)
  const onRefreshedRef = useRef(onRefreshed)
  onRefreshedRef.current = onRefreshed

  const load = useCallback(async () => {
    const seq = ++loadSeq.current
    loading.current = true
    try {
      const res = await getAgentJobs(agentId)
      if (seq !== loadSeq.current || currentAgent.current !== agentId) return
      appliedSeq.current = seq
      setJobs(res.data.jobs)
      setScheduler(res.data.scheduler)
      setLoadError(null)
    } catch (e) {
      if (seq !== loadSeq.current || currentAgent.current !== agentId) return
      setLoadError(errorText(e, 'Could not load job status'))
    } finally {
      if (seq === loadSeq.current) loading.current = false
    }
  }, [agentId])

  useEffect(() => {
    currentAgent.current = agentId
    setJobs(null)
    setLoadError(null)
    setRefreshing(false)
    setDetached(false)
    setNotice(null)
    setResult(null)
    setRefreshError(null)
    setOpenJob(null)
    load()
    return () => { currentAgent.current = null }
  }, [agentId, load])

  const lockMinutes = scheduler?.lockMinutes || DEFAULT_LOCK_MINUTES
  const refreshJobs = (jobs || []).filter(j => j.inRefresh)
  const current = refreshJobs.findIndex(j => isLive(j.agentRun, lockMinutes))
  const serverBusy = current >= 0
  const watching = refreshing || detached || serverBusy

  useEffect(() => {
    if (!watching) return
    let stopped = false
    let delay = POLL_START_MS
    let timer = window.setTimeout(function tick() {
      const next = () => {
        if (stopped) return
        delay = Math.min(POLL_MAX_MS, Math.round(delay * 1.5))
        timer = window.setTimeout(tick, delay)
      }
      if (loading.current) next()
      else load().finally(next)
    }, delay)
    return () => { stopped = true; window.clearTimeout(timer) }
  }, [watching, load])

  useEffect(() => {
    if (!refreshing) return
    const started = Date.now()
    const t = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000)
    return () => window.clearInterval(t)
  }, [refreshing])

  useEffect(() => {
    // Only a status fetched after contact was lost can tell that the server run has ended.
    if (!detached || serverBusy || appliedSeq.current <= detachedAtSeq.current) return
    setDetached(false)
    setNotice('The refresh is no longer running. Each step\'s outcome is shown above.')
    onRefreshedRef.current?.()
  }, [detached, serverBusy, jobs])

  async function refresh() {
    const target = agentId
    let lostContact = false
    setRefreshing(true)
    setElapsed(0)
    setResult(null)
    setRefreshError(null)
    setDetached(false)
    setNotice(null)
    try {
      const res = await refreshAgent(target)
      if (currentAgent.current === target) setResult(res.data)
    } catch (e: any) {
      if (currentAgent.current !== target) return
      if (e?.response) setRefreshError(errorText(e, 'Refresh failed'))
      else lostContact = true
    } finally {
      if (currentAgent.current === target) {
        setRefreshing(false)
        detachedAtSeq.current = loadSeq.current
        setDetached(lostContact)
        await load()
        if (!lostContact) onRefreshedRef.current?.()
      }
    }
  }

  const neverRun = jobs !== null && jobs.every(j => !j.lastRun)
  const notOk = (result?.results || []).filter(r => r.status !== 'ok')
  const openItem = jobs?.find(j => j.job === openJob) || null
  const labelOf = (job: string) => jobs?.find(j => j.job === job)?.shortLabel || job

  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50/60 px-3 py-2 text-xs space-y-1.5" data-testid="job-status-bar">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="text-gray-400">Data jobs</span>

        {jobs === null && !loadError && <span className="text-gray-400">Loading job status…</span>}
        {jobs === null && loadError && (
          <span className="text-rose-600">
            Job status unavailable ({loadError}){' '}
            <button type="button" onClick={() => load()} className="text-teal-700 underline">Retry</button>
          </span>
        )}
        {jobs?.map(item => (
          <JobChip
            key={item.job}
            item={item}
            scheduler={scheduler}
            lockMinutes={lockMinutes}
            open={openJob === item.job}
            controls={detailId}
            onToggle={() => setOpenJob(openJob === item.job ? null : item.job)}
          />
        ))}

        <span className="ml-auto flex items-center gap-3">
          {scheduler && (
            <span
              className="text-gray-500 whitespace-nowrap"
              title={scheduler.enabled
                ? `Daily jobs run in UTC.${scheduler.nextRunAt ? ` Next: ${new Date(scheduler.nextRunAt).toLocaleString()}` : ''}`
                : 'Daily jobs are off (SCHEDULER_ENABLED=false). Data changes only when someone refreshes it.'}
            >
              Scheduler:{' '}
              <span className={scheduler.enabled ? 'font-semibold text-teal-700' : 'font-semibold text-gray-500'}>
                {scheduler.enabled ? (scheduler.running ? 'on' : 'on (not running)') : 'off'}
              </span>
            </span>
          )}
          <button
            type="button"
            onClick={refresh}
            disabled={refreshing}
            className="btn-secondary btn-sm whitespace-nowrap"
            title="Re-reads Phoenix usage, then reruns cost rollup, risk scan and governance checks for this agent. Nothing about the agent itself is changed."
          >
            {refreshing ? 'Refreshing…' : 'Refresh all data'}
          </button>
        </span>
      </div>

      {jobs !== null && loadError && (
        <div className="text-amber-700">Job status may be out of date: {loadError}</div>
      )}

      {openItem && (
        <ul id={detailId} className="rounded border border-gray-100 bg-white px-2 py-1.5 text-gray-600 space-y-0.5">
          <li className="font-medium text-gray-700">{openItem.label}</li>
          {detailLines(openItem, scheduler, lockMinutes).map((line, i) => <li key={i}>{line}</li>)}
        </ul>
      )}

      {refreshing && (
        <div className="text-teal-700" role="status">
          {current >= 0
            ? `Step ${current + 1} of ${refreshJobs.length}: ${refreshJobs[current].label}`
            : 'Refreshing usage, cost, risk and governance data'}
          {' '}· {elapsed}s
        </div>
      )}
      {!refreshing && detached && (
        <div className="text-amber-700" role="status">
          The refresh request timed out or lost its connection. If it reached the server it keeps running there
          {current >= 0 ? ` (now: ${refreshJobs[current].label})` : ''}; this bar updates as each step finishes.
        </div>
      )}
      {!refreshing && !detached && serverBusy && (
        <div className="text-teal-700" role="status">
          Running now for this agent: {refreshJobs[current].label}. This bar updates when it finishes.
        </div>
      )}

      {!refreshing && refreshError && <div className="text-rose-600" role="alert">Refresh failed: {refreshError}</div>}
      {!refreshing && !detached && notice && <div className="text-gray-600" role="status">{notice}</div>}

      {!refreshing && result && (
        <div className={RESULT_TONE[result.status] || 'text-gray-600'} role="status">
          {result.locked
            ? result.reason || 'A refresh is already running for this agent.'
            : `Refresh finished in ${Math.max(0, Math.round((Date.parse(result.finishedAt) - Date.parse(result.startedAt)) / 1000))}s: ${countBy(result.results)}.`}
          {notOk.length > 0 && (
            <ul className="mt-0.5 space-y-0.5 text-gray-500">
              {notOk.map(r => (
                <li key={r.job}>
                  <span className="text-gray-600">{labelOf(r.job)}:</span>
                  {' '}{statusText(r, lockMinutes)}{runReason(r) ? `: ${runReason(r)}` : ''}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {!refreshing && !result && !refreshError && !notice && neverRun && (
        <div className="text-gray-400">No data jobs have run for this agent yet. Use "Refresh all data" to collect them now.</div>
      )}
    </div>
  )
}
