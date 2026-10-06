import { useEffect, useRef } from 'react'
import type { Agent } from '../../services/api'
import InfoTip from '../../components/InfoTip'
import type { GlossaryKey } from '../../lib/glossary'

export interface TabProps {
  agent: Agent
  agentId: string
  onChanged: () => void
  // Goes up when the registry has updated the record or its figures.
  dataVersion: number
}

// Reloads a tab's data in place, without its loading screen, when the registry has updated the record.
export function useReloadOn(dataVersion: number, reload: () => unknown) {
  const seen = useRef(dataVersion)
  useEffect(() => {
    if (dataVersion === seen.current) return
    seen.current = dataVersion
    reload()
  }, [dataVersion, reload])
}

export const SEVERITY_PILL: Record<string, string> = {
  LOW: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  MEDIUM: 'bg-amber-50 text-amber-700 ring-amber-200',
  HIGH: 'bg-orange-50 text-orange-700 ring-orange-200',
  CRITICAL: 'bg-rose-50 text-rose-700 ring-rose-200',
}

export const CATEGORY_LABELS: Record<string, string> = {
  SECURITY: 'Security',
  DATA_PRIVACY: 'Data Privacy',
  OPERATIONAL: 'Operational',
  FINANCIAL: 'Financial',
  COMPLIANCE: 'Compliance',
  REPUTATIONAL: 'Reputational',
}

export const CATEGORY_COLORS: Record<string, string> = {
  SECURITY: '#e11d48',
  DATA_PRIVACY: '#8b5cf6',
  OPERATIONAL: '#f59e0b',
  FINANCIAL: '#3DDBD9',
  COMPLIANCE: '#6366f1',
  REPUTATIONAL: '#f472b6',
}

export const SEVERITIES = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

export const STAGE_PILL: Record<string, string> = {
  Ideation: 'status-pending',
  Development: 'status-active',
  Testing: 'status-review',
  Production: 'status-complete',
  Deprecated: 'status-failed',
}

export const SOURCE_BADGE: Record<string, { label: string; className: string }> = {
  phoenix: { label: 'Phoenix traces', className: 'bg-teal-50 text-teal-700 ring-teal-200' },
  metered: { label: 'Metered (Azure)', className: 'bg-sky-50 text-sky-700 ring-sky-200' },
  declared: { label: 'Declared by owner', className: 'bg-indigo-50 text-indigo-700 ring-indigo-200' },
  estimate: { label: 'Estimate', className: 'bg-amber-50 text-amber-700 ring-amber-200' },
  seed: { label: 'Demo data', className: 'bg-gray-100 text-slate-700 ring-gray-300' },
  none: { label: 'No data', className: 'bg-gray-50 text-slate-500 ring-gray-200' },
}

export function SourceBadge({ source }: { source: string }) {
  const b = SOURCE_BADGE[source] || SOURCE_BADGE.none
  return <span className={`text-[12px] px-1.5 py-0.5 rounded-full ring-1 whitespace-nowrap ${b.className}`}>{b.label}</span>
}

export function fmtCents(c: number | null | undefined): string {
  if (c == null) return '—'
  const n = c / 100
  if (Math.abs(n) >= 1000) return '$' + (n / 1000).toFixed(1) + 'K'
  if (Math.abs(n) > 0 && Math.abs(n) < 0.01) return '<$0.01'
  return '$' + n.toFixed(2)
}

export function fmtDollars(n: number | null | undefined): string {
  if (n == null) return '—'
  if (Math.abs(n) >= 1000) return '$' + (n / 1000).toFixed(1) + 'K'
  return '$' + n.toFixed(2)
}

// Whole-dollar business value, as the AIRegistry prototype shows it: $950, $42K, $1.78M.
export function fmtMoney(n: number): string {
  if (Math.abs(n) >= 1000000) return '$' + (n / 1000000).toFixed(2) + 'M'
  if (Math.abs(n) >= 1000) return '$' + Math.round(n / 1000) + 'K'
  return '$' + Math.round(n)
}

// One colour per AI application type (the prototype's palette).
export const TYPE_COLORS: Record<string, string> = {
  'Autonomous Agent': '#3DDBD9',
  'Copilot / Assistant': '#8C7CF0',
  'Predictive / ML Model': '#F0A85A',
  'Generative AI Feature': '#F2A6D8',
  'Conversational AI / Chatbot': '#6EA8FE',
  'Computer Vision Model': '#57C785',
}

export function TypeBadge({ type }: { type?: string | null }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-2 py-0.5 text-xs text-slate-700 whitespace-nowrap">
      <span className="h-2 w-2 rounded-sm shrink-0" style={{ background: (type && TYPE_COLORS[type]) || '#8C9AAB' }} />
      {type || 'Uncategorized'}
    </span>
  )
}

export function fmtNumber(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString()
}

export function MiniStat({ label, value, accent, hint, tip }: { label: string; value: string; accent?: string; hint?: string; tip?: GlossaryKey }) {
  return (
    <div className="text-center rounded-xl bg-white py-2.5 px-2 ring-1 ring-slate-200/80 shadow-sm" title={hint}>
      <div className={`text-base font-extrabold leading-tight ${accent || 'text-slate-900'}`}>{value}</div>
      <div className="mt-0.5 text-[11.5px] font-semibold uppercase tracking-[.04em] text-slate-600">{label}{tip && <> <InfoTip term={tip} /></>}</div>
    </div>
  )
}

export function Loading({ text }: { text: string }) {
  return <div className="py-10 text-center text-sm text-slate-500">{text}</div>
}

export function errorMessage(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d: any) => d.msg || String(d)).join('; ')
  if (detail?.message) return detail.message
  return e?.message || fallback
}

// Cost per call is usually a fraction of a cent, so it keeps three significant figures.
export function fmtCostPerCall(cents: number | null | undefined): string {
  if (cents == null) return '—'
  const n = cents / 100
  if (n === 0) return '$0.00'
  if (Math.abs(n) >= 1) return '$' + n.toFixed(2)
  return '$' + Number(n.toPrecision(3)).toString()
}

// The label of one field inside a card (Owner, Evidence, …): small and quiet,
// so the value under it carries the weight, unlike a SectionLabel.
export function FieldLabel({ children, tip }: { children: React.ReactNode; tip?: GlossaryKey }) {
  return <span className="text-[12px] font-semibold uppercase tracking-[.04em] text-slate-600">{children}{tip && <> <InfoTip term={tip} /></>}</span>
}

// A section heading inside a tab: dark and bold with the brand accent bar,
// so each block of a tab reads as its own titled section.
export function SectionLabel({ children, tip }: { children: React.ReactNode; tip?: GlossaryKey }) {
  return (
    <span className="inline-flex items-center gap-2 text-[13px] font-bold text-slate-800">
      <span className="h-3.5 w-1 shrink-0 rounded-full bg-gradient-to-b from-zen-400 to-zen-700" aria-hidden />
      {children}
      {tip && <InfoTip term={tip} />}
    </span>
  )
}
