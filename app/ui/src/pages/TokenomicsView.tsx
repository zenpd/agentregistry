import { useState, useEffect } from 'react'
import { getAgents, getPortfolioCost, getModelPrices, getOptimizations, type Agent, type ModelPrice } from '../services/api'

export default function TokenomicsView() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [portfolioCost, setPortfolioCost] = useState<{ agentCount: number; totalValue: number } | null>(null)
  const [modelPrices, setModelPrices] = useState<ModelPrice[]>([])
  const [optimizations, setOptimizations] = useState<Record<string, unknown>[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { fetchData() }, [])

  async function fetchData() {
    try {
      setLoading(true)
      const [agentsRes, costRes, pricesRes, optRes] = await Promise.all([
        getAgents(1, 100),
        getPortfolioCost(),
        getModelPrices(),
        getOptimizations(),
      ])
      setAgents(agentsRes.data.data)
      setPortfolioCost(costRes.data)
      setModelPrices(pricesRes.data)
      setOptimizations(optRes.data)
      setError(null)
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Failed to fetch')
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="p-8 text-center text-gray-500">Loading...</div>
  if (error) return <div className="p-8 text-center text-red-500">Error: {error}</div>

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Tokenomics</h1>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-white rounded-lg border p-4">
          <div className="text-xs text-gray-500 uppercase">Agents in Production</div>
          <div className="text-2xl font-bold">{portfolioCost?.agentCount || 0}</div>
        </div>
        <div className="bg-white rounded-lg border p-4">
          <div className="text-xs text-gray-500 uppercase">Total Value/mo</div>
          <div className="text-2xl font-bold">${((portfolioCost?.totalValue || 0) / 1000).toFixed(0)}K</div>
        </div>
        <div className="bg-white rounded-lg border p-4">
          <div className="text-xs text-gray-500 uppercase">Model Types</div>
          <div className="text-2xl font-bold">{modelPrices.length}</div>
        </div>
        <div className="bg-white rounded-lg border p-4">
          <div className="text-xs text-gray-500 uppercase">Optimization Opportunities</div>
          <div className="text-2xl font-bold">{optimizations.length}</div>
        </div>
      </div>

      {/* Model Prices */}
      <div className="bg-white rounded-lg border p-4">
        <h2 className="font-semibold mb-3">Model Pricing</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b">
              <th className="pb-2">Model</th>
              <th className="pb-2">Provider</th>
              <th className="pb-2">Tier</th>
              <th className="pb-2 text-right">Input/1M</th>
              <th className="pb-2 text-right">Output/1M</th>
            </tr>
          </thead>
          <tbody>
            {modelPrices.map(p => (
              <tr key={p.modelName} className="border-b last:border-0">
                <td className="py-2 font-medium">{p.modelName}</td>
                <td className="py-2">{p.provider}</td>
                <td className="py-2">{p.tier}</td>
                <td className="py-2 text-right font-mono">${p.inputPrice.toFixed(2)}</td>
                <td className="py-2 text-right font-mono">${p.outputPrice.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Optimization Suggestions */}
      {optimizations.length > 0 && (
        <div className="bg-yellow-50 rounded-lg border border-yellow-200 p-4">
          <h2 className="font-semibold text-yellow-800 mb-3">Optimization Suggestions</h2>
          {optimizations.map((opt, i) => (
            <div key={i} className="flex items-start gap-3 py-2">
              <div className="w-2 h-2 rounded-full bg-yellow-500 mt-2" />
              <div>
                <div className="font-medium">{opt.agentName as string}</div>
                <div className="text-sm text-yellow-700">{opt.reason as string}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Per-Agent Costs */}
      <div className="bg-white rounded-lg border p-4">
        <h2 className="font-semibold mb-3">Agent Cost Estimates</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b">
              <th className="pb-2">Agent</th>
              <th className="pb-2">Model</th>
              <th className="pb-2">Stage</th>
              <th className="pb-2 text-right">Value/mo</th>
            </tr>
          </thead>
          <tbody>
            {agents.filter(a => a.stage === 'Production').map(a => (
              <tr key={a.id} className="border-b last:border-0">
                <td className="py-2 font-medium">{a.name}</td>
                <td className="py-2">{a.modelName}</td>
                <td className="py-2">{a.stage}</td>
                <td className="py-2 text-right font-mono">${(a.valueAmount / 1000).toFixed(0)}K</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
