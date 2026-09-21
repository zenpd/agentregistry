import { useEffect, useMemo, useRef, useState } from 'react'
import { forceSimulation, forceX, forceY, forceCollide, type SimulationNodeDatum } from 'd3-force'
import { select } from 'd3-selection'
import { drag as d3drag } from 'd3-drag'
import { zoom as d3zoom, zoomIdentity, type ZoomBehavior } from 'd3-zoom'
import type { ReconstructedNode, ReconstructedEdge } from '../services/api'

interface Props {
  nodes: ReconstructedNode[]
  edges: ReconstructedEdge[]
  height?: number
  selectedId?: string | null
  onSelect?: (id: string | null) => void
}

// role -> swimlane row + color. Order top-to-bottom mirrors the backend's
// ROLE_LANES so "step" (the agent's own trajectory) reads as the spine of
// the diagram, with what it calls laid out underneath it.
const LANES: { role: string; label: string; color: string }[] = [
  { role: 'step', label: 'Agent steps', color: '#6EA8FE' },
  { role: 'model', label: 'Models', color: '#57C785' },
  { role: 'tool', label: 'Tools & skills', color: '#F0A85A' },
  { role: 'resource', label: 'Resources & knowledge', color: '#3DDBD9' },
  { role: 'check', label: 'Guardrails & checks', color: '#F472B6' },
  { role: 'other', label: 'Other', color: '#9CA3AF' },
]
const LANE_COLOR: Record<string, string> = Object.fromEntries(LANES.map(l => [l.role, l.color]))

const ERROR_MIN_CALLS = 20
const ERROR_AMBER_RATE = 0.02
const ERROR_RED_RATE = 0.1

function borderFor(n: ReconstructedNode): string {
  if (n.count < ERROR_MIN_CALLS || n.errorCount === 0) return 'rgba(255,255,255,0.25)'
  const rate = n.errorCount / n.count
  if (rate > ERROR_RED_RATE) return '#f43f5e'
  if (rate > ERROR_AMBER_RATE) return '#f59e0b'
  return 'rgba(255,255,255,0.25)'
}

const COL_WIDTH = 190
const LEFT_GUTTER = 140
const TOP_GUTTER = 16
// One node's full vertical footprint (circle + two label lines) at max
// radius, so nodes stacked in a busy cell never overlap regardless of how
// many land there — a real supervisor-pattern agent can have a dozen+
// "root" nodes in one lane (each sub-flow's parent fell outside the
// sampled window), and a fixed lane height would crush them together.
const NODE_SLOT = 84
const LANE_MIN_HEIGHT = 110
const R_MIN = 14
const R_MAX = 26
const ZOOM_EXTENT: [number, number] = [0.15, 3]

interface SimNode extends SimulationNodeDatum, ReconstructedNode {
  targetX: number
  targetY: number
  r: number
}

