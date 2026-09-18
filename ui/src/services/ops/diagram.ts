import api from '../api'
import type { ReconstructedNode, ReconstructedEdge } from '../api'

export type SampleStatus = 'not_linked' | 'phoenix_unreachable' | 'no_traces_yet' | 'ok'

export interface SampleWindow {
  from: string | null
  to: string | null
}

interface SampleMeta {
  status: SampleStatus
  project: string | null
  reason?: string | null
  spanCount: number
  traceCount: number
  cachedAt: string | null
  fromCache: boolean
  sampleWindow: SampleWindow | null
}

export interface DiagramGraph extends SampleMeta {
  nodes: ReconstructedNode[]
  edges: ReconstructedEdge[]
  sampleLimit: number
  truncated: boolean
  orphanRate: number | null
}

export interface ObservedItem {
  name: string
  count: number
}

export type ObservedKey = 'tools' | 'mcp_servers' | 'retrievers' | 'models' | 'agents' | 'embeddings'
export type ObservedDeps = Record<ObservedKey, ObservedItem[]>

export type DeclaredField =
  | 'enterprise_systems' | 'databases' | 'knowledge_bases' | 'mcp_servers' | 'calls' | 'model_name'

export interface ConfirmedDep {
  name: string
  kind: string
  declaredAs: DeclaredField
  observedAs: ObservedKey
  observedName: string
  count: number
}

export interface DeclaredOnlyDep {
  name: string
  kind: string
  declaredAs: DeclaredField
}

export interface ObservedOnlyDep {
  name: string
  kind: string
  observedAs: ObservedKey
  count: number
}

export interface DependencyComparison {
  confirmed: ConfirmedDep[]
  declared_only: DeclaredOnlyDep[]
  observed_only: ObservedOnlyDep[]
  absenceConclusive: boolean
  minTracesForAbsence: number
}

export interface DeclaredDeps {
  enterpriseSystems: string[]
  databases: string[]
  knowledgeBases: string[]
  mcpServers: string[]
  calls: string[]
  consumers: string[]
  modelName: string | null
}

export interface BlastAgent {
  id: string
  name: string
  stage: string | null
  dept: string | null
  atRisk: boolean
  riskLevel: string | null
  hops: number | null
}

export interface BlastConsumer {
  id: string
  name: string
  hops: number
}

export interface BlastRadius {
  downstreamCount: number
  agents: BlastAgent[]
  consumers: BlastConsumer[]
  revenueAtRisk: number
  hoursAtRisk: number
  riskLevel: string | null
  depts: string[]
}

export interface UpstreamDep {
  id: string
  name: string
  registered: boolean
  stage: string | null
  atRisk: boolean | null
  riskLevel: string | null
  worstGate: string | null
}

export interface SharedResource {
  id: string
  name: string
  kind: string | null
  alsoUsedBy: number
  concentrated: boolean
}

export interface DependenciesResponse extends SampleMeta {
  declared: DeclaredDeps
  observed: ObservedDeps | null
  comparison: DependencyComparison | null
  blastRadius: BlastRadius
  upstream: UpstreamDep[]
  sharedResources: SharedResource[]
}

// Kinds the backend accepts on adopt, and the declared field each lands in.
export const ADOPT_TARGET: Record<string, string> = {
  tool: 'MCP servers',
  mcp_server: 'MCP servers',
  retriever: 'Knowledge bases',
}

export interface AdoptItem {
  name: string
  kind: string
}

export interface AdoptResponse {
  status: 'updated' | 'unchanged'
  added: { name: string; field: string }[]
  skipped: { name: string; field: string; reason: string }[]
  declared: DeclaredDeps
}

// The backend waits up to 45 s for a cold Phoenix connection.
const SAMPLE_TIMEOUT_MS = 60_000

const agentPath = (agentId: string) => `/agents/${encodeURIComponent(agentId)}`

export const getDiagramGraph = (agentId: string, refresh = false) =>
  api.get<DiagramGraph>(`${agentPath(agentId)}/reconstructed-graph`, {
    params: refresh ? { refresh: 1 } : undefined,
    timeout: SAMPLE_TIMEOUT_MS,
  })

export const getDependencies = (agentId: string, refresh = false) =>
  api.get<DependenciesResponse>(`${agentPath(agentId)}/dependencies`, {
    params: refresh ? { refresh: 1 } : undefined,
    timeout: SAMPLE_TIMEOUT_MS,
  })

export const adoptDependencies = (agentId: string, items: AdoptItem[]) =>
  api.post<AdoptResponse>(`${agentPath(agentId)}/dependencies/adopt`, { items })

// PUT /agents/{id} takes snake_case fields and silently drops unknown ones.
export const linkPhoenixProject = (agentId: string, project: string) =>
  api.put<{ status: string }>(agentPath(agentId), { phoenix_project: project })
