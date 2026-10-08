import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Bell } from 'lucide-react'
import { getMyNotifications, markAllNotificationsRead, markNotificationRead, NOTIFICATIONS_CHANGED, type AppNotification } from '../services/ops/notifications'

function age(iso: string | null): string {
  if (!iso) return ''
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000))
  if (mins < 60) return `${mins} min ago`
  const h = Math.round(mins / 60)
  return h < 36 ? `${h} h ago` : `${Math.round(h / 24)} days ago`
}

// The in-app inbox: the daily digest and immediate notices for the signed-in person.
export default function NotificationBell() {
  const { pathname } = useLocation()
  const [rows, setRows] = useState<AppNotification[]>([])
  const [unread, setUnread] = useState(0)
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  const load = () => getMyNotifications().then(r => { setRows(r.data.rows); setUnread(r.data.unread) }).catch(() => {})
  useEffect(() => { load() }, [pathname])
  useEffect(() => {
    window.addEventListener(NOTIFICATIONS_CHANGED, load)
    const onDoc = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => { window.removeEventListener(NOTIFICATIONS_CHANGED, load); document.removeEventListener('mousedown', onDoc) }
  }, [])

  async function read(n: AppNotification) {
    if (!n.read) { await markNotificationRead(n.id).catch(() => {}); load() }
  }

  return (
    <div className="relative" ref={box}>
      <button type="button" onClick={() => setOpen(o => !o)} className="relative rounded-lg p-2 text-slate-600 hover:bg-gray-100 hover:text-slate-900"
        aria-label={`Notifications${unread ? `, ${unread} unread` : ''}`} data-testid="notification-bell">
        <Bell size={18} />
        {unread > 0 && <span className="absolute -right-0.5 -top-0.5 rounded-full bg-rose-600 px-1.5 text-[11px] font-bold text-white">{unread}</span>}
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-2 w-[420px] max-h-[70vh] overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-xl" data-testid="notification-panel">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
            <span className="text-sm font-bold text-slate-900">Notifications</span>
            {unread > 0 && <button type="button" className="text-[12.5px] font-semibold text-zen-700 hover:underline" onClick={async () => { await markAllNotificationsRead().catch(() => {}); load() }}>Mark all read</button>}
          </div>
          {rows.length === 0 && <p className="px-4 py-6 text-center text-[13px] text-slate-600">Nothing yet. A daily summary of what waits for you arrives here.</p>}
          <ul className="divide-y divide-slate-100">
            {rows.map(n => (
              <li key={n.id} className={`px-4 py-3 ${n.read ? '' : 'bg-zen-50/40'}`} onMouseEnter={() => read(n)}>
                <div className="flex items-start justify-between gap-2">
                  <span className="text-[13.5px] font-semibold text-slate-900">{n.subject.replace(/^Agent Registry: /, '')}</span>
                  <span className="shrink-0 text-[11.5px] text-slate-500">{age(n.createdAt)}</span>
                </div>
                <ul className="mt-1 space-y-0.5">
                  {n.items.map((it, i) => (
                    <li key={i} className="text-[13px] text-slate-700">
                      {it.link ? <Link to={it.link} className="hover:text-zen-700 hover:underline" onClick={() => { read(n); setOpen(false) }}>{it.text}</Link> : it.text}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
