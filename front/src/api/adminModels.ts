import { apiDelete, apiGet, apiPatchJson, apiPostJson } from "./client"

export type ModelKind = "chat" | "embedding" | "rerank" | "query_rewrite"
export interface ModelProfile {
  id: string
  name: string
  kind: ModelKind
  base_url: string
  model: string
  has_api_key: boolean
  enabled: boolean
  is_default: boolean
  timeout_seconds: number
  max_retries: number
  dimensions: number | null
  api_format: "compatible" | "dashscope" | null
  created_at: string
  updated_at: string
  revision: number
}
export interface ModelWrite {
  name: string
  base_url: string
  model: string
  api_key?: string
  clear_api_key?: boolean
  timeout_seconds: number
  max_retries: number
  dimensions?: number
  api_format?: "compatible" | "dashscope"
}
export interface ModelPage {
  items: ModelProfile[]
  total: number
  offset: number
  limit: number
}
export function listModels({
  offset = 0,
  limit = 20,
  kind = "",
}: {
  offset?: number
  limit?: number
  kind?: ModelKind | ""
} = {}): Promise<ModelPage> {
  return apiGet(
    `/admin/models?offset=${offset}&limit=${limit}${kind ? `&kind=${kind}` : ""}`,
  )
}
export function createModel(
  payload: ModelWrite & { kind: ModelKind },
): Promise<ModelProfile> {
  return apiPostJson("/admin/models", payload)
}
export function updateModel(
  id: string,
  payload: Partial<ModelWrite> & { enabled?: boolean },
): Promise<ModelProfile> {
  return apiPatchJson(`/admin/models/${encodeURIComponent(id)}`, payload)
}
export function deleteModel(id: string): Promise<void> {
  return apiDelete(`/admin/models/${encodeURIComponent(id)}`)
}
export function activateModel(id: string): Promise<ModelProfile> {
  return apiPostJson(`/admin/models/${encodeURIComponent(id)}/activate`)
}
export function deactivateModel(id: string): Promise<ModelProfile> {
  return apiPostJson(`/admin/models/${encodeURIComponent(id)}/deactivate`)
}

export interface ModelProbe {
  probe_id: string
  status: "running" | "passed" | "failed" | "interrupted"
  code: string
  detail: string
  latency_ms: number | null
  checked_at: string
  config_revision: number
  is_current: boolean
}
export interface EffectiveModel {
  kind: ModelKind
  source: "profile" | "environment"
  enabled: boolean
  profile_id: string | null
  model: string
  profile_revision: number | null
  binding_revision: number
  configuration_status: "ok" | "unavailable" | "disabled"
  latest_probe: ModelProbe | null
}
export function getEffectiveModels(): Promise<EffectiveModel[]> {
  return apiGet("/admin/models/effective")
}
export function testModel(
  id: string,
  expected_revision: number,
): Promise<ModelProbe> {
  return apiPostJson(`/admin/models/${encodeURIComponent(id)}/test`, {
    expected_revision,
  })
}
