import { useCallback, useEffect, useRef, useState, type ChangeEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Agent, GraphV2Response } from '../../services/api'
import {
  confirmContextSuggestion,
  dismissContextSuggestion,
  downloadAgentContext,
  getAgentContext,
  getAgentOverview,
  getContextTemplate,
  getContextVersion,
  saveAgentContext,
  type AgentContext,
  type AgentOverview,
  type ContextInsight,
  type ContextSummary,
  type ContextVersion,
  type DeclaredField,
  type GateKey,
  type LlmStatus,
  type OverviewFacts,
  type OverviewHeader,
  type SuggestionType,
} from '../../services/ops/overview'
import {
  CATEGORY_LABELS,
  Loading,
  SEVERITIES,
  SEVERITY_PILL,
  SectionLabel,
  SourceBadge,
  fmtCents,
  fmtNumber,
  type TabProps,
} from './shared'

const GATES: { key: GateKey; label: string }[] = [
  { key: 'arb', label: 'ARB' },
  { key: 'security', label: 'Security' },
  { key: 'dp', label: 'Data Protection' },
]

const GATE_PILL: Record<string, string> = {
  'Not Submitted': 'bg-gray-100 text-gray-600 ring-gray-200',
  'In Review': 'bg-violet-50 text-violet-700 ring-violet-200',
  'Changes Requested': 'bg-rose-50 text-rose-700 ring-rose-200',
  'Approved with Conditions': 'bg-amber-50 text-amber-700 ring-amber-200',
  'Approved (expired)': 'bg-rose-50 text-rose-700 ring-rose-200',
  Approved: 'bg-teal-50 text-teal-700 ring-teal-200',
}

const APPROVED = ['Approved', 'Approved with Conditions']

const BUDGET_STATE: Record<string, { label: string; className: string }> = {
  on_track: { label: 'On track', className: 'text-teal-700' },
  at_threshold: { label: 'At alert threshold', className: 'text-amber-700' },
  over_budget: { label: 'Over budget', className: 'text-rose-700' },
  no_usage_data: { label: 'No usage data', className: 'text-gray-400' },
}

const FRESHNESS_PILL: Record<string, string> = {
  fresh: 'bg-teal-50 text-teal-700 ring-teal-200',
  aging: 'bg-amber-50 text-amber-700 ring-amber-200',
  stale: 'bg-rose-50 text-rose-700 ring-rose-200',
}

const FIELD_LABEL: Record<DeclaredField, string> = {
  enterprise_systems: 'Enterprise system',
  databases: 'Database',
  knowledge_bases: 'Knowledge base',
  mcp_servers: 'MCP server',
  calls: 'Calls agent',
}

const LLM_NOTE: Partial<Record<LlmStatus, string>> = {
  unavailable: 'Generated summary unavailable: Azure OpenAI could not be reached. The rule-based checks below do not need it.',
  not_configured: 'Generated summary not configured (no Azure OpenAI credentials). The rule-based checks below do not need it.',
}

const MARKDOWN_CLASS =
  'text-sm text-gray-700 space-y-2 break-words [&_h1]:text-base [&_h1]:font-semibold [&_h1]:text-gray-900 ' +
  '[&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-gray-900 [&_h2]:pt-2 [&_h3]:font-semibold [&_h3]:text-gray-800 ' +
  '[&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5 [&_a]:text-teal-600 [&_a]:underline ' +
  '[&_code]:font-mono [&_code]:text-xs [&_code]:bg-gray-100 [&_code]:px-1 [&_code]:rounded ' +
  '[&_pre]:bg-gray-50 [&_pre]:p-2 [&_pre]:rounded [&_pre]:overflow-x-auto [&_table]:text-xs [&_table]:border-collapse ' +
  '[&_th]:border [&_th]:border-gray-200 [&_th]:bg-gray-50 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left ' +
  '[&_td]:border [&_td]:border-gray-200 [&_td]:px-2 [&_td]:py-1 ' +
  '[&_blockquote]:border-l-2 [&_blockquote]:border-gray-200 [&_blockquote]:pl-3 [&_blockquote]:text-gray-500'

const UPLOAD_ACCEPT = '.md,.markdown,.txt,text/markdown,text/plain'

