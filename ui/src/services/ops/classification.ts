import api from '../api'

// Classification of an agent (EU AI Act category and registry risk level) and
// the approved tool list. Only a confirmed classification changes the agent.

export type Level = 'LOW' | 'MEDIUM' | 'HIGH'
export type Category = 'Minimal Risk' | 'Limited Risk' | 'High Risk' | 'Unacceptable Risk'

export interface Question {
  key: string
  kind: 'single' | 'multi' | 'bool'
  label: string
  help?: string
  options?: { value: string; label: string }[]
  // Shown only when another answer is not the given value.
  showIf?: { key: string; not: string }
}

export interface ClassificationRecord {
  id: string
  status: 'proposed' | 'confirmed' | 'replaced'
  answers: Record<string, unknown>
  suggestedCategory: Category
  suggestedRiskLevel: Level
  reasons: string[]
  category: Category | null
  riskLevel: Level | null
  note: string | null
  proposedBy: string | null
  proposedAt: string | null
  confirmedBy: string | null
  confirmedAt: string | null
}

export interface ToolRisk {
  // The highest class among the declared tools on the approved list; null when none is listed.
  class: Level | null
  source: string | null
  tools: { name: string; kind: string; class: Level | null; approvedName: string | null }[]
  unlisted: string[]
  listEmpty: boolean
}

export interface ClassificationState {
  current: ClassificationRecord | null
  pending: ClassificationRecord | null
  history: ClassificationRecord[]
  recorded: { category: string | null; riskLevel: string | null }
  toolRisk: ToolRisk
  canConfirm: boolean
}

export interface Suggestion { category: Category; riskLevel: Level; reasons: string[]; missing: string[] }

export const getClassificationQuestions = () =>
  api.get<{ questions: Question[]; categories: Category[]; levels: Level[]; minNoteWhenLower: number; confirmedBy: string }>('/classification/questions')
export const getClassification = (agentId: string) => api.get<ClassificationState>(`/agents/${encodeURIComponent(agentId)}/classification`)
export const suggestClassification = (agentId: string, answers: Record<string, unknown>) =>
  api.post<Suggestion>(`/agents/${encodeURIComponent(agentId)}/classification/suggest`, { answers })
export const saveClassification = (agentId: string, body: { answers: Record<string, unknown>; confirm: boolean; category?: string; riskLevel?: string; note?: string }) =>
  api.post<ClassificationRecord>(`/agents/${encodeURIComponent(agentId)}/classification`, body)
export const confirmClassification = (agentId: string, recordId: string, body: { category?: string; riskLevel?: string; note?: string }) =>
  api.post<ClassificationRecord>(`/agents/${encodeURIComponent(agentId)}/classification/${encodeURIComponent(recordId)}/confirm`, body)

export interface ApprovedTool {
  id: string
  name: string
  kind: string
  kindLabel: string
  riskClass: Level
  note: string | null
  addedBy: string | null
  updatedAt: string | null
  usedBy: string[]
}

export const getApprovedTools = () =>
  api.get<{ tools: ApprovedTool[]; candidates: { name: string; kind: string; agents: string[] }[]; kinds: { value: string; label: string }[]; classes: Level[] }>('/tools/approved')
export const addApprovedTool = (body: { name: string; kind: string; riskClass: Level; note?: string }) => api.post<ApprovedTool>('/tools/approved', body)
export const updateApprovedTool = (id: string, body: { riskClass?: Level; kind?: string; note?: string }) =>
  api.put<ApprovedTool>(`/tools/approved/${encodeURIComponent(id)}`, body)
export const removeApprovedTool = (id: string) => api.delete(`/tools/approved/${encodeURIComponent(id)}`)
