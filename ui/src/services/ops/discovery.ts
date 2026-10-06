import api from '../api'
import type { JobRun } from './jobs'

export type Activity = 'active' | 'quiet' | 'stale' | 'none'

export interface PhoenixProjectRow {
  name: string
  state: 'new' | 'dismissed'
  activity: Activity
  lastSeen: string | null
  spanCount: number
  windowDays: number
  models: string[]
  tools: string[]
  mcpServers: string[]
  agentNames: string[]
  spanKinds: string[]
  attributeKeys: string[]
  scanError: string | null
  dismissReason: string | null
  scannedAt: string | null
}

export interface RegisteredProjectRow extends PhoenixProjectRow {
  agentId: string
  agentName: string
  stage: string
}

export interface PhoenixInbox {
  configured: boolean
  // A scan is running now (it runs in the background; the page polls until it ends).
  scanning: boolean
  // Nothing has been read from the current Phoenix yet (first use, or its address changed in Settings).
  needsScan: boolean
  lastScan: JobRun | null
  windowDays: number
  staleDays: number
  summary: { new: number; newActive: number; dismissed: number; registered: number; quiet: number }
  // Spans read per project; a count at this number means "at least".
  sampleCap: number
  inbox: PhoenixProjectRow[]
  dismissed: PhoenixProjectRow[]
  registered: RegisteredProjectRow[]
}

// Starting values for the registration form, each with where it came from.
export interface Prefill {
  fields: Record<string, string | string[]>
  sources: Record<string, string>
}

export interface PhoenixPrefill extends Prefill {
  project: string
  missing: string[]
  attributeKeys: string[]
  // An address pattern is saved in Settings, so the app can be looked for by name.
  canFindApp: boolean
}

export interface UrlPrefill extends Partial<Prefill> {
  ok: boolean
  url: string
  base: string
  usedSibling: boolean
  error?: string
  hint?: string
  card: { found: boolean; path?: string; legacyPath?: boolean; conformant?: boolean; problems?: string[] }
  openapi: { found: boolean; title?: string | null; operations?: number; status?: number }
  health: { ok: boolean; status?: number | null }
}

// The app looked for at the address pattern from Settings.
export interface FoundApp extends Partial<UrlPrefill> {
  found: boolean
  guessed?: boolean
  reason?: 'no_template' | 'no_answer'
  tried: string[]
}

// Dispatched on window after a scan or a dismissal, so the sidebar count refreshes.
export const DISCOVERY_CHANGED = 'discovery-changed'

export const getPhoenixInbox = () => api.get<PhoenixInbox>('/discovery/phoenix')
export const scanPhoenix = () => api.post<{ started: boolean; scanning: boolean }>('/discovery/phoenix/scan')
export const dismissProject = (name: string, reason: string) => api.post('/discovery/phoenix/dismiss', { name, reason })
export const restoreProject = (name: string) => api.post('/discovery/phoenix/restore', { name })
export const getPhoenixPrefill = (name: string) => api.get<PhoenixPrefill>('/discovery/phoenix/prefill', { params: { name } })
export const findApp = (name: string) => api.post<FoundApp>('/discovery/phoenix/find-app', { name })
export const prefillFromUrl = (url: string) => api.post<UrlPrefill>('/agents/prefill-url', { url })
