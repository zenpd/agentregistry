import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { login } from '../services/api'

const DEMO_EMAIL = 'admin@airegistry.local'
const DEMO_PASSWORD = 'admin123'

export default function LoginPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  // The local demo account is shown only when the server runs in development.
  const [showDemo, setShowDemo] = useState(false)
  useEffect(() => {
    axios.get('/api/v1/auth/config').then(r => {
      if (r.data?.showDemoLogin) { setShowDemo(true); setEmail(DEMO_EMAIL); setPassword(DEMO_PASSWORD) }
    }).catch(() => {})
  }, [])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await login(email, password)
      navigate('/', { replace: true })
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Invalid credentials')
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="bg-white rounded-lg shadow-lg border border-gray-200 p-8 w-full max-w-sm">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-lg bg-gradient-zen flex items-center justify-center text-white font-bold text-lg">
            Z
          </div>
          <div>
            <div className="font-bold text-slate-900">Agent Registry</div>
            <div className="text-xs text-slate-600">Enterprise AI Control Tower</div>
          </div>
        </div>

        <h2 className="text-lg font-semibold mb-4">Sign in to continue</h2>

        <form onSubmit={submit} className="space-y-3">
          <div>
            <label className="text-xs text-slate-600">Email</label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zen-400"
              placeholder="you@company.com"
            />
          </div>
          <div>
            <label className="text-xs text-slate-600">Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zen-400"
            />
          </div>
          {error && <div className="text-sm text-red-600 bg-red-50 rounded p-2">{error}</div>}
          <button
            type="submit"
            disabled={busy}
            className="w-full bg-gradient-zen text-white py-2 rounded-lg text-sm font-medium disabled:opacity-50 hover:opacity-90"
          >
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        {showDemo && (
          <div className="mt-4 text-xs text-slate-500" data-testid="demo-login">
            <div>Local development account:</div>
            <div>{DEMO_EMAIL} / {DEMO_PASSWORD}</div>
          </div>
        )}
      </div>
    </div>
  )
}