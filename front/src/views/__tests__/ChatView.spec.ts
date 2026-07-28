import { mount, flushPromises } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { nextTick } from "vue"

// ── Mock setup ──────────────────────────────────────────────────────────

const {
  mockSearchChunks,
  mockLoggerDebug,
  mockLoggerInfo,
  mockLoggerWarn,
  mockLoggerError,
} = vi.hoisted(() => ({
  mockSearchChunks: vi.fn(),
  mockLoggerDebug: vi.fn(),
  mockLoggerInfo: vi.fn(),
  mockLoggerWarn: vi.fn(),
  mockLoggerError: vi.fn(),
}))

vi.mock("../../api/search", () => ({
  searchChunks: (...args: unknown[]) => mockSearchChunks(...args),
}))

vi.mock("../../shared/logger", () => ({
  createLogger: vi.fn(() => ({
    debug: mockLoggerDebug,
    info: mockLoggerInfo,
    warn: mockLoggerWarn,
    error: mockLoggerError,
  })),
  getRingBuffer: vi.fn(() => ({ getAll: () => [] })),
}))

// Mock marked for AnswerPanel rendered markdown (avoids import issues)
vi.mock("marked", () => ({
  marked: {
    parse: vi.fn((text: string) => `<p>${text}</p>`),
  },
}))

// Lazy import after mocks are established
const { default: ChatView } = await import("../ChatView.vue")

// ── Test data factories ─────────────────────────────────────────────────

function buildSearchResponse(overrides?: {
  answer?: string
  results?: Record<string, unknown>[]
  answerTokens?: Record<string, unknown> | null
  chatModel?: string | null
  promptMessages?: Record<string, unknown>[]
  generationError?: string | null
  searchedDocumentCount?: number
  totalSearched?: number
  searchTimeMs?: number
}): Record<string, unknown> {
  const results = overrides?.results ?? [
    {
      rank: 1,
      score: 0.12,
      chunk_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      parsed_document_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
      document_name: "医疗AI综述.pdf",
      sequence_index: 3,
      text: "大模型在医疗领域有广泛的应用，包括辅助诊断、药物研发、医学影像分析等方面。",
      contextualized_text: "",
      token_count: 150,
      heading_path: ["第三章", "3.1 大模型应用"],
      page_numbers: [12, 13],
    },
    {
      rank: 2,
      score: 0.25,
      chunk_id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
      parsed_document_id: "dddddddd-dddd-dddd-dddd-dddddddddddd",
      document_name: "AI医疗案例研究.pdf",
      sequence_index: 7,
      text: "在实际临床应用中，大模型辅助诊断系统已经展现出显著的效能提升...",
      contextualized_text: "",
      token_count: 120,
      heading_path: ["案例研究"],
      page_numbers: [45],
    },
  ]

  return {
    query: "大模型在医疗领域的应用有哪些？",
    query_embedding_preview: [0.0123, -0.0456, 0.0789, 0.0012, -0.0345],
    embedding_model: "Qwen/Qwen3-Embedding-4B",
    embedding_dimensions: 2560,
    top_k: 5,
    total_searched: overrides?.totalSearched ?? 100,
    searched_document_count: overrides?.searchedDocumentCount ?? 2,
    search_time_ms: overrides?.searchTimeMs ?? 45.2,
    results,
    answer:
      overrides?.answer ??
      "根据提供的文档内容，大模型在医疗领域的应用主要包括辅助诊断、药物研发等方面。",
    answer_tokens: overrides?.answerTokens ?? {
      prompt_tokens: 500,
      completion_tokens: 200,
      total_tokens: 700,
    },
    chat_model: overrides?.chatModel ?? "qwen3.5-plus",
    prompt_messages: overrides?.promptMessages ?? [
      {
        role: "system",
        content: "你是一个知识库助手。请仅根据提供的上下文回答问题。",
      },
      {
        role: "user",
        content: "## 上下文\n\n## 问题\n\n大模型在医疗领域的应用有哪些？",
      },
    ],
    chat_config_snapshot: null,
    generation_error: overrides?.generationError ?? null,
  }
}

async function sendQuery(wrapper: ReturnType<typeof mount>, queryText: string) {
  const textarea = wrapper.find('[data-testid="chat-input"]')
  await textarea.setValue(queryText)
  const button = wrapper.find('[data-testid="send-button"]')
  await button.trigger("click")
}

// ── Tests ───────────────────────────────────────────────────────────────

