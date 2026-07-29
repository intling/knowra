import { describe, expect, it, vi } from "vitest"

// Mock future component imports so the router module can load
vi.mock("../../components/layout/ChatLayout.vue", () => ({
  default: {},
}))
vi.mock("../../views/VerificationView.vue", () => ({
  default: {},
}))

const { default: router } = await import("../index")

describe("路由器重构", () => {
  it("应包含 / 路由指向 ChatLayout", () => {
    const routes = router.getRoutes()
    const chatRoute = routes.find((r) => r.path === "/")
    expect(chatRoute).toBeDefined()
  })

  it("应包含 /verify 路由指向 VerificationView", () => {
    const routes = router.getRoutes()
    const verifyRoute = routes.find((r) => r.path === "/verify")
    expect(verifyRoute).toBeDefined()
  })

  it("应将 /home 重定向到 /", () => {
    const routes = router.getRoutes()
    const homeRedirect = routes.find((r) => r.path === "/home")
    expect(homeRedirect).toBeDefined()
    expect(homeRedirect!.redirect).toBe("/")
  })

  it("应将 /chat 重定向到 /", () => {
    const routes = router.getRoutes()
    const chatRedirect = routes.find((r) => r.path === "/chat")
    expect(chatRedirect).toBeDefined()
    expect(chatRedirect!.redirect).toBe("/")
  })

  it("应只有 4 条路由（/、/verify、/home 重定向、/chat 重定向）", () => {
    const routes = router.getRoutes()
    expect(routes).toHaveLength(4)
  })
})
