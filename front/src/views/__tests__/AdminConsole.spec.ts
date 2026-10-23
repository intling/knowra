import { flushPromises, mount, type VueWrapper } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { createMemoryHistory, RouterView } from "vue-router"

import { makeUser } from "../../__tests__/fixtures/users"
import { mountPage } from "../../__tests__/helpers/authHarness"
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

const MODEL = {
  id: "model-1",
  name: "测试聊天配置",
  kind: "chat",
  base_url: "https://models.example/v1",
  model: "chat-example",
  has_api_key: true,
  enabled: true,
  is_default: false,
  timeout_seconds: 15,
  max_retries: 1,
  dimensions: null,
  api_format: null,
  created_at: "2026-10-22T00:00:00Z",
  updated_at: "2026-10-22T00:00:00Z",
}
const fetchMock = vi.fn()
let wrapper: VueWrapper | null = null

function respond(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body }
}

async function mountModels(role: UserRole = "admin") {
  const pinia = createPinia()
  setActivePinia(pinia)
  const user = useUserStore()
  user.currentUser = makeUser(role, {
    permissions:
      role === "admin"
        ? ["users:manage", "models:manage", "knowledge:read", "knowledge:write"]
        : ["knowledge:read"],
  })
  user.status = "authenticated"
  const { createAppRouter } = await import("../../router")
  const router = createAppRouter(createMemoryHistory())
  const match = router.resolve("/admin/models")
  expect(
    match.matched.length,
    "后台缺少 /admin/models 模型配置路由",
  ).toBeGreaterThan(0)
  await router.push("/admin/models")
  await router.isReady()
  wrapper = mount(RouterView, {
    global: { plugins: [pinia, router] },
    attachTo: document.body,
  })
  await flushPromises()
  return { wrapper, router }
}

async function fillModel(w: VueWrapper, kind = "chat") {
  await w.get('[data-testid="admin-create-model"]').trigger("click")
  const form = w.get('[data-testid="admin-model-form"]')
  await form.get('[name="kind"]').setValue(kind)
  await form.get('[name="name"]').setValue("新模型配置")
  await form.get('[name="base_url"]').setValue("http://localhost:11434/v1")
  await form.get('[name="model"]').setValue("local-example")
  await form.get('[name="api_key"]').setValue("synthetic-form-test-key")
  return form
}

async function confirmModel() {
  const button = document.querySelector<HTMLButtonElement>(
    '[data-testid="confirm-dialog-confirm-btn"]',
  )
  expect(button, "切换默认模型属于影响全系统的操作，必须确认").not.toBeNull()
  button!.click()
  await flushPromises()
}

