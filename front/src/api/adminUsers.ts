import {
  apiDelete,
  apiGet,
  apiPatchJson,
  apiPostJson,
  apiPutJson,
} from "./client"
import type { User } from "./users"

export interface UserPage {
  items: User[]
  total: number
  offset: number
  limit: number
}
export interface UserUpdate {
  role?: User["role"]
  status?: User["status"]
}
export interface UserFilters {
  offset?: number
  limit?: number
  q?: string
  role?: User["role"]
  status?: User["status"]
}
export function listUsers({
  offset = 0,
  limit = 20,
  q,
  role,
  status,
}: UserFilters = {}): Promise<UserPage> {
  const params = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  })
  if (q) params.set("q", q)
  if (role) params.set("role", role)
  if (status) params.set("status", status)
  return apiGet<UserPage>(`/admin/users?${params}`)
}

export interface ChatLimitSnapshot {
  hourly_limit: number | null
  occupied_slots: number | null
  remaining: number | null
  window_seconds: number
  observed_at: string
}
export interface AdminUserDetail {
  user: User
  active_session_count: number
  chat_limit: ChatLimitSnapshot
}
export function readUser(id: string): Promise<AdminUserDetail> {
  return apiGet(`/admin/users/${encodeURIComponent(id)}`)
}
export function setChatLimit(
  id: string,
  hourly_limit: number | null,
): Promise<ChatLimitSnapshot> {
  return apiPutJson(`/admin/users/${encodeURIComponent(id)}/chat-limit`, {
    hourly_limit,
  })
}
export function revokeUserSessions(
  id: string,
): Promise<{ revoked_count: number }> {
  return apiPostJson(`/admin/users/${encodeURIComponent(id)}/revoke-sessions`)
}
export function updateUser(id: string, payload: UserUpdate): Promise<User> {
  return apiPatchJson<User>(`/admin/users/${encodeURIComponent(id)}`, payload)
}

export interface UserCreate {
  email: string
  display_name: string
  password: string
  role: User["role"]
}
export function createUser(payload: UserCreate): Promise<User> {
  return apiPostJson<User>("/admin/users", payload)
}
export function resetUserPassword(
  id: string,
  payload: { new_password: string },
): Promise<void> {
  return apiPostJson(
    `/admin/users/${encodeURIComponent(id)}/reset-password`,
    payload,
  )
}
export function deleteUser(id: string): Promise<void> {
  return apiDelete(`/admin/users/${encodeURIComponent(id)}`)
}
