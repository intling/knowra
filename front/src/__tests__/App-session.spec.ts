import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { defineComponent } from "vue"
import { createMemoryHistory, createRouter } from "vue-router"
import { describe, expect, it, vi } from "vitest"
import App from "../App.vue"
import { useUserStore } from "../stores/user"
import { getCurrentUser } from "../api/users"
import { makeUser } from "./fixtures/users"

vi.mock("../api/users", () => ({
  getCurrentUser: vi.fn(),
  updateMyProfile: vi.fn(),
  changeMyPassword: vi.fn(),
}))
vi.mock("../shared/logger", () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
  getRingBuffer: vi.fn(),
}))

async function setup(
  status: "unknown" | "error" | "authenticated",
  guest = false,
) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const user = useUserStore()
  user.status = status
  user.userError = status === "error" ? "服务暂时不可用" : null
  if (status === "authenticated") user.currentUser = makeUser("member")
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: "/",
        component: defineComponent({
          template: '<p data-testid="page">页面内容</p>',
        }),
        meta: { requiresAuth: !guest, guestOnly: guest },
      },
    ],
  })
  await router.push("/")
  return { wrapper: mount(App, { global: { plugins: [pinia, router] } }), user }
}

describe("应用会话边界", () => {
  // 测试：会话未知或失败时私有页面不挂载，避免加载旧资料或发出私有请求。
  it.each(["unknown", "error"] as const)(
    "%s 状态不挂载私有页面",
    async (status) => {
      const { wrapper } = await setup(status)
      expect(wrapper.find('[data-testid="page"]').exists()).toBe(false)
      wrapper.unmount()
    },
  )
  // 测试：网络故障显示可读原因，点击重试恢复会话后再渲染私有页面。
  it("会话错误可重试并恢复页面", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue(makeUser("member"))
    const { wrapper } = await setup("error")
    expect(wrapper.find('[role="alert"]').text()).toContain("服务暂时不可用")
    await wrapper.find('[data-testid="session-retry"]').trigger("click")
    await flushPromises()
    expect(wrapper.find('[data-testid="page"]').exists()).toBe(true)
    wrapper.unmount()
  })
  // 测试：认证成功可访问私有页面；公开页面无需有效会话即可显示登录表单。
  it("已认证页面与公开入口正常挂载", async () => {
    const privatePage = await setup("authenticated")
    expect(privatePage.wrapper.find('[data-testid="page"]').exists()).toBe(true)
    privatePage.wrapper.unmount()
    const publicPage = await setup("unknown", true)
    expect(publicPage.wrapper.find('[data-testid="page"]').exists()).toBe(true)
    publicPage.wrapper.unmount()
  })
})
