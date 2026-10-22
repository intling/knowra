import { flushPromises, type VueWrapper } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { makeUser } from "../../__tests__/fixtures/users"
import { mountPage } from "../../__tests__/helpers/authHarness"
import { ApiError } from "../../api/client"
import { login } from "../../api/auth"

const logCalls: unknown[][] = []
vi.mock("../../shared/logger", () => {
  const record = (...args: unknown[]) => logCalls.push(args)
  return {
    createLogger: () => ({
      debug: record,
      info: record,
      warn: record,
      error: record,
    }),
    getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
  }
})
vi.mock("../../api/auth", () => ({
  login: vi.fn(),
  register: vi.fn(),
  logout: vi.fn(),
}))

const loginMock = vi.mocked(login)
const PASSWORD = "Knowra-Pass-2026"

let wrapper: VueWrapper | null = null

async function mountLogin(at = "/login") {
  const { default: LoginView } = await import("../LoginView.vue")
  const mounted = await mountPage(LoginView, { name: "login", at })
  wrapper = mounted.wrapper
  return mounted
}

async function fillAndSubmit(
  w: VueWrapper,
  email = "member@example.com",
  password = PASSWORD,
) {
  await w.find('input[type="email"]').setValue(email)
  await w.find('input[type="password"]').setValue(password)
  await w.find('[data-testid="login-form"]').trigger("submit")
}

describe("LoginView", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    logCalls.length = 0
    localStorage.clear()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ""
  })

  // 测试：表单具备标签与密码自动填充属性，并提供前往注册的入口。
  it("渲染可访问的登录表单与注册入口", async () => {
    const { wrapper: w } = await mountLogin()

    const email = w.find('input[type="email"]')
    const password = w.find('input[type="password"]')
    expect(email.attributes("autocomplete")).toBe("email")
    expect(password.attributes("autocomplete")).toBe("current-password")
    expect(w.find(`label[for="${email.attributes("id")}"]`).text()).toContain(
      "邮箱",
    )
    expect(
      w.find(`label[for="${password.attributes("id")}"]`).text(),
    ).toContain("密码")
    expect(w.find('[data-testid="go-register"]').attributes("href")).toBe(
      "/register",
    )
  })

  // 测试：提交期间禁用按钮防止重复提交；成功后进入合法的站内返回页。
  it("提交中禁用按钮并在成功后跳转 redirect", async () => {
    let resolveLogin!: (u: ReturnType<typeof makeUser>) => void
    loginMock.mockReturnValue(
      new Promise((resolve) => (resolveLogin = resolve)),
    )
    const { wrapper: w, router } = await mountLogin("/login?redirect=/verify")

    await fillAndSubmit(w)
    const submit = w.find('[data-testid="login-submit"]')
    expect(submit.attributes("disabled")).toBeDefined()
    expect(submit.text()).toContain("登录中")
    await w.find('[data-testid="login-form"]').trigger("submit")
    expect(loginMock).toHaveBeenCalledTimes(1)

    resolveLogin(makeUser("member"))
    await flushPromises()

    expect(loginMock).toHaveBeenCalledWith({
      email: "member@example.com",
      password: PASSWORD,
    })
    expect(router.currentRoute.value.path).toBe("/verify")
  })

  // 测试：外部或协议相对的 redirect 被忽略，登录后回到站内默认页。
  it("拒绝外部返回地址", async () => {
    loginMock.mockResolvedValue(makeUser("member"))
    const { wrapper: w, router } = await mountLogin(
      "/login?redirect=//evil.example",
    )

    await fillAndSubmit(w)
    await flushPromises()

    expect(router.currentRoute.value.path).toBe("/")
  })

  // 测试：失败时显示后端可读原因（role=alert），保留邮箱、清空密码，且密码不出现在日志中。
  it("失败时显示原因、保留邮箱并清空密码", async () => {
    loginMock.mockRejectedValue(
      new ApiError(401, "invalid_credentials", "邮箱或密码错误"),
    )
    const { wrapper: w, router } = await mountLogin()

    await fillAndSubmit(w)
    await flushPromises()

    expect(w.find('[role="alert"]').text()).toContain("邮箱或密码错误")
    expect(
      (w.find('input[type="email"]').element as HTMLInputElement).value,
    ).toBe("member@example.com")
    expect(
      (w.find('input[type="password"]').element as HTMLInputElement).value,
    ).toBe("")
    expect(router.currentRoute.value.name).toBe("login")
    expect(JSON.stringify(logCalls)).not.toContain(PASSWORD)
    expect(JSON.stringify(localStorage)).not.toContain(PASSWORD)
  })

  // 测试：限流 429 时显示稍后再试的提示。
  it("限流时提示稍后再试", async () => {
    loginMock.mockRejectedValue(
      new ApiError(429, "too_many_attempts", "尝试过于频繁，请 15 分钟后再试"),
    )
    const { wrapper: w } = await mountLogin()

    await fillAndSubmit(w)
    await flushPromises()

    expect(w.find('[role="alert"]').text()).toContain("尝试过于频繁")
  })

  // 测试：会话过期或改密后带原因跳转到登录页时，展示对应提示。
  it.each([
    ["expired", "登录已过期"],
    ["password_changed", "密码已更新"],
    ["logged_out", "已安全退出"],
  ])("reason=%s 时显示“%s”", async (reason, text) => {
    const { wrapper: w } = await mountLogin(`/login?reason=${reason}`)

    expect(w.find('[data-testid="login-notice"]').text()).toContain(text)
  })
})
