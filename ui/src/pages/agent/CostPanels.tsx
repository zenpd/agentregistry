import { useCallback, useEffect, useState } from 'react'
import {
  addResourceLink, collectInfraCosts, deleteResourceLink, getInfraCostStatus, getInfraProfile, getResourceLinks, saveInfraProfile,
  type AgentEconomicsDetail, type InfraComponent, type InfraCostStatus, type InfraProfile, type JobRunSummary, type ResourceLink,
} from '../../services/ops/economics'
import { FieldLabel, SectionLabel, SourceBadge, fmtCents } from './shared'
import { Banner, RUN_STATUS_TEXT, SERIES, Swatch, Tile, errorMessage, fmtCost, fmtWhen } from './costUi'

// The cost side of an agent: token cost, hosting cost, where the money goes, and how hosting cost is set.
// Shown on the Tokenomics tab. The Business Value tab keeps one total cost figure and links here.

export function TokenTile({ econ }: { econ: AgentEconomicsDetail }) {
  const t = econ.token
  if (econ.tokenCostCents != null) {
    return (
      <Tile
        label="Token cost"
        value={fmtCost(econ.tokenCostCents)}
        sub={
          <>
            <SourceBadge source={econ.tokenSource} />
            {t.status === 'no_calls'
              ? <span>no LLM calls read this month</span>
              : <span>{fmtCost(t.monthToDateCents)} so far</span>}
            {t.pricing === 'partial' && <span className="text-amber-700">excludes unpriced {t.unpricedModels.join(', ')}</span>}
          </>
        }
      />
    )
  }
  if (t.pricing === 'missing') {
    return <Tile label="Token cost" muted value="Pricing not configured"
      sub={<><SourceBadge source={econ.tokenSource} /><span>no price for {t.unpricedModels.join(', ') || 'this model'}</span></>} />
  }
  if (t.status === 'awaiting_ingestion') {
    return <Tile label="Token cost" muted value="No usage data yet"
      sub={<span>Phoenix project <span className="font-mono">{t.phoenixProject}</span> not read yet — refresh on the Tokenomics tab</span>} />
  }
  return <Tile label="Token cost" muted value="No usage data" sub={<span>No tracing linked and no usage entered by hand</span>} />
}