function errorMessage(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d: any) => d.msg || String(d)).join('; ')
  return e?.message || fallback
}

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function relTime(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function Pill({ className, children }: { className: string; children: ReactNode }) {
  return <span className={`text-[10px] px-1.5 py-0.5 rounded-full ring-1 whitespace-nowrap ${className}`}>{children}</span>
}

function ErrorLine({ text, onRetry }: { text: string | null; onRetry?: () => void }) {
  if (!text) return null
  return (
    <p className="text-xs text-rose-600">
      {text}
      {onRetry && <button onClick={onRetry} className="ml-2 underline text-rose-700">Retry</button>}
    </p>
  )
}

function Markdown({ text }: { text: string }) {
  return (
    <div className={MARKDOWN_CLASS}>
      {/* skipHtml: raw HTML in the document is dropped, never rendered. */}
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{ a: ({ node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" /> }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}

// ── Header KPI strip ────────────────────────────────────────────────────────

function Tile({ label, to, children }: { label: string; to?: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50/60 p-3 space-y-1.5 min-w-0">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] uppercase tracking-wide text-gray-400">{label}</span>
        {to && <Link to={to} className="text-[10px] text-teal-600 hover:underline">Open</Link>}
      </div>
      {children}
    </div>
  )
}

function RiskTile({ header, agentId }: { header: OverviewHeader; agentId: string }) {
  const { worst, openCounts, total } = header.riskScore
  const counts = [...SEVERITIES].reverse().filter(s => openCounts[s])
  return (
    <Tile label="Open risks" to={`/agents/${agentId}?tab=risk`}>
      {total === 0 || !worst ? (
        <p className="text-sm font-semibold text-teal-700">None open</p>
      ) : (
        <div className="flex items-center gap-2">
          <span className="text-lg font-bold text-gray-900">{total}</span>
          <Pill className={SEVERITY_PILL[worst] || SEVERITY_PILL.LOW}>worst {worst}</Pill>
        </div>
      )}
      {counts.length > 0 && (
        <p className="text-[11px] text-gray-500">{counts.map(s => `${openCounts[s]} ${s.toLowerCase()}`).join(' · ')}</p>
      )}
      <p className="text-[10px] text-gray-400">Declared risk level: {header.riskLevel || '—'}</p>
    </Tile>
  )
}

function GatesTile({ header, agentId }: { header: OverviewHeader; agentId: string }) {
  const approved = GATES.filter(g => APPROVED.includes(header.gates[g.key])).length
  return (
    <Tile label="Governance gates" to={`/agents/${agentId}?tab=governance`}>
      <p className={`text-sm font-semibold ${approved === GATES.length ? 'text-teal-700' : 'text-gray-900'}`}>
        {approved} of {GATES.length} approved
      </p>
      <div className="flex flex-wrap gap-1">
        {GATES.map(g => {
          const status = header.gates[g.key] || 'Not Submitted'
          return (
            <span key={g.key} title={`${g.label}: ${status}`}>
              <Pill className={GATE_PILL[status] || GATE_PILL['Not Submitted']}>{g.label}: {status}</Pill>
            </span>
          )
        })}
      </div>
    </Tile>
  )
}

function BudgetTile({ header, agentId }: { header: OverviewHeader; agentId: string }) {
  const b = header.budget
  return (
    <Tile label="Budget (month to date)" to={`/agents/${agentId}?tab=tokenomics`}>
      {!b ? (
        <p className="text-sm text-gray-400">No budget set</p>
      ) : (
        <>
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-sm font-semibold ${BUDGET_STATE[b.state]?.className || 'text-gray-900'}`}>
              {BUDGET_STATE[b.state]?.label || b.state}
            </span>
            {b.usedPct != null && <span className="text-xs font-mono text-gray-600">{b.usedPct}%</span>}
            <SourceBadge source={b.source} />
          </div>
          {b.state === 'no_usage_data' ? (
            <p className="text-[11px] text-gray-500">Budget {fmtCents(b.monthlyBudgetCents)}; nothing to measure against yet</p>
          ) : (
            <p className="text-[11px] text-gray-500 font-mono">{fmtCents(b.mtdCents)} of {fmtCents(b.monthlyBudgetCents)}</p>
          )}
          {b.unpriced.length > 0 && <p className="text-[10px] text-amber-700">Unpriced model: {b.unpriced.join(', ')}</p>}
        </>
      )}
      <p className="text-[10px] text-gray-400">Visibility only, never enforced</p>
    </Tile>
  )
}

function TelemetryTile({ header, agentId }: { header: OverviewHeader; agentId: string }) {
  const t = header.telemetry
  return (
    <Tile label="Telemetry" to={`/agents/${agentId}?tab=diagram`}>
      <div className="flex items-center gap-2 flex-wrap">
        <SourceBadge source={t.source} />
        {t.freshness && <Pill className={FRESHNESS_PILL[t.freshness]}>{t.freshness}</Pill>}
      </div>
      {t.status === 'not_linked' && (
        <p className="text-[11px] text-gray-500">No Phoenix project linked, so no usage data. Link one on the Diagram tab.</p>
      )}
      {t.status === 'no_usage_yet' && (
        <p className="text-[11px] text-gray-500">
          Linked to <span className="font-mono">{t.phoenixProject}</span>; no usage ingested yet.
        </p>
      )}
      {t.status === 'demo' && (
        <p className="text-[11px] text-gray-500">
          Showing demo usage, not real traces.{t.linked ? '' : ' No Phoenix project linked.'}
        </p>
      )}
      {t.status === 'ok' && (
        <p className="text-[11px] text-gray-500">
          <span className="font-mono">{t.phoenixProject}</span> · ingested {relTime(t.lastIngestedAt)}
          {t.lastActivityDate && <> · last activity {t.lastActivityDate}</>}
        </p>
      )}
    </Tile>
  )
}

function KpiStrip({ overview, error, onRetry, agentId }: {
  overview: AgentOverview | null; error: string | null; onRetry: () => void; agentId: string
}) {
  if (!overview) {
    return (
      <div className="rounded-lg border border-rose-100 bg-rose-50/50 p-3">
        <ErrorLine text={error || 'Overview unavailable'} onRetry={onRetry} />
      </div>
    )
  }
  const h = overview.header
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <RiskTile header={h} agentId={agentId} />
      <GatesTile header={h} agentId={agentId} />
      <BudgetTile header={h} agentId={agentId} />
      <TelemetryTile header={h} agentId={agentId} />
    </div>
  )
}

// ── Key facts ───────────────────────────────────────────────────────────────

function Fact({ label, children, wide }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className={wide ? 'col-span-2 md:col-span-3' : ''}>
      <SectionLabel>{label}</SectionLabel>
      <div className="text-sm text-gray-900">{children}</div>
    </div>
  )
}

function FactsGrid({ agent, facts }: { agent: Agent; facts: OverviewFacts | null }) {
  const model = facts?.modelName ?? agent.modelName
  const provider = facts?.modelProvider
  const endpoint = facts?.apiEndpoint ?? agent.apiEndpoint
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
      <Fact label="Owner">
        {agent.owner || 'Unassigned'}
        {agent.ownerContact && <span className="block text-xs text-gray-500">{agent.ownerContact}</span>}
      </Fact>
      <Fact label="Department">{facts?.dept ?? agent.dept ?? '—'}</Fact>
      <Fact label="Type">{agent.aiType || '—'}</Fact>
      <Fact label="Model">
        {model ? <span className="font-mono">{model}</span> : '—'}
        {provider && <span className="block text-xs text-gray-500">{provider}</span>}
      </Fact>
      <Fact label="Value">
        {agent.valueAmount ? <span className="font-mono">${(agent.valueAmount / 1000).toFixed(0)}K/mo</span> : 'Not declared'}
        {agent.valueType && <span className="block text-xs text-gray-500">{agent.valueType}</span>}
      </Fact>
      <Fact label="Hours saved">{agent.hoursSavedMonthly ? `${fmtNumber(agent.hoursSavedMonthly)} h/mo` : 'Not declared'}</Fact>
      <Fact label="SLA">{agent.sla || '—'}</Fact>
      <Fact label="EU AI Act category">{facts?.euAiActCategory || '—'}</Fact>
      <Fact label="Version">{agent.version || '—'}</Fact>
      <Fact label="API endpoint" wide>
        <span className="font-mono text-gray-700 break-all">{endpoint || 'N/A'}</span>
        {facts?.apiEndpointWarning && (
          <span className="mt-1 flex items-start gap-1 text-xs text-amber-700">
            <span aria-hidden>⚠</span>
            <span>{facts.apiEndpointWarning} Update it in the agent profile if the agent has its own API.</span>
          </span>
        )}
      </Fact>
    </div>
  )
}

// ── Declared dependencies ───────────────────────────────────────────────────

const CHIP_GROUPS: { key: 'enterpriseSystems' | 'databases' | 'mcpServers' | 'knowledgeBases'; label: string; className: string }[] = [
  { key: 'enterpriseSystems', label: 'Enterprise Systems', className: 'bg-teal-50 text-teal-700 ring-teal-200' },
  { key: 'databases', label: 'Databases', className: 'bg-amber-50 text-amber-700 ring-amber-200' },
  { key: 'mcpServers', label: 'MCP Servers', className: 'bg-purple-50 text-purple-700 ring-purple-200' },
  { key: 'knowledgeBases', label: 'Knowledge Bases', className: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
]

function DeclaredDependencies({ agent, agentId, graph }: { agent: Agent; agentId: string; graph: GraphV2Response | null }) {
  const deps = graph ? graph.edges.filter(e => e.from === agentId || e.to === agentId) : []
  const groups = CHIP_GROUPS.filter(g => (agent[g.key] || []).length > 0)
  if (groups.length === 0 && deps.length === 0) {
    return <p className="text-xs text-gray-400">No declared systems, data stores or dependencies.</p>
  }
  return (
    <div className="space-y-4">
      {groups.length > 0 && (
        <div className="grid grid-cols-2 gap-4">
          {groups.map(g => (
            <div key={g.key}>
              <SectionLabel>{g.label}</SectionLabel>
              <div className="flex flex-wrap gap-1 mt-1">
                {(agent[g.key] || []).map(s => (
                  <span key={s} className={`text-xs ring-1 px-2 py-0.5 rounded-full ${g.className}`}>{s}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
      {deps.length > 0 && (
        <div>
          <SectionLabel>Dependencies</SectionLabel>
          <div className="mt-2 space-y-1">
            {deps.map((e, i) => {
              const otherId = e.from === agentId ? e.to : e.from
              const otherName = graph?.nodes.find(n => n.id === otherId)?.name ?? otherId
              const typeLabel = e.type === 'CALLS' ? 'calls' : e.type === 'CONSUMED_BY' ? 'feeds' : e.type === 'ACCESSES' ? 'accesses' : e.type === 'USES_KB' ? 'knowledge' : 'tool'
              const direction = e.from === agentId ? typeLabel : 'needed by'
              return (
                <div key={i} className="text-xs flex gap-2">
                  <span className="text-gray-400">{direction}</span>
                  <span className="font-mono text-teal-600">{otherName}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Context panel ───────────────────────────────────────────────────────────

function CompletenessBar({ pct, missing }: { pct: number; missing: string[] }) {
  const color = pct >= 80 ? 'bg-teal-500' : pct >= 40 ? 'bg-amber-400' : 'bg-rose-400'
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-3">
        <span className="text-xs text-gray-500 whitespace-nowrap">Completeness</span>
        <div className="flex-1 h-2 rounded-full bg-gray-100 overflow-hidden">
          <div className={`h-full ${color}`} style={{ width: `${Math.max(0, Math.min(pct, 100))}%` }} />
        </div>
        <span className="text-xs font-mono text-gray-700 w-10 text-right">{pct}%</span>
      </div>
      {missing.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-[10px] text-gray-400">Missing or under 20 characters:</span>
          {missing.map(s => <Pill key={s} className="bg-gray-50 text-gray-500 ring-gray-200">{s}</Pill>)}
        </div>
      )}
    </div>
  )
}

function SuggestionTag() {
  return <span className="text-[10px] text-amber-700 bg-amber-50 ring-1 ring-amber-200 rounded-full px-1.5 py-0.5 whitespace-nowrap">Suggestion — not counted until confirmed</span>
}

function Excerpt({ text }: { text: string }) {
  if (!text) return null
  return <p className="text-[11px] text-gray-500 italic border-l-2 border-gray-200 pl-2 mt-1 break-words">"{text}"</p>
}

function Suggestions({ insight, busy, onAction }: {
  insight: ContextInsight
  busy: string | null
  onAction: (action: 'confirm' | 'dismiss', type: SuggestionType, ref: string) => void
}) {
  const risks = insight.suggestedRisks
  const deps = insight.suggestedDependencies
  if (risks.length === 0 && deps.length === 0) {
    return <p className="text-xs text-gray-400">No open suggestions from this document.</p>
  }
  const buttons = (type: SuggestionType, ref: string, confirmLabel: string) => {
    const id = `${type}:${ref}`
    return (
      <div className="flex gap-1 shrink-0">
        <button className="btn-primary btn-sm" disabled={busy !== null} onClick={() => onAction('confirm', type, ref)}>
          {busy === `confirm:${id}` ? 'Saving…' : confirmLabel}
        </button>
        <button className="btn-secondary btn-sm" disabled={busy !== null} onClick={() => onAction('dismiss', type, ref)}>
          {busy === `dismiss:${id}` ? 'Dismissing…' : 'Dismiss'}
        </button>
      </div>
    )
  }
  return (
    <div className="space-y-3">
      {risks.length > 0 && (
        <div className="space-y-2">
          <SectionLabel>Suggested risks ({risks.length})</SectionLabel>
          {risks.map(r => (
            <div key={r.key} className="rounded-lg border border-dashed border-amber-200 bg-amber-50/30 p-3 flex gap-3 items-start">
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-1.5 mb-1">
                  <Pill className={SEVERITY_PILL[r.severity] || SEVERITY_PILL.LOW}>{r.severity}</Pill>
                  <Pill className="bg-white text-gray-600 ring-gray-200">{CATEGORY_LABELS[r.category] || r.category}</Pill>
                  <SuggestionTag />
                </div>
                <p className="text-sm font-medium text-gray-900">{r.title}</p>
                <p className="text-xs text-gray-600">{r.description}</p>
                <Excerpt text={r.excerpt} />
              </div>
              {buttons('risk', r.key, 'Add to risk register')}
            </div>
          ))}
        </div>
      )}
      {deps.length > 0 && (
        <div className="space-y-2">
          <SectionLabel>Mentioned but not declared ({deps.length})</SectionLabel>
          {deps.map(d => (
            <div key={d.name} className="rounded-lg border border-dashed border-amber-200 bg-amber-50/30 p-3 flex gap-3 items-start">
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-1.5 mb-1">
                  <span className="text-sm font-mono text-teal-700">{d.name}</span>
                  <Pill className="bg-white text-gray-600 ring-gray-200">{FIELD_LABEL[d.field] || d.field}</Pill>
                  <SuggestionTag />
                </div>
                <Excerpt text={d.excerpt} />
              </div>
              {buttons('dependency', d.name, 'Add to declared')}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Signals({ insight }: { insight: ContextInsight }) {
  const labels = Array.from(new Set(insight.keywordHits.filter(h => !h.negated).map(h => h.label)))
  if (labels.length === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="text-[10px] text-gray-400">Mentions:</span>
      {labels.map(l => <Pill key={l} className="bg-gray-50 text-gray-600 ring-gray-200">{l}</Pill>)}
    </div>
  )
}

function VersionHistory({ agentId, versions, onLoad }: {
  agentId: string
  versions: ContextVersion[]
  onLoad: (content: string, label: string) => void
}) {
  const [viewing, setViewing] = useState<ContextVersion | null>(null)
  const [loadingId, setLoadingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const view = async (v: ContextVersion) => {
    if (viewing?.id === v.id) { setViewing(null); return }
    setLoadingId(v.id)
    setError(null)
    try {
      setViewing((await getContextVersion(agentId, v.id)).data)
    } catch (e) {
      setError(errorMessage(e, 'Could not load that version'))
    } finally {
      setLoadingId(null)
    }
  }

  if (versions.length === 0) return <p className="text-xs text-gray-400">No saved versions yet.</p>
  return (
    <div className="space-y-2">
      <ErrorLine text={error} />
      <ul className="divide-y divide-gray-100 rounded-lg border border-gray-100">
        {versions.map((v, i) => (
          <li key={v.id} className="px-3 py-2">
            <div className="flex items-center gap-3 text-xs">
              <span className="font-mono text-gray-400 w-8">v{versions.length - i}</span>
              <span className="text-gray-700">{fmtDateTime(v.savedAt)}</span>
              <span className="text-gray-500 truncate">{v.savedBy || '—'}</span>
              <span className="ml-auto flex items-center gap-2">
                {v.removed ? <Pill className="bg-gray-100 text-gray-500 ring-gray-200">removed</Pill> : <span className="text-gray-400">{fmtBytes(v.sizeBytes)}</span>}
                {i === 0 && <Pill className="bg-teal-50 text-teal-700 ring-teal-200">current</Pill>}
                <span className="font-mono text-gray-300" title={v.hash}>{v.hash.slice(0, 8)}</span>
                {!v.removed && (
                  <button className="text-teal-600 hover:underline" onClick={() => view(v)} disabled={loadingId !== null}>
                    {loadingId === v.id ? 'Loading…' : viewing?.id === v.id ? 'Hide' : 'View'}
                  </button>
                )}
              </span>
            </div>
            {viewing?.id === v.id && viewing.content != null && (
              <div className="mt-2 rounded-lg bg-gray-50 border border-gray-100 p-3 space-y-2">
                <div className="max-h-80 overflow-y-auto"><Markdown text={viewing.content} /></div>
                {i > 0 && (
                  <button className="btn-secondary btn-sm" onClick={() => onLoad(viewing.content || '', `version v${versions.length - i}`)}>
                    Load into editor
                  </button>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function ContextEditor({ draft, origin, saving, error, onChange, onUpload, onSave, onCancel }: {
  draft: string
  origin: string
  saving: boolean
  error: string | null
  onChange: (text: string) => void
  onUpload: () => void
  onSave: () => void
  onCancel: () => void
}) {
  const size = new Blob([draft]).size
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-xs text-gray-500">
          Editing {origin}. Markdown, any length. Saved as a new version; earlier versions stay in the history.
        </p>
        <button className="btn-secondary btn-sm" onClick={onUpload} disabled={saving}>Upload .md / .txt</button>
      </div>
      <textarea
        className="input w-full font-mono text-xs min-h-[22rem]"
        value={draft}
        onChange={e => onChange(e.target.value)}
        spellCheck={false}
        aria-label="context.md content"
      />
      <p className="text-[10px] text-gray-400">
        {fmtBytes(size)} · The registry reads this as data only and never follows instructions in it. It only adds suggestions, which a person confirms.
      </p>
      <ErrorLine text={error} />
      <div className="flex gap-2">
        <button className="btn-primary btn-sm" onClick={onSave} disabled={saving}>{saving ? 'Saving…' : 'Save context'}</button>
        <button className="btn-secondary btn-sm" onClick={onCancel} disabled={saving}>Cancel</button>
      </div>
    </div>
  )
}

function ContextPanel({ agentId, ctx, summary, error, onRetry, onChanged }: {
  agentId: string
  ctx: AgentContext | null
  summary: ContextSummary | null
  error: string | null
  onRetry: () => void
  onChanged: (next?: AgentContext) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [origin, setOrigin] = useState('')
  const [saving, setSaving] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const openEditor = (text: string, label: string) => {
    setDraft(text)
    setOrigin(label)
    setEditing(true)
    setActionError(null)
    setNotice(null)
  }

  const addContext = async () => {
    setBusy('template')
    setActionError(null)
    try {
      openEditor((await getContextTemplate()).data.content, 'from the template')
    } catch (e) {
      setActionError(errorMessage(e, 'Could not load the template'))
    } finally {
      setBusy(null)
    }
  }

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (!/\.(md|markdown|txt)$/i.test(file.name)) {
      setActionError('Upload a .md, .markdown or .txt file.')
      return
    }
    try {
      openEditor(await file.text(), `${file.name} (review, then save)`)
    } catch {
      setActionError(`Could not read ${file.name}.`)
    }
  }

  const persist = async (content: string) => {
    setSaving(true)
    setActionError(null)
    try {
      const res = (await saveAgentContext(agentId, content)).data
      setEditing(false)
      setNotice(
        res.status === 'saved' ? 'Saved as a new version.'
          : res.status === 'removed' ? 'Context removed. Earlier versions are kept in the history.'
            : 'No change: identical to the latest version.',
      )
      onChanged(res)
    } catch (e) {
      setActionError(errorMessage(e, 'Could not save context.md'))
    } finally {
      setSaving(false)
    }
  }

  const save = () => {
    if (!draft.trim() && !window.confirm('The editor is empty. Saving removes context.md from this agent (history is kept). Continue?')) return
    persist(draft)
  }

  const remove = () => {
    if (window.confirm('Remove context.md from this agent? Earlier versions stay in the history, and the registry keeps working without it.')) persist('')
  }

  const download = async () => {
    setActionError(null)
    try {
      const blob = (await downloadAgentContext(agentId)).data
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${agentId}-context.md`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setActionError(errorMessage(e, 'Download failed'))
    }
  }

  const act = async (action: 'confirm' | 'dismiss', type: SuggestionType, ref: string) => {
    setBusy(`${action}:${type}:${ref}`)
    setActionError(null)
    setNotice(null)
    try {
      const call = action === 'confirm' ? confirmContextSuggestion : dismissContextSuggestion
      const res = (await call(agentId, type, ref)).data
      if (action === 'dismiss') setNotice('Suggestion dismissed.')
      else if (type === 'risk') setNotice(res.status === 'exists' ? 'That risk is already in the register.' : 'Added to the risk register as an open risk (source: context). Manage it on the Risk tab.')
      else setNotice(res.status === 'exists' ? `${res.name} is already declared.` : `Added ${res.name} to the declared dependencies (${FIELD_LABEL[res.field as DeclaredField] || res.field}).`)
      onChanged(ctx ? { ...ctx, insight: res.insight } : undefined)
    } catch (e) {
      setActionError(errorMessage(e, 'Could not update the suggestion'))
    } finally {
      setBusy(null)
    }
  }

  const fileInput = <input ref={fileRef} type="file" accept={UPLOAD_ACCEPT} className="hidden" onChange={onFile} />
  const upload = () => fileRef.current?.click()

  if (!ctx) {
    return (
      <div className="rounded-lg border border-rose-100 bg-rose-50/50 p-3">
        <ErrorLine text={error || 'context.md unavailable'} onRetry={onRetry} />
      </div>
    )
  }

  const insight = ctx.insight
  const versions = ctx.versions
  const latest = versions[0]
  const status = (
    <>
      {notice && <p className="text-xs text-teal-700">{notice}</p>}
      <ErrorLine text={editing ? null : actionError} />
    </>
  )

  const history = versions.length > 0 && (
    <div>
      <button className="text-xs text-teal-600 hover:underline" onClick={() => setShowHistory(s => !s)}>
        {showHistory ? 'Hide' : 'Show'} version history ({versions.length})
      </button>
      {showHistory && (
        <div className="mt-2">
          <VersionHistory agentId={agentId} versions={versions} onLoad={(text, label) => openEditor(text, label)} />
        </div>
      )}
    </div>
  )

  if (editing) {
    return (
      <div className="space-y-3">
        {fileInput}
        <ContextEditor
          draft={draft}
          origin={origin}
          saving={saving}
          error={actionError}
          onChange={setDraft}
          onUpload={upload}
          onSave={save}
          onCancel={() => { setEditing(false); setActionError(null) }}
        />
      </div>
    )
  }

  if (!ctx.present || !insight) {
    return (
      <div className="space-y-3">
        {fileInput}
        <div className="rounded-lg border border-dashed border-gray-200 p-4 space-y-3">
          <p className="text-sm text-gray-600">No context added — the registry works fully without it.</p>
          <p className="text-xs text-gray-400">
            A context.md lets the owner describe purpose, users, data, systems, oversight and fallback in their own words.
            The registry then offers suggestions a person confirms; nothing changes on its own.
          </p>
          <CompletenessBar pct={0} missing={[]} />
          <div className="flex gap-2">
            <button className="btn-primary btn-sm" onClick={addContext} disabled={busy !== null}>
              {busy === 'template' ? 'Loading template…' : 'Add context'}
            </button>
            <button className="btn-secondary btn-sm" onClick={upload}>Upload .md / .txt</button>
          </div>
        </div>
        {status}
        {history}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {fileInput}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <p className="text-xs text-gray-500">
          {versions.length} version{versions.length === 1 ? '' : 's'}
          {' · '}{fmtBytes(summary?.sizeBytes ?? latest?.sizeBytes ?? 0)}
          {latest && <> · updated {relTime(latest.savedAt)} by {latest.savedBy || 'unknown'}</>}
        </p>
        <div className="flex gap-1 flex-wrap">
          <button className="btn-secondary btn-sm" onClick={() => openEditor(ctx.content, 'the current context')}>Edit</button>
          <button className="btn-secondary btn-sm" onClick={upload}>Replace from file</button>
          <button className="btn-secondary btn-sm" onClick={download}>Download</button>
          <button className="btn-secondary btn-sm text-rose-600" onClick={remove} disabled={saving}>{saving ? 'Removing…' : 'Remove'}</button>
        </div>
      </div>
      {status}

      <CompletenessBar pct={insight.completenessPct} missing={insight.sectionsMissing} />

      {insight.llmStatus === 'ok' && insight.summary ? (
        <div className="rounded-lg bg-teal-50/40 border border-teal-100 p-3">
          <span className="text-[10px] uppercase tracking-wide text-teal-700">Generated summary — verify before relying on it</span>
          <p className="text-sm text-gray-700 mt-1">{insight.summary}</p>
        </div>
      ) : LLM_NOTE[insight.llmStatus] ? (
        <p className="text-[11px] text-gray-400">{LLM_NOTE[insight.llmStatus]}</p>
      ) : null}

      <Signals insight={insight} />
      <Suggestions insight={insight} busy={busy} onAction={act} />

      <div>
        <SectionLabel>context.md</SectionLabel>
        <div className="mt-1 rounded-lg border border-gray-100 bg-white p-4 max-h-[36rem] overflow-y-auto">
          <Markdown text={ctx.content} />
        </div>
      </div>
      {history}
    </div>
  )
}

// ── Tab ─────────────────────────────────────────────────────────────────────

export default function OverviewTab({ agent, agentId, onChanged, graph }: TabProps & { graph: GraphV2Response | null }) {
  const [overview, setOverview] = useState<AgentOverview | null>(null)
  const [overviewError, setOverviewError] = useState<string | null>(null)
  const [ctx, setCtx] = useState<AgentContext | null>(null)
  const [ctxError, setCtxError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    const [ov, cx] = await Promise.allSettled([getAgentOverview(agentId), getAgentContext(agentId)])
    if (ov.status === 'fulfilled') {
      setOverview(ov.value.data)
      setOverviewError(null)
    } else {
      setOverviewError(errorMessage(ov.reason, 'Could not load the overview'))
    }
    if (cx.status === 'fulfilled') {
      setCtx(cx.value.data)
      setCtxError(null)
    } else {
      setCtxError(errorMessage(cx.reason, 'Could not load context.md'))
    }
    setLoading(false)
  }, [agentId])

  useEffect(() => {
    setLoading(true)
    load()
  }, [load])

  const contextChanged = (next?: AgentContext) => {
    if (next) setCtx(next)
    load()
    onChanged()
  }

  if (loading) return <Loading text="Loading overview…" />

  return (
    <div className="space-y-6">
      <KpiStrip overview={overview} error={overviewError} onRetry={load} agentId={agentId} />

      <FactsGrid agent={agent} facts={overview?.facts ?? null} />

      {(agent.description || agent.businessOutcome) && (
        <div className="space-y-3">
          {agent.description && (
            <div>
              <SectionLabel>Description</SectionLabel>
              <p className="text-sm text-gray-700">{agent.description}</p>
            </div>
          )}
          {agent.businessOutcome && (
            <div>
              <SectionLabel>Business Outcome</SectionLabel>
              <p className="text-sm text-gray-700">{agent.businessOutcome}</p>
            </div>
          )}
        </div>
      )}

      <DeclaredDependencies agent={agent} agentId={agentId} graph={graph} />

      <div className="border-t border-gray-100 pt-4 space-y-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-gray-900">Context</h3>
          <span className="text-[10px] text-gray-400">optional · context.md</span>
        </div>
        <ContextPanel
          agentId={agentId}
          ctx={ctx}
          summary={overview?.context ?? null}
          error={ctxError}
          onRetry={load}
          onChanged={contextChanged}
        />
      </div>
    </div>
  )
}
