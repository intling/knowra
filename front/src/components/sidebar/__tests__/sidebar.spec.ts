import { createPinia, setActivePinia } from "pinia"
import { mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"

// ── Mock logger ────────────────────────────────────────────────────────────

vi.mock("../../../shared/logger", () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))

// ── Mock stores ────────────────────────────────────────────────────────────

const mockChatStore = {
  conversations: [] as Array<{
    id: string
    title: string
    messages: unknown[]
    bubbles: unknown[]
    createdAt: string
    updatedAt: string
  }>,
  activeConversationId: null as string | null,
  /** 当前活跃的对话对象（getter 模拟） */
  get activeConversation() {
    if (!this.activeConversationId) return null
    return this.conversations.find((c) => c.id === this.activeConversationId) ?? null
  },
  /** 非活跃的历史对话列表（getter 模拟） */
  get historyConversations() {
    return this.conversations.filter((c) => c.id !== this.activeConversationId)
  },
  addConversation: vi.fn(),
  deleteConversation: vi.fn(),
  renameConversation: vi.fn(),
  autoTitleConversation: vi.fn(),
  setActiveConversation: vi.fn(),
}

const mockUserStore = {
  currentUser: null as {
    id: string
    display_name: string
    email: string | null
    avatar_url: string | null
  } | null,
  isUserLoading: false,
  userError: null as string | null,
  loadCurrentUser: vi.fn(),
}

vi.mock("../../../stores/chat", () => ({
  useChatStore: () => mockChatStore,
}))

vi.mock("../../../stores/user", () => ({
  useUserStore: () => mockUserStore,
}))

// ── Test helpers ───────────────────────────────────────────────────────────

function resetStores() {
  mockChatStore.conversations = []
  mockChatStore.activeConversationId = null
  mockChatStore.addConversation = vi.fn()
  mockChatStore.deleteConversation = vi.fn()
  mockChatStore.renameConversation = vi.fn()
  mockChatStore.autoTitleConversation = vi.fn()
  mockChatStore.setActiveConversation = vi.fn()
  mockUserStore.currentUser = null
  mockUserStore.isUserLoading = false
  mockUserStore.userError = null
  mockUserStore.loadCurrentUser = vi.fn()
}

// ── Tests: AppSidebar ──────────────────────────────────────────────────────

describe("AppSidebar", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    resetStores()
  })

  describe("渲染结构", () => {
    it("渲染侧边栏容器（aside 语义元素）", async () => {
      const { default: AppSidebar } = await import("../AppSidebar.vue")
      const wrapper = mount(AppSidebar)

      expect(wrapper.find("aside").exists()).toBe(true)
    })

    it("渲染 SidebarHeader 区域", async () => {
      const { default: AppSidebar } = await import("../AppSidebar.vue")
      const wrapper = mount(AppSidebar)

      expect(wrapper.find('[data-testid="sidebar-header"]').exists()).toBe(true)
    })

    it("渲染 ConversationList 区域", async () => {
      const { default: AppSidebar } = await import("../AppSidebar.vue")
      const wrapper = mount(AppSidebar)

      expect(wrapper.find('[data-testid="conversation-list"]').exists()).toBe(true)
    })

    it("渲染 SidebarUser 区域", async () => {
      const { default: AppSidebar } = await import("../AppSidebar.vue")
      const wrapper = mount(AppSidebar)

      expect(wrapper.find('[data-testid="sidebar-user"]').exists()).toBe(true)
    })
  })
})

// ── Tests: ConversationList ────────────────────────────────────────────────