export function CostBreakdown({ econ }: { econ: AgentEconomicsDetail }) {
  const token = econ.tokenCostCents ?? 0
  const infra = econ.infraCostCents
  const cost = token + infra
  const scale = Math.max(cost, econ.valueDeclared ? econ.valueCents : 0, 1)
  const parts = [
    { key: 'token', label: 'Token cost', cents: token, color: SERIES.token, known: econ.tokenCostCents != null, source: econ.tokenSource },
    { key: 'infra', label: 'Hosting cost', cents: infra, color: SERIES.infra, known: true, source: econ.infraSource },
  ]
  return (
    <section className="space-y-2">
      <SectionLabel>Where the money goes</SectionLabel>
      {cost <= 0 ? (
        <p className="text-xs text-slate-500">No cost recorded this month{econ.tokenCostCents == null ? ' (token cost unknown)' : ''}.</p>
      ) : (
        <div className="space-y-1.5">
          <BarRow label="Cost">
            {parts.filter(p => p.cents > 0).map(p => (
              <div key={p.key} className="h-full first:rounded-l last:rounded-r" title={`${p.label}: ${fmtCost(p.cents)}`}
                style={{ width: `${(p.cents / scale) * 100}%`, background: p.color }} />
            ))}
          </BarRow>
          {econ.valueDeclared && (
            <BarRow label="Value">
              <div className="h-full rounded" style={{ width: `${(econ.valueCents / scale) * 100}%`, background: SERIES.value }}
                title={`Value used: ${fmtCents(econ.valueCents)}`} />
            </BarRow>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-700">
        {parts.map(p => (
          <span key={p.key} className="inline-flex items-center gap-1.5">
            <Swatch color={p.color} />
            {p.label} <span className="font-medium text-slate-900">{p.known ? fmtCost(p.cents) : 'unknown'}</span>
            {cost > 0 && p.known && <span className="text-slate-500">({Math.round((p.cents / cost) * 100)}%)</span>}
            <SourceBadge source={p.source} />
          </span>
        ))}
        {econ.valueDeclared && (
          <span className="inline-flex items-center gap-1.5">
            <Swatch color={SERIES.value} /> Value used <span className="font-medium text-slate-900">{fmtCents(econ.valueCents)}</span>
          </span>
        )}
      </div>
    </section>
  )
}

function BarRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-10 shrink-0 text-[12px] uppercase text-slate-500">{label}</span>
      <div className="h-3 flex-1 rounded bg-gray-100 overflow-hidden flex gap-[2px]">{children}</div>
    </div>
  )
}

// ── Hosting & infrastructure ─────────────────────────────────────────────────

export function InfraPanel({ agentId, econ, onChanged }: { agentId: string; econ: AgentEconomicsDetail; onChanged: () => void }) {
  const [status, setStatus] = useState<InfraCostStatus | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)

  const loadStatus = useCallback(() => {
    getInfraCostStatus()
      .then(r => { setStatus(r.data); setStatusError(null) })
      .catch(e => setStatusError(errorMessage(e, 'Could not load the collector status')))
  }, [])

  useEffect(() => { loadStatus() }, [loadStatus])

  return (
    <section className="rounded-lg border border-gray-100 p-4 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-900">Hosting &amp; infrastructure</h3>
        <span className="text-[12px] text-slate-500">The registry uses the first that exists: metered (Azure), then declared by the owner, then the stage estimate</span>
      </div>
      <p className="text-xs text-slate-700 flex flex-wrap items-center gap-1.5">
        This month: <span className="font-semibold text-slate-900">{fmtCents(econ.infraCostCents)}</span>
        <SourceBadge source={econ.infraSource} />
        {econ.infraSource === 'metered' && econ.infra.meteredThrough && (
          <span className="text-slate-500">({fmtCents(econ.infra.meteredMonthToDateCents)} through {econ.infra.meteredThrough})</span>
        )}
        {econ.infraSource === 'estimate' && <span className="text-slate-500">flat {econ.stage} estimate — declare or meter the real cost</span>}
      </p>
      <CollectorStatus agentId={agentId} status={status} error={statusError} onCollected={() => { loadStatus(); onChanged() }} />
      {econ.infra.byResource.length > 0 && <MeteredResources econ={econ} />}
      <DeclaredInfraForm agentId={agentId} stage={econ.stage} estimateCents={econ.infra.estimateCents} onSaved={onChanged} />
      <ResourceLinks agentId={agentId} tagKey={status?.tagKey || 'agent-id'} />
    </section>
  )
}

function CollectorStatus({ agentId, status, error, onCollected }: {
  agentId: string
  status: InfraCostStatus | null
  error: string | null
  onCollected: () => void
}) {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<(JobRunSummary & { reason?: string }) | null>(null)
  const [runError, setRunError] = useState<string | null>(null)

  if (error) return <Banner tone="rose">{error}</Banner>
  if (!status) return <p className="text-xs text-slate-500">Loading collector status…</p>

  if (!status.configured) {
    return (
      <Banner tone="gray">
        <p><span className="font-semibold text-slate-700">Metered cost (Azure Cost Management): not configured.</span> Until it is,
          hosting cost is the owner's declared figure, else the stage estimate.</p>
        <ol className="list-decimal ml-4 mt-1.5 space-y-0.5 break-words">
          {status.setup.map(s => <li key={s}>{s}</li>)}
        </ol>
        {status.missing.length > 0 && (
          <p className="mt-1.5 break-all">Missing: {status.missing.map(m => <code key={m} className="mr-1.5 font-mono text-slate-700">{m}</code>)}</p>
        )}
      </Banner>
    )
  }

  const collect = async () => {
    setRunning(true)
    setRunError(null)
    try {
      const r = await collectInfraCosts(agentId)
      setResult(r.data)
      onCollected()
    } catch (e) {
      setRunError(errorMessage(e, 'Collection failed'))
    } finally {
      setRunning(false)
    }
  }

  const last = result || status.lastRun
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-700">
        <span>
          Azure Cost Management · scope <span className="font-mono text-slate-700">{status.scope}</span> · tag{' '}
          <span className="font-mono text-slate-700">{status.tagKey}</span>
        </span>
        <button onClick={collect} disabled={running} className="btn-secondary btn-sm"
          title="Read the last 7 days of actual cost for this agent (admin)">
          {running ? 'Reading Azure cost…' : 'Read Azure cost now'}
        </button>
      </div>
      {runError && <Banner tone="rose">{runError}</Banner>}
      {last ? (
        <p className="text-xs text-slate-600">
          Last run {fmtWhen(last.finishedAt || last.startedAt)}: {RUN_STATUS_TEXT[last.status] || last.status}
          {typeof last.summary?.reason === 'string' && <> — {last.summary.reason}</>}
          {typeof last.summary?.unallocated_cents === 'number' && last.summary.unallocated_cents > 0 &&
            <> · {fmtCents(last.summary.unallocated_cents)} unallocated</>}
        </p>
      ) : (
        <p className="text-xs text-slate-500">Not collected yet. The daily job reads cost once a day; Azure data lags 8–72 hours.</p>
      )}
    </div>
  )
}

