import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Archive } from 'lucide-react'
import api from '../services/api'
import { errorMessage } from '../pages/agent/shared'

type Archived = { id: string; name: string; stage: string; isDemo: boolean; archivedAt: string; reason: string | null }

// Settings → Archived agents: agents left out of every page, count and job but kept
// with all their records. An agent is archived from its delete dialog on Agent Registry.
export default function ArchivedAgentsCard({ canEdit }: { canEdit: boolean }) {
  const [archived, setArchived] = useState<Archived[] | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const load = useCallback(() => {
    api.get<{ agents: Archived[] }>('/admin/archived-agents').then(r => setArchived(r.data.agents)).catch(() => setArchived([]))
  }, [])
  useEffect(() => { load() }, [load])

  async function bringBack(a: Archived) {
    try { await api.post(`/agents/${encodeURIComponent(a.id)}/unarchive`); setMsg(`${a.name} is back on every page.`); load() }
    catch (e) { setMsg(errorMessage(e, `${a.name} was not brought back`)) }
  }
  return (
    <div className="card p-6 space-y-3" data-testid="archived-agents">
      <div className="flex items-start gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-slate-100 text-slate-600"><Archive size={20} /></div>
        <div>
          <h3 className="text-[16px] font-extrabold text-slate-900">Archived agents{archived ? ` (${archived.length})` : ''}</h3>
          <p className="text-[13px] text-slate-600">Left out of every page, count and job, and kept with all their records. An agent is archived from its delete dialog on Agent Registry.</p>
        </div>
      </div>
      {archived && archived.length === 0 && <p className="text-[13px] text-slate-600">No agent is archived.</p>}
      {archived && archived.length > 0 && (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
          {archived.map(a => (
            <li key={a.id} className="flex flex-wrap items-center gap-2 px-3 py-1.5 text-[13px]">
              <Link to={`/agents/${a.id}`} className="font-medium text-zen-700 hover:underline">{a.name}</Link>
              <span className="text-slate-500">{a.stage}{a.isDemo ? ' · Demo' : ''}</span>
              <span className="flex-1 text-slate-600">{a.reason}</span>
              {canEdit && <button type="button" className="btn-secondary btn-sm" onClick={() => bringBack(a)}>Bring back</button>}
            </li>
          ))}
        </ul>
      )}
      {msg && <p className="text-[13px] text-slate-700" role="status">{msg}</p>}
    </div>
  )
}
