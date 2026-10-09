import api from '../api'

// Compliance packs and coverage, evidence exports, the decision log check, the data and
// retention report, the GRC export, and incidents with stop requests.

export interface PackSummary {
  key: string; name: string; source: string; url?: string | null
  total: number; evidenced: number; missing: number; outside: number; notApplicable: number; inRegistry: number
  dates: { key: string; label: string; date: string }[]
}
export const getPacks = () => api.get<{ packs: PackSummary[]; agents: number; registry: Record<string, boolean>; meaning: string }>('/compliance/packs')

export interface ControlRow {
  id: string; title: string; applies: string; appliesText: string; outside: string | null
  evidence: string[]; status: 'evidenced' | 'missing' | 'outside' | 'not_applicable'
  agentsInScope: number; agentsMissing: number
  agents: { agentId: string; name: string; status: string; missing: string[] }[]
  registryMissing: string[]
}
export const getPack = (key: string) => api.get<PackSummary & { controls: ControlRow[] }>(`/compliance/packs/${key}`)
export const updatePackDates = (dates: Record<string, Record<string, string>>) => api.put('/compliance/dates', { dates })
export const controlEvidence = (key: string, controlId: string, format: 'csv' | 'pdf') =>
  api.get(`/compliance/packs/${key}/controls/${encodeURIComponent(controlId)}/evidence`, { params: { format }, responseType: 'blob' })
export const agentEvidencePack = (agentId: string, format: 'pdf' | 'csv') =>
  api.get(`/agents/${encodeURIComponent(agentId)}/evidence-pack`, { params: { format }, responseType: 'blob' })
export const checkExport = (sha256: string) =>
  api.get<{ found: boolean; what?: string; format?: string; exportedAt?: string; by?: string }>('/compliance/exports/check', { params: { sha256 } })

export interface ChainCheck {
  ok: boolean; entries: number; firstBroken: { seq: number; auditId: number; problem: string } | null
  unsealed: number; lastHash: string | null; checkedAt: string; sealingSince: string | null
}
export const verifyDecisionLog = () => api.get<ChainCheck>('/compliance/decision-log/verify')

export interface DataRow {
  agentId: string; name: string; unit: string; stage: string; data: string; dataKey: string | null; retention: string
  affects: string; confirmedBy: string | null; confirmedAt: string | null; tracing: boolean
}
export const getDataReport = () => api.get<{ rows: DataRow[]; summary: Record<string, number>; note: string }>('/compliance/data-report')
export const dataReportCsv = () => api.get('/compliance/data-report', { params: { format: 'csv' }, responseType: 'blob' })
export const grcExport = (tool: string, kind: string) => api.get('/compliance/grc-export', { params: { tool, kind, format: 'csv' }, responseType: 'blob' })

export interface IncidentRow {
  id: string; agentId: string; source: string; externalId: string | null; url: string | null; title: string
  severity: 'low' | 'medium' | 'high' | 'critical'; status: 'open' | 'resolved'; openedAt: string | null; resolvedAt: string | null
  resolution: string | null; createdBy: string | null
  stop: null | { requestedAt: string; requestedBy: string | null; reason: string | null; acknowledgedAt: string | null; acknowledgedBy: string | null; note: string | null }
}
const a = (id: string) => `/agents/${encodeURIComponent(id)}`
export const getIncidents = (id: string) =>
  api.get<{ incidents: IncidentRow[]; open: number; history: { at: string | null; kind: string; text: string; by: string | null }[] }>(`${a(id)}/incidents`)
export const linkIncident = (id: string, body: { title: string; url?: string; severity: string }) => api.post<IncidentRow>(`${a(id)}/incidents`, body)
export const resolveIncident = (id: string, iid: string, resolution: string) => api.post(`${a(id)}/incidents/${iid}/resolve`, { resolution })
export const requestStop = (id: string, iid: string, note: string) => api.post<IncidentRow & { told: number; toldOwners: boolean }>(`${a(id)}/incidents/${iid}/stop-request`, { note })
export const acknowledgeStop = (id: string, iid: string, note: string) => api.post(`${a(id)}/incidents/${iid}/stop-ack`, { note })

// Saves a downloaded blob under a file name.
export function saveBlob(data: Blob, name: string) {
  const url = URL.createObjectURL(data)
  const link = document.createElement('a')
  link.href = url; link.download = name; link.click()
  URL.revokeObjectURL(url)
}

export async function sha256Hex(buf: ArrayBuffer): Promise<string> {
  const d = await crypto.subtle.digest('SHA-256', buf)
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, '0')).join('')
}
