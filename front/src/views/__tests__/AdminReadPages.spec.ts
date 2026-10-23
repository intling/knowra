import { flushPromises, type VueWrapper } from "@vue/test-utils"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { mountPage } from "../../__tests__/helpers/authHarness"
import { makeUser } from "../../__tests__/fixtures/users"
import { useUserStore } from "../../stores/user"
const api = vi.hoisted(() => ({
  listJobs: vi.fn(),
  getJob: vi.fn(),
  getOverview: vi.fn(),
  getSystemStatus: vi.fn(),
  listAuditEvents: vi.fn(),
}))
vi.mock("../../api/adminOperations", () => api)
const models = vi.hoisted(() => ({ getEffectiveModels: vi.fn() }))
vi.mock("../../api/adminModels", () => models)
const time = "2026-10-22T10:00:00Z"
const job = {
  id: "job1",
  kind: "chunk",
  uploaded_file_id: "upload-id",
  owner_user_id: "owner-id",
  owner_label: "账号 owner",
  status: "failed",
  attempt_count: 1,
  created_at: time,
  started_at: time,
  finished_at: time,
  duration_ms: 120,
  item_count: 0,
  error_code: "processing_failed",
  error_detail: "处理失败，请排查服务日志",
}
let wrapper: VueWrapper
async function mountRead(
  page: string,
  name: string,
  role: "admin" | "member" | "viewer" = "admin",
) {
  const mounted = await mountPage((await import(`../${page}.vue`)).default, {
    name: `admin-${name}`,
    at: `/admin/${name}`,
    setup: () => {
      const store = useUserStore()
      store.currentUser = makeUser(role)
      store.status = "authenticated"
    },
  })
  wrapper = mounted.wrapper
  await flushPromises()
  return wrapper
}
beforeEach(() => {
  vi.resetAllMocks()
  api.listJobs.mockResolvedValue({
    items: [job],
    total: 1,
    offset: 0,
    limit: 20,
  })
  api.getJob.mockResolvedValue({
    job,
    timeline: [job],
    missing_kinds: ["parse", "embedding"],
  })
  api.listAuditEvents.mockResolvedValue({
    items: [
      {
        id: "audit1",
        actor_user_id: "admin1",
        action: "user.update",
        resource_type: "user",
        resource_id: "user1",
        result: "success",
        changes_json: { role: { before: "member", after: "viewer" } },
        error_code: null,
        trace_id: "trace-one",
        created_at: time,
      },
    ],
    total: 1,
    offset: 0,
    limit: 20,
  })
  api.getSystemStatus.mockResolvedValue({
    checked_at: time,
    scope: "instance",
    instance_id: "instance-one",
    components: [
      { name: "database", status: "ok", detail: "数据库可访问" },
      { name: "pgvector", status: "unavailable", detail: "未检测到扩展" },
      { name: "model:rerank", status: "disabled", detail: "未启用" },
    ],
  })
  api.getOverview.mockResolvedValue({
    snapshot_at: time,
    users: { status: "ok", total: 3, active: 2, disabled: 1 },
    uploads: { status: "unavailable", total: null, logical_bytes: null },
    jobs_by_kind: [
      {
        kind: "parse",
        status: "ok",
        queued: 1,
        running: 0,
        succeeded_24h: 0,
        failed_24h: 2,
        success_rate_24h: 0,
      },
    ],
    attention_items: [
      {
        code: "failed_jobs",
        detail: "解析失败",
        href: "/admin/jobs?kind=parse&status=failed",
        count: 2,
      },
    ],
  })
  models.getEffectiveModels.mockResolvedValue([])
})
afterEach(() => {
  wrapper?.unmount()
  document.body.innerHTML = ""
})
// 验证任务列表筛选提交到服务端，详情诚实展示缺失阶段且没有跨用户写入口。
it("任务筛选、详情与缺失阶段", async () => {
  await mountRead("AdminJobsView", "jobs")
  expect(wrapper.findAll('[data-testid="admin-job-row"]')).toHaveLength(1)
  await wrapper.get('[data-testid="admin-job-kind"]').setValue("embedding")
  await flushPromises()
  expect(api.listJobs).toHaveBeenLastCalledWith(
    expect.objectContaining({ kind: "embedding", offset: 0 }),
  )
  await wrapper.get('[data-testid="admin-job-open"]').trigger("click")
  await flushPromises()
  expect(wrapper.text()).toContain("尚未创建")
  expect(wrapper.text()).toContain("processing_failed")
  expect(wrapper.text()).not.toMatch(/100%|重试任务|取消任务|正文预览/)
})
// 验证系统页显示检查时间和当前进程范围，保留不可用、未知与未启用语义。
it("系统状态检查时间与实例范围", async () => {
  await mountRead("AdminSystemView", "system")
  expect(wrapper.text()).toContain("当前实例")
  expect(wrapper.text()).toContain("instance-one")
  expect(wrapper.text()).toContain("无法使用")
  expect(wrapper.text()).toContain("未启用")
  api.getSystemStatus.mockRejectedValue(new Error("检查暂时失败"))
  await wrapper.get('[data-testid="admin-refresh"]').trigger("click")
  await flushPromises()
  expect(wrapper.text()).toContain("旧数据")
  expect(wrapper.text()).toContain("检查暂时失败")
})
// 验证总览未知值不显示零，统计时间/口径明确，异常卡片带筛选跳转。
it("总览真实口径与局部不可用", async () => {
  await mountRead("AdminOverviewView", "overview")
  expect(wrapper.get('[data-testid="overview-users-total"]').text()).toContain(
    "3",
  )
  expect(
    wrapper.get('[data-testid="overview-uploads-total"]').text(),
  ).toContain("无法获取")
  expect(wrapper.text()).toContain("原文件逻辑容量")
  expect(wrapper.text()).toContain("最近 24 小时")
  expect(wrapper.findAll("a").map((a) => a.attributes("href"))).toContain(
    "/admin/jobs?kind=parse&status=failed",
  )
  expect(wrapper.text()).not.toContain("在线人数")
})
// 验证审计只读筛选与安全前后值展示，trace 可复制且空页有明确提示。
it("审计筛选、前后值与追踪标识", async () => {
  await mountRead("AdminAuditView", "audit")
  expect(wrapper.text()).toContain("member")
  expect(wrapper.text()).toContain("viewer")
  expect(wrapper.text()).toContain("trace-one")
  await wrapper.get('[data-testid="admin-audit-result"]').setValue("failed")
  await flushPromises()
  expect(api.listAuditEvents).toHaveBeenLastCalledWith(
    expect.objectContaining({ result: "failed", offset: 0 }),
  )
  api.listAuditEvents.mockResolvedValue({
    items: [],
    total: 0,
    offset: 0,
    limit: 20,
  })
  await wrapper.get('[data-testid="admin-refresh"]').trigger("click")
  await flushPromises()
  expect(wrapper.text()).toContain("暂无匹配的管理操作")
  expect(wrapper.text()).not.toMatch(/导出日志|删除审计|编辑审计/)
})
// 验证成员和只读角色打开任意运维页面均不发起管理请求。
it.each(["member", "viewer"] as const)("%s 无权读取管理统计", async (role) => {
  await mountRead("AdminOverviewView", "overview", role)
  expect(wrapper.text()).toContain("权限")
  expect(api.getOverview).not.toHaveBeenCalled()
  expect(models.getEffectiveModels).not.toHaveBeenCalled()
})
