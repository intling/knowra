import { apiDelete, apiGet, apiPatchJson, apiPostJson } from "./client"
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
export function listUsers({ offset = 0, limit = 20 } = {}): Promise<UserPage> {
  return apiGet<UserPage>(`/admin/users?offset=${offset}&limit=${limit}`)
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
