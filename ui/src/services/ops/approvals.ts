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
}

export interface ApprovalDiscovery {
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

export interface Approvals {
  accessRequests: ApprovalAccessRequest[]
  reviews: ApprovalReview[]
  discoveries: ApprovalDiscovery[]
  // Testing mode (ALLOW_SELF_APPROVAL): the requester may approve their own request.
  selfApprovalAllowed: boolean
  counts: { accessRequests: number; reviews: number; discoveries: number; total: number }
}

export const getApprovals = () => api.get<Approvals>('/approvals')

// Dispatched on window after a decision, so the sidebar count refreshes.
export const APPROVALS_CHANGED = 'approvals-changed'