describe("ChatView", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  // ── 空状态 ─────────────────────────────────────────────────────────

  describe("empty state", () => {
    it("renders empty state when no conversations have been started", () => {
      const wrapper = mount(ChatView)

      const emptyState = wrapper.find('[data-testid="chat-empty-state"]')
      expect(emptyState.exists()).toBe(true)
      expect(emptyState.text()).toContain("开始对话")
      expect(emptyState.text()).toContain("无需选文档")
    })

    it("renders ChatInput component even in empty state", () => {
      const wrapper = mount(ChatView)

      expect(wrapper.find('[data-testid="chat-input"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="send-button"]').exists()).toBe(true)
    })
  })

  // ── 发送查询显示回答和结果 ────────────────────────────────────────

  describe("sending a query", () => {
    it("sends query and displays answer panel with AI response", async () => {
      mockSearchChunks.mockResolvedValue(buildSearchResponse())

      const wrapper = mount(ChatView)
      await sendQuery(wrapper, "大模型在医疗领域的应用有哪些？")
      await flushPromises()

      // Empty state should be hidden
      expect(wrapper.find('[data-testid="chat-empty-state"]').exists()).toBe(false)

      // User question bubble should appear
      expect(wrapper.text()).toContain("大模型在医疗领域的应用有哪些？")

      // Answer panel should be rendered via AnswerPanel component
      const answerContent = wrapper.find('[data-testid="answer-content"]')
      expect(answerContent.exists()).toBe(true)

      // Citation stats should be visible
      const citationStats = wrapper.find('[data-testid="citation-stats"]')
      expect(citationStats.exists()).toBe(true)
      expect(citationStats.text()).toContain("2 个文档")

      // Token stats should be visible
      const tokenStats = wrapper.find('[data-testid="token-stats"]')
      expect(tokenStats.exists()).toBe(true)
      expect(tokenStats.text()).toContain("700")
    })

    it("calls searchChunks with correct parameters", async () => {
      mockSearchChunks.mockResolvedValue(buildSearchResponse())

      const wrapper = mount(ChatView)
      await sendQuery(wrapper, "测试查询")
      await flushPromises()

      expect(mockSearchChunks).toHaveBeenCalledWith({
        query: "测试查询",
        top_k: 5,
      })
    })

    it("calls searchChunks with custom top_k value", async () => {
      mockSearchChunks.mockResolvedValue(buildSearchResponse())

      const wrapper = mount(ChatView)
      // Set the top-k slider
      const slider = wrapper.find('#topk-slider')
      await slider.setValue(10)
      await sendQuery(wrapper, "测试查询")
      await flushPromises()

      expect(mockSearchChunks).toHaveBeenCalledWith({
        query: "测试查询",
        top_k: 10,
      })
    })

    it("displays the user's question bubble after sending", async () => {
      mockSearchChunks.mockResolvedValue(buildSearchResponse())

      const wrapper = mount(ChatView)
      await sendQuery(wrapper, "这是一个测试问题")
      await flushPromises()

      expect(wrapper.text()).toContain("这是一个测试问题")
    })

    it("clears input after sending", async () => {
      mockSearchChunks.mockResolvedValue(buildSearchResponse())

      const wrapper = mount(ChatView)
      await sendQuery(wrapper, "测试查询")
      await flushPromises()

      const textarea = wrapper.find<HTMLTextAreaElement>('[data-testid="chat-input"]')
      expect(textarea.element.value).toBe("")
    })

    it("shows ResultsPanel with result items after successful response", async () => {
      mockSearchChunks.mockResolvedValue(buildSearchResponse())

      const wrapper = mount(ChatView)
      await sendQuery(wrapper, "测试查询")
      await flushPromises()

      // ResultsPanel toggle should exist
      const resultsToggle = wrapper.find('[data-testid="results-toggle"]')
      expect(resultsToggle.exists()).toBe(true)

      // Expand the panel
      await resultsToggle.trigger("click")
      await nextTick()

      // Result items should be rendered
      const resultItems = wrapper.findAll('[data-testid="result-item"]')
      expect(resultItems).toHaveLength(2)
    })

    it("shows PromptPreview after successful response", async () => {
      mockSearchChunks.mockResolvedValue(buildSearchResponse())

      const wrapper = mount(ChatView)
      await sendQuery(wrapper, "测试查询")
      await flushPromises()

      const promptToggle = wrapper.find('[data-testid="prompt-toggle"]')
      expect(promptToggle.exists()).toBe(true)
    })

    it("disables send button when input is empty", async () => {
      const wrapper = mount(ChatView)

      const button = wrapper.find('[data-testid="send-button"]')
      expect(button.attributes("disabled")).toBeDefined()
    })

    it("disables send button while loading", async () => {
      // Never resolve to keep in loading state
      let resolveLater!: (value: unknown) => void
      mockSearchChunks.mockReturnValue(
        new Promise((resolve) => { resolveLater = resolve }),
      )

      const wrapper = mount(ChatView)
      await sendQuery(wrapper, "测试查询")
      await nextTick()

      const button = wrapper.find('[data-testid="send-button"]')
      expect(button.attributes("disabled")).toBeDefined()

      // Cleanup
      resolveLater(buildSearchResponse())
      await flushPromises()
    })

    it("accepts Enter to send", async () => {
      mockSearchChunks.mockResolvedValue(buildSearchResponse())

      const wrapper = mount(ChatView)
      const textarea = wrapper.find('[data-testid="chat-input"]')
      await textarea.setValue("快捷键发送测试")

      await textarea.trigger("keydown", {
        key: "Enter",
        ctrlKey: false,
      })
      await flushPromises()

      expect(mockSearchChunks).toHaveBeenCalledWith({
        query: "快捷键发送测试",
        top_k: 5,
      })
    })

    it("does not send on Ctrl+Enter (inserts newline)", async () => {
      mockSearchChunks.mockResolvedValue(buildSearchResponse())

      const wrapper = mount(ChatView)
      const textarea = wrapper.find('[data-testid="chat-input"]')
      await textarea.setValue("普通换行测试")

      await textarea.trigger("keydown", {
        key: "Enter",
        ctrlKey: true,
      })

      // Ctrl+Enter should not trigger send — inserts newline instead
      expect(mockSearchChunks).not.toHaveBeenCalled()
    })

    it("does not send on Ctrl+Enter when input is empty", async () => {
      mockSearchChunks.mockResolvedValue(buildSearchResponse())

      const wrapper = mount(ChatView)

      const textarea = wrapper.find('[data-testid="chat-input"]')
      await textarea.trigger("keydown", {
        key: "Enter",
        ctrlKey: true,
      })

      expect(mockSearchChunks).not.toHaveBeenCalled()
    })

    it("accumulates multiple conversations in history", async () => {
      mockSearchChunks.mockResolvedValue(buildSearchResponse())

      const wrapper = mount(ChatView)

      await sendQuery(wrapper, "第一个问题")
      await flushPromises()

      await sendQuery(wrapper, "第二个问题")
      await flushPromises()

      // Both questions should be visible
      expect(wrapper.text()).toContain("第一个问题")
      expect(wrapper.text()).toContain("第二个问题")
    })
  })

  // ── 空结果 ─────────────────────────────────────────────────────────

  describe("empty results", () => {
    it("does not show ResultsPanel when there are zero results", async () => {
      mockSearchChunks.mockResolvedValue(
        buildSearchResponse({ results: [] }),
      )

      const wrapper = mount(ChatView)
      await sendQuery(wrapper, "无结果查询")
      await flushPromises()

      // ResultsPanel should not be rendered when results is empty
      expect(wrapper.find('[data-testid="results-toggle"]').exists()).toBe(false)
    })

    it("still shows AnswerPanel even with empty results", async () => {
      mockSearchChunks.mockResolvedValue(
        buildSearchResponse({ results: [] }),
      )

      const wrapper = mount(ChatView)
      await sendQuery(wrapper, "无结果查询")
      await flushPromises()

      // Answer panel should still render
      const answerContent = wrapper.find('[data-testid="answer-content"]')
      expect(answerContent.exists()).toBe(true)
    })

    it("shows 0 results in citation stats", async () => {
      mockSearchChunks.mockResolvedValue(
        buildSearchResponse({ results: [] }),
      )

      const wrapper = mount(ChatView)
      await sendQuery(wrapper, "无结果查询")
      await flushPromises()

      const citationStats = wrapper.find('[data-testid="citation-stats"]')
      expect(citationStats.exists()).toBe(true)
      expect(citationStats.text()).toContain("引用 0 个分块")
    })
  })

  // ── API 错误处理 ──────────────────────────────────────────────────

  describe("api error handling", () => {
    it("shows error message when search fails", async () => {
      mockSearchChunks.mockRejectedValue(
        Object.assign(
          new Error("知识库中暂无任何已向量化的文档"),
          { status: 404, detail: "知识库中暂无任何已向量化的文档" },
        ),
      )

      const wrapper = mount(ChatView)
      await sendQuery(wrapper, "测试查询")
      await flushPromises()

      const errorBox = wrapper.find('[data-testid="chat-error"]')
      expect(errorBox.exists()).toBe(true)
      expect(errorBox.text()).toContain("请求失败")
      expect(errorBox.text()).toContain("知识库中暂无任何已向量化的文档")
    })

    it("does not show AnswerPanel on error", async () => {
      mockSearchChunks.mockRejectedValue(new Error("网络请求失败"))

      const wrapper = mount(ChatView)
      await sendQuery(wrapper, "测试查询")
      await flushPromises()

      expect(wrapper.find('[data-testid="answer-content"]').exists()).toBe(false)
    })

    it("shows generic error message for non-Error instances", async () => {
      mockSearchChunks.mockRejectedValue("Unknown rejection")

      const wrapper = mount(ChatView)
      await sendQuery(wrapper, "测试查询")
      await flushPromises()

      const errorBox = wrapper.find('[data-testid="chat-error"]')
      expect(errorBox.exists()).toBe(true)
      expect(errorBox.text()).toContain("未知错误")
    })

    it("shows network error message", async () => {
      mockSearchChunks.mockRejectedValue(
        Object.assign(new Error("Failed to fetch"), {
          status: 0,
          detail: "Failed to fetch",
        }),
      )

      const wrapper = mount(ChatView)
      await sendQuery(wrapper, "测试查询")
      await flushPromises()

      const errorBox = wrapper.find('[data-testid="chat-error"]')
      expect(errorBox.exists()).toBe(true)
      expect(errorBox.text()).toContain("Failed to fetch")
    })
  })
})
