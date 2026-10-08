import { useState, useEffect } from 'react'
import { getPhoenixConfig, testPhoenixConnection, updatePhoenixConfig, type ConnectionTestResult } from '../services/api'
import NotificationSettings from '../components/NotificationSettings'
import AwaySettings from '../components/AwaySettings'
import RegistryAiCard from '../components/RegistryAiCard'
import ApiKeysCard from '../components/ApiKeysCard'
import ConnectorsCard from '../components/ConnectorsCard'
import GovernanceRulesCard from '../components/GovernanceRulesCard'
import ApprovedToolsCard from '../components/ApprovedToolsCard'
import ControlsCard from '../components/ControlsCard'
import CostSettingsCard from '../components/CostSettingsCard'
import DemoAgentsCard from '../components/DemoAgentsCard'
import ArchivedAgentsCard from '../components/ArchivedAgentsCard'
import UsersSection from '../components/UsersSection'
import InfoTip from '../components/InfoTip'
import { can, useMe } from '../lib/me'

export default function SettingsPage() {
  const me = useMe()
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
  const [testing, setTesting] = useState(false)
  const [test, setTest] = useState<ConnectionTestResult | null>(null)

  async function runTest() {
    setTesting(true)
    setTest(null)
    try {
      // A typed address is tested as typed; otherwise the saved connection is tested.
      const typed = endpoint.trim()
      setTest((await testPhoenixConnection(typed ? { endpoint: typed, apiKey: apiKey.trim() } : {})).data)
    } catch (e: any) {
      setTest({ endpoint: null, state: 'error', message: e.response?.data?.detail || 'The test could not run.' })
    } finally {
      setTesting(false)
    }
  }

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
    <div className="max-w-4xl space-y-4 animate-fade-in">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Settings</h2>
        <p className="text-slate-600 mt-0.5">Settings for the whole registry.</p>
      </div>
      {me && !can(me, 'admin') && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[13px] text-amber-900" data-testid="settings-readonly">
          Only a Registry Admin can change settings and users. Your role is {me.accountRole}.
        </div>
      )}

      <div className="card p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-slate-900">Common tracing endpoint <InfoTip term="common_endpoint" /></h3>
          {source === 'env_default' && !loading && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 ring-1 ring-amber-200">Using the installation default. Nothing saved here yet.</span>
          )}
          {source === 'saved' && !loading && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200">Saved</span>
          )}
        </div>
        <p className="text-sm text-slate-600">
          The Phoenix address the registry reads traces from. Discovery scans it, and the registration form offers it
          as the default. An agent can use its own address instead.
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
              Use this address. When off, the registry uses the Phoenix address set at installation
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
              <button onClick={runTest} disabled={testing} className="btn-secondary btn-sm" data-testid="test-connection">
                {testing ? 'Testing…' : 'Test connection'}
              </button>
            </div>
            {test && (
              <div className={`rounded-lg border px-3 py-2 text-[13px] ${test.state === 'connected' ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-rose-200 bg-rose-50 text-rose-800'}`}
                role="status" data-testid="connection-result">
                <span className="font-semibold">{test.state === 'connected' ? 'Connected' : test.state.replace(/_/g, ' ')}</span>
                {' — '}{test.message}
                {test.state === 'connected' && <> Phoenix {test.version || '(version not reported)'}, {test.projectCount} project{test.projectCount === 1 ? '' : 's'}.</>}
              </div>
            )}
          </>
        )}
      </div>

      <DemoAgentsCard />
      <GovernanceRulesCard canEdit={can(me, 'admin')} />
      <ApprovedToolsCard canEdit={can(me, 'admin')} />
      <ControlsCard />

      <NotificationSettings canSendTest={can(me, 'admin')} />
      <AwaySettings />

      <RegistryAiCard canEdit={can(me, 'admin')} />
      <CostSettingsCard canEdit={can(me, 'admin')} />

      {can(me, 'admin') && <UsersSection />}

      {can(me, 'admin') && <ConnectorsCard />}

      {can(me, 'admin') && <ApiKeysCard />}

      <ArchivedAgentsCard canEdit={can(me, 'admin')} />

      <div className="card p-6 text-sm text-slate-700 space-y-2">
        <p>Other options are set at installation (see <code className="font-mono text-zen-700">backend/.env.example</code>).</p>
      </div>
    </div>
  )
}
