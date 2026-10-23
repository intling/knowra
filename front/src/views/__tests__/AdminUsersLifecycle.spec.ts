import { flushPromises, type VueWrapper } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { makeUser } from "../../__tests__/fixtures/users"
import { mountPage } from "../../__tests__/helpers/authHarness"
import { ApiError } from "../../api/client"
import { useUserStore } from "../../stores/user"

const api = vi.hoisted(() => ({
  listUsers: vi.fn(),
  updateUser: vi.fn(),
  createUser: vi.fn(),
  resetUserPassword: vi.fn(),
  deleteUser: vi.fn(),
}))
vi.mock("../../api/adminUsers", () => api)
vi.mock("../../shared/logger", () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))

const ME = makeUser("admin", { id: "me", email: "me@example.com" })
const TARGET = makeUser("member", { id: "target", email: "target@example.com" })
const CREATED = makeUser("viewer", {
  id: "created",
  email: "new@example.com",
  display_name: "新增成员",
})
let wrapper: VueWrapper | null = null

async function mountAdmin(offset = 0, total = 2) {
  api.listUsers.mockResolvedValue({
    items: [ME, TARGET],
    total,
    offset,
    limit: 20,
  })
  const { default: page } = await import("../AdminUsersView.vue")
  const mounted = await mountPage(page, {
    name: "admin-users",
    at: "/admin/users",
    setup: () => {
      const store = useUserStore()
      store.currentUser = ME
      store.status = "authenticated"
    },
  })
  wrapper = mounted.wrapper
  await flushPromises()
  return mounted.wrapper
}

function targetRow(w: VueWrapper) {
  const found = w
    .findAll('[data-testid="admin-user-row"]')
    .find((r) => r.text().includes(TARGET.email!))
  expect(found, "管理员列表应包含目标账号").toBeDefined()
  return found!
}

async function fillCreate(
  w: VueWrapper,
  confirmPassword = "Initial-Knowra-2026",
) {
  const open = w.find('[data-testid="admin-create-user"]')
  expect(open.exists(), "用户管理缺少新增账号入口，无法完成管理员建号").toBe(
    true,
  )
  await open.trigger("click")
  const form = w.get('[data-testid="admin-create-form"]')
  await form.get('[name="email"]').setValue("new@example.com")
  await form.get('[name="display_name"]').setValue("新增成员")
  await form.get('[name="password"]').setValue("Initial-Knowra-2026")
  await form.get('[name="confirm_password"]').setValue(confirmPassword)
  await form.get('[name="role"]').setValue("viewer")
  return form
}

async function clickConfirmation(action: "confirm" | "cancel") {
  if (action === "confirm") {
    const input = document.querySelector<HTMLInputElement>(
      '[data-testid="confirm-dialog-input"]',
    )
    if (input) {
      input.value = TARGET.email!
      input.dispatchEvent(new Event("input", { bubbles: true }))
      await flushPromises()
    }
  }
  const button = document.querySelector<HTMLButtonElement>(
    `[data-testid="confirm-dialog-${action}-btn"]`,
  )
  expect(button, "删除账号必须提供确认与取消操作").not.toBeNull()
  button!.click()
  await flushPromises()
}

