import { useState } from 'react'
import { Loader2, MessageCircleQuestion, Sparkles } from 'lucide-react'
import { askRegistry, type Insight } from '../services/ops/insights'
import { InsightResult } from '../components/InsightPanel'
import ErrorNote from '../components/ErrorNote'
import InfoTip from '../components/InfoTip'

const EXAMPLES = [
  'Which agents are in Production without all three reviews approved?',
  'Which agents use a model different from the one they declare?',
  'What does the retail bank onboarding agent depend on?',
  'Which agents have no owner recorded?',
]

// Ask the Registry: a question in plain words, answered by an AI agent that
// looks it up with the registry's own read-only tools and links every row.
export default function AskPage() {
  const [question, setQuestion] = useState('')
  const [asked, setAsked] = useState<string | null>(null)
  const [answer, setAnswer] = useState<Insight | null>(null)
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function ask(text: string) {
    const q = text.trim()
    if (q.length < 3 || asking) return
    setAsking(true)
    setError(null)
    setAnswer(null)
    setAsked(q)
    try {
      setAnswer((await askRegistry(q)).data)
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'The question could not be answered just now.')
    } finally {
      setAsking(false)
    }
  }

  return (
    <div className="space-y-5 animate-fade-in max-w-4xl">
      <div>
        <h1 className="text-2xl font-bold gradient-text flex items-center gap-1.5">Ask the Registry <InfoTip term="ask_registry" /></h1>
        <p className="text-slate-600 mt-0.5">Ask about the registered AI agents in plain words. The answer links to the records it came from.</p>
      </div>

      <form className="card p-4 space-y-3" onSubmit={e => { e.preventDefault(); ask(question) }}>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <MessageCircleQuestion size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input className="input pl-9" value={question} onChange={e => setQuestion(e.target.value)} maxLength={600}
              placeholder="e.g. Which production agents have open high risks?" aria-label="Your question" />
          </div>
          <button type="submit" className="btn-primary btn-sm shrink-0" disabled={asking || question.trim().length < 3} data-testid="ask-button">
            {asking ? <><Loader2 size={14} className="animate-spin" /> Looking…</> : <><Sparkles size={14} /> Ask</>}
          </button>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {EXAMPLES.map(e => (
            <button key={e} type="button" disabled={asking} onClick={() => { setQuestion(e); ask(e) }}
              className="rounded-full bg-slate-50 px-2.5 py-1 text-[12px] text-slate-700 ring-1 ring-slate-200 hover:bg-zen-50 hover:text-zen-700">{e}</button>
          ))}
        </div>
      </form>

      {error && <ErrorNote message={error} onDismiss={() => setError(null)} />}
      {asking && <p className="text-[13px] text-slate-600">Looking through the registry. This usually takes 20 to 40 seconds.</p>}
      {answer && (
        <div className="card p-5 space-y-3" data-testid="ask-answer">
          <div className="text-[12px] font-bold uppercase tracking-wide text-slate-500">{asked}</div>
          <InsightResult insight={answer} basis="links" />
        </div>
      )}
    </div>
  )
}
