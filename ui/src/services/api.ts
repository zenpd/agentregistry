import axios from 'axios'

// In dev, Vite proxies /api -> VITE_API_URL. In production, the nginx container
// proxies /api -> BACKEND_URL. The app always calls the relative /api/v1 base.
const api = axios.create({
  baseURL: '/api/v1',
  timeout: 90_000, // LLM chains can take 30-60s under load
})

// ── Auth token management ────────────────────────────────────────────────────

const TOKEN_KEY = 'airegistry_token'

export function setAuthToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function getAuthToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function clearAuthToken() {
  localStorage.removeItem(TOKEN_KEY)
}

// ── Demo agents ──────────────────────────────────────────────────────────────
// The seeded example agents are shown on every page, labelled Demo, so a first
// look has agents and graphs to show. The viewer can hide them with the switch in
// the top bar. The choice is kept per browser and sent on every request, so all
// pages count the same agents (backend/db/scope.py).
const INCLUDE_DEMO_KEY = 'airegistry_include_demo'

export function includingDemo(): boolean {
  try { return localStorage.getItem(INCLUDE_DEMO_KEY) !== '0' } catch { return true }
}

export function setIncludingDemo(on: boolean) {
  try { localStorage.setItem(INCLUDE_DEMO_KEY, on ? '1' : '0') } catch { /* private mode */ }
}

// demoEnabled is false when the installation turned the demo agents off (DEMO_AGENTS_ENABLED=false).
export const getScope = () => api.get<{ demoAgents: number; includingDemo: boolean; demoEnabled: boolean }>('/admin/scope')

// Add auth header to every request if token exists
api.interceptors.request.use((config) => {
  const token = getAuthToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  if (includingDemo()) config.headers['X-Include-Demo'] = '1'
  return config
})

// A 401 means the stored token is missing, invalid or expired (JWTs here are
// valid for 7 days — a browser tab left open past that, or a token from a
// stale localStorage, both land here). Every page's own error text otherwise
// dead-ends the user with no way back in; send them to a fresh login instead.
// The login POST itself is exempt — a wrong password must stay a form error.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && !error.config?.url?.includes('/auth/login')) {
      clearAuthToken()
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

// ── Bootstrap API (existing) ─────────────────────────────────────────────────

export const checkHealth = () => api.get<{ status: string }>('/health')

// ── Agent Registry API ───────────────────────────────────────────────────────

export interface Agent {
  id: string
  name: string
  slug: string
  description: string
  aiType: string
  owner: string
  ownerContact?: string
  stage: string
  dept?: string
  // Resolved department name (e.g. "Finance"); null when the agent has no
  // department or the id no longer resolves.
  deptName?: string | null
  // Set only by GET /agents/{id}; list rows carry it on RegistryAgent.
  reuse?: ReuseStatus
  version?: string
  valueAmount: number
  valueType?: string
  hoursSavedMonthly: number
  businessOutcome?: string
  enterpriseSystems: string[]
  databases: string[]
  knowledgeBases: string[]
  mcpServers: string[]
  calls: string[]
  consumers: string[]
  inputs: string[]
  outputs: string[]
  apiEndpoint?: string
  sla?: string
  tags: string[]
  modelName?: string
  riskLevel?: string
  riskNote?: string
  atRisk: boolean
  timeInStageWeeks?: number
  reviews?: Record<string, string>
  phoenixProject?: string | null
  phoenixEndpoint?: string | null
  contextMd?: string | null
  capabilities: string[]
  rateLimit?: string | null
  // A seeded example agent (hidden on every page unless demo agents are switched on).
  isDemo?: boolean
  // Archived: left out of every page, kept in the database (Settings → Demo agents brings it back).
  archivedAt?: string | null
  // Set only by GET /agents/{id}: other records linked to the same Phoenix project.
  sharedProject?: { id: string; name: string }[]
  // Where else the agent is known (set when a connector finding is linked to it).
  sourceRepo?: string | null
  cloudResourceId?: string | null
  traceConnectorId?: string | null
  ownerUserId?: string | null
  backupOwnerUserId?: string | null
}

