import type { Agent } from '../../services/api'

export interface TabProps {
  agent: Agent
  agentId: string
  onChanged: () => void
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
  seed: { label: 'Demo data', className: 'bg-gray-100 text-gray-600 ring-gray-300' },
  none: { label: 'No data', className: 'bg-gray-50 text-gray-400 ring-gray-200' },
}

export function SourceBadge({ source }: { source: string }) {
  const b = SOURCE_BADGE[source] || SOURCE_BADGE.none
  return <span className={`text-[10px] px-1.5 py-0.5 rounded-full ring-1 whitespace-nowrap ${b.className}`}>{b.label}</span>
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

export function fmtNumber(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString()
}

export function MiniStat({ label, value, accent, hint }: { label: string; value: string; accent?: string; hint?: string }) {
  return (
    <div className="text-center rounded-lg bg-gray-50 py-2 px-1" title={hint}>
      <div className={`text-sm font-bold ${accent || 'text-gray-900'}`}>{value}</div>
      <div className="text-[10px] text-gray-400 uppercase">{label}</div>
    </div>
  )
}

export function Loading({ text }: { text: string }) {
  return <div className="py-10 text-center text-sm text-gray-400">{text}</div>
}

export function SectionLabel({ children }: { children: React.ReactNode }) {
  return <span className="text-xs text-gray-400">{children}</span>
}
