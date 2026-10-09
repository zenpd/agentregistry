import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { Settings, Bot, ShieldCheck, LayoutGrid, Cpu, GitBranch, Briefcase, Inbox, BookOpen, Workflow, Radar, MessageCircleQuestion, LogOut, ScrollText, HeartPulse, ClipboardCheck } from 'lucide-react'
import { can, useMe } from '../../lib/me'
import NotificationBell from '../NotificationBell'
import { getMe, logout } from '../../services/api'
import { APPROVALS_CHANGED, getApprovals } from '../../services/ops/approvals'
import { DISCOVERY_CHANGED, getPhoenixInbox } from '../../services/ops/discovery'

// Trimmed to what's still distinct now that agent-level detail (diagram,
// governance, risk, economics) lives on each agent's own page: Tokenomics,
// Security and Dashboard were folded into the Executive dashboard's KPIs /
// revenue-vs-expenditure / risk pie+heatmap sections. Business Impact stays
// its own page: it answers a BU owner's question (my unit's agents and
// outcomes), not the portfolio-wide one Executive answers.
const NAV = [
  { to: '/', label: 'Executive', icon: LayoutGrid },
  { to: '/agents', label: 'AI Registry', icon: Bot },
  { to: '/discovered', label: 'Discovered Agents', icon: Radar },
  { to: '/approvals', label: 'Integration Approval', icon: Inbox },
  { to: '/governance', label: 'Governance', icon: ShieldCheck },
  { to: '/compliance', label: 'Compliance', icon: ClipboardCheck },
  { to: '/business', label: 'Business Impact', icon: Briefcase },
  { to: '/programme', label: 'Programme Health', icon: HeartPulse },
  { to: '/platform', label: 'Platform', icon: Cpu },
  { to: '/dependencies', label: 'All Agents Graph', icon: GitBranch },
  { to: '/ask', label: 'Ask the Registry', icon: MessageCircleQuestion },
  { to: '/settings', label: 'Settings', icon: Settings },
]

// Explanations rather than daily work, kept apart at the bottom.
const REFERENCE = [
  { to: '/how-it-works', label: 'How It Works', icon: BookOpen },
  { to: '/pipelines', label: 'Pipelines', icon: Workflow },
  { to: '/audit', label: 'Audit Trail', icon: ScrollText, perm: 'audit' },
]

// How many decisions are waiting, for the Approvals badge. Refreshed on every
// page change and right after a decision is made on the Approvals page.
function usePendingApprovals(): number | null {
  const { pathname } = useLocation()
  const [count, setCount] = useState<number | null>(null)
  useEffect(() => {
    let live = true
    const load = () => getApprovals().then(r => { if (live) setCount(r.data.counts.total) }).catch(() => { if (live) setCount(null) })
    load()
    window.addEventListener(APPROVALS_CHANGED, load)
    return () => { live = false; window.removeEventListener(APPROVALS_CHANGED, load) }
  }, [pathname])
  return count
}

// How many Phoenix projects are waiting to be registered, for the Discovered badge.
function useNewDiscoveries(): number | null {
  const { pathname } = useLocation()
  const [count, setCount] = useState<number | null>(null)
  useEffect(() => {
    let live = true
    const load = () => getPhoenixInbox().then(r => { if (live) setCount(r.data.summary.new) }).catch(() => { if (live) setCount(null) })
    load()
    window.addEventListener(DISCOVERY_CHANGED, load)
    return () => { live = false; window.removeEventListener(DISCOVERY_CHANGED, load) }
  }, [pathname])
  return count
}

function UserChip() {
  const [me, setMe] = useState<{ name: string | null; email: string | null; accountRole: string | null } | null>(null)
  useEffect(() => { getMe().then(r => setMe(r.data)).catch(() => setMe(null)) }, [])
  function signOut() {
    logout()
    window.location.href = '/login'
  }
  return (
    <div className="flex items-center gap-2">
      {me && (
        <div className="text-right leading-tight" data-testid="user-chip">
          <div className="text-[13px] font-semibold text-slate-900">{me.name ?? me.email}</div>
          <div className="text-[11.5px] text-slate-600">{me.accountRole}</div>
        </div>
      )}
      <button type="button" onClick={signOut} data-testid="logout" title="Sign out"
        className="rounded-lg p-2 text-slate-600 hover:bg-gray-100 hover:text-slate-900"><LogOut size={17} /></button>
    </div>
  )
}

export default function AppShell({ children }: { children: ReactNode }) {
  const me = useMe()
  const pending = usePendingApprovals()
  const discovered = useNewDiscoveries()
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className="fixed inset-y-0 left-0 w-[240px] bg-white shadow-sidebar flex flex-col">
        <div className="h-[60px] flex items-center gap-2 px-5 border-b border-gray-100">
          <div className="w-8 h-8 rounded-lg bg-gradient-zen flex items-center justify-center text-white font-bold">
            Z
          </div>
          <span className="font-bold text-slate-900">Agent Registry</span>
        </div>
        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  isActive ? 'bg-zen-50 text-zen-700' : 'text-slate-700 hover:bg-gray-50'
                }`
              }
            >
              <Icon size={18} className="shrink-0" />
              <span className="whitespace-nowrap">{label}</span>
              {to === '/discovered' && discovered != null && discovered > 0 && (
                <span className="ml-auto rounded-full bg-zen-600 px-2 py-0.5 text-[12px] font-bold text-white" data-testid="discovered-badge"
                  title={`${discovered} not registered yet`}>{discovered}</span>
              )}
              {to === '/approvals' && pending != null && pending > 0 && (
                <span className="ml-auto shrink-0 rounded-full bg-zen-600 px-2 py-0.5 text-[12px] font-bold text-white" data-testid="approvals-badge"
                  title={`${pending} waiting for a decision`}>{pending}</span>
              )}
            </NavLink>
          ))}
          <div className="pt-4 pb-1 px-3 text-[11.5px] font-bold uppercase tracking-[.12em] text-slate-500">Reference</div>
          {REFERENCE.filter(r => !r.perm || can(me, r.perm)).map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  isActive ? 'bg-zen-50 text-zen-700' : 'text-slate-700 hover:bg-gray-50'
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="p-4 text-xs text-slate-500">Powered by ZenLabs Agent Foundry</div>
      </aside>

      {/* Main */}
      <div className="pl-[240px]">
        <header className="relative h-[60px] bg-white shadow-header flex items-center justify-between px-6">
          <div className="leading-tight">
            <div className="flex items-center gap-1.5 text-[11.5px] font-bold uppercase tracking-[.12em] text-zen-600">
              <span className="h-1.5 w-1.5 rounded-full bg-zen-500 animate-pulse-dot" aria-hidden />
              Enterprise AI Operations
            </div>
            <div className="text-[17px] font-extrabold gradient-text">AI Control Tower</div>
          </div>
          <div className="flex items-center gap-4">
            <span className="hidden xl:inline-flex items-center gap-1.5 rounded-full border border-zen-200 bg-zen-50 px-3 py-1 text-xs font-semibold text-zen-700">
              Agents · copilots · models · generative features
            </span>
            <NotificationBell />
            <UserChip />
          </div>
          {/* Thin brand line under the bar. */}
          <span className="absolute inset-x-0 bottom-0 h-[2px] bg-gradient-zen opacity-60" aria-hidden />
        </header>
        <main className="p-6">{children}</main>
      </div>
    </div>
  )
}