describe("ConversationList", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    resetStores()
  })

  describe("列表渲染", () => {
    it("有对话时渲染 ConversationItem 列表", async () => {
      mockChatStore.conversations = [
        { id: "c1", title: "对话1", messages: [], bubbles: [], createdAt: "2026-01-01T00:00:00Z", updatedAt: "2026-01-01T00:00:00Z" },
        { id: "c2", title: "对话2", messages: [], bubbles: [], createdAt: "2026-01-02T00:00:00Z", updatedAt: "2026-01-02T00:00:00Z" },
      ]

      const { default: ConversationList } = await import("../ConversationList.vue")
      const wrapper = mount(ConversationList)

      const items = wrapper.findAll('[data-testid="conversation-item"]')
      expect(items).toHaveLength(2)
    })

    it("每个对话条目显示标题", async () => {
      mockChatStore.conversations = [
        { id: "c1", title: "我的第一个问题", messages: [], bubbles: [], createdAt: "2026-01-01T00:00:00Z", updatedAt: "2026-01-01T00:00:00Z" },
      ]

      const { default: ConversationList } = await import("../ConversationList.vue")
      const wrapper = mount(ConversationList)

      expect(wrapper.text()).toContain("我的第一个问题")
    })
  })

  describe("空状态", () => {
    it("无对话时显示空状态提示", async () => {
      mockChatStore.conversations = []

      const { default: ConversationList } = await import("../ConversationList.vue")
      const wrapper = mount(ConversationList)

      expect(wrapper.find('[data-testid="conversation-list-empty"]').exists()).toBe(true)
    })

    it("无对话时显示引导文案", async () => {
      mockChatStore.conversations = []

      const { default: ConversationList } = await import("../ConversationList.vue")
      const wrapper = mount(ConversationList)

      expect(wrapper.text()).toContain("暂无对话")
    })

    it("无对话时不渲染 ConversationItem", async () => {
      mockChatStore.conversations = []

      const { default: ConversationList } = await import("../ConversationList.vue")
      const wrapper = mount(ConversationList)

      expect(wrapper.find('[data-testid="conversation-item"]').exists()).toBe(false)
    })
  })

  describe("列表排序", () => {
    it("对话按 conversation 数组顺序展示（store 已保证时间倒序）", async () => {
      mockChatStore.conversations = [
        { id: "c2", title: "最新对话", messages: [], bubbles: [], createdAt: "2026-01-02T00:00:00Z", updatedAt: "2026-01-02T00:00:00Z" },
        { id: "c1", title: "较早对话", messages: [], bubbles: [], createdAt: "2026-01-01T00:00:00Z", updatedAt: "2026-01-01T00:00:00Z" },
      ]

      const { default: ConversationList } = await import("../ConversationList.vue")
      const wrapper = mount(ConversationList)

      const items = wrapper.findAll('[data-testid="conversation-item"]')
      expect(items).toHaveLength(2)
      expect(items[0].text()).toContain("最新对话")
      expect(items[1].text()).toContain("较早对话")
    })
  })
})

// ── Tests: ConversationItem ────────────────────────────────────────────────

describe("ConversationItem", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    resetStores()
  })

  const defaultConversation = {
    id: "c-test",
    title: "测试对话标题",
    messages: [],
    bubbles: [],
    createdAt: "2026-07-01T00:00:00Z",
    updatedAt: "2026-07-01T00:00:00Z",
  }

  describe("基本渲染", () => {
    it("渲染对话标题", async () => {
      const { default: ConversationItem } = await import("../ConversationItem.vue")
      const wrapper = mount(ConversationItem, {
        props: { conversation: defaultConversation },
      })

      expect(wrapper.text()).toContain("测试对话标题")
    })

    it("活跃对话高亮显示", async () => {
      mockChatStore.activeConversationId = "c-test"

      const { default: ConversationItem } = await import("../ConversationItem.vue")
      const wrapper = mount(ConversationItem, {
        props: { conversation: defaultConversation },
      })

      const item = wrapper.find('[data-testid="conversation-item"]')
      expect(item.classes()).toContain("bg-neutral-100")
    })

    it("非活跃对话不高亮", async () => {
      mockChatStore.activeConversationId = "other-id"

      const { default: ConversationItem } = await import("../ConversationItem.vue")
      const wrapper = mount(ConversationItem, {
        props: { conversation: defaultConversation },
      })

      const item = wrapper.find('[data-testid="conversation-item"]')
      expect(item.classes()).not.toContain("bg-neutral-100")
    })
  })

  describe("操作按钮", () => {
    it("点击对话条目时调用 setActiveConversation", async () => {
      const { default: ConversationItem } = await import("../ConversationItem.vue")
      const wrapper = mount(ConversationItem, {
        props: { conversation: defaultConversation },
      })

      await wrapper.find('[data-testid="conversation-item"]').trigger("click")

      expect(mockChatStore.setActiveConversation).toHaveBeenCalledWith("c-test")
    })

    it("悬停时显示重命名按钮", async () => {
      mockChatStore.activeConversationId = "c-test"

      const { default: ConversationItem } = await import("../ConversationItem.vue")
      const wrapper = mount(ConversationItem, {
        props: { conversation: defaultConversation },
      })

      // 模拟 hover 状态：需要通过 CSS :hover 或直接操作
      // 在 jsdom 中无法真正触发 hover，检查按钮存在即可
      const renameBtn = wrapper.find('[data-testid="rename-conversation-btn"]')
      expect(renameBtn.exists()).toBe(true)
    })

    it("悬停时显示删除按钮", async () => {
      mockChatStore.activeConversationId = "c-test"

      const { default: ConversationItem } = await import("../ConversationItem.vue")
      const wrapper = mount(ConversationItem, {
        props: { conversation: defaultConversation },
      })

      const deleteBtn = wrapper.find('[data-testid="delete-conversation-btn"]')
      expect(deleteBtn.exists()).toBe(true)
    })
  })
})
