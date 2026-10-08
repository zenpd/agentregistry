import api from '../api'

export interface ApprovalAccessRequest {
  id: string
  agentId: string
  agentName: string
  agentStage: string | null
  // Whether the requested agent is certified for reuse.
  certified: boolean
  team: string
  purpose: string
  requesterId: string
  requesterName: string | null
  createdAt: string | null
  // Raised by the current user, who therefore cannot approve it.
  mine: boolean
}

export interface ApprovalReview {
  agentId: string
  agentName: string
  agentStage: string
  gate: 'arb' | 'security' | 'dp'
  gateLabel: string
  reviewerRole: string | null
  reviewer: string | null
  since: string | null
  // Ranking: open critical findings, then open high findings, then risk tier, then the longest wait.
  criticalFindings: number
  highFindings: number
  riskTier: 'LOW' | 'MEDIUM' | 'HIGH'
  daysWaiting: number | null
  // Waiting longer than slaDays (the review target, in days).
  overdue: boolean
  slaDays: number
  // People whose role decides this gate: who is here, and who is away with their deputy.
  deciders: { available: string[]; away: { name: string; until: string; deputy: string | null }[] }
}

export interface ApprovalDiscovery {
  agentId: string | null
  id: string
  suspectedName: string
  suspectedDept: string | null
  suspectedType: string | null
  source: string
  confidence: number
  signal: string | null
  shadowAiRisk: string | null
  firstSeen: string | null
}

// A classification proposed by an owner, waiting for an Architect Steward,
// Data Protection Officer or Registry Admin to confirm it.
export interface ApprovalClassification {
  id: string
  agentId: string
  agentName: string
  category: string
  riskLevel: string
  proposedBy: string | null
  since: string | null
  daysWaiting: number | null
}

export interface Approvals {
  accessRequests: ApprovalAccessRequest[]
  reviews: ApprovalReview[]
  classifications: ApprovalClassification[]
  discoveries: ApprovalDiscovery[]
  // Testing mode (ALLOW_SELF_APPROVAL): the requester may approve their own request.
  selfApprovalAllowed: boolean
  counts: { accessRequests: number; reviews: number; classifications: number; discoveries: number; total: number }
}

export const getApprovals = () => api.get<Approvals>('/approvals')

// Dispatched on window after a decision, so the sidebar count refreshes.
export const APPROVALS_CHANGED = 'approvals-changed'

export interface DecisionRow {
  at: string | null
  actor: string
  action: string
  agentId: string | null
  agentName: string | null
  summary: string
}

// Decisions already made (gates, access, waivers, stage changes), newest first.
export const getApprovalHistory = (limit = 50) => api.get<{ rows: DecisionRow[] }>('/approvals/history', { params: { limit } })
