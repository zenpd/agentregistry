import api from '../api'

export type JobName = 'usage_ingestion' | 'infra_costs' | 'cost_rollup' | 'risk_scan' | 'governance_checks'

// ok | partial | not_configured | skipped | error | unreachable come from the jobs;
// running | stale | cancelled | unavailable are set by the runner. A job that
// reports anything else is stored as 'error' with its own word in summary.jobStatus.
export type JobStatus =
  | 'ok' | 'partial' | 'not_configured' | 'skipped' | 'error' | 'unreachable'
  | 'running' | 'stale' | 'cancelled' | 'unavailable'
  | (string & {})

export interface JobRun {
  runId: string | null
  // 'refresh' rows hold the per-agent refresh lock; they appear only in /jobs/runs.
  job: JobName | 'refresh'
  agentId: string | null
  trigger: 'manual' | 'scheduled' | string
  status: JobStatus
  startedAt: string | null
  finishedAt: string | null
  durationMs: number | null
  summary: Record<string, unknown>
  error: string | null
  locked?: boolean
  reason?: string
}

export interface SchedulerStatus {
  enabled: boolean
  running: boolean
  nextRunAt: string | null
  timezone: string
  lockMinutes: number
}

export interface JobInfo {
  job: JobName
  label: string
  shortLabel: string
  dailyAt: string
  schedule: string
  adminOnly: boolean
  inRefresh: boolean
  available: boolean
  unavailableReason: string | null
}

export interface JobListItem extends JobInfo {
  enabled: boolean
  lastRun: JobRun | null
  lastAllAgentsRun: JobRun | null
}

export interface JobsResponse {
  scheduler: SchedulerStatus
  jobs: JobListItem[]
}

export interface AgentJobItem extends JobInfo {
  agentRun: JobRun | null
  allAgentsRun: JobRun | null
  lastRun: JobRun | null
}

export interface AgentJobsResponse {
  agentId: string
  scheduler: SchedulerStatus
  jobs: AgentJobItem[]
}

export interface JobRunsResponse {
  runs: JobRun[]
  count: number
}

export interface RefreshResult {
  agentId: string
  trigger: string
  status: 'ok' | 'partial' | 'error' | 'skipped'
  locked: boolean
  reason?: string
  startedAt: string
  finishedAt: string
  results: JobRun[]
}

// A refresh reads Phoenix and runs four jobs back to back.
const REFRESH_TIMEOUT_MS = 10 * 60_000

export const getJobs = () => api.get<JobsResponse>('/jobs')

export const getJobRuns = (params: { job?: JobName; agent_id?: string; limit?: number } = {}) =>
  api.get<JobRunsResponse>('/jobs/runs', { params })

export const runJob = (job: JobName, params: { agent_id?: string; days?: number } = {}) =>
  api.post<JobRun>(`/jobs/${job}/run`, null, { params, timeout: REFRESH_TIMEOUT_MS })

export const getAgentJobs = (agentId: string) =>
  api.get<AgentJobsResponse>(`/agents/${encodeURIComponent(agentId)}/jobs`)

export const refreshAgent = (agentId: string) =>
  api.post<RefreshResult>(`/agents/${encodeURIComponent(agentId)}/refresh`, null, { timeout: REFRESH_TIMEOUT_MS })
