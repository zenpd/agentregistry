import { Link } from 'react-router-dom'
import { ShieldCheck, ShieldAlert, CheckCircle2, CircleAlert, ArrowRight } from 'lucide-react'
import InfoTip from './InfoTip'
import type { ReuseCheck, ReuseStatus } from '../services/api'

const tabHref = (agentId: string, tab: ReuseCheck['tab']) => `/agents/${encodeURIComponent(agentId)}?tab=${tab}`

// Status pill per failing check, in the shared semantic tones.
const PILL = {
  muted: 'bg-slate-100 text-slate-700 ring-slate-200',
  info: 'bg-sky-50 text-sky-700 ring-sky-200',
  warn: 'bg-[#fffbeb] text-[#b45309] ring-[#fde68a]',
  danger: 'bg-[#fef2f2] text-[#dc2626] ring-[#fecaca]',
  success: 'bg-[#f0fdf4] text-[#15803d] ring-[#bbf7d0]',
}

function statusPill(c: ReuseCheck): { text: string; tone: keyof typeof PILL } {
  if (c.key === 'stage') return { text: 'Not in Production', tone: 'muted' }
  if (c.key === 'risk') return { text: 'Open risk', tone: 'danger' }
  switch (c.status) {
    case 'In Review': return { text: 'In review', tone: 'info' }
    case 'Changes Requested': return { text: 'Changes requested', tone: 'danger' }
    case 'Approved':
    case 'Approved with Conditions': return { text: 'Expired', tone: 'danger' }
    default: return { text: 'Not submitted', tone: 'muted' }
  }
}

// The pill already names the status, so the line under it says what
// happens next rather than repeating it.
function nextStep(c: ReuseCheck): string {
  if (c.key === 'stage') return `${c.detail} — only Production agents can be certified.`
  if (c.key === 'risk') return `${c.detail} — close or re-rate them on the Risk tab.`
  switch (c.status) {
    case 'In Review': return 'Waiting on the reviewer’s decision.'
    case 'Changes Requested': return 'The reviewer asked for changes before approving.'
    case 'Approved':
    case 'Approved with Conditions': return 'The approval has lapsed and needs to be renewed.'
    default: return 'The owner still has to submit it for review.'
  }
}

function actionLabel(c: ReuseCheck): string {
  if (c.key === 'stage') return 'Change stage'
  return c.tab === 'risk' ? 'Resolve on Risk' : 'Resolve on Governance'
}

// Reuse certification for one agent: whether another team can safely build
// on it, and exactly what stands in the way. Failing checks come first, each
// with where it is resolved, so the answer never has to be pieced together
// from the Governance and Risk tabs.
export default function ReuseChecklist({ reuse, agentId }: { reuse: ReuseStatus; agentId: string }) {
  const failing = reuse.checks.filter(c => !c.met)
  const passed = reuse.checks.filter(c => c.met)
  const ok = reuse.certified
  return (
    <section
      className={`rounded-2xl border bg-white shadow-sm overflow-hidden ${ok ? 'border-emerald-200' : 'border-amber-200'}`}
      data-testid="reuse-checklist"
    >
      <header className={`px-5 pt-4 pb-3.5 bg-gradient-to-r ${ok ? 'from-emerald-50 via-white' : 'from-amber-50 via-white'} to-white`}>
        <div className="flex items-start gap-3.5">
          <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${ok ? 'bg-emerald-100 text-emerald-600' : 'bg-amber-100 text-amber-600'}`}>
            {ok ? <ShieldCheck size={22} /> : <ShieldAlert size={22} />}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-[16px] font-extrabold text-slate-900">Reuse certification <InfoTip term="certified_for_reuse" /></h3>
              <span className={`inline-flex items-center rounded-full px-2.5 py-[3px] text-[12px] font-bold ring-1 ${ok ? PILL.success : PILL.warn}`}>
                {ok ? 'Certified for reuse' : 'Not certified for reuse'}
              </span>
            </div>
            <p className="mt-1 text-[13px] text-slate-600">
              {ok
                ? 'Another team can build on this agent: it is in Production, every review is approved and no serious risk is open.'
                : 'Another team should not build on this agent yet. All five checks must pass — resolve the ones below.'}
            </p>
          </div>
          <div className="shrink-0 text-right">
            <div className="text-[28px] font-extrabold leading-none text-slate-900">
              {passed.length}<span className="text-[16px] font-bold text-slate-500">/{reuse.checks.length}</span>
            </div>
            <div className="mt-1 text-[12px] font-semibold uppercase tracking-[.04em] text-slate-600">checks passed <InfoTip term="certification_checks" /></div>
          </div>
        </div>
        <div className="mt-3 flex gap-1" aria-hidden>
          {reuse.checks.map(c => (
            <span key={c.key} className={`h-1.5 flex-1 rounded-full ${c.met ? (c.conditions ? 'bg-amber-400' : 'bg-emerald-500') : 'bg-gray-200'}`} />
          ))}
        </div>
      </header>

      <div className="px-5 pb-4 pt-3 space-y-3">
        {failing.length > 0 && (
          <div>
            <div className="mb-1.5 text-[12px] font-bold uppercase tracking-[.05em] text-amber-700">Needs attention · {failing.length}</div>
            <ul className="space-y-1.5">
              {failing.map(c => {
                const pill = statusPill(c)
                return (
                  <li key={c.key} data-testid={`reuse-check-${c.key}`} data-met={false}>
                    <Link
                      to={tabHref(agentId, c.tab)}
                      className="group flex items-center gap-3 rounded-xl border border-amber-200 border-l-[3px] border-l-amber-400 bg-white px-3.5 py-2.5 transition-colors hover:bg-amber-50/60"
                    >
                      <CircleAlert size={18} className="shrink-0 text-amber-500" />
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-[14px] font-semibold text-slate-900">{c.label}</span>
                          <span className={`inline-flex rounded-full px-2 py-[1px] text-[12px] font-bold ring-1 ${PILL[pill.tone]}`}>{pill.text}</span>
                        </div>
                        <div className="text-[13px] text-slate-700">{nextStep(c)}</div>
                      </div>
                      <span className="hidden sm:inline-flex shrink-0 items-center gap-1 rounded-full border border-zen-200 bg-zen-50 px-3 py-1 text-[12px] font-semibold text-zen-700 group-hover:bg-zen-100">
                        {actionLabel(c)} <ArrowRight size={13} />
                      </span>
                    </Link>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
        {passed.length > 0 && (
          <div>
            <div className="mb-1.5 text-[12px] font-bold uppercase tracking-[.05em] text-emerald-700">Passed · {passed.length}</div>
            <ul className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
              {passed.map(c => (
                <li key={c.key} data-testid={`reuse-check-${c.key}`} data-met={true}
                  className="flex items-center gap-2.5 rounded-xl bg-emerald-50/50 px-3 py-2 ring-1 ring-emerald-100">
                  <CheckCircle2 size={16} className={`shrink-0 ${c.conditions ? 'text-amber-500' : 'text-emerald-600'}`} />
                  <span className="text-[13px] font-semibold text-slate-800">{c.label}</span>
                  {c.conditions ? (
                    <Link to={tabHref(agentId, c.tab)} className={`ml-auto inline-flex rounded-full px-2 py-[1px] text-[12px] font-bold ring-1 ${PILL.warn} hover:brightness-95`}
                      title="Approved with conditions — read them on the Governance tab">
                      With conditions
                    </Link>
                  ) : (
                    <span className="ml-auto text-[12px] text-slate-600">{c.detail}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
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
