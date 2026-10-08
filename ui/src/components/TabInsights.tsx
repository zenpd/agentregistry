import { useCallback, useEffect, useRef, useState } from 'react'
import { Loader2, RefreshCw, Sparkles, Undo2 } from 'lucide-react'
import { refreshAgent } from '../services/ops/jobs'
import { updateAgent } from '../services/api'
import {
  getTabInsights, runInsight, setContentAudit, undoAutoUpdate,
  type AutoUpdate, type Insight, type InsightKind, type InsightTab, type TabInsight, type TabInsights as TabData,
} from '../services/ops/insights'
import { FindingItem, InsightFeedback, insightAge, statusText } from './InsightPanel'

// The registry is asked to look at an agent again at most this often from one browser,
// so a source that cannot be read is not retried on every tab.
const RETRIGGER_MS = 10 * 60_000
const POLL_MS = 5000
const MAX_POLLS = 36
const PREVIEW = 3
const lastAsked = new Map<string, number>()

type Phase = 'loading' | 'updating' | 'writing' | 'ready'

// The two insights that read other people's text. They run only when a person asks.
const READERS: Partial<Record<InsightKind, { ask: string; again: string; about: string }>> = {
  evidence_review: {
    ask: 'Read the attached evidence', again: 'Read the evidence again',
    about: 'Optional: have AI read the documents attached to the reviews and say which checklist items they address.',
  },
  trace_audit: {
    ask: 'Check a sample of real answers', again: 'Check another sample',
    about: 'Optional: have AI read a sample of this agent’s real questions and answers. Nothing it reads is stored.',
  },
}

function errorText(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

function shorten(text: string, max = 180): string {
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text
}

function UpdateRow({ update: u, busy, onUndo }: { update: AutoUpdate; busy: boolean; onUndo: () => void }) {
  return (
    <li className="rounded-lg border border-emerald-200 bg-white px-3.5 py-2.5" data-testid="auto-update" data-field={u.field}>
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
        <div className="min-w-0 flex-1">
          <span className="text-[14px] font-semibold text-slate-900">{u.label}</span>
          {u.isList ? (
            <span className="ml-2 inline-flex flex-wrap gap-1 align-middle">
              {u.added.map(item => (
                <span key={item} className="rounded-md bg-emerald-50 px-1.5 py-0.5 text-[12.5px] font-medium text-emerald-900 ring-1 ring-emerald-200" title={item}>{shorten(item, 70)}</span>
              ))}
            </span>
          ) : (
            <span className="ml-2 text-[13.5px] text-slate-800">
              {u.from !== 'empty' && <><span className="text-slate-600 line-through">{shorten(u.from, 60)}</span>{' → '}</>}
              <span className="font-medium" title={u.to}>{shorten(u.to)}</span>
            </span>
          )}
        </div>
        {u.canUndo && (
          <button type="button" onClick={onUndo} disabled={busy} data-testid="auto-update-undo"
            title="Puts back what was there before. The registry then leaves this field to you."
            className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[12.5px] font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 disabled:opacity-50">
            {busy ? <Loader2 size={12} className="animate-spin" /> : <Undo2 size={12} />} Undo
          </button>
        )}
      </div>
      {u.reason && <p className="mt-1 text-[12.5px] leading-snug text-slate-600">{u.reason}</p>}
    </li>
  )
}

// What the registry filled in or corrected on this record by itself. Short by default: the values
// are on the page above; the detail (what it was, what it rests on, Undo) opens on request.
function AutoUpdatesBlock({ updates, undoing, onUndo }: { updates: AutoUpdate[]; undoing: string | null; onUndo: (u: AutoUpdate) => void }) {
  const [open, setOpen] = useState(false)
  const corrected = updates.filter(u => !u.isList && u.from !== 'empty')
  const filled = updates.filter(u => !corrected.includes(u))
  return (
    <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 px-3.5 py-3" data-testid="auto-updates">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1.5">
        <div className="min-w-0 flex-1">
          <h4 className="text-[13.5px] font-bold text-emerald-900">Filled in for you ({updates.length})</h4>
          <p className="mt-0.5 text-[13.5px] leading-snug text-slate-800" data-testid="auto-updates-summary">
            {corrected.map(u => (
              <span key={u.id}><span className="font-semibold">{u.label}</span> corrected from {shorten(u.from, 40)} to <span className="font-semibold">{shorten(u.to, 40)}</span>.{' '}</span>
            ))}
            {filled.length > 0 && <>{corrected.length > 0 ? 'Also filled in: ' : ''}<span className="font-semibold">{filled.map(u => u.label).join(', ')}</span>.</>}
          </p>
          <p className="mt-0.5 text-[12.5px] text-slate-600">
            Read from this agent’s real usage, its traces and its own API description, so nobody has to type it. Every change is logged and can be undone.
          </p>
        </div>
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} data-testid="auto-updates-toggle"
          className="shrink-0 rounded-md px-2.5 py-1 text-[12.5px] font-semibold text-emerald-900 ring-1 ring-emerald-300 hover:bg-emerald-100">
          {open ? 'Hide details' : 'See what changed'}
        </button>
      </div>
      {open && <ul className="mt-2.5 space-y-2">{updates.map(u => <UpdateRow key={u.id} update={u} busy={undoing === u.id} onUndo={() => onUndo(u)} />)}</ul>}
    </div>
  )
}

