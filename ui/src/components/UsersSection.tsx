import { useCallback, useEffect, useState } from 'react'
import { UserPlus, Users } from 'lucide-react'
import { createUser, getMe, getTaxonomy, getUsers, type User } from '../services/api'
import { errorMessage } from '../pages/agent/shared'

const EMPTY = { name: '', email: '', role: '', password: '' }

function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map(p => p[0]!.toUpperCase()).join('') || '?'
}

// Settings → Users: the people who can sign in. Exists mainly so an approval
// can have a second person — nobody can approve their own access request.
export default function UsersSection() {
  const [users, setUsers] = useState<User[] | null>(null)
  const [roles, setRoles] = useState<string[]>([])
  const [me, setMe] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setUsers((await getUsers()).data)
    } catch (e) {
      setError(errorMessage(e, 'Could not load users'))
    }
  }, [])

  useEffect(() => {
    load()
    getTaxonomy().then(r => setRoles(r.data.userRoles || [])).catch(() => setRoles([]))
    getMe().then(r => setMe(r.data.user_id)).catch(() => setMe(null))
  }, [load])

  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }))
  const role = form.role || roles[0] || ''
  const ready = form.name.trim() && form.email.trim() && form.password.length >= 8 && role

  async function add() {
    setBusy(true)
    setError(null)
    try {
      const res = (await createUser({ name: form.name, email: form.email, role, password: form.password })).data as { user?: User }
      const added = res.user
      setNotice(`Added ${added?.name || form.name.trim()}. They can sign in now as ${added?.email || form.email.trim()} with the password you set — share it with them securely.`)
      setForm(EMPTY)
      setAdding(false)
      await load()
    } catch (e) {
      setError(errorMessage(e, 'Could not add the user'))
    } finally {
      setBusy(false)
    }
  }

  const label = 'block text-xs font-semibold uppercase text-gray-500 mb-1 tracking-wide'

  return (
    <div className="card p-6 space-y-4" data-testid="users-section">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-zen-50 text-zen-600"><Users size={20} /></div>
          <div>
            <h3 className="text-[16px] font-extrabold text-slate-900">Users</h3>
            <p className="text-[13px] text-slate-500">People who can sign in. Optional while testing — you can approve your own requests.</p>
          </div>
        </div>
        {!adding && (
          <button type="button" className="btn-primary btn-sm flex shrink-0 items-center gap-1.5 whitespace-nowrap" onClick={() => { setAdding(true); setNotice(null); setError(null) }}
            data-testid="add-user">
            <UserPlus size={15} /> Add user
          </button>
        )}
      </div>

      {notice && <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[13px] text-emerald-800" role="status">{notice}</div>}

      {adding && (
        <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-4 space-y-3" data-testid="add-user-form">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={label} htmlFor="u-name">Name</label>
              <input id="u-name" className="input" value={form.name} onChange={set('name')} placeholder="Priya Sharma" autoFocus />
            </div>
            <div>
              <label className={label} htmlFor="u-email">Email</label>
              <input id="u-email" type="email" className="input" value={form.email} onChange={set('email')} placeholder="priya@company.com" />
            </div>
            <div>
              <label className={label} htmlFor="u-role">Role</label>
              <select id="u-role" className="input" value={role} onChange={set('role')}>
                {roles.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
              <p className="mt-1 text-[11px] text-slate-400">Recorded only for now; everyone can do everything.</p>
            </div>
            <div>
              <label className={label} htmlFor="u-password">Temporary password</label>
              <input id="u-password" type="password" className="input" value={form.password} onChange={set('password')}
                placeholder="At least 8 characters" autoComplete="new-password" />
              {form.password && form.password.length < 8 && <p className="mt-1 text-xs text-rose-600">At least 8 characters.</p>}
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-secondary btn-sm" onClick={() => { setAdding(false); setForm(EMPTY); setError(null) }} disabled={busy}>Cancel</button>
            <button type="button" className="btn-primary btn-sm" onClick={add} disabled={busy || !ready} data-testid="save-user">
              {busy ? 'Adding…' : 'Add user'}
            </button>
          </div>
        </div>
      )}

      {error && <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[13px] text-rose-700">{error}</div>}

      {users === null ? (
        <p className="text-sm text-slate-400">Loading users…</p>
      ) : (
        <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white" data-testid="user-list">
          {users.map(u => (
            <li key={u.id} className="flex items-center gap-3 px-4 py-3">
              <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-gradient-zen text-[12px] font-bold text-white">{initials(u.name)}</div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-slate-900 truncate">{u.name}</span>
                  {u.id === me && <span className="rounded-full bg-zen-50 px-2 py-0.5 text-[11px] font-bold text-zen-700 ring-1 ring-zen-200">You</span>}
                </div>
                <div className="text-[13px] text-slate-500 truncate">{u.email}</div>
              </div>
              <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[12px] font-semibold text-slate-700">{u.role}</span>
              <span className={`text-[12px] font-semibold ${u.isActive ? 'text-emerald-700' : 'text-slate-400'}`}>{u.isActive ? 'Active' : 'Inactive'}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
