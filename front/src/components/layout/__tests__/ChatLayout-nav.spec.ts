/**
 * ChatLayout 移动端导航（重构 RED）
 *
 * 使用真实 Pinia store（chat / app / user），只 mock 网络 API 与 logger，
 * 以验证「选择/新建对话后自动收起抽屉」这类依赖 store 响应式的行为。
 */
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useChatStore } from "../../../stores/chat"

vi.mock("../../../shared/logger", () => ({
  createLogger: () => ({ debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))

const mockListParsedDocuments = vi.fn()

vi.mock("../../../api/documentParsing", () => ({
  listParsedDocuments: (...args: unknown[]) => mockListParsedDocuments(...args),
}))

vi.mock("../../../api/users", () => ({
  getCurrentUser: vi.fn().mockResolvedValue({
    id: "u1",
    display_name: "林同学",
    email: "lin@example.com",
    avatar_url: null,
  }),
}))

vi.mock("../../../api/search", () => ({ searchChunks: vi.fn() }))
vi.mock("../../../api/uploads", () => ({ uploadFile: vi.fn() }))

function setViewportWidth(width: number) {
  Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: width })
  window.dispatchEvent(new Event("resize"))
}

let wrapper: VueWrapper | null = null

async function mountLayout() {
  const { default: ChatLayout } = await import("../ChatLayout.vue")
  wrapper = mount(ChatLayout, { attachTo: document.body })
  await flushPromises()
  return wrapper
}

function drawer(w: VueWrapper) {
  return w.find('[data-testid="mobile-sidebar"]')
}

function menuButton(w: VueWrapper) {
  return w.find('[data-testid="hamburger-menu"]')
}

describe("ChatLayout 移动端抽屉导航", () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    setViewportWidth(390)
    mockListParsedDocuments.mockReset()
    mockListParsedDocuments.mockResolvedValue([])
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ""
    setViewportWidth(1024)
  })

  // 验证菜单按钮位于顶栏布局流内，而不是浮在内容上方（修复 390px 下按钮压住标题）
  it("菜单按钮渲染在顶栏内部", async () => {
    const w = await mountLayout()

    expect(w.find('[data-testid="chat-top-nav"] [data-testid="hamburger-menu"]').exists()).toBe(true)
  })

  // 验证抽屉关闭时对键盘与读屏不可达（inert + aria-hidden）
  it("抽屉关闭时带 inert 与 aria-hidden=true", async () => {
    const w = await mountLayout()

    expect(drawer(w).attributes("inert")).toBeDefined()
    expect(drawer(w).attributes("aria-hidden")).toBe("true")
    expect(menuButton(w).attributes("aria-expanded")).toBe("false")
  })

  // 验证打开抽屉后移除 inert、更新 aria-expanded，并把焦点移入抽屉的「新建对话」按钮
  it("打开抽屉后焦点进入抽屉", async () => {
    const w = await mountLayout()

    await menuButton(w).trigger("click")
    await flushPromises()

    expect(menuButton(w).attributes("aria-expanded")).toBe("true")
    expect(drawer(w).attributes("inert")).toBeUndefined()
    expect(drawer(w).attributes("aria-hidden")).toBeUndefined()
    expect(drawer(w).attributes("role")).toBe("dialog")
    expect(document.activeElement).toBe(
      drawer(w).find('[data-testid="new-conversation-btn"]').element,
    )
  })

  // 验证按 Esc 关闭抽屉，焦点回到菜单按钮
  it("按 Esc 关闭抽屉并把焦点还给菜单按钮", async () => {
    const w = await mountLayout()

    await menuButton(w).trigger("click")
    await flushPromises()
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))
    await flushPromises()

    expect(drawer(w).attributes("inert")).toBeDefined()
    expect(document.activeElement).toBe(menuButton(w).element)
  })

  // 验证点击遮罩关闭后焦点同样回到菜单按钮
  it("点击遮罩关闭后焦点回到菜单按钮", async () => {
    const w = await mountLayout()

    await menuButton(w).trigger("click")
    await flushPromises()
    await w.find('[data-testid="sidebar-overlay"]').trigger("click")
    await flushPromises()

    expect(drawer(w).attributes("inert")).toBeDefined()
    expect(document.activeElement).toBe(menuButton(w).element)
  })

  // 验证抽屉内提供显式的关闭按钮（不依赖遮罩或键盘）
  it("抽屉内关闭按钮可关闭抽屉", async () => {
    const w = await mountLayout()

    await menuButton(w).trigger("click")
    await flushPromises()
    await w.find('[data-testid="mobile-sidebar-close"]').trigger("click")
    await flushPromises()

    expect(drawer(w).attributes("inert")).toBeDefined()
  })

  // 验证在抽屉里新建对话后抽屉自动收起，用户直接回到对话区
  it("在抽屉中新建对话后自动收起", async () => {
    const w = await mountLayout()

    await menuButton(w).trigger("click")
    await flushPromises()
    await drawer(w).find('[data-testid="new-conversation-btn"]').trigger("click")
    await flushPromises()

    expect(useChatStore().conversations).toHaveLength(1)
    expect(drawer(w).attributes("inert")).toBeDefined()
    expect(menuButton(w).attributes("aria-expanded")).toBe("false")
  })

  // 验证在抽屉里选择历史对话后抽屉自动收起
  it("在抽屉中选择历史对话后自动收起", async () => {
    const store = useChatStore()
    const older = store.addConversation("旧对话")
    store.addConversation("新对话甲")
    const w = await mountLayout()

    await menuButton(w).trigger("click")
    await flushPromises()
    const items = drawer(w).findAll('[data-testid="conversation-select"]')
    const target = items.find((i) => i.text().includes("旧对话"))
    expect(target, "抽屉中应能找到「旧对话」条目的选择按钮").toBeTruthy()
    await target!.trigger("click")
    await flushPromises()

    expect(store.activeConversationId).toBe(older.id)
    expect(drawer(w).attributes("inert")).toBeDefined()
  })

  // 验证选择「当前」对话也会关闭抽屉（activeConversationId 不变，仅监听 ID 会漏掉此路径）
  it("在抽屉中选择当前对话也会收起", async () => {
    const store = useChatStore()
    store.addConversation("当前对话")
    const w = await mountLayout()

    await menuButton(w).trigger("click")
    await flushPromises()
    await drawer(w).find('[data-testid="conversation-select"]').trigger("click")
    await flushPromises()

    expect(drawer(w).attributes("inert")).toBeDefined()
  })

  // 验证抽屉打开时 Tab 焦点被限制在抽屉内：最后一个控件 Tab 回到第一个，第一个 Shift+Tab 到最后一个
  it("抽屉打开时 Tab / Shift+Tab 在抽屉内循环", async () => {
    const w = await mountLayout()

    await menuButton(w).trigger("click")
    await flushPromises()
    const focusables = Array.from(
      drawer(w).element.querySelectorAll<HTMLElement>("button:not([disabled]), a[href], input, [tabindex]:not([tabindex='-1'])"),
    )
    expect(focusables.length).toBeGreaterThan(1)
    const first = focusables[0]!
    const last = focusables[focusables.length - 1]!

    last.focus()
    last.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }))
    await flushPromises()
    expect(document.activeElement).toBe(first)

    first.focus()
    first.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true }))
    await flushPromises()
    expect(document.activeElement).toBe(last)
  })

  // 验证抽屉内弹出删除确认框后，Esc 只关闭最上层的确认框，抽屉保持打开且焦点回到删除按钮；再按 Esc 才关闭抽屉
  it("抽屉内确认框按 Esc 只关闭确认框，第二次 Esc 才关闭抽屉", async () => {
    const store = useChatStore()
    store.addConversation("要删除的对话")
    const w = await mountLayout()

    await menuButton(w).trigger("click")
    await flushPromises()
    const del = drawer(w).find('[data-testid="delete-conversation-btn"]')
    ;(del.element as HTMLElement).focus()
    await del.trigger("click")
    await flushPromises()
    expect(document.querySelector('[data-testid="confirm-dialog-overlay"]')).not.toBeNull()

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }))
    await flushPromises()

    expect(document.querySelector('[data-testid="confirm-dialog-overlay"]'), "确认框应已关闭").toBeNull()
    expect(drawer(w).attributes("inert"), "取消删除后抽屉应保持打开").toBeUndefined()
    expect(document.activeElement).toBe(del.element)
    expect(store.conversations).toHaveLength(1)

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }))
    await flushPromises()
    expect(drawer(w).attributes("inert")).toBeDefined()
  })

  // 验证确认框打开期间 Tab / Shift+Tab 只在确认框内循环，不被抽屉的焦点循环抢走
  it("抽屉内确认框打开时 Tab 焦点留在确认框内", async () => {
    const store = useChatStore()
    store.addConversation("要删除的对话")
    const w = await mountLayout()

    await menuButton(w).trigger("click")
    await flushPromises()
    await drawer(w).find('[data-testid="delete-conversation-btn"]').trigger("click")
    await flushPromises()
    const cancel = document.querySelector<HTMLElement>('[data-testid="confirm-dialog-cancel-btn"]')!
    const confirm = document.querySelector<HTMLElement>('[data-testid="confirm-dialog-confirm-btn"]')!

    confirm.focus()
    confirm.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(cancel)

    cancel.focus()
    cancel.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(confirm)
  })

  // 验证移动端只挂载一个侧边栏实例，资料库接口只请求一次（隐藏的桌面侧边栏不应重复请求）
  it("移动端只请求一次已解析文档接口", async () => {
    await mountLayout()

    expect(mockListParsedDocuments).toHaveBeenCalledTimes(1)
  })
})

describe("ChatLayout 桌面端", () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    setViewportWidth(1280)
    mockListParsedDocuments.mockReset()
    mockListParsedDocuments.mockResolvedValue([])
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ""
  })

  // 验证桌面端不挂载移动抽屉，资料库接口只请求一次
  it("桌面端只请求一次已解析文档接口且不渲染移动抽屉", async () => {
    const w = await mountLayout()

    expect(mockListParsedDocuments).toHaveBeenCalledTimes(1)
    expect(w.find('[data-testid="mobile-sidebar"]').exists()).toBe(false)
  })
})
