import { NavLink } from 'react-router-dom'
import { Sparkles, Settings, Bot, ShieldCheck, LayoutGrid, Cpu, GitBranch } from 'lucide-react'
import type { ReactNode } from 'react'

// Trimmed to what's still distinct now that agent-level detail (diagram,
// governance, risk, economics) lives on each agent's own page: Business,
// Tokenomics, Security and Dashboard were folded into the Executive
// dashboard's KPIs / revenue-vs-expenditure / risk pie+heatmap sections.
const NAV = [
  { to: '/', label: 'Executive', icon: LayoutGrid },
  { to: '/agents', label: 'AI Registry', icon: Bot },
  { to: '/governance', label: 'Governance', icon: ShieldCheck },
  { to: '/platform', label: 'Platform', icon: Cpu },
  { to: '/dependencies', label: 'Dependencies', icon: GitBranch },
  { to: '/playground', label: 'Playground', icon: Sparkles },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export default function AppShell({ children }: { children: ReactNode }) {
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
            </NavLink>
          ))}
        </nav>
        <div className="p-4 text-xs text-gray-400">Powered by ZenLabs Agent Foundry</div>
      </aside>

      {/* Main */}
      <div className="pl-[240px]">
        <header className="h-[60px] bg-white shadow-header flex items-center px-6">
          <h1 className="text-sm font-semibold text-gray-700">Enterprise AI Control Tower</h1>
        </header>
        <main className="p-6">{children}</main>
      </div>
    </div>
  )
}
