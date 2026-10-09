import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, Download, FileSearch, Link2, ShieldCheck, XCircle } from 'lucide-react'
import {
  checkExport, controlEvidence, dataReportCsv, getDataReport, getPack, getPacks, grcExport, saveBlob, sha256Hex, updatePackDates,
  verifyDecisionLog, type ChainCheck, type ControlRow, type DataRow, type PackSummary,
} from '../services/ops/compliance'
import InfoTip from '../components/InfoTip'
import { can, useMe } from '../lib/me'
import { errorMessage } from './agent/shared'

const STATUS: Record<ControlRow['status'], { label: string; cls: string }> = {
  evidenced: { label: 'Evidenced', cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  missing: { label: 'Evidence missing', cls: 'bg-amber-50 text-amber-800 ring-amber-200' },
  outside: { label: 'Kept outside the registry', cls: 'bg-slate-100 text-slate-700 ring-slate-200' },
  not_applicable: { label: 'No agent in scope', cls: 'bg-slate-50 text-slate-500 ring-slate-200' },
}
const fmtDate = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })

// Compliance: how much of each framework the registry holds evidence for, with the
// gaps named per agent, evidence exports, the decision log check, the data and
// retention report and the GRC export.
export default function CompliancePage() {
  const me = useMe()
  const [packs, setPacks] = useState<Awaited<ReturnType<typeof getPacks>>['data'] | null>(null)
  const [key, setKey] = useState('iso_42001')
  const [pack, setPack] = useState<Awaited<ReturnType<typeof getPack>>['data'] | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => getPacks().then(r => setPacks(r.data)).catch(e => setError(errorMessage(e, 'Could not load the compliance packs'))), [])
  useEffect(() => { load() }, [load])
  useEffect(() => { setPack(null); getPack(key).then(r => setPack(r.data)).catch(e => setError(errorMessage(e, 'Could not load the pack'))) }, [key])

  if (error) return <div className="p-8 text-center text-rose-600">{error}</div>
  if (!packs) return <div className="p-8 text-center text-slate-600">Checking every agent against each compliance pack (EU AI Act, ISO 42001, NIST AI RMF, India DPDP)…</div>
  return (
    <div className="space-y-5 animate-fade-in max-w-6xl" data-testid="compliance-page">
      <div>
        <h1 className="text-2xl font-bold gradient-text">Compliance <InfoTip term="compliance_pack" /></h1>
        <p className="text-slate-600 mt-0.5">{packs.meaning} Checked across {packs.agents} agents that are not retired.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3" role="tablist" aria-label="Packs">
        {packs.packs.map(p => (
          <button key={p.key} type="button" role="tab" aria-selected={key === p.key} onClick={() => setKey(p.key)} data-testid={`pack-${p.key}`}
            className={`card p-4 text-left ${key === p.key ? 'ring-2 ring-zen-400' : ''}`}>
            <div className="text-xs uppercase tracking-wide text-slate-600">{p.name}</div>
            <div className="mt-1 text-xl font-bold text-slate-900">{p.evidenced} of {p.total} controls evidenced</div>
            <div className="mt-1 text-xs text-slate-600">{p.missing} with evidence missing, {p.outside} kept outside the registry{p.notApplicable ? `, ${p.notApplicable} with no agent in scope` : ''}.</div>
          </button>
        ))}
      </div>

      {pack && (
        <div className="card p-5 space-y-3" data-testid="pack-detail">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h2 className="font-semibold text-slate-900">{pack.name} <span className="text-[13px] font-normal text-slate-500">({pack.source})</span></h2>
              <p className="text-[13px] text-slate-700" data-testid="pack-summary">{pack.name}: {pack.evidenced} of {pack.total} controls evidenced.</p>
            </div>
            <DatesEditor pack={pack} canEdit={can(me, 'admin')} onSaved={load} />
          </div>
          <table className="w-full text-[13px]">
            <thead><tr className="text-left text-slate-600 border-b"><th className="py-1.5">Control</th><th>Status</th><th>Applies to</th><th>Agents missing evidence</th><th /></tr></thead>
            <tbody>
              {pack.controls.map(c => (
                <ControlLine key={c.id} c={c} packKey={pack.key} open={open === c.id} onToggle={() => setOpen(open === c.id ? null : c.id)} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <DecisionLogCard />
        <ExportCheckCard />
      </div>
      <DataReportCard />
      <GrcExportCard />
    </div>
  )
}

function DatesEditor({ pack, canEdit, onSaved }: { pack: PackSummary; canEdit: boolean; onSaved: () => void }) {
  const [editing, setEditing] = useState(false)
  const [values, setValues] = useState<Record<string, string>>({})
  const [msg, setMsg] = useState<string | null>(null)
  const today = new Date().toISOString().slice(0, 10)
  return (
    <div className="text-[12.5px] text-slate-600 min-w-[280px]" data-testid="pack-dates">
      <div className="font-semibold text-slate-800">Dates <span className="font-normal text-slate-500">(default dates: verify them against the official texts)</span></div>
      <ul>
        {pack.dates.map(d => (
          <li key={d.key}>
            {editing
              ? <label className="flex items-center gap-2">{d.label}<input type="date" className="input !w-40 !py-0.5 text-xs" value={values[d.key] ?? d.date} onChange={e => setValues({ ...values, [d.key]: e.target.value })} /></label>
              : <>{d.label}: {d.date ? <b className={d.date <= today ? 'text-slate-900' : 'text-zen-700'}>{fmtDate(d.date)}{d.date > today ? ' (in the future)' : ''}</b> : 'not set'}</>}
          </li>
        ))}
      </ul>
      {canEdit && !editing && <button type="button" className="text-zen-700 hover:underline" onClick={() => { setValues({}); setEditing(true) }}>Change the dates</button>}
      {editing && (
        <span className="flex gap-2 mt-1">
          <button type="button" className="btn-primary btn-sm" onClick={async () => {
            try { await updatePackDates({ [pack.key]: Object.fromEntries(pack.dates.map(d => [d.key, values[d.key] ?? d.date])) }); setEditing(false); onSaved(); setMsg('Saved.') }
            catch (e) { setMsg(errorMessage(e, 'Not saved')) }
          }}>Save</button>
          <button type="button" className="btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancel</button>
        </span>
      )}
      {msg && <span className="block">{msg}</span>}
    </div>
  )
}

function ControlLine({ c, packKey, open, onToggle }: { c: ControlRow; packKey: string; open: boolean; onToggle: () => void }) {
  async function download(format: 'csv' | 'pdf') {
    const r = await controlEvidence(packKey, c.id, format)
    saveBlob(r.data as Blob, `${packKey}-${c.id.replace(/[^A-Za-z0-9]+/g, '-')}.${format}`)
  }
  const s = STATUS[c.status]
  return (
    <>
      <tr className="border-b border-slate-100 align-top" data-testid="control-line">
        <td className="py-1.5 pr-2"><button type="button" className="text-left hover:text-zen-700" onClick={onToggle}><b>{c.id}</b> {c.title}</button></td>
        <td className="pr-2"><span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-[12px] font-semibold ring-1 ${s.cls}`}>{s.label}</span></td>
        <td className="pr-2 text-slate-600">{c.appliesText} ({c.agentsInScope})</td>
        <td className="pr-2">{c.status === 'missing' ? (c.agentsMissing ? `${c.agentsMissing} of ${c.agentsInScope}` : 'Registry rule off') : '—'}</td>
        <td className="whitespace-nowrap text-right">
          <button type="button" className="btn-ghost btn-sm" onClick={() => download('csv')} title="Evidence of this control, per agent">CSV</button>
          <button type="button" className="btn-ghost btn-sm" onClick={() => download('pdf')}>PDF</button>
        </td>
      </tr>
      {open && (
        <tr className="border-b border-slate-100 bg-slate-50/60">
          <td colSpan={5} className="px-3 py-2 text-[12.5px] text-slate-700 space-y-1">
            {c.outside ? <p>{c.outside}</p> : <p>Evidence required: {c.evidence.join('. ')}.</p>}
            {c.registryMissing.length > 0 && <p className="text-amber-800">Registry rule off: {c.registryMissing.join(', ')} (Settings → Controls).</p>}
            {c.agents.filter(x => x.status === 'missing').map(x => (
              <p key={x.agentId}><Link to={`/agents/${x.agentId}?tab=governance`} className="font-medium text-zen-700 hover:underline">{x.name}</Link>: {x.missing.join('. ')}.</p>
            ))}
          </td>
        </tr>
      )}
    </>
  )
}

function DecisionLogCard() {
  const [r, setR] = useState<ChainCheck | null>(null)
  const [busy, setBusy] = useState(false)
  const run = () => { setBusy(true); verifyDecisionLog().then(x => setR(x.data)).finally(() => setBusy(false)) }
  useEffect(run, [])
  return (
    <div className="card p-5 space-y-2" data-testid="decision-log">
      <h2 className="font-semibold text-slate-900 flex items-center gap-2"><Link2 size={16} /> Decision log <InfoTip term="decision_chain" /></h2>
      {r && (r.ok
        ? <p className="flex items-start gap-2 text-[13px] text-emerald-800"><CheckCircle2 size={16} className="mt-0.5" /> All {r.entries} sealed decisions match. Last hash {r.lastHash?.slice(0, 16)}…</p>
        : <p className="flex items-start gap-2 text-[13px] text-rose-700"><XCircle size={16} className="mt-0.5" /> Entry {r.firstBroken?.seq} (audit row {r.firstBroken?.auditId}): {r.firstBroken?.problem}. Every entry after it is in doubt.</p>)}
      {r?.sealingSince && <p className="text-[12.5px] text-slate-600">Sealing started {fmtDate(r.sealingSince)}. Decisions made before were sealed as they stood then.</p>}
      <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={run}>{busy ? 'Checking…' : 'Check again'}</button>
    </div>
  )
}

function ExportCheckCard() {
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  async function check(file: File) {
    const hex = await sha256Hex(await file.arrayBuffer())
    const r = (await checkExport(hex)).data
    setMsg(r.found ? { ok: true, text: `Unchanged: this is the ${r.format} "${r.what}" exported by ${r.by} on ${fmtDate(r.exportedAt!)}.` }
      : { ok: false, text: `No export with this content is recorded (SHA-256 ${hex.slice(0, 16)}…). The file was changed, or it did not come from the registry.` })
  }
  return (
    <div className="card p-5 space-y-2" data-testid="export-check">
      <h2 className="font-semibold text-slate-900 flex items-center gap-2"><FileSearch size={16} /> Check an evidence file</h2>
      <p className="text-[13px] text-slate-600">Every evidence export records the SHA-256 of the file in the audit trail. Choose a file to see whether it is unchanged since it was exported. The file is not uploaded: only its hash is sent.</p>
      <input type="file" className="text-[13px]" onChange={e => e.target.files?.[0] && check(e.target.files[0])} data-testid="check-file" />
      {msg && <p className={`text-[13px] ${msg.ok ? 'text-emerald-700' : 'text-rose-700'}`} role="status">{msg.text}</p>}
    </div>
  )
}

function DataReportCard() {
  const [d, setD] = useState<{ rows: DataRow[]; summary: Record<string, number>; note: string } | null>(null)
  useEffect(() => { getDataReport().then(r => setD(r.data)).catch(() => setD(null)) }, [])
  if (!d) return null
  return (
    <div className="card p-5 space-y-2" data-testid="data-report">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold text-slate-900">Personal data and how long it is kept</h2>
        <button type="button" className="btn-secondary btn-sm" onClick={async () => saveBlob((await dataReportCsv()).data as Blob, 'data-and-retention.csv')}><Download size={14} /> CSV</button>
      </div>
      <p className="text-[13px] text-slate-600">
        {d.summary.personal} agents use personal data, {d.summary.special} special category data, {d.summary.none} none, and {d.summary.unknown} are not recorded yet. {d.note}
      </p>
      <table className="w-full text-[13px]">
        <thead><tr className="text-left text-slate-600 border-b"><th className="py-1.5">Agent</th><th>Business unit</th><th>Personal data</th><th>Kept for</th><th>People affected</th><th>Confirmed by</th></tr></thead>
        <tbody>
          {d.rows.map(r => (
            <tr key={r.agentId} className="border-b border-slate-100">
              <td className="py-1.5"><Link to={`/agents/${r.agentId}?tab=governance`} className="text-zen-700 hover:underline">{r.name}</Link></td>
              <td>{r.unit}</td><td className={r.dataKey ? '' : 'text-amber-800'}>{r.data}</td><td>{r.retention}</td><td>{r.affects}</td>
              <td>{r.confirmedBy ? `${r.confirmedBy}, ${r.confirmedAt}` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function GrcExportCard() {
  const [tool, setTool] = useState('servicenow')
  return (
    <div className="card p-5 space-y-2" data-testid="grc-export">
      <h2 className="font-semibold text-slate-900 flex items-center gap-2"><ShieldCheck size={16} /> Export to a GRC tool</h2>
      <p className="text-[13px] text-slate-600">CSV files for the import step of ServiceNow, OneTrust or Archer: the agent inventory, and every pack control with its status and the agents missing evidence. Map the columns in the tool's import step.</p>
      <div className="flex flex-wrap items-center gap-2">
        <select className="input !w-48 text-sm" value={tool} onChange={e => setTool(e.target.value)} aria-label="GRC tool">
          <option value="servicenow">ServiceNow</option><option value="onetrust">OneTrust</option><option value="archer">Archer</option>
        </select>
        <button type="button" className="btn-secondary btn-sm" data-testid="grc-inventory" onClick={async () => saveBlob((await grcExport(tool, 'inventory')).data as Blob, `${tool}-inventory.csv`)}><Download size={14} /> Agent inventory</button>
        <button type="button" className="btn-secondary btn-sm" data-testid="grc-controls" onClick={async () => saveBlob((await grcExport(tool, 'controls')).data as Blob, `${tool}-controls.csv`)}><Download size={14} /> Controls and evidence</button>
      </div>
    </div>
  )
}
