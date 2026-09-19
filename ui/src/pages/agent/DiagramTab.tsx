import { useState, useEffect, useMemo, useCallback } from 'react'
import { Link } from 'react-router-dom'
import type { ReconstructedNode, ReconstructedEdge } from '../../services/api'
import {
  getDiagramGraph, getDependencies, adoptDependencies, linkPhoenixProject, ADOPT_TARGET,
  type DiagramGraph, type DependenciesResponse, type DependencyComparison, type DeclaredDeps,
  type ObservedOnlyDep, type AdoptResponse, type BlastRadius, type UpstreamDep, type SharedResource,
} from '../../services/ops/diagram'
import { Loading, SectionLabel, SourceBadge, MiniStat, STAGE_PILL, fmtDollars, fmtNumber, type TabProps } from './shared'
import TraceNetworkGraph, { styleFor } from '../../components/TraceNetworkGraph'
import PhoenixProjectPicker from '../../components/PhoenixProjectPicker'

// Sample-quality and error-colour thresholds from the diagram research: a
// node is only coloured once it has enough calls for its error rate to mean something.
const PARTIAL_ORPHAN_RATE = 0.05
const ERROR_MIN_CALLS = 20
const ERROR_AMBER_RATE = 0.02
const ERROR_RED_RATE = 0.1
// Framework graph nodes (LangGraph steps) show up as agents; beyond a handful they drown the table.
const AGENT_STEPS_SHOWN = 5
// The circular layout stops being legible past ~30 nodes; the rest stay one click away.
const GRAPH_NODE_CAP = 30

const KIND_LABEL: Record<string, string> = {
  system: 'System', database: 'Database', knowledge_base: 'Knowledge base', mcp_server: 'MCP server',
  agent: 'Agent', model: 'Model', tool: 'Tool', retriever: 'Retriever', embedding: 'Embedding', guardrail: 'Guardrail',
  step: 'Workflow step',
}

const FIELD_LABEL: Record<string, string> = {
  enterprise_systems: 'Enterprise systems', databases: 'Databases', knowledge_bases: 'Knowledge bases',
  mcp_servers: 'MCP servers', calls: 'Calls (agents)', model_name: 'Model',
}

const NEUTRAL_CHIP = 'bg-gray-50 text-gray-600 ring-gray-200'

type Settled<T> = { data: T; error: null } | { data: null; error: string }

function errorText(e: any): string {
  return e?.response?.data?.detail || e?.message || 'Request failed'
}

async function settle<T>(p: Promise<{ data: T }>): Promise<Settled<T>> {
  try {
    return { data: (await p).data, error: null }
  } catch (e) {
    return { data: null, error: errorText(e) }
  }
}

function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function nodeTone(n: ReconstructedNode): string {
  if (n.count < ERROR_MIN_CALLS || n.errorCount === 0) return NEUTRAL_CHIP
  const rate = n.errorCount / n.count
  if (rate > ERROR_RED_RATE) return 'bg-rose-50 text-rose-700 ring-rose-200'
  if (rate > ERROR_AMBER_RATE) return 'bg-amber-50 text-amber-700 ring-amber-200'
  return NEUTRAL_CHIP
}

const obsKey = (o: ObservedOnlyDep) => `${o.kind}:${o.name}`

