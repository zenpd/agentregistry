import { useState } from 'react'
import { getPhoenixProjects } from '../services/api'
import { errorMessage } from '../pages/agent/shared'

// Shared by the onboarding form and the "link an existing agent" control in
// the agent page's Diagram tab — a text input backed by a <datalist> of REAL
// Phoenix project names (discovered live, not typed blind), with manual entry
// still allowed since a not-yet-instrumented app has no project to discover yet.
export default function PhoenixProjectPicker({ value, onChange, id }: { value: string; onChange: (v: string) => void; id: string }) {
  const [projects, setProjects] = useState<string[] | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function discover() {
    setLoading(true)
    setFailure(null)
    try {
      const resp = await getPhoenixProjects()
      setProjects(resp.data.projects)
      // Phoenix itself is down or misconfigured; the server says why.
      setFailure(resp.data.reachable ? null
        : `Could not reach Phoenix${resp.data.reason ? `: ${resp.data.reason}` : ''}. Enter the project name manually if you know it.`)
    } catch (e: any) {
      setProjects([])
      // The registry's own API failed, which is a different problem: the
      // backend may be restarting, or the call was rejected.
      setFailure(e?.response
        ? `The registry API returned ${e.response.status}: ${errorMessage(e, 'request failed')}. Try Discover again.`
        : 'Could not reach the registry API — check that the backend is running, then try Discover again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div className="flex gap-2">
        <input
          className="input"
          list={id}
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder="e.g. retail-onboarding"
        />
        <button type="button" onClick={discover} disabled={loading} className="btn-secondary btn-sm whitespace-nowrap">
          {loading ? 'Looking…' : '🔍 Discover'}
        </button>
      </div>
      {projects !== null && (
        <datalist id={id}>
          {projects.map(p => <option key={p} value={p} />)}
        </datalist>
      )}
      {failure && <p className="text-xs text-rose-600 mt-1" data-testid="phoenix-failure">{failure}</p>}
      {projects !== null && !failure && projects.length === 0 && (
        <p className="text-xs text-gray-400 mt-1">Phoenix has no projects yet.</p>
      )}
      {projects !== null && !failure && projects.length > 0 && (
        <p className="text-xs text-gray-400 mt-1">{projects.length} project(s) found — pick from the list or type your own.</p>
      )}
    </div>
  )
}
