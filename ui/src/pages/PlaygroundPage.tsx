import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { getAgents, type RegistryAgent } from '../services/api'
import { getIntegration, type Integration } from '../services/ops/integrate'
import TryItPanel from '../components/TryItPanel'
import { ReuseBanner } from './agent/IntegrateTab'
import { errorMessage } from './agent/shared'

export default function PlaygroundPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const selected = searchParams.get('agent') || ''
  const [agents, setAgents] = useState<RegistryAgent[]>([])
  const [integration, setIntegration] = useState<Integration | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getAgents(1, 100)
      .then(r => setAgents([...r.data.data].sort((a, b) => a.name.localeCompare(b.name))))
      .catch(e => setError(errorMessage(e, 'Could not load the registry')))
  }, [])

  useEffect(() => {
    setIntegration(null)
    if (!selected) return
    let cancelled = false
    getIntegration(selected)
      .then(r => { if (!cancelled) { setIntegration(r.data); setError(null) } })
      .catch(e => { if (!cancelled) setError(errorMessage(e, 'Could not load the agent')) })
    return () => { cancelled = true }
  }, [selected])

  const agent = agents.find(a => a.id === selected)

  return (
    <div className="max-w-3xl mx-auto space-y-4 animate-fade-in">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Agent Playground</h2>
        <p className="text-gray-500 mt-1">Call any registered agent with your own input before you ask for access.</p>
      </div>

      <div className="card p-4 space-y-4">
        <select
          className="input"
          value={selected}
          onChange={e => setSearchParams(e.target.value ? { agent: e.target.value } : {}, { replace: true })}
          aria-label="Agent"
        >
          <option value="">Choose an agent…</option>
          {agents.map(a => (
            <option key={a.id} value={a.id}>{a.name} · {a.stage}{a.reuse.certified ? ' · certified' : ''}</option>
          ))}
        </select>

        {error && <div className="rounded-xl bg-rose-50 border border-rose-200 px-3 py-2 text-sm text-rose-700">{error}</div>}

        {selected && integration && (
          <>
            <ReuseBanner reuse={integration.reuse} />
            <TryItPanel agentId={selected} tryIt={integration.tryIt} />
            <div className="text-xs text-gray-500">
              Contract, access requests and consumers are on the agent’s{' '}
              <Link to={`/agents/${selected}?tab=integrate`} className="text-teal-700 hover:underline">
                Integrate tab{agent ? ` (${agent.name})` : ''}
              </Link>.
            </div>
          </>
        )}
        {!selected && <p className="text-sm text-gray-400">Pick an agent to see how to call it.</p>}
      </div>
    </div>
  )
}
