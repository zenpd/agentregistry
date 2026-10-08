import { useCallback, useEffect, useState } from 'react'
import { Layers } from 'lucide-react'
import { getScope, includingDemo, setIncludingDemo } from '../services/api'

// Settings → Demo agents: whether this browser shows the seeded example agents on every page.
// Archived agents have their own card (ArchivedAgentsCard).
export default function DemoAgentsCard() {
  const [count, setCount] = useState<number | null>(null)
  const [enabled, setEnabled] = useState(true)
  const on = includingDemo()
  const load = useCallback(() => {
    getScope().then(r => { setCount(r.data.demoAgents); setEnabled(r.data.demoEnabled !== false) }).catch(() => setCount(null))
  }, [])
  useEffect(() => { load() }, [load])

  return (
    <div className="card p-6 space-y-3" data-testid="demo-agents">
      <div className="flex items-start gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-amber-50 text-amber-600"><Layers size={20} /></div>
        <div>
          <h3 className="text-[16px] font-extrabold text-slate-900">Demo agents</h3>
          <p className="text-[13px] text-slate-600" data-testid="demo-state">
            {enabled
              ? <>{count ?? '…'} seeded example agents, each labelled Demo on its card and page. They are {on ? 'shown' : 'hidden'} on every page in this browser.</>
              : <>The demo agents are turned off for this installation (DEMO_AGENTS_ENABLED=false in the backend environment). They are left out of every page and job, and kept in the database.</>}
          </p>
        </div>
      </div>
      {enabled && (
        <label className="flex items-center gap-2 text-[13px] text-slate-800">
          <input type="checkbox" checked={on} data-testid="demo-toggle"
            onChange={() => { setIncludingDemo(!on); window.location.reload() }} />
          Show the demo agents on every page
        </label>
      )}
    </div>
  )
}
