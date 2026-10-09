import api from '../api'

// Who really uses an agent, reuse figures, programme health, search gaps,
// starting from a certified agent, and the chargeback split.

const a = (id: string) => `/agents/${encodeURIComponent(id)}`

export interface ConsumerRow {
  name: string
  kind: 'team' | 'agent'
  approved: boolean
  declared: boolean
  seen: boolean
  calls: number | null
  firstSeen: string | null
  lastSeen: string | null
  approvedAt: string | null
  callerAgentId?: string | null
  status: 'both' | 'approved_not_calling' | 'calling_not_approved' | 'declared_only'
  statusText: string
}
export interface Consumers {
  consumers: ConsumerRow[]
  approvedNotCalling: string[]
  callingNotApproved: string[]
  // The span attribute a calling team sets to be recognised.
  attribute: string
  linked: boolean
  observedAt: string | null
  buildsAvoided: number
  medianDaysToFirstCall: number | null
  startedFrom: { id: string; name: string } | null
}
export const getConsumers = (id: string) => api.get<Consumers>(`${a(id)}/consumers`)
export const observeConsumers = (id: string) => api.post<{ status: string; summary?: Record<string, unknown>; error?: string | null }>(`${a(id)}/consumers/observe`)

export interface ReuseSummary {
  productionAgents: number; reusedAgents: number; reuseRate: number | null
  buildsAvoided: number; medianDaysToFirstCall: number | null; firstCallsMeasured: number
}
export interface ProgrammeHealth {
  // The rows each score is counted from.
  behind: {
    notRegistered: { phoenixProjects: string[]; connectorFindings: number }
    ownerPerson: { agentId: string; name: string; owner: string | null; backup: boolean }[]
    ownerNameOnly: { agentId: string; name: string; owner: string | null }[]
    ownerNone: { agentId: string; name: string; owner: string | null }[]
    decisions: { agentId: string; name: string; review: string; decision: string; submitted: string; decided: string; days: number }[]
    productionAgents: { agentId: string; name: string; teams: number }[]
  }
  known: { registered: number; foundNotRegistered: number; share: number | null; text: string }
  owners: { total: number; person: number; nameOnly: number; none: number; withBackup: number; share: number | null }
  approvalSpeed: { medianDays: number | null; decisions: number; days: number; text: string }
  overdueReviews: { count: number; slaDays: number; items: { agentId: string; agentName: string; gate: string; days: number }[] }
  reuse: ReuseSummary
  reuseByUnit: (ReuseSummary & { unit: string })[]
  reuseSavings: { buildCostCents: number | null; cents: number | null; text: string }
  searchGaps: { term: string; times: number; people: number; lastAt: string }[]
}
export const getProgrammeHealth = () => api.get<ProgrammeHealth>('/portfolio/health')

export const getAgentTemplate = (id: string) => api.get<{ agentId: string; name: string; fields: Record<string, unknown> }>(`${a(id)}/template`)

export interface ChargebackShare { payer: string; share: number; cents: number }
export interface AgentChargeback {
  month: string; agentId: string; agentName: string; ownerUnit: string; costCents: number; costSource: string; unpriced: string[]
  basis: 'calls' | 'equal' | 'owner_only'; basisText: string; shares: ChargebackShare[]
}
export const getAgentChargeback = (id: string, month?: string) => api.get<AgentChargeback>(`${a(id)}/chargeback`, { params: { month } })
export const getPortfolioChargeback = (month?: string) =>
  api.get<{ month: string; agents: Omit<AgentChargeback, 'month'>[]; payers: { payer: string; cents: number }[] }>('/portfolio/chargeback', { params: { month } })
export const chargebackCsvUrl = (month: string) => `/api/v1/portfolio/chargeback?format=csv&month=${encodeURIComponent(month)}`
