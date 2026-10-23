import { flushPromises, type VueWrapper } from "@vue/test-utils"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { mountPage } from "../../__tests__/helpers/authHarness"
import { makeUser } from "../../__tests__/fixtures/users"
import { useUserStore } from "../../stores/user"
const api = vi.hoisted(() => ({
  listModels: vi.fn(),
  getEffectiveModels: vi.fn(),
  testModel: vi.fn(),
  createModel: vi.fn(),
  updateModel: vi.fn(),
  deleteModel: vi.fn(),
  activateModel: vi.fn(),
  deactivateModel: vi.fn(),
}))
vi.mock("../../api/adminModels", () => api)
const profile = {
  id: "p1",
  name: "聊天候选",
  kind: "chat",
  base_url: "http://localhost:9000/v1",
  model: "chat-one",
  has_api_key: true,
  enabled: false,
  is_default: false,
  revision: 3,
  timeout_seconds: 15,
  max_retries: 1,
  dimensions: null,
  api_format: null,
  created_at: "2026-10-22T00:00:00Z",
  updated_at: "2026-10-22T00:00:00Z",
}
let wrapper: VueWrapper
beforeEach(() => {
  vi.resetAllMocks()
  api.listModels.mockResolvedValue({
    items: [profile],
    total: 1,
    offset: 0,
    limit: 20,
  })
  api.getEffectiveModels.mockResolvedValue(
    ["chat", "embedding", "rerank", "query_rewrite"].map((kind) => ({
      kind,
      source: "environment",
      enabled: kind === "chat",
      profile_id: null,
      model: "env-model",
      profile_revision: null,
      binding_revision: 0,
      configuration_status: kind === "chat" ? "ok" : "disabled",
      latest_probe: null,
    })),
  )
})
afterEach(() => {
  wrapper?.unmount()
  vi.useRealTimers()
  document.body.innerHTML = ""
})
// 验证页面持续打开时，配置卡片和本页测试结果超过十五分钟自动过期，且不发起付费调用。
it("停留页面时自动更新测试过期状态", async () => {
  vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] })
  const probe = {
    probe_id: "probe1",
    status: "passed",
    code: "model_test_passed",
    detail: "连接与协议检查通过",
    latency_ms: 40,
    checked_at: new Date().toISOString(),
    config_revision: 3,
    is_current: true,
  }
  const effective = await api.getEffectiveModels()
  effective[0].latest_probe = probe
  api.getEffectiveModels.mockResolvedValue(effective)
  api.testModel.mockResolvedValue(probe)
  await open()
  await wrapper.get('[data-testid="admin-model-test"]').trigger("click")
  await wrapper
    .get('[data-testid="confirm-dialog-confirm-btn"]')
    .trigger("click")
  await flushPromises()
  expect(wrapper.text(), "刚完成的测试应在卡片和列表提供当前参考").toContain(
    "当前参考",
  )
  await vi.advanceTimersByTimeAsync(15 * 60 * 1000 + 1000)
  expect(wrapper.text(), "超过十五分钟后不得继续显示当前参考").not.toContain(
    "当前参考",
  )
  expect(wrapper.find('[data-testid="effective-model-card"]').text()).toContain(
    "已过期",
  )
  expect(wrapper.find('[data-testid="admin-model-row"]').text()).toContain(
    "已过期",
  )
  expect(api.testModel, "时间更新不能自动调用模型").toHaveBeenCalledTimes(1)
})
async function open() {
  const { default: Page } = await import("../AdminModelsView.vue")
  wrapper = (
    await mountPage(Page, {
      name: "admin-models",
      at: "/admin/models",
      setup: () => {
        useUserStore().currentUser = makeUser("admin")
        useUserStore().status = "authenticated"
      },
    })
  ).wrapper
  await flushPromises()
}
// 验证四用途生效卡片与候选配置分开呈现，环境来源和未启用状态准确。
it("四用途生效卡片", async () => {
  await open()
  expect(wrapper.findAll('[data-testid="effective-model-card"]')).toHaveLength(
    4,
  )
  expect(wrapper.text()).toContain("环境配置")
  expect(wrapper.text()).toContain("未启用")
  expect(wrapper.text()).toContain("配置版本 3")
})
// 验证禁用配置也可测试，确认前说明固定内容与费用，测试不自动切换默认。
it("测试须确认费用且不改变默认", async () => {
  await open()
  await wrapper.get('[data-testid="admin-model-test"]').trigger("click")
  expect(wrapper.text()).toContain("少量费用")
  expect(api.testModel).not.toHaveBeenCalled()
  api.testModel.mockResolvedValue({
    probe_id: "probe1",
    status: "passed",
    code: "model_test_passed",
    detail: "连接与协议检查通过",
    latency_ms: 40,
    checked_at: new Date().toISOString(),
    config_revision: 3,
    is_current: true,
  })
  await wrapper
    .get('[data-testid="confirm-dialog-confirm-btn"]')
    .trigger("click")
  await flushPromises()
  expect(api.testModel).toHaveBeenCalledWith("p1", 3)
  expect(api.activateModel).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain("连接与协议检查通过")
})
// 验证过期测试不作为当前可用性依据，版本冲突提示刷新且保留原配置。
it("测试结果过期与版本冲突", async () => {
  await open()
  api.testModel.mockResolvedValue({
    probe_id: "probe1",
    status: "passed",
    code: "model_test_passed",
    detail: "连接与协议检查通过",
    latency_ms: 40,
    checked_at: "2020-01-01T00:00:00Z",
    config_revision: 2,
    is_current: false,
  })
  await wrapper.get('[data-testid="admin-model-test"]').trigger("click")
  await wrapper
    .get('[data-testid="confirm-dialog-confirm-btn"]')
    .trigger("click")
  await flushPromises()
  expect(wrapper.text()).toContain("已过期")
  api.testModel.mockRejectedValue(new Error("配置已更新，请刷新后测试"))
  await wrapper.get('[data-testid="admin-model-test"]').trigger("click")
  await wrapper
    .get('[data-testid="confirm-dialog-confirm-btn"]')
    .trigger("click")
  await flushPromises()
  expect(wrapper.text()).toContain("配置已更新")
  expect(wrapper.text()).toContain("聊天候选")
})
