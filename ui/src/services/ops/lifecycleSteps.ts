import api from '../api'

// Retirement steps, versions with the version each team uses, the AssureAI
// verdict line, the tool-call share and the controls list.

const a = (id: string) => `/agents/${encodeURIComponent(id)}`

export interface RetirementStep {
  key: 'traffic' | 'consumers' | 'access' | 'stage'
  label: string
  state: 'done' | 'waiting' | 'needs_confirmation' | 'todo'
  detail: string
}
export interface Retirement {
  active: {
    id: string; status: string; reason: string; replacement: { id: string; name: string } | null
    startedBy: string | null; startedAt: string | null; steps: RetirementStep[]; canFinish: boolean
  } | null
  history: { status: string; reason: string; startedBy: string | null; startedAt: string | null; completedAt: string | null }[]
  quietDays: number
  stage: string
}
export const getRetirement = (id: string) => api.get<Retirement>(`${a(id)}/retirement`)
export const startRetirement = (id: string, reason: string, replacementAgentId?: string) =>
  api.post<Retirement>(`${a(id)}/retirement`, { reason, replacementAgentId: replacementAgentId || null })
export const confirmRetirementStep = (id: string, step: 'traffic' | 'consumers', note: string) =>
  api.post<Retirement>(`${a(id)}/retirement/confirm`, { step, note })
export const revokeForRetirement = (id: string) => api.post<Retirement>(`${a(id)}/retirement/revoke`)
export const finishRetirement = (id: string) => api.post<Retirement>(`${a(id)}/retirement/finish`)
export const cancelRetirement = (id: string, reason: string) => api.post<Retirement>(`${a(id)}/retirement/cancel`, { reason })

export interface Versions {
  current: string | null
  versions: { version: string; changelog: string; releasedBy: string | null; releasedAt: string | null; structuralChanges: string | null }[]
  // Teams with approved access, the version each uses and how far behind the latest it is.
  consumers: { requestId: string; team: string; contact: string | null; version: string | null; behind: number | null; changedSince: string | null }[]
  consumersWithoutGrant: string[]
}
export const getVersions = (id: string) => api.get<Versions>(`${a(id)}/versions`)
export const releaseVersion = (id: string, version: string, changelog: string) =>
  api.post<{ version: string; told: number }>(`${a(id)}/versions`, { version, changelog })
export const setConsumerVersion = (id: string, requestId: string, version: string) =>
  api.put(`${a(id)}/access/${encodeURIComponent(requestId)}/version`, { version })

export interface VerdictRow {
  id: string; runId: string; verdict: 'pass' | 'fail' | null; application: string | null; completedAt: string | null
  url: string | null; error: string | null; connector: string | null; recordedBy: string | null; fetchedAt: string | null
}
export interface Evidence {
  latest: VerdictRow | null
  runs: VerdictRow[]
  connectors: { id: string; label: string; enabled: boolean }[]
  requiredForProduction: boolean
  phoenixProject: string | null
}
export const getEvidence = (id: string) => api.get<Evidence>(`${a(id)}/evidence`)
export const recordAssureRun = (id: string, runId: string, connectorId?: string) =>
  api.post<VerdictRow>(`${a(id)}/evidence/assureai`, { runId, connectorId: connectorId || null })

export interface ToolCallShare {
  status: 'ok' | 'no_tool_calls' | 'no_approval' | 'not_linked' | 'no_traces_yet' | 'phoenix_unreachable'
  message?: string
  total?: number
  approved?: number
  share?: number | null
  notApproved?: { name: string; count: number }[]
  approvedSet?: string[]
  approvedAt?: string | null
  sampleWindow?: { from: string | null; to: string | null } | null
  sampleLimit?: number
  truncated?: boolean
}
export const getToolCallShare = (id: string, refresh = false) => api.get<ToolCallShare>(`${a(id)}/tool-calls`, { params: { refresh } })

export interface Control { key: string; name: string; state: 'enforced' | 'partly' | 'recorded' | 'off'; detail: string; where: string }
export const getControls = () => api.get<{ controls: Control[]; counts: Record<string, number> }>('/governance/controls')