function InsightBlock({ item, heading, showBasis }: { item: TabInsight & { insight: Insight }; heading: boolean; showBasis: boolean }) {
  const [all, setAll] = useState(false)
  const [gaps, setGaps] = useState(false)
  const { insight } = item
  const out = insight.output

  if (insight.status !== 'ok' || !out) {
    return (
      <div className="space-y-1" data-testid="tab-insight" data-kind={item.kind}>
        {heading && <h4 className="text-[12px] font-bold uppercase tracking-wide text-slate-600">{item.title}</h4>}
        <p className="rounded-lg bg-slate-50 px-3 py-2 text-[13.5px] text-slate-700 ring-1 ring-slate-200" data-testid="insight-status">{statusText(insight)}</p>
      </div>
    )
  }
  const found = out.findings
  const shown = all ? found : found.slice(0, PREVIEW)
  const hidden = found.length - shown.length
  return (
    <div className="space-y-2.5" data-testid="tab-insight" data-kind={item.kind}>
      {heading && <h4 className="text-[12px] font-bold uppercase tracking-wide text-slate-600">{item.title}</h4>}
      {item.recordChangedSince && (
        <p className="text-[12.5px] font-medium text-amber-800">Written before the record last changed, so parts of it may be out of date.</p>
      )}
      <p className="text-[14.5px] leading-relaxed text-slate-800" data-testid="insight-summary">{out.summary}</p>
      {shown.length > 0 && (
        <ul className="space-y-2">{shown.map((f, i) => <FindingItem key={i} finding={f} insight={insight} basis={showBasis ? 'text' : 'none'} brief />)}</ul>
      )}
      {(hidden > 0 || (all && found.length > PREVIEW)) && (
        <button type="button" className="text-[13px] font-semibold text-zen-700 hover:underline" onClick={() => setAll(!all)} data-testid="insight-more">
          {all ? 'Show fewer' : `Show ${hidden} more`}
        </button>
      )}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {out.notDetermined.length > 0 && (
          <button type="button" className="text-[13px] font-semibold text-slate-700 hover:underline" onClick={() => setGaps(!gaps)} aria-expanded={gaps}>
            {gaps ? 'Hide' : 'See'} what could not be determined ({out.notDetermined.length})
          </button>
        )}
        <span className="ml-auto"><InsightFeedback insight={insight} /></span>
      </div>
      {gaps && (
        <ul className="list-disc space-y-0.5 rounded-lg bg-slate-50 py-2 pl-7 pr-3 text-[13px] text-slate-700 ring-1 ring-slate-200" data-testid="insight-gaps">
          {out.notDetermined.map((n, i) => <li key={i}>{n}</li>)}
        </ul>
      )}
    </div>
  )
}

