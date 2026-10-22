import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { createMemoryHistory } from "vue-router"

import { makeUser } from "../../__tests__/fixtures/users"
import { ApiError } from "../../api/client"
import { getCurrentUser } from "../../api/users"
import { useChatStore } from "../../stores/chat"
import { LOGOUT_SIGNAL_KEY, useUserStore } from "../../stores/user"

vi.mock("../../components/layout/ChatLayout.vue", () =>
  import("../../__tests__/helpers/authHarness").then((m) => ({
    default: m.Placeholder,
  })),
)
vi.mock("../../views/VerificationView.vue", () =>
  import("../../__tests__/helpers/authHarness").then((m) => ({
    default: m.Placeholder,
  })),
)
vi.mock("../../views/LoginView.vue", () =>
  import("../../__tests__/helpers/authHarness").then((m) => ({
    default: m.Placeholder,
  })),
)
vi.mock("../../views/RegisterView.vue", () =>
  import("../../__tests__/helpers/authHarness").then((m) => ({
    default: m.Placeholder,
  })),
)
vi.mock("../../views/AccountView.vue", () =>
  import("../../__tests__/helpers/authHarness").then((m) => ({
    default: m.Placeholder,
  })),
)
vi.mock("../../views/AdminUsersView.vue", () =>
  import("../../__tests__/helpers/authHarness").then((m) => ({
    default: m.Placeholder,
  })),
)
vi.mock("../../api/users", () => ({ getCurrentUser: vi.fn() }))
vi.mock("../../shared/logger", () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))

const { createAppRouter } = await import("../index")
const { installAuthHandling } = await import("../guards")
const { setUnauthorizedHandler, apiGet } = await import("../../api/client")

const getCurrentUserMock = vi.mocked(getCurrentUser)

function anonymous() {
  getCurrentUserMock.mockRejectedValue(
    new ApiError(401, "auth_required", "请先登录"),
  )
}

describe("路由认证守卫", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    setUnauthorizedHandler(null)
  })

  // 测试：匿名访问私有页面跳转登录页，并记录站内返回路径。
  it("匿名访问 /verify 跳转 /login?redirect=/verify", async () => {
    anonymous()
    const router = createAppRouter(createMemoryHistory())

    await router.push("/verify")

    expect(router.currentRoute.value.name).toBe("login")
    expect(router.currentRoute.value.query.redirect).toBe("/verify")
  })

  // 测试：已登录用户访问登录或注册页被导向工作台。
  it("已登录用户访问 /login 与 /register 导向 /", async () => {
    getCurrentUserMock.mockResolvedValue(makeUser("member"))
    const router = createAppRouter(createMemoryHistory())

    await router.push("/login")
    expect(router.currentRoute.value.path).toBe("/")
    await router.push("/register")
    expect(router.currentRoute.value.path).toBe("/")
  })

  // 测试：守卫在会话恢复完成前不放行，避免短暂渲染私有页面。
  it("会话恢复完成前导航保持挂起", async () => {
    let resolveUser!: (value: ReturnType<typeof makeUser>) => void
    getCurrentUserMock.mockReturnValue(
      new Promise((resolve) => (resolveUser = resolve)),
    )
    const router = createAppRouter(createMemoryHistory())

    const navigation = router.push("/account")
    await Promise.resolve()
    expect(router.currentRoute.value.matched).toHaveLength(0)

    resolveUser(makeUser("member"))
    await navigation
    expect(router.currentRoute.value.name).toBe("account")
  })

  // 测试：成员可以进入用户管理路由，由页面展示权限不足（守卫不泄露路由存在与否以外的信息）。
  it("非管理员进入 /admin/users 由页面处理权限反馈", async () => {
    getCurrentUserMock.mockResolvedValue(makeUser("member"))
    const router = createAppRouter(createMemoryHistory())

    await router.push("/admin/users")

    expect(router.currentRoute.value.name).toBe("admin-users")
  })

  // 测试：服务不可用时不跳转登录，保留在目标路由由应用壳展示可重试错误。
  it("会话探测网络错误时保留导航目标", async () => {
    getCurrentUserMock.mockRejectedValue(new TypeError("Failed to fetch"))
    const router = createAppRouter(createMemoryHistory())

    await router.push("/verify")

    expect(useUserStore().status).toBe("error")
    expect(router.currentRoute.value.name).toBe("verify")
  })
})

describe("统一会话失效处理", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    vi.unstubAllGlobals()
  })

  // 测试：任一业务请求 401 时清理私有状态并跳转登录页（携带返回路径与过期原因）。
  it("业务请求 401 触发重新登录流程", async () => {
    getCurrentUserMock.mockResolvedValue(makeUser("member"))
    const router = createAppRouter(createMemoryHistory())
    installAuthHandling(router)
    await router.push("/verify")
    useChatStore().addConversation("私有对话")
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        json: () =>
          Promise.resolve({ detail: "登录已失效", code: "auth_required" }),
      }),
    )

    await apiGet("/parsed-documents").catch(() => undefined)
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe("login"))

    expect(router.currentRoute.value.query).toMatchObject({
      redirect: "/verify",
      reason: "expired",
    })
    expect(useUserStore().currentUser).toBeNull()
    expect(useChatStore().conversations).toEqual([])
  })

  // 测试：其他标签页退出（storage 事件）时本标签页同步清理并跳转登录页。
  it("跨标签页退出同步清理", async () => {
    getCurrentUserMock.mockResolvedValue(makeUser("member"))
    const router = createAppRouter(createMemoryHistory())
    installAuthHandling(router)
    await router.push("/")

    window.dispatchEvent(
      new StorageEvent("storage", {
        key: LOGOUT_SIGNAL_KEY,
        newValue: String(Date.now()),
      }),
    )
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe("login"))

    expect(useUserStore().status).toBe("anonymous")
  })

  // 测试：退出或改密使状态变为未登录后，停留在私有页面会被导向登录页。
  it("本页退出后离开私有页面", async () => {
    getCurrentUserMock.mockResolvedValue(makeUser("member"))
    const router = createAppRouter(createMemoryHistory())
    installAuthHandling(router)
    await router.push("/account")

    useUserStore().handleUnauthorized()
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe("login"))
  })
})