describe("后台入口和模型配置", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchMock.mockResolvedValue(
      respond({ items: [MODEL], total: 1, offset: 0, limit: 20 }),
    )
    vi.stubGlobal("fetch", fetchMock)
  })
  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ""
    vi.unstubAllGlobals()
  })

  // 验证后台根入口兼容跳转至运行总览，模型页带会话和显式权限元数据。
  it("后台入口跳转运行总览并声明模型管理权限", async () => {
    const { router } = await mountModels()
    const models = router.resolve("/admin/models")
    expect(models.meta.requiresAuth).toBe(true)
    expect(models.meta.permission).toBe("models:manage")
    await router.push("/admin")
    expect(router.currentRoute.value.path).toBe("/admin/overview")
  })

  // 验证账户菜单将管理员引导到统一后台，而非只有原用户管理单页入口。
  it("管理员菜单提供后台管理入口", async () => {
    const { default: SidebarUser } =
      await import("../../components/sidebar/SidebarUser.vue")
    const mounted = await mountPage(SidebarUser, {
      name: "home",
      at: "/",
      setup: () => {
        useUserStore().currentUser = makeUser("admin")
        useUserStore().status = "authenticated"
      },
    })
    wrapper = mounted.wrapper
    await wrapper.get('[data-testid="user-menu-button"]').trigger("click")
    const link = wrapper.get('[data-testid="menu-admin"]')
    expect(link.text()).toContain("后台管理")
    expect(link.attributes("href")).toBe("/admin")
  })

  // 验证匿名访问模型页回到登录，保留安全的站内返回路径。
  it("匿名访问模型页要求登录", async () => {
    setActivePinia(createPinia())
    fetchMock.mockResolvedValue(
      respond({ code: "auth_required", detail: "请先登录" }, 401),
    )
    const { createAppRouter } = await import("../../router")
    const router = createAppRouter(createMemoryHistory())
    expect(
      router.resolve("/admin/models").matched.length,
      "缺少需认证的模型配置路由",
    ).toBeGreaterThan(0)
    await router.push("/admin/models")
    expect(router.currentRoute.value.name).toBe("login")
    expect(router.currentRoute.value.query.redirect).toBe("/admin/models")
  })

  // 验证成员和只读用户不能请求模型配置，界面给出权限提示。
  it.each(["member", "viewer"] as const)(
    "%s 不能读取模型配置",
    async (role) => {
      const { wrapper: w } = await mountModels(role)
      expect(w.text()).toMatch(/权限/)
      expect(
        fetchMock.mock.calls.filter(([url]) =>
          String(url).includes("/admin/models"),
        ),
      ).toHaveLength(0)
    },
  )

  // 验证管理员列表能查看配置地址和默认状态，且提供后台双向导航。
  it("模型列表显示基本信息与后台导航", async () => {
    const { wrapper: w } = await mountModels()
    expect(w.text()).toContain("测试聊天配置")
    expect(w.text()).toContain("https://models.example/v1")
    expect(w.find('a[href="/admin/users"]').exists()).toBe(true)
    expect(w.find('a[href="/"]').exists()).toBe(true)
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      credentials: "include",
    })
  })

  // 验证四种用途可选择，模型新增通过统一 API 发送且成功清空秘密。
  it.each(["chat", "embedding", "rerank", "query_rewrite"])(
    "新增 %s 模型配置",
    async (kind) => {
      const { wrapper: w } = await mountModels()
      const form = await fillModel(w, kind)
      fetchMock.mockImplementation(async (_url: string, init?: RequestInit) =>
        init?.method === "POST"
          ? respond({ ...MODEL, kind, name: "新模型配置" }, 201)
          : respond({ items: [MODEL], total: 1, offset: 0, limit: 20 }),
      )
      await form.trigger("submit")
      await flushPromises()
      const request = fetchMock.mock.calls.find(
        ([, init]) => init?.method === "POST",
      )
      expect(request?.[0]).toBe("/api/admin/models")
      const payload = JSON.parse(request?.[1].body ?? "{}")
      expect(payload).toMatchObject({
        kind,
        name: "新模型配置",
        base_url: "http://localhost:11434/v1",
        model: "local-example",
        api_key: "synthetic-form-test-key",
      })
      for (const input of w.findAll<HTMLInputElement>('input[type="password"]'))
        expect(input.element.value).toBe("")
    },
  )

  // 验证编辑表单不回填遮罩密钥，留空保存时不会发送伪密钥覆盖已有秘密。
  it("编辑密钥留空保留旧值", async () => {
    const { wrapper: w } = await mountModels()
    await w.get('[data-testid="admin-model-edit"]').trigger("click")
    const form = w.get('[data-testid="admin-model-form"]')
    expect(form.get<HTMLInputElement>('[name="api_key"]').element.value).toBe(
      "",
    )
    await form.get('[name="name"]').setValue("改名配置")
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) =>
      init?.method === "PATCH"
        ? respond({ ...MODEL, name: "改名配置" })
        : respond({ items: [MODEL], total: 1, offset: 0, limit: 20 }),
    )
    await form.trigger("submit")
    await flushPromises()
    const request = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "PATCH",
    )
    expect(request?.[0]).toBe("/api/admin/models/model-1")
    const payload = JSON.parse(request?.[1].body ?? "{}")
    expect([undefined, ""]).toContain(payload.api_key)
    expect(payload.clear_api_key).not.toBe(true)
  })

  // 验证设为默认经过确认，并更新对应配置状态。
  it("确认后设为默认模型", async () => {
    const { wrapper: w } = await mountModels()
    await w.get('[data-testid="admin-model-activate"]').trigger("click")
    expect(
      fetchMock.mock.calls.some(([, init]) => init?.method === "POST"),
    ).toBe(false)
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) =>
      init?.method === "POST"
        ? respond({ ...MODEL, is_default: true })
        : respond({
            items: [{ ...MODEL, is_default: true }],
            total: 1,
            offset: 0,
            limit: 20,
          }),
    )
    await confirmModel()
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          url === "/api/admin/models/model-1/activate" &&
          init?.method === "POST",
      ),
    ).toBe(true)
    expect(w.text()).toMatch(/默认/)
  })

  // 验证向量空间冲突时保留原默认状态并展示后端原因。
  it("模型激活被拒绝时显示索引冲突原因", async () => {
    const { wrapper: w } = await mountModels()
    await w.get('[data-testid="admin-model-activate"]').trigger("click")
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) =>
      init?.method === "POST"
        ? respond(
            {
              code: "embedding_index_conflict",
              detail: "已有索引，请先规划重建向量",
            },
            409,
          )
        : respond({ items: [MODEL], total: 1, offset: 0, limit: 20 }),
    )
    await confirmModel()
    expect(w.text()).toContain("已有索引，请先规划重建向量")
    expect(w.find('[data-testid="admin-model-activate"]').exists()).toBe(true)
  })

  // 验证取消模型删除不会发出 DELETE，配置保持可见。
  it("取消模型删除保留配置", async () => {
    const { wrapper: w } = await mountModels()
    await w.get('[data-testid="admin-model-delete"]').trigger("click")
    const cancel = document.querySelector<HTMLButtonElement>(
      '[data-testid="confirm-dialog-cancel-btn"]',
    )
    expect(cancel, "删除配置必须提供取消入口").not.toBeNull()
    cancel!.click()
    await flushPromises()
    expect(
      fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE"),
    ).toBe(false)
    expect(w.text()).toContain("测试聊天配置")
  })

  // 验证列表网络失败给出可读原因，并提供可见错误状态。
  it("模型列表失败显示具体原因", async () => {
    fetchMock.mockResolvedValue(
      respond({ code: "unavailable", detail: "模型配置暂时无法读取" }, 503),
    )
    const { wrapper: w } = await mountModels()
    expect(w.text()).toContain("模型配置暂时无法读取")
    expect(w.find('[role="alert"]').exists()).toBe(true)
  })
})