export interface ReuseUnmet {
  code: 'stage' | 'gate_not_approved' | 'gate_expired' | 'open_high_risk'
  gate: string | null
  message: string
}

// One certification criterion, met or not; tab is the agent-page tab where
// it is resolved.
export interface ReuseCheck {
  key: 'stage' | 'arb' | 'security' | 'dp' | 'risk'
  label: string
  met: boolean
  detail: string
  tab: 'governance' | 'risk'
  status?: string
  conditions?: boolean
}

// Derived on the server from stage, governance gates and the Risk tab.
export interface ReuseStatus {
  certified: boolean
  unmet: ReuseUnmet[]
  withConditions: string[]
  checks: ReuseCheck[]
}

export interface RegistryCard {
  costPerCallCents: number | null
  source: 'phoenix' | 'langfuse' | 'seed' | 'none'
  // 'missing': nothing the agent ran on has a price, so cost is unknown.
  pricing: 'ok' | 'partial' | 'missing'
  consumerCount: number
}

// One row of the registry list: the agent plus figures computed for the card.
export interface RegistryAgent extends Agent {
  reuse: ReuseStatus
  card: RegistryCard
  matchedTerms: string[]
}

export interface SimilarAgent {
  id: string
  name: string
  stage: string
  owner: string
  description: string
  score: number
  matchedTerms: string[]
  sharedCapabilities: string[]
  sameEndpoint: boolean
  certified: boolean
}

export interface AgentCreateInput {
  name: string
  dept: string
  owner: string
  owner_contact: string
  stage: string
  ai_type: string
  description: string
  business_outcome: string
  value_amount: number
  hours_saved_monthly: number
  model_name: string
  api_endpoint: string
  sla: string
  rate_limit: string
  phoenix_project: string
  phoenix_endpoint: string
  context_md: string
  capabilities: string[]
  inputs: string[]
  outputs: string[]
  enterprise_systems: string[]
  databases: string[]
  knowledge_bases: string[]
  mcp_servers: string[]
  calls: string[]
  consumers: string[]
  reuse_justification: string
  // Required when stage is not Ideation: why the agent skips the earlier gates.
  stage_reason?: string
  version?: string
  // A certified agent whose contract this registration started from.
  started_from_agent_id?: string
}

export interface PaginationInfo {
  page: number
  limit: number
  total: number
  pages: number
}

export interface PaginatedResponse<T> {
  data: T[]
  pagination: PaginationInfo
}

export interface LoginRequest {
  email: string
  password: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  user: {
    id: string
    name: string
    email: string
    role: string
  }
}

export const login = async (email: string, password: string): Promise<LoginResponse> => {
  const resp = await api.post<LoginResponse>('/auth/login', { email, password })
  if (resp.data.access_token) {
    setAuthToken(resp.data.access_token)
  }
  return resp.data
}

export const getMe = () => api.get<{ user_id: string; role: string; name: string | null; email: string | null; accountRole: string | null; perms: string[]; gates: string[]; rbac: boolean; awayUntil: string | null; deputyUserId: string | null }>('/auth/me')

// Away until a date (empty clears it), with a deputy who receives your review notices meanwhile.
export const setMyAway = (awayUntil: string | null, deputyUserId: string | null) =>
  api.put<{ awayUntil: string | null; deputyUserId: string | null }>('/auth/me/away', { awayUntil, deputyUserId })

// The accountable owner (a person with an account) and a backup owner who takes
// over if the owner's account is deactivated. An empty string clears a field.
export const setOwnership = (agentId: string, body: { ownerUserId?: string; backupOwnerUserId?: string; ownerText?: string; reason?: string }) =>
  api.put<{ owner: string; ownerUserId: string | null; backupOwnerUserId: string | null }>(`/agents/${encodeURIComponent(agentId)}/ownership`, body)

export const logout = () => {
  clearAuthToken()
}

