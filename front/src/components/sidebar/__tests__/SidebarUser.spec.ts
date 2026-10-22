import { flushPromises, type VueWrapper } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { makeUser } from "../../../__tests__/fixtures/users"
import { mountPage } from "../../../__tests__/helpers/authHarness"
import { logout } from "../../../api/auth"
import type { UserRole } from "../../../api/users"
import { useUserStore } from "../../../stores/user"

vi.mock("../../../shared/logger", () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))
vi.mock("../../../api/auth", () => ({
  login: vi.fn(),
  register: vi.fn(),
  logout: vi.fn(),
}))

const logoutMock = vi.mocked(logout)
let wrapper: VueWrapper | null = null

async function mountSidebarUser(role: UserRole) {
  const { default: SidebarUser } = await import("../SidebarUser.vue")
  const mounted = await mountPage(SidebarUser, {
    name: "home",
    at: "/",
    setup: () => {
      const store = useUserStore()
      store.currentUser = makeUser(role)
      store.status = "authenticated"
    },
  })
  wrapper = mounted.wrapper
  return mounted
}

async function openMenu(w: VueWrapper) {
  const trigger = w.find('[data-testid="user-menu-button"]')
  await trigger.trigger("click")
  return trigger
}

describe("SidebarUser 账户入口", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ""
  })

  // 测试：侧栏展示当前用户名称与角色，入口按钮声明展开状态。
  it("展示用户名与角色", async () => {
    const { wrapper: w } = await mountSidebarUser("admin")

    expect(w.text()).toContain("管理员小王")
    expect(w.find('[data-testid="sidebar-user-role"]').text()).toContain(
      "管理员",
    )
    const trigger = w.find('[data-testid="user-menu-button"]')
    expect(trigger.attributes("aria-expanded")).toBe("false")
  })

  // 测试：展开后提供账户设置与退出；用户管理入口只对管理员可见。
  it.each([
    ["admin", true],
    ["member", false],
    ["viewer", false],
  ] as const)(
    "%s 的账户菜单（用户管理可见：%s）",
    async (role, adminVisible) => {
      const { wrapper: w } = await mountSidebarUser(role)

      const trigger = await openMenu(w)

      expect(trigger.attributes("aria-expanded")).toBe("true")
      expect(w.find('[data-testid="menu-account"]').attributes("href")).toBe(
        "/account",
      )
      expect(w.find('[data-testid="menu-admin"]').exists()).toBe(adminVisible)
      expect(w.find('[data-testid="menu-logout"]').exists()).toBe(true)
    },
  )

  // 测试：Esc 收起菜单并把焦点还给入口按钮。
  it("Esc 关闭菜单并归还焦点", async () => {
    const { wrapper: w } = await mountSidebarUser("member")
    const trigger = await openMenu(w)

    await w
      .find('[data-testid="menu-account"]')
      .trigger("keydown", { key: "Escape" })

    expect(w.find('[data-testid="menu-account"]').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
  })

  // 测试：退出请求服务端撤销会话、清理用户并回到登录页。
  it("退出登录", async () => {
    logoutMock.mockResolvedValue(undefined)
    const { wrapper: w, router } = await mountSidebarUser("member")
    await openMenu(w)

    await w.find('[data-testid="menu-logout"]').trigger("click")
    await flushPromises()

    expect(logoutMock).toHaveBeenCalledTimes(1)
    expect(useUserStore().currentUser).toBeNull()
    expect(router.currentRoute.value.name).toBe("login")
    expect(router.currentRoute.value.query.reason).toBe("logged_out")
  })
})
