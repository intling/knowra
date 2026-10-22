import { flushPromises, type VueWrapper } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { makeUser } from "../../__tests__/fixtures/users"
import { mountPage } from "../../__tests__/helpers/authHarness"
import { ApiError } from "../../api/client"
import { logout } from "../../api/auth"
import { changeMyPassword, updateMyProfile } from "../../api/users"
import type { UserRole } from "../../api/users"
import { useUserStore } from "../../stores/user"

vi.mock("../../shared/logger", () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))
vi.mock("../../api/auth", () => ({
  login: vi.fn(),
  register: vi.fn(),
  logout: vi.fn(),
}))
vi.mock("../../api/users", () => ({
  getCurrentUser: vi.fn(),
  updateMyProfile: vi.fn(),
  changeMyPassword: vi.fn(),
}))

const updateMock = vi.mocked(updateMyProfile)
const changeMock = vi.mocked(changeMyPassword)
const logoutMock = vi.mocked(logout)

let wrapper: VueWrapper | null = null

async function mountAccount(role: UserRole = "member") {
  const { default: AccountView } = await import("../AccountView.vue")
  const mounted = await mountPage(AccountView, {
    name: "account",
    at: "/account",
    setup: () => {
      const store = useUserStore()
      store.currentUser = makeUser(role)
      store.status = "authenticated"
    },
  })
  wrapper = mounted.wrapper
  return mounted
}

async function submitPassword(
  w: VueWrapper,
  current: string,
  next: string,
  confirm = next,
) {
  await w.find('[data-testid="current-password"]').setValue(current)
  await w.find('[data-testid="new-password"]').setValue(next)
  await w.find('[data-testid="confirm-password"]').setValue(confirm)
  await w.find('[data-testid="password-form"]').trigger("submit")
  await flushPromises()
}

describe("AccountView", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ""
  })

  // 测试：展示账户信息与角色中文名称，邮箱只读。
  it.each([
    ["admin", "管理员"],
    ["member", "成员"],
    ["viewer", "只读"],
  ] as const)("角色 %s 显示为“%s”", async (role, label) => {
    const { wrapper: w } = await mountAccount(role)

    expect(w.find('[data-testid="account-role"]').text()).toContain(label)
    expect(w.text()).toContain(`${role}@example.com`)
    expect(w.find('input[type="email"]').exists()).toBe(false)
  })

  // 测试：修改显示名后调用资料 API，并更新 store 与成功提示。
  it("保存显示名并更新当前用户", async () => {
    updateMock.mockResolvedValue(makeUser("member", { display_name: "新名字" }))
    const { wrapper: w } = await mountAccount()

    await w.find('[data-testid="profile-name"]').setValue("新名字")
    await w.find('[data-testid="profile-form"]').trigger("submit")
    await flushPromises()

    expect(updateMock).toHaveBeenCalledWith({ display_name: "新名字" })
    expect(useUserStore().currentUser?.display_name).toBe("新名字")
    expect(w.find('[data-testid="profile-status"]').text()).toContain("已保存")
  })

  // 测试：资料保存失败时显示后端原因。
  it("保存显示名失败时显示原因", async () => {
    updateMock.mockRejectedValue(
      new ApiError(422, "invalid_display_name", "显示名称不能为空"),
    )
    const { wrapper: w } = await mountAccount()

    await w.find('[data-testid="profile-name"]').setValue("   ")
    await w.find('[data-testid="profile-form"]').trigger("submit")
    await flushPromises()

    expect(
      w.find('[data-testid="profile-form"] [role="alert"]').text(),
    ).toContain("显示名称")
  })

  // 测试：新密码不合规或两次不一致时不调用改密 API。
  it.each([
    ["short1", "short1", "10"],
    ["Brand-New-Pass-2027", "Other-Pass-2027", "不一致"],
  ])("改密校验失败（%s / %s）提示“%s”", async (next, confirm, message) => {
    const { wrapper: w } = await mountAccount()

    await submitPassword(w, "Knowra-Pass-2026", next, confirm)

    expect(changeMock).not.toHaveBeenCalled()
    expect(w.find('[data-testid="password-form"]').text()).toContain(message)
  })

  // 测试：改密成功后清理私有状态，并要求使用新密码重新登录。
  it("改密成功后跳转登录页", async () => {
    changeMock.mockResolvedValue(undefined)
    const { wrapper: w, router } = await mountAccount()

    await submitPassword(w, "Knowra-Pass-2026", "Brand-New-Pass-2027")

    expect(changeMock).toHaveBeenCalledWith({
      current_password: "Knowra-Pass-2026",
      new_password: "Brand-New-Pass-2027",
    })
    expect(useUserStore().currentUser).toBeNull()
    expect(router.currentRoute.value.name).toBe("login")
    expect(router.currentRoute.value.query.reason).toBe("password_changed")
  })

  // 测试：当前密码错误时显示原因且保持登录。
  it("当前密码错误时保持登录并提示", async () => {
    changeMock.mockRejectedValue(
      new ApiError(400, "current_password_incorrect", "当前密码不正确"),
    )
    const { wrapper: w, router } = await mountAccount()

    await submitPassword(w, "Wrong-Pass-2026", "Brand-New-Pass-2027")

    expect(
      w.find('[data-testid="password-form"] [role="alert"]').text(),
    ).toContain("当前密码不正确")
    expect(useUserStore().status).toBe("authenticated")
    expect(router.currentRoute.value.name).toBe("account")
  })

  // 测试：退出请求服务端撤销会话并回到登录页。
  it("退出登录", async () => {
    logoutMock.mockResolvedValue(undefined)
    const { wrapper: w, router } = await mountAccount()

    await w.find('[data-testid="account-logout"]').trigger("click")
    await flushPromises()

    expect(logoutMock).toHaveBeenCalledTimes(1)
    expect(useUserStore().currentUser).toBeNull()
    expect(router.currentRoute.value.name).toBe("login")
  })
})