// Reconstructed from real Phoenix traces, set against what the owner
// declared. Four trace states are never collapsed into one generic "no data":
// not linked, Phoenix unreachable, linked but zero traces yet, and a real
// diagram. Declared dependencies and blast radius come from the registry and
// show in every state. Nothing here changes the agent without a person confirming.
export default function DiagramTab({ agent, agentId, onChanged }: TabProps) {
  const [graph, setGraph] = useState<Settled<DiagramGraph> | null>(null)
  const [deps, setDeps] = useState<Settled<DependenciesResponse> | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [linkValue, setLinkValue] = useState('')
  const [linking, setLinking] = useState(false)
  const [linkError, setLinkError] = useState<string | null>(null)

  const load = useCallback(async (refresh = false) => {
    setRefreshing(true)
    try {
      if (refresh) {
        // Sequential on purpose: the dependencies request then reads the sample the refresh just cached.
        const g = await settle(getDiagramGraph(agentId, true))
        const d = await settle(getDependencies(agentId))
        setDeps(d)
        setGraph(g)
      } else {
        const [g, d] = await Promise.all([settle(getDiagramGraph(agentId)), settle(getDependencies(agentId))])
        setGraph(g)
        setDeps(d)
      }
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [agentId])

  useEffect(() => { setLoading(true); load() }, [load])

  async function linkProject() {
    if (!linkValue.trim()) return
    setLinking(true)
    setLinkError(null)
    try {
      await linkPhoenixProject(agent.id, linkValue.trim())
      onChanged()
      await load()
    } catch (e) {
      setLinkError(errorText(e))
    } finally {
      setLinking(false)
    }
  }

  if (loading) return <Loading text="Reconstructing from traces…" />
  if (!graph || !deps) return null

  if (graph.error && deps.error) {
    return (
      <div className="py-6 text-center">
        <p className="text-sm text-rose-600">Couldn't load this agent's diagram.</p>
        <p className="text-xs text-gray-400 mt-1 break-all">{graph.error}</p>
        <button onClick={() => { setLoading(true); load() }} className="btn-secondary btn-sm mt-3">Retry</button>
      </div>
    )
  }

  const g = graph.data
  const d = deps.data
  const status = g?.status ?? d?.status
  const project = g?.project ?? d?.project ?? null

  return (
    <div className="space-y-5">
      <section>
        {status === 'not_linked' && (
          <div className="py-2">
            <p className="text-sm text-gray-500 mb-3">This agent isn't linked to a Phoenix project yet — no trace data. Link one to reconstruct its real dependency diagram from actual traces.</p>
            <div className="flex gap-2 items-start">
              <div className="flex-1">
                <PhoenixProjectPicker id="link-phoenix-projects" value={linkValue} onChange={setLinkValue} />
              </div>
              <button onClick={linkProject} disabled={linking || !linkValue.trim()} className="btn-primary btn-sm whitespace-nowrap">
                {linking ? 'Linking…' : 'Link'}
              </button>
            </div>
            {linkError && <p className="text-xs text-rose-600 mt-2">{linkError}</p>}
          </div>
        )}

        {status === 'phoenix_unreachable' && (
          <div className="py-4 text-center">
            <p className="text-sm text-gray-500">Linked to <span className="font-mono text-gray-700">{project}</span>, but Phoenix couldn't be reached.</p>
            {(g?.reason || d?.reason) && <p className="text-xs text-gray-400 mt-1 break-all">{g?.reason || d?.reason}</p>}
            <button onClick={() => load()} disabled={refreshing} className="btn-secondary btn-sm mt-3">{refreshing ? 'Retrying…' : 'Retry'}</button>
          </div>
        )}

        {status === 'no_traces_yet' && (
          <div className="py-4 text-center">
            <p className="text-sm text-gray-500">Linked to <span className="font-mono text-gray-700">{project}</span> — no traces seen yet.</p>
            {(g?.reason || d?.reason) && <p className="text-xs text-gray-400 mt-1">{g?.reason || d?.reason}.</p>}
            <p className="text-xs text-gray-400 mt-1">Once this app runs and exports real traces, its diagram reconstructs here. Checked {fmtWhen(g?.cachedAt ?? d?.cachedAt)}.</p>
            <button onClick={() => load(true)} disabled={refreshing} className="btn-secondary btn-sm mt-3">{refreshing ? 'Refreshing…' : 'Refresh'}</button>
          </div>
        )}

        {status === 'ok' && g && <TraceGraph graph={g} refreshing={refreshing} onRefresh={() => load(true)} />}
        {status === 'ok' && !g && <p className="text-xs text-rose-600">Trace graph failed to load: {graph.error}</p>}
      </section>

      {d ? (
        <>
          <DeclaredVsObserved deps={d} agentId={agentId} onAdopted={() => { onChanged(); load(true) }} />
          <BlastRadiusCard blast={d.blastRadius} upstream={d.upstream} shared={d.sharedResources} />
        </>
      ) : (
        <p className="text-xs text-rose-600">Dependencies failed to load: {deps.error}</p>
      )}

      <div className="text-right">
        <Link to="/dependencies" className="text-xs text-teal-600 hover:text-teal-700">Open full dependency graph →</Link>
      </div>
    </div>
  )
}

const SHAPE_GLYPH: Record<string, string> = { agent: '●', step: '⬭', tool: '▭', mcp_server: '▭', retriever: '⛁', guardrail: '▭' }

function TraceGraph({ graph, refreshing, onRefresh }: { graph: DiagramGraph; refreshing: boolean; onRefresh: () => void }) {
  const [showAll, setShowAll] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [hiddenKinds, setHiddenKinds] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')
  const [focusSignal, setFocusSignal] = useState<{ id: string; token: number } | null>(null)

  // Memoized on the underlying graph data (not on selection/hover state) so
  // TraceNetworkGraph's own dataset-build memo doesn't see a "new" nodes/edges
  // array on every click — that was rebuilding the vis-network instance from
  // scratch and restarting physics on every single selection, making the
  // whole layout visibly jump instead of just highlighting.
  const byCount = useMemo(() => [...graph.nodes].sort((a, b) => b.count - a.count), [graph.nodes])
  const drawn = useMemo(() => (showAll ? byCount : byCount.slice(0, GRAPH_NODE_CAP)), [byCount, showAll])
  // A supervisor dispatching to a step and getting control back is one
  // relationship, not two. The reconstruction reports both directions, which
  // drew every hub edge twice (an in-line and an out-line side by side); they
  // collapse here into a single line with an arrowhead at each end.
  const nwEdges = useMemo(() => {
    const drawnIds = new Set(drawn.map(n => n.id))
    const merged: (ReconstructedEdge & { bidirectional?: boolean })[] = []
    const seen = new Map<string, number>()
    for (const e of graph.edges) {
      if (!drawnIds.has(e.from) || !drawnIds.has(e.to)) continue
      const reverse = seen.get(`${e.to}|${e.from}|${e.kind}`)
      if (reverse !== undefined) {
        merged[reverse].bidirectional = true
        merged[reverse].count += e.count
        continue
      }
      const forward = `${e.from}|${e.to}|${e.kind}`
      if (seen.has(forward)) continue
      seen.set(forward, merged.length)
      merged.push({ ...e })
    }
    return merged
  }, [drawn, graph.edges])
  const nodeById = useMemo(() => new Map(drawn.map(n => [n.id, n])), [drawn])
  const orphanRate = graph.orphanRate ?? 0
  const selected = selectedId ? nodeById.get(selectedId) : null

  // Legend chips — one toggle per node kind, counted over what's actually drawn
  // (busiest-30 cap included), so a toggle's count always matches what it affects.
  const legend = useMemo(() => {
    const counts = new Map<string, number>()
    for (const n of drawn) counts.set(n.kind, (counts.get(n.kind) ?? 0) + 1)
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([kind, count]) => ({ kind, count, label: KIND_LABEL[kind] || kind, color: styleFor(kind).border }))
  }, [drawn])

  const callsCount = nwEdges.filter(e => e.kind !== 'sequence').length
  const sequenceCount = nwEdges.length - callsCount
  const errorCount = drawn.filter(n => n.errorCount > 0).length

  function searchFocus() {
    const q = search.trim().toLowerCase()
    if (!q) return
    const match = drawn.find(n => n.name.toLowerCase().includes(q))
    if (match) {
      setSelectedId(match.id)
      setFocusSignal({ id: match.id, token: Date.now() })
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between gap-3 mb-2">
        <p
          className="text-xs text-gray-500 truncate cursor-help"
          title={`${graph.truncated ? `Newest ${fmtNumber(graph.sampleLimit)} spans` : 'Full sample'}, window ${fmtWhen(graph.sampleWindow?.from)} → ${fmtWhen(graph.sampleWindow?.to)} · cached ${fmtWhen(graph.cachedAt)}${graph.fromCache ? ' (served from cache)' : ''}`}
        >
          Reconstructed from <b className="text-gray-700">{fmtNumber(graph.spanCount)}</b> span(s) across{' '}
          <b className="text-gray-700">{fmtNumber(graph.traceCount)}</b> trace(s) — project <span className="font-mono">{graph.project}</span>
          <span className="text-gray-400 ml-1" title="Hover for sample window and cache details">ⓘ</span>
        </p>
        <div className="flex items-center gap-2 flex-shrink-0">
          <SourceBadge source="phoenix" />
          <button onClick={onRefresh} disabled={refreshing} className="text-xs text-teal-600 hover:text-teal-700 disabled:opacity-50">
            {refreshing ? 'Refreshing…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      {orphanRate > PARTIAL_ORPHAN_RATE && (
        <p className="text-xs text-amber-700 bg-amber-50 ring-1 ring-amber-200 rounded-lg px-3 py-2 mb-2">
          Partial sample: {Math.round(orphanRate * 1000) / 10}% of spans have a parent outside the sample, so some calls between steps are missing.
        </p>
      )}

      <div className="grid grid-cols-4 gap-2 mb-2">
        {([
          ['Steps', drawn.length],
          ['Dependencies', nwEdges.length],
          ['Calls', callsCount],
          ['Errors', errorCount],
        ] as [string, number][]).map(([label, value]) => (
          <div key={label} className="rounded-lg border bg-white p-2 text-center">
            <div className="text-lg font-bold text-gray-800">{value}</div>
            <div className="text-[10px] uppercase text-gray-500">{label}</div>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-2">
        {legend.map(item => {
          const off = hiddenKinds.has(item.kind)
          return (
            <button
              key={item.kind}
              onClick={() => setHiddenKinds(prev => {
                const next = new Set(prev)
                if (next.has(item.kind)) next.delete(item.kind)
                else next.add(item.kind)
                return next
              })}
              title={`${item.count} node(s) — click to show/hide these and every edge touching them`}
              className={`rounded-full border px-3 py-1 text-xs font-medium transition-opacity ${off ? 'opacity-35' : ''}`}
              style={{ borderColor: item.color }}
            >
              <span className="mr-1.5 inline-block h-2.5 w-2.5 rounded-full border" style={{ background: item.color, borderColor: item.color }} />
              {item.label} ({item.count})
            </button>
          )
        })}
        {legend.length > 0 && (
          <>
            <button onClick={() => setHiddenKinds(new Set())} className="rounded-full border border-gray-200 px-3 py-1 text-xs text-gray-600 hover:bg-gray-50">
              Show all
            </button>
            <button onClick={() => setHiddenKinds(new Set(legend.map(i => i.kind)))} className="rounded-full border border-gray-200 px-3 py-1 text-xs text-gray-600 hover:bg-gray-50">
              Hide all
            </button>
          </>
        )}
        {byCount.length > GRAPH_NODE_CAP && (
          <button onClick={() => setShowAll(!showAll)} className="text-xs text-teal-600 hover:text-teal-700 px-1">
            {showAll ? `Show ${GRAPH_NODE_CAP} busiest only` : `+${byCount.length - GRAPH_NODE_CAP} quieter — show all`}
          </button>
        )}
        <div className="ml-auto flex items-center gap-2">
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') searchFocus() }}
            placeholder="Search & focus…"
            className="w-44 rounded-lg border px-3 py-1.5 text-xs"
          />
          <button onClick={searchFocus} className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50">
            Go
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="col-span-2 rounded-lg border bg-white overflow-hidden relative">
          <TraceNetworkGraph nodes={drawn} edges={nwEdges} hiddenKinds={hiddenKinds} height={540} selectedId={selectedId} onSelect={setSelectedId} focusSignal={focusSignal} />
          <p className="absolute bottom-1.5 right-2 text-[10px] text-gray-400">drag to move · scroll to zoom · click a node to trace its calls</p>
        </div>

        <div className="rounded-lg border border-gray-100 bg-white p-3 text-xs" style={{ maxHeight: 540, overflowY: 'auto' }}>
          {selected ? (
            <div className="space-y-3">
              <div>
                <h4 className="font-semibold text-gray-800">{selected.name}</h4>
                <span className={`inline-block mt-1 text-[11px] px-2 py-0.5 rounded-full ring-1 ${nodeTone(selected)}`}>
                  {SHAPE_GLYPH[selected.kind] || '●'} {KIND_LABEL[selected.kind] || selected.kind} · ×{fmtNumber(selected.count)}
                </span>
              </div>
              {selected.errorCount > 0 && (
                <p className="text-rose-600">{selected.errorCount} error(s) in this sample ({Math.round((selected.errorCount / selected.count) * 1000) / 10}%).</p>
              )}
              {selected.avgLatencyMs != null && <p className="text-gray-500">{Math.round(selected.avgLatencyMs)}ms avg latency</p>}
              <div>
                <h5 className="text-[10px] font-semibold uppercase text-gray-400">Calls / runs next</h5>
                <ul className="mt-1 space-y-1">
                  {nwEdges.filter(e => e.from === selected.id).map(e => (
                    <li key={`${e.to}-${e.kind}`} className="cursor-pointer text-teal-700 hover:underline" onClick={() => setSelectedId(e.to)}>
                      {e.kind === 'sequence' ? '⇢' : '→'} {nodeById.get(e.to)?.name ?? e.to}
                    </li>
                  ))}
                  {nwEdges.filter(e => e.from === selected.id).length === 0 && <li className="text-gray-400">none</li>}
                </ul>
              </div>
              <div>
                <h5 className="text-[10px] font-semibold uppercase text-gray-400">Called by</h5>
                <ul className="mt-1 space-y-1">
                  {nwEdges.filter(e => e.to === selected.id).map(e => (
                    <li key={`${e.from}-${e.kind}`} className="cursor-pointer text-emerald-700 hover:underline" onClick={() => setSelectedId(e.from)}>
                      ← {nodeById.get(e.from)?.name ?? e.from}
                    </li>
                  ))}
                  {nwEdges.filter(e => e.to === selected.id).length === 0 && <li className="text-gray-400">none</li>}
                </ul>
              </div>
              <button onClick={() => setSelectedId(null)} className="text-[11px] text-teal-700 hover:text-teal-800">clear selection</button>
            </div>
          ) : (
            <p className="text-gray-400">Click a step for details — its calls, callers and error rate. Hover any node for a quick tooltip.</p>
          )}
        </div>
      </div>

      <div className="mt-2 rounded-lg border bg-gray-50 p-3 text-[11px] leading-relaxed text-gray-600">
        <b>How to read this graph</b><br />
        ● solid blue circle = agent · ⬭ grey ellipse = workflow step (a framework graph node — a wait, an interrupt, a terminal state — not an agent) · ▭ amber box = tool · ▭ purple box = MCP server · ⛁ green cylinder = retriever · ▭ rose box = guardrail — busier steps are drawn larger, with bigger type<br />
        Amber/red border = error rate above {ERROR_AMBER_RATE * 100}%/{ERROR_RED_RATE * 100}% (at {ERROR_MIN_CALLS}+ calls only — thin sample sizes aren't coloured)<br />
        Lines take the colour of what they point at: violet to an agent · grey to a workflow step · amber to a tool · fuchsia to an MCP server · green to a retriever<br />
        Solid line = <b>calls</b> ({fmtNumber(callsCount)}), a real nested call · dashed = <b>sequence</b> ({fmtNumber(sequenceCount)}), ran next in the same trace with no nested call · an arrowhead at both ends means control went both ways (e.g. a supervisor dispatching and getting it back)<br />
        Drag nodes to rearrange · scroll to zoom · click a legend chip to show/hide that kind.
      </div>
    </div>
  )
}

function DeclaredList({ declared, upstream }: { declared: DeclaredDeps; upstream: UpstreamDep[] }) {
  const names = new Map(upstream.map(u => [u.id, u.name]))
  const groups: [string, string[]][] = [
    ['Enterprise systems', declared.enterpriseSystems],
    ['Databases', declared.databases],
    ['Knowledge bases', declared.knowledgeBases],
    ['MCP servers', declared.mcpServers],
    ['Calls (agents)', declared.calls.map(c => names.get(c) || c)],
    ['Consumers', declared.consumers],
    ['Model', declared.modelName ? [declared.modelName] : []],
  ]
  const filled = groups.filter(([, items]) => items.length > 0)
  if (filled.length === 0) return <p className="text-xs text-gray-400">Nothing declared for this agent yet.</p>
  return (
    <div className="grid grid-cols-2 gap-3">
      {filled.map(([label, items]) => (
        <div key={label}>
          <SectionLabel>{label}</SectionLabel>
          <div className="flex flex-wrap gap-1 mt-1">
            {items.map(item => (
              <span key={item} className={`text-xs px-2 py-0.5 rounded-full ring-1 ${NEUTRAL_CHIP}`}>{item}</span>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function DeclaredVsObserved({ deps, agentId, onAdopted }: { deps: DependenciesResponse; agentId: string; onAdopted: () => void }) {
  const note: Record<string, string> = {
    not_linked: 'No trace data — link a Phoenix project to compare these with what the agent actually calls.',
    phoenix_unreachable: 'Phoenix is unreachable, so these cannot be compared with observed calls right now.',
    no_traces_yet: 'No traces yet, so nothing has been observed to compare against.',
  }
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-800">Declared vs observed dependencies</h3>
        <div className="flex gap-1.5">
          <SourceBadge source="declared" />
          {deps.comparison && <SourceBadge source="phoenix" />}
        </div>
      </div>
      {deps.comparison ? (
        <ComparisonTable comparison={deps.comparison} traceCount={deps.traceCount} agentId={agentId} onAdopted={onAdopted} />
      ) : (
        <>
          <p className="text-xs text-gray-400 mb-3">{note[deps.status] || ''}</p>
          <DeclaredList declared={deps.declared} upstream={deps.upstream} />
        </>
      )}
    </div>
  )
}

function ComparisonTable({ comparison, traceCount, agentId, onAdopted }: {
  comparison: DependencyComparison; traceCount: number; agentId: string; onAdopted: () => void
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [confirming, setConfirming] = useState(false)
  const [adopting, setAdopting] = useState(false)
  const [result, setResult] = useState<AdoptResponse | null>(null)
  const [adoptError, setAdoptError] = useState<string | null>(null)
  const [showAllSteps, setShowAllSteps] = useState(false)

  const { confirmed, declared_only: declaredOnly, observed_only: observedOnly } = comparison
  const chosen = observedOnly.filter(o => selected.has(obsKey(o)))
  const agentSteps = observedOnly.filter(o => o.kind === 'agent')
  const hiddenSteps = showAllSteps ? 0 : Math.max(0, agentSteps.length - AGENT_STEPS_SHOWN)
  const observedRows = [
    ...observedOnly.filter(o => o.kind !== 'agent'),
    ...agentSteps.slice(0, agentSteps.length - hiddenSteps),
  ]

  function toggle(o: ObservedOnlyDep) {
    const next = new Set(selected)
    if (next.has(obsKey(o))) next.delete(obsKey(o))
    else next.add(obsKey(o))
    setSelected(next)
  }

  async function adopt() {
    setAdopting(true)
    setAdoptError(null)
    try {
      const res = await adoptDependencies(agentId, chosen.map(o => ({ name: o.name, kind: o.kind })))
      setResult(res.data)
      setSelected(new Set())
      setConfirming(false)
      onAdopted()
    } catch (e) {
      setAdoptError(errorText(e))
    } finally {
      setAdopting(false)
    }
  }

  if (!confirmed.length && !declaredOnly.length && !observedOnly.length) {
    return <p className="text-xs text-gray-400">Nothing declared and nothing recognisable observed in this sample.</p>
  }

  const th = 'py-1.5 pr-3 font-normal'
  const td = 'py-1.5 pr-3 align-top'
  const groupRow = (label: string, count: number, hint?: string) => (
    <tr className="border-t border-gray-100">
      <td colSpan={6} className="pt-3 pb-1 text-[11px] font-semibold text-gray-500 uppercase tracking-wide">
        {label} <span className="text-gray-400 font-normal normal-case">({count}){hint ? ` — ${hint}` : ''}</span>
      </td>
    </tr>
  )

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-gray-400">
              <th className={`${th} w-6`} />
              <th className={th}>Dependency</th>
              <th className={th}>Kind</th>
              <th className={th}>Declared as</th>
              <th className={th}>Seen in traces</th>
              <th className={th}>Calls</th>
            </tr>
          </thead>
          <tbody>
            {groupRow('Confirmed', confirmed.length)}
            {confirmed.map(c => (
              <tr key={`c:${c.declaredAs}:${c.name}`}>
                <td className={td}><span className="inline-block w-2 h-2 rounded-full bg-emerald-500" title="Declared and seen" /></td>
                <td className={`${td} text-gray-800`}>{c.name}</td>
                <td className={`${td} text-gray-500`}>{KIND_LABEL[c.kind] || c.kind}</td>
                <td className={`${td} text-gray-500`}>{FIELD_LABEL[c.declaredAs] || c.declaredAs}</td>
                <td className={`${td} font-mono text-gray-600`}>{c.observedName}</td>
                <td className={`${td} text-gray-600`}>×{fmtNumber(c.count)}</td>
              </tr>
            ))}

            {groupRow('Declared only', declaredOnly.length, comparison.absenceConclusive
              ? 'not seen in this sample'
              : `only ${fmtNumber(traceCount)} trace(s) sampled; absence isn't conclusive below ${comparison.minTracesForAbsence}`)}
            {declaredOnly.map(o => (
              <tr key={`d:${o.declaredAs}:${o.name}`}>
                <td className={td}><span className="inline-block w-2 h-2 rounded-full bg-amber-400" title="Declared, not seen" /></td>
                <td className={`${td} text-gray-800`}>{o.name}</td>
                <td className={`${td} text-gray-500`}>{KIND_LABEL[o.kind] || o.kind}</td>
                <td className={`${td} text-gray-500`}>{FIELD_LABEL[o.declaredAs] || o.declaredAs}</td>
                <td className={`${td} text-gray-400`}>not seen</td>
                <td className={`${td} text-gray-400`}>—</td>
              </tr>
            ))}

            {groupRow('Observed only', observedOnly.length, 'seen in traces but not declared')}
            {observedRows.map(o => {
              const target = ADOPT_TARGET[o.kind]
              return (
                <tr key={`o:${obsKey(o)}`}>
                  <td className={td}>
                    <input
                      type="checkbox"
                      className="accent-teal-600"
                      aria-label={`Select ${o.name}`}
                      disabled={!target || adopting}
                      checked={selected.has(obsKey(o))}
                      onChange={() => toggle(o)}
                      title={target ? `Add to ${target}` : 'Only tools, MCP servers and retrievers can be added to the declaration'}
                    />
                  </td>
                  <td className={`${td} font-mono text-gray-800`}>{o.name}</td>
                  <td className={`${td} text-gray-500`}>{o.kind === 'agent' ? 'Agent step' : KIND_LABEL[o.kind] || o.kind}</td>
                  <td className={`${td} text-gray-400`}>{target ? `not declared → ${target}` : 'not declared'}</td>
                  <td className={`${td} text-gray-600`}>seen</td>
                  <td className={`${td} text-gray-600`}>×{fmtNumber(o.count)}</td>
                </tr>
              )
            })}
            {agentSteps.length > AGENT_STEPS_SHOWN && (
              <tr>
                <td />
                <td colSpan={5} className="py-1.5">
                  <button onClick={() => setShowAllSteps(!showAllSteps)} className="text-xs text-teal-600 hover:text-teal-700">
                    {showAllSteps ? 'Show fewer agent steps' : `Show ${hiddenSteps} more agent step(s)`}
                  </button>
                  <span className="text-xs text-gray-400 ml-2">Usually steps inside this app's own graph. A call to another registered agent belongs in this agent's Calls field.</span>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {observedOnly.some(o => ADOPT_TARGET[o.kind]) && (
        <div className="mt-3 border-t border-gray-100 pt-3">
          {confirming ? (
            <div className="rounded-lg bg-teal-50/60 ring-1 ring-teal-200 p-3">
              <p className="text-xs text-gray-700 mb-1">Add {chosen.length} item(s) to this agent's declared dependencies?</p>
              <ul className="text-xs text-gray-600 mb-2 list-disc pl-4">
                {chosen.map(o => <li key={obsKey(o)}><span className="font-mono">{o.name}</span> → {ADOPT_TARGET[o.kind]}</li>)}
              </ul>
              <div className="flex gap-2">
                <button onClick={adopt} disabled={adopting} className="btn-primary btn-sm">{adopting ? 'Adopting…' : 'Confirm'}</button>
                <button onClick={() => setConfirming(false)} disabled={adopting} className="btn-secondary btn-sm">Cancel</button>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-400">Nothing is added until you confirm.</span>
              <button onClick={() => { setResult(null); setConfirming(true) }} disabled={chosen.length === 0} className="btn-secondary btn-sm">
                Adopt selected{chosen.length ? ` (${chosen.length})` : ''}
              </button>
            </div>
          )}
          {adoptError && <p className="text-xs text-rose-600 mt-2">{adoptError}</p>}
          {result && (
            <p className="text-xs text-teal-700 mt-2">
              {result.added.length ? `Added ${result.added.map(a => a.name).join(', ')}.` : 'Nothing new to add.'}
              {result.skipped.length ? ` Skipped ${result.skipped.map(s => s.name).join(', ')} (already declared).` : ''}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function hopLabel(hops: number | null): string {
  if (hops == null) return ''
  return hops === 1 ? 'direct' : `${hops} hops`
}

function BlastRadiusCard({ blast, upstream, shared }: { blast: BlastRadius; upstream: UpstreamDep[]; shared: SharedResource[] }) {
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-800">Blast radius</h3>
        <SourceBadge source="declared" />
      </div>
      <div className="grid grid-cols-2 gap-5">
        <div>
          <SectionLabel>If this agent goes down</SectionLabel>
          <div className="grid grid-cols-3 gap-2 mt-1 mb-3">
            <MiniStat label="Downstream" value={fmtNumber(blast.downstreamCount)} accent={blast.downstreamCount ? 'text-rose-600' : undefined} />
            <MiniStat label="Agents" value={fmtNumber(blast.agents.length)} />
            <MiniStat label="Consumers" value={fmtNumber(blast.consumers.length)} />
          </div>
          {blast.downstreamCount === 0 ? (
            <p className="text-xs text-gray-400">No registered agent calls this one and no consumers are declared.</p>
          ) : (
            <>
              <ul className="space-y-1">
                {blast.agents.map(a => (
                  <li key={a.id} className="flex items-center gap-2 text-xs">
                    <Link to={`/agents/${encodeURIComponent(a.id)}?tab=diagram`} className="text-gray-800 hover:text-teal-700 truncate">{a.name}</Link>
                    {a.stage && <span className={STAGE_PILL[a.stage] || 'status-pending'}>{a.stage}</span>}
                    {a.atRisk && <span className="text-[10px] text-rose-600">at risk</span>}
                    <span className="text-gray-400 ml-auto whitespace-nowrap">{hopLabel(a.hops)}</span>
                  </li>
                ))}
              </ul>
              {blast.consumers.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {blast.consumers.map(c => (
                    <span key={c.id} className={`text-xs px-2 py-0.5 rounded-full ring-1 ${NEUTRAL_CHIP}`} title={hopLabel(c.hops)}>{c.name}</span>
                  ))}
                </div>
              )}
              {blast.revenueAtRisk > 0 && (
                <p className="text-xs text-gray-500 mt-2">Declared value on the affected path (incl. this agent): <b className="text-gray-700">{fmtDollars(blast.revenueAtRisk)}/mo</b></p>
              )}
            </>
          )}
        </div>

        <div>
          <SectionLabel>Depends on (agents this one calls)</SectionLabel>
          {upstream.length === 0 ? (
            <p className="text-xs text-gray-400 mt-1">No agent dependencies declared.</p>
          ) : (
            <ul className="space-y-1 mt-1">
              {upstream.map(u => (
                <li key={u.id} className="flex items-center gap-2 text-xs">
                  {u.registered ? (
                    <Link to={`/agents/${encodeURIComponent(u.id)}?tab=diagram`} className="text-gray-800 hover:text-teal-700 truncate">{u.name}</Link>
                  ) : (
                    <span className="text-gray-800 truncate">{u.name}</span>
                  )}
                  {u.registered
                    ? u.stage && <span className={STAGE_PILL[u.stage] || 'status-pending'}>{u.stage}</span>
                    : <span className={`text-[10px] px-1.5 py-0.5 rounded-full ring-1 ${NEUTRAL_CHIP}`}>unregistered</span>}
                  {u.atRisk && <span className="text-[10px] px-1.5 py-0.5 rounded-full ring-1 bg-rose-50 text-rose-700 ring-rose-200">at risk</span>}
                  {u.worstGate && u.worstGate !== 'Approved' && <span className="text-gray-400 ml-auto whitespace-nowrap">gate: {u.worstGate}</span>}
                </li>
              ))}
            </ul>
          )}

          {shared.length > 0 && (
            <div className="mt-3">
              <SectionLabel>Shared resources</SectionLabel>
              <ul className="space-y-1 mt-1">
                {shared.map(r => (
                  <li key={r.id} className="flex items-center gap-2 text-xs">
                    <span className="text-gray-700 truncate">{r.name}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full ring-1 ${r.concentrated ? 'bg-amber-50 text-amber-700 ring-amber-200' : NEUTRAL_CHIP}`}>
                      {r.alsoUsedBy ? `also used by ${r.alsoUsedBy} agent(s)` : 'only this agent'}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
