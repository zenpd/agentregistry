import { useEffect, useState, useRef } from 'react'
import { Send, ListTree } from 'lucide-react'
import {
  getApiOperations, tryAgent, updateContract,
  type ApiOperations, type EndpointAdvice, type Integration, type TryItResult,
} from '../services/ops/integrate'
import { errorMessage } from '../pages/agent/shared'
import ErrorNote from './ErrorNote'
import InfoTip from './InfoTip'

function pretty(body: unknown): string {
  if (body == null) return ''
  return typeof body === 'string' ? body : JSON.stringify(body, null, 2)
}

// What the response means, in the terms of "is this the right endpoint?".
function explain(result: TryItResult, method: string, canPickPath: boolean): string | null {
  const html = (result.contentType || '').includes('text/html')
  const pick = canPickPath ? ' Use “Load API operations” to pick a path the app really serves.' : ''
  if (result.status === 404) {
    return (html
      ? 'Nothing is served at this path, and the host answers with a web page — this is probably the app’s site, not its API.'
      : 'The host answered, but nothing is served at this path.') + pick
  }
  if (result.status === 405) {
    return `The path exists but does not accept ${method}. Try the other method.` + pick
  }
  if (result.status === 401 || result.status === 403) {
    return 'The agent requires credentials. Request access below, then ask the owner how to authenticate.'
  }
  if (html && result.ok) {
    return 'This returned a web page, not data — the address serves the app’s UI rather than its API.' + pick
  }
  if (result.status && result.status >= 500) {
    return 'The agent itself errored. The path looks right; the owner needs to look at their logs.'
  }
  return null
}

type Target = 'api' | 'recorded'

const normPath = (p: string) => p.split('?')[0].replace(/\/+$/, '') || '/'

// Whether a path is one the host publishes; {params} match one segment, so
// /api/v1/onboard/abc counts as /api/v1/onboard/{session_id}.
function inApiList(ops: ApiOperations, path: string): boolean {
  const wanted = normPath(path)
  return ops.operations.some(o => {
    const pattern = normPath(o.path).replace(/[.*+?^$()|[\]\\]/g, '\\$&').replace(/\{[^}]+\}/g, '[^/]+')
    return new RegExp(`^${pattern}$`).test(wanted)
  })
}

// Paths that prove the host is up but are not what a consumer calls, so a
// 200 from them is no reason to make them the contract endpoint.
const PROBE_PATH = /^\/(api\/v\d+\/)?(health|healthz|ready|readyz|live|livez|ping|status|version|openapi\.json|docs)\/?$/i

