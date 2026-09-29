import { Link } from 'react-router-dom'
import { BadgeCheck, AlertTriangle, CheckCircle2, CircleAlert, ChevronRight } from 'lucide-react'
import type { ReuseCheck, ReuseStatus } from '../services/api'

const tabHref = (agentId: string, tab: ReuseCheck['tab']) => `/agents/${encodeURIComponent(agentId)}?tab=${tab}`

// Every certification check in one row, met or not. A check that needs
// attention links to the agent-page tab where it is resolved (gates and stage
// on Governance, findings on Risk), so the reason an agent is not certified
// is visible from every tab instead of only inside Integrate.
export default function ReuseChecklist({ reuse, agentId }: { reuse: ReuseStatus; agentId: string }) {
  const met = reuse.checks.filter(c => c.met).length
  return (
    <div
      className={`rounded-xl border px-3 py-2.5 ${reuse.certified ? 'border-emerald-200 bg-emerald-50/50' : 'border-amber-200 bg-amber-50/50'}`}
      data-testid="reuse-checklist"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm">
        {reuse.certified
          ? <BadgeCheck size={16} className="text-emerald-600 shrink-0" />
          : <AlertTriangle size={16} className="text-amber-600 shrink-0" />}
        <span className={`font-semibold ${reuse.certified ? 'text-emerald-800' : 'text-amber-900'}`}>
          {reuse.certified ? 'Certified for reuse' : 'Not certified for reuse'}
        </span>
        <span className="text-xs text-gray-500">
          {met} of {reuse.checks.length} checks met
          {!reuse.certified && ' · open a check to see where it is resolved'}
        </span>
      </div>
      <ul className="mt-2 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-1.5">
        {reuse.checks.map(c => <CheckItem key={c.key} check={c} agentId={agentId} />)}
      </ul>
    </div>
  )
}

function CheckItem({ check: c, agentId }: { check: ReuseCheck; agentId: string }) {
  // Met with conditions still deserves a look, so it links like a failure.
  const attention = !c.met || !!c.conditions
  const body = (
    <>
      <span className="flex items-start gap-1.5">
        {c.met
          ? <CheckCircle2 size={14} className={`shrink-0 mt-px ${c.conditions ? 'text-amber-500' : 'text-emerald-600'}`} />
          : <CircleAlert size={14} className="shrink-0 mt-px text-amber-600" />}
        <span className="text-xs font-semibold leading-tight text-gray-800">{c.label}</span>
        {attention && <ChevronRight size={13} className="ml-auto shrink-0 mt-px text-gray-400 group-hover:text-gray-600" />}
      </span>
      <span className={`block text-[11px] leading-snug mt-0.5 ${c.met && !c.conditions ? 'text-gray-500' : 'text-amber-800'}`}>{c.detail}</span>
    </>
  )
  const base = 'block h-full rounded-lg px-2.5 py-1.5 ring-1'
  return (
    <li data-testid={`reuse-check-${c.key}`} data-met={c.met}>
      {attention ? (
        <Link to={tabHref(agentId, c.tab)} className={`group ${base} bg-white ring-amber-200 hover:ring-amber-300 hover:bg-amber-50 transition-colors`}
          title={`Resolved on the ${c.tab === 'risk' ? 'Risk' : 'Governance'} tab`}>
          {body}
        </Link>
      ) : (
        <div className={`${base} bg-white/70 ring-emerald-100`}>{body}</div>
      )}
    </li>
  )
}

// Registry-card form: one segment per check, with every check in the tooltip.
export function ReuseProgress({ reuse }: { reuse: ReuseStatus }) {
  const met = reuse.checks.filter(c => c.met).length
  const title = reuse.checks.map(c => `${c.met ? '✓' : '✗'} ${c.label}: ${c.detail}`).join('\n')
  return (
    <span className="mt-1 inline-flex items-center gap-1.5 text-xs text-amber-700" title={title} data-testid="reuse-progress">
      <span className="inline-flex gap-0.5" aria-hidden>
        {reuse.checks.map(c => (
          <span key={c.key} className={`h-1.5 w-3 rounded-full ${c.met ? 'bg-emerald-500' : 'bg-amber-300'}`} />
        ))}
      </span>
      {met}/{reuse.checks.length} reuse checks
      <span className="sr-only">. {title}</span>
    </span>
  )
}
