/**
 * 测试夹具：镜像后端 `UserRead`（含 role 与 permissions）。
 *
 * 权限集与后端 ROLE_PERMISSIONS 保持一致，供 store、路由守卫与页面测试复用。
 */
import type { User, UserRole } from "../../api/users"

const PERMISSIONS: Record<UserRole, User["permissions"]> = {
  viewer: ["knowledge:read"],
  member: ["knowledge:read", "knowledge:write"],
  admin: ["knowledge:read", "knowledge:write", "models:manage", "users:manage"],
}

export function makeUser(
  role: UserRole = "member",
  overrides: Partial<User> = {},
): User {
  return {
    id: `user-${role}`,
    display_name:
      role === "admin"
        ? "管理员小王"
        : role === "viewer"
          ? "只读小李"
          : "成员小张",
    email: `${role}@example.com`,
    avatar_url: null,
    status: "active",
    deleted_at: null,
    created_at: "2026-10-20T00:00:00Z",
    updated_at: "2026-10-20T00:00:00Z",
    role,
    permissions: PERMISSIONS[role],
    ...overrides,
  }
}