export const getAgents = (page = 1, limit = 50, filters?: {
  dept?: string
  stage?: string
  type?: string
  q?: string
  certified?: boolean
}) => {
  const params = new URLSearchParams({ page: String(page), limit: String(limit) })
  if (filters?.dept) params.set('dept', filters.dept)
  if (filters?.stage) params.set('stage', filters.stage)
  if (filters?.type) params.set('type', filters.type)
  if (filters?.q) params.set('q', filters.q)
  if (filters?.certified) params.set('certified', 'true')
  return api.get<PaginatedResponse<RegistryAgent>>(`/agents/?${params.toString()}`)
}

export const getAgent = (id: string) => api.get<Agent>(`/agents/${id}`)

export const createAgent = (agent: AgentCreateInput) =>
  api.post<{ id: string; status: string }>('/agents/', agent)

export const findSimilarAgents = (query: {
  name: string; description: string; business_outcome: string; capabilities: string[]; api_endpoint: string
}) => api.post<{ similar: SimilarAgent[] }>('/agents/similar', query)

export const deleteAgent = (id: string) =>
  api.delete<{ status: string }>(`/agents/${encodeURIComponent(id)}`)

// Profile fields only: stage changes go through the Governance tab's gates,
// and the contract is edited on the Integrate tab.
export interface AgentProfileUpdate {
  name: string
  description: string
  owner: string
  owner_contact: string
  dept: string
  ai_type: string
  business_outcome: string
  value_amount: number
  hours_saved_monthly: number
}

export const updateAgent = (id: string, update: Partial<AgentProfileUpdate>) =>
  api.put<{ status: string }>(`/agents/${encodeURIComponent(id)}`, update)

// ── Phoenix discovery — reconstructing an onboarded app's real dependency
// diagram from its actual traces, not its hand-declared calls/consumers ──────

export interface PhoenixProjectsResponse {
  reachable: boolean
  reason?: string
  projects: string[]
}

export const getPhoenixProjects = () =>
  api.get<PhoenixProjectsResponse>('/phoenix/projects')

// role/depth/isRoot classify a node for the trajectory layout — role picks
// its lane (step/model/tool/resource/check/other), depth its left-to-right
// column (longest path from a root), isRoot whether it starts the trace.
export interface ReconstructedNode {
  id: string
  name: string
  kind: string
  count: number
  errorCount: number
  avgLatencyMs: number | null
  role: string
  depth: number
  isRoot: boolean
}

export interface ReconstructedEdge {
  from: string
  to: string
  // 'calls': a true nested span call (agent → tool/sub-step). 'sequence':
  // same trace, no span-nesting reaches between them (e.g. a supervisor's
  // routing handoff) — recovered from real start_time ordering instead.
  kind: 'calls' | 'sequence'
  count: number
}

// ── Phoenix config (Settings tab — the "common" tracing endpoint) ───────────

export interface PhoenixConfigResponse {
  endpoint: string
  apiKeySet: boolean
  enabled: boolean
  source: 'saved' | 'env_default'
  // Where apps are hosted, with {project} for the Phoenix project name.
  appUrlTemplate: string
}

export const getPhoenixConfig = () => api.get<PhoenixConfigResponse>('/phoenix/config')

export const updatePhoenixConfig = (update: { endpoint: string; api_key?: string; enabled: boolean; app_url_template?: string }) =>
  api.put<{ status: string }>('/phoenix/config', update)

// ── Risk register (governance/risk_categories.py) ────────────────────────────

export interface RiskSummary {
  totalFindings: number
  byCategory: { category: string; label: string; count: number }[]
  severities: string[]
  heatmap: { category: string; label: string; counts: Record<string, number> }[]
}

export const getRiskSummary = () => api.get<RiskSummary>('/governance/risks/summary')

// ── Economics (governance/economics.py) — revenue vs expenditure ────────────