// The one AI card at the bottom of each tab of the agent page. It first lets the registry bring
// the record up to date from what it can see for itself (real usage, traces, the app's own API
// description), then says what was filled in, what the analysis found, and what only a person
// can still provide. The first and the last of those are facts from the registry; only the
// analysis in between is written by AI.
export default function TabInsights({ agentId, tab, onRecordChanged }: { agentId: string; tab: InsightTab; onRecordChanged: () => void }) {
  const [data, setData] = useState<TabData | null>(null)
  const [phase, setPhase] = useState<Phase>('loading')
  const [note, setNote] = useState<string | null>(null)
  const [undoing, setUndoing] = useState<string | null>(null)
  const [reading, setReading] = useState<InsightKind | null>(null)
  const [showBasis, setShowBasis] = useState(false)
  // Each pass through `sync` holds a number; a newer pass (or leaving the page) makes the older one stop.
  const pass = useRef(0)
  const changed = useRef(onRecordChanged)
  changed.current = onRecordChanged

  const sync = useCallback(async (force: boolean) => {
    const mine = ++pass.current
    const current = () => mine === pass.current
    const fetchState = async () => (await getTabInsights(agentId, tab)).data
    setNote(null)

    let state: TabData
    try {
      state = await fetchState()
    } catch (e) {
      if (current()) { setNote(errorText(e, 'The AI insights could not be loaded.')); setPhase('ready') }
      return
    }
    if (!current()) return
    setData(state)

    try {
      const askedRecently = Date.now() - (lastAsked.get(agentId) ?? 0) < RETRIGGER_MS
      if (state.autoUpdates.running || force || (state.autoUpdates.due && !askedRecently)) {
        setPhase('updating')
        if (!state.autoUpdates.running) {
          lastAsked.set(agentId, Date.now())
          // Usage, record, cost, risks and governance, one after another. A viewer without edit
          // rights is refused, and a long run may outlive the request: either way carry on.
          try { await refreshAgent(agentId) } catch { /* shown below as whatever the record now holds */ }
        }
        state = await fetchState()
        for (let i = 0; i < MAX_POLLS && state.autoUpdates.running && current(); i++) {
          await new Promise(resolve => window.setTimeout(resolve, POLL_MS))
          state = await fetchState()
        }
        if (!current()) return
        setData(state)
        changed.current()
      }

      const todo = state.insights.filter(i => !i.readsContent && (force || !i.insight || i.stale))
      if (todo.length) {
        setPhase('writing')
        // Hide a summary that was written for the record as it used to be while its replacement is written.
        setData({ ...state, insights: state.insights.map(i => (todo.includes(i) && i.recordChangedSince ? { ...i, insight: null } : i)) })
        const results = await Promise.allSettled(todo.map(i => runInsight(agentId, i.kind)))
        if (!current()) return
        const failed = results.find(r => r.status === 'rejected') as PromiseRejectedResult | undefined
        // A viewer without edit rights is simply shown what there is.
        if (failed && failed.reason?.response?.status !== 403) setNote(errorText(failed.reason, 'The summary could not be written just now.'))
        state = await fetchState()
        if (!current()) return
        setData(state)
      }
    } catch (e) {
      if (current()) setNote(errorText(e, 'The AI insights could not be refreshed just now.'))
    }
    if (current()) setPhase('ready')
  }, [agentId, tab])

  useEffect(() => {
    setData(null)
    setPhase('loading')
    sync(false)
    return () => { pass.current++ }
  }, [sync])

  async function undo(u: AutoUpdate) {
    setUndoing(u.id)
    setNote(null)
    try {
      await undoAutoUpdate(agentId, u.id)
      changed.current()
      await sync(false)                    // the summary described the record as it was, so it is rewritten
    } catch (e) {
      setNote(errorText(e, 'That could not be undone.'))
    } finally {
      setUndoing(null)
    }
  }

  async function read(kind: InsightKind, allowFirst: boolean) {
    setReading(kind)
    setNote(null)
    try {
      if (allowFirst) await setContentAudit(agentId, true)
      await runInsight(agentId, kind)
      setData((await getTabInsights(agentId, tab)).data)
    } catch (e) {
      setNote(errorText(e, 'That could not be read just now.'))
    } finally {
      setReading(null)
    }
  }

  async function stopReadingTraces() {
    try {
      await setContentAudit(agentId, false)
      setData((await getTabInsights(agentId, tab)).data)
    } catch (e) {
      setNote(errorText(e, 'That could not be switched off.'))
    }
  }

  const busy = phase !== 'ready'
  const updates = data?.autoUpdates.updates ?? []
  const unread = data?.autoUpdates.evidence?.unread ?? []
  const needsPerson = data?.autoUpdates.needsPerson ?? []
  const written = (data?.insights ?? []).filter((i): i is TabInsight & { insight: Insight } => !i.readsContent && !!i.insight)
  const readers = (data?.insights ?? []).filter(i => i.readsContent)
  const newest = written.map(i => i.insight.createdAt).filter(Boolean).sort().pop() ?? null
  const hasRefs = written.some(i => i.insight.output?.findings.some(f => f.refs.length > 0))

  return (
    <section className="mt-8 rounded-2xl border border-zen-100 bg-gradient-to-b from-zen-50/60 to-white p-5" data-testid="tab-insights" data-phase={phase} aria-label="AI insights">
      <div className="flex flex-wrap items-center gap-2">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-zen-600 text-white"><Sparkles size={15} /></span>
        <h3 className="text-[15px] font-bold text-slate-900">AI insights</h3>
        {!busy && newest && <span className="text-[12.5px] text-slate-600">written {insightAge(newest)}</span>}
        <button type="button" className="btn-secondary btn-sm ml-auto inline-flex items-center gap-1.5" onClick={() => sync(true)} disabled={busy} data-testid="insights-refresh"
          title="Reads this agent's latest usage, traces and API description, fills in what the record is missing, recalculates cost, risks and governance, and rewrites this summary.">
          <RefreshCw size={13} className={busy ? 'animate-spin' : ''} /> {busy ? 'Working…' : 'Check again'}
        </button>
      </div>

      <div className="mt-3 space-y-4">
        {busy && (
          <p className="flex items-center gap-2 text-[13.5px] text-zen-800" role="status" data-testid="insights-progress">
            <Loader2 size={14} className="animate-spin" />
            {phase === 'updating'
              ? 'Reading this agent’s latest usage, traces and API description, and filling in what the record is missing. This can take a minute.'
              : phase === 'writing' ? 'Writing the summary. This usually takes 20 to 40 seconds.' : 'Loading…'}
          </p>
        )}
        {note && <p className="rounded-lg bg-amber-50 px-3 py-2 text-[13px] text-amber-900 ring-1 ring-amber-200" role="alert">{note}</p>}

        {updates.length > 0 && <AutoUpdatesBlock updates={updates} undoing={undoing} onUndo={undo} />}
        {unread.length > 0 && !busy && (
          <p className="text-[12.5px] text-amber-800" data-testid="auto-unread">
            At the last check the registry could not read {unread.join(' or ')}, so some fields may still be empty. It will try again by itself.
          </p>
        )}

        {written.map(item => <InsightBlock key={item.insight.id} item={item} heading={written.length > 1} showBasis={showBasis} />)}
        {!busy && data && written.length === 0 && !note && (
          <p className="text-[13.5px] text-slate-700">No summary has been written for this page yet.</p>
        )}

        {needsPerson.length > 0 && (
          <div className="rounded-xl border border-amber-200 bg-amber-50/60 px-3.5 py-3" data-testid="needs-person">
            <h4 className="text-[13.5px] font-bold text-amber-900">Only a person can provide ({needsPerson.length})</h4>
            <ul className="mt-1 space-y-0.5 text-[13.5px] leading-snug text-slate-800">
              {needsPerson.map(n => (
                <li key={n.key} data-key={n.key}><span className="font-semibold">{n.label}</span> <span className="text-slate-700">— {n.why}</span>
                  {n.suggested && (
                    <span className="ml-1 inline-flex flex-wrap items-center gap-1.5" data-testid="person-suggestion">
                      <span className="text-slate-700">Its traces say: <span className="font-semibold text-slate-900">{n.suggested.label}</span>.</span>
                      <button type="button" className="btn-secondary btn-sm !py-0.5" disabled={busy}
                        title={`Set this from ${n.suggested.source}. You confirm it, so it is recorded as your change.`}
                        onClick={async () => {
                          try {
                            await updateAgent(agentId, n.key === 'owner' ? { owner: n.suggested!.value } : { dept: n.suggested!.value })
                            onRecordChanged()
                            await sync(false)
                          } catch { /* the page keeps its values; the server message shows on the next load */ }
                        }}>Use it</button>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {readers.map(item => {
          const text = READERS[item.kind]
          if (!text) return null
          const needsSwitch = item.kind === 'trace_audit' && !data?.traceTextAllowed
          return (
            <div key={item.kind} className="space-y-2 border-t border-slate-200 pt-3" data-testid="content-insight" data-kind={item.kind}>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <p className="min-w-0 flex-1 text-[13px] text-slate-700">{text.about}</p>
                <button type="button" className="btn-secondary btn-sm inline-flex items-center gap-1.5" disabled={busy || reading !== null} onClick={() => read(item.kind, needsSwitch)} data-testid="content-insight-run">
                  {reading === item.kind ? <><Loader2 size={13} className="animate-spin" /> Reading…</> : needsSwitch ? 'Allow and check a sample' : item.insight ? text.again : text.ask}
                </button>
                {item.kind === 'trace_audit' && data?.traceTextAllowed && (
                  <button type="button" className="text-[12.5px] font-semibold text-slate-700 underline" onClick={stopReadingTraces}>Stop reading its answers</button>
                )}
              </div>
              {item.insight && <InsightBlock item={{ ...item, insight: item.insight }} heading showBasis={showBasis} />}
            </div>
          )
        })}

        {written.length > 0 && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-slate-200 pt-2.5 text-[12.5px] text-slate-600">
            <span>The summary and its points are written by AI from the registry’s own records. Check anything important before relying on it.</span>
            {hasRefs && (
              <button type="button" className="font-semibold text-slate-700 hover:underline" onClick={() => setShowBasis(!showBasis)} aria-pressed={showBasis} data-testid="insights-basis">
                {showBasis ? 'Hide' : 'Show'} what each point is based on
              </button>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
