import { flushPromises, type VueWrapper } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { makeUser } from "../../__tests__/fixtures/users"
import { mountPage } from "../../__tests__/helpers/authHarness"
import { listUsers, updateUser } from "../../api/adminUsers"
import { ApiError } from "../../api/client"
import type { User, UserRole } from "../../api/users"
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
vi.mock("../../api/adminUsers", () => ({
  listUsers: vi.fn(),
  updateUser: vi.fn(),
}))

const listMock = vi.mocked(listUsers)
const updateMock = vi.mocked(updateUser)

const ME = makeUser("admin", { id: "me", email: "me@example.com" })
const MEMBER = makeUser("member", {
  id: "u-member",
  email: "member@example.com",
})

let wrapper: VueWrapper | null = null

async function mountAdmin(
  role: UserRole = "admin",
  items: User[] = [ME, MEMBER],
  total = items.length,
) {
  listMock.mockResolvedValue({ items, total, offset: 0, limit: 20 })
  const { default: AdminUsersView } = await import("../AdminUsersView.vue")
  const mounted = await mountPage(AdminUsersView, {
    name: "admin-users",
    at: "/admin/users",
    setup: () => {
      const store = useUserStore()
      store.currentUser = role === "admin" ? ME : makeUser(role)
      store.status = "authenticated"
    },
  })
  await flushPromises()
  wrapper = mounted.wrapper
  return mounted
}

function row(w: VueWrapper, email: string) {
  const found = w
    .findAll('[data-testid="admin-user-row"]')
    .find((r) => r.text().includes(email))
  expect(found, `缺少 ${email} 所在行`).toBeDefined()
  return found!
}

async function confirm(w: VueWrapper) {
  const button = document.querySelector<HTMLButtonElement>(
    '[data-testid="confirm-dialog-confirm-btn"]',
  )
  expect(button, "高影响操作必须先确认").not.toBeNull()
  button!.click()
  await flushPromises()
  await w.vm.$nextTick()
}

describe("AdminUsersView", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ""
  })

  // 测试：非管理员看到明确的权限不足提示，且不请求用户列表。
  it.each(["member", "viewer"] as const)(
    "%s 看到权限不足且不请求列表",
    async (role) => {
      const { wrapper: w } = await mountAdmin(role)

      expect(w.find('[data-testid="admin-forbidden"]').text()).toContain("权限")
      expect(listMock).not.toHaveBeenCalled()
    },
  )

  // 测试：管理员加载第一页用户，展示邮箱、角色与状态，并标记当前登录账号。
  it("管理员加载用户列表", async () => {
    const { wrapper: w } = await mountAdmin()

    expect(listMock).toHaveBeenCalledWith({ offset: 0, limit: 20 })
    expect(w.findAll('[data-testid="admin-user-row"]')).toHaveLength(2)
    expect(row(w, "me@example.com").text()).toContain("你")
    expect(
      (row(w, "member@example.com").find("select").element as HTMLSelectElement)
        .value,
    ).toBe("member")
  })

  // 测试：变更角色需确认，成功后刷新该行。
  it("变更角色经确认后调用 API 并更新行", async () => {
    updateMock.mockResolvedValue({
      ...MEMBER,
      role: "viewer",
      permissions: ["knowledge:read"],
    })
    const { wrapper: w } = await mountAdmin()

    await row(w, "member@example.com").find("select").setValue("viewer")
    expect(updateMock).not.toHaveBeenCalled()
    await confirm(w)

    expect(updateMock).toHaveBeenCalledWith("u-member", { role: "viewer" })
    expect(
      (row(w, "member@example.com").find("select").element as HTMLSelectElement)
        .value,
    ).toBe("viewer")
  })

  // 测试：禁用账号需确认，成功后行状态显示为已停用。
  it("禁用账号经确认后更新状态", async () => {
    updateMock.mockResolvedValue({ ...MEMBER, status: "disabled" })
    const { wrapper: w } = await mountAdmin()

    await row(w, "member@example.com")
      .find('[data-testid="status-toggle"]')
      .trigger("click")
    await confirm(w)

    expect(updateMock).toHaveBeenCalledWith("u-member", { status: "disabled" })
    expect(row(w, "member@example.com").text()).toContain("已停用")
  })

  // 测试：末位管理员保护被后端拒绝时，保留原行状态并显示明确原因。
  it("last_admin 失败时回滚并显示原因", async () => {
    updateMock.mockRejectedValue(
      new ApiError(409, "last_admin", "不能移除最后一位有效管理员"),
    )
    const { wrapper: w } = await mountAdmin()

    await row(w, "me@example.com").find("select").setValue("member")
    await confirm(w)

    expect(
      (row(w, "me@example.com").find("select").element as HTMLSelectElement)
        .value,
    ).toBe("admin")
    expect(row(w, "me@example.com").find('[role="alert"]').text()).toContain(
      "最后一位有效管理员",
    )
  })

  // 测试：当前登录账号不能被自己禁用（按钮不可用）。
  it("不能禁用自己", async () => {
    const { wrapper: w } = await mountAdmin()

    expect(
      row(w, "me@example.com")
        .find('[data-testid="status-toggle"]')
        .attributes("disabled"),
    ).toBeDefined()
  })

  // 测试：超过一页时可以翻到下一页。
  it("分页加载下一页", async () => {
    const { wrapper: w } = await mountAdmin("admin", [ME, MEMBER], 45)

    await w.find('[data-testid="admin-next-page"]').trigger("click")
    await flushPromises()

    expect(listMock).toHaveBeenLastCalledWith({ offset: 20, limit: 20 })
  })
})