function MeteredResources({ econ }: { econ: AgentEconomicsDetail }) {
  return (
    <div className="space-y-1">
      <FieldLabel>Metered this month, by resource</FieldLabel>
      <ul className="divide-y divide-gray-100 text-xs">
        {econ.infra.byResource.map(r => (
          <li key={r.resourceId} className="flex items-center justify-between gap-3 py-1">
            <span className="min-w-0 truncate font-mono text-slate-700" title={r.resourceId}>{r.resourceId.split('/').slice(-1)[0]}</span>
            <span className="shrink-0 text-slate-500">{r.serviceName || ''} · {r.allocation === 'link' ? 'linked' : 'tagged'}</span>
            <span className="shrink-0 font-medium text-slate-800">{fmtCents(r.cents)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ── Declared hosting cost ────────────────────────────────────────────────────

interface ComponentDraft { name: string; dollars: string; recurring: boolean }

function DeclaredInfraForm({ agentId, stage, estimateCents, onSaved }: {
  agentId: string
  stage: string
  estimateCents: number
  onSaved: () => void
}) {
  const [profile, setProfile] = useState<InfraProfile | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [platform, setPlatform] = useState('')
  const [resourceGroup, setResourceGroup] = useState('')
  const [monthly, setMonthly] = useState('')
  const [effectiveFrom, setEffectiveFrom] = useState('')
  const [components, setComponents] = useState<ComponentDraft[]>([])
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ tone: 'teal' | 'rose'; text: string } | null>(null)

  const fill = (p: InfraProfile) => {
    setProfile(p)
    setPlatform(p.platform || '')
    setResourceGroup(p.resourceGroup || '')
    setMonthly(p.declared && p.monthlyCostCents ? String(p.monthlyCostCents / 100) : '')
    setEffectiveFrom(p.effectiveFrom || '')
    setComponents(p.components.map(c => ({ name: c.name, dollars: c.costCents != null ? String(c.costCents / 100) : '', recurring: c.recurring })))
  }

  useEffect(() => {
    setProfile(null)
    getInfraProfile(agentId).then(r => { fill(r.data); setLoadError(null) }).catch(e => setLoadError(errorMessage(e, 'Could not load the hosting profile')))
  }, [agentId])

  const toCents = (text: string): number | null | 'invalid' => {
    if (!text.trim()) return null
    const n = Number(text)
    return Number.isFinite(n) && n >= 0 ? Math.round(n * 100) : 'invalid'
  }

  const save = async () => {
    const cents = toCents(monthly)
    const parts: InfraComponent[] = []
    for (const c of components) {
      if (!c.name.trim()) continue
      const cc = toCents(c.dollars)
      if (cc === 'invalid') return setMessage({ tone: 'rose', text: `"${c.name}": enter a cost of 0 or more.` })
      parts.push({ name: c.name.trim(), costCents: cc, recurring: c.recurring })
    }
    if (cents === 'invalid') return setMessage({ tone: 'rose', text: 'Monthly cost must be a number of 0 or more.' })
    setSaving(true)
    setMessage(null)
    try {
      const r = await saveInfraProfile(agentId, {
        platform: platform.trim() || null, resourceGroup: resourceGroup.trim() || null,
        monthlyCostCents: cents, components: parts, effectiveFrom: effectiveFrom || null,
      })
      fill(r.data)
      setMessage({ tone: 'teal', text: r.data.declared ? 'Saved. The declared cost is used when no metered cost exists.' : 'Saved. No monthly cost declared, so the stage estimate still applies.' })
      onSaved()
    } catch (e) {
      setMessage({ tone: 'rose', text: errorMessage(e, 'Save failed') })
    } finally {
      setSaving(false)
    }
  }

  const setComponent = (i: number, patch: Partial<ComponentDraft>) =>
    setComponents(cs => cs.map((c, j) => (j === i ? { ...c, ...patch } : c)))

  if (loadError) return <Banner tone="rose">{loadError}</Banner>
  if (!profile) return <p className="text-xs text-slate-500">Loading hosting profile…</p>

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <FieldLabel>Declared by owner</FieldLabel>
        <span className="text-[12px] text-slate-500">
          {profile.declared
            ? `${fmtCents(profile.monthlyCostCents)}/mo declared${profile.updatedBy ? ` by ${profile.updatedBy}` : ''}`
            : `Not declared — ${stage} estimate ${fmtCents(estimateCents)}/mo applies`}
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
        <label className="text-xs text-slate-600 space-y-1">
          <span>Platform</span>
          <input className="input w-full" value={platform} onChange={e => setPlatform(e.target.value)} placeholder="Azure Container Apps" maxLength={100} />
        </label>
        <label className="text-xs text-slate-600 space-y-1">
          <span>Resource group</span>
          <input className="input w-full" value={resourceGroup} onChange={e => setResourceGroup(e.target.value)} placeholder="rg-onboarding" maxLength={255} />
        </label>
        <label className="text-xs text-slate-600 space-y-1">
          <span>Monthly cost ($)</span>
          <input className="input w-full" type="number" min={0} step="0.01" value={monthly} onChange={e => setMonthly(e.target.value)} placeholder="blank = not declared" />
        </label>
        <label className="text-xs text-slate-600 space-y-1">
          <span>Effective from</span>
          <input className="input w-full" type="date" value={effectiveFrom} onChange={e => setEffectiveFrom(e.target.value)} />
        </label>
      </div>
      <div className="space-y-1">
        <span className="text-xs text-slate-600">Components</span>
        {components.length === 0 && <p className="text-[12px] text-slate-500">None listed.</p>}
        {components.map((c, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <input className="input flex-1 min-w-[10rem]" value={c.name} onChange={e => setComponent(i, { name: e.target.value })} placeholder="Component (e.g. Cosmos DB)" aria-label="Component name" maxLength={200} />
            <input className="input w-28" type="number" min={0} step="0.01" value={c.dollars} onChange={e => setComponent(i, { dollars: e.target.value })} placeholder="$" aria-label="Component cost in dollars" />
            <label className="text-xs text-slate-600 inline-flex items-center gap-1">
              <input type="checkbox" checked={!c.recurring} onChange={e => setComponent(i, { recurring: !e.target.checked })} /> one-time
            </label>
            <button type="button" className="text-xs text-slate-500 hover:text-rose-600" onClick={() => setComponents(cs => cs.filter((_, j) => j !== i))}>Remove</button>
          </div>
        ))}
        <button type="button" className="text-xs text-zen-700 hover:text-zen-800" onClick={() => setComponents(cs => [...cs, { name: '', dollars: '', recurring: true }])}>+ Add component</button>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={save} disabled={saving} className="btn-primary btn-sm">{saving ? 'Saving…' : 'Save hosting cost'}</button>
        <span className="text-[12px] text-slate-500">One-time components give the payback period; recurring ones are informational — the monthly cost is what counts.</span>
      </div>
      {message && <Banner tone={message.tone}>{message.text}</Banner>}
    </div>
  )
}

// ── Azure resource links ─────────────────────────────────────────────────────

const LINK_KIND: Record<string, string> = { subscription: 'Subscription', resource_group: 'Resource group', resource: 'Resource' }

function ResourceLinks({ agentId, tagKey }: { agentId: string; tagKey: string }) {
  const [links, setLinks] = useState<ResourceLink[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [resourceId, setResourceId] = useState('')
  const [share, setShare] = useState('100')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ tone: 'amber' | 'rose'; text: string } | null>(null)

  const load = useCallback(() => {
    getResourceLinks(agentId).then(r => { setLinks(r.data.links); setLoadError(null) })
      .catch(e => setLoadError(errorMessage(e, 'Could not load resource links')))
  }, [agentId])

  useEffect(() => { setLinks(null); load() }, [load])

  const add = async () => {
    const pct = Number(share)
    if (!resourceId.trim().toLowerCase().startsWith('/subscriptions/')) {
      return setMessage({ tone: 'rose', text: 'Paste a full Azure resource id starting with /subscriptions/.' })
    }
    if (!Number.isInteger(pct) || pct < 1 || pct > 100) return setMessage({ tone: 'rose', text: 'Share must be a whole number from 1 to 100.' })
    setBusy(true)
    setMessage(null)
    try {
      const r = await addResourceLink(agentId, resourceId.trim(), pct)
      setResourceId('')
      setShare('100')
      if (r.data.warning) setMessage({ tone: 'amber', text: r.data.warning })
      load()
    } catch (e) {
      setMessage({ tone: 'rose', text: errorMessage(e, 'Could not add the link') })
    } finally {
      setBusy(false)
    }
  }

  const remove = async (link: ResourceLink) => {
    if (!window.confirm(`Remove the link to ${link.resourceId}?`)) return
    setBusy(true)
    try {
      await deleteResourceLink(agentId, link.id)
      setMessage(null)
      load()
    } catch (e) {
      setMessage({ tone: 'rose', text: errorMessage(e, 'Could not remove the link') })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <FieldLabel>Linked Azure resources</FieldLabel>
        <span className="text-[12px] text-slate-500">
          Resources tagged <span className="font-mono">{tagKey}={agentId}</span> are found without a link; link shared ones with a share %.
        </span>
      </div>
      {loadError && <Banner tone="rose">{loadError}</Banner>}
      {!links && !loadError && <p className="text-xs text-slate-500">Loading…</p>}
      {links && links.length === 0 && <p className="text-xs text-slate-500">No linked resources.</p>}
      {links && links.length > 0 && (
        <ul className="divide-y divide-gray-100 text-xs">
          {links.map(l => (
            <li key={l.id} className="flex flex-wrap items-center gap-2 py-1.5">
              <span className="text-[12px] px-1.5 py-0.5 rounded-full ring-1 bg-gray-50 text-slate-700 ring-gray-200">{LINK_KIND[l.kind] || l.kind}</span>
              <span className="min-w-0 flex-1 truncate font-mono text-slate-700" title={l.resourceId}>{l.resourceId}</span>
              <span className="text-slate-800 font-medium">{l.sharePct}%</span>
              {l.totalClaimedPct > 100 && (
                <span className="text-amber-700" title="Shares are scaled down so no more than the real cost is allocated">⚠ {l.totalClaimedPct}% claimed in total</span>
              )}
              <button type="button" disabled={busy} className="text-slate-500 hover:text-rose-600" onClick={() => remove(l)}>Remove</button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <input className="input flex-1 min-w-[16rem] font-mono text-xs" value={resourceId} onChange={e => setResourceId(e.target.value)}
          placeholder="/subscriptions/<id>/resourceGroups/<rg>[/providers/…]" aria-label="Azure resource id" maxLength={500} />
        <input className="input w-20" type="number" min={1} max={100} step={1} value={share} onChange={e => setShare(e.target.value)} aria-label="Share percent" />
        <span className="text-xs text-slate-500">%</span>
        <button onClick={add} disabled={busy || !resourceId.trim()} className="btn-secondary btn-sm">Link resource</button>
      </div>
      {message && <Banner tone={message.tone}>{message.text}</Banner>}
    </div>
  )
}
