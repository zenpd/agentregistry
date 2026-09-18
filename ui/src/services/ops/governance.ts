import api from '../api'

export type GateKey = 'arb' | 'security' | 'dp'
export type GateStatus = 'Not Submitted' | 'In Review' | 'Changes Requested' | 'Approved with Conditions' | 'Approved'
export type ExpiryState = 'valid' | 'expiring' | 'expired' | 'n/a'
export type AutoResult = 'pass' | 'fail' | 'n/a' | 'manual'
export type Tick = 'pass' | 'fail' | 'n/a'
export type EnforcementMode = 'warn' | 'block'

export const LIFECYCLE_STAGES = ['Ideation', 'Development', 'Testing', 'Production', 'Deprecated'] as const

export interface ChecklistItem {
  id: string
  label: string
  ref: string
  auto: AutoResult
  detail: string | null
  tick: Tick | null
  // The reviewer's tick when present, otherwise the auto result ('pending' for manual items).
  result: Tick | 'pending'
}

export interface ChecklistSummary {
  total: number
  passed: number
  failed: number
  notApplicable: number
  pending: number
  complete: boolean
}

export interface EvidenceLink {
  label: string
  url: string
}

export interface GovernanceWarning {
  code: string
  message: string
  gate?: string | null
  blocking?: boolean
}

export interface GateReview {
  gate: GateKey
  label: string
  reviewerRole: string
  status: GateStatus
  reviewer: string | null
  notes: string | null
  conditions: string | null
  evidence: EvidenceLink[]
  checklist: ChecklistItem[]
  checklistSummary: ChecklistSummary
  reviewedAt: string | null
  expiresAt: string | null
  expiryState: ExpiryState
}

export interface GateUpdateResult extends GateReview {
  warnings: GovernanceWarning[]
}

export interface StageReadiness {
  target: string
  ready: boolean
  mode: EnforcementMode
  blocked: boolean
  warnings: GovernanceWarning[]
  exceptionsApplied: string[]
}

export interface GovernanceException {
  id: string
  gate: GateKey
  gateLabel: string
  reason: string
  approvedBy: string | null
  expiresAt: string | null
  createdAt: string | null
  daysLeft: number | null
}

export interface RecertificationReason {
  code: string
  gate: string | null
  message: string
}

export interface UsageSummary {
  days: number
  calls: number
  runs: number
  inputTokens: number
  outputTokens: number
  errors: number
  costCents: number
  topModel: string
}

// 'seed' means only demo rows exist; they are never used as governance evidence.
export type UsageSource = 'phoenix' | 'seed' | 'none'

export interface HistoryEntry {
  at: string | null
  actor: string
  action: 'gate_update' | 'stage_change' | 'stage_change_blocked' | 'recertify' | 'exception_create'
  gate: GateKey | null
  summary: string
}

export interface GovernanceState {
  agentId: string
  stage: string
  riskLevel: string | null
  riskTier: string
  euAiActCategory: string | null
  enforcement: EnforcementMode
  validityDays: number
  maxExceptionDays: number
  gates: GateReview[]
  exceptions: GovernanceException[]
  readiness: {
    current: string
    next: StageReadiness | null
    production: StageReadiness
  }
  recertification: { due: boolean; reasons: RecertificationReason[] }
  telemetry: { phoenixProject: string | null; usage: UsageSummary | null; usageSource: UsageSource }
  contextPresent: boolean
  history: HistoryEntry[]
}

// A body with `status` records a decision; without it, only the other fields change.
export interface GateReviewUpdate {
  status?: GateStatus
  reviewer?: string
  notes?: string
  conditions?: string
  evidence?: EvidenceLink[]
  checklist?: Record<string, Tick | null>
}

export interface DraftNotes {
  gate: GateKey
  draft: string
  llmStatus: 'ok' | 'unavailable'
  usedContext: boolean
}

export interface StageChangeResult {
  agentId: string
  from: string
  to: string
  changed: boolean
  mode: EnforcementMode
  overrideReason?: string | null
  warnings: GovernanceWarning[]
  readiness: StageReadiness
}

export interface StageBlockedDetail {
  message: string
  mode: EnforcementMode
  warnings: GovernanceWarning[]
}

export interface ExceptionCreate {
  gate: GateKey
  reason: string
  expiresAt: string
  approvedBy: string
}

const agentPath = (agentId: string) => `/agents/${encodeURIComponent(agentId)}`

// Drafting waits on the LLM, which can take a while over the VPN.
const DRAFT_TIMEOUT_MS = 150_000

export const getGovernance = (agentId: string) =>
  api.get<GovernanceState>(`${agentPath(agentId)}/governance`)

export const updateGateReview = (agentId: string, gate: GateKey, body: GateReviewUpdate) =>
  api.put<GateUpdateResult>(`${agentPath(agentId)}/governance/${gate}`, body)

export const draftReviewNotes = (agentId: string, gate: GateKey) =>
  api.post<DraftNotes>(`${agentPath(agentId)}/governance/${gate}/draft-notes`, null, { timeout: DRAFT_TIMEOUT_MS })

export const getStageReadiness = (agentId: string, target: string) =>
  api.get<StageReadiness & { agentId: string; current: string }>(`${agentPath(agentId)}/stage-readiness`, { params: { target } })

export const changeStage = (agentId: string, stage: string, overrideReason?: string) =>
  api.put<StageChangeResult>(`${agentPath(agentId)}/stage`, { stage, overrideReason: overrideReason || undefined })

export const recertifyGates = (agentId: string, reason?: string) =>
  api.post<{ status: string; gates_reset: GateKey[] }>(`${agentPath(agentId)}/recertify`, { reason: reason || undefined })

export const createGovernanceException = (agentId: string, body: ExceptionCreate) =>
  api.post<GovernanceException>(`${agentPath(agentId)}/governance/exceptions`, body)
