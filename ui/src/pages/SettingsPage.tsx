import { useState, useEffect } from 'react'
import { getPhoenixConfig, updatePhoenixConfig } from '../services/api'
import UsersSection from '../components/UsersSection'
import InfoTip from '../components/InfoTip'

export default function SettingsPage() {
  const [endpoint, setEndpoint] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [apiKeySet, setApiKeySet] = useState(false)
  const [enabled, setEnabled] = useState(true)
  const [template, setTemplate] = useState('')
  const [saveError, setSaveError] = useState<string | null>(null)
  const [source, setSource] = useState<'saved' | 'env_default' | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    setSaveError(null)
    try {
      const resp = await getPhoenixConfig()
      setEndpoint(resp.data.endpoint)
      setApiKeySet(resp.data.apiKeySet)
      setEnabled(resp.data.enabled)
      setTemplate(resp.data.appUrlTemplate || '')
      setSource(resp.data.source)
    } catch {
      setSaveError('Could not load the saved settings. Reload the page before saving, or the form may overwrite them.')
    } finally {
      setLoading(false)
    }
  }

  async function save() {
    setSaving(true)
    setSaved(false)
    setSaveError(null)
    try {
      await updatePhoenixConfig({ endpoint: endpoint.trim(), api_key: apiKey.trim(), enabled, app_url_template: template.trim() })
      setApiKey('')
      setSaved(true)
      await load()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setSaveError(Array.isArray(detail) ? String(detail[0]?.msg || 'Could not save').replace('Value error, ', '') : typeof detail === 'string' ? detail : 'Could not save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-2xl space-y-4 animate-fade-in">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Settings</h2>
        <p className="text-slate-600 mt-0.5">Org-wide configuration shared by every onboarded app.</p>
      </div>

      <div className="card p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-slate-900">Common tracing endpoint <InfoTip term="common_endpoint" /></h3>
          {source === 'env_default' && !loading && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 ring-1 ring-amber-200">Using deployment default — not yet saved</span>
          )}
          {source === 'saved' && !loading && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200">Saved</span>
          )}
        </div>
        <p className="text-sm text-slate-600">
          The default Phoenix/OTel endpoint the onboarding form's "common endpoint" option resolves to,
          and what the discovery picker checks by default. An individual app can still override this
          with its own custom endpoint at onboarding time.
        </p>

        {loading ? (
          <div className="text-sm text-slate-500">Loading…</div>
        ) : (
          <>
            <div>
              <label className="block text-xs font-semibold uppercase text-slate-600 mb-1 tracking-wide">Endpoint URL</label>
              <input className="input" value={endpoint} onChange={e => setEndpoint(e.target.value)} placeholder="https://zaf-phoenix.example.com" />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase text-slate-600 mb-1 tracking-wide">
                API key {apiKeySet && <span className="normal-case text-slate-500">(a key is already saved — leave blank to keep it; changing the address above clears it, so enter it again)</span>}
              </label>
              <input className="input" type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder={apiKeySet ? '••••••••' : 'optional'} />
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} />
              Enabled — when off, apps fall back to this deployment's own env-configured Phoenix
            </label>

            <div>
              <div className="flex items-center mb-1">
                <label className="block text-xs font-semibold uppercase text-slate-600 tracking-wide">App address pattern <span className="normal-case text-slate-500">(optional)</span></label>
                <InfoTip term="app_url_template" className="ml-1" />
              </div>
              <input className="input" value={template} onChange={e => setTemplate(e.target.value)} aria-label="App address pattern"
                placeholder="https://{project}-be.<environment>.azurecontainerapps.io" />
              <p className="text-xs text-slate-500 mt-1">
                Use <code className="font-mono">{'{project}'}</code> where the Phoenix project name goes. Registering from Discovered then finds the app and fills its description, capabilities, inputs and outputs.
              </p>
            </div>
            {saveError && <p className="text-xs text-rose-600" role="alert">{saveError}</p>}

            <div className="flex items-center gap-3 pt-2">
              <button onClick={save} disabled={saving} className="btn-primary btn-sm">
                {saving ? 'Saving…' : 'Save'}
              </button>
              {saved && <span className="text-xs text-emerald-600">Saved.</span>}
            </div>
          </>
        )}
      </div>

      <UsersSection />

      <div className="card p-6 text-sm text-slate-700 space-y-2">
        <p>Other configuration lives in environment variables (see <code className="font-mono text-zen-700">backend/.env.example</code>).</p>
        <p>Backend base URL is resolved through the nginx proxy in production and the Vite dev proxy locally.</p>
      </div>
    </div>
  )
}