export interface AgentEconomics {
  agentId: string
  stage: string
  revenueCents: number
  // null when there is no usage data, so the token cost is unknown.
  tokenCostCents: number | null
  estimatedInfraCostCents: number
  expenditureCents: number
  netCents: number
  // Per month: declared value, and token + infra cost with where each came from.
  valueCents?: number
  totalCostCents?: number
  infraCostCents?: number
  tokenSource?: string
  infraSource?: string
  costComplete?: boolean
  // Which figure the value is: declared, attested or adjusted by finance, or declared again (stale).
  valueState?: 'none' | 'declared' | 'attested' | 'adjusted' | 'stale'
  valueMethodLabel?: string | null
}


export interface PortfolioEconomics {
  // Declared value of every agent, all stages, per month.
  totalRevenueCents: number
  totalExpenditureCents: number
  totalNetCents: number
  agents: (AgentEconomics & { name: string })[]
}

export const getPortfolioEconomics = () => api.get<PortfolioEconomics>('/value/economics')

// ── Governance ────────────────────────────────────────────────────────────────

export interface GovernanceOverview {
  [gate: string]: Record<string, number>
}

export const getGovernanceOverview = () =>
  api.get<GovernanceOverview>('/governance/')

export interface GovernanceSummary {
  requiredReviews: Record<string, string[]>   // by risk level, from Settings → Governance rules
  agents: number; cleared: number; blocked: number; inReview: number
}
export const getGovernanceSummary = () => api.get<GovernanceSummary>('/governance/summary')
// The reviews an agent's risk level requires. All three until the rules are loaded.
export const requiredReviewsOf = (s: GovernanceSummary | null, riskLevel?: string | null): string[] =>
  s?.requiredReviews[(riskLevel || 'LOW').toUpperCase()] ?? ['arb', 'security', 'dp']

export const updateGate = (agentId: string, gate: string, status: string) =>
  api.put<{ status: string }>(`/governance/agents/${agentId}/governance/${gate}`, { status })

// ── Discovery ─────────────────────────────────────────────────────────────────

export interface Discovery {
  id: string
  suspectedName: string
  suspectedDept?: string
  suspectedType?: string
  source: string
  confidence: number
  signal?: string
  status: string
  shadowAiRisk?: string
  firstSeen: string
}

export const getDiscoveries = () =>
  api.get<Discovery[]>('/discoveries/')

export const getShadowAI = () =>
  api.get<Discovery[]>('/discoveries/shadow-ai')

export const registerDiscovery = (id: string) =>
  api.post<{ status: string }>(`/discoveries/${id}/register`)

export const dismissDiscovery = (id: string) =>
  api.post<{ status: string }>(`/discoveries/${id}/dismiss`)

// ── Tokenomics ────────────────────────────────────────────────────────────────

export interface TokenSummary {
  agentId: string
  inputTokens: number
  outputTokens: number
  costCents: number
  invocations: number
}

export interface ModelPrice {
  id: string
  modelName: string
  provider: string
  inputPrice: number
  outputPrice: number
  cacheReadPrice: number
  tier: string
}

export const getPortfolioCost = () =>
  api.get<{ agentCount: number; totalValue: number }>('/portfolio/cost')

export const getAgentTokens = (id: string) =>
  api.get<TokenSummary>(`/agents/${id}/tokens`)

export const getModelPrices = () =>
  api.get<ModelPrice[]>('/models/prices')

// ── Graph ─────────────────────────────────────────────────────────────────────

export interface GraphNode {
  id: string
  name: string
  type: string
  stage?: string
}

