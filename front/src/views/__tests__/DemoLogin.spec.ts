import { flushPromises, type VueWrapper } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { makeUser } from "../../__tests__/fixtures/users"
import { mountPage } from "../../__tests__/helpers/authHarness"
import { login } from "../../api/auth"
import { ApiError } from "../../api/client"

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

const DEMO_EMAIL = "demo@deerfd.com"
const FIXTURE_PASSWORD = "D3mo-Test^$Pass@2026"
const loginMock = vi.mocked(login)
let wrapper: VueWrapper | null = null

function encoded(payload: unknown) {
  return btoa(JSON.stringify(payload))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "")
}

function validFragment() {
  return `#demo=${encoded({ email: DEMO_EMAIL, password: FIXTURE_PASSWORD })}`
}

async function mountLogin(at = `/login${validFragment()}`) {
  const { default: LoginView } = await import("../LoginView.vue")
  const mounted = await mountPage(LoginView, { name: "login", at })
  wrapper = mounted.wrapper
  await flushPromises()
  return mounted
}

function input(w: VueWrapper, type: string) {
  return (w.find(`input[type="${type}"]`).element as HTMLInputElement).value
}

describe("演示链接预填", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    logCalls.length = 0
    localStorage.clear()
    sessionStorage.clear()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ""
  })

  // 验证链接填好指定 demo 的邮箱和含特殊符号密码，并且必须点击登录才提交。
  it("自动填好表单但不自动登录", async () => {
    const { wrapper: w } = await mountLogin()

    expect(input(w, "email")).toBe(DEMO_EMAIL)
    expect(input(w, "password")).toBe(FIXTURE_PASSWORD)
    expect(loginMock).not.toHaveBeenCalled()
    expect(
      w.find('[data-testid="login-submit"]').attributes("disabled"),
    ).toBeUndefined()
  })

  // 验证填充成功后清除片段并保留合法站内返回地址，不把密码转移到 query。
  it("移除凭据片段并保留站内 redirect", async () => {
    const { router } = await mountLogin(
      `/login?redirect=/verify${validFragment()}`,
    )

    expect(router.currentRoute.value.hash).toBe("")
    expect(router.currentRoute.value.query).toEqual({ redirect: "/verify" })
    expect(router.currentRoute.value.fullPath).not.toContain(FIXTURE_PASSWORD)
    expect(router.currentRoute.value.fullPath).not.toContain("demo=")
  })

  // 验证预填提示说明滚动 60 分钟、3 次限制，以及所有面试官共用账号额度。
  it("显示共享演示额度说明", async () => {
    const { wrapper: w } = await mountLogin()

    const notice = w.find('[data-testid="demo-notice"]')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toContain("60 分钟")
    expect(notice.text()).toContain("3 次")
    expect(notice.text()).toContain("共享")
    expect(notice.text()).not.toContain(FIXTURE_PASSWORD)
  })

  // 验证点击后走普通登录接口，传入原密码，成功清空密码并到站内 redirect。
  it("点击登录后提交预填凭据", async () => {
    loginMock.mockResolvedValue(makeUser("member"))
    const { wrapper: w, router } = await mountLogin(
      `/login?redirect=/verify${validFragment()}`,
    )

    await w.find('[data-testid="login-form"]').trigger("submit")
    await flushPromises()

    expect(loginMock).toHaveBeenCalledWith({
      email: DEMO_EMAIL,
      password: FIXTURE_PASSWORD,
    })
    expect(router.currentRoute.value.path).toBe("/verify")
  })

  // 验证预填密码不会通过日志、localStorage 或 sessionStorage 持久化。
  it("不将凭据写入日志或持久存储", async () => {
    const { wrapper: w } = await mountLogin()

    expect(input(w, "password")).toBe(FIXTURE_PASSWORD)
    expect(JSON.stringify(logCalls)).not.toContain(FIXTURE_PASSWORD)
    expect(JSON.stringify(localStorage)).not.toContain(FIXTURE_PASSWORD)
    expect(JSON.stringify(sessionStorage)).not.toContain(FIXTURE_PASSWORD)
    expect(w.find('[data-testid="go-register"]').attributes("href")).toBe(
      "/register",
    )
  })

  // 验证清理后的链接重新打开不会从残留存储中恢复 demo 密码。
  it("清理后的地址重新打开是普通空表单", async () => {
    const { wrapper: first, router } = await mountLogin()
    expect(input(first, "password")).toBe(FIXTURE_PASSWORD)
    const cleaned = router.currentRoute.value.fullPath
    first.unmount()
    wrapper = null

    const { wrapper: second } = await mountLogin(cleaned)

    expect(input(second, "email")).toBe("")
    expect(input(second, "password")).toBe("")
    expect(second.find('[data-testid="demo-notice"]').exists()).toBe(false)
  })

  // 验证错误密码或禁用账号沿用普通认证错误，邮箱保留、密码清空且不泄露凭据。
  it("认证失败后保留邮箱并清空密码", async () => {
    loginMock.mockRejectedValue(
      new ApiError(401, "invalid_credentials", "邮箱或密码错误"),
    )
    const { wrapper: w } = await mountLogin()

    await w.find('[data-testid="login-form"]').trigger("submit")
    await flushPromises()

    expect(loginMock).toHaveBeenCalledWith({
      email: DEMO_EMAIL,
      password: FIXTURE_PASSWORD,
    })
    expect(w.find('[role="alert"]').text()).toContain("邮箱或密码错误")
    expect(input(w, "email")).toBe(DEMO_EMAIL)
    expect(input(w, "password")).toBe("")
    expect(JSON.stringify(logCalls)).not.toContain(FIXTURE_PASSWORD)
  })

  // 验证无效编码、错误结构、其他身份及重复字段都被忽略，同时移除有问题的片段。
  it.each([
    ["无效编码", "not_base64!"],
    ["空载荷", ""],
    ["非 JSON", btoa("broken-json")],
    ["数组", encoded([{ email: DEMO_EMAIL, password: FIXTURE_PASSWORD }])],
    ["null", encoded(null)],
    ["缺少密码", encoded({ email: DEMO_EMAIL })],
    ["空密码", encoded({ email: DEMO_EMAIL, password: "" })],
    ["非字符串密码", encoded({ email: DEMO_EMAIL, password: 123456 })],
    ["过长密码", encoded({ email: DEMO_EMAIL, password: "a1".repeat(65) })],
    [
      "管理员身份",
      encoded({ email: "admin@example.com", password: FIXTURE_PASSWORD }),
    ],
    ["过大载荷", "a".repeat(5000)],
    [
      "重复字段",
      `${encoded({ email: DEMO_EMAIL, password: FIXTURE_PASSWORD })}&demo=other`,
    ],
  ])("%s 不填入表单且清除片段", async (_name, payload) => {
    const { wrapper: w, router } = await mountLogin(`/login#demo=${payload}`)

    expect(input(w, "email")).toBe("")
    expect(input(w, "password")).toBe("")
    expect(router.currentRoute.value.hash).toBe("")
    expect(loginMock).not.toHaveBeenCalled()
    expect(w.find('[data-testid="demo-notice"]').exists()).toBe(false)
  })

  // 验证没有片段的普通登录页面保持空表单，不显示演示账号提示。
  it("普通登录入口保持原行为", async () => {
    const { wrapper: w } = await mountLogin("/login")

    expect(input(w, "email")).toBe("")
    expect(input(w, "password")).toBe("")
    expect(w.find('[data-testid="demo-notice"]').exists()).toBe(false)
    expect(loginMock).not.toHaveBeenCalled()
  })
})
