import { useEffect, useState } from 'react'
import { Activity, CheckCircle2, AlertCircle } from 'lucide-react'
import { checkHealth, getAgents, getGovernanceOverview } from '../services/api'

export default function DashboardPage() {
  const [health, setHealth] = useState<'checking' | 'ok' | 'down'>('checking')
  const [agentCount, setAgentCount] = useState(0)
  const [reviewCount, setReviewCount] = useState(0)

  useEffect(() => {
    checkHealth().then(() => setHealth('ok')).catch(() => setHealth('down'))
    getAgents(1, 100).then(r => setAgentCount(r.data.pagination.total)).catch(() => {})
    getGovernanceOverview().then(r => {
      let total = 0
      for (const group of Object.values(r)) {
        if (group && typeof group === 'object') {
          for (const count of Object.values(group as Record<string, unknown>)) {
            total += Number(count) || 0
          }
        }
      }
      setReviewCount(total)
    }).catch(() => {})
  }, [])

  const stats = [
    { label: 'API Status', value: health === 'ok' ? 'Healthy' : health === 'down' ? 'Unreachable' : '…', icon: health === 'ok' ? CheckCircle2 : AlertCircle },
    { label: 'Agents Registered', value: String(agentCount), icon: Activity },
    { label: 'Governance Reviews', value: String(reviewCount), icon: Activity },
  ]

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Welcome to Agent Registry</h2>
        <p className="text-gray-500 mt-1">
          Your AI portfolio is live. Navigate the sidebar to explore agents, governance, tokenomics, and more.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {stats.map(({ label, value, icon: Icon }) => (
          <div key={label} className="card p-5">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-gray-500">{label}</span>
              <Icon size={18} className="text-zen-500" />
            </div>
            <div className="text-2xl font-bold text-gray-900 mt-2">{value}</div>
          </div>
        ))}
      </div>

      <div className="card p-6">
        <h3 className="font-semibold text-gray-900 mb-2">Quick Links</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
          {[
            { label: 'AI Registry', to: '/agents' },
            { label: 'Governance', to: '/governance' },
            { label: 'Business Impact', to: '/business' },
            { label: 'Tokenomics', to: '/tokenomics' },
            { label: 'Platform & Dependencies', to: '/platform' },
            { label: 'Security & Compliance', to: '/security' },
            { label: 'Agent Playground', to: '/playground' },
            { label: 'Settings', to: '/settings' },
          ].map(l => (
            <a key={l.to} href={l.to} className="text-sm text-teal-600 hover:text-teal-700 border border-gray-200 rounded px-3 py-2 hover:bg-gray-50">
              → {l.label}
            </a>
          ))}
        </div>
      </div>
    </div>
  )
}
