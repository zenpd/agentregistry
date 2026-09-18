import api from '../api'

export type GateKey = 'arb' | 'security' | 'dp'
export type UsageSource = 'phoenix' | 'seed' | 'none'
export type TelemetryStatus = 'ok' | 'demo' | 'no_usage_yet' | 'not_linked'
export type Freshness = 'fresh' | 'aging' | 'stale'
export type BudgetState = 'on_track' | 'at_threshold' | 'over_budget' | 'no_usage_data'
// ok: summary present; disabled: turned off in settings; not_configured: no Azure OpenAI
// credentials; unavailable: the call failed; not_run: no context.
export type LlmStatus = 'ok' | 'disabled' | 'not_configured' | 'unavailable' | 'not_run'

export interface RiskScore {
  worst: string | null
  openCounts: Record<string, number>
  total: number
}

export interface BudgetHeader {
  monthlyBudgetCents: number
  alertThresholdPct: number | null
  periodStart: string
  source: UsageSource
  unpriced: string[]
  state: BudgetState
  usedPct: number | null
  mtdCents: number | null
}

export interface TelemetryHeader {
  linked: boolean
  phoenixProject: string | null
  status: TelemetryStatus
  source: UsageSource
  lastIngestedAt: string | null
  lastActivityDate: string | null
  freshness: Freshness | null
}

export interface OverviewHeader {
  name: string
  stage: string
  owner: string
  dept: string | null
  riskLevel: string | null
  riskScore: RiskScore
  gates: Record<GateKey, string>
  budget: BudgetHeader | null
  telemetry: TelemetryHeader
}

export interface OverviewFacts {
  owner: string
  ownerContact: string | null
  deptId: string | null
  dept: string | null
  aiType: string | null
  function: string | null
  version: string | null
  modelName: string | null
  modelProvider: string | null
  framework: string | null
  runtime: string | null
  valueAmount: number | null
  valueType: string | null
  hoursSavedMonthly: number | null
  sla: string | null
  apiEndpoint: string | null
  apiEndpointWarning: string | null
  euAiActCategory: string | null
  phoenixProject: string | null
  description: string | null
  businessOutcome: string | null
  tags: string[]
  source: string | null
  createdAt: string | null
  updatedAt: string | null
}

export interface ContextSummary {
  present: boolean
  completenessPct: number
  sectionsPresent: string[]
  sectionsMissing: string[]
  summary: string | null
  llmStatus: LlmStatus
  suggestedRiskCount: number
  suggestedDependencyCount: number
  sizeBytes: number
  updatedAt: string | null
  versionCount: number
}

export interface AgentOverview {
  agentId: string
  header: OverviewHeader
  facts: OverviewFacts
  context: ContextSummary
}

export interface ContextVersion {
  id: string
  savedAt: string | null
  savedBy: string | null
  sizeBytes: number
  hash: string
  removed: boolean
  content?: string
}

export interface KeywordHit {
  category: string
  label: string
  keyword: string
  excerpt: string
  count: number
  negated: boolean
}

export interface RiskSuggestion {
  key: string
  category: string
  severity: string
  title: string
  description: string
  keyword: string
  excerpt: string
}

export type DeclaredField = 'enterprise_systems' | 'databases' | 'knowledge_bases' | 'mcp_servers' | 'calls'

export interface DependencySuggestion {
  name: string
  field: DeclaredField
  value: string
  excerpt: string
}

export interface ContextInsight {
  hash: string
  sections: Record<string, string>
  sectionsPresent: string[]
  sectionsMissing: string[]
  completenessPct: number
  keywordHits: KeywordHit[]
  suggestedRisks: RiskSuggestion[]
  suggestedDependencies: DependencySuggestion[]
  dismissed: string[]
  summary: string | null
  llmStatus: LlmStatus
  analysedAt: string | null
}

export interface AgentContext {
  agentId: string
  present: boolean
  content: string
  versions: ContextVersion[]
  insight: ContextInsight | null
}

export interface ContextSaveResult extends AgentContext {
  status: 'saved' | 'removed' | 'unchanged'
  version: ContextVersion | null
}

export interface ContextTemplate {
  content: string
  sections: string[]
  minSectionChars: number
}

export type SuggestionType = 'risk' | 'dependency'

export interface SuggestionActionResult {
  status: 'created' | 'added' | 'exists' | 'dismissed' | 'unchanged'
  type?: SuggestionType
  riskId?: string
  ruleId?: string
  field?: DeclaredField
  name?: string
  value?: string
  dismissed?: string
  insight: ContextInsight | null
}

export const getAgentOverview = (agentId: string) =>
  api.get<AgentOverview>(`/agents/${agentId}/overview`)

export const getAgentContext = (agentId: string) =>
  api.get<AgentContext>(`/agents/${agentId}/context`)

// An empty string removes the context; earlier versions stay in the history.
export const saveAgentContext = (agentId: string, content: string) =>
  api.put<ContextSaveResult>(`/agents/${agentId}/context`, { content })

export const getContextVersion = (agentId: string, versionId: string) =>
  api.get<ContextVersion>(`/agents/${agentId}/context/versions/${versionId}`)

export const downloadAgentContext = (agentId: string) =>
  api.get<Blob>(`/agents/${agentId}/context/download`, { responseType: 'blob' })

export const getContextTemplate = () => api.get<ContextTemplate>('/context/template')

function suggestionBody(type: SuggestionType, ref: string) {
  return type === 'risk' ? { type, key: ref } : { type, name: ref }
}

export const confirmContextSuggestion = (agentId: string, type: SuggestionType, ref: string) =>
  api.post<SuggestionActionResult>(`/agents/${agentId}/context/suggestions/confirm`, suggestionBody(type, ref))

export const dismissContextSuggestion = (agentId: string, type: SuggestionType, ref: string) =>
  api.post<SuggestionActionResult>(`/agents/${agentId}/context/suggestions/dismiss`, suggestionBody(type, ref))
