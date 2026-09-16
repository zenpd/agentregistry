import { useState, useEffect } from 'react'
import { getPhoenixConfig, updatePhoenixConfig } from '../services/api'

export default function SettingsPage() {
  const [endpoint, setEndpoint] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [apiKeySet, setApiKeySet] = useState(false)
  const [enabled, setEnabled] = useState(true)
  const [source, setSource] = useState<'saved' | 'env_default' | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    try {
      const resp = await getPhoenixConfig()
      setEndpoint(resp.data.endpoint)
      setApiKeySet(resp.data.apiKeySet)
      setEnabled(resp.data.enabled)
      setSource(resp.data.source)
    } finally {
      setLoading(false)
    }
  }

  async function save() {
    setSaving(true)
    setSaved(false)
    try {
      await updatePhoenixConfig({ endpoint: endpoint.trim(), api_key: apiKey.trim(), enabled })
      setApiKey('')
      setSaved(true)
      await load()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-2xl space-y-4 animate-fade-in">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Settings</h2>
        <p className="text-gray-500 mt-0.5">Org-wide configuration shared by every onboarded app.</p>
      </div>

      <div className="card p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-gray-900">Common tracing endpoint</h3>
          {source === 'env_default' && !loading && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 ring-1 ring-amber-200">Using deployment default — not yet saved</span>
          )}
          {source === 'saved' && !loading && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200">Saved</span>
          )}
        </div>
        <p className="text-sm text-gray-500">
          The default Phoenix/OTel endpoint the onboarding form's "common endpoint" option resolves to,
          and what the discovery picker checks by default. An individual app can still override this
          with its own custom endpoint at onboarding time.
        </p>

        {loading ? (
          <div className="text-sm text-gray-400">Loading…</div>
        ) : (
          <>
            <div>
              <label className="block text-xs font-semibold uppercase text-gray-500 mb-1 tracking-wide">Endpoint URL</label>
              <input className="input" value={endpoint} onChange={e => setEndpoint(e.target.value)} placeholder="https://zaf-phoenix.example.com" />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase text-gray-500 mb-1 tracking-wide">
                API key {apiKeySet && <span className="normal-case text-gray-400">(a key is already saved — leave blank to keep it)</span>}
              </label>
              <input className="input" type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder={apiKeySet ? '••••••••' : 'optional'} />
            </div>
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} />
              Enabled — when off, apps fall back to this deployment's own env-configured Phoenix
            </label>

            <div className="flex items-center gap-3 pt-2">
              <button onClick={save} disabled={saving} className="btn-primary btn-sm">
                {saving ? 'Saving…' : 'Save'}
              </button>
              {saved && <span className="text-xs text-emerald-600">Saved.</span>}
            </div>
          </>
        )}
      </div>

      <div className="card p-6 text-sm text-gray-600 space-y-2">
        <p>Other configuration lives in environment variables (see <code className="font-mono text-zen-700">backend/.env.example</code>).</p>
        <p>Backend base URL is resolved through the nginx proxy in production and the Vite dev proxy locally.</p>
      </div>
    </div>
  )
}
