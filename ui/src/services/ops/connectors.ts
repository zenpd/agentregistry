import api from '../api'

export type ConnectorKind = 'langfuse' | 'github' | 'azure' | 'assureai'
export interface ConnectorRow {
  id: string; kind: ConnectorKind; kindLabel: string; label: string; settings: Record<string, unknown>
  secretSet: string[]; enabled: boolean; lastSyncAt: string | null; lastStatus: string | null; lastMessage: string | null; lastFound: number
}
export interface FindingRow {
  id: string; kind: 'trace_project' | 'code_repo' | 'cloud_deployment' | 'cloud_agent'; name: string; url: string | null
  details: Record<string, any>; state: 'new' | 'dismissed' | 'linked'; dismissReason: string | null; linkedAgentId: string | null
  firstSeenAt: string | null; lastSeenAt: string | null; connectorId: string; connector: { kind: ConnectorKind; label: string } | null
  matches?: { agentId: string; name: string; confidence: 'high' | 'medium' | 'low'; reason: string }[]
}

export const listConnectors = () => api.get<{ kinds: { kind: ConnectorKind; label: string; secretKeys: string[] }[]; connectors: ConnectorRow[] }>('/connectors')
export const createConnector = (body: { kind: ConnectorKind; label: string; settings: Record<string, unknown>; secret: Record<string, string> }) =>
  api.post<ConnectorRow>('/connectors', body)
export const updateConnector = (id: string, body: Partial<{ label: string; settings: Record<string, unknown>; secret: Record<string, string>; enabled: boolean }>) =>
  api.put<ConnectorRow>(`/connectors/${encodeURIComponent(id)}`, body)
export const deleteConnector = (id: string) => api.delete(`/connectors/${encodeURIComponent(id)}`)
export const testConnector = (id: string) => api.post<{ ok: boolean; status: string; message: string }>(`/connectors/${encodeURIComponent(id)}/test`, null, { timeout: 120_000 })
export const syncConnector = (id: string) => api.post<{ status: string; message: string; found: number }>(`/connectors/${encodeURIComponent(id)}/sync`, null, { timeout: 300_000 })
export const getFindings = () => api.get<{ findings: FindingRow[]; summary: { new: number; dismissed: number; linked: number } }>('/connectors/findings')
export const dismissFinding = (id: string, reason: string) => api.post(`/connectors/findings/${encodeURIComponent(id)}/dismiss`, { reason })
export const restoreFinding = (id: string) => api.post(`/connectors/findings/${encodeURIComponent(id)}/restore`)
export const linkFinding = (id: string, agentId: string) => api.post<{ status: string; agentName: string }>(`/connectors/findings/${encodeURIComponent(id)}/link`, { agentId })
export const findingPrefill = (id: string) => api.get<{ findingId: string; fields: Record<string, string | string[]>; sources: Record<string, string> }>(`/connectors/findings/${encodeURIComponent(id)}/prefill`)
