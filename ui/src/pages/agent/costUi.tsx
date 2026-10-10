import InfoTip from '../../components/InfoTip'
import type { GlossaryKey } from '../../lib/glossary'
import { fmtCents } from './shared'

// Figures and small pieces shared by the Business Value tab and the cost panels of the Tokenomics tab.

// Validated categorical slots 1-2 (blue, orange); value is neutral ink, not a series hue.
export const SERIES = { token: '#2a78d6', infra: '#eb6834', value: '#374151' }


export const RUN_STATUS_TEXT: Record<string, string> = {
  ok: 'Collected',
  partial: 'Collected — some cost could not be allocated to an agent',
  not_configured: 'Not configured',
  forbidden: 'Azure refused access (check the service principal and its Cost Management Reader role)',
  throttled: 'Azure throttled the request — try again later',
  unreachable: 'Azure could not be reached',
  error: 'Failed',
  skipped: 'Skipped',
  running: 'Running',
}


// ── Formatting ───────────────────────────────────────────────────────────────

export function errorMessage(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d: any) => String(d.msg || d).replace(/^Value error, /, '')).join('; ')
  return e?.message || fallback
}

// Token costs are often fractions of a cent, so small amounts keep 3 significant digits.
export function fmtCost(cents: number | null | undefined): string {
  if (cents == null) return '—'
  const n = cents / 100
  const abs = Math.abs(n)
  if (abs === 0) return '$0.00'
  if (abs >= 1) return fmtCents(cents)
  if (abs < 0.0001) return '<$0.0001'
  return '$' + Number(n.toPrecision(3)).toString()
}

// Past 1,000% a percentage stops reading as a number; the multiple says the
// same thing plainly (value is N times what it costs to run).
export function fmtRoi(pct: number): string {
  return Math.abs(pct) >= 1000 ? `${Math.round(pct / 100 + 1).toLocaleString()}× cost` : `${pct.toLocaleString()}%`
}

// A real but tiny share must not read as zero. The API rounds to one
// decimal, so a nonzero cost can arrive as 0.
export function fmtSmallPct(pct: number, hasCost: boolean): string {
  return hasCost && pct < 0.1 ? '<0.1%' : `${pct.toLocaleString()}%`
}

export function fmtSigned(cents: number): string {
  return (cents < 0 ? '−' : '+') + fmtCents(Math.abs(cents))
}

export function fmtMonth(month: string): string {
  const [y, m] = month.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })
}

export function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

export function Banner({ tone, children }: { tone: 'teal' | 'amber' | 'rose' | 'gray'; children: React.ReactNode }) {
  const style = {
    teal: 'bg-teal-50 text-teal-800 border-teal-100',
    amber: 'bg-amber-50 text-amber-800 border-amber-100',
    rose: 'bg-rose-50 text-rose-700 border-rose-100',
    gray: 'bg-gray-50 text-slate-700 border-gray-100',
  }[tone]
  return <div className={`rounded-lg border px-3 py-2 text-xs ${style}`}>{children}</div>
}

const TILE_TIPS: Record<string, GlossaryKey> = {
  'Token cost': 'tokens',
  'Declared value': 'declared_value',
  'Total cost': 'cost_to_run',
  'ROI': 'return_on_cost',
}

export function Tile({ label, value, sub, accent, muted }: {
  label: string
  value: React.ReactNode
  sub?: React.ReactNode
  accent?: string
  muted?: boolean
}) {
  return (
    <div className="rounded-xl bg-white px-3.5 py-2.5 min-w-0 ring-1 ring-slate-200/80 shadow-sm">
      <div className="text-[11.5px] font-semibold uppercase tracking-[.04em] text-slate-600">{label}{TILE_TIPS[label] && <> <InfoTip term={TILE_TIPS[label]} /></>}</div>
      <div className={`mt-1 ${muted ? 'text-sm font-medium text-slate-500' : `text-lg font-extrabold leading-tight ${accent || 'text-slate-900'}`}`}>{value}</div>
      {sub && <div className="text-[12.5px] text-slate-600 mt-1 flex flex-wrap items-center gap-1">{sub}</div>}
    </div>
  )
}

export function Swatch({ color }: { color: string }) {
  return <span className="inline-block h-2.5 w-2.5 rounded-sm shrink-0" style={{ background: color }} aria-hidden />
}


export function fmtDollarsExact(dollars: number): string {
  return fmtCents(Math.round(dollars * 100))
}

