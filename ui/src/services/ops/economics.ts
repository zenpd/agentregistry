import api from '../api'

// Revenue & Expenditure tab (backend: api/routers/ops/economics.py).
// Every cost carries its source; an unknown figure is null, never 0.

export type TokenSource = 'phoenix' | 'seed' | 'none'
export type InfraSource = 'metered' | 'declared' | 'estimate'
export type TokenStatus = 'measured' | 'demo' | 'no_calls' | 'awaiting_ingestion' | 'no_usage_data'
export type EfficiencyRating =
  | 'efficient' | 'moderate' | 'below_average' | 'inefficient' | 'insufficient_data' | 'not_declared'

export interface TrendMonth {
  month: string
  tokenCostCents: number | null
  infraCostCents: number | null
  infraSource: InfraSource | null
  totalCostCents: number | null
  valueCents: number | null
  netCents: number | null
  roiPct: number | null
  partial: boolean
}

export interface FinancialFlag {
  rule_id: 'negative_roi_2_months' | 'idle_cost' | 'no_budget' | (string & {})
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  title: string
  description: string
  source: string
}

export interface InfraComponent {
  name: string
  costCents: number | null
  recurring: boolean
}

export interface MeteredResource {
  resourceId: string
  serviceName: string | null
  cents: number
  allocation: 'tag' | 'link' | null
}

export interface AgentEconomicsDetail {
  agentId: string
  name: string
  stage: string
  valueType: string | null
  hoursSavedMonthly: number
  hourlyRate: number
  period: { month: string; start: string; end: string; daysElapsed: number; daysInPeriod: number; basis: 'run_rate' }
  valueCents: number
  valueDeclared: boolean
  realizedValueCents: number
  tokenCostCents: number | null
  tokenSource: TokenSource
  infraCostCents: number
  infraSource: InfraSource
  totalCostCents: number
  costComplete: boolean
  netCents: number
  netAvailable: boolean
  roiPct: number | null
  paybackMonths: number | null
  oneTimeCostCents: number
  costToValuePct: number | null
  token: {
    status: TokenStatus
    pricing: 'ok' | 'partial' | 'missing'
    monthToDateCents: number | null
    projectedCents: number | null
    unpricedModels: string[]
    lastIngestedAt: string | null
    phoenixLinked: boolean
    phoenixProject: string | null
    callsLast30d: number | null
  }
  infra: {
    source: InfraSource
    cents: number
    meteredMonthToDateCents: number | null
    meteredThrough: string | null
    declaredMonthlyCents: number | null
    declaredFrom: string | null
    components: InfraComponent[]
    estimateCents: number
    byResource: MeteredResource[]
  }
  efficiencyRating: EfficiencyRating
  hasBudget: boolean
  trend: TrendMonth[]
  financialFlags: FinancialFlag[]
  // Legacy keys kept for older clients.
  revenueCents: number
  estimatedInfraCostCents: number
  expenditureCents: number
}

export const getEconomics = (agentId: string) =>
  api.get<AgentEconomicsDetail>(`/agents/${agentId}/economics`)

// snake_case: the endpoint's original contract.
export interface CostPerOutcome {
  agent_id: string
  total_cost: number
  business_outcome: number
  cost_per_outcome: number | null
  efficiency_rating: EfficiencyRating
  basis: 'monthly_run_rate'
  month: string
  tokenSource: TokenSource
  infraSource: InfraSource
  costComplete: boolean
}

export const getCostPerOutcome = (agentId: string) =>
  api.get<CostPerOutcome>(`/agents/${agentId}/cost/business-outcome`)

export interface InfraProfile {
  agentId: string
  exists: boolean
  declared: boolean
  platform: string | null
  resourceGroup: string | null
  monthlyCostCents: number | null
  components: InfraComponent[]
  effectiveFrom: string | null
  updatedBy: string | null
  updatedAt: string | null
}

export interface InfraProfileInput {
  platform: string | null
  resourceGroup: string | null
  monthlyCostCents: number | null
  components: InfraComponent[]
  effectiveFrom: string | null
}

export const getInfraProfile = (agentId: string) =>
  api.get<InfraProfile>(`/agents/${agentId}/infra-profile`)

export const saveInfraProfile = (agentId: string, body: InfraProfileInput) =>
  api.put<InfraProfile>(`/agents/${agentId}/infra-profile`, body)

export interface ResourceLink {
  id: string
  agentId: string
  resourceId: string
  sharePct: number
  kind: 'subscription' | 'resource_group' | 'resource'
  createdAt: string | null
  totalClaimedPct: number
  warning?: string | null
}

export const getResourceLinks = (agentId: string) =>
  api.get<{ agentId: string; links: ResourceLink[] }>(`/agents/${agentId}/resource-links`)

export const addResourceLink = (agentId: string, resourceId: string, sharePct: number) =>
  api.post<ResourceLink>(`/agents/${agentId}/resource-links`, { resourceId, sharePct })

export const deleteResourceLink = (agentId: string, linkId: string) =>
  api.delete<{ deleted: boolean; link: ResourceLink }>(`/agents/${agentId}/resource-links/${linkId}`)

export interface JobRunSummary {
  runId: string | null
  job: string
  agentId: string | null
  trigger: string
  status: string
  startedAt: string | null
  finishedAt: string | null
  durationMs: number | null
  summary: Record<string, any>
  error: string | null
}

export interface InfraCostStatus {
  configured: boolean
  status: 'configured' | 'not_configured'
  missing: string[]
  scope: string | null
  tagKey: string
  lastRun: JobRunSummary | null
  requiredRole: string
  setup: string[]
}

export const getInfraCostStatus = () => api.get<InfraCostStatus>('/infra-costs/status')

export const collectInfraCosts = (agentId?: string, days = 7) =>
  api.post<JobRunSummary & { locked?: boolean; reason?: string }>('/infra-costs/collect', null, {
    params: { ...(agentId ? { agentId } : {}), days },
  })
