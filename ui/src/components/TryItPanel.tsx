import { useEffect, useState } from 'react'
import { Send, AlertTriangle } from 'lucide-react'
import { tryAgent, type EndpointAdvice, type Integration, type TryItResult } from '../services/ops/integrate'
import { errorMessage } from '../pages/agent/shared'

function pretty(body: unknown): string {
  if (body == null) return ''
  return typeof body === 'string' ? body : JSON.stringify(body, null, 2)
}

// What the response means, in the terms of "is this the right endpoint?".
function explain(result: TryItResult, method: string): string | null {
  const html = (result.contentType || '').includes('text/html')
  if (result.status === 404) {
    return html
      ? 'Nothing is served at this path, and the host answers with a web page — this is probably the app\u2019s site, not its API.'
      : 'The host answered, but nothing is served at this path. Check the path against the app\u2019s API list (its /openapi.json).'
  }
  if (result.status === 405) {
    return `The path exists but does not accept ${method}. Try the other method, or check the app\u2019s API list for the right one.`
  }
  if (result.status === 401 || result.status === 403) {
    return 'The agent requires credentials. Request access below, then ask the owner how to authenticate.'
  }
  if (html && result.ok) {
    return 'This returned a web page, not data — the address serves the app\u2019s UI rather than its API.'
  }
  if (result.status && result.status >= 500) {
    return 'The agent itself errored. The path looks right; the owner needs to look at their logs.'
  }
  return null
}

// Calls one registered agent's own endpoint through the registry server.
export default function TryItPanel({ agentId, tryIt, endpointAdvice }: {
  agentId: string
  tryIt: Integration['tryIt']
  // Same advice the Contract section shows in full, one level up — surfaced
  // here too because this is where someone actually acts on it: without
  // this, the only warning sits above the fold and a person can go straight
  // to Send, wait out a call against a web page or a dead cold-started
  // container, and never connect the failure to the warning they skipped.
  endpointAdvice?: EndpointAdvice | null
}) {
  const example = JSON.stringify(tryIt.examplePayload, null, 2)
  const [method, setMethod] = useState<'POST' | 'GET'>('POST')
  const [body, setBody] = useState(example)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<TryItResult | null>(null)
  const isHtml = (result?.contentType || '').includes('text/html')
  const hint = result ? explain(result, result.method) : null

  // Keyed on content, so a reload of the same agent keeps what was typed.
  useEffect(() => {
    setBody(example)
    setResult(null)
    setError(null)
  }, [agentId, example])

  if (!tryIt.available) {
    return (
      <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600" data-testid="try-it-unavailable">
        <span className="font-medium text-gray-700">Try it is not available for this agent.</span> {tryIt.reason}
      </div>
    )
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
    try {
      setResult((await tryAgent(agentId, method, parsed)).data)
    } catch (e) {
      setResult(null)
      setError(errorMessage(e, 'The call could not be made'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3" data-testid="try-it">
      {endpointAdvice && (
        <div className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900" data-testid="try-it-endpoint-advice">
          <AlertTriangle size={14} className="shrink-0 mt-0.5 text-amber-600" />
          <span>
            <span className="font-medium">
              {endpointAdvice.looksLike === 'frontend' ? "This doesn't look like an API — " : 'This is a tracing endpoint, not an API — '}
            </span>
            calling it below will likely return {endpointAdvice.looksLike === 'frontend' ? 'a web page' : 'nothing useful'}, not data.
            See Contract above for where to find the real one.
          </span>
        </div>
      )}
      <div className="flex items-center gap-2 text-xs">
        <select className="input w-auto py-1.5" value={method} onChange={e => setMethod(e.target.value as 'POST' | 'GET')} aria-label="HTTP method">
          <option value="POST">POST</option>
          <option value="GET">GET</option>
        </select>
        <code className="flex-1 truncate rounded-lg bg-gray-50 px-3 py-2 font-mono text-gray-700" title={tryIt.url || ''}>{tryIt.url}</code>
      </div>

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
        <p className="text-xs text-gray-400">
          Sent from the registry server. Your login is not passed to the agent. Calls are logged without their
          content and limited per minute.
        </p>
        <button type="button" onClick={send} disabled={busy} className="btn-primary btn-sm flex items-center gap-1.5 shrink-0">
          <Send size={14} /> {busy ? 'Calling…' : 'Send'}
        </button>
      </div>

      {error && <div className="rounded-xl bg-rose-50 border border-rose-200 px-3 py-2 text-xs text-rose-700">{error}</div>}

      {result && (
        <div className="rounded-xl border border-gray-200 overflow-hidden" data-testid="try-it-result">
          <div className="flex flex-wrap items-center gap-2 bg-gray-50 px-3 py-2 text-xs">
            <span className="font-mono text-gray-500">{result.method}</span>
            {result.status != null
              ? <span className={result.ok ? 'status-complete' : 'status-failed'}>HTTP {result.status}</span>
              : <span className="status-failed">No response</span>}
            {result.latencyMs != null && <span className="text-gray-500">{result.latencyMs} ms</span>}
            {result.contentType && <span className="text-gray-400 truncate">{result.contentType}</span>}
          </div>
          {result.error && <div className="px-3 py-2 text-xs text-rose-700">{result.error}</div>}
          {result.location && (
            <div className="px-3 py-2 text-xs text-amber-700">Redirect to {result.location} was not followed.</div>
          )}
          {hint && <div className="px-3 py-2 text-xs text-amber-800 bg-amber-50 border-t border-amber-100">{hint}</div>}
          {result.body != null && pretty(result.body) !== '' && (
            isHtml ? (
              <details className="px-3 py-2 text-xs text-gray-600">
                <summary className="cursor-pointer select-none">Show the HTML that came back ({pretty(result.body).length.toLocaleString()} characters)</summary>
                <pre className="mt-2 max-h-56 overflow-auto font-mono whitespace-pre-wrap break-all text-gray-700">{pretty(result.body)}</pre>
              </details>
            ) : (
              <pre className="max-h-72 overflow-auto px-3 py-2 text-xs font-mono text-gray-800 whitespace-pre-wrap break-all">{pretty(result.body)}</pre>
            )
          )}
          {result.truncated && <div className="px-3 pb-2 text-xs text-gray-400">Response cut off at 64 KB.</div>}
        </div>
      )}
    </div>
  )
}
