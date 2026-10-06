import { useState } from 'react'
import { Loader2, Sparkles } from 'lucide-react'
import { runDraftInsight, type DraftRegistration, type Insight } from '../services/ops/insights'
import { InsightResult } from './InsightPanel'
import InfoTip from './InfoTip'
import ErrorNote from './ErrorNote'

// On the registration form: an AI agent reads what has been typed so far and
// says whether it is specific and plausible, which risk tier it implies, and
// whether another agent already does the job. Advice only; it blocks nothing.
export default function DraftCoach({ draft }: { draft: () => DraftRegistration }) {
  const [result, setResult] = useState<{ kind: string; insight: Insight } | null>(null)
  const [running, setRunning] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function run(kind: 'registration_coach' | 'duplicates') {
    setRunning(kind)
    setError(null)
    try {
      setResult({ kind, insight: (await runDraftInsight(kind, draft())).data })
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'The check could not be run.')
    } finally {
      setRunning(null)
    }
  }

  return (
    <div className="rounded-xl border border-zen-100 bg-zen-50/40 p-3 space-y-2" data-testid="draft-coach">
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex items-center gap-1 text-xs font-bold uppercase tracking-wide text-zen-700"><Sparkles size={13} /> AI check of this registration</span>
        <InfoTip term="ai_insight" />
        <span className="text-xs text-slate-500">optional — it changes nothing</span>
        <span className="ml-auto flex gap-2">
          <button type="button" className="btn-secondary btn-sm" disabled={!!running} onClick={() => run('registration_coach')} data-testid="run-coach">
            {running === 'registration_coach' ? <><Loader2 size={13} className="animate-spin" /> Reading…</> : 'Is it clear and plausible?'}
          </button>
          <button type="button" className="btn-secondary btn-sm" disabled={!!running} onClick={() => run('duplicates')} data-testid="run-draft-duplicates">
            {running === 'duplicates' ? <><Loader2 size={13} className="animate-spin" /> Comparing…</> : 'Does it already exist?'}
          </button>
        </span>
      </div>
      {error && <ErrorNote message={error} onDismiss={() => setError(null)} />}
      {result && !running && <InsightResult insight={result.insight} />}
    </div>
  )
}