export interface GraphEdge {
  from: string
  to: string
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export const getGraph = () => api.get<GraphData>('/graph/')

export const getConcentrationRisk = () =>
  api.get<{ name: string; count: number }[]>('/graph/concentration-risk')

// ── Value & Waste ─────────────────────────────────────────────────────────────

export interface ValueSummary {
  totalAgents: number
  agentsInProduction: number
  realizedValueMonthly: number
  totalValueMonthly: number
  hoursSavedMonthly: number
  atRiskCount: number
}

export interface DeptValue {
  department: string
  agentCount: number
  totalValue: number
  hoursSaved: number
}

export const getValueSummary = () => api.get<ValueSummary>('/value/summary')

export const getValueByDepartment = () =>
  api.get<DeptValue[]>('/value/by-department')

export const getTopAgents = (limit = 5) =>
  api.get<Agent[]>(`/value/top-agents?limit=${limit}`)

export const getWasteReport = () =>
  api.get<Record<string, unknown>[]>('/waste/report')

export const getWasteSummary = () =>
  api.get<{ totalFindings: number; totalMonthlyWasteCents: number }>('/waste/summary')

export const getOptimizations = () =>
  api.get<Record<string, unknown>[]>('/optimizations')

// ── Orchestration triggers ─────────────────────────────────────────────────────

export const runGovernance = (agentId: string, orgId = 'org-default') =>
  api.post(`/orchestrations/governance/${agentId}`, { org_id: orgId })

export const runTokenomics = (agentId: string, modelName = 'GPT-5', budget = 5000) =>
  api.post(`/orchestrations/tokenomics/${agentId}`, { model_name: modelName, budget })

export const runWasteDetection = (orgId = 'org-default') =>
  api.post('/orchestrations/waste-detection', { org_id: orgId })

export const runImpact = (nodeId: string, nodeType = 'agent') =>
  api.post(`/orchestrations/impact/${nodeId}`, { node_type: nodeType })

export const runDiscovery = (orgId = 'org-default') =>
  api.post('/orchestrations/discovery', { org_id: orgId })

// ── Agent Identity ─────────────────────────────────────────────────────────────

export interface AgentIdentity {
  agent_id: string
  service_account: string
  entra_agent_id: string | null
  api_key_hash: string | null
  permissions: string[]
  revoked_at: string | null
}

export const getAgentIdentity = (agentId: string) =>
  api.get<AgentIdentity>(`/agents/${agentId}/identity`)

export const revokeAgentIdentity = (agentId: string) =>
  api.post(`/agents/${agentId}/identity/revoke`)

// ── Offboarding ────────────────────────────────────────────────────────────────

// Older offboarding notes (steps 1 to 6). The stage itself changes through the retirement steps (services/ops/retirement.ts).
export const offboardAgent = (agentId: string, stage: number) =>
  api.post(`/agents/${agentId}/offboard`, null, { params: { stage } })

export const recertifyAgent = (agentId: string) =>
  api.post(`/governance/agents/${agentId}/recertify`)

// ── Exceptions ─────────────────────────────────────────────────────────────────

export interface Exception {
  id: string
  agent_id: string
  gate: string
  reason: string
  expires_at: string
  granted_by: string
}

export const getExceptions = () =>
  api.get<Exception[]>('/governance/exceptions')

export const createException = (data: { agent_id: string; gate: string; reason: string; expires_at: string }) =>
  api.post('/governance/exceptions', data)

// ── Admin ─────────────────────────────────────────────────────────────────────

export interface Taxonomy {
  stages: string[]
  gates: string[]
  reviewStatuses: string[]
  riskLevels: string[]
  aiTypes: string[]
  // Persona roles a user can be given (recorded; enforced only with RBAC on).
  userRoles?: string[]
}

export interface User {
  id: string
  email: string
  name: string
  role: string
  isActive: boolean
  // Away until this date: review notices go to the deputy meanwhile.
  awayUntil?: string | null
  deputyUserId?: string | null
  // For an Auditor: the last day the account can sign in.
  accessUntil?: string | null
}

export const getTaxonomy = () => api.get<Taxonomy>('/admin/taxonomy')

export const getUsers = () => api.get<User[]>('/admin/users')

export const createUser = (data: { email: string; name: string; role: string; password: string; accessUntil?: string }) =>
  api.post<{ id: string; status: string }>('/admin/users', data)

export const updateUser = (id: string, data: { name?: string; role?: string; isActive?: boolean; awayUntil?: string | null; deputyUserId?: string | null; accessUntil?: string | null }) =>
  api.put<{ status: string; user: User }>(`/admin/users/${encodeURIComponent(id)}`, data)

export const resetUserPassword = (id: string, password: string) =>
  api.post<{ status: string }>(`/admin/users/${encodeURIComponent(id)}/password`, { password })

// Active people for pickers (owner, deputy); readable by everyone signed in.
export const getDirectory = () =>
  api.get<{ id: string; name: string; email: string; role: string }[]>('/admin/directory')

// ── V2 Features ──────────────────────────────────────────────────────────────

export const findDuplicates = () =>
  api.get<{ duplicates: { agent_a: { id: string; name: string; dept: string }; agent_b: { id: string; name: string; dept: string }; similarity: number; shared_endpoint: boolean; shared_systems: string[] }[]; count: number }>('/agents/duplicates')

export const getEuAiActCompliance = () =>
  api.get<{ total_agents: number; tiers: Record<string, number>; agents_by_tier: Record<string, { id: string; name: string; dept: string; ai_type: string }[]>; recommendation: string }>('/compliance/eu-ai-act')

export const getBatchProcessing = () =>
  api.get<{ batch_agents: { id: string; name: string; invocation_count: number; batch_processing: boolean; recommendation: string }[]; count: number }>('/batch-processing')

// ── Dependency Graph v2 ──────────────────────────────────────────────────────

export interface GraphNodeV2 {
  id: string
  name: string
  kind: string
  attrs: {
    dept?: string
    // Department name for display; dept is the id.
    dept_name?: string
    stage?: string
    entry?: 'production' | 'pipeline'
    model_name?: string
    value_amount?: number
    hours_saved_monthly?: number
    // null: no priced usage in the last 30 days (unpriced model, or none at
    // all) — distinct from a real $0, which never happens for this field.
    token_cost?: number | null
    at_risk?: boolean
    risk_level?: string
    worst_gate?: string
    ref?: string
  }
}

export interface GraphEdgeV2 {
  from: string
  to: string
  type: 'CALLS' | 'CONSUMED_BY' | 'ACCESSES' | 'USES_KB' | 'USES_MCP'
}

export interface GraphLegendItem {
  kind: string
  label: string
  count: number
  color: string
}

export interface GraphV2Response {
  nodes: GraphNodeV2[]
  edges: GraphEdgeV2[]
  legend: GraphLegendItem[]
  stats: {
    agents: number
    nodes: number
    edges: number
    cross_agent_edges: number
    cross_dept_edges: number
    orphan_agents: number
    orphan_agent_ids: string[]
    production_agents: number
  }
}

export const getGraphV2 = () => api.get<GraphV2Response>('/graph/v2')

// ── Cobol-style pyvis/vis-network graph view ─────────────────────────────────

export interface GraphViewLegend {
  key: string
  label: string
  color: string
  border: string
  shape: string
  count: number
}

export interface GraphViewResponse {
  html: string
  node_count: number
  edge_count: number
  entry_point_count: number
  group_colors: Record<string, string>
  legend: GraphViewLegend[]
}

export const getGraphView = () => api.get<GraphViewResponse>('/graph/view')

export const getImpact = (nodeId: string) =>
  api.get<{
    status: string
    target_name: string
    affected_node_ids: string[]
    affected_edge_keys: string[]
    revenue_at_risk: number
    efficiency_at_risk: number
    blast_radius_depts: string[]
    risk_level: string
    mitigation_suggestions: string[]
  }>(`/graph/impact/${nodeId}`)

export default api

// Step-by-step Phoenix check: connected, not_configured, blocked_address,
// unreachable, not_phoenix, unauthorized or project_not_found.
export interface ConnectionTestResult { endpoint: string | null; state: string; message: string; version?: string | null; projectCount?: number }
export const testPhoenixConnection = (body: { endpoint?: string; apiKey?: string; project?: string } = {}) =>
  api.post<ConnectionTestResult>('/phoenix/test-connection', body, { timeout: 60_000 })
