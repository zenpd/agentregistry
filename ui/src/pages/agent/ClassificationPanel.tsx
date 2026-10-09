import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Scale } from 'lucide-react'
import {
  confirmClassification, getClassification, getClassificationQuestions, saveClassification, suggestClassification,
  type Category, type ClassificationRecord, type ClassificationState, type Level, type Question, type Suggestion,
} from '../../services/ops/classification'
import { can, notAllowed, useMe } from '../../lib/me'
import { SectionLabel } from './shared'

type Answers = Record<string, unknown>
type Meta = Awaited<ReturnType<typeof getClassificationQuestions>>['data']

const LEVEL_PILL: Record<string, string> = {
  HIGH: 'bg-rose-50 text-rose-700 ring-rose-200',
  MEDIUM: 'bg-amber-50 text-amber-700 ring-amber-200',
  LOW: 'bg-slate-100 text-slate-700 ring-slate-200',
}

function errorMessage(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  return typeof detail === 'string' ? detail : e?.message || fallback
}

function fmtDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—'
}

function Pill({ level }: { level: string | null }) {
  if (!level) return null
  return <span className={`rounded-full px-2 py-0.5 text-[12px] font-bold ring-1 ${LEVEL_PILL[level] || LEVEL_PILL.LOW}`}>{level}</span>
}

