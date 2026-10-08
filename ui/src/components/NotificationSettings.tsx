import { useEffect, useState } from 'react'
import { Bell } from 'lucide-react'
import { getNotificationStatus, sendTestNotification, NOTIFICATIONS_CHANGED } from '../services/ops/notifications'
import { errorMessage } from '../pages/agent/shared'

type Status = Awaited<ReturnType<typeof getNotificationStatus>>['data']

function Channel({ name, on, detail }: { name: string; on: boolean; detail: string }) {
  return (
    <li className="flex items-start gap-3">
      <span className={`mt-0.5 rounded-full px-2 py-0.5 text-[12px] font-semibold ${on ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200' : 'bg-slate-100 text-slate-700 ring-1 ring-slate-200'}`}>
        {on ? 'On' : 'Not configured'}
      </span>
      <div><div className="text-sm font-semibold text-slate-900">{name}</div><div className="text-[12.5px] text-slate-600">{detail}</div></div>
    </li>
  )
}

// Settings → Notifications: which channels deliver, and a test message to yourself.
export default function NotificationSettings({ canSendTest }: { canSendTest: boolean }) {
  const [status, setStatus] = useState<Status | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { getNotificationStatus().then(r => setStatus(r.data)).catch(() => setStatus(null)) }, [])

  async function test() {
    setBusy(true)
    try {
      const d = (await sendTestNotification()).data.deliveries
      const email = d.email?.status
      setResult(`Sent to your inbox (the bell). E-mail: ${email === 'sent' ? 'sent' : email === 'not_configured' ? 'not configured' : email === 'no_email' ? 'your account has no e-mail address' : `failed — ${d.email?.error || 'no reason given'}`}.`)
      window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED))
    } catch (e) {
      setResult(errorMessage(e, 'The test message was not sent'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card p-6 space-y-3" data-testid="notification-settings">
      <div className="flex items-start gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-orange-50 text-orange-600"><Bell size={20} /></div>
        <div>
          <h3 className="text-[16px] font-extrabold text-slate-900">Notifications</h3>
          <p className="text-[13px] text-slate-600">Each person gets one message a day with what waits for them, and admins hear at once when a scheduled job fails.</p>
        </div>
      </div>
      {status && (
        <ul className="space-y-2.5">
          <Channel name="In-app inbox" on detail="The bell in the top bar. Always on." />
          <Channel name="E-mail" on={status.email} detail={status.email ? `Sent from ${status.emailFrom}.` : 'Set SMTP_HOST and SMTP_FROM (and SMTP_USER, SMTP_PASSWORD if the server needs them) in the backend environment.'} />
          <Channel name="Teams channel" on={status.teams} detail={status.teams ? 'A daily summary is posted to the channel.' : 'Set TEAMS_WEBHOOK_URL to an incoming webhook of the channel.'} />
        </ul>
      )}
      {canSendTest && (
        <div className="flex items-center gap-3">
          <button type="button" className="btn-secondary btn-sm" onClick={test} disabled={busy} data-testid="send-test-notification">{busy ? 'Sending…' : 'Send me a test message'}</button>
          {result && <span className="text-[13px] text-slate-700" role="status">{result}</span>}
        </div>
      )}
    </div>
  )
}
