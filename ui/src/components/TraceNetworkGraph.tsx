import { useEffect, useMemo, useRef } from 'react'
import { DataSet } from 'vis-data'
import { Network } from 'vis-network'

export interface TraceNode {
  id: string
  name: string
  kind: string
  count: number
  errorCount: number
  avgLatencyMs?: number | null
}

export interface TraceEdge {
  from: string
  to: string
  // 'calls': a true nested call (agent → tool/sub-step), drawn solid.
  // 'sequence': no span-nesting between them — a supervisor's routing
  // handoff recovered from real trace ordering — drawn dashed, since it's
  // "ran next," not "called."
  kind?: 'calls' | 'sequence'
  // The reverse edge exists too (a supervisor hands off and gets control
  // back). Drawn as one line with an arrowhead at each end rather than two
  // parallel lines, which doubled every edge around a hub.
  bidirectional?: boolean
}

interface Props {
  nodes: TraceNode[]
  edges: TraceEdge[]
  height?: number
  selectedId?: string | null
  onSelect?: (id: string | null) => void
  // Kinds currently toggled off in the legend — hidden, not removed, so
  // vis-network keeps node positions and the layout doesn't jump on toggle.
  hiddenKinds?: Set<string>
  // Bump the token (even for the same id) to re-trigger a pan/select from a
  // search box, independent of plain node clicks.
  focusSignal?: { id: string; token: number } | null
}

const ERROR_MIN_CALLS = 20
const ERROR_AMBER_RATE = 0.02
const ERROR_RED_RATE = 0.1
const DIMMED = '#e2e8f0'

// Edges are coloured by what they point AT, exactly like the Dependencies page
// colours its typed edges: agent→agent is the violet "calls" line, and each
// resource kind keeps the hue that page already uses for it (amber for things
// accessed, fuchsia for MCP, green for knowledge/retrieval).
const EDGE_COLOR_BY_TARGET: Record<string, string> = {
  agent: '#7c3aed',      // EDGE_COLORS.CALLS
  step: '#64748b',       // EDGE_COLORS.CONSUMED_BY
  tool: '#d97706',       // EDGE_COLORS.ACCESSES
  mcp_server: '#a21caf', // EDGE_COLORS.USES_MCP
  retriever: '#15803d',  // EDGE_COLORS.USES_KB
  guardrail: '#e11d48',
}
const EDGE_FALLBACK_COLOR = '#475569'

// Same pastel-fill + saturated-border + dark-font convention as the portfolio
// Dependencies page (DependencyGraphView), on the same white canvas — this graph
// used to be a dark-background/flat-colour scheme of its own; the ask was to
// look like the same product, not a different tool bolted onto the agent page.
// mcp_server and retriever reuse that page's mcp_server/knowledge_base values
// verbatim since the kinds are the same thing; agent/tool/guardrail have no
// direct equivalent there, so they're new but drawn in the same idiom.
// Every shape here carries its label INSIDE the node, like the Dependencies
// page — vis-network only does that for circle/ellipse/box/database, so those
// are the four silhouettes available, and each kind gets one. The actors are
// saturated fill with white text; everything they use is a pastel fill with
// dark text, which is exactly how that page separates agents from resources.
const LINEAGE_STYLE: Record<string, { bg: string; border: string; font: string; shape: string }> = {
  agent: { bg: '#2563eb', border: '#1e40af', font: '#ffffff', shape: 'circle' },
  // A framework graph node (a wait, an interrupt, a terminal state) — real,
  // and often busy, but not an agent: it never carries agent evidence. Given
  // its own silhouette so it can't be mistaken for one at a glance.
  step: { bg: '#e2e8f0', border: '#64748b', font: '#334155', shape: 'ellipse' },
  tool: { bg: '#fef3c7', border: '#c2410c', font: '#7c2d12', shape: 'box' },
  mcp_server: { bg: '#fee2e2', border: '#a21caf', font: '#7f1d1d', shape: 'box' },
  // A retriever is a store you read from, so it takes the cylinder the
  // Dependencies page uses for systems and databases.
  retriever: { bg: '#dcfce7', border: '#15803d', font: '#14532d', shape: 'database' },
  guardrail: { bg: '#ffe4e6', border: '#e11d48', font: '#881337', shape: 'box' },
}
const DEFAULT_STYLE = { bg: '#f1f5f9', border: '#475569', font: '#334155', shape: 'box' }

