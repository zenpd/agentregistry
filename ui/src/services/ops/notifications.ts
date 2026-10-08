import api from '../api'

export interface NotificationItem { type: string; text: string; link: string | null; agentId?: string | null }
export interface AppNotification {
  id: string
  kind: string
  subject: string
  items: NotificationItem[]
  createdAt: string | null
  read: boolean
  deliveries: Record<string, { status: string; error?: string; at?: string }>
}

export const NOTIFICATIONS_CHANGED = 'ar:notifications-changed'

export const getMyNotifications = () => api.get<{ rows: AppNotification[]; unread: number }>('/notifications/mine')
export const markNotificationRead = (id: string) => api.post(`/notifications/${encodeURIComponent(id)}/read`)
export const markAllNotificationsRead = () => api.post('/notifications/read-all')
export const getNotificationStatus = () =>
  api.get<{ inApp: boolean; email: boolean; teams: boolean; emailFrom: string | null; lastSentAt: string | null; lastDelivery: Record<string, { status: string; error?: string }> | null }>('/notifications/status')
export const sendTestNotification = () => api.post<{ id: string; deliveries: Record<string, { status: string; error?: string }> }>('/notifications/test')
