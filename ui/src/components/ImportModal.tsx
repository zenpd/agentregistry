import { useState } from 'react'
import { Link } from 'react-router-dom'
import { commitImport, downloadImportTemplate, previewImport, type ImportRow } from '../services/ops/bulkImport'
import { errorMessage } from '../pages/agent/shared'

const ACTION: Record<ImportRow['action'], string> = {
  create: 'bg-emerald-50 text-emerald-700 ring-emerald-200', skip: 'bg-slate-100 text-slate-700 ring-slate-200', error: 'bg-rose-50 text-rose-700 ring-rose-200',
}

// Register many agents from a CSV file: preview what each row does, then create.
export default function ImportModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [text, setText] = useState('')
  const [fileName, setFileName] = useState('')
  const [rows, setRows] = useState<ImportRow[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [result, setResult] = useState<Awaited<ReturnType<typeof commitImport>>['data'] | null>(null)

  async function pick(f: File | undefined) {
    if (!f) return
    setFileName(f.name); setRows(null); setResult(null); setMsg(null)
    const t = await f.text(); setText(t)
    setBusy(true)
    try { setRows((await previewImport(t)).data.rows) } catch (e) { setMsg(errorMessage(e, 'The file could not be read')) } finally { setBusy(false) }
  }

  async function commit() {
    setBusy(true)
    try { setResult((await commitImport(text)).data); onDone() } catch (e) { setMsg(errorMessage(e, 'The import failed')) } finally { setBusy(false) }
  }

  const creates = rows?.filter(r => r.action === 'create').length ?? 0
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" role="dialog" aria-label="Import agents">
      <div className="max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-2xl bg-white p-6 shadow-xl space-y-4" data-testid="import-modal">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-lg font-bold text-slate-900">Import agents from a CSV file</h2>
            <p className="text-[13px] text-slate-600">Each row becomes a new agent at the stage it names. An agent already registered under the same name or Phoenix project is skipped, never changed. Lists (capabilities, inputs, outputs, MCP servers, knowledge bases) are separated by |.</p>
          </div>
          <button type="button" className="text-slate-500 hover:text-slate-900" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className="btn-secondary btn-sm" onClick={() => downloadImportTemplate().catch(e => setMsg(errorMessage(e, 'Download failed')))}>Download the template</button>
          <label className="btn-primary btn-sm cursor-pointer">Choose a CSV file<input type="file" accept=".csv,text/csv" className="hidden" onChange={e => pick(e.target.files?.[0])} data-testid="import-file" /></label>
          {fileName && <span className="text-[13px] text-slate-700">{fileName}</span>}
        </div>
        {msg && <p className="text-[13px] text-rose-700">{msg}</p>}
        {rows && !result && (
          <>
            <p className="text-[13px] text-slate-700" data-testid="import-summary">{creates} to create · {rows.filter(r => r.action === 'skip').length} skipped · {rows.filter(r => r.action === 'error').length} with a problem. Nothing is saved until you press Create.</p>
            <table className="w-full text-[13px]">
              <thead><tr className="text-left text-slate-600 border-b"><th className="py-1.5">Line</th><th>Name</th><th>Stage</th><th>What happens</th></tr></thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.line} className="border-b last:border-0 align-top">
                    <td className="py-1.5">{r.line}</td><td className="font-medium text-slate-900">{r.name}</td><td>{r.stage}</td>
                    <td><span className={`rounded-full px-2 py-0.5 text-[11.5px] font-bold ring-1 ${ACTION[r.action]}`}>{r.action}</span> <span className="text-slate-700">{r.reason}</span>
                      {r.matchedAgentId && <> <Link to={`/agents/${r.matchedAgentId}`} className="text-zen-700 hover:underline">open it</Link></>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex gap-2">
              <button type="button" className="btn-primary btn-sm" disabled={busy || creates === 0} onClick={commit} data-testid="import-commit">{busy ? 'Creating…' : `Create ${creates} agent${creates === 1 ? '' : 's'}`}</button>
              <button type="button" className="btn-secondary btn-sm" onClick={onClose}>Cancel</button>
            </div>
          </>
        )}
        {result && (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[13px] text-emerald-900" data-testid="import-result">
            Created {result.created.length} agent{result.created.length === 1 ? '' : 's'}{result.failed.length ? `, ${result.failed.length} failed` : ''}.
            <ul className="mt-1">{result.created.map(c => <li key={c.id}><Link to={`/agents/${c.id}`} className="hover:underline">{c.name}</Link></li>)}</ul>
            {result.failed.map(f => <div key={f.line} className="text-rose-700">Line {f.line} ({f.name}): {f.reason}</div>)}
          </div>
        )}
      </div>
    </div>
  )
}
