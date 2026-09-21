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

// Add auth header to every request if token exists
api.interceptors.request.use((config) => {
  const token = getAuthToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
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

export interface SessionResponse {
  session_id: string
  current_step: string
  step_status: string
  messages: { role: string; agent?: string; content: string }[]
  collected: Record<string, unknown>
}

export const checkHealth = () => api.get<{ status: string }>('/health')

export const startSession = (message: string, context?: Record<string, unknown>) =>
  api.post<SessionResponse>('/example/start', { message, context })

export const resumeSession = (session_id: string, message: string) =>
  api.post<SessionResponse>('/example/resume', { session_id, message })

export const getSession = (session_id: string) =>
  api.get<SessionResponse>(`/example/${session_id}`)

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

export const logout = () => {
  clearAuthToken()
}

export const getAgents = (page = 1, limit = 50, filters?: {
  dept?: string
  stage?: string
  type?: string
  q?: string
}) => {
  const params = new URLSearchParams({ page: String(page), limit: String(limit) })
  if (filters?.dept) params.set('dept', filters.dept)
  if (filters?.stage) params.set('stage', filters.stage)
  if (filters?.type) params.set('type', filters.type)
  if (filters?.q) params.set('q', filters.q)
  return api.get<PaginatedResponse<Agent>>(`/agents/?${params.toString()}`)
}

export const getAgent = (id: string) => api.get<Agent>(`/agents/${id}`)

export const createAgent = (agent: Partial<Agent>) =>
  api.post<{ id: string; status: string }>('/agents/', agent)

export const deleteAgent = (id: string) =>
  api.delete<{ status: string }>(`/agents/${id}`)

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
}

export const getPhoenixConfig = () => api.get<PhoenixConfigResponse>('/phoenix/config')

export const updatePhoenixConfig = (update: { endpoint: string; api_key?: string; enabled: boolean }) =>
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
  tokenCostCents: number
  estimatedInfraCostCents: number
  expenditureCents: number
  netCents: number
}


export interface PortfolioEconomics {
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

export const offboardAgent = (agentId: string, stage: number) =>
  api.post(`/agents/${agentId}/offboard`, { stage })

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
}

export interface User {
  id: string
  email: string
  name: string
  role: string
  isActive: boolean
}

export const getTaxonomy = () => api.get<Taxonomy>('/admin/taxonomy')

export const getUsers = () => api.get<User[]>('/admin/users')

export const createUser = (data: { email: string; name: string; role: string; password: string }) =>
  api.post<{ id: string; status: string }>('/admin/users', data)

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
    stage?: string
    entry?: 'production' | 'pipeline'
    model_name?: string
    value_amount?: number
    hours_saved_monthly?: number
    token_cost?: number
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
