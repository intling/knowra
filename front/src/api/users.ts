import { apiGet } from "./client"

export interface User {
  id: string
  display_name: string
  email: string | null
  avatar_url: string | null
  status: "active" | "disabled"
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export function getCurrentUser(): Promise<User> {
  return apiGet<User>("/users/me")
}
