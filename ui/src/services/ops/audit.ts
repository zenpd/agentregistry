import api from '../api'

export interface AuditRow {
  id: number
  at: string | null
  actorId: string
  actor: string
  kind: 'people' | 'machine'
  category: string
  action: string
  actionLabel: string
  entityType: string
  entityId: string | null
  entityName: string | null
  summary: string
}

export interface AuditFilter {
  kind?: 'people' | 'machine' | 'all'
  category?: string
  actor?: string
  action?: string
  entity?: string
  from?: string
  to?: string
  q?: string
}

const clean = (f: AuditFilter) => Object.fromEntries(Object.entries(f).filter(([, v]) => v))

export const getAuditTrail = (f: AuditFilter, beforeId?: number | null) =>
  api.get<{ rows: AuditRow[]; total: number; nextBeforeId: number | null }>('/audit', { params: { ...clean(f), ...(beforeId ? { before_id: beforeId } : {}) } })

export const getAuditOptions = () =>
  api.get<{ actors: { id: string; label: string }[]; actions: { id: string; label: string }[]; categories: string[] }>('/audit/options')

// The export needs the sign-in header, so it is fetched and then saved as a file.
export async function downloadAuditCsv(f: AuditFilter) {
  const r = await api.get('/audit/export.csv', { params: clean(f), responseType: 'blob' })
  const name = /filename="([^"]+)"/.exec(r.headers['content-disposition'] || '')?.[1] || 'audit-trail.csv'
  const url = URL.createObjectURL(r.data as Blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}
