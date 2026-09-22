import api, { type ReuseStatus } from '../api'

const agentPath = (agentId: string) => `/agents/${encodeURIComponent(agentId)}`

export type AccessStatus = 'pending' | 'approved' | 'rejected' | 'revoked'
export type AccessDecision = 'approve' | 'reject' | 'revoke'

export interface AccessRequest {
  id: string
  team: string
  purpose: string
  status: AccessStatus
  requesterId: string
  requesterName: string | null
  decidedBy: string | null
  decidedAt: string | null
  decisionNote: string | null
  createdAt: string | null
}

export interface Contract {
  apiEndpoint: string | null
  endpointKind: 'missing' | 'observability' | 'app' | 'invalid'
  capabilities: string[]
  inputs: string[]
  outputs: string[]
  sla: string | null
  rateLimit: string | null
  owner: string
  ownerContact: string | null
}

export interface Integration {
  agentId: string
  contract: Contract
  gaps: string[]
  reuse: ReuseStatus
  reuseCheck: { checked: { id: string; name: string; score: number; certified: boolean }[]; justification: string | null }
  tryIt: { available: boolean; reason: string | null; url: string | null; examplePayload: Record<string, string> }
  accessRequests: AccessRequest[]
  consumers: { approvedTeams: string[]; declared: string[] }
}

export interface ContractUpdate {
  api_endpoint?: string
  capabilities?: string[]
  inputs?: string[]
  outputs?: string[]
  sla?: string
  rate_limit?: string
  owner_contact?: string
}

export interface TryItResult {
  url: string
  method: 'POST' | 'GET'
  ok: boolean
  status?: number
  contentType?: string | null
  body?: unknown
  truncated?: boolean
  location?: string | null
  error?: string
  latencyMs?: number
}

export const getIntegration = (agentId: string) =>
  api.get<Integration>(`${agentPath(agentId)}/integration`)

export const updateContract = (agentId: string, update: ContractUpdate) =>
  api.put<{ status: string; fields: string[] }>(`${agentPath(agentId)}/contract`, update)

export const requestAccess = (agentId: string, team: string, purpose: string) =>
  api.post<{ id: string; status: AccessStatus }>(`${agentPath(agentId)}/access-requests`, { team, purpose })

export const decideAccess = (agentId: string, requestId: string, decision: AccessDecision, note?: string) =>
  api.post<{ id: string; status: AccessStatus }>(
    `${agentPath(agentId)}/access-requests/${encodeURIComponent(requestId)}/decision`, { decision, note })

export const tryAgent = (agentId: string, method: 'POST' | 'GET', body: unknown) =>
  api.post<TryItResult>(`${agentPath(agentId)}/try`, { method, body })
