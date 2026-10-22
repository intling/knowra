import { apiPostJson } from "./client"
import type { User } from "./users"

export interface LoginRequest {
  email: string
  password: string
}
export interface RegisterRequest extends LoginRequest {
  display_name: string
}
export function login(payload: LoginRequest): Promise<User> {
  return apiPostJson<User>("/auth/login", payload)
}
export function register({
  display_name,
  email,
  password,
}: RegisterRequest): Promise<User> {
  return apiPostJson<User>("/auth/register", { display_name, email, password })
}
export function logout(): Promise<void> {
  return apiPostJson("/auth/logout")
}
