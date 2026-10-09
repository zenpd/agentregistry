import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ThumbsDown, ThumbsUp } from 'lucide-react'
import { sendInsightFeedback, type Insight, type InsightFinding } from '../services/ops/insights'

// Where the record behind a citation lives.
const TAB_OF: Record<string, string> = {
  review: 'governance', check: 'governance', evidence: 'governance', risk: 'risk', usage: 'tokenomics', model: 'tokenomics',
  anomaly: 'tokenomics', economics: 'revenue', dep: 'diagram', step: 'diagram', span: 'diagram', contract: 'integrate',
}

function refLink(ref: string): string | null {
  const [kind, agentId] = ref.split(':')
  if (kind === 'draft' || !agentId) return null
  const tab = TAB_OF[kind]
  return `/agents/${agentId}${tab ? `?tab=${tab}` : ''}`
}

// How the records behind a finding are shown: as links (an answer that names several agents),
// as plain words, or not at all.
export type Basis = 'links' | 'text' | 'none'

export function insightAge(iso: string | null): string {
  if (!iso) return ''
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000))
  if (mins < 2) return 'just now'
  if (mins < 90) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  return hours < 36 ? `${hours} h ago` : `${Math.round(hours / 24)} days ago`
}

// `brief` leaves out the "why it matters" line, for places where the list has to stay short.
export function FindingItem({ finding: f, insight, basis, brief }: { finding: InsightFinding; insight: Insight; basis: Basis; brief?: boolean }) {
  const labels = f.refs.map(ref => ({ ref, text: insight.refs[ref] ?? ref }))
  return (
    <li className="rounded-lg border border-slate-200 bg-white px-3.5 py-2.5" data-testid="insight-finding">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[14px] font-semibold text-slate-900">{f.title}</span>
        {f.confidence === 'low' && (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[12px] font-semibold text-slate-700 ring-1 ring-slate-300" title="The evidence for this point is thin.">Uncertain</span>
        )}
      </div>
      <p className="mt-1 text-[13.5px] leading-snug text-slate-700">{f.detail}</p>
      {f.whyItMatters && !brief && <p className="mt-0.5 text-[13px] text-slate-700">{f.whyItMatters}</p>}
      {f.unverifiedFigures.length > 0 && (
        <p className="mt-1 text-[12.5px] font-medium text-amber-800">Check against the record: {f.unverifiedFigures.join(', ')} (not found in the data the AI read).</p>
      )}
      {basis === 'text' && labels.length > 0 && (
        <p className="mt-1.5 text-[12.5px] text-slate-600" data-testid="insight-basis">Based on: {labels.map(l => l.text).join(' · ')}</p>
      )}
      {basis === 'links' && labels.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {labels.map(({ ref, text }) => {
            const to = refLink(ref)
            return to
              ? <Link key={ref} to={to} className="rounded-full bg-slate-50 px-2.5 py-0.5 text-[12px] font-medium text-zen-700 ring-1 ring-slate-200 hover:bg-zen-50 hover:ring-zen-200">{text} →</Link>
              : <span key={ref} className="rounded-full bg-slate-50 px-2.5 py-0.5 text-[12px] font-medium text-slate-700 ring-1 ring-slate-200">{text}</span>
          })}
        </div>
      )}
    </li>
  )
}

export function statusText(insight: Insight): string {
  return insight.output?.summary
    || (insight.status === 'unavailable' ? 'The AI model could not be reached. The figures on this page are unaffected.' : 'Nothing to report.')
}

// What an insight agent found: a short answer, its findings, and what it could not establish.
export function InsightBody({ insight, basis = 'text' }: { insight: Insight; basis?: Basis }) {
  const [gaps, setGaps] = useState(false)
  const out = insight.output

  if (insight.status !== 'ok') {
    return <p className="rounded-lg bg-slate-50 px-3 py-2 text-[13.5px] text-slate-700 ring-1 ring-slate-200" data-testid="insight-status">{statusText(insight)}</p>
  }
  if (!out) return null
  return (
    <div className="space-y-2.5" data-testid="insight-result">
      <p className="text-[14.5px] leading-relaxed text-slate-800">{out.summary}</p>
      {out.findings.length > 0 && <ul className="space-y-2">{out.findings.map((f, i) => <FindingItem key={i} finding={f} insight={insight} basis={basis} />)}</ul>}
      {out.notDetermined.length > 0 && (
        <button type="button" className="text-[13px] font-semibold text-slate-700 hover:underline" onClick={() => setGaps(!gaps)} aria-expanded={gaps}>
          {gaps ? 'Hide' : 'See'} what could not be determined ({out.notDetermined.length})
        </button>
      )}
      {gaps && (
        <ul className="list-disc space-y-0.5 rounded-lg bg-slate-50 py-2 pl-7 pr-3 text-[13px] text-slate-700 ring-1 ring-slate-200" data-testid="insight-gaps">
          {out.notDetermined.map((n, i) => <li key={i}>{n}</li>)}
        </ul>
      )}
    </div>
  )
}

export function InsightFeedback({ insight }: { insight: Insight }) {
  const [sent, setSent] = useState(insight.feedback?.verdict ?? null)
  async function rate(verdict: 'useful' | 'not_useful') {
    setSent(verdict)
    try { await sendInsightFeedback(insight.id, verdict) } catch { /* feedback is best-effort */ }
  }
  if (insight.status !== 'ok') return null
  return (
    <span className="inline-flex items-center gap-1 text-[12.5px] text-slate-700">
      {sent ? <>Thanks — noted as {sent === 'useful' ? 'useful' : 'not useful'}.</> : <>
        Was this useful?
        <button type="button" aria-label="Useful" onClick={() => rate('useful')} className="rounded p-1 text-slate-700 hover:bg-emerald-50 hover:text-emerald-700"><ThumbsUp size={14} /></button>
        <button type="button" aria-label="Not useful" onClick={() => rate('not_useful')} className="rounded p-1 text-slate-700 hover:bg-rose-50 hover:text-rose-700"><ThumbsDown size={14} /></button>
      </>}
    </span>
  )
}

// A complete insight with its label and feedback, for places that show one on its own (Ask, the registration form).
export function InsightResult({ insight, basis }: { insight: Insight; basis?: Basis }) {
  return (
    <div className="space-y-2.5">
      <InsightBody insight={insight} basis={basis} />
      {insight.status === 'ok' && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-2">
          <span className="text-[12.5px] font-medium text-slate-700">Written by AI from the registry’s records — check before relying on it. It changed nothing.</span>
          <InsightFeedback insight={insight} />
        </div>
      )}
    </div>
  )
}
