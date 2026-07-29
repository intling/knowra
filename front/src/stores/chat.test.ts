import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"

// ── Mock logger (same pattern as app.test.ts / user.test.ts) ──────────────

vi.mock("../shared/logger", () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))

// Lazy import after mocks are established
const { useChatStore, autoTitleFromMessage } = await import("./chat")

// ── Helpers ────────────────────────────────────────────────────────────────

const STORAGE_KEY = "knowra:chat"

function populateStorage(store: ReturnType<typeof useChatStore>) {
  const c1 = store.addConversation("第一个对话")
  const c2 = store.addConversation("第二个对话")
  return { c1, c2 }
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe("useChatStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  // ── 创建对话 ──────────────────────────────────────────────────────────

  describe("addConversation", () => {
    it("创建对话并设为活跃对话", () => {
      const store = useChatStore()
      const conv = store.addConversation("指定标题")

      expect(store.conversations).toHaveLength(1)
      expect(store.conversations[0].title).toBe("指定标题")
      expect(store.activeConversationId).toBe(conv.id)
    })

    it("创建对话时默认标题为空（UI 显示占位符）", () => {
      const store = useChatStore()
      store.addConversation()

      expect(store.conversations[0].title).toBe("")
    })

    it("新对话的 bubbles 初始为空数组", () => {
      const store = useChatStore()
      const conv = store.addConversation("测试")

      expect(conv.bubbles).toEqual([])
    })

    it("多次创建对话会依次添加到列表头部", () => {
      const store = useChatStore()
      store.addConversation("对话A")
      store.addConversation("对话B")
      store.addConversation("对话C")

      expect(store.conversations).toHaveLength(3)
      expect(store.conversations[0].title).toBe("对话C") // 最新在前
      expect(store.conversations[1].title).toBe("对话B")
      expect(store.conversations[2].title).toBe("对话A")
    })

    it("创建对话后设置 createdAt 和 updatedAt", () => {
      const store = useChatStore()
      const conv = store.addConversation("测试对话")

      expect(conv.createdAt).toBeTruthy()
      expect(conv.updatedAt).toBeTruthy()
      expect(conv.createdAt).toBe(conv.updatedAt)
    })

    it("新建对话时消息列表为空", () => {
      const store = useChatStore()
      const conv = store.addConversation("测试")

      expect(conv.messages).toEqual([])
    })
  })

  // ── 删除对话 ──────────────────────────────────────────────────────────

  describe("deleteConversation", () => {
    it("删除指定对话", () => {
      const store = useChatStore()
      const { c1, c2 } = populateStorage(store)

      store.deleteConversation(c1.id)

      expect(store.conversations).toHaveLength(1)
      expect(store.conversations[0].id).toBe(c2.id)
    })

    it("删除活跃对话后清除 activeConversationId", () => {
      const store = useChatStore()
      const { c1 } = populateStorage(store)

      store.setActiveConversation(c1.id)
      store.deleteConversation(c1.id)

      expect(store.activeConversationId).toBeNull()
    })

    it("删除非活跃对话时不影响活跃状态", () => {
      const store = useChatStore()
      const { c1, c2 } = populateStorage(store)

      store.setActiveConversation(c1.id)
      store.deleteConversation(c2.id)

      expect(store.activeConversationId).toBe(c1.id)
    })

    it("删除不存在的对话 ID 不会出错", () => {
      const store = useChatStore()
      populateStorage(store)

      expect(() => store.deleteConversation("nonexistent")).not.toThrow()
      expect(store.conversations).toHaveLength(2)
    })
  })

  // ── 重命名对话 ────────────────────────────────────────────────────────

  describe("renameConversation", () => {
    it("重命名指定对话标题", () => {
      const store = useChatStore()
      const { c1 } = populateStorage(store)

      store.renameConversation(c1.id, "新标题")

      const renamed = store.conversations.find((c) => c.id === c1.id)
      expect(renamed!.title).toBe("新标题")
    })

    it("重命名时更新 updatedAt", async () => {
      const store = useChatStore()
      const { c1 } = populateStorage(store)
      const originalUpdatedAt = c1.updatedAt

      // 等待一小段时间确保时间戳不同
      await new Promise((resolve) => setTimeout(resolve, 10))
      store.renameConversation(c1.id, "新标题")

      const renamed = store.conversations.find((c) => c.id === c1.id)
      expect(renamed!.updatedAt).not.toBe(originalUpdatedAt)
    })

    it("重命名空标题保持原标题不变", () => {
      const store = useChatStore()
      const { c1 } = populateStorage(store)

      store.renameConversation(c1.id, "")

      const renamed = store.conversations.find((c) => c.id === c1.id)
      expect(renamed!.title).toBe("第一个对话")
    })

    it("重命名不存在的对话 ID 不会出错", () => {
      const store = useChatStore()
      populateStorage(store)

      expect(() => store.renameConversation("nonexistent", "新标题")).not.toThrow()
    })
  })

  // ── 切换活跃对话 ──────────────────────────────────────────────────────

  describe("setActiveConversation", () => {
    it("切换到指定对话", () => {
      const store = useChatStore()
      const { c2 } = populateStorage(store)

      store.setActiveConversation(c2.id)

      expect(store.activeConversationId).toBe(c2.id)
    })

    it("切换对话后原有活跃对话被替换", () => {
      const store = useChatStore()
      const { c1, c2 } = populateStorage(store)

      store.setActiveConversation(c1.id)
      store.setActiveConversation(c2.id)

      expect(store.activeConversationId).toBe(c2.id)
    })

    it("设为 null 清除活跃对话", () => {
      const store = useChatStore()
      const { c1 } = populateStorage(store)

      store.setActiveConversation(c1.id)
      store.setActiveConversation(null)

      expect(store.activeConversationId).toBeNull()
    })

    it("设为不存在的 ID 不会出错", () => {
      const store = useChatStore()
      populateStorage(store)

      expect(() => store.setActiveConversation("nonexistent")).not.toThrow()
      expect(store.activeConversationId).toBe("nonexistent")
    })
  })

  // ── localStorage 持久化 ───────────────────────────────────────────────

  describe("localStorage 持久化", () => {
    it("创建对话后自动持久化到 localStorage", () => {
      const store = useChatStore()
      store.addConversation("持久化测试")

      const saved = localStorage.getItem(STORAGE_KEY)
      expect(saved).toBeTruthy()

      const parsed = JSON.parse(saved!)
      expect(parsed.conversations).toHaveLength(1)
      expect(parsed.conversations[0].title).toBe("持久化测试")
      expect(parsed.activeConversationId).toBe(parsed.conversations[0].id)
    })

    it("bubbles 列表持久化并可从 localStorage 恢复", () => {
      const store = useChatStore()
      const conv = store.addConversation("气泡测试")
      store.addBubble(conv.id, {
        id: "b-1",
        query: "测试查询",
        topK: 5,
        fileNames: [],
        response: null,
        error: null,
      })

      // 模拟重新加载
      JSON.parse(localStorage.getItem(STORAGE_KEY)!)
      setActivePinia(createPinia())
      const store2 = useChatStore()

      expect(store2.conversations[0].bubbles).toHaveLength(1)
      expect(store2.conversations[0].bubbles[0].query).toBe("测试查询")
    })

    it("从 localStorage 读取已有对话数据", () => {
      // 预填充 localStorage
      const preData = {
        conversations: [
          {
            id: "pre-1",
            title: "预先存在的对话",
            messages: [],
            bubbles: [],
            createdAt: "2026-07-01T00:00:00.000Z",
            updatedAt: "2026-07-01T00:00:00.000Z",
          },
        ],
        activeConversationId: "pre-1",
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(preData))

      // 创建新 Pinia 实例模拟页面刷新
      setActivePinia(createPinia())
      const store = useChatStore()

      expect(store.conversations).toHaveLength(1)
      expect(store.conversations[0].title).toBe("预先存在的对话")
      expect(store.activeConversationId).toBe("pre-1")
    })

    it("旧数据迁移：缺少 bubbles 字段自动补全为空数组", () => {
      const preData = {
        conversations: [
          {
            id: "old-1",
            title: "旧版本对话（无 bubbles）",
            messages: [],
            createdAt: "2026-07-01T00:00:00.000Z",
            updatedAt: "2026-07-01T00:00:00.000Z",
          },
        ],
        activeConversationId: "old-1",
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(preData))

      setActivePinia(createPinia())
      const store = useChatStore()

      expect(store.conversations[0].bubbles).toEqual([])
    })

    it("localStorage 为空时初始化为空列表", () => {
      const store = useChatStore()

      expect(store.conversations).toEqual([])
      expect(store.activeConversationId).toBeNull()
    })

    it("删除对话后同步更新 localStorage", () => {
      const store = useChatStore()
      const { c1, c2 } = populateStorage(store)

      store.deleteConversation(c1.id)

      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)!)
      expect(saved.conversations).toHaveLength(1)
      expect(saved.conversations[0].id).toBe(c2.id)
    })

    it("重命名对话后同步更新 localStorage", () => {
      const store = useChatStore()
      const { c1 } = populateStorage(store)

      store.renameConversation(c1.id, "新名称")

      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)!)
      const renamed = saved.conversations.find((c: { id: string }) => c.id === c1.id)
      expect(renamed.title).toBe("新名称")
    })

    it("localStorage 数据异常时初始化为空列表（不崩溃）", () => {
      localStorage.setItem(STORAGE_KEY, "invalid json {{{")

      expect(() => {
        setActivePinia(createPinia())
        useChatStore()
      }).not.toThrow()
    })

    it("localStorage 数据缺少必要字段时初始化为空列表", () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ unknownField: true }))

      setActivePinia(createPinia())
      const store = useChatStore()

      expect(store.conversations).toEqual([])
      expect(store.activeConversationId).toBeNull()
    })

    it("多个对话按时间倒序排列", () => {
      const store = useChatStore()
      const c1 = store.addConversation("最早")
      const c2 = store.addConversation("次之")
      const c3 = store.addConversation("最新")

      expect(store.conversations[0].id).toBe(c3.id)
      expect(store.conversations[1].id).toBe(c2.id)
      expect(store.conversations[2].id).toBe(c1.id)
    })
  })

  // ── 对话自动命名 ────────────────────────────────────────────────────────

  describe("autoTitleFromMessage", () => {
    it("短消息直接作为标题", () => {
      expect(autoTitleFromMessage("你好")).toBe("你好")
    })

    it("移除常见前缀「请帮我」", () => {
      expect(autoTitleFromMessage("请帮我总结一下知识库的内容")).toBe("总结一下知识库的内容")
    })

    it("移除常见前缀「帮我」", () => {
      expect(autoTitleFromMessage("帮我分析这份报告的核心观点")).toBe("分析这份报告的核心观点")
    })

    it("移除常见前缀「如何」", () => {
      expect(autoTitleFromMessage("如何在Hadoop上配置HDFS高可用")).toBe("在Hadoop上配置HDFS高可用")
    })

    it("移除常见前缀「怎么」", () => {
      expect(autoTitleFromMessage("怎么解决Python依赖冲突问题")).toBe("解决Python依赖冲突问题")
    })

    it("移除常见前缀「我想知道」", () => {
      expect(autoTitleFromMessage("我想知道微服务架构的最佳实践")).toBe("微服务架构的最佳实践")
    })

    it("长消息截断并追加省略号", () => {
      const long = "这是一个非常长的消息内容用于测试标题自动截断功能需要更多字符来验证"
      const result = autoTitleFromMessage(long)
      // AUTO_TITLE_MAX_LENGTH = 18, result max = 18 + "…"
      expect(result.length).toBeLessThanOrEqual(19)
      expect(result.endsWith("…")).toBe(true)
    })

    it("多行空白消息折叠为单行", () => {
      expect(autoTitleFromMessage("  你好  世界  ")).toBe("你好 世界")
    })

    it("换行符替换为空格", () => {
      expect(autoTitleFromMessage("第一行\n第二行\n第三行")).toBe("第一行 第二行 第三行")
    })

    it("全为前缀时返回空字符串", () => {
      // 仅由前缀组成，移除后为空
      expect(autoTitleFromMessage("请帮我")).toBe("")
    })

    it("末尾标点被移除", () => {
      expect(autoTitleFromMessage("Hadoop安装步骤？")).toBe("Hadoop安装步骤")
      expect(autoTitleFromMessage("Python代码报错分析。")).toBe("Python代码报错分析")
    })
  })

  describe("autoTitleConversation", () => {
    it("首条消息自动提炼标题（初始空标题）", () => {
      const store = useChatStore()
      const conv = store.addConversation() // 默认标题 ""

      store.autoTitleConversation(conv.id, "帮我总结一下知识库的内容")

      const updated = store.conversations.find((c) => c.id === conv.id)
      // "帮我" 前缀被移除
      expect(updated!.title).toBe("总结一下知识库的内容")
    })

    it("标题为空且内容无法提炼时回退到时间戳命名", () => {
      const store = useChatStore()
      const conv = store.addConversation()

      // 仅前缀的消息，提炼结果为空
      store.autoTitleConversation(conv.id, "请问")

      const updated = store.conversations.find((c) => c.id === conv.id)
      // 应回退到时间戳格式（如 "7月29日 14:30"）
      expect(updated!.title).not.toBe("")
      expect(updated!.title).not.toBe("新对话")
      // 验证包含月和日
      expect(updated!.title).toMatch(/\d+月\d+日/)
    })

    it("标题已修改后不再自动覆盖", () => {
      const store = useChatStore()
      const conv = store.addConversation()
      store.renameConversation(conv.id, "用户自定义标题")

      store.autoTitleConversation(conv.id, "新的消息内容")

      const updated = store.conversations.find((c) => c.id === conv.id)
      expect(updated!.title).toBe("用户自定义标题")
    })

    it("非空标题时 autoTitle 不生效", () => {
      const store = useChatStore()
      const conv = store.addConversation("已命名对话")

      store.autoTitleConversation(conv.id, "新消息")

      const updated = store.conversations.find((c) => c.id === conv.id)
      expect(updated!.title).toBe("已命名对话")
    })

    it("旧版「新对话」默认标题也会被自动提炼覆盖", () => {
      const store = useChatStore()
      const conv = store.addConversation("新对话")

      store.autoTitleConversation(conv.id, "帮我分析数据")

      const updated = store.conversations.find((c) => c.id === conv.id)
      // "帮我" 前缀被移除
      expect(updated!.title).toBe("分析数据")
    })
  })

  // ── 派生状态（getters）─────────────────────────────────────────────────

  describe("getters", () => {
    it("activeConversation 返回当前活跃对话对象", () => {
      const store = useChatStore()
      const conv = store.addConversation("活跃对话")

      expect(store.activeConversation).not.toBeNull()
      expect(store.activeConversation!.id).toBe(conv.id)
      expect(store.activeConversation!.title).toBe("活跃对话")
    })

    it("无活跃对话时 activeConversation 返回 null", () => {
      const store = useChatStore()
      store.addConversation("某对话")
      store.setActiveConversation(null)

      expect(store.activeConversation).toBeNull()
    })

    it("historyConversations 排除活跃对话", () => {
      const store = useChatStore()
      const c1 = store.addConversation("活跃")
      store.addConversation("历史1")
      store.addConversation("历史2")
      store.setActiveConversation(c1.id)

      expect(store.historyConversations).toHaveLength(2)
      expect(store.historyConversations.every((c) => c.id !== c1.id)).toBe(true)
    })

    it("无活跃对话时所有对话都在 historyConversations 中", () => {
      const store = useChatStore()
      store.addConversation("对话A")
      store.addConversation("对话B")
      store.setActiveConversation(null)

      expect(store.historyConversations).toHaveLength(2)
    })
  })

  // ── 气泡 CRUD ──────────────────────────────────────────────────────────

  describe("addBubble", () => {
    it("向对话追加一个气泡", () => {
      const store = useChatStore()
      const conv = store.addConversation("气泡测试")

      store.addBubble(conv.id, {
        id: "b-1",
        query: "测试查询",
        topK: 5,
        fileNames: [],
        response: null,
        error: null,
      })

      expect(store.conversations[0].bubbles).toHaveLength(1)
      expect(store.conversations[0].bubbles[0].query).toBe("测试查询")
    })

    it("向同一个对话追加多个气泡", () => {
      const store = useChatStore()
      const conv = store.addConversation("多气泡测试")

      store.addBubble(conv.id, { id: "b-1", query: "第一个问题", topK: 5, fileNames: [], response: null, error: null })
      store.addBubble(conv.id, { id: "b-2", query: "第二个问题", topK: 5, fileNames: [], response: null, error: null })

      expect(store.conversations[0].bubbles).toHaveLength(2)
      expect(store.conversations[0].bubbles[1].query).toBe("第二个问题")
    })

    it("添加气泡后更新 updatedAt", async () => {
      const store = useChatStore()
      const conv = store.addConversation("时间戳测试")
      const originalUpdatedAt = conv.updatedAt

      await new Promise((resolve) => setTimeout(resolve, 10))
      store.addBubble(conv.id, { id: "b-1", query: "测试", topK: 5, fileNames: [], response: null, error: null })

      expect(store.conversations[0].updatedAt).not.toBe(originalUpdatedAt)
    })

    it("向不存在的对话添加气泡不抛出异常", () => {
      const store = useChatStore()

      expect(() =>
        store.addBubble("nonexistent", { id: "b-1", query: "测试", topK: 5, fileNames: [], response: null, error: null }),
      ).not.toThrow()
    })
  })

  describe("updateBubble", () => {
    it("更新气泡的 response 字段", () => {
      const store = useChatStore()
      const conv = store.addConversation("更新测试")
      store.addBubble(conv.id, { id: "b-1", query: "查询", topK: 5, fileNames: [], response: null, error: null })

      const mockResponse = { answer: "AI 回答", chat_model: "test-model" }
      store.updateBubble(conv.id, "b-1", { response: mockResponse as unknown as import("../api/search").SearchResponse })

      expect(store.conversations[0].bubbles[0].response).not.toBeNull()
    })

    it("更新气泡的 error 字段", () => {
      const store = useChatStore()
      const conv = store.addConversation("错误更新测试")
      store.addBubble(conv.id, { id: "b-1", query: "查询", topK: 5, fileNames: [], response: null, error: null })

      store.updateBubble(conv.id, "b-1", { error: "网络错误" })

      expect(store.conversations[0].bubbles[0].error).toBe("网络错误")
    })

    it("更新不存在的对话或气泡不抛出异常", () => {
      const store = useChatStore()

      expect(() => store.updateBubble("nonexistent", "b-1", { error: "测试" })).not.toThrow()
    })
  })

  describe("clearBubbles", () => {
    it("清空对话的所有气泡", () => {
      const store = useChatStore()
      const conv = store.addConversation("清空测试")
      store.addBubble(conv.id, { id: "b-1", query: "查询1", topK: 5, fileNames: [], response: null, error: null })
      store.addBubble(conv.id, { id: "b-2", query: "查询2", topK: 5, fileNames: [], response: null, error: null })

      store.clearBubbles(conv.id)

      expect(store.conversations[0].bubbles).toEqual([])
    })

    it("清空不存在的对话不抛出异常", () => {
      const store = useChatStore()

      expect(() => store.clearBubbles("nonexistent")).not.toThrow()
    })
  })
})
