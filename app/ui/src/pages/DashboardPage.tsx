import { useEffect, useState } from 'react'
import { Activity, CheckCircle2, AlertCircle } from 'lucide-react'
import { checkHealth } from '../services/api'

export default function DashboardPage() {
  const [health, setHealth] = useState<'checking' | 'ok' | 'down'>('checking')

  useEffect(() => {
    checkHealth()
      .then(() => setHealth('ok'))
      .catch(() => setHealth('down'))
  }, [])

  const stats = [
    { label: 'API Status', value: health === 'ok' ? 'Healthy' : health === 'down' ? 'Unreachable' : '…', icon: health === 'ok' ? CheckCircle2 : AlertCircle },
    { label: 'Active Sessions', value: '0', icon: Activity },
    { label: 'Agents', value: '1', icon: Activity },
  ]

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Welcome to __APP_TITLE__</h2>
        <p className="text-gray-500 mt-1">
          Your accelerator app is running. Wire up agents, workflows, and pages from here.
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
        <h3 className="font-semibold text-gray-900 mb-2">Next steps</h3>
        <ol className="list-decimal list-inside text-sm text-gray-600 space-y-1">
          <li>Add a specialist node in <code className="font-mono text-zen-700">app/agents/nodes/</code> and register it in <code className="font-mono text-zen-700">graph.py</code>.</li>
          <li>Expose it via a router under <code className="font-mono text-zen-700">app/api/routers/</code>.</li>
          <li>Build screens under <code className="font-mono text-zen-700">app/ui/src/pages/</code>.</li>
          <li>Deploy with <code className="font-mono text-zen-700">infra/aca-setup.sh</code> or the Azure Pipelines.</li>
        </ol>
      </div>
    </div>
  )
}
