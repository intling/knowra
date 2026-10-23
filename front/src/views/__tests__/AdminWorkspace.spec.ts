import { flushPromises, mount, type VueWrapper } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { afterEach, expect, it } from "vitest"
import { createMemoryHistory, createRouter } from "vue-router"
import { makeUser } from "../../__tests__/fixtures/users"
import { useUserStore } from "../../stores/user"
import AdminFrame from "../../components/shared/AdminFrame.vue"

let wrapper: VueWrapper | undefined
afterEach(() => {
  wrapper?.unmount()
  document.body.innerHTML = ""
})
// 验证六页稳定路由与服务端权限一致，保留原有直达地址。
it("六个管理页面声明固定权限", async () => {
  const { createAppRouter } = await import("../../router")
  const router = createAppRouter(createMemoryHistory())
  for (const [path, permission] of [
    ["overview", "operations:read"],
    ["users", "users:manage"],
    ["models", "models:manage"],
    ["jobs", "operations:read"],
    ["audit", "audit:read"],
    ["system", "operations:read"],
  ]) {
    const route = router.resolve(`/admin/${path}`)
    expect(route.matched.length, `缺少管理页面 ${path}`).toBeGreaterThan(0)
    expect(route.meta.permission).toBe(permission)
    expect(route.meta.requiresAuth).toBe(true)
  }
})
// 验证管理壳层提供六页导航、位置、账户及返回入口。
it("管理侧栏与窄屏抽屉可访问", async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  useUserStore().currentUser = makeUser("admin", {
    permissions: [
      "users:manage",
      "models:manage",
      "operations:read",
      "audit:read",
    ],
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/:pathMatch(.*)*", component: { template: "<div />" } }],
  })
  await router.push("/admin/users")
  wrapper = mount(AdminFrame, {
    props: { title: "用户管理" },
    global: { plugins: [pinia, router] },
    attachTo: document.body,
  })
  expect(wrapper.findAll('[data-testid="admin-nav-link"]')).toHaveLength(6)
  expect(wrapper.find('a[href="/account"]').exists()).toBe(true)
  expect(wrapper.find('a[href="/"]').text()).toContain("知识书房")
  expect(wrapper.find('[aria-current="page"]').text()).toContain("用户管理")
  const trigger = wrapper.get('[data-testid="admin-menu-toggle"]')
  await trigger.trigger("click")
  await flushPromises()
  expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
  document.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
  )
  await flushPromises()
  expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  expect(document.activeElement).toBe(trigger.element)
})
