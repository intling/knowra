import { createPinia, setActivePinia } from "pinia"
import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

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

// 资料库分区只读调用已解析文档接口；此处固定返回 2 条，避免测试访问网络
const mockListParsedDocuments = vi.fn()

vi.mock("../../../api/documentParsing", () => ({
  listParsedDocuments: (...args: unknown[]) => mockListParsedDocuments(...args),
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
  mockListParsedDocuments.mockReset()
  mockListParsedDocuments.mockResolvedValue([{ id: "pd-1" }, { id: "pd-2" }])
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

// ── 重构 RED：侧边栏资料库分区、分区顺序、可访问的对话条目与删除确认 ─────────

describe("AppSidebar 资料库分区", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    resetStores()
  })

  // 验证侧边栏包含资料库分区，并展示已解析文档数量
  it("渲染资料库分区并显示已解析资料数量", async () => {
    const { default: AppSidebar } = await import("../AppSidebar.vue")
    const wrapper = mount(AppSidebar)
    await flushPromises()

    expect(wrapper.find('[data-testid="knowledge-info"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="knowledge-count"]').text()).toContain("2 份已解析资料")
  })

  // 验证分区顺序：头部 → 资料库 → 最近对话（资料库在对话列表之前，主线"先有资料再提问"）
  it("资料库分区位于对话列表之前", async () => {
    const { default: AppSidebar } = await import("../AppSidebar.vue")
    const wrapper = mount(AppSidebar)
    await flushPromises()

    const html = wrapper.html()
    expect(html.indexOf('data-testid="knowledge-info"')).toBeGreaterThan(-1)
    expect(html.indexOf('data-testid="knowledge-info"')).toBeLessThan(
      html.indexOf('data-testid="conversation-list"'),
    )
  })

  // 验证侧边栏字标显示中文品牌名「知寻」
  it("头部显示「知寻」字标", async () => {
    const { default: AppSidebar } = await import("../AppSidebar.vue")
    const wrapper = mount(AppSidebar)

    expect(wrapper.find('[data-testid="sidebar-header"]').text()).toContain("知寻")
  })
})

describe("ConversationList 分区标题顺序", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    resetStores()
  })

  // 验证空状态下「最近对话」标题出现在「暂无对话」之前（此前标题渲染在空状态之后）
  it("无对话时标题位于空状态之前", async () => {
    mockChatStore.conversations = []
    const { default: ConversationList } = await import("../ConversationList.vue")
    const wrapper = mount(ConversationList)

    const text = wrapper.text()
    expect(text.indexOf("最近对话")).toBeGreaterThan(-1)
    expect(text.indexOf("最近对话")).toBeLessThan(text.indexOf("暂无对话"))
  })

  // 验证有对话时标题位于第一个对话条目之前
  it("有对话时标题位于条目之前", async () => {
    mockChatStore.conversations = [
      {
        id: "c1",
        title: "第一章复习",
        messages: [],
        bubbles: [],
        createdAt: "2026-07-01T00:00:00Z",
        updatedAt: "2026-07-01T00:00:00Z",
      },
    ]
    const { default: ConversationList } = await import("../ConversationList.vue")
    const wrapper = mount(ConversationList)

    const text = wrapper.text()
    expect(text.indexOf("最近对话")).toBeLessThan(text.indexOf("第一章复习"))
  })
})

