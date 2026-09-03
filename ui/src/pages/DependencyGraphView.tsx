import { useState, useEffect } from 'react'
import { getGraph, type GraphNode, type GraphEdge } from '../services/api'

export default function DependencyGraphView() {
  const [nodes, setNodes] = useState<GraphNode[]>([])
  const [edges, setEdges] = useState<GraphEdge[]>([])
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { fetchData() }, [])

  async function fetchData() {
    try {
      setLoading(true)
      const resp = await getGraph()
      setNodes(resp.data.nodes)
      setEdges(resp.data.edges)
      setError(null)
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Failed to fetch')
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="p-8 text-center text-gray-500">Loading...</div>
  if (error) return <div className="p-8 text-center text-red-500">Error: {error}</div>

  // Simple SVG layout
  const agentNodes = nodes.filter(n => n.type === 'agent')
  const systemNodes = nodes.filter(n => n.type !== 'agent')

  const getNodePosition = (node: GraphNode, index: number, total: number) => {
    const cx = 400
    const cy = 300
    const radius = 200
    const angle = (2 * Math.PI * index) / total - Math.PI / 2
    return {
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Dependency Graph</h1>

      <div className="grid grid-cols-3 gap-4">
        {/* Graph Visualization */}
        <div className="col-span-2 bg-white rounded-lg border p-4">
          <svg viewBox="0 0 800 600" className="w-full h-96">
            {/* Edges */}
            {edges.map((edge, i) => {
              const fromNode = nodes.find(n => n.id === edge.from)
              const toNode = nodes.find(n => n.id === edge.to)
              if (!fromNode || !toNode) return null
              const fromIdx = agentNodes.indexOf(fromNode)
              const toIdx = agentNodes.indexOf(toNode)
              const fromPos = getNodePosition(fromNode, fromIdx, agentNodes.length || 1)
              const toPos = getNodePosition(toNode, toIdx >= 0 ? toIdx : 0, agentNodes.length || 1)
              return (
                <line
                  key={i}
                  x1={fromPos.x}
                  y1={fromPos.y}
                  x2={toPos.x}
                  y2={toPos.y}
                  stroke="#d1d5db"
                  strokeWidth="1"
                />
              )
            })}
            {/* Agent Nodes */}
            {agentNodes.map((node, i) => {
              const pos = getNodePosition(node, i, agentNodes.length)
              const isSelected = selectedNode?.id === node.id
              return (
                <g key={node.id} onClick={() => setSelectedNode(node)} className="cursor-pointer">
                  <circle
                    cx={pos.x}
                    cy={pos.y}
                    r={isSelected ? 20 : 15}
                    fill={isSelected ? '#3b82f6' : '#3DDBD9'}
                    stroke={isSelected ? '#1d4ed8' : '#0d9488'}
                    strokeWidth="2"
                  />
                  <text x={pos.x} y={pos.y + 30} textAnchor="middle" className="text-xs fill-gray-600">
                    {node.name?.substring(0, 15)}
                  </text>
                </g>
              )
            })}
          </svg>
        </div>

        {/* Node Details */}
        <div className="bg-white rounded-lg border p-4">
          {selectedNode ? (
            <div>
              <h3 className="font-semibold">{selectedNode.name}</h3>
              <div className="text-sm text-gray-500">Type: {selectedNode.type}</div>
              {selectedNode.stage && <div className="text-sm text-gray-500">Stage: {selectedNode.stage}</div>}
              <div className="mt-4">
                <h4 className="text-sm font-semibold">Dependencies</h4>
                <ul className="text-sm space-y-1 mt-2">
                  {edges.filter(e => e.from === selectedNode.id).map(e => {
                    const target = nodes.find(n => n.id === e.to)
                    return <li key={e.to} className="text-blue-600">→ {target?.name || e.to}</li>
                  })}
                </ul>
              </div>
              <div className="mt-4">
                <h4 className="text-sm font-semibold">Consumers</h4>
                <ul className="text-sm space-y-1 mt-2">
                  {edges.filter(e => e.to === selectedNode.id).map(e => {
                    const source = nodes.find(n => n.id === e.from)
                    return <li key={e.from} className="text-green-600">← {source?.name || e.from}</li>
                  })}
                </ul>
              </div>
            </div>
          ) : (
            <div className="text-gray-400 text-sm">Click a node to see details</div>
          )}
        </div>
      </div>
    </div>
  )
}
