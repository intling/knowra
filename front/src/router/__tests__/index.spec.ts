import { describe, expect, it, vi } from "vitest"

// Mock page components so the router module can load without rendering them.
vi.mock("../../components/layout/ChatLayout.vue", () => ({ default: {} }))
vi.mock("../../views/VerificationView.vue", () => ({ default: {} }))
vi.mock("../../views/LoginView.vue", () => ({ default: {} }))
vi.mock("../../views/RegisterView.vue", () => ({ default: {} }))
vi.mock("../../views/AccountView.vue", () => ({ default: {} }))
vi.mock("../../views/AdminUsersView.vue", () => ({ default: {} }))

const { default: router } = await import("../index")

function route(path: string) {
  const found = router.getRoutes().find((r) => r.path === path)
  expect(found, `缺少路由 ${path}`).toBeDefined()
  return found!
}

describe("路由表", () => {
  // 测试：工作台、核对、账户页面都需要登录。
  it("私有页面标记 requiresAuth", () => {
    for (const path of ["/", "/verify", "/account", "/admin/users"]) {
      expect(route(path).meta.requiresAuth, `${path} 必须要求登录`).toBe(true)
    }
  })

  // 测试：登录与注册页面只对未登录用户开放，并具备稳定的路由名。
  it("登录注册页面标记 guestOnly", () => {
    expect(route("/login").name).toBe("login")
    expect(route("/register").name).toBe("register")
    expect(route("/login").meta.guestOnly).toBe(true)
    expect(route("/register").meta.guestOnly).toBe(true)
  })

  // 测试：用户管理页面声明所需的 users:manage 权限，由页面展示权限不足反馈。
  it("用户管理页声明权限", () => {
    expect(route("/admin/users").name).toBe("admin-users")
    expect(route("/admin/users").meta.permission).toBe("users:manage")
    expect(route("/account").name).toBe("account")
  })

  // 测试：保留历史重定向 /home、/chat → /。
  it("保留旧入口重定向", () => {
    expect(route("/home").redirect).toBe("/")
    expect(route("/chat").redirect).toBe("/")
  })

  // 新增页面需同步更新路由总数断言。
  it("共 10 条路由", () => {
    expect(router.getRoutes()).toHaveLength(10)
  })
})