describe("ConversationItem 可访问性与删除确认", () => {
  const conversation = {
    id: "c-del",
    title: "待删除的对话",
    messages: [],
    bubbles: [],
    createdAt: "2026-07-01T00:00:00Z",
    updatedAt: "2026-07-01T00:00:00Z",
  }

  beforeEach(() => {
    setActivePinia(createPinia())
    resetStores()
  })

  const mounted: { unmount: () => void }[] = []

  afterEach(() => {
    mounted.splice(0).forEach((w) => w.unmount())
    document.body.innerHTML = ""
  })

  async function mountItem() {
    const { default: ConversationItem } = await import("../ConversationItem.vue")
    const w = mount(ConversationItem, {
      props: { conversation },
      attachTo: document.body,
    })
    mounted.push(w)
    return w
  }

  function dialog() {
    return document.querySelector('[data-testid="confirm-dialog-overlay"]')
  }

  // 验证条目主体是原生按钮（键盘可聚焦、Enter/Space 可选中），点击时切换对话
  it("条目主体为原生按钮并可选中对话", async () => {
    const wrapper = await mountItem()

    const select = wrapper.find('[data-testid="conversation-select"]')
    expect(select.element.tagName).toBe("BUTTON")
    await select.trigger("click")
    expect(mockChatStore.setActiveConversation).toHaveBeenCalledWith("c-del")
  })

  // 验证当前对话用 aria-current 标记，读屏用户可知道所在位置
  it("当前对话带 aria-current=page，非当前对话不带", async () => {
    mockChatStore.activeConversationId = "c-del"
    const active = await mountItem()
    expect(active.find('[data-testid="conversation-select"]').attributes("aria-current")).toBe("page")

    mockChatStore.activeConversationId = "other"
    const inactive = await mountItem()
    expect(inactive.find('[data-testid="conversation-select"]').attributes("aria-current")).toBeUndefined()
  })

  // 验证操作按钮有明确的中文可访问名称
  it("重命名与删除按钮带中文 aria-label", async () => {
    const wrapper = await mountItem()

    expect(wrapper.find('[data-testid="rename-conversation-btn"]').attributes("aria-label")).toBe("重命名对话")
    expect(wrapper.find('[data-testid="delete-conversation-btn"]').attributes("aria-label")).toBe("删除对话")
  })

  // 验证操作按钮在键盘聚焦条目时可见（focus-within），而不仅仅是鼠标悬停
  it("操作按钮容器在键盘聚焦时可见", async () => {
    const wrapper = await mountItem()

    const actions = wrapper.find('[data-testid="conversation-actions"]')
    expect(actions.classes()).toContain("group-focus-within:opacity-100")
  })

  // 验证点击删除先弹出确认框，此时不会删除
  it("点击删除弹出确认框且尚未删除", async () => {
    const wrapper = await mountItem()

    await wrapper.find('[data-testid="delete-conversation-btn"]').trigger("click")

    expect(dialog()).not.toBeNull()
    expect(dialog()!.textContent).toContain("待删除的对话")
    expect(mockChatStore.deleteConversation).not.toHaveBeenCalled()
    expect(mockChatStore.setActiveConversation).not.toHaveBeenCalled()
  })

  // 验证确认后才真正删除该对话
  it("确认后删除对话", async () => {
    const wrapper = await mountItem()

    await wrapper.find('[data-testid="delete-conversation-btn"]').trigger("click")
    const confirm = document.querySelector<HTMLButtonElement>('[data-testid="confirm-dialog-confirm-btn"]')
    confirm!.click()
    await wrapper.vm.$nextTick()

    expect(mockChatStore.deleteConversation).toHaveBeenCalledWith("c-del")
    expect(dialog()).toBeNull()
  })

  // 验证取消后关闭确认框且不删除
  it("取消后不删除并关闭确认框", async () => {
    const wrapper = await mountItem()

    await wrapper.find('[data-testid="delete-conversation-btn"]').trigger("click")
    document.querySelector<HTMLButtonElement>('[data-testid="confirm-dialog-cancel-btn"]')!.click()
    await wrapper.vm.$nextTick()

    expect(mockChatStore.deleteConversation).not.toHaveBeenCalled()
    expect(dialog()).toBeNull()
  })

  // 验证按 Esc 等同于取消
  it("按 Esc 取消删除", async () => {
    const wrapper = await mountItem()

    await wrapper.find('[data-testid="delete-conversation-btn"]').trigger("click")
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))
    await wrapper.vm.$nextTick()

    expect(mockChatStore.deleteConversation).not.toHaveBeenCalled()
    expect(dialog()).toBeNull()
  })

  // 验证关闭确认框后焦点回到触发它的删除按钮
  it("取消后焦点回到删除按钮", async () => {
    const wrapper = await mountItem()

    const del = wrapper.find('[data-testid="delete-conversation-btn"]')
    ;(del.element as HTMLElement).focus()
    await del.trigger("click")
    await wrapper.vm.$nextTick()
    document.querySelector<HTMLButtonElement>('[data-testid="confirm-dialog-cancel-btn"]')!.click()
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    expect(document.activeElement).toBe(del.element)
  })
})
