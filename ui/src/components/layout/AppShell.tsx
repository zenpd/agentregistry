import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { Sparkles, Settings, Bot, ShieldCheck, LayoutGrid, Cpu, GitBranch, Briefcase, Inbox } from 'lucide-react'
import { APPROVALS_CHANGED, getApprovals } from '../../services/ops/approvals'

// Trimmed to what's still distinct now that agent-level detail (diagram,
// governance, risk, economics) lives on each agent's own page: Tokenomics,
// Security and Dashboard were folded into the Executive dashboard's KPIs /
// revenue-vs-expenditure / risk pie+heatmap sections. Business Impact stays
// its own page: it answers a BU owner's question (my unit's agents and
// outcomes), not the portfolio-wide one Executive answers.
const NAV = [
  { to: '/', label: 'Executive', icon: LayoutGrid },
  { to: '/agents', label: 'AI Registry', icon: Bot },
  { to: '/approvals', label: 'Approvals', icon: Inbox },
  { to: '/governance', label: 'Governance', icon: ShieldCheck },
  { to: '/business', label: 'Business Impact', icon: Briefcase },
  { to: '/platform', label: 'Platform', icon: Cpu },
  { to: '/dependencies', label: 'Dependencies', icon: GitBranch },
  { to: '/playground', label: 'Playground', icon: Sparkles },
  { to: '/settings', label: 'Settings', icon: Settings },
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

export default function AppShell({ children }: { children: ReactNode }) {
  const pending = usePendingApprovals()
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className="fixed inset-y-0 left-0 w-[240px] bg-white shadow-sidebar flex flex-col">
        <div className="h-[60px] flex items-center gap-2 px-5 border-b border-gray-100">
          <div className="w-8 h-8 rounded-lg bg-gradient-zen flex items-center justify-center text-white font-bold">
            Z
          </div>
          <span className="font-bold text-gray-900">Agent Registry</span>
        </div>
        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  isActive ? 'bg-zen-50 text-zen-700' : 'text-gray-600 hover:bg-gray-50'
                }`
              }
            >
              <Icon size={18} />
              {label}
              {to === '/approvals' && pending != null && pending > 0 && (
                <span className="ml-auto rounded-full bg-zen-600 px-2 py-0.5 text-[11px] font-bold text-white" data-testid="approvals-badge"
                  title={`${pending} waiting for a decision`}>{pending}</span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="p-4 text-xs text-gray-400">Powered by ZenLabs Agent Foundry</div>
      </aside>

      {/* Main */}
      <div className="pl-[240px]">
        <header className="relative h-[60px] bg-white shadow-header flex items-center justify-between px-6">
          <div className="leading-tight">
            <div className="flex items-center gap-1.5 text-[10.5px] font-bold uppercase tracking-[.12em] text-zen-600">
              <span className="h-1.5 w-1.5 rounded-full bg-zen-500 animate-pulse-dot" aria-hidden />
              Enterprise AI Operations
            </div>
            <div className="text-[17px] font-extrabold gradient-text">AI Control Tower</div>
          </div>
          <span className="hidden md:inline-flex items-center gap-1.5 rounded-full border border-zen-200 bg-zen-50 px-3 py-1 text-xs font-semibold text-zen-700">
            Agents · copilots · models · generative features
          </span>
          {/* Thin brand line under the bar. */}
          <span className="absolute inset-x-0 bottom-0 h-[2px] bg-gradient-zen opacity-60" aria-hidden />
        </header>
        <main className="p-6">{children}</main>
      </div>
    </div>
  )
}
