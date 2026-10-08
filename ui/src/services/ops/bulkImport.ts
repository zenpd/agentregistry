import api from '../api'

export interface ImportRow { line: number; name: string; stage: string; action: 'create' | 'skip' | 'error'; reason: string; matchedAgentId: string | null }
export const previewImport = (csv: string) => api.post<{ rows: ImportRow[]; summary: { create: number; skip: number; error: number } }>('/agents/import/preview', { csv })
export const commitImport = (csv: string) =>
  api.post<{ created: { line: number; name: string; id: string }[]; failed: { line: number; name: string; reason: string }[] }>('/agents/import/commit', { csv }, { timeout: 180_000 })
export async function downloadImportTemplate() {
  const r = await api.get('/agents/import/template.csv', { responseType: 'blob' })
  const url = URL.createObjectURL(r.data as Blob)
  const a = document.createElement('a'); a.href = url; a.download = 'agent-import-template.csv'; a.click(); URL.revokeObjectURL(url)
}
