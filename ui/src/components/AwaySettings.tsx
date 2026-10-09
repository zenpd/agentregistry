import { useEffect, useState } from 'react'
import { Plane } from 'lucide-react'
import { getDirectory, setMyAway } from '../services/api'
import { reloadMe, useMe } from '../lib/me'
import { errorMessage } from '../pages/agent/shared'

// Settings → Away and deputy: while you are away, the reviews and notices that
// would go to you go to your deputy, and the Approvals page says so.
export default function AwaySettings() {
  const me = useMe()
  const [people, setPeople] = useState<{ id: string; name: string; role: string }[]>([])
  const [until, setUntil] = useState('')
  const [deputy, setDeputy] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  // What is saved now: from the signed-in person at first, then from each save.
  const [saved, setSaved] = useState<{ awayUntil: string | null; deputyUserId: string | null }>({ awayUntil: null, deputyUserId: null })
  useEffect(() => { getDirectory().then(r => setPeople(r.data)).catch(() => setPeople([])) }, [])
  useEffect(() => {
    if (me) { setUntil(me.awayUntil || ''); setDeputy(me.deputyUserId || ''); setSaved({ awayUntil: me.awayUntil, deputyUserId: me.deputyUserId }) }
  }, [me])
  const today = new Date().toISOString().slice(0, 10)
  const away = !!saved.awayUntil && saved.awayUntil >= today

  async function save(clear = false) {
    setBusy(true); setMsg(null)
    try {
      const r = (await setMyAway(clear ? null : until || null, clear ? null : deputy || null)).data
      setSaved(r)
      await reloadMe()
      if (clear) { setUntil(''); setDeputy('') }
      setMsg({ ok: true, text: r.awayUntil ? `Saved. You are away until ${r.awayUntil}${r.deputyUserId ? `, and ${people.find(p => p.id === r.deputyUserId)?.name || 'your deputy'} receives your notices.` : '. No deputy is set, so your notices wait for you.'}` : 'Saved. You are not marked as away.' })
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e, 'Not saved') })
    } finally { setBusy(false) }
  }

  return (
    <div className="card p-6 space-y-3" data-testid="away-settings">
      <div className="flex items-start gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-sky-50 text-sky-600"><Plane size={20} /></div>
        <div>
          <h3 className="text-[16px] font-extrabold text-slate-900">Away and deputy</h3>
          <p className="text-[13px] text-slate-600">
            While you are away, the daily notices that would go to you go to your deputy, and the Integration Approval page shows the deputy next to the reviews you would decide.
            {away && <span className="ml-1 font-semibold text-amber-800" data-testid="away-now">You are marked as away until {saved.awayUntil}.</span>}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-[12.5px] text-slate-600">Away until
          <input type="date" className="input mt-0.5 !w-44 text-sm" min={today} value={until} onChange={e => setUntil(e.target.value)} data-testid="away-until" />
        </label>
        <label className="text-[12.5px] text-slate-600">Deputy
          <select className="input mt-0.5 !w-64 text-sm" value={deputy} onChange={e => setDeputy(e.target.value)} data-testid="away-deputy">
            <option value="">No deputy</option>
            {people.filter(p => p.id !== me?.user_id).map(p => <option key={p.id} value={p.id}>{p.name} · {p.role}</option>)}
          </select>
        </label>
        <button type="button" className="btn-primary btn-sm" disabled={busy || !until} onClick={() => save()} data-testid="save-away">Save</button>
        {(saved.awayUntil || saved.deputyUserId) && (
          <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={() => save(true)} data-testid="clear-away">I am back</button>
        )}
      </div>
      {msg && <p className={`text-[13px] ${msg.ok ? 'text-emerald-700' : 'text-rose-700'}`} role="status">{msg.text}</p>}
    </div>
  )
}
