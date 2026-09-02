import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Sparkles, Settings } from 'lucide-react'
import type { ReactNode } from 'react'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
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
          <span className="font-bold text-gray-900">__APP_TITLE__</span>
        </div>
        <nav className="flex-1 p-3 space-y-1">
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
          <h1 className="text-sm font-semibold text-gray-700">__APP_TITLE__</h1>
        </header>
        <main className="p-6">{children}</main>
      </div>
    </div>
  )
}
