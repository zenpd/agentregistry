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

export const updateAgent = (id: string, updates: Partial<Agent>) =>
  api.put<{ status: string }>(`/agents/${id}`, updates)

export const deleteAgent = (id: string) =>
  api.delete<{ status: string }>(`/agents/${id}`)

export const offboardAgent = (id: string) =>
  api.post<{ status: string }>(`/agents/${id}/offboard`)

export const getAgentIdentity = (id: string) =>
  api.get<Record<string, unknown>>(`/agents/${id}/identity`)

export const revokeAgentIdentity = (id: string) =>
  api.post<{ status: string }>(`/agents/${id}/identity/revoke`)

// ── Governance ────────────────────────────────────────────────────────────────

export interface GovernanceOverview {
  [gate: string]: Record<string, number>
}

export const getGovernanceOverview = () =>
  api.get<GovernanceOverview>('/governance/')

export const updateGate = (agentId: string, gate: string, status: string) =>
  api.put<{ status: string }>(`/governance/agents/${agentId}/governance/${gate}`, { status })

export const recertifyAgent = (agentId: string) =>
  api.post<{ status: string }>(`/governance/agents/${agentId}/recertify`)

export const getExceptions = () =>
  api.get<Record<string, unknown>[]>('/governance/exceptions')

export const createException = (data: {
  agentId: string
  gate: string
  reason: string
  expiresAt: string
  approvedBy?: string
}) => api.post<{ id: string; status: string }>('/governance/exceptions', data)

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

export const getAnomalies = () =>
  api.get<Record<string, unknown>[]>('/anomalies')

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

export default api
