import { flushPromises, type VueWrapper } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { makeUser } from "../../__tests__/fixtures/users"
import { mountPage } from "../../__tests__/helpers/authHarness"
import { ApiError } from "../../api/client"
import { register } from "../../api/auth"

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

const registerMock = vi.mocked(register)
const PASSWORD = "Knowra-Pass-2026"

let wrapper: VueWrapper | null = null

async function mountRegister() {
  const { default: RegisterView } = await import("../RegisterView.vue")
  const mounted = await mountPage(RegisterView, {
    name: "register",
    at: "/register",
  })
  wrapper = mounted.wrapper
  return mounted
}

async function fill(
  w: VueWrapper,
  values: Partial<
    Record<"name" | "email" | "password" | "confirm", string>
  > = {},
) {
  const v = {
    name: "小张",
    email: "zhang@example.com",
    password: PASSWORD,
    confirm: PASSWORD,
    ...values,
  }
  await w.find('[data-testid="register-name"]').setValue(v.name)
  await w.find('[data-testid="register-email"]').setValue(v.email)
  await w.find('[data-testid="register-password"]').setValue(v.password)
  await w.find('[data-testid="register-confirm"]').setValue(v.confirm)
  await w.find('[data-testid="register-form"]').trigger("submit")
  await flushPromises()
}

describe("RegisterView", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ""
  })

  // 测试：字段具备标签与 new-password 自动填充属性，并提供前往登录的入口。
  it("渲染可访问的注册表单与登录入口", async () => {
    const { wrapper: w } = await mountRegister()

    expect(
      w.find('[data-testid="register-email"]').attributes("autocomplete"),
    ).toBe("email")
    expect(
      w.find('[data-testid="register-password"]').attributes("autocomplete"),
    ).toBe("new-password")
    expect(
      w.find('[data-testid="register-confirm"]').attributes("autocomplete"),
    ).toBe("new-password")
    for (const field of [
      "register-name",
      "register-email",
      "register-password",
      "register-confirm",
    ]) {
      const id = w.find(`[data-testid="${field}"]`).attributes("id")
      expect(
        w.find(`label[for="${id}"]`).exists(),
        `${field} 缺少关联 label`,
      ).toBe(true)
    }
    expect(w.find('[data-testid="go-login"]').attributes("href")).toBe("/login")
  })

  // 测试：本地校验失败（空名称、邮箱格式、弱密码、两次密码不一致）时不发出注册请求，并逐项提示。
  it.each([
    [{ name: "  " }, "名称"],
    [{ email: "not-an-email" }, "邮箱"],
    [{ password: "short1", confirm: "short1" }, "10"],
    [
      { password: "onlyletterspassword", confirm: "onlyletterspassword" },
      "数字",
    ],
    [{ confirm: "Different-Pass-2026" }, "不一致"],
  ])("校验失败 %o 时提示“%s”且不请求", async (values, message) => {
    const { wrapper: w } = await mountRegister()

    await fill(w, values)

    expect(registerMock).not.toHaveBeenCalled()
    expect(w.text()).toContain(message)
    expect(w.find('[aria-invalid="true"]').exists()).toBe(true)
  })

  // 测试：注册成功后建立登录态并进入工作台，只提交公开字段。
  it("注册成功后进入工作台", async () => {
    registerMock.mockResolvedValue(makeUser("member"))
    const { wrapper: w, router } = await mountRegister()

    await fill(w, { email: " Zhang@Example.com " })

    expect(registerMock).toHaveBeenCalledWith({
      display_name: "小张",
      email: "Zhang@Example.com",
      password: PASSWORD,
    })
    expect(router.currentRoute.value.path).toBe("/")
  })

  // 测试：邮箱已注册时显示后端原因并提供登录入口，停留在注册页。
  it("邮箱已注册时显示原因", async () => {
    registerMock.mockRejectedValue(
      new ApiError(409, "email_taken", "该邮箱已注册，请直接登录"),
    )
    const { wrapper: w, router } = await mountRegister()

    await fill(w)

    expect(w.find('[role="alert"]').text()).toContain("该邮箱已注册")
    expect(router.currentRoute.value.name).toBe("register")
  })
})
