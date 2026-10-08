import api from '../api'

export interface ApiKeyRow {
  id: string; label: string; prefix: string; scopes: string[]; createdBy: string | null; createdAt: string | null
  expiresAt: string | null; lastUsedAt: string | null; revokedAt: string | null; active: boolean
}
export const listApiKeys = () => api.get<ApiKeyRow[]>('/admin/api-keys')
export const issueApiKey = (body: { label: string; scopes: string[]; expiresInDays?: number | null }) => api.post<ApiKeyRow & { key: string }>('/admin/api-keys', body)
export const revokeApiKey = (id: string) => api.delete<ApiKeyRow>(`/admin/api-keys/${encodeURIComponent(id)}`)
