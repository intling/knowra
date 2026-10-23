import { apiGet } from "./client"
export type JobKind = "parse" | "chunk" | "embedding"
export type ComponentStatus =
  | "ok"
  | "degraded"
  | "unavailable"
  | "unknown"
  | "disabled"
export interface Page<T> {
  items: T[]
  total: number
  offset: number
  limit: number
}
export interface AdminJob {
  id: string
  kind: JobKind
  uploaded_file_id: string
  owner_user_id: string
  owner_label: string
  status: string
  attempt_count: number
  created_at: string
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  item_count: number | null
  error_code: string | null
  error_detail: string | null
}
export interface JobDetail {
  job: AdminJob
  timeline: AdminJob[]
  missing_kinds: JobKind[]
}
export interface JobFilters {
  kind?: string
  status?: string
  owner_user_id?: string
  from?: string
  to?: string
  offset?: number
  limit?: number
}
export interface AuditEvent {
  id: string
  actor_user_id: string
  action: string
  resource_type: string
  resource_id: string
  result: string
  changes_json: Record<string, unknown>
  error_code: string | null
  trace_id: string
  created_at: string
}
export interface AuditFilters {
  actor_user_id?: string
  action?: string
  result?: string
  trace_id?: string
  from?: string
  to?: string
  offset?: number
  limit?: number
}
export interface SystemStatus {
  checked_at: string
  scope: "instance"
  instance_id: string
  components: { name: string; status: ComponentStatus; detail: string }[]
}
export interface JobTotals {
  kind: JobKind
  status: ComponentStatus
  queued: number | null
  running: number | null
  succeeded_24h: number | null
  failed_24h: number | null
  success_rate_24h: number | null
}
export interface Overview {
  snapshot_at: string
  users: {
    status: ComponentStatus
    total: number | null
    active: number | null
    disabled: number | null
  }
  uploads: {
    status: ComponentStatus
    total: number | null
    logical_bytes: number | null
  }
  jobs_by_kind: JobTotals[]
  attention_items: {
    code: string
    detail: string
    href: string
    count: number | null
  }[]
}
function params(filters: object) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") query.set(key, String(value))
  }
  return query.toString()
}
export function listJobs(filters: JobFilters = {}): Promise<Page<AdminJob>> {
  return apiGet(`/admin/jobs?${params({ offset: 0, limit: 20, ...filters })}`)
}
export function getJob(kind: JobKind, id: string): Promise<JobDetail> {
  return apiGet(`/admin/jobs/${kind}/${encodeURIComponent(id)}`)
}
export function listAuditEvents(
  filters: AuditFilters = {},
): Promise<Page<AuditEvent>> {
  return apiGet(
    `/admin/audit-events?${params({ offset: 0, limit: 20, ...filters })}`,
  )
}
export function getOverview(): Promise<Overview> {
  return apiGet("/admin/overview")
}
export function getSystemStatus(): Promise<SystemStatus> {
  return apiGet("/admin/system/status")
}