// Lays out the trace-reconstructed graph as a left-to-right trajectory: X is
// how many hops into the call chain a step sits (BFS distance from the
// trace's root — see backend discovery/reconstruct.py for why BFS and not
// longest-path), Y is a swimlane per role sized to fit its busiest column.
//
// A d3-force simulation anchors every node at that computed (targetX,
// targetY) with forceX/forceY, and a collide force keeps neighbors from
// overlapping — the diagram is draggable (d3-drag), and letting go of a
// dragged node releases its pinned position, so the spring back to
// targetX/targetY animates it right back to its logical spot. Shake it all
// you want; it settles back to the same trajectory every time.
//
// d3-zoom drives pan/scroll-to-zoom on top of that, auto-fit to the
// container on load (a busy supervisor-pattern agent's diagram can be
// 2000+ px tall — nobody should have to scroll blind to find the shape of
// it), with +/-/Fit controls for when auto-fit undershoots what you want to
// inspect.
export default function TrajectoryDiagram({ nodes, edges, height = 440, selectedId, onSelect }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null)
  const zoomLayerRef = useRef<SVGGElement | null>(null)
  const gRef = useRef<SVGGElement | null>(null)
  const zoomBehaviorRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null)
  const selectRef = useRef(onSelect)
  selectRef.current = onSelect
  const [showLegend, setShowLegend] = useState(false)

  const maxCount = useMemo(() => Math.max(1, ...nodes.map(n => n.count)), [nodes])
  const maxDepth = useMemo(() => Math.max(0, ...nodes.map(n => n.depth)), [nodes])

  const layout = useMemo(() => {
    const activeLanes = LANES.filter(l => nodes.some(n => n.role === l.role))
    const byCell = new Map<string, ReconstructedNode[]>()
    for (const n of nodes) {
      const cellKey = `${n.role}:${n.depth}`
      const list = byCell.get(cellKey) ?? []
      list.push(n)
      byCell.set(cellKey, list)
    }
    for (const list of byCell.values()) list.sort((a, b) => b.count - a.count)

    // Each lane's height fits its busiest single cell (role at one depth),
    // not a fixed row height — a lane with 15 co-located roots gets a tall
    // band; a lane with one node per column stays compact.
    const laneHeights = activeLanes.map(l => {
      let maxStack = 1
      for (const [cellKey, list] of byCell) {
        if (cellKey.startsWith(`${l.role}:`)) maxStack = Math.max(maxStack, list.length)
      }
      return Math.max(LANE_MIN_HEIGHT, maxStack * NODE_SLOT)
    })
    const laneTop: number[] = []
    let cursor = TOP_GUTTER
    for (const h of laneHeights) {
      laneTop.push(cursor)
      cursor += h
    }
    const laneIndex = new Map(activeLanes.map((l, i) => [l.role, i]))

    const simNodes: SimNode[] = nodes.map(n => {
      const cellKey = `${n.role}:${n.depth}`
      const cell = byCell.get(cellKey) ?? [n]
      const slot = cell.indexOf(n)
      const laneI = laneIndex.get(n.role) ?? activeLanes.length - 1
      const laneH = laneHeights[laneI]
      const targetX = LEFT_GUTTER + n.depth * COL_WIDTH + COL_WIDTH / 2
      const targetY = laneTop[laneI] + ((slot + 0.5) / cell.length) * laneH
      const r = R_MIN + Math.round((Math.min(n.count, maxCount) / maxCount) * (R_MAX - R_MIN))
      return { ...n, targetX, targetY, x: targetX, y: targetY, r }
    })

    return { activeLanes, laneHeights, laneTop, simNodes, totalHeight: cursor + TOP_GUTTER }
  }, [nodes, maxCount])

  const { activeLanes, laneHeights, laneTop, simNodes, totalHeight } = layout
  const viewW = Math.max(760, LEFT_GUTTER + (maxDepth + 1) * COL_WIDTH)
  const viewH = Math.max(height, totalHeight)
  const maxEdgeCount = Math.max(1, ...edges.map(e => e.count))
  const errorCount = nodes.filter(n => n.errorCount > 0).length
  const busiest = nodes.length ? nodes.reduce((a, b) => (b.count > a.count ? b : a)) : null

  // Zoom/pan behaviour + fit-to-container, rebuilt whenever the diagram's
  // own virtual size changes (new data fetched).
  useEffect(() => {
    const svgEl = svgRef.current
    const layerEl = zoomLayerRef.current
    if (!svgEl || !layerEl) return
    const svg = select(svgEl)
    const layer = select(layerEl)

    const zoomBehavior = d3zoom<SVGSVGElement, unknown>()
      .scaleExtent(ZOOM_EXTENT)
      .on('zoom', (event) => layer.attr('transform', event.transform.toString()))
    svg.call(zoomBehavior)
    zoomBehaviorRef.current = zoomBehavior

    const cw = svgEl.clientWidth || viewW
    const ch = height
    const scale = Math.min(cw / viewW, ch / viewH, 1)
    const tx = (cw - viewW * scale) / 2
    const ty = (ch - viewH * scale) / 2
    svg.call(zoomBehavior.transform, zoomIdentity.translate(tx, ty).scale(scale))

    return () => {
      svg.on('.zoom', null)
    }
  }, [viewW, viewH, height])

  function fitView() {
    const svgEl = svgRef.current
    const zoomBehavior = zoomBehaviorRef.current
    if (!svgEl || !zoomBehavior) return
    const cw = svgEl.clientWidth || viewW
    const ch = height
    const scale = Math.min(cw / viewW, ch / viewH, 1)
    const tx = (cw - viewW * scale) / 2
    const ty = (ch - viewH * scale) / 2
    select(svgEl).transition().duration(300).call(zoomBehavior.transform, zoomIdentity.translate(tx, ty).scale(scale))
  }

  function zoomBy(factor: number) {
    const svgEl = svgRef.current
    const zoomBehavior = zoomBehaviorRef.current
    if (!svgEl || !zoomBehavior) return
    select(svgEl).transition().duration(200).call(zoomBehavior.scaleBy, factor)
  }

  // Rebuilds the D3-managed nodes/edges whenever the underlying data
  // changes. Selection highlighting is a separate effect below so clicking
  // a node doesn't restart the simulation.
  useEffect(() => {
    const gEl = gRef.current
    if (!gEl) return
    const g = select(gEl)
    g.selectAll('*').remove()

    const byId = new Map(simNodes.map(n => [n.id, n]))
    const links = edges
      .filter(e => byId.has(e.from) && byId.has(e.to))
      .map(e => ({ ...e, source: byId.get(e.from)!, target: byId.get(e.to)! }))

    const linkSel = g.append('g')
      .selectAll('path')
      .data(links)
      .join('path')
      .attr('fill', 'none')
      .attr('stroke', '#7c8ba1')
      .attr('stroke-width', d => 1 + (d.count / maxEdgeCount) * 2.5)
      .attr('stroke-dasharray', d => (d.kind === 'sequence' ? '4,3' : null))
      .attr('opacity', 0.55)
      .attr('marker-end', 'url(#traj-arrow)')

    const nodeSel = g.append('g')
      .selectAll<SVGGElement, SimNode>('g')
      .data(simNodes, (d: any) => d.id)
      .join('g')
      .style('cursor', selectRef.current ? 'pointer' : 'default')
      .on('click', (_event, d) => selectRef.current?.(d.id))

    nodeSel.append('title').text(d => [
      `${d.name} (${d.kind})`,
      `${d.count.toLocaleString()} call(s)`,
      d.errorCount > 0 ? `${d.errorCount} error(s)` : null,
      d.avgLatencyMs != null ? `${Math.round(d.avgLatencyMs)}ms avg` : null,
    ].filter(Boolean).join('\n'))

    nodeSel.filter(d => d.isRoot)
      .append('circle')
      .attr('r', d => d.r + 5)
      .attr('fill', 'none')
      .attr('stroke', d => LANE_COLOR[d.role] || '#6b7280')
      .attr('stroke-width', 1)
      .attr('stroke-dasharray', '2,3')
      .attr('opacity', 0.6)

    nodeSel.append('circle')
      .attr('class', 'traj-dot')
      .attr('r', d => d.r)
      .attr('fill', d => LANE_COLOR[d.role] || '#6b7280')
      .attr('fill-opacity', 0.9)
      .attr('stroke', d => borderFor(d))
      .attr('stroke-width', d => (d.errorCount > 0 && d.count >= ERROR_MIN_CALLS ? 2.5 : 1.5))

    nodeSel.append('text')
      .attr('y', d => d.r + 13)
      .attr('text-anchor', 'middle')
      .attr('fill', '#d1d5db')
      .attr('font-size', 10)
      .attr('font-family', 'Inter')
      .text(d => (d.name.length > 18 ? d.name.slice(0, 17) + '…' : d.name))

    nodeSel.append('text')
      .attr('y', d => d.r + 25)
      .attr('text-anchor', 'middle')
      .attr('fill', '#6b7280')
      .attr('font-size', 9)
      .attr('font-family', 'Inter')
      .text(d => `×${d.count}`)

    function tick() {
      linkSel.attr('d', d => {
        const s = d.source, t = d.target
        const dx = (t.x ?? 0) - (s.x ?? 0)
        const dy = (t.y ?? 0) - (s.y ?? 0)
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        const sx = (s.x ?? 0) + (dx / dist) * s.r
        const sy = (s.y ?? 0) + (dy / dist) * s.r
        const ex = (t.x ?? 0) - (dx / dist) * (t.r + 6)
        const ey = (t.y ?? 0) - (dy / dist) * (t.r + 6)
        const midx = (sx + ex) / 2
        return `M ${sx} ${sy} C ${midx} ${sy}, ${midx} ${ey}, ${ex} ${ey}`
      })
      nodeSel.attr('transform', d => `translate(${d.x ?? 0},${d.y ?? 0})`)
    }

    // Anchored at (targetX, targetY): the simulation's whole job is to hold
    // every node at its logical trajectory position and keep neighbors from
    // overlapping — it is what makes a dragged-and-released node spring
    // back to the same spot instead of staying wherever it was dropped.
    const simulation = forceSimulation<SimNode>(simNodes)
      .force('x', forceX<SimNode>(d => d.targetX).strength(0.4))
      .force('y', forceY<SimNode>(d => d.targetY).strength(0.4))
      .force('collide', forceCollide<SimNode>(d => d.r + 6))
      .alphaDecay(0.05)
      .on('tick', tick)

    nodeSel.call(
      d3drag<SVGGElement, SimNode>()
        .on('start', (event, d) => {
          // Without this, a mousedown on a node also starts the SVG's own
          // zoom-pan gesture (it's a mousedown on a descendant of the
          // zoomed element), so dragging a node would pan the canvas too.
          event.sourceEvent?.stopPropagation()
          if (!event.active) simulation.alphaTarget(0.3).restart()
          d.fx = d.x
          d.fy = d.y
        })
        .on('drag', (event, d) => {
          d.fx = event.x
          d.fy = event.y
        })
        .on('end', (event, d) => {
          if (!event.active) simulation.alphaTarget(0)
          // Releasing fx/fy (rather than leaving it pinned) is the "snap
          // back" — forceX/forceY immediately start pulling it toward
          // targetX/targetY again.
          d.fx = null
          d.fy = null
        }),
    )

    return () => {
      simulation.stop()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [simNodes, edges, maxEdgeCount])

  // Selection highlight — dim everything outside the selected node's
  // neighborhood without touching the simulation.
  useEffect(() => {
    const gEl = gRef.current
    if (!gEl) return
    const g = select(gEl)
    if (!selectedId) {
      g.selectAll<SVGGElement, SimNode>('g').style('opacity', 1)
      g.selectAll<SVGPathElement, any>('path').style('opacity', null)
      return
    }
    const neighborIds = new Set<string>([selectedId])
    for (const e of edges) {
      if (e.from === selectedId) neighborIds.add(e.to)
      if (e.to === selectedId) neighborIds.add(e.from)
    }
    g.selectAll<SVGGElement, SimNode>('g').style('opacity', d => (d?.id && neighborIds.has(d.id) ? 1 : 0.3))
    g.selectAll<SVGCircleElement, SimNode>('circle.traj-dot')
      .attr('stroke', d => (d.id === selectedId ? '#ffffff' : borderFor(d)))
      .attr('stroke-width', d => (d.id === selectedId ? 2.5 : d.errorCount > 0 && d.count >= ERROR_MIN_CALLS ? 2.5 : 1.5))
  }, [selectedId, edges])

  const btnClass = 'w-6 h-6 flex items-center justify-center rounded bg-gray-800/90 text-gray-200 text-xs hover:bg-gray-700 ring-1 ring-white/10'

  return (
    <div className="relative">
      <svg ref={svgRef} width="100%" height={height} style={{ display: 'block', cursor: 'grab' }}>
        <defs>
          <marker id="traj-arrow" markerWidth="8" markerHeight="8" refX="7" refY="2.5" orient="auto">
            <path d="M0,0 L0,5 L7,2.5 z" fill="#7c8ba1" />
          </marker>
        </defs>
        <g ref={zoomLayerRef}>
          {/* Lane bands + labels */}
          {activeLanes.map((l, i) => (
            <g key={l.role}>
              <rect
                x={0} y={laneTop[i]}
                width={viewW} height={laneHeights[i]}
                fill={i % 2 === 0 ? 'rgba(255,255,255,0.02)' : 'transparent'}
              />
              <text x={12} y={laneTop[i] + 16}
                fill={l.color} fontSize={10} fontFamily="Inter" fontWeight={600} opacity={0.85}>
                {l.label}
              </text>
            </g>
          ))}

          {/* D3-managed nodes + edges (force simulation + drag) */}
          <g ref={gRef} />
        </g>
      </svg>

      {/* Zoom controls */}
      <div className="absolute bottom-2 right-2 flex flex-col gap-1">
        <button className={btnClass} onClick={() => zoomBy(1.4)} title="Zoom in">+</button>
        <button className={btnClass} onClick={() => zoomBy(1 / 1.4)} title="Zoom out">−</button>
        <button className={btnClass} onClick={fitView} title="Fit to view">⤢</button>
        <button className={btnClass} onClick={() => setShowLegend(v => !v)} title="Toggle legend">?</button>
      </div>

      {/* Quick stats */}
      <div className="absolute top-2 right-2 text-[10px] text-gray-400 bg-gray-800/70 rounded px-2 py-1">
        {nodes.length} step(s){busiest ? ` · busiest: ${busiest.name} (×${busiest.count})` : ''}
        {errorCount > 0 ? ` · ${errorCount} with errors` : ''}
      </div>

      {showLegend && (
        <div className="absolute top-2 left-2 text-[10px] text-gray-300 bg-gray-800/90 rounded-lg px-3 py-2 ring-1 ring-white/10 space-y-1">
          {LANES.filter(l => activeLanes.some(a => a.role === l.role)).map(l => (
            <div key={l.role} className="flex items-center gap-1.5">
              <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: l.color }} />
              {l.label}
            </div>
          ))}
          <div className="flex items-center gap-1.5 pt-1 border-t border-white/10">
            <span className="inline-block w-2.5 h-2.5 rounded-full border border-dashed border-gray-300" />
            Trace entry point
          </div>
          <div className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full border-2" style={{ borderColor: '#f59e0b' }} />
            Elevated error rate (&gt;2%, 20+ calls)
          </div>
          <div className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full border-2" style={{ borderColor: '#f43f5e' }} />
            High error rate (&gt;10%)
          </div>
        </div>
      )}
    </div>
  )
}
