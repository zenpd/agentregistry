import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { getAgents, type RegistryAgent } from '../services/api'
import { STAGE_PILL, errorMessage, fmtMoney } from './agent/shared'

const UNASSIGNED = '__none__'
const PAGE = 100
// A full-time month: 40 h x 52 weeks / 12.
const FTE_HOURS_PER_MONTH = 173

// Every registered agent, across as many pages as the registry has; the
// totals here are only right if nothing is left out.
async function loadAllAgents(): Promise<RegistryAgent[]> {
  const first = (await getAgents(1, PAGE)).data
  const rest = await Promise.all(
    Array.from({ length: Math.max(0, first.pagination.pages - 1) }, (_, i) => getAgents(i + 2, PAGE)),
  )
  return [...first.data, ...rest.flatMap(r => r.data.data)]
}

const deptKey = (a: RegistryAgent) => a.dept || UNASSIGNED
const deptLabel = (a: RegistryAgent) => a.deptName || a.dept || 'Unassigned'

// Business Impact: what each business unit is running and what it produces.
// The unit filter lives in the URL (?dept=...), so a BU owner can bookmark
// their own team's view.
export default function BusinessView() {
  const [searchParams, setSearchParams] = useSearchParams()
  const dept = searchParams.get('dept') || ''
  const [agents, setAgents] = useState<RegistryAgent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadAllAgents()
      .then(list => { setAgents(list); setError(null) })
      .catch(e => setError(errorMessage(e, 'Could not load the registry')))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-8 text-center text-gray-500">Loading…</div>
  if (error) return <div className="p-8 text-center text-rose-500">Error: {error}</div>

  const units = [...agents.reduce((m, a) => {
    const u = m.get(deptKey(a)) || { key: deptKey(a), label: deptLabel(a), count: 0 }
    u.count += 1
    return m.set(u.key, u)
  }, new Map<string, { key: string; label: string; count: number }>()).values()]
    .sort((a, b) => (a.key === UNASSIGNED ? 1 : b.key === UNASSIGNED ? -1 : a.label.localeCompare(b.label)))
  const unit = units.find(u => u.key === dept)
  const list = unit ? agents.filter(a => deptKey(a) === unit.key) : agents

  // Retired agents stay in the table but produce nothing now.
  const running = list.filter(a => a.stage !== 'Deprecated')
  const live = running.filter(a => a.stage === 'Production')
  const realized = live.reduce((s, a) => s + (a.valueAmount || 0), 0)
  const projected = running.filter(a => a.stage !== 'Production').reduce((s, a) => s + (a.valueAmount || 0), 0)
  const hours = live.reduce((s, a) => s + (a.hoursSavedMonthly || 0), 0)
  const pipelineHours = running.filter(a => a.stage !== 'Production').reduce((s, a) => s + (a.hoursSavedMonthly || 0), 0)

  const select = (key: string) => setSearchParams(key ? { dept: key } : {}, { replace: true })
  const chip = (active: boolean) => `text-xs px-3 py-1 rounded-full border transition-colors ${
    active ? 'bg-teal-600 text-white border-teal-600' : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300 hover:text-gray-800'
  }`

  return (
    <div className="space-y-5 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold gradient-text">Business Impact</h1>
        <p className="text-gray-500 mt-0.5">What each business unit is running, and the outcomes it’s producing. Filter to your team.</p>
      </div>

      <div className="flex gap-2 flex-wrap" role="group" aria-label="Business unit" data-testid="bu-chips">
        <button type="button" onClick={() => select('')} aria-pressed={!unit} className={chip(!unit)}>
          All business units <span className="opacity-70">{agents.length}</span>
        </button>
        {units.map(u => (
          <button key={u.key} type="button" onClick={() => select(u.key)} aria-pressed={unit?.key === u.key} className={chip(unit?.key === u.key)}>
            {u.label} <span className="opacity-70">{u.count}</span>
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4" data-testid="bu-kpis">
        <Kpi label="Agents running" value={running.length.toLocaleString()} sub={`${live.length} live in production`} />
        <Kpi
          label="Value / month"
          value={fmtMoney(realized + projected)}
          sub={`${fmtMoney(realized)} realized in production · ${fmtMoney(projected)} projected`}
          accent="text-teal-600"
        />
        <Kpi
          label="Hours saved / month"
          value={hours.toLocaleString()}
          sub={`≈ ${Math.round(hours / FTE_HOURS_PER_MONTH)} FTE from production agents${pipelineHours ? ` · +${pipelineHours.toLocaleString()} projected` : ''}`}
        />
      </div>

      <div className="card p-5">
        <h2 className="font-semibold text-gray-900 mb-3">
          Agents in {unit ? unit.label : 'every business unit'}
          <span className="ml-2 text-xs font-normal text-gray-400">highest value first</span>
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="bu-table">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-gray-400 border-b border-gray-100">
                <th className="py-2 pr-3 font-medium">Initiative</th>
                <th className="py-2 pr-3 font-medium">AI type</th>
                <th className="py-2 pr-3 font-medium">Owner</th>
                <th className="py-2 pr-3 font-medium">Stage</th>
                <th className="py-2 pr-3 font-medium">Business outcome</th>
                <th className="py-2 pr-3 font-medium text-right">Value / mo</th>
                <th className="py-2 font-medium text-right">Hours / mo</th>
              </tr>
            </thead>
            <tbody>
              {list.map(a => (
                <tr key={a.id} className="border-b border-gray-50 last:border-0 align-top">
                  <td className="py-2.5 pr-3">
                    <Link to={`/agents/${a.id}`} className="font-medium text-gray-900 hover:text-teal-700">{a.name}</Link>
                    {!unit && <div className="text-xs text-gray-400">{deptLabel(a)}</div>}
                  </td>
                  <td className="py-2.5 pr-3 text-xs text-gray-600">{a.aiType}</td>
                  <td className="py-2.5 pr-3 text-xs text-gray-600">{a.owner || '—'}</td>
                  <td className="py-2.5 pr-3"><span className={STAGE_PILL[a.stage] || 'status-pending'}>{a.stage}</span></td>
                  <td className="py-2.5 pr-3 text-xs text-gray-600 max-w-[280px]">{a.businessOutcome || <span className="text-gray-400">Not stated</span>}</td>
                  <td className="py-2.5 pr-3 text-right">
                    <div className="font-mono text-gray-900">{a.valueAmount ? fmtMoney(a.valueAmount) : '—'}</div>
                    {a.valueType && a.valueAmount > 0 && <div className="text-[11px] text-gray-400">{a.valueType}</div>}
                  </td>
                  <td className="py-2.5 text-right font-mono text-gray-700">{a.hoursSavedMonthly ? a.hoursSavedMonthly.toLocaleString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {list.length === 0 && <p className="py-6 text-center text-sm text-gray-400">No agents registered for this unit yet.</p>}
        </div>
      </div>
    </div>
  )
}

function Kpi({ label, value, sub, accent }: { label: string; value: string; sub: string; accent?: string }) {
  return (
    <div className="card p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wide">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${accent || 'text-gray-900'}`}>{value}</div>
      <div className="text-xs text-gray-400 mt-1">{sub}</div>
    </div>
  )
}