// Calls one registered agent's own endpoint through the registry server.
// When the recorded endpoint is a -fe web page, the call goes to the paired
// -be host by default (tryIt.backendDefault): a web page cannot answer an API
// call, so defaulting to it only produces a 404 or a page of HTML.
export default function TryItPanel({ agentId, tryIt, endpointAdvice, onEndpointSaved }: {
  agentId: string
  tryIt: Integration['tryIt']
  // Same advice the Contract section shows in full, repeated here because
  // this is where someone acts on it.
  endpointAdvice?: EndpointAdvice | null
  // Set where the viewer may edit the contract (the Integrate tab): offers to
  // save a path that just answered with data as the contract endpoint.
  onEndpointSaved?: () => void
}) {
  const example = JSON.stringify(tryIt.examplePayload, null, 2)
  const [target, setTarget] = useState<Target>('api')
  const [path, setPath] = useState(tryIt.path || '/')
  const [method, setMethod] = useState<'POST' | 'GET'>('POST')
  const [body, setBody] = useState(example)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<TryItResult | null>(null)
  const [ops, setOps] = useState<ApiOperations | null>(null)
  const [opsBusy, setOpsBusy] = useState(false)
  const [opsError, setOpsError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)

  // A different agent starts over. When only the example changes (the registry filled in the inputs
  // while the page was open), what a person typed and the result they are reading are kept.
  const shown = useRef({ agentId, example })
  useEffect(() => {
    const before = shown.current
    shown.current = { agentId, example }
    if (before.agentId === agentId) {
      setBody(current => (current === before.example ? example : current))
      return
    }
    setBody(example)
    setResult(null)
    setError(null)
  }, [agentId, example])

  // A different agent, or a contract edit that moved the target, starts over.
  // The API list belongs to the host, so it survives a path-only change such
  // as saving a picked operation as the endpoint.
  useEffect(() => {
    setTarget('api')
    setPath(tryIt.path || '/')
  }, [agentId, tryIt.base, tryIt.path])
  useEffect(() => {
    setOps(null)
    setOpsError(null)
  }, [agentId, tryIt.base])

  if (!tryIt.available) {
    return (
      <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-slate-700" data-testid="try-it-unavailable">
        <span className="font-medium text-slate-700">Try it is not available for this agent.</span> {tryIt.reason}
      </div>
    )
  }

  const onApi = tryIt.pathEditable && target === 'api'
  const isHtml = (result?.contentType || '').includes('text/html')
  const explained = result ? explain(result, result.method, tryIt.pathEditable) : null
  // The endpoint advice is only worth saying once a call has gone wrong.
  const hint = explained && endpointAdvice && (!tryIt.backendDefault || target === 'recorded')
    ? `${explained} ${endpointAdvice.looksLike === 'frontend' ? 'The recorded endpoint looks like a web page' : 'The recorded endpoint is a tracing URL'} — see Contract above for where to find the real API.`
    : explained
  // A path that just answered with data, and is not what the contract says yet.
  const savable = !!onEndpointSaved && !!result?.ok && !isHtml && result.url !== tryIt.url && onApi
    && !PROBE_PATH.test(new URL(result.url).pathname)

  async function loadOperations() {
    setOpsBusy(true)
    setOpsError(null)
    try {
      const res = (await getApiOperations(agentId)).data
      setOps(res)
      if (!res.ok) setOpsError(res.error || 'Could not read the API list')
    } catch (e) {
      setOpsError(errorMessage(e, 'Could not read the API list'))
    } finally {
      setOpsBusy(false)
    }
  }

  function pickOperation(key: string) {
    const op = ops?.operations.find(o => `${o.method} ${o.path}` === key)
    if (!op) return
    setMethod(op.method)
    setPath(op.path)
    if (op.method === 'POST' && op.exampleBody != null) setBody(JSON.stringify(op.exampleBody, null, 2))
    setResult(null)
    setError(null)
  }

  async function send() {
    let parsed: unknown = undefined
    if (method === 'POST') {
      try {
        parsed = body.trim() ? JSON.parse(body) : {}
      } catch {
        setError('The request body is not valid JSON')
        return
      }
    }
    setBusy(true)
    setError(null)
    setSaved(null)
    try {
      setResult((await tryAgent(agentId, method, parsed, onApi ? path : undefined)).data)
    } catch (e) {
      setResult(null)
      setError(errorMessage(e, 'The call could not be made'))
    } finally {
      setBusy(false)
    }
  }

  async function saveEndpoint() {
    if (!result) return
    setSaving(true)
    setError(null)
    try {
      await updateContract(agentId, { api_endpoint: result.url })
      setSaved(result.url)
      onEndpointSaved?.()
    } catch (e) {
      setError(errorMessage(e, 'Could not save the endpoint'))
    } finally {
      setSaving(false)
    }
  }

  const templated = onApi && path.includes('{')
  // Mirrors the server's rule, so a bad path is explained before Send.
  const badPath = onApi && (!path.startsWith('/') || path.startsWith('//'))
  // Once the API list is loaded it is better evidence than any guess from
  // the URL: e.g. a recorded /analytics that the backend does not serve.
  const unlisted = onApi && !badPath && !templated && !!ops?.ok && ops.operations.length > 0 && !inApiList(ops, path)

  return (
    <div className="space-y-3" data-testid="try-it">
      {onApi && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <button type="button" onClick={loadOperations} disabled={opsBusy} className="btn-secondary btn-sm flex items-center gap-1.5" data-testid="load-operations">
            <ListTree size={14} /> {opsBusy ? 'Reading openapi.json…' : ops?.ok ? 'Reload API operations' : 'Load API operations'}
          </button>
          <InfoTip term="openapi_doc" />
          {opsBusy && <span className="text-slate-500">An app that scales to zero can take ~30 s to wake up.</span>}
          {ops?.ok && ops.operations.length > 0 && (
            <select
              className="input w-auto flex-1 min-w-[240px] py-1.5 font-mono text-xs"
              value={ops.operations.some(o => o.method === method && o.path === path) ? `${method} ${path}` : ''}
              onChange={e => pickOperation(e.target.value)}
              aria-label="API operation"
              data-testid="operation-picker"
            >
              <option value="">Pick one of {ops.operations.length} operations{ops.title ? ` from ${ops.title}` : ''}…</option>
              {ops.operations.map(o => (
                <option key={`${o.method} ${o.path}`} value={`${o.method} ${o.path}`}>
                  {o.method.padEnd(4)} {o.path}{o.summary ? ` — ${o.summary}` : ''}
                </option>
              ))}
            </select>
          )}
          {ops?.ok && ops.operations.length === 0 && <span className="text-slate-600">The API list has no GET or POST operations.</span>}
          {ops?.ok && ops.otherMethods > 0 && (
            <span className="w-full text-slate-500">{ops.otherMethods} PUT/PATCH/DELETE operation{ops.otherMethods === 1 ? '' : 's'} not listed — Try it sends GET and POST only.</span>
          )}
        </div>
      )}
      {opsError && <ErrorNote message={opsError} hint={ops?.hint} onDismiss={() => setOpsError(null)} testId="operations-error" />}

      <div className="flex items-center gap-2 text-xs">
        <select className="input w-auto py-1.5" value={method} onChange={e => setMethod(e.target.value as 'POST' | 'GET')} aria-label="HTTP method">
          <option value="POST">POST</option>
          <option value="GET">GET</option>
        </select>
        {onApi ? (
          <div className="flex flex-1 min-w-0 items-center rounded-lg bg-gray-50 ring-1 ring-gray-200 focus-within:ring-zen-400">
            <code className="shrink-0 max-w-[45%] truncate pl-3 font-mono text-slate-600" title={tryIt.base || ''}>{tryIt.base}</code>
            <input
              className="flex-1 min-w-0 bg-transparent px-1 py-2 font-mono text-slate-800 outline-none"
              value={path}
              onChange={e => setPath(e.target.value)}
              aria-label="Path"
              placeholder="/api/…"
              spellCheck={false}
              data-testid="try-it-path"
            />
          </div>
        ) : (
          <code className="flex-1 truncate rounded-lg bg-gray-50 px-3 py-2 font-mono text-slate-700" title={tryIt.url || ''}>{tryIt.url}</code>
        )}
      </div>
      {tryIt.backendDefault && endpointAdvice?.suggestedBase && (
        <p className="text-[12.5px] text-slate-500" data-testid="try-it-backend-default">
          {target === 'api'
            ? <>Calling the app’s backend host (the recorded endpoint is its web page). <button type="button" className="underline hover:text-slate-700" onClick={() => { setTarget('recorded'); setResult(null) }}>Call the recorded page instead</button></>
            : <>Calling the recorded web page. <button type="button" className="underline hover:text-slate-700" onClick={() => { setTarget('api'); setResult(null) }}>Back to the backend host</button></>}
        </p>
      )}
      {badPath && <p className="text-xs text-rose-700">The path must start with a single /, e.g. /api/v1/…</p>}
      {unlisted && (
        <p className="text-xs text-amber-700" data-testid="path-not-listed">
          <code className="font-mono">{normPath(path)}</code> is not in this host’s API list, so it will most likely answer 404. Pick an operation above.
        </p>
      )}
      {templated && <p className="text-xs text-amber-700">Replace the {'{…}'} part of the path with a real value before sending.</p>}

      {method === 'POST' && (
        <textarea
          className="input font-mono text-xs"
          rows={6}
          value={body}
          onChange={e => setBody(e.target.value)}
          aria-label="Request body (JSON)"
          spellCheck={false}
        />
      )}

      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-slate-500">
          Sent from the registry server. Your login is not passed to the agent. Calls are logged without their
          content, and each person can send a limited number of calls a minute (10 unless the installation changed it).
        </p>
        <button type="button" onClick={send} disabled={busy || badPath} className="btn-primary btn-sm flex items-center gap-1.5 shrink-0">
          <Send size={14} /> {busy ? 'Calling…' : 'Send'}
        </button>
      </div>

      {error && <div className="rounded-xl bg-rose-50 border border-rose-200 px-3 py-2 text-xs text-rose-700">{error}</div>}

      {result && (
        <div className="rounded-xl border border-gray-200 overflow-hidden" data-testid="try-it-result">
          <div className="flex flex-wrap items-center gap-2 bg-gray-50 px-3 py-2 text-xs">
            <span className="font-mono text-slate-600">{result.method}</span>
            {result.status != null
              ? <span className={result.ok ? 'status-complete' : 'status-failed'}>HTTP {result.status}</span>
              : <span className="status-failed">No response</span>}
            {result.latencyMs != null && <span className="text-slate-600">{result.latencyMs} ms</span>}
            {result.contentType && <span className="text-slate-500 truncate">{result.contentType}</span>}
            <span className="ml-auto font-mono text-slate-500 truncate max-w-full" title={result.url}>{result.url}</span>
          </div>
          {result.error && <div className="px-3 py-2"><ErrorNote message={result.error} hint={result.hint} /></div>}
          {result.location && (
            <div className="px-3 py-2 text-xs text-amber-700">Redirect to {result.location} was not followed.</div>
          )}
          {hint && <div className="px-3 py-2 text-xs text-amber-800 bg-amber-50 border-t border-amber-100">{hint}</div>}
          {savable && saved !== result.url && (
            <div className="flex flex-wrap items-center gap-2 px-3 py-2 text-xs bg-emerald-50 border-t border-emerald-100 text-emerald-900" data-testid="save-endpoint">
              <span className="flex-1">This path answered with data. Make it the contract endpoint, so consumers call it instead of the web page?</span>
              <button type="button" className="btn-success btn-sm" onClick={saveEndpoint} disabled={saving}>
                {saving ? 'Saving…' : 'Save as contract endpoint'}
              </button>
            </div>
          )}
          {saved === result.url && (
            <div className="px-3 py-2 text-xs bg-emerald-50 border-t border-emerald-100 text-emerald-800">Saved. The contract endpoint is now {saved}.</div>
          )}
          {result.body != null && pretty(result.body) !== '' && (
            isHtml ? (
              <details className="px-3 py-2 text-xs text-slate-700">
                <summary className="cursor-pointer select-none">Show the HTML that came back ({pretty(result.body).length.toLocaleString()} characters)</summary>
                <pre className="mt-2 max-h-56 overflow-auto font-mono whitespace-pre-wrap break-all text-slate-700">{pretty(result.body)}</pre>
              </details>
            ) : (
              <pre className="max-h-72 overflow-auto px-3 py-2 text-xs font-mono text-slate-800 whitespace-pre-wrap break-all">{pretty(result.body)}</pre>
            )
          )}
          {result.truncated && <div className="px-3 pb-2 text-xs text-slate-500">Response cut off at 64 KB.</div>}
        </div>
      )}
    </div>
  )
}
