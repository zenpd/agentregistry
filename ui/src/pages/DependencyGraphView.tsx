import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { DataSet } from 'vis-data'
import { Network } from 'vis-network'

import { getGraphV2, getImpact, type GraphNodeV2, type GraphV2Response } from '../services/api'

// ── cobol visual vocabulary (raw hex — serialised into vis options) ─────────

const EDGE_COLORS: Record<string, string> = {
  CALLS: '#7c3aed',
  CONSUMED_BY: '#475569',
  ACCESSES: '#d97706',
  USES_KB: '#15803d',
  USES_MCP: '#a21caf',
}

const EDGE_LABELS: Record<string, string> = {
  CALLS: 'calls',
  CONSUMED_BY: 'feeds',
  ACCESSES: 'accesses',
  USES_KB: 'knowledge',
  USES_MCP: 'tool',
}

interface VisNode {
  id: string
  label: string
  ci_kind: string
  ci_entry?: string
  color: { background: string; border: string }
  font: { color: string; size: number }
  title: string
  borderWidth: number
  shape: string
  hidden?: boolean
  x?: number
  y?: number
  baseColor?: { background: string; border: string; borderWidth: number }
  at_risk?: boolean
}

interface VisEdge {
  id: string
  from: string
  to: string
  label?: string
  color: string
  dashes?: boolean[] | boolean
  title?: string
  hidden?: boolean
  baseColor?: string
  width?: number
}

interface Props {
  height?: number
}

/**
 * Cobol ContextIntel-style dependency graph, rendered natively with the SAME
 * engine cobol uses (vis-network via pyvis) — but as a React component, so the
 * legend chips, selection, outage overlay and hierarchical view talk to the
 * vis DataSets directly instead of through an iframe bridge.
 *
 * Cobol rules kept intact:
 *  - one ci_kind per node; entry-point-ness is a border decoration
 *  - an edge is hidden when either endpoint is hidden
 *  - nodes are hidden, never removed (layout is preserved on re-toggle)
 *  - right-click a Production agent → "🌳 Hierarchical view from here"
 *    (BFS out-edges tidy tree, physics off, positions restored on exit)
 */
