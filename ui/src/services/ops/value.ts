import api from '../api'

// Value with a method and a finance check, measured outcomes, the model what-if,
// usage typed in for agents without tracing, spend review, scenario, scorecard.

const a = (id: string) => `/agents/${encodeURIComponent(id)}`

export type ValueState = 'none' | 'declared' | 'attested' | 'adjusted' | 'stale'
export interface Attestation {
  id: string; status: 'attested' | 'adjusted'; declaredCents: number; declaredMethod: string | null
  attestedCents: number; note: string; attestedBy: string | null; attestedAt: string
}
export interface ValueView {
  declaredCents: number
  method: string | null
  methodLabel: string | null
  // False when the method is only inferred from the older value type or hours saved.
  methodSet: boolean
  basis: string | null
  valueType: string | null
  hoursSavedMonthly: number
  hourlyRateCents: number
  timeSavedCents: number
  state: { state: ValueState; cents: number; label: string }
  attestations: Attestation[]
  methods: { value: string; label: string; help: string }[]
  canAttest: boolean
}
export const getValue = (id: string) => api.get<ValueView>(`${a(id)}/value`)
export const declareValue = (id: string, body: { method: string; basis: string; amountDollars?: number; hoursSavedMonthly?: number; hourlyRateCents?: number }) =>
  api.put<ValueView>(`${a(id)}/value`, body)
export const attestValue = (id: string, body: { status: 'attested' | 'adjusted'; note: string; amountDollars?: number }) =>
  api.post<ValueView>(`${a(id)}/value/attest`, body)

export interface Outcomes {
  days: number; from: string; to: string
  rows: { day: string; outcome: string; count: number; source: string }[]
  outcomes: { outcome: string; count: number; costPerOutcomeCents: number | null }[]
  costCents: number | null; tokenCostCents: number | null; infraCostCents: number; infraSource: string; tokenSource: string
}
export const getOutcomes = (id: string, days = 30) => api.get<Outcomes>(`${a(id)}/outcomes`, { params: { days } })
export const recordOutcome = (id: string, outcome: string, count: number, day?: string) =>
  api.post(`${a(id)}/outcomes`, { outcome, count, day: day || null })
export const importOutcomes = (id: string, csv: string) =>
  api.post<{ stored: number }>(`${a(id)}/outcomes/import`, csv, { headers: { 'Content-Type': 'text/csv' } })

export interface WhatIf {
  days: number; source: string; tokens: { input: number; output: number; cached: number }; currentCents: number
  modelsUsed: string[]; unpricedModels: string[]; priceChangePct: number; currentAfterChangeCents: number
  models: { model: string; cents: number; changePct: number | null }[]; caveat: string
}
export const getWhatIf = (id: string, priceChangePct = 0) => api.get<WhatIf>(`${a(id)}/model-whatif`, { params: { priceChangePct } })

export interface ManualUsageRow { day: string; model: string; calls: number; inputTokens: number; outputTokens: number }
export const getManualUsage = (id: string) => api.get<{ allowed: boolean; rows: ManualUsageRow[] }>(`${a(id)}/usage/manual`)
export const addManualUsage = (id: string, row: ManualUsageRow) => api.post(`${a(id)}/usage/manual`, row)
export const importManualUsage = (id: string, csv: string) =>
  api.post<{ stored: number }>(`${a(id)}/usage/import`, csv, { headers: { 'Content-Type': 'text/csv' } })
export const deleteManualUsage = (id: string, day: string, model: string) => api.delete(`${a(id)}/usage/manual`, { params: { day, model } })

export interface SpendReview {
  idle: { agentId: string; name: string; monthlyCents: number; text: string }[]
  duplicates: { agents: { id: string; name: string }[]; reason: string; monthlyCents: number; possibleSavingCents: number; text: string }[]
}
export const getSpendReview = () => api.get<SpendReview>('/portfolio/spend-review')

export interface Scenario {
  agents: { agentId: string; name: string; stage: string; valueCents: number; valueState: ValueState; tokenCents: number; infraCents: number; infraBasis: string }[]
  valueCents: number; costCents: number; netCents: number; attestedShare: number | null; caveat: string
  tokenCents: number; fixedHostingCents: number; fixedHostingAgents: number; fixedHostingTotalCents: number
}
export const getScenario = (ids: string[] = []) => api.get<Scenario>('/portfolio/scenario', { params: { agents: ids.join(',') } })

export const getValueSettings = () => api.get<{ buildCostCents: number | null; hourlyRateUsd: number }>('/value/settings')
export const updateValueSettings = (buildCostCents: number | null) => api.put('/value/settings', { buildCostCents })
export const scorecardPdf = (unit?: string) => api.get('/portfolio/scorecard', { params: { unit, format: 'pdf' }, responseType: 'blob' })

export const VALUE_STATE_PILL: Record<ValueState, string> = {
  none: 'bg-slate-100 text-slate-600 ring-slate-200',
  declared: 'bg-indigo-50 text-indigo-700 ring-indigo-200',
  attested: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  adjusted: 'bg-teal-50 text-teal-700 ring-teal-200',
  stale: 'bg-amber-50 text-amber-800 ring-amber-200',
}
export const VALUE_STATE_SHORT: Record<ValueState, string> = {
  none: 'Not declared', declared: 'Declared', attested: 'Attested', adjusted: 'Adjusted by finance', stale: 'Declared again, not attested',
}
