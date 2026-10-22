import { apiGet, apiPatchJson, apiPostJson } from "./client"

export type UserRole = "admin" | "member" | "viewer"

export interface User {
  id: string
  display_name: string
  email: string | null
  avatar_url: string | null
  role: UserRole
  permissions: string[]
  status: "active" | "disabled"
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export function getCurrentUser(): Promise<User> {
  return apiGet<User>("/users/me", { skipAuthRedirect: true })
}

export function updateMyProfile(payload: {
  display_name: string
}): Promise<User> {
  return apiPatchJson<User>("/users/me", payload)
}

export function changeMyPassword(payload: {
  current_password: string
  new_password: string
}): Promise<void> {
  return apiPostJson("/users/me/password", payload)
}
