import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { deleteAgent, type Agent } from '../services/api'
import { errorMessage } from '../pages/agent/shared'

// callers: names of other registered agents that call this one.
export default function DeleteAgentDialog({ agent, callers, onClose, onDeleted }: {
  agent: Agent; callers: string[]; onClose: () => void; onDeleted: () => void
}) {
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const consumers = agent.consumers?.length || 0
  // Anything live or depended on needs the name typed, not a single click.
  const mustType = agent.stage === 'Production' || consumers > 0 || callers.length > 0
  const confirmed = !mustType || typed.trim() === agent.name.trim()

  async function remove() {
    setBusy(true)
    setError(null)
    try {
      await deleteAgent(agent.id)
      onDeleted()
    } catch (e) {
      setError(errorMessage(e, 'Could not delete the agent'))
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div role="alertdialog" aria-modal="true" aria-labelledby="delete-agent-title"
        className="bg-white rounded-2xl border border-gray-100 shadow-card-hover max-w-lg w-full animate-slide-up p-6 space-y-4"
        onClick={e => e.stopPropagation()} data-testid="delete-agent-dialog">
        <div className="flex items-start gap-3">
          <AlertTriangle size={20} className="text-rose-600 mt-0.5 shrink-0" />
          <div>
            <h2 id="delete-agent-title" className="text-lg font-bold text-gray-900">Delete {agent.name}?</h2>
            <p className="text-sm text-gray-600 mt-1">
              This permanently removes the agent with its governance reviews, risk findings, cost and usage records,
              context versions and access requests. It cannot be undone. The audit log keeps a record that it was deleted.
            </p>
          </div>
        </div>

        {(agent.stage === 'Production' || consumers > 0 || callers.length > 0) && (
          <ul className="rounded-xl bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-900 list-disc pl-8 space-y-1">
            {agent.stage === 'Production' && (
              <li>It is in Production. To retire a live agent while keeping its history, move it to Deprecated on the Governance tab instead.</li>
            )}
            {consumers > 0 && (
              <li>{consumers === 1 ? '1 consumer depends' : `${consumers} consumers depend`} on it: {agent.consumers.join(', ')}.</li>
            )}
            {callers.length > 0 && (
              <li>
                Called by {callers.join(', ')}. Those agents will still list it, and the dependency graph will show it as unregistered.
              </li>
            )}
          </ul>
        )}

        {mustType && (
          <div>
            <label htmlFor="delete-confirm" className="block text-xs font-semibold uppercase text-gray-500 mb-1 tracking-wide">
              Type <span className="normal-case font-mono text-gray-800">{agent.name}</span> to confirm
            </label>
            <input id="delete-confirm" className="input" value={typed} onChange={e => setTyped(e.target.value)} autoFocus autoComplete="off" />
          </div>
        )}

        {error && <div className="rounded-xl bg-rose-50 border border-rose-200 px-3 py-2 text-xs text-rose-700">{error}</div>}

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="btn-secondary btn-sm">Cancel</button>
          <button type="button" onClick={remove} disabled={busy || !confirmed} className="btn-danger btn-sm">
            {busy ? 'Deleting…' : 'Delete agent'}
          </button>
        </div>
      </div>
    </div>
  )
}
