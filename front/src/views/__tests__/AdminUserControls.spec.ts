import { flushPromises, type VueWrapper } from "@vue/test-utils"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { mountPage } from "../../__tests__/helpers/authHarness"
import { makeUser } from "../../__tests__/fixtures/users"
import { useUserStore } from "../../stores/user"

const api = vi.hoisted(() => ({
  listUsers: vi.fn(),
  readUser: vi.fn(),
  setChatLimit: vi.fn(),
  revokeUserSessions: vi.fn(),
  createUser: vi.fn(),
  updateUser: vi.fn(),
  resetUserPassword: vi.fn(),
  deleteUser: vi.fn(),
}))
vi.mock("../../api/adminUsers", () => api)
const me = makeUser("admin", { id: "me" }),
  target = makeUser("member", { id: "target" })
const quota = {
  hourly_limit: 3,
  occupied_slots: 2,
  remaining: 1,
  window_seconds: 3600,
  observed_at: "2026-10-22T00:00:00Z",
}
let wrapper: VueWrapper
async function mountUsers() {
  const { default: Page } = await import("../AdminUsersView.vue")
  const mounted = await mountPage(Page, {
    name: "admin-users",
    at: "/admin/users",
    setup: () => {
      const store = useUserStore()
      store.currentUser = me
      store.status = "authenticated"
    },
  })
  wrapper = mounted.wrapper
  await flushPromises()
  return wrapper
}
async function detail() {
  await wrapper.get('[data-testid="admin-user-detail-open"]').trigger("click")
  await flushPromises()
}
async function confirmation(action = "confirm") {
  await wrapper
    .get(`[data-testid="confirm-dialog-${action}-btn"]`)
    .trigger("click")
  await flushPromises()
}
beforeEach(() => {
  vi.resetAllMocks()
  api.listUsers.mockResolvedValue({
    items: [target],
    total: 1,
    offset: 0,
    limit: 20,
  })
  api.readUser.mockResolvedValue({
    user: target,
    active_session_count: 2,
    chat_limit: { ...quota },
  })
})
afterEach(() => {
  wrapper?.unmount()
  vi.useRealTimers()
  document.body.innerHTML = ""
})
// 验证搜索防抖恰为 300ms，所有筛选送到服务端并重置分页，不持久化邮箱搜索。
it("服务端搜索防抖并组合角色状态", async () => {
  await mountUsers()
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] })
  await wrapper.get('[data-testid="admin-user-search"]').setValue("member@")
  await vi.advanceTimersByTimeAsync(299)
  expect(api.listUsers).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(1)
  await flushPromises()
  expect(api.listUsers).toHaveBeenLastCalledWith({
    offset: 0,
    limit: 20,
    q: "member@",
  })
  await wrapper.get('[data-testid="admin-role-filter"]').setValue("member")
  await flushPromises()
  await wrapper.get('[data-testid="admin-status-filter"]').setValue("disabled")
  await flushPromises()
  expect(api.listUsers).toHaveBeenLastCalledWith({
    offset: 0,
    limit: 20,
    q: "member@",
    role: "member",
    status: "disabled",
  })
  expect(location.search).not.toContain("member")
})
// 验证慢请求后返回不会覆盖最新筛选结果，刷新失败时保留并标记旧数据。
it("过期响应不覆盖最新结果", async () => {
  await mountUsers()
  let old!: (value: unknown) => void
  api.listUsers
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          old = resolve
        }),
    )
    .mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 20 })
  await wrapper.get('[data-testid="admin-role-filter"]').setValue("admin")
  await wrapper.get('[data-testid="admin-role-filter"]').setValue("viewer")
  await flushPromises()
  old({ items: [target], total: 1, offset: 0, limit: 20 })
  await flushPromises()
  expect(wrapper.findAll('[data-testid="admin-user-row"]')).toHaveLength(0)
  expect(wrapper.text()).toMatch(/无匹配|暂无账号/)
})
// 验证详情显示安全会话数与占用口径，取消确认不发请求，确认撤销只发一次。
// 回归既有筛选行为：保存成功但不匹配筛选时说明原因，双重提交只创建一次。
it("筛选下创建反馈与重复提交保护", async () => {
  await mountUsers()
  api.listUsers.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 20 })
  await wrapper.get('[data-testid="admin-role-filter"]').setValue("viewer")
  await flushPromises()
  let complete!: (value: unknown) => void
  api.createUser.mockImplementation(
    () =>
      new Promise((resolve) => {
        complete = resolve
      }),
  )
  await wrapper.get('[data-testid="admin-create-user"]').trigger("click")
  const form = wrapper.get('[data-testid="admin-create-form"]')
  await form.get("[name=email]").setValue("new-member@example.com")
  await form.get("[name=display_name]").setValue("新成员")
  await form.get("[name=password]").setValue("Secure-Password-2026")
  await form.get("[name=confirm_password]").setValue("Secure-Password-2026")
  await form.trigger("submit")
  await form.trigger("submit")
  expect(api.createUser, "进行中的创建请求不得重复发送").toHaveBeenCalledTimes(
    1,
  )
  complete({ ...target, id: "created" })
  await flushPromises()
  expect(wrapper.text(), "新成员不匹配只读筛选时应说明保存结果").toContain(
    "已保存，当前筛选下不可见",
  )
  expect(wrapper.find('[data-testid="admin-create-form"]').exists()).toBe(false)
})
// 回归详情代次保护：切换对象后，旧对象的慢响应不得污染当前抽屉。
it("详情切换拒绝旧对象响应", async () => {
  const other = makeUser("viewer", {
    id: "other",
    email: "other@example.com",
    display_name: "当前详情",
  })
  api.listUsers.mockResolvedValue({
    items: [target, other],
    total: 2,
    offset: 0,
    limit: 20,
  })
  let old!: (value: unknown) => void
  api.readUser
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          old = resolve
        }),
    )
    .mockResolvedValueOnce({
      user: other,
      active_session_count: 8,
      chat_limit: quota,
    })
  await mountUsers()
  await wrapper
    .findAll('[data-testid="admin-user-detail-open"]')[0]!
    .trigger("click")
  await wrapper.get('[aria-label="关闭抽屉"]').trigger("click")
  await wrapper
    .findAll('[data-testid="admin-user-detail-open"]')[1]!
    .trigger("click")
  await flushPromises()
  old({ user: target, active_session_count: 99, chat_limit: quota })
  await flushPromises()
  const panel = wrapper.get('[role="dialog"]')
  expect(panel.text(), "抽屉必须保留最新目标").toContain("other@example.com")
  expect(panel.get('[data-testid="admin-live-sessions"]').text()).toBe("8")
})
// 回归刷新失败场景：保留已有列表，但明确标记旧数据和失败原因。
it("用户刷新失败保留并标记旧结果", async () => {
  await mountUsers()
  api.listUsers.mockRejectedValue(new Error("账号目录暂不可读"))
  await wrapper.get('[data-testid="admin-status-filter"]').setValue("disabled")
  await flushPromises()
  expect(
    wrapper.findAll('[data-testid="admin-user-row"]'),
    "刷新失败不能误清空已有结果",
  ).toHaveLength(1)
  expect(wrapper.text()).toContain("旧数据")
  expect(wrapper.text()).toContain("账号目录暂不可读")
})
// 验证详情显示安全会话数与占用口径，取消确认不发请求，确认撤销只发一次。
it("详情与撤销设备会话", async () => {
  await mountUsers()
  await detail()
  expect(wrapper.text()).toContain("已占用额度（含处理中）")
  expect(wrapper.get('[data-testid="admin-live-sessions"]').text()).toContain(
    "2",
  )
  await wrapper.get('[data-testid="admin-revoke-sessions"]').trigger("click")
  await confirmation("cancel")
  expect(api.revokeUserSessions).not.toHaveBeenCalled()
  api.revokeUserSessions.mockResolvedValue({ revoked_count: 2 })
  api.readUser.mockResolvedValue({
    user: target,
    active_session_count: 0,
    chat_limit: quota,
  })
  await wrapper.get('[data-testid="admin-revoke-sessions"]').trigger("click")
  await confirmation()
  expect(api.revokeUserSessions).toHaveBeenCalledOnce()
  expect(wrapper.get('[data-testid="admin-live-sessions"]').text()).toContain(
    "0",
  )
})
// 验证收紧额度需说明影响并确认，输入错误不发请求，失败保留当前详情。
it("额度修改确认与失败恢复", async () => {
  await mountUsers()
  await detail()
  await wrapper.get('[data-testid="admin-quota-input"]').setValue("0")
  await wrapper.get('[data-testid="admin-quota-save"]').trigger("click")
  expect(api.setChatLimit).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain("100000")
  await wrapper.get('[data-testid="admin-quota-input"]').setValue("1")
  await wrapper.get('[data-testid="admin-quota-save"]').trigger("click")
  expect(wrapper.text()).toContain("已有预留")
  expect(api.setChatLimit).not.toHaveBeenCalled()
  api.setChatLimit.mockRejectedValue(new Error("额度暂不可写"))
  await confirmation()
  expect(wrapper.text()).toContain("额度暂不可写")
  expect(
    wrapper.get('[data-testid="admin-quota-input"]').element,
  ).toHaveProperty("value", "1")
})
// 验证删除必须匹配邮箱，确认取消及焦点恢复符合高风险操作约定。
it("删除账号必须输入目标邮箱并恢复焦点", async () => {
  await mountUsers()
  const button = wrapper.get('[data-testid="admin-user-delete"]')
  await button.trigger("click")
  const confirm = wrapper.get('[data-testid="confirm-dialog-confirm-btn"]')
  expect(confirm.attributes("disabled")).toBeDefined()
  await wrapper
    .get('[data-testid="confirm-dialog-input"]')
    .setValue("wrong@example.com")
  expect(confirm.attributes("disabled")).toBeDefined()
  await wrapper
    .get('[data-testid="confirm-dialog-input"]')
    .setValue(target.email!)
  expect(confirm.attributes("disabled")).toBeUndefined()
  await confirmation("cancel")
  expect(api.deleteUser).not.toHaveBeenCalled()
  expect(document.activeElement).toBe(button.element)
})
// 验证无邮箱旧账号使用完整 UUID 确认，不接受可能重复的显示名称。
it("无邮箱旧账号删除使用唯一账号标识", async () => {
  const legacy = { ...target, email: null }
  api.listUsers.mockResolvedValue({
    items: [legacy],
    total: 1,
    offset: 0,
    limit: 20,
  })
  await mountUsers()
  await wrapper.get('[data-testid="admin-user-delete"]').trigger("click")
  expect(wrapper.text(), "旧账号没有邮箱时应明确要求完整 UUID").toContain(
    "输入完整账号 UUID 以确认",
  )
  const input = wrapper.get('[data-testid="confirm-dialog-input"]')
  await input.setValue(legacy.display_name)
  expect(
    wrapper
      .get('[data-testid="confirm-dialog-confirm-btn"]')
      .attributes("disabled"),
  ).toBeDefined()
  await input.setValue(legacy.id)
  expect(
    wrapper
      .get('[data-testid="confirm-dialog-confirm-btn"]')
      .attributes("disabled"),
  ).toBeUndefined()
  await confirmation("cancel")
  expect(api.deleteUser).not.toHaveBeenCalled()
})
// 验证当前管理员不提供撤销自身设备动作。
it("自身会话引导账户页面", async () => {
  api.listUsers.mockResolvedValue({
    items: [me],
    total: 1,
    offset: 0,
    limit: 20,
  })
  api.readUser.mockResolvedValue({
    user: me,
    active_session_count: 1,
    chat_limit: quota,
  })
  await mountUsers()
  await detail()
  expect(wrapper.find('[data-testid="admin-revoke-sessions"]').exists()).toBe(
    false,
  )
  expect(
    wrapper.get('[data-testid="admin-own-sessions"]').attributes("href"),
  ).toBe("/account")
})