// Governance tab → Classification: the EU AI Act category and the risk level,
// from questions, confirmed by a named person, with the risk class of the tools.
export default function ClassificationPanel({ agentId, onDone }: { agentId: string; onDone: () => Promise<void> }) {
  const me = useMe()
  const [state, setState] = useState<ClassificationState | null>(null)
  const [meta, setMeta] = useState<Meta | null>(null)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try { setState((await getClassification(agentId)).data); setError(null) } catch (e) { setError(errorMessage(e, 'Could not load the classification')) }
  }, [agentId])
  useEffect(() => { load(); getClassificationQuestions().then(r => setMeta(r.data)).catch(() => setMeta(null)) }, [load])

  const done = useCallback(async () => { setOpen(false); await load(); await onDone() }, [load, onDone])

  if (!state || !meta) return error ? <p className="text-sm text-rose-600">{error}</p> : null
  const { current, pending, toolRisk } = state

  return (
    <div className="rounded-xl ring-1 ring-gray-100 p-4 space-y-3" data-testid="classification">
      <div className="flex items-center gap-2">
        <Scale size={16} className="text-zen-600" />
        <SectionLabel tip="classification">Classification</SectionLabel>
      </div>

      <div className="text-sm text-slate-800" data-testid="classification-current">
        {current ? (
          <>
            EU AI Act category <b>{current.category}</b> · risk level <Pill level={current.riskLevel} />
            <span className="text-slate-600"> · confirmed by {current.confirmedBy} on {fmtDate(current.confirmedAt)}</span>
            {current.note && <span className="block text-[13px] text-slate-600">Note: {current.note}</span>}
          </>
        ) : (
          <span className="text-amber-800">
            Not confirmed. The record says {state.recorded.category || 'no category'}, risk level {state.recorded.riskLevel || 'not set'}, entered at registration, without answering the classification questions.
          </span>
        )}
      </div>

      <div className="text-[13px] text-slate-700" data-testid="tool-risk">
        <span className="font-semibold">Highest risk class among its tools: </span>
        {toolRisk.listEmpty
          ? <>no approved tool list yet. {can(me, 'admin') ? <Link to="/settings#approved-tools" className="text-zen-700 hover:underline">Build it in Settings</Link> : 'A Registry Admin builds it in Settings.'}</>
          : toolRisk.class
            ? <><Pill level={toolRisk.class} /> from {toolRisk.source}. The suggested risk level is never lower than this.</>
            : <>none of the declared tools is on the approved list.</>}
        {!toolRisk.listEmpty && toolRisk.unlisted.length > 0 && (
          <span className="block text-amber-800">Not on the approved list: {toolRisk.unlisted.join(', ')}.</span>
        )}
        {toolRisk.tools.length === 0 && <span className="block text-slate-500">The record declares no tools, systems, databases or knowledge bases.</span>}
      </div>

      {pending && (
        <PendingBox rec={pending} canConfirm={state.canConfirm} meta={meta} agentId={agentId} onDone={done} confirmedBy={meta.confirmedBy} />
      )}

      {!open && (can(me, 'update')
        ? <button type="button" className="btn-secondary btn-sm" onClick={() => setOpen(true)} data-testid="classify">
            {current || pending ? 'Classify again' : 'Answer the classification questions'}
          </button>
        : me && <p className="text-[12.5px] text-slate-500">{notAllowed(me, 'classify an agent')}</p>)}
      {open && <Wizard agentId={agentId} meta={meta} canConfirm={state.canConfirm} start={pending?.answers || current?.answers || {}}
        onCancel={() => setOpen(false)} onDone={done} />}

      {state.history.length > 0 && (
        <details className="text-[13px]">
          <summary className="cursor-pointer text-slate-600">Earlier classifications ({state.history.length})</summary>
          <ul className="mt-2 space-y-1">
            {state.history.map(r => (
              <li key={r.id} className="text-slate-700">
                {fmtDate(r.confirmedAt || r.proposedAt)} · {r.status === 'confirmed' ? 'confirmed' : r.status === 'proposed' ? 'proposed' : 'replaced'} ·{' '}
                {r.category}, {r.riskLevel} · suggested {r.suggestedCategory}, {r.suggestedRiskLevel} · by {r.confirmedBy || r.proposedBy}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function Reasons({ reasons }: { reasons: string[] }) {
  return <ul className="list-disc pl-5 text-[13px] text-slate-700 space-y-0.5">{reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
}

function ResultFields({ meta, category, level, note, setCategory, setLevel, setNote, lower }: {
  meta: Meta; category: string; level: string; note: string
  setCategory: (v: string) => void; setLevel: (v: string) => void; setNote: (v: string) => void; lower: boolean
}) {
  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="text-[12.5px] text-slate-600">EU AI Act category
        <select className="input mt-0.5 !w-48 text-sm" value={category} onChange={e => setCategory(e.target.value)} data-testid="cls-category">
          {meta.categories.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </label>
      <label className="text-[12.5px] text-slate-600">Risk level
        <select className="input mt-0.5 !w-32 text-sm" value={level} onChange={e => setLevel(e.target.value)} data-testid="cls-level">
          {meta.levels.map(l => <option key={l} value={l}>{l}</option>)}
        </select>
      </label>
      <label className="flex-1 min-w-[240px] text-[12.5px] text-slate-600">
        Note {lower ? <span className="text-rose-700">(required, at least {meta.minNoteWhenLower} characters, because your choice is lower than the suggestion)</span> : '(optional)'}
        <input className="input mt-0.5 text-sm" value={note} onChange={e => setNote(e.target.value)} data-testid="cls-note" />
      </label>
    </div>
  )
}

const CAT_ORDER: Category[] = ['Minimal Risk', 'Limited Risk', 'High Risk', 'Unacceptable Risk']
const LVL_ORDER: Level[] = ['LOW', 'MEDIUM', 'HIGH']
const isLower = (c: string, l: string, sc: string, sl: string) =>
  CAT_ORDER.indexOf(c as Category) < CAT_ORDER.indexOf(sc as Category) || LVL_ORDER.indexOf(l as Level) < LVL_ORDER.indexOf(sl as Level)

function PendingBox({ rec, canConfirm, meta, agentId, onDone, confirmedBy }: {
  rec: ClassificationRecord; canConfirm: boolean; meta: Meta; agentId: string; onDone: () => Promise<void>; confirmedBy: string
}) {
  const [category, setCategory] = useState<string>(rec.category || rec.suggestedCategory)
  const [level, setLevel] = useState<string>(rec.riskLevel || rec.suggestedRiskLevel)
  const [note, setNote] = useState(rec.note || '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const lower = isLower(category, level, rec.suggestedCategory, rec.suggestedRiskLevel)
  async function confirm() {
    setBusy(true); setError(null)
    try { await confirmClassification(agentId, rec.id, { category, riskLevel: level, note }); await onDone() }
    catch (e) { setError(errorMessage(e, 'The classification was not confirmed')) } finally { setBusy(false) }
  }
  return (
    <div className="rounded-lg border border-violet-200 bg-violet-50/50 p-3 space-y-2" data-testid="classification-pending">
      <p className="text-sm text-slate-800">
        <b>Waiting for confirmation:</b> {rec.category}, risk level {rec.riskLevel}, proposed by {rec.proposedBy} on {fmtDate(rec.proposedAt)}.
        The agent's category and risk level change only when it is confirmed.
      </p>
      <Reasons reasons={rec.reasons} />
      {canConfirm ? (
        <>
          <ResultFields meta={meta} category={category} level={level} note={note} setCategory={setCategory} setLevel={setLevel} setNote={setNote} lower={lower} />
          <button type="button" className="btn-primary btn-sm" disabled={busy || (lower && note.trim().length < meta.minNoteWhenLower)} onClick={confirm} data-testid="confirm-classification">
            {busy ? 'Confirming…' : 'Confirm this classification'}
          </button>
        </>
      ) : <p className="text-[12.5px] text-slate-600">An {confirmedBy} confirms it.</p>}
      {error && <p className="text-[13px] text-rose-700">{error}</p>}
    </div>
  )
}

function Wizard({ agentId, meta, canConfirm, start, onCancel, onDone }: {
  agentId: string; meta: Meta; canConfirm: boolean; start: Answers; onCancel: () => void; onDone: () => Promise<void>
}) {
  const [answers, setAnswers] = useState<Answers>({ prohibited: [], ...start })
  const [sug, setSug] = useState<Suggestion | null>(null)
  const [category, setCategory] = useState('')
  const [level, setLevel] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const t = setTimeout(() => {
      suggestClassification(agentId, answers).then(r => { setSug(r.data); setCategory(r.data.category); setLevel(r.data.riskLevel) }).catch(() => setSug(null))
    }, 250)
    return () => clearTimeout(t)
  }, [agentId, answers])

  const set = (k: string, v: unknown) => setAnswers(a => ({ ...a, [k]: v }))
  const visible = (q: Question) => !q.showIf || (answers[q.showIf.key] !== undefined && answers[q.showIf.key] !== q.showIf.not)
  const complete = sug !== null && sug.missing.length === 0
  const lower = !!sug && isLower(category, level, sug.category, sug.riskLevel)

  async function save(confirm: boolean) {
    setBusy(true); setError(null)
    try { await saveClassification(agentId, { answers, confirm, category, riskLevel: level, note }); await onDone() }
    catch (e) { setError(errorMessage(e, 'The answers were not saved')) } finally { setBusy(false) }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 space-y-3" data-testid="classification-wizard">
      {meta.questions.filter(visible).map(q => (
        <fieldset key={q.key} className="space-y-1" data-testid={`q-${q.key}`}>
          <legend className="text-sm font-semibold text-slate-900">{q.label}</legend>
          {q.help && <p className="text-[12.5px] text-slate-600">{q.help}</p>}
          {q.kind === 'bool' && (
            <div className="flex gap-4 text-sm">
              {[['Yes', true], ['No', false]].map(([label, v]) => (
                <label key={String(label)} className="flex items-center gap-1.5">
                  <input type="radio" name={q.key} checked={answers[q.key] === v} onChange={() => set(q.key, v)} /> {label}
                </label>
              ))}
            </div>
          )}
          {q.kind === 'single' && (
            <div className="grid gap-1 sm:grid-cols-2 text-sm">
              {q.options!.map(o => (
                <label key={o.value} className="flex items-start gap-1.5">
                  <input type="radio" className="mt-1" name={q.key} checked={answers[q.key] === o.value} onChange={() => set(q.key, o.value)} /> {o.label}
                </label>
              ))}
            </div>
          )}
          {q.kind === 'multi' && (
            <div className="grid gap-1 sm:grid-cols-2 text-sm">
              {q.options!.map(o => {
                const list = (answers[q.key] as string[]) || []
                return (
                  <label key={o.value} className="flex items-start gap-1.5">
                    <input type="checkbox" className="mt-1" checked={list.includes(o.value)}
                      onChange={e => set(q.key, e.target.checked ? [...list, o.value] : list.filter(x => x !== o.value))} /> {o.label}
                  </label>
                )
              })}
            </div>
          )}
        </fieldset>
      ))}

      {sug && (
        <div className="rounded-lg bg-white p-3 ring-1 ring-slate-200 space-y-2" data-testid="classification-suggestion">
          <p className="text-sm text-slate-900">
            Suggested: <b>{sug.category}</b>, risk level <Pill level={sug.riskLevel} />
            {!complete && <span className="ml-2 text-[12.5px] text-amber-800">Answer every question to save ({sug.missing.length} left).</span>}
          </p>
          <Reasons reasons={sug.reasons} />
          <ResultFields meta={meta} category={category} level={level} note={note} setCategory={setCategory} setLevel={setLevel} setNote={setNote} lower={lower} />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {canConfirm && (
          <button type="button" className="btn-primary btn-sm" disabled={busy || !complete || (lower && note.trim().length < meta.minNoteWhenLower)}
            onClick={() => save(true)} data-testid="save-confirm">Confirm as the agent's classification</button>
        )}
        <button type="button" className={canConfirm ? 'btn-secondary btn-sm' : 'btn-primary btn-sm'} disabled={busy || !complete || (lower && note.trim().length < meta.minNoteWhenLower)}
          onClick={() => save(false)} data-testid="save-proposal">Save as a proposal</button>
        <button type="button" className="btn-ghost btn-sm" disabled={busy} onClick={onCancel}>Cancel</button>
        {!canConfirm && <span className="text-[12.5px] text-slate-600">An {meta.confirmedBy} confirms it.</span>}
      </div>
      {error && <p className="text-[13px] text-rose-700">{error}</p>}
    </div>
  )
}
