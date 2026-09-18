import api from '../api'

export type RiskCategory = 'SECURITY' | 'DATA_PRIVACY' | 'OPERATIONAL' | 'FINANCIAL' | 'COMPLIANCE' | 'REPUTATIONAL'
export type RiskSeverity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type RiskStatus = 'open' | 'acknowledged' | 'mitigating' | 'accepted' | 'resolved'
export type RiskSource = 'auto' | 'manual' | 'context'
export type RiskAction = 'acknowledge' | 'mitigate' | 'resolve' | 'accept' | 'reopen' | 'update'
// ok: spans read; no_traces: linked project, nothing in the window; not_linked: no Phoenix project;
// unavailable: Phoenix could not be reached, so trace rules were skipped.
export type TraceSignals = 'ok' | 'no_traces' | 'not_linked' | 'unavailable'

export const RISK_CATEGORIES: RiskCategory[] = ['SECURITY', 'DATA_PRIVACY', 'OPERATIONAL', 'FINANCIAL', 'COMPLIANCE', 'REPUTATIONAL']
export const RISK_SEVERITIES: RiskSeverity[] = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
export const ACTIVE_STATUSES: RiskStatus[] = ['open', 'acknowledged', 'mitigating', 'accepted']

export interface RiskHistoryEntry {
  at: string
  by: string
  action: string
  note: string | null
}

export interface RiskRegisterFinding {
  id: string
  ruleId: string | null
  category: RiskCategory
  severity: RiskSeverity
  title: string
  description: string | null
  source: RiskSource | string
  status: RiskStatus
  owner: string | null
  mitigation: string | null
  dueDate: string | null
  acceptedUntil: string | null
  acceptedBy: string | null
  detectedAt: string | null
  lastDetectedAt: string | null
  resolvedAt: string | null
  history: RiskHistoryEntry[]
  overdue: boolean
}

export interface FinancialFinding {
  ruleId: string
  category: 'FINANCIAL'
  severity: RiskSeverity
  title: string
  description: string | null
  source: 'auto'
  origin: 'economics' | 'cost_anomalies' | 'waste_findings' | string
  // 'seed' marks demo rows; null when the source table does not say.
  dataSource: string | null
  sourceId: string | null
}

export interface TraceKri {
  span_count: number
  trace_count: number
  error_spans: number
  error_rate: number | null
  worst_error_span: { name: string; errors: number } | null
  pii_spans: number
  pii_traces: number
  injection_spans: number
  injection_traces: number
  p95_latency_ms: number | null
  llm_calls: number
}

export interface ReconcileCounts {
  inserted: number
  updated: number
  reopened: number
  resolved: number
  acceptanceExpired: number
  backfilled: number
  unchecked: number
}

export interface RiskScore {
  worst: RiskSeverity | null
  total: number
  countsBySeverity: Record<RiskSeverity, number>
  countsByCategory: Record<RiskCategory, number>
  overdue: number
  resolved: number
}

export interface LastRiskScan {
  runId: string
  status: string
  trigger: string
  scope: 'agent' | 'all'
  startedAt: string | null
  finishedAt: string | null
  error: string | null
  traceSignals: TraceSignals | null
  traceReason: string | null
  traceWindowDays: number
  sampleCapped: boolean | null
  kri: TraceKri | null
  blastRadius: number | null
  reconcile: ReconcileCounts | null
}

export interface AgentRisksResponse {
  agentId: string
  statusFilter: 'active' | 'all'
  findings: RiskRegisterFinding[]
  financial: FinancialFinding[]
  score: RiskScore
  lastScan: LastRiskScan | null
  phoenixLinked: boolean
  phoenixProject: string | null
  today: string
  maxAcceptanceDays: number
}

export interface RiskScanResult {
  status: 'scanned'
  runId: string | null
  scannedAt: string | null
  findingCount: number
  findings: Pick<RiskRegisterFinding, 'ruleId' | 'category' | 'severity' | 'title' | 'description' | 'source'>[]
  financial: FinancialFinding[]
  reconcile: ReconcileCounts | null
  uncheckedRules: string[]
  traceSignals: TraceSignals | null
  traceReason: string | null
  kri: TraceKri | null
  blastRadius: number | null
}

export interface RiskActionPayload {
  action: RiskAction
  owner?: string | null
  mitigation?: string | null
  dueDate?: string | null
  acceptedUntil?: string
  note?: string
}

export interface NewRiskPayload {
  category: RiskCategory
  severity: RiskSeverity
  title: string
  description?: string
  owner?: string
  dueDate?: string
}

export const getAgentRiskRegister = (agentId: string, status: 'active' | 'all' = 'active') =>
  api.get<AgentRisksResponse>(`/agents/${agentId}/risks`, { params: { status } })

// A scan reads Phoenix (up to 5,000 spans), so it can take longer than a normal request.
export const scanAgentRiskRegister = (agentId: string) =>
  api.post<RiskScanResult>(`/agents/${agentId}/risks/scan`, undefined, { timeout: 180_000 })

export const updateAgentRisk = (agentId: string, riskId: string, payload: RiskActionPayload) =>
  api.patch<RiskRegisterFinding>(`/agents/${agentId}/risks/${riskId}`, payload)

export const createAgentRisk = (agentId: string, payload: NewRiskPayload) =>
  api.post<RiskRegisterFinding>(`/agents/${agentId}/risks`, payload)
