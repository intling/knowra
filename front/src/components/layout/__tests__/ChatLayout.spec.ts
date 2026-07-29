import { mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"
import { nextTick } from "vue"

// ── Mock logger ──────────────────────────────────────────────────────────

vi.mock("../../../shared/logger", () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))

// ── Mock stores ───────────────────────────────────────────────────────────

const mockToggleSidebar = vi.fn()

vi.mock("../../../stores/app", () => ({
  useAppStore: () => ({
    sidebarCollapsed: false,
    toggleSidebar: mockToggleSidebar,
  }),
}))

vi.mock("../../../stores/chat", () => ({
  useChatStore: () => ({
    conversations: [],
    activeConversationId: null,
    get activeConversation() {
      if (!this.activeConversationId) return null
      return this.conversations.find((c: { id: string }) => c.id === this.activeConversationId) ?? null
    },
    get historyConversations() {
      return this.conversations.filter((c: { id: string }) => c.id !== this.activeConversationId)
    },
    addConversation: vi.fn(),
    deleteConversation: vi.fn(),
    renameConversation: vi.fn(),
    autoTitleConversation: vi.fn(),
    setActiveConversation: vi.fn(),
  }),
}))

// ── Viewport helpers ──────────────────────────────────────────────────────

function setViewportWidth(width: number) {
  Object.defineProperty(window, "innerWidth", {
    writable: true,
    configurable: true,
    value: width,
  })
  window.dispatchEvent(new Event("resize"))
}

// ── Tests: ChatLayout 移动端响应式 ───────────────────────────────────────

describe("ChatLayout 移动端响应式", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    setViewportWidth(1024)
    mockToggleSidebar.mockClear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe("桌面端（viewport ≥ 768px）", () => {
    it("侧边栏默认可见", async () => {
      const { default: ChatLayout } = await import("../ChatLayout.vue")
      const wrapper = mount(ChatLayout)

      const sidebar = wrapper.find('[data-testid="desktop-sidebar"]')
      expect(sidebar.exists()).toBe(true)
    })

    it("不显示汉堡菜单按钮", async () => {
      const { default: ChatLayout } = await import("../ChatLayout.vue")
      const wrapper = mount(ChatLayout)

      const hamburger = wrapper.find('[data-testid="hamburger-menu"]')
      expect(hamburger.isVisible()).toBe(false)
    })

    it("侧边栏为非 overlay 模式（正常流布局）", async () => {
      const { default: ChatLayout } = await import("../ChatLayout.vue")
      const wrapper = mount(ChatLayout)

      const sidebar = wrapper.find('[data-testid="desktop-sidebar"]')
      // 桌面端侧边栏在正常文档流中，不含 translate-x 隐藏类
      expect(sidebar.classes()).not.toContain("-translate-x-full")
    })
  })

  describe("移动端（viewport < 768px）", () => {
    it("侧边栏默认隐藏", async () => {
      setViewportWidth(375)
      const { default: ChatLayout } = await import("../ChatLayout.vue")
      const wrapper = mount(ChatLayout)

      const mobileSidebar = wrapper.find('[data-testid="mobile-sidebar"]')
      expect(mobileSidebar.exists()).toBe(true)
      // 移动端默认隐藏：translate-x-full
      expect(mobileSidebar.classes()).toContain("-translate-x-full")
    })

    it("显示汉堡菜单按钮", async () => {
      setViewportWidth(375)
      const { default: ChatLayout } = await import("../ChatLayout.vue")
      const wrapper = mount(ChatLayout)

      const hamburger = wrapper.find('[data-testid="hamburger-menu"]')
      expect(hamburger.exists()).toBe(true)
    })

    it("汉堡菜单按钮在桌面端不可见，移动端可见", async () => {
      // 桌面端
      setViewportWidth(1024)
      const { default: ChatLayout } = await import("../ChatLayout.vue")
      const wrapper1 = mount(ChatLayout)
      expect(wrapper1.find('[data-testid="hamburger-menu"]').isVisible()).toBe(false)
      wrapper1.unmount()

      // 移动端
      setViewportWidth(375)
      const wrapper2 = mount(ChatLayout)
      expect(wrapper2.find('[data-testid="hamburger-menu"]').isVisible()).toBe(true)
    })
  })

  describe("侧边栏折叠/展开切换", () => {
    it("移动端点击汉堡菜单展开侧边栏", async () => {
      setViewportWidth(375)
      const { default: ChatLayout } = await import("../ChatLayout.vue")
      const wrapper = mount(ChatLayout)

      const hamburger = wrapper.find('[data-testid="hamburger-menu"]')
      await hamburger.trigger("click")
      await nextTick()

      const mobileSidebar = wrapper.find('[data-testid="mobile-sidebar"]')
      expect(mobileSidebar.classes()).toContain("translate-x-0")
      expect(mobileSidebar.classes()).not.toContain("-translate-x-full")
    })

    it("移动端侧边栏展开后显示 overlay 背景", async () => {
      setViewportWidth(375)
      const { default: ChatLayout } = await import("../ChatLayout.vue")
      const wrapper = mount(ChatLayout)

      const hamburger = wrapper.find('[data-testid="hamburger-menu"]')
      await hamburger.trigger("click")
      await nextTick()

      const overlay = wrapper.find('[data-testid="sidebar-overlay"]')
      expect(overlay.exists()).toBe(true)
    })

    it("点击 overlay 遮罩层关闭侧边栏", async () => {
      setViewportWidth(375)
      const { default: ChatLayout } = await import("../ChatLayout.vue")
      const wrapper = mount(ChatLayout)

      // 先展开
      const hamburger = wrapper.find('[data-testid="hamburger-menu"]')
      await hamburger.trigger("click")
      await nextTick()

      // 点击 overlay
      const overlay = wrapper.find('[data-testid="sidebar-overlay"]')
      await overlay.trigger("click")
      await nextTick()

      // 侧边栏应再次隐藏
      const mobileSidebar = wrapper.find('[data-testid="mobile-sidebar"]')
      expect(mobileSidebar.classes()).toContain("-translate-x-full")
    })

    it("桌面端侧边栏始终在正常流布局中", async () => {
      setViewportWidth(1024)
      const { default: ChatLayout } = await import("../ChatLayout.vue")
      const wrapper = mount(ChatLayout)

      const sidebar = wrapper.find('[data-testid="desktop-sidebar"]')
      expect(sidebar.exists()).toBe(true)
    })
  })

  describe("汉堡菜单按钮视觉", () => {
    it("汉堡菜单按钮包含图标元素", async () => {
      setViewportWidth(375)
      const { default: ChatLayout } = await import("../ChatLayout.vue")
      const wrapper = mount(ChatLayout)

      const hamburger = wrapper.find('[data-testid="hamburger-menu"]')
      expect(hamburger.find('[data-testid="hamburger-icon"]').exists()).toBe(true)
    })

    it("汉堡菜单按钮位于对话区可见位置", async () => {
      setViewportWidth(375)
      const { default: ChatLayout } = await import("../ChatLayout.vue")
      const wrapper = mount(ChatLayout)

      const hamburger = wrapper.find('[data-testid="hamburger-menu"]')
      expect(hamburger.isVisible()).toBe(true)
    })
  })
})