export default function DependencyGraphView() {
  const [graph, setGraph] = useState<GraphV2Response | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [hiddenKinds, setHiddenKinds] = useState<Set<string>>(new Set())
  const [focusRoot, setFocusRoot] = useState<string | null>(null)
  const [focusCount, setFocusCount] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [impact, setImpact] = useState<Awaited<ReturnType<typeof getImpact>>['data'] | null>(null)
  const [impactLoading, setImpactLoading] = useState(false)
  const [menu, setMenu] = useState<{ x: number; y: number; items: { label: string; run: () => void }[] } | null>(null)
  const [search, setSearch] = useState('')

  const containerRef = useRef<HTMLDivElement | null>(null)
  const networkRef = useRef<Network | null>(null)
  const nodesDs = useRef<DataSet<any> | null>(null)
  const edgesDs = useRef<DataSet<any> | null>(null)
  const savedPositions = useRef<Record<string, { x: number; y: number }> | null>(null)

  const hiddenRef = useRef(hiddenKinds)
  hiddenRef.current = hiddenKinds
  const focusRef = useRef(focusRoot)
  focusRef.current = focusRoot

  const fetchData = useCallback(async () => {
    try {
      setLoading(true)
      const resp = await getGraphV2()
      setGraph(resp.data)
      setError(null)
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Failed to fetch')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const nodeById = useMemo(() => {
    const m = new Map<string, GraphNodeV2>()
    for (const n of graph?.nodes ?? []) m.set(n.id, n)
    return m
  }, [graph])

  // ── build vis datasets from the shared builder output ─────────────────────

  const datasetsBuilt = useMemo(() => {
    if (!graph) return null
    const deptColors = new Map<string, string>()
    for (const item of graph.legend) {
      if (item.kind.startsWith('group:')) deptColors.set(item.kind, item.color)
    }

    const nodes = new DataSet<VisNode>()
    const edges = new DataSet<VisEdge>()

    for (const n of graph.nodes as GraphNodeV2[]) {
      const attrs = n.attrs ?? {}
      if (n.kind.startsWith('group:')) {
        const isProduction = attrs.entry === 'production'
        const fill = deptColors.get(n.kind) ?? '#9ca3af'
        nodes.add({
          id: n.id,
          label: `${isProduction ? '▶ ' : ''}${n.name}`,
          ci_kind: n.kind,
          ci_entry: isProduction ? 'production' : 'pipeline',
          color: { background: fill, border: isProduction ? '#17b26a' : '#d97706' },
          baseColor: { background: fill, border: isProduction ? '#17b26a' : '#d97706', borderWidth: isProduction ? 5 : 2 },
          font: { color: '#ffffff', size: 13 },
          title: [
            `Dept: ${attrs.dept ?? ''}`,
            `Stage: ${attrs.stage ?? ''}`,
            attrs.model_name ? `Model: ${attrs.model_name}` : '',
            `Value: $${attrs.value_amount ?? 0}/mo · ${attrs.hours_saved_monthly ?? 0} h/mo`,
            `Tokens: $${attrs.token_cost ?? 0}/mo`,
            attrs.at_risk ? '⚠ FLAGGED AT RISK' : '',
            attrs.worst_gate ? `Governance: ${attrs.worst_gate}` : '',
            isProduction ? 'right-click for a hierarchical view of what it feeds' : '',
          ].filter(Boolean).join('\n'),
          borderWidth: isProduction ? 5 : 2,
          shape: 'circle',
          at_risk: !!attrs.at_risk,
        })
      } else {
        const style = ({
          external: { bg: '#f8f7ff', border: '#e7e4fb', font: '#9ca3af', shape: 'circle', kind: 'external', title: 'Unregistered agent (shadow-AI candidate)' },
          system: { bg: '#dbeafe', border: '#0891b2', font: '#1f2937', shape: 'database', kind: 'system', title: `Enterprise system: ${n.name}` },
          database: { bg: '#fef3c7', border: '#c2410c', font: '#7c2d12', shape: 'database', kind: 'database', title: `Database: ${n.name}` },
          knowledge_base: { bg: '#dcfce7', border: '#15803d', font: '#14532d', shape: 'box', kind: 'knowledge_base', title: `Knowledge base: ${n.name}` },
          mcp_server: { bg: '#fee2e2', border: '#a21caf', font: '#7f1d1d', shape: 'box', kind: 'mcp_server', title: `MCP / tool server: ${n.name}` },
          consumer: { bg: '#f1f5f9', border: '#475569', font: '#334155', shape: 'box', kind: 'consumer', title: `Consumer: ${n.name}` },
        } as Record<string, { bg: string; border: string; font: string; shape: string; kind: string; title: string }>)[n.kind] ?? {
          bg: '#f1f5f9', border: '#94a3b8', font: '#334155', shape: 'box', kind: n.kind, title: n.name,
        }
        nodes.add({
          id: n.id,
          label: n.name,
          ci_kind: style.kind,
          color: { background: style.bg, border: style.border },
          font: { color: style.font, size: 12 },
          title: style.title,
          borderWidth: 2,
          baseColor: { background: style.bg, border: style.border, borderWidth: 2 },
          shape: style.shape,
        })
      }
    }

    for (const e of graph.edges as { from: string; to: string; type: string }[]) {
      const isCalls = e.type === 'CALLS'
      const color = EDGE_COLORS[e.type] ?? '#94a3b8'
      edges.add({
        id: `${e.from}|${e.to}|${e.type}`,
        from: e.from,
        to: e.to,
        label: isCalls ? 'calls' : e.type === 'CONSUMED_BY' ? 'feeds' : undefined,
        color,
        baseColor: color,
        width: 1,
        dashes: !isCalls,
        title: EDGE_LABELS[e.type] ?? e.type,
      })
    }
    return { nodes, edges }
  }, [graph])

  // ── engine boot ────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!datasetsBuilt || !containerRef.current) return
    const { nodes, edges } = datasetsBuilt
    nodesDs.current = nodes
    edgesDs.current = edges

    const network = new Network(
      containerRef.current,
      { nodes: nodes as any, edges: edges as any },
      {
        physics: {
          solver: 'forceAtlas2Based',
          forceAtlas2Based: { springLength: 160 },
          stabilization: { iterations: 350 },
        } as any,
        edges: {
          arrows: { to: { enabled: true } },
          color: { color: '#a78bfa' },
          smooth: { enabled: true, type: 'dynamic' } as any,
          font: { size: 10, color: '#64748b', strokeWidth: 0 },
        } as any,
        interaction: { hover: true, tooltipDelay: 120 },
      } as any
    )
    networkRef.current = network

    // Selection → details panel
    network.on('click', (params: any) => {
      if (params.nodes?.length) setSelectedId(String(params.nodes[0]))
      else setSelectedId(null)
      setMenu(null)
    })
    network.on('dragStart', () => setMenu(null))
    network.on('zoom', () => setMenu(null))
    network.on('oncontext', (params: any) => {
      const nodeId = network.getNodeAt(params.pointer.DOM)
      const node = nodeId != null ? nodes.get(String(nodeId)) : null
      const items: { label: string; run: () => void }[] = []
      if (node?.ci_entry === 'production' && String(nodeId) !== focusRef.current) {
        items.push({ label: '🌳 Hierarchical view from here', run: () => setFocusRoot(String(nodeId)) })
      }
      if (focusRef.current) {
        items.push({ label: '↩ Back to the full graph', run: () => setFocusRoot(null) })
      }
      if (!items.length) { setMenu(null); return }
      params.event.preventDefault()
      setMenu({ x: params.event.clientX, y: params.event.clientY, items })
    })

    return () => {
      network.destroy()
      networkRef.current = null
    }
  }, [datasetsBuilt])

  // ── filtering + hierarchical view (cobol runtime, ported to TS) ────────────

  const applyFilters = useCallback(() => {
    const nodes = nodesDs.current
    const edges = edgesDs.current
    const network = networkRef.current
    if (!nodes || !edges || !network) return { visibleNodes: 0 }

    // While focused, the tree decides visibility; the root always stays.
    let tree: { seen: Record<string, boolean>; treeEdges: Record<string, boolean>; order: string[] } | null = null
    if (focusRef.current) {
      const root = focusRef.current
      const adjacency: Record<string, { id: string; to: string }[]> = {}
      edges.forEach((e: any) => (adjacency[e.from] = adjacency[e.from] || []).push(e))
      const kindOf: Record<string, string> = {}
      nodes.forEach((n: any) => (kindOf[n.id] = n.ci_kind))

      const order = [root]
      const seen: Record<string, boolean> = { [root]: true }
      const depth: Record<string, number> = { [root]: 0 }
      const children: Record<string, string[]> = { [root]: [] }
      const treeEdges: Record<string, boolean> = {}
      for (let i = 0; i < order.length; i++) {
        const from = order[i]
        for (const out of adjacency[from] || []) {
          if (seen[out.to] || hiddenRef.current.has(kindOf[out.to])) continue
          seen[out.to] = true
          depth[out.to] = depth[from] + 1
          children[from].push(out.to)
          children[out.to] = []
          treeEdges[out.id] = true
          order.push(out.to)
        }
      }
      tree = { seen, treeEdges, order }

      // Tidy-tree layout: leaves take the next free column, parents centre.
      const LEAF_GAP = 190
      const LEVEL_GAP = 170
      const pos: Record<string, { x: number; y: number }> = {}
      let nextLeaf = 0
      const stack = [{ id: root, expanded: false }]
      while (stack.length) {
        const frame = stack.pop()!
        const kids = children[frame.id] || []
        if (kids.length === 0 || frame.expanded) {
          let x = 0
          if (kids.length === 0) { x = nextLeaf * LEAF_GAP; nextLeaf++ }
          else { for (const k of kids) x += pos[k].x; x /= kids.length }
          pos[frame.id] = { x, y: depth[frame.id] * LEVEL_GAP }
        } else {
          stack.push({ id: frame.id, expanded: true })
          for (let m = kids.length - 1; m >= 0; m--) stack.push({ id: kids[m], expanded: false })
        }
      }
      const shift = pos[root].x
      for (const id in pos) pos[id].x -= shift
      for (const id in pos) {
        try { network.moveNode(id, pos[id].x, pos[id].y) } catch { /* node vanished */ }
      }
      try {
        network.fit({ nodes: tree.order, animation: { duration: 400, easingFunction: 'easeInOutQuad' } } as any)
      } catch { /* older vis-network */ }
    }

    const nodeUpdates: any[] = []
    let visibleNodes = 0
    nodes.forEach((n: any) => {
      const isHidden = tree ? tree.seen[n.id] !== true : hiddenRef.current.has(n.ci_kind)
      if (!isHidden) visibleNodes++
      if ((n.hidden === true) !== isHidden) nodeUpdates.push({ id: n.id, hidden: isHidden })
    })

    // An edge survives only if BOTH endpoints do (cobol rule).
    const edgeUpdates: any[] = []
    let visibleEdges = 0
    edges.forEach((e: any) => {
      const fromNode: any = nodes.get(e.from)
      const toNode: any = nodes.get(e.to)
      const fromHidden = tree ? tree.seen[e.from] !== true : hiddenRef.current.has(fromNode?.ci_kind ?? '')
      const toHidden = tree ? tree.seen[e.to] !== true : hiddenRef.current.has(toNode?.ci_kind ?? '')
      const isHidden = fromHidden || toHidden
      if (!isHidden) visibleEdges++
      if ((e.hidden === true) !== isHidden) edgeUpdates.push({ id: e.id, hidden: isHidden })
    })

    if (nodeUpdates.length) nodes.update(nodeUpdates)
    if (edgeUpdates.length) edges.update(edgeUpdates)
    return { visibleNodes, visibleEdges }
  }, [])

  // Re-apply filters when kinds toggled or focus changes.
  useEffect(() => {
    const result = applyFilters()
    if (focusRoot) setFocusCount(result.visibleNodes)
  }, [hiddenKinds, focusRoot, applyFilters])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setMenu(null)
        setFocusRoot(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // ── outage overlay ─────────────────────────────────────────────────────────

  const simulateOutage = useCallback(async (nodeId: string) => {
    try {
      setImpactLoading(true)
      const resp = await getImpact(nodeId)
      setImpact(resp.data)
      const nodes = nodesDs.current
      const edges = edgesDs.current
      if (nodes && edges) {
        const hitNodes = new Set(resp.data.affected_node_ids ?? [])
        const hitEdges = new Set(resp.data.affected_edge_keys ?? [])
        nodes.forEach((n: any) => {
          const hit = hitNodes.has(n.id)
          nodes.update({
            id: n.id,
            color: hit
              ? { background: '#fee2e2', border: '#ef4444' }
              : { background: n.baseColor.background, border: n.baseColor.border },
            borderWidth: hit ? 4 : n.baseColor.borderWidth,
          })
        })
        edges.forEach((e: any) => {
          const hit = hitEdges.has(e.id)
          edges.update({
            id: e.id,
            color: hit ? '#ef4444' : e.baseColor,
            width: hit ? 3 : 1,
          })
        })
      }
      // reveal the target even if its kind is hidden
      const n = nodesDs.current?.get(nodeId)
      if (n?.hidden && nodesDs.current) nodesDs.current.update({ id: nodeId, hidden: false })
    } finally {
      setImpactLoading(false)
    }
  }, [])

  const clearOverlay = useCallback(() => {
    setImpact(null)
    const nodes = nodesDs.current
    const edges = edgesDs.current
    if (nodes && edges) {
      nodes.forEach((n: any) => {
        nodes.update({
          id: n.id,
          color: { background: n.baseColor.background, border: n.baseColor.border },
          borderWidth: n.baseColor.borderWidth,
        })
      })
      edges.forEach((e: any) => {
        edges.update({ id: e.id, color: e.baseColor, width: 1 })
      })
    }
  }, [])

  const searchFocus = useCallback(() => {
    const q = search.trim().toLowerCase()
    if (!q || !networkRef.current) return
    const match = (graph?.nodes ?? []).find(n => n.name.toLowerCase().includes(q))
    if (match) {
      setSelectedId(match.id)
      try { networkRef.current.focus(match.id, { scale: 1.1, animation: { duration: 400, easingFunction: 'easeInOutQuad' } } as any) } catch { /* noop */ }
      try { networkRef.current.selectNodes([match.id]) } catch { /* noop */ }
    }
  }, [search, graph])

  const selected = selectedId ? nodeById.get(selectedId) : null

  if (loading) return <div className="p-8 text-center text-gray-500">Loading dependency graph…</div>
  if (error) return <div className="p-8 text-center text-red-500">Error: {error}</div>
  if (!graph) return null

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-4 gap-2">
        {([
          ['Agents + deps', graph.stats.nodes],
          ['Dependencies', graph.stats.edges],
          ['Production entry points', graph.stats.production_agents],
          ['Agent→Agent calls', graph.stats.cross_agent_edges],
        ] as [string, number][]).map(([label, value]) => (
          <div key={label} className="rounded-lg border bg-white p-2 text-center">
            <div className="text-lg font-bold text-slate-800">{value}</div>
            <div className="text-[10px] uppercase text-slate-500">{label}</div>
          </div>
        ))}
      </div>

      {/* Legend chips — one toggle per node kind (cobol contract) */}
      <div className="flex flex-wrap items-center gap-2">
        {graph.legend.map(item => {
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
        <button
          onClick={() => setHiddenKinds(new Set())}
          className="rounded-full border border-slate-300 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50"
        >
          Show all
        </button>
        <button
          onClick={() => setHiddenKinds(new Set(graph.legend.map(i => i.kind)))}
          className="rounded-full border border-slate-300 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50"
        >
          Hide all
        </button>
        <div className="ml-auto flex items-center gap-2">
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') searchFocus() }}
            placeholder="Search & focus…"
            className="w-52 rounded-lg border px-3 py-1.5 text-sm"
          />
          <button onClick={searchFocus} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50">
            Go
          </button>
        </div>
      </div>

      {focusRoot && (
        <div className="flex items-center justify-between rounded-lg bg-indigo-50 px-4 py-2 text-sm">
          <span>
            🌳 Hierarchical view from <strong>{nodeById.get(focusRoot)?.name ?? focusRoot}</strong> — {focusCount} node(s) reached, laid out as a tree
          </span>
          <button
            onClick={() => setFocusRoot(null)}
            className="rounded border border-indigo-300 px-2 py-1 text-xs text-indigo-700"
          >
            ↩ Back to full graph
          </button>
        </div>
      )}

      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2 overflow-hidden rounded-lg border bg-white" style={{ height: 620 }}>
          <div ref={containerRef} style={{ width: '100%', height: 620 }} />
          {menu && (
            <div
              className="fixed z-50 min-w-[210px] rounded-lg border border-gray-200 bg-white p-1 shadow-lg"
              style={{ left: menu.x, top: menu.y }}
            >
              {menu.items.map(item => (
                <button
                  key={item.label}
                  onClick={() => { item.run(); setMenu(null) }}
                  className="block w-full rounded px-3 py-1.5 text-left text-xs font-semibold text-slate-700 hover:bg-slate-100"
                >
                  {item.label}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-lg border bg-white p-4 text-sm" style={{ maxHeight: 620, overflowY: 'auto' }}>
          {selected ? (
            <div className="space-y-3">
              <div>
                <h3 className="font-semibold text-slate-800">{selected.name}</h3>
                <div className="text-xs text-slate-500">
                  {selected.kind.startsWith('group:')
                    ? `${selected.attrs.stage ?? ''} · ${selected.attrs.dept ?? ''}`
                    : selected.kind}
                </div>
              </div>
              {selected.attrs.worst_gate && (
                <div className="text-xs">Worst governance gate: <b>{selected.attrs.worst_gate}</b></div>
              )}
              {selected.attrs.at_risk && (
                <div className="rounded bg-amber-50 px-2 py-1 text-xs text-amber-700">▶ Flagged at risk</div>
              )}
              {selected.kind.startsWith('group:') && (
                <div className="text-xs text-slate-500">
                  ${Math.round(selected.attrs.value_amount ?? 0).toLocaleString()}/mo value ·{' '}
                  {selected.attrs.hours_saved_monthly ?? 0} h/mo saved ·{' '}
                  ${selected.attrs.token_cost ?? 0} tokens/mo
                </div>
              )}
              <div>
                <h4 className="text-xs font-semibold uppercase text-slate-500">Outgoing</h4>
                <ul className="mt-1 space-y-1 text-xs">
                  {graph.edges.filter(e => e.from === selected.id).map(e => {
                    const target = nodeById.get(e.to)
                    return (
                      <li
                        key={`${e.to}-${e.type}`}
                        className="cursor-pointer text-blue-600 hover:underline"
                        onClick={() => setSelectedId(e.to)}
                      >
                        {EDGE_LABELS[e.type] ?? e.type} {target?.name ?? e.to}
                      </li>
                    )
                  })}
                </ul>
              </div>
              <div>
                <h4 className="text-xs font-semibold uppercase text-slate-500">Incoming</h4>
                <ul className="mt-1 space-y-1 text-xs">
                  {graph.edges.filter(e => e.to === selected.id).map(e => {
                    const source = nodeById.get(e.from)
                    return (
                      <li
                        key={`${e.from}-${e.type}`}
                        className="cursor-pointer text-green-600 hover:underline"
                        onClick={() => setSelectedId(e.from)}
                      >
                        ← {source?.name ?? e.from}
                      </li>
                    )
                  })}
                </ul>
              </div>
              {selected.kind.startsWith('group:') && (
                <button
                  disabled={impactLoading}
                  onClick={() => simulateOutage(selected.id)}
                  className="w-full rounded-lg bg-red-600 px-3 py-2 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-50"
                >
                  {impactLoading ? 'Simulating…' : '⚡ Simulate outage'}
                </button>
              )}
              {impact && (
                <div className="rounded-lg bg-red-50 p-3 text-xs">
                  <div className="mb-1 font-semibold text-red-700">
                    Outage: {impact.target_name} — {impact.risk_level.toUpperCase()}
                  </div>
                  <div>Revenue at risk: ${impact.revenue_at_risk.toLocaleString()}/mo</div>
                  <div>Hours at risk: {impact.efficiency_at_risk}/mo</div>
                  <div>Departments hit: {impact.blast_radius_depts.join(', ')}</div>
                  <ul className="mt-1 list-disc pl-4">
                    {impact.mitigation_suggestions.map((m, i) => <li key={i}>{m}</li>)}
                  </ul>
                  <button
                    onClick={() => { setImpact(null); setSelectedId(null) }}
                    className="mt-2 rounded border border-red-300 px-2 py-1"
                  >
                    Clear highlight
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="text-xs text-slate-400">
              Click an agent node for details. Right-click a ▶ Production agent for the hierarchical view. Hover for tooltips.
            </div>
          )}
        </div>
      </div>

      <div className="rounded-lg border bg-white p-3 text-xs leading-relaxed text-slate-600">
        <b>How to read this graph</b><br />
        🟢 Thick green border + ▶ = <b>Production agent</b> (right-click for the hierarchical tree) · 🟠 amber border = pipeline stage · circle fill = department (see toggles)<br />
        ⚪ Light hollow circle = <b>shadow-AI candidate</b> (referenced but unregistered) · 🔵 cylinder = enterprise system · 🟠 cylinder = database<br />
        🟩 Green box = knowledge base · 🟪 Purple box = MCP server · ⬜ Grey box = consumer · Solid violet "calls" = agent→agent chain · dashed = accesses / tools / feeds<br />
        Drag nodes to rearrange · scroll to zoom · hover for details.
      </div>
    </div>
  )
}
