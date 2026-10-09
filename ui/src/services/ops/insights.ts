import api from '../api'

export type InsightKind =
  | 'review_pack' | 'agent_brief' | 'cost_root_cause' | 'duplicates' | 'consistency'
  | 'registration_coach' | 'evidence_review' | 'trace_audit' | 'ask'
  | 'flow_explainer' | 'value_review' | 'risk_explainer'

// The tabs of the agent page that carry an insight.
export type InsightTab = 'overview' | 'diagram' | 'governance' | 'tokenomics' | 'revenue' | 'risk' | 'integrate'

export interface TabInsight {
  kind: InsightKind
  title: string
  question: string
  // Reads other people's text (documents, trace content): runs only when a person asks.
  readsContent: boolean
  insight: Insight | null
  // Written by older instructions, before the record last changed, or when the model could not be reached: rewritten on the next visit.
  stale?: boolean
  // The record changed after this was written, so it may describe what is no longer there.
  recordChangedSince?: boolean
}

// One field the registry filled in or corrected by itself, and that still stands.
export interface AutoUpdate {
  id: string
  field: string
  label: string
  isList: boolean
  from: string
  to: string
  // List fields: the entries that were added.
  added: string[]
  source: 'usage' | 'traces' | 'app_api' | 'address_pattern' | 'ai_draft' | (string & {})
  sourceLabel: string
  reason: string | null
  appliedAt: string | null
  canUndo: boolean
  undoBlockedReason: string | null
}

export interface AutoUpdates {
  // Only the updates to fields this tab shows.
  updates: AutoUpdate[]
  // It is time to read this agent's evidence again (never read, its sources changed, or a day has passed).
  due: boolean
  // That is happening right now.
  running: boolean
  checkedAt: string | null
  evidence: { realCalls?: number; tracesRead?: number; appRead?: boolean; draftUsed?: boolean; unread?: string[] } | null
  // What only a person can give and this record still lacks, worked out from the record (not written by AI).
  // suggested: a value the agent's own spans carry (agent.owner, agent.department); a person confirms it.
  needsPerson: { key: string; label: string; why: string; suggested?: { value: string; label: string; source: string } }[]
}

export interface TabInsights {
  agentId: string
  tab: InsightTab
  insights: TabInsight[]
  // The owner has switched on reading of this agent's trace text.
  traceTextAllowed: boolean
  autoUpdates: AutoUpdates
}

export interface InsightFinding {
  title: string
  detail: string
  whyItMatters: string
  // Records this finding rests on ("risk:<agent>:<id>"); labels are in Insight.refs.
  refs: string[]
  confidence: 'high' | 'medium' | 'low'
  tag: string
  // Figures in the text that no tool returned.
  unverifiedFigures: string[]
}

export interface Insight {
  id: string
  kind: InsightKind
  title: string
  agentId: string | null
  subject: string | null
  // ok | unavailable (model or Phoenix not reachable) | nothing_to_read | error
  status: 'ok' | 'unavailable' | 'nothing_to_read' | 'error'
  output: { summary: string; findings: InsightFinding[]; notDetermined: string[]; summaryUnverifiedFigures?: string[] } | null
  refs: Record<string, string>
  toolsUsed: string[]
  checks: Record<string, number | string>
  model: string | null
  promptVersion: string | null
  steps: number
  durationMs: number
  createdAt: string | null
  tags: Record<string, string>
  feedback: { verdict: 'useful' | 'not_useful'; note: string | null } | null
}

export interface DraftRegistration {
  name: string
  description: string
  business_outcome: string
  capabilities: string[]
  ai_type: string
  owner_recorded: boolean
  value_amount: number
  inputs: string[]
  outputs: string[]
  model_name: string
}

// An investigation reads several records and calls the model more than once.
const RUN_TIMEOUT_MS = 180_000

export const getTabInsights = (agentId: string, tab: InsightTab) =>
  api.get<TabInsights>(`/agents/${encodeURIComponent(agentId)}/insights`, { params: { tab } })
export const getLatestInsight = (agentId: string, kind: InsightKind) =>
  api.get<{ insight: Insight | null }>(`/agents/${encodeURIComponent(agentId)}/insights/${kind}`)
export const runInsight = (agentId: string, kind: InsightKind, subject?: string) =>
  api.post<Insight>(`/agents/${encodeURIComponent(agentId)}/insights/${kind}/run`, { subject: subject ?? null }, { timeout: RUN_TIMEOUT_MS })
export const runDraftInsight = (kind: 'registration_coach' | 'duplicates', draft: DraftRegistration) =>
  api.post<Insight>(`/insights/draft/${kind}`, draft, { timeout: RUN_TIMEOUT_MS })
export const askRegistry = (question: string) =>
  api.post<Insight>('/insights/ask', { question }, { timeout: RUN_TIMEOUT_MS })
export const sendInsightFeedback = (insightId: string, verdict: 'useful' | 'not_useful', note?: string) =>
  api.post(`/insights/${insightId}/feedback`, { verdict, note: note ?? null })
// Puts back what was there before one automatic update. The registry then leaves that field to people.
export const undoAutoUpdate = (agentId: string, updateId: string) =>
  api.post(`/agents/${encodeURIComponent(agentId)}/auto-updates/${encodeURIComponent(updateId)}/undo`, null, { timeout: 60_000 })

export interface ContentAuditState { agentId: string; enabled: boolean; enabledBy: string | null; enabledAt: string | null; sampleSize: number }
export const getContentAudit = (agentId: string) => api.get<ContentAuditState>(`/agents/${encodeURIComponent(agentId)}/content-audit`)
export const setContentAudit = (agentId: string, enabled: boolean) =>
  api.put(`/agents/${encodeURIComponent(agentId)}/content-audit`, { enabled })
