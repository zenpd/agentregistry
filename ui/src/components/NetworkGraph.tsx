import { useMemo } from 'react'

interface Node {
  id: string
  name: string
  type: string
  stage?: string
}

interface Edge {
  from: string
  to: string
}

interface Props {
  nodes: Node[]
  edges: Edge[]
  width?: number
  height?: number
}

export const CAT_COLORS: Record<string, string> = {
  // Declared-dependency kinds (PlatformView) — unchanged.
  agent: '#6EA8FE',
  mcp: '#8C7CF0',
  sys: '#3DDBD9',
  db: '#F0A85A',
  kb: '#57C785',
  // Lineage-diagram node kinds (AgentPage's Diagram tab, reconstructed from
  // real Phoenix traces via discovery/observed_deps.classify_span — the
  // same resolver the declared-vs-observed comparison on that tab uses).
  // Deliberately NOT raw Phoenix/OpenInference span kinds: an LLM call with
  // no tool/agent signal is plumbing, folded away rather than drawn.
  tool: '#F0A85A',
  mcp_server: '#8C7CF0',
  retriever: '#57C785',
  guardrail: '#e11d48',
}

export default function NetworkGraph({ nodes, edges, width = 500, height = 400 }: Props) {
  const cx = width / 2
  const cy = height / 2
  const radius = Math.min(width, height) / 2 - 50

  // Position nodes in a circle
  const positioned = useMemo(() => {
    return nodes.map((n, i) => {
      const angle = (i / nodes.length) * 2 * Math.PI - Math.PI / 2
      return {
        ...n,
        x: cx + Math.cos(angle) * radius,
        y: cy + Math.sin(angle) * radius,
      }
    })
  }, [nodes, cx, cy, radius])

  const nodeMap = new Map(positioned.map(n => [n.id, n]))

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <defs>
        <marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
          <path d="M0,0 L0,6 L9,3 z" fill="#6EA8FE" />
        </marker>
      </defs>

      {/* Edges */}
      {edges.map((e, i) => {
        const from = nodeMap.get(e.from)
        const to = nodeMap.get(e.to)
        if (!from || !to) return null

        const dx = to.x - from.x
        const dy = to.y - from.y
        const dist = Math.sqrt(dx * dx + dy * dy)
        const r = 22
        const sx = from.x + (dx / dist) * r
        const sy = from.y + (dy / dist) * r
        const ex = to.x - (dx / dist) * r
        const ey = to.y - (dy / dist) * r

        return (
          <line
            key={i}
            x1={sx} y1={sy}
            x2={ex} y2={ey}
            stroke="#6EA8FE"
            strokeWidth={1.6}
            opacity={0.6}
            markerEnd="url(#arrow)"
          />
        )
      })}

      {/* Nodes */}
      {positioned.map(n => (
        <g key={n.id}>
          <circle
            cx={n.x} cy={n.y} r={18}
            fill="#121C27"
            stroke={CAT_COLORS[n.type] || '#6EA8FE'}
            strokeWidth={2}
          />
          <text
            x={n.x} y={n.y + 30}
            textAnchor="middle"
            fill="#E9EEF3"
            fontSize={10}
            fontFamily="Inter"
          >
            {n.name.slice(0, 14)}
          </text>
        </g>
      ))}
    </svg>
  )
}