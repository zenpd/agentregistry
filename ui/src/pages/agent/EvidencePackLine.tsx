import { useState } from 'react'
import { agentEvidencePack, saveBlob } from '../../services/ops/compliance'

// Governance tab → Evidence pack: everything the registry holds on this agent (record,
// classification, reviews and checklists, waivers, risks, controls, versions, incidents,
// sealed decisions) as one PDF or CSV. The file's SHA-256 is recorded in the audit trail.
export default function EvidencePackLine({ agentId }: { agentId: string }) {
  const [hash, setHash] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  async function get(format: 'pdf' | 'csv') {
    setBusy(true)
    try {
      const r = await agentEvidencePack(agentId, format)
      saveBlob(r.data as Blob, `evidence-${agentId}.${format}`)
      setHash((r.headers['x-evidence-sha256'] as string) || null)
    } finally { setBusy(false) }
  }
  return (
    <div className="flex flex-wrap items-baseline gap-x-2" data-testid="evidence-pack">
      <span className="text-slate-500 w-20 shrink-0">Evidence</span>
      <span className="text-slate-600 flex-1 min-w-[240px]">
        Download everything the registry holds on this agent for an auditor:{' '}
        <button type="button" className="text-zen-700 hover:underline" disabled={busy} onClick={() => get('pdf')} data-testid="evidence-pdf">PDF</button>{' or '}
        <button type="button" className="text-zen-700 hover:underline" disabled={busy} onClick={() => get('csv')}>CSV</button>.
        {hash && <span className="block text-slate-700" data-testid="evidence-hash">SHA-256 {hash}, recorded in the audit trail. Compliance → Check an evidence file confirms a copy is unchanged.</span>}
      </span>
    </div>
  )
}
