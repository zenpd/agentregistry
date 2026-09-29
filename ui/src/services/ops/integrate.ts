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

// Set when the recorded endpoint looks like a web page or a tracing URL
// rather than the agent's own API; `where` says how to find the real one.
export interface EndpointAdvice {
  looksLike: 'frontend' | 'tracing'
  message: string
  where: string[]
  // The -be host paired with a recorded -fe web page; Try it calls it by default.
  suggestedBase: string | null
}

export interface Contract {
  apiEndpoint: string | null
  endpointKind: 'missing' | 'observability' | 'app' | 'invalid'
  endpointAdvice: EndpointAdvice | null
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
  tryIt: TryItTarget & { examplePayload: Record<string, string> }
  accessRequests: AccessRequest[]
  // Testing mode (ALLOW_SELF_APPROVAL): the requester may approve their own request.
  selfApprovalAllowed: boolean
  consumers: { approvedTeams: string[]; declared: string[] }
}

// Where Try it sends a call. url is the recorded endpoint; a chosen path is
// joined to base, which is the -be host when backendDefault is set.
export interface TryItTarget {
  available: boolean
  reason: string | null
  url: string | null
  base: string | null
  path: string | null
  backendDefault: boolean
  pathEditable: boolean
}

export interface ApiOperation {
  method: 'GET' | 'POST'
  path: string
  summary: string
  hasPathParams: boolean
  exampleBody: unknown
}

// The Try it target host's own /openapi.json, read by the registry server.
export interface ApiOperations {
  ok: boolean
  error?: string | null
  hint?: string | null
  base: string
  specUrl: string
  title: string | null
  operations: ApiOperation[]
  truncated: boolean
  otherMethods: number
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
  // What to do about the error; only sent with one.
  hint?: string
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

// path: a path on tryIt.base; omitted, the recorded endpoint is called.
export const tryAgent = (agentId: string, method: 'POST' | 'GET', body: unknown, path?: string) =>
  api.post<TryItResult>(`${agentPath(agentId)}/try`, { method, body, path })

export const getApiOperations = (agentId: string) =>
  api.get<ApiOperations>(`${agentPath(agentId)}/api-operations`)
