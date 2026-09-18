import { useEffect, useMemo, useRef } from 'react'
import { DataSet } from 'vis-data'
import { Network } from 'vis-network'
import { CAT_COLORS } from './NetworkGraph'

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
}

interface Props {
  nodes: TraceNode[]
  edges: TraceEdge[]
  height?: number
  selectedId?: string | null
  onSelect?: (id: string | null) => void
}

const ERROR_MIN_CALLS = 20
const ERROR_AMBER_RATE = 0.02
const ERROR_RED_RATE = 0.1
const DIMMED = '#2a3542'

function borderFor(n: TraceNode): string {
  if (n.count < ERROR_MIN_CALLS || n.errorCount === 0) return '#1f2a37'
  const rate = n.errorCount / n.count
  if (rate > ERROR_RED_RATE) return '#f43f5e'
  if (rate > ERROR_AMBER_RATE) return '#f59e0b'
  return '#1f2a37'
}

// vis-network render of the trace-reconstructed graph on the agent page's
// Diagram tab — physics layout, drag/zoom/pan and hover/click, matching the
// interaction model of the portfolio Dependencies view (DependencyGraphView)
// instead of the old fixed-circle SVG (NetworkGraph).
export default function TraceNetworkGraph({ nodes, edges, height = 440, selectedId, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const networkRef = useRef<Network | null>(null)
  const nodesDs = useRef<DataSet<any> | null>(null)
  const edgesDs = useRef<DataSet<any> | null>(null)

  const maxCount = useMemo(() => Math.max(1, ...nodes.map(n => n.count)), [nodes])

  const built = useMemo(() => {
    const ds = new DataSet<any>()
    for (const n of nodes) {
      const size = 14 + Math.round((Math.min(n.count, maxCount) / maxCount) * 16)
      const rate = n.count > 0 ? n.errorCount / n.count : 0
      ds.add({
        id: n.id,
        label: n.name.length > 22 ? n.name.slice(0, 21) + '…' : n.name,
        shape: 'dot',
        size,
        color: { background: CAT_COLORS[n.kind] || '#6b7280', border: borderFor(n), highlight: { background: CAT_COLORS[n.kind] || '#6b7280', border: '#ffffff' } },
        borderWidth: n.errorCount > 0 && n.count >= ERROR_MIN_CALLS ? 3 : 1.5,
        font: { color: '#e5e7eb', size: 11, strokeWidth: 0 },
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
    for (const e of edges) {
      if (!ids.has(e.from) || !ids.has(e.to)) continue
      eds.add({ id: `${e.from}|${e.to}`, from: e.from, to: e.to, color: { color: '#7c8ba1', highlight: '#3DDBD9' }, width: 1 })
    }
    return { nodes: ds, edges: eds }
  }, [nodes, edges, maxCount])

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
          forceAtlas2Based: { springLength: 110, avoidOverlap: 0.6 },
          stabilization: { iterations: 250 },
        } as any,
        edges: {
          arrows: { to: { enabled: true, scaleFactor: 0.6 } },
          smooth: { enabled: true, type: 'dynamic' } as any,
        } as any,
        nodes: { shadow: false },
        interaction: { hover: true, tooltipDelay: 120, dragView: true, zoomView: true },
      } as any,
    )
    networkRef.current = network
    network.on('click', (params: any) => {
      onSelect?.(params.nodes?.length ? String(params.nodes[0]) : null)
    })
    return () => {
      network.destroy()
      networkRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [built])

  // Dim everything except the selected node's neighborhood, without rebuilding the layout.
  useEffect(() => {
    const nodesDsCur = nodesDs.current
    const edgesDsCur = edgesDs.current
    if (!nodesDsCur || !edgesDsCur) return
    if (!selectedId) {
      nodesDsCur.forEach((n: any) => nodesDsCur.update({ id: n.id, opacity: 1 }))
      edgesDsCur.forEach((e: any) => edgesDsCur.update({ id: e.id, color: { color: '#7c8ba1', highlight: '#3DDBD9' } }))
      return
    }
    const neighborIds = new Set<string>([selectedId])
    edgesDsCur.forEach((e: any) => {
      if (e.from === selectedId) neighborIds.add(e.to)
      if (e.to === selectedId) neighborIds.add(e.from)
    })
    nodesDsCur.forEach((n: any) => nodesDsCur.update({ id: n.id, opacity: neighborIds.has(n.id) ? 1 : 0.25 }))
    edgesDsCur.forEach((e: any) =>
      edgesDsCur.update({ id: e.id, color: { color: e.from === selectedId || e.to === selectedId ? '#3DDBD9' : DIMMED } }),
    )
  }, [selectedId])

  return <div ref={containerRef} style={{ height, width: '100%' }} />
}
