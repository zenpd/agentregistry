import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getToolCallShare, type ToolCallShare } from '../../services/ops/lifecycleSteps'
import { can, useMe } from '../../lib/me'

function errorMessage(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  return typeof detail === 'string' ? detail : e?.message || fallback
}

function fmtDate(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : 'an unknown date'
}

// Governance tab → evidence: the share of traced tool calls that go to tools
// approved at the last Security Review.
export function ToolCallsLine({ agentId }: { agentId: string }) {
  const [d, setD] = useState<ToolCallShare | null>(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback((refresh = false) => {
    setBusy(true)
    return getToolCallShare(agentId, refresh).then(r => setD(r.data)).catch(() => setD(null)).finally(() => setBusy(false))
  }, [agentId])
  useEffect(() => { load() }, [load])
  if (!d) return null
  return (
    <div className="flex flex-wrap items-baseline gap-x-2" data-testid="tool-calls-line">
      <span className="text-slate-500 w-20 shrink-0">Tool calls</span>
      <span className="text-slate-600 flex-1 min-w-[240px]">
        {d.status === 'ok' ? (
          <>
            <b className={d.share === 100 ? 'text-emerald-700' : 'text-amber-800'}>{d.share}%</b> of {d.total} traced tool calls
            ({d.approved} calls) went to tools or MCP servers approved at the last Security Review
            {d.approvedAt ? ` (${fmtDate(d.approvedAt)})` : ''}. Read from the latest {d.sampleLimit} spans
            {d.sampleWindow?.from ? `, ${fmtDate(d.sampleWindow.from)} to ${fmtDate(d.sampleWindow.to)}` : ''}.
            {d.notApproved && d.notApproved.length > 0 && (
              <span className="block text-amber-800">Not approved: {d.notApproved.map(n => `${n.name} (${n.count})`).join(', ')}.</span>
            )}
          </>
        ) : d.status === 'no_tool_calls'
          ? <>No tool call in the latest {d.sampleLimit} traced spans.</>
          : d.message}
        <button type="button" className="ml-1 text-zen-700 hover:underline" disabled={busy} onClick={() => load(true)}>{busy ? 'Reading…' : 'Read again'}</button>
      </span>
    </div>
  )
}
