import { useCallback, useEffect, useState } from 'react'
import { UserPlus, Users } from 'lucide-react'
import { createUser, getTaxonomy, getUsers, resetUserPassword, updateUser, type User } from '../services/api'
import InfoTip from './InfoTip'
import { loadMe } from '../lib/me'
import { errorMessage } from '../pages/agent/shared'

const EMPTY = { name: '', email: '', role: '', password: '', accessUntil: '' }
// Thrown by an action that has already reported its own message.
const SKIP = Symbol('skip')

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
    loadMe().then(m => setMe(m?.user_id ?? null))
  }, [load])

  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }))
  const role = form.role || roles[0] || ''
  const ready = form.name.trim() && form.email.trim() && form.password.length >= 8 && role && (role !== 'Auditor' || form.accessUntil)

  async function add() {
    setBusy(true)
    setError(null)
    try {
      const res = (await createUser({ name: form.name, email: form.email, role, password: form.password, ...(role === 'Auditor' ? { accessUntil: form.accessUntil } : {}) })).data as { user?: User }
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

  const label = 'block text-xs font-semibold uppercase text-slate-600 mb-1 tracking-wide'

  return (
    <div className="card p-6 space-y-4" data-testid="users-section">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-zen-50 text-zen-600"><Users size={20} /></div>
          <div>
            <h3 className="text-[16px] font-extrabold text-slate-900">Users</h3>
            <p className="text-[13px] text-slate-600">People who can sign in. Their role decides what they can change and which review they decide.</p>
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
              <div className="flex items-center gap-1">
                <label className={label} htmlFor="u-role">Role</label>
                <InfoTip term="user_role" className="-my-0.5 mb-1" />
              </div>
              <select id="u-role" className="input" value={role} onChange={set('role')}>
                {roles.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
              <p className="mt-1 text-[12px] text-slate-500">Enforced on every action. Hover the ⓘ for what each role can do.</p>
              {role === 'Auditor' && (
                <label className="mt-2 block text-[12.5px] text-slate-600">Access until (last day): every page the auditor opens is logged
                  <input type="date" className="input mt-0.5" min={new Date().toISOString().slice(0, 10)} value={form.accessUntil} onChange={set('accessUntil')} data-testid="auditor-until" />
                </label>
              )}
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
        <p className="text-sm text-slate-500">Loading users…</p>
      ) : (
        <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white" data-testid="user-list">
          {users.map(u => (
            <li key={u.id} className="flex items-center gap-3 px-4 py-3">
              <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-gradient-zen text-[12px] font-bold text-white">{initials(u.name)}</div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-slate-900 truncate">{u.name}</span>
                  {u.id === me && <span className="rounded-full bg-zen-50 px-2 py-0.5 text-[12px] font-bold text-zen-700 ring-1 ring-zen-200">You</span>}
                </div>
                <div className="text-[13px] text-slate-600 truncate">{u.email}</div>
              </div>
              <UserActions user={u} roles={roles} isMe={u.id === me} deputyName={id => users.find(x => x.id === id)?.name} onChanged={async msg => { setNotice(msg); setError(null); await load() }}
                onError={msg => setError(msg)} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// Role, sign-in access and password for one person. Every change is logged.
function UserActions({ user: u, roles, isMe, deputyName, onChanged, onError }: {
  user: User
  roles: string[]
  isMe: boolean
  deputyName: (id: string) => string | undefined
  onChanged: (msg: string) => void
  onError: (msg: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [password, setPassword] = useState('')

  async function run(action: () => Promise<unknown>, msg: string) {
    setBusy(true)
    try {
      await action()
      onChanged(msg)
    } catch (e) {
      if (e === SKIP) return
      onError(errorMessage(e, 'The change was not saved'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <select className="input !w-auto !py-1 text-[12.5px]" value={u.role} disabled={busy} aria-label={`Role of ${u.name}`}
        onChange={e => {
          const role = e.target.value
          // An Auditor needs an end date: 30 days from today, changed next to the role.
          const until = new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10)
          run(() => updateUser(u.id, role === 'Auditor' ? { role, accessUntil: until } : { role }),
            role === 'Auditor' ? `${u.name} is now Auditor until ${until}. Change the date next to the role.` : `${u.name} is now ${role}.`)
        }}>
        {roles.map(r => <option key={r} value={r}>{r}</option>)}
      </select>
      <span className={`text-[12px] font-semibold ${u.isActive ? 'text-emerald-700' : 'text-slate-500'}`}>{u.isActive ? 'Active' : 'Inactive'}</span>
      {u.role === 'Auditor' && (
        <label className="flex items-center gap-1 text-[12px] text-slate-600" title="The last day this auditor can sign in">
          Access until
          <input type="date" className="input !w-36 !py-0.5 text-[12px]" value={u.accessUntil || ''} disabled={busy} data-testid="auditor-until-edit"
            onChange={e => e.target.value && run(() => updateUser(u.id, { accessUntil: e.target.value }), `${u.name} can sign in until ${e.target.value}.`)} />
        </label>
      )}
      {u.awayUntil && new Date(u.awayUntil) >= new Date(new Date().toDateString()) && (
        <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[12px] font-semibold text-amber-800 ring-1 ring-amber-200" data-testid="user-away">
          Away until {new Date(u.awayUntil).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}
          {u.deputyUserId ? `, deputy ${deputyName(u.deputyUserId) || u.deputyUserId}` : ', no deputy'}
        </span>
      )}
      {!isMe && (
        <button type="button" className="btn-secondary btn-sm" disabled={busy}
          onClick={() => run(async () => {
            const r = await updateUser(u.id, { isActive: !u.isActive })
            const own = (r.data as { ownership?: { moved: unknown[]; orphaned: unknown[] } }).ownership
            if (own && (own.moved.length || own.orphaned.length)) {
              onChanged(`${u.name} can no longer sign in. ${own.moved.length} agent${own.moved.length === 1 ? '' : 's'} went to the backup owner and ${own.orphaned.length} ${own.orphaned.length === 1 ? 'has' : 'have'} no owner now (listed on the Executive page).`)
              throw SKIP
            }
          }, u.isActive ? `${u.name} can no longer sign in.` : `${u.name} can sign in again.`)}>
          {u.isActive ? 'Deactivate' : 'Reactivate'}
        </button>
      )}
      {resetting ? (
        <span className="flex items-center gap-1.5">
          <input type="password" className="input !w-40 !py-1 text-[12.5px]" placeholder="New password (8+)" value={password}
            onChange={e => setPassword(e.target.value)} autoComplete="new-password" />
          <button type="button" className="btn-primary btn-sm" disabled={busy || password.length < 8}
            onClick={() => run(() => resetUserPassword(u.id, password), `New password set for ${u.name}. Share it with them securely.`).then(() => { setResetting(false); setPassword('') })}>Save</button>
          <button type="button" className="btn-secondary btn-sm" onClick={() => { setResetting(false); setPassword('') }}>Cancel</button>
        </span>
      ) : (
        <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={() => setResetting(true)}>Reset password</button>
      )}
    </div>
  )
}