export function styleFor(kind: string) {
  return LINEAGE_STYLE[kind] || DEFAULT_STYLE
}

function borderFor(n: TraceNode): string {
  const base = styleFor(n.kind).border
  if (n.count < ERROR_MIN_CALLS || n.errorCount === 0) return base
  const rate = n.errorCount / n.count
  if (rate > ERROR_RED_RATE) return '#f43f5e'
  if (rate > ERROR_AMBER_RATE) return '#f59e0b'
  return base
}

// vis-network render of the trace-reconstructed lineage graph on the agent
// page's Diagram tab — physics layout, drag/zoom/pan and hover/click,
// matching the interaction model of the portfolio Dependencies view
// (DependencyGraphView) instead of the old fixed-circle SVG (NetworkGraph).
export default function TraceNetworkGraph({ nodes, edges, height = 440, selectedId, onSelect, hiddenKinds, focusSignal }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const networkRef = useRef<Network | null>(null)
  const nodesDs = useRef<DataSet<any> | null>(null)
  const edgesDs = useRef<DataSet<any> | null>(null)

  // sqrt scale: real call counts are power-law distributed (a supervisor
  // can be 100x busier than a leaf tool) — linear sizing would flatten
  // every non-hub node to nearly the same tiny dot.
  const maxSqrt = useMemo(() => Math.sqrt(Math.max(1, ...nodes.map(n => n.count))), [nodes])

  const built = useMemo(() => {
    const ds = new DataSet<any>()
    for (const n of nodes) {
      // These shapes size themselves to their label, so `size` is ignored.
      // Call volume comes through as padding AND type size: padding alone gets
      // swamped by name length, which would leave a one-off step with a long
      // name looking busier than the hub everything routes through.
      const weight = Math.sqrt(Math.max(1, n.count)) / maxSqrt
      const margin = 5 + Math.round(weight * 13)
      const fontSize = 11 + Math.round(weight * 8)
      const rate = n.count > 0 ? n.errorCount / n.count : 0
      const style = styleFor(n.kind)
      const border = borderFor(n)
      ds.add({
        id: n.id,
        kind: n.kind,
        label: n.name.length > 22 ? n.name.slice(0, 21) + '…' : n.name,
        shape: style.shape,
        margin: { top: margin, bottom: margin, left: margin + 2, right: margin + 2 },
        color: { background: style.bg, border, highlight: { background: style.bg, border } },
        borderWidth: n.errorCount > 0 && n.count >= ERROR_MIN_CALLS ? 4 : 2,
        font: { color: style.font, size: fontSize, strokeWidth: 0 },
        title: [
          `${n.name} (${n.kind})`,
          `${n.count.toLocaleString()} call(s)`,
          n.errorCount > 0 ? `${n.errorCount} error(s) — ${(rate * 100).toFixed(1)}%` : null,
          n.avgLatencyMs != null ? `${Math.round(n.avgLatencyMs)}ms avg` : null,
        ].filter(Boolean).join('\n'),
      })
    }
    const eds = new DataSet<any>()
    const ids = new Set(nodes.map(n => n.id))
    const kindOf = new Map(nodes.map(n => [n.id, n.kind]))
    const arrow = { enabled: true, scaleFactor: 0.6 }
    let i = 0
    for (const e of edges) {
      if (!ids.has(e.from) || !ids.has(e.to)) continue
      const isSequence = e.kind === 'sequence'
      const baseColor = EDGE_COLOR_BY_TARGET[kindOf.get(e.to) ?? ''] ?? EDGE_FALLBACK_COLOR
      eds.add({
        id: `${e.from}|${e.to}|${e.kind ?? 'calls'}|${i++}`,
        from: e.from,
        to: e.to,
        baseColor,
        baseWidth: isSequence ? 1 : 1.5,
        dashes: isSequence,
        color: { color: baseColor, highlight: baseColor },
        width: isSequence ? 1 : 1.5,
        label: isSequence ? undefined : 'calls',
        arrows: e.bidirectional ? { to: arrow, from: arrow } : { to: arrow },
        title: `${isSequence ? 'ran next (no nested call)' : 'called'}${e.bidirectional ? ' — both directions' : ''}`,
      })
    }
    return { nodes: ds, edges: eds }
  }, [nodes, edges, maxSqrt])

  useEffect(() => {
    if (!containerRef.current) return
    nodesDs.current = built.nodes
    edgesDs.current = built.edges

    const network = new Network(
      containerRef.current,
      { nodes: built.nodes as any, edges: built.edges as any },
      {
        physics: {
          solver: 'forceAtlas2Based',
          forceAtlas2Based: { springLength: 230, avoidOverlap: 1 },
          stabilization: { iterations: 300 },
        } as any,
        edges: {
          smooth: { enabled: true, type: 'curvedCW', roundness: 0.2 } as any,
          font: { size: 10, color: '#64748b', strokeWidth: 0 },
        } as any,
        nodes: { shadow: false },
        interaction: { hover: true, tooltipDelay: 120, dragView: true, zoomView: true },
      } as any,
    )
    networkRef.current = network
    network.on('click', (params: any) => {
      onSelect?.(params.nodes?.length ? String(params.nodes[0]) : null)
    })
    // Labels sit inside the nodes, so a busy graph is far wider than a dot
    // layout and would otherwise settle half outside the canvas. Fires once,
    // when the layout settles — not on selection, so it can't reintroduce the
    // jumping. Physics is switched off at the same time: nodes this large never
    // fully converge under avoidOverlap, so leaving it running let a click land
    // in a still-moving simulation and fling the whole graph. Frozen, the
    // layout holds still and dragging a node just leaves it where it's dropped.
    network.once('stabilized', () => {
      try {
        network.fit({ animation: { duration: 300, easingFunction: 'easeInOutQuad' } } as any)
        network.setOptions({ physics: false } as any)
      } catch { /* noop */ }
    })
    return () => {
      network.destroy()
      networkRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [built])

  // Toggle legend-chip visibility — hidden, not removed, and without touching
  // physics/layout. An edge is hidden whenever either endpoint is hidden.
  useEffect(() => {
    const nodesDsCur = nodesDs.current
    const edgesDsCur = edgesDs.current
    if (!nodesDsCur || !edgesDsCur) return
    const hidden = hiddenKinds ?? new Set<string>()
    const nodeHidden = new Map<string, boolean>()
    nodesDsCur.forEach((n: any) => {
      const isHidden = hidden.has(n.kind)
      nodeHidden.set(n.id, isHidden)
      nodesDsCur.update({ id: n.id, hidden: isHidden })
    })
    edgesDsCur.forEach((e: any) =>
      edgesDsCur.update({ id: e.id, hidden: !!nodeHidden.get(e.from) || !!nodeHidden.get(e.to) }),
    )
  }, [hiddenKinds, built])

  // Search & focus: pan/zoom to a node and select it, independent of a plain click.
  useEffect(() => {
    const network = networkRef.current
    if (!network || !focusSignal) return
    try {
      network.focus(focusSignal.id, { scale: 1.1, animation: { duration: 400, easingFunction: 'easeInOutQuad' } } as any)
      network.selectNodes([focusSignal.id])
    } catch { /* node not in the current dataset */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusSignal])

  // Dim everything except the selected node's neighborhood, without rebuilding the layout.
  useEffect(() => {
    const nodesDsCur = nodesDs.current
    const edgesDsCur = edgesDs.current
    if (!nodesDsCur || !edgesDsCur) return
    if (!selectedId) {
      nodesDsCur.forEach((n: any) => nodesDsCur.update({ id: n.id, opacity: 1 }))
      edgesDsCur.forEach((e: any) =>
        edgesDsCur.update({ id: e.id, color: { color: e.baseColor, highlight: e.baseColor }, width: e.baseWidth }))
      return
    }
    const neighborIds = new Set<string>([selectedId])
    edgesDsCur.forEach((e: any) => {
      if (e.from === selectedId) neighborIds.add(e.to)
      if (e.to === selectedId) neighborIds.add(e.from)
    })
    nodesDsCur.forEach((n: any) => nodesDsCur.update({ id: n.id, opacity: neighborIds.has(n.id) ? 1 : 0.25 }))
    // Edges touching the selection keep their own colour — the hue says what
    // they point at, so recolouring them all to one highlight would throw that
    // away. Only the rest fade back.
    edgesDsCur.forEach((e: any) => {
      const touches = e.from === selectedId || e.to === selectedId
      edgesDsCur.update({
        id: e.id,
        color: { color: touches ? e.baseColor : DIMMED, highlight: touches ? e.baseColor : DIMMED },
        width: touches ? 2.5 : 1,
      })
    })
  }, [selectedId])

  return <div ref={containerRef} style={{ height, width: '100%' }} />
}