describe("后台用户生命周期", () => {
  beforeEach(() => vi.resetAllMocks())
  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ""
  })

  // 验证管理员提交建号表单后更新列表，并清空初始密码。
  it("创建用户后刷新列表和清空密码", async () => {
    api.createUser.mockResolvedValue(CREATED)
    const w = await mountAdmin()
    const form = await fillCreate(w)
    api.listUsers.mockResolvedValue({
      items: [ME, TARGET, CREATED],
      total: 3,
      offset: 0,
      limit: 20,
    })
    await form.trigger("submit")
    await flushPromises()
    expect(api.createUser).toHaveBeenCalledWith({
      email: "new@example.com",
      display_name: "新增成员",
      password: "Initial-Knowra-2026",
      role: "viewer",
    })
    expect(w.text()).toContain("new@example.com")
    for (const input of w.findAll<HTMLInputElement>('input[type="password"]'))
      expect(input.element.value).toBe("")
  })

  // 验证两次初始密码不一致时在本地阻止请求并说明原因。
  it("密码不一致时不发送建号请求", async () => {
    const w = await mountAdmin()
    await (await fillCreate(w, "Different-Knowra-2026")).trigger("submit")
    await flushPromises()
    expect(api.createUser).not.toHaveBeenCalled()
    expect(w.text()).toMatch(/一致/)
  })

  // 验证重复邮箱失败保留可编辑表单，并显示后端具体原因。
  it("建号失败保留表单并显示错误", async () => {
    api.createUser.mockRejectedValue(
      new ApiError(409, "email_conflict", "该邮箱已被其他账号使用"),
    )
    const w = await mountAdmin()
    await (await fillCreate(w)).trigger("submit")
    await flushPromises()
    const form = w.get('[data-testid="admin-create-form"]')
    expect(form.text()).toContain("该邮箱已被其他账号使用")
    expect(form.get<HTMLInputElement>('[name="email"]').element.value).toBe(
      "new@example.com",
    )
  })

  // 验证提交进行中禁用重复提交，避免重复创建账号。
  it("建号进行中只提交一次", async () => {
    let finish!: (user: typeof CREATED) => void
    api.createUser.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    const w = await mountAdmin()
    const form = await fillCreate(w)
    await form.trigger("submit")
    await form.trigger("submit")
    expect(api.createUser).toHaveBeenCalledTimes(1)
    expect(form.get('[type="submit"]').attributes("disabled")).toBeDefined()
    finish(CREATED)
    await flushPromises()
  })

  // 验证重置他人密码提供新密码与确认字段，成功后清空秘密并显示重新登录说明。
  it("重置密码后清空密码并说明会话失效", async () => {
    api.resetUserPassword.mockResolvedValue(undefined)
    const w = await mountAdmin()
    const button = targetRow(w).find('[data-testid="admin-user-reset"]')
    expect(button.exists(), "目标账号缺少重置密码入口").toBe(true)
    await button.trigger("click")
    const form = w.get('[data-testid="admin-reset-form"]')
    await form.get('[name="new_password"]').setValue("Reset-Knowra-2026")
    await form.get('[name="confirm_password"]').setValue("Reset-Knowra-2026")
    await form.trigger("submit")
    await flushPromises()
    expect(api.resetUserPassword).toHaveBeenCalledWith("target", {
      new_password: "Reset-Knowra-2026",
    })
    expect(w.text()).toMatch(/重新登录/)
    for (const input of w.findAll<HTMLInputElement>('input[type="password"]'))
      expect(input.element.value).toBe("")
  })

  // 验证取消删除不调用 API，确认框明确说明目标邮箱和保留资料。
  it("删除前确认且取消不调用 API", async () => {
    const w = await mountAdmin()
    const button = targetRow(w).find('[data-testid="admin-user-delete"]')
    expect(button.exists(), "目标账号缺少删除入口").toBe(true)
    await button.trigger("click")
    expect(document.body.textContent).toContain("target@example.com")
    expect(document.body.textContent).toMatch(/保留/)
    expect(api.deleteUser).not.toHaveBeenCalled()
    await clickConfirmation("cancel")
    expect(api.deleteUser).not.toHaveBeenCalled()
  })

  // 验证删除成功后列表和总数刷新，当前管理员仍保留。
  it("删除成功刷新账号列表", async () => {
    api.deleteUser.mockResolvedValue(undefined)
    const w = await mountAdmin()
    const button = targetRow(w).find('[data-testid="admin-user-delete"]')
    expect(button.exists(), "目标账号缺少删除入口").toBe(true)
    await button.trigger("click")
    api.listUsers.mockResolvedValue({
      items: [ME],
      total: 1,
      offset: 0,
      limit: 20,
    })
    await clickConfirmation("confirm")
    expect(api.deleteUser).toHaveBeenCalledWith("target")
    expect(w.findAll('[data-testid="admin-user-row"]')).toHaveLength(1)
    expect(w.text()).toContain("me@example.com")
  })

  // 验证删除被后端拒绝时保留目标行并显示可读错误，不伪装成功。
  it("删除失败保留账号并显示原因", async () => {
    api.deleteUser.mockRejectedValue(
      new ApiError(409, "last_admin", "必须保留有效管理员"),
    )
    const w = await mountAdmin()
    const button = targetRow(w).find('[data-testid="admin-user-delete"]')
    expect(button.exists(), "目标账号缺少删除入口").toBe(true)
    await button.trigger("click")
    await clickConfirmation("confirm")
    expect(targetRow(w).exists()).toBe(true)
    expect(w.text()).toContain("必须保留有效管理员")
  })

  // 验证删除末页唯一账号后返回有效的上一页，而不是停留在空的越界页。
  it("删除末页最后一项返回有效页", async () => {
    api.deleteUser.mockResolvedValue(undefined)
    const w = await mountAdmin(0, 21)
    api.listUsers.mockResolvedValueOnce({
      items: [TARGET],
      total: 21,
      offset: 20,
      limit: 20,
    })
    await w.get('[data-testid="admin-next-page"]').trigger("click")
    await flushPromises()
    const button = targetRow(w).find('[data-testid="admin-user-delete"]')
    expect(button.exists(), "末页账号应有删除操作").toBe(true)
    await button.trigger("click")
    api.listUsers.mockImplementation(
      async ({ offset }: { offset: number }) => ({
        items: offset === 0 ? [ME] : [],
        total: 20,
        offset,
        limit: 20,
      }),
    )
    await clickConfirmation("confirm")
    expect(api.listUsers).toHaveBeenLastCalledWith({ offset: 0, limit: 20 })
    expect(w.text()).toContain("me@example.com")
  })
})
