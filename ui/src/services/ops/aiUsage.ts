import api from '../api'

export interface AiFunctionUsage {
  function: string; label: string; enabled: boolean; runs30d: number; refused30d: number
  inputTokens30d: number; outputTokens30d: number; costCents30d: number; avgMs: number | null
  lastModel: string | null; lastPromptVersion: string | null
}
export interface AiRunRow {
  at: string | null; function: string; kind: string | null; agentId: string | null; model: string | null
  promptVersion: string | null; inputTokens: number; outputTokens: number; costCents: number | null
  durationMs: number; status: string; reason: string | null; scheduled: boolean
}
export interface AiUsage {
  monthStart: string; spentThisMonthCents: number; monthlyCapCents: number | null
  capState: 'no_cap' | 'within' | 'reached'; interactiveCeiling: number
  functions: AiFunctionUsage[]; recent: AiRunRow[]
}

export const getAiUsage = () => api.get<AiUsage>('/ai-usage')
export const setAiSwitch = (fn: string, enabled: boolean) => api.put(`/ai-usage/switches/${encodeURIComponent(fn)}`, { enabled })
export const setAiCap = (monthlyCapCents: number | null) => api.put('/ai-usage/cap', { monthlyCapCents })
export const runAiOffCheck = () =>
  api.post<{ passed: boolean; checks: { function: string; kind: string | null; passed: boolean; shows: string }[] }>('/ai-usage/off-check', null, { timeout: 120_000 })
