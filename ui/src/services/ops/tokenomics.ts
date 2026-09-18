import api from '../api'

export type UsageSource = 'phoenix' | 'seed' | 'none'

// ok | partial come from a completed read; the rest mean Phoenix was not read.
export type UsageStatus =
  | 'ok' | 'partial' | 'unreachable' | 'auth_failed' | 'not_configured' | 'skipped' | 'error'
  | (string & {})

export type BudgetState = 'no_budget' | 'no_data' | 'on_track' | 'at_threshold' | 'over_budget'

export interface UsageTotals {
  inputTokens: number
  outputTokens: number
  cachedTokens: number
  calls: number
  runs: number
  errors: number
  // null when the agent has no usage data at all
  costCents: number | null
}

export interface DailyUsage {
  date: string
  inputTokens: number
  outputTokens: number
  cachedTokens: number
  calls: number
  runs: number
  errors: number
  costCents: number
  spike: boolean
}

export interface ModelUsage {
  model: string
  inputTokens: number
  outputTokens: number
  cachedTokens: number
  calls: number
  costCents: number
  sharePct: number
  priced: boolean
}

export interface BudgetView {
  monthlyBudgetCents: number
  alertThresholdPct: number
  budgetResetDay: number
  state: BudgetState
  usedPct: number | null
  periodStart: string
  periodEnd: string
  monthToDateCents: number | null
  projectedPeriodEndCents: number | null
  projectedOverBudget: boolean
  note: string
}

export interface CostForecast {
  status: 'ok' | 'insufficient_data'
  method: string
  minDays: number
  daysWithUsage: number
  dailySlopeCents: number | null
  months: { month: number; projectedCents: number }[]
}

export type CostAnomalyType =
  | 'spend_spike' | 'budget_threshold' | 'over_budget' | 'cost_per_call_jump'
  | 'unpriced_model' | 'undeclared_model' | 'error_burn'
  | (string & {})

export interface CostAnomaly {
  id: string
  type: CostAnomalyType
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | (string & {})
  detectedAt: string | null
  details: Record<string, any>
}

export interface LastRefresh {
  status: UsageStatus
  reason: string | null
  truncated: boolean
  days: number | null
  at: string | null
  trigger: string
}

export interface AnomalyCostShare {
  pct: number
  band: 'green' | 'yellow' | 'red'
  impactCents: number
  evaluatedDays: number
}

export interface Tokenomics {
  agentId: string
  linked: boolean
  phoenixProject: string | null
  declaredModel: string | null
  source: UsageSource
  lastIngestedAt: string | null
  lastRefresh: LastRefresh | null
  unpricedModels: string[]
  currency: 'USD'
  days: number
  windowStart: string
  windowEnd: string
  totals: UsageTotals
  monthToDateCents: number | null
  projectedPeriodEndCents: number | null
  costPerCallCents: number | null
  budget: BudgetView
  daily: DailyUsage[]
  byModel: ModelUsage[]
  forecast: CostForecast
  anomalyCostShare: AnomalyCostShare | null
  anomalies: CostAnomaly[]
}

export interface UsageRefreshResult {
  agentId: string
  status: 'ok' | 'partial' | 'error' | 'skipped'
  usage: {
    status: UsageStatus
    reason: string | null
    days: number | null
    rows: number
    calls: number
    truncated: boolean
    unpricedModels: string[]
  }
  ingestion: { status: string; locked?: boolean; reason?: string; runId: string | null }
  rollup: { status: string; locked?: boolean; reason?: string; runId: string | null }
}

export interface BudgetUpdate {
  monthlyBudgetCents?: number
  alertThresholdPct?: number
  budgetResetDay?: number
}

// The first read backfills 30 days of spans from Phoenix, which can take a minute.
const REFRESH_TIMEOUT_MS = 10 * 60_000

const agentPath = (agentId: string) => `/agents/${encodeURIComponent(agentId)}`

export const getTokenomics = (agentId: string, days = 30) =>
  api.get<Tokenomics>(`${agentPath(agentId)}/tokenomics`, { params: { days } })

export const refreshUsage = (agentId: string, days?: number) =>
  api.post<UsageRefreshResult>(`${agentPath(agentId)}/usage/refresh`, null, {
    params: days ? { days } : {},
    timeout: REFRESH_TIMEOUT_MS,
  })

export const updateBudget = (agentId: string, body: BudgetUpdate) =>
  api.put(`${agentPath(agentId)}/budget`, body)

// The resolve route lives in registry.py and is shared with the portfolio pages.
export const resolveCostAnomaly = (anomalyId: string) =>
  api.post<{ status: string }>(`/anomalies/${encodeURIComponent(anomalyId)}/resolve`)
