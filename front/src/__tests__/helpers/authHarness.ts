/**
 * 用户体系页面测试的挂载辅助：真实 Pinia + 内存路由（其余页面用占位组件），
 * 让页面测试可以断言跳转目标而不依赖浏览器地址栏。
 */
import { mount, type VueWrapper } from "@vue/test-utils"
import { createPinia, setActivePinia, type Pinia } from "pinia"
import { defineComponent, h, type Component } from "vue"
import {
  createMemoryHistory,
  createRouter,
  RouterView,
  type Router,
} from "vue-router"

export const Placeholder = defineComponent({
  name: "PlaceholderPage",
  render: () => h("div", { "data-testid": "placeholder-page" }),
})

const ROUTES = [
  { path: "/", name: "home" },
  { path: "/verify", name: "verify" },
  { path: "/login", name: "login" },
  { path: "/register", name: "register" },
  { path: "/account", name: "account" },
  { path: "/admin/users", name: "admin-users" },
  ...["overview", "models", "jobs", "audit", "system"].map((name) => ({
    path: `/admin/${name}`,
    name: `admin-${name}`,
  })),
]

export function makeTestRouter(pageName: string, component: Component): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: ROUTES.map((route) => ({
      ...route,
      component: route.name === pageName ? component : Placeholder,
    })),
  })
}

export async function mountPage(
  component: Component,
  options: { name: string; at: string; setup?: (pinia: Pinia) => void },
): Promise<{ wrapper: VueWrapper; router: Router; pinia: Pinia }> {
  const pinia = createPinia()
  setActivePinia(pinia)
  options.setup?.(pinia)
  const router = makeTestRouter(options.name, component)
  await router.push(options.at)
  await router.isReady()
  const wrapper = mount(RouterView, {
    global: { plugins: [pinia, router] },
    attachTo: document.body,
  })
  return { wrapper, router, pinia }
}
