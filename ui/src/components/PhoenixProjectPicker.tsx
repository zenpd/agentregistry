import { useState } from 'react'
import { getPhoenixProjects } from '../services/api'

// Shared by the onboarding form and the "link an existing agent" control in
// the agent page's Diagram tab — a text input backed by a <datalist> of REAL
// Phoenix project names (discovered live, not typed blind), with manual entry
// still allowed since a not-yet-instrumented app has no project to discover yet.
export default function PhoenixProjectPicker({ value, onChange, id }: { value: string; onChange: (v: string) => void; id: string }) {
  const [projects, setProjects] = useState<string[] | null>(null)
  const [reachable, setReachable] = useState(true)
  const [loading, setLoading] = useState(false)

  async function discover() {
    setLoading(true)
    try {
      const resp = await getPhoenixProjects()
      setReachable(resp.data.reachable)
      setProjects(resp.data.projects)
    } catch {
      setReachable(false)
      setProjects([])
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
      {projects !== null && !reachable && (
        <p className="text-xs text-rose-600 mt-1">Could not reach Phoenix — enter the project name manually if you know it.</p>
      )}
      {projects !== null && reachable && projects.length === 0 && (
        <p className="text-xs text-gray-400 mt-1">Phoenix has no projects yet.</p>
      )}
      {projects !== null && reachable && projects.length > 0 && (
        <p className="text-xs text-gray-400 mt-1">{projects.length} project(s) found — pick from the list or type your own.</p>
      )}
    </div>
  )
}
