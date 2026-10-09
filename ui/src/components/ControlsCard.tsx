import { useEffect, useState } from 'react'
import { ShieldCheck } from 'lucide-react'
import { getControls, type Control } from '../services/ops/lifecycleSteps'
import InfoTip from './InfoTip'
import { errorMessage } from '../pages/agent/shared'

const STATE: Record<Control['state'], { label: string; cls: string }> = {
  enforced: { label: 'Enforced', cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  partly: { label: 'Enforced for some tiers', cls: 'bg-teal-50 text-teal-700 ring-teal-200' },
  recorded: { label: 'Recorded only', cls: 'bg-amber-50 text-amber-800 ring-amber-200' },
  off: { label: 'Off', cls: 'bg-slate-100 text-slate-700 ring-slate-200' },
}

// Settings → Controls: every rule the registry applies and whether it is enforced,
// read from the settings themselves.
export default function ControlsCard() {
  const [d, setD] = useState<{ controls: Control[]; counts: Record<string, number> } | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  useEffect(() => { getControls().then(r => setD(r.data)).catch(e => setMsg(errorMessage(e, 'Could not load the controls'))) }, [])
  if (!d) return <div className="card p-6 text-sm text-slate-600">{msg ?? 'Loading controls…'}</div>
  return (
    <div className="card p-6 space-y-3" data-testid="controls">
      <div className="flex items-start gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-emerald-50 text-emerald-600"><ShieldCheck size={20} /></div>
        <div>
          <h3 className="text-[16px] font-extrabold text-slate-900">Controls <InfoTip term="controls" /></h3>
          <p className="text-[13px] text-slate-600">
            {d.counts.enforced} enforced, {d.counts.partly || 0} enforced for some risk tiers, {d.counts.recorded} recorded only, {d.counts.off} off.
            Read from the current settings each time this page opens.
          </p>
        </div>
      </div>
      <table className="w-full text-[13px]">
        <thead><tr className="text-left text-slate-600 border-b"><th className="py-1.5">Control</th><th>State</th><th>What it does now</th><th>Set in</th></tr></thead>
        <tbody>
          {d.controls.map(c => (
            <tr key={c.key} className="border-b border-slate-100 align-top" data-testid="control-row">
              <td className="py-1.5 pr-2 font-medium text-slate-900">{c.name}</td>
              <td className="pr-2"><span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-[12px] font-semibold ring-1 ${STATE[c.state].cls}`}>{STATE[c.state].label}</span></td>
              <td className="pr-2 text-slate-700">{c.detail}</td>
              <td className="text-slate-600">{c.where}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
