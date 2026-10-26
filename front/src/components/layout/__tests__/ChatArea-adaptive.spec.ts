/** 自适应回答 RED：真实 ChatArea、AnswerPanel、来源组件和 Pinia，仅替换网络。 */
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import type { SearchResponse } from "../../../api/search"
import { makeResponse, makeResult } from "../../../__tests__/fixtures/search"
import { makeUser } from "../../../__tests__/fixtures/users"
import { useUserStore } from "../../../stores/user"

vi.mock("../../../shared/logger", () => ({
  createLogger: () => ({ debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))

const mockSearch = vi.fn()
vi.mock("../../../api/search", () => ({
  searchChunks: (...args: unknown[]) => mockSearch(...args),
}))
vi.mock("../../../api/uploads", () => ({ uploadFile: vi.fn() }))

type AdaptiveResponse = SearchResponse & {
  answer_mode: "general" | "rag" | "summary" | "clarification"
  retrieval_status: "skipped" | "matched" | "no_match" | "empty" | "unavailable"
  summary_coverage: {
    document_count: number
    included_document_count: number
    total_chunks: number
    included_chunks: number
    truncated: boolean
  } | null
}

function generalResponse(overrides: Partial<AdaptiveResponse> = {}): AdaptiveResponse {
  return {
    ...makeResponse({
      query: "Python 装饰器怎么使用？",
      results: [],
      total_searched: 0,
      searched_document_count: 0,
      answer: "装饰器可以包装函数并扩展其行为。",
      query_embedding_preview: [],
    }),
    answer_mode: "general",
    retrieval_status: "no_match",
    summary_coverage: null,
    ...overrides,
  }
}

let wrapper: VueWrapper | null = null

async function showAnswer(response: SearchResponse) {
  mockSearch.mockResolvedValueOnce(response)
  const { default: ChatArea } = await import("../ChatArea.vue")
  wrapper = mount(ChatArea, { attachTo: document.body })
  await flushPromises()
  const input = wrapper.find('[data-testid="chat-input"]')
  await input.setValue(response.query)
  await input.trigger("keydown", { key: "Enter" })
  await flushPromises()
  return wrapper
}

describe("自适应 RAG 主对话", () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    const user = useUserStore()
    user.currentUser = makeUser("member")
    user.status = "authenticated"
    mockSearch.mockReset()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ""
  })

  // 验证普通回答展示真实正文和轻量归属，用户不会误认为已引用自己的资料。
  it("通用回答显示模型正文并标注基于通用知识", async () => {
    const area = await showAnswer(generalResponse())

    expect(area.find('[data-testid="answer-content"]').text()).toContain("装饰器可以包装函数")
    expect(area.text()).toContain("基于通用知识")
  })

  // 验证 general 模式不再出现截图中的零引用统计和红色无依据来源框。
  it("通用回答省略零引用统计和空来源告警", async () => {
    const area = await showAnswer(generalResponse())

    expect(area.find('[data-testid="citation-stats"]').exists()).toBe(false)
    expect(area.find('[data-testid="source-list"]').exists()).toBe(false)
    expect(area.text()).not.toContain("本回答缺少资料依据")
  })

  // 验证没有用于回答的资料时不展示空的检索详情栏。
  it("通用回答省略零片段检索详情", async () => {
    const area = await showAnswer(generalResponse())

    expect(area.find('[data-testid="retrieval-details"]').exists()).toBe(false)
  })

  // 回归守护：去掉空来源展示的同时仍应保留复制和真实模型用量。
  it("通用回答保留复制及真实 token 用量", async () => {
    const area = await showAnswer(generalResponse())

    expect(area.find('[data-testid="copy-answer-button"]').exists()).toBe(true)
    expect(area.find('[data-testid="token-total"]').text()).toContain("700")
  })

  // 验证检索服务故障不被 UI 表述为用户没有资料或资料没有相关内容。
  it("检索故障降级显示检索暂不可用的独立说明", async () => {
    const area = await showAnswer(generalResponse({ retrieval_status: "unavailable" }))

    expect(area.text()).toContain("检索暂不可用")
    expect(area.find('[data-testid="source-list"]').exists()).toBe(false)
    expect(area.text()).not.toContain("没有检索到相关资料")
  })

  // 验证资料不足的引导直接可读，不用零引用告警覆盖或稀释下一步操作。
  it("澄清只显示资料引导并省略零引用和虚假用量", async () => {
    const area = await showAnswer(generalResponse({
      answer_mode: "clarification",
      retrieval_status: "empty",
      answer: "请上传资料，或选择已处理完成的文档后再总结。",
      answer_tokens: null,
      chat_model: null,
    }))

    expect(area.text()).toContain("请上传资料")
    expect(area.find('[data-testid="citation-stats"]').exists()).toBe(false)
    expect(area.find('[data-testid="source-list"]').exists()).toBe(false)
    expect(area.find('[data-testid="token-stats"]').exists()).toBe(false)
    expect(area.text()).not.toContain("基于通用知识")
  })

  // 验证部分覆盖的总结明确告知用户局限，同时保留可核对的真实来源。
  it("部分总结显示覆盖说明并允许展开资料来源", async () => {
    const area = await showAnswer(generalResponse({
      answer_mode: "summary",
      retrieval_status: "matched",
      answer: "资料的核心观点包括特征值与矩阵关系。",
      results: [makeResult()],
      summary_coverage: {
        document_count: 3,
        included_document_count: 1,
        total_chunks: 100,
        included_chunks: 8,
        truncated: true,
      },
    }))

    expect(area.text()).toContain("基于部分资料总结")
    expect(area.text()).toContain("1 / 3")
    await area.find('[data-testid="source-toggle"]').trigger("click")
    expect(area.find('[data-testid="source-chunk-text"]').text()).toContain("特征值")
    expect(area.text()).not.toContain("检索排名")
  })

  // 验证总结来源不会被误包装成带虚假相似度分数的语义检索结果。
  it("文档总结展示来源但不显示语义检索详情", async () => {
    const area = await showAnswer(generalResponse({
      answer_mode: "summary",
      retrieval_status: "matched",
      results: [makeResult()],
      summary_coverage: {
        document_count: 1,
        included_document_count: 1,
        total_chunks: 1,
        included_chunks: 1,
        truncated: false,
      },
    }))

    expect(area.find('[data-testid="source-list"]').exists()).toBe(true)
    expect(area.find('[data-testid="retrieval-details"]').exists()).toBe(false)
    expect(area.text()).not.toContain("基于部分资料总结")
  })

  // 验证生成失败仍显示错误状态，不能把非空降级提示伪装成成功的通用回答。
  it("通用生成失败显示生成错误而不标记成功归属", async () => {
    const area = await showAnswer(generalResponse({
      generation_error: "模型服务超时",
      answer: "AI 回答生成失败，请稍后重试。",
      answer_tokens: null,
      chat_model: null,
    }))

    expect(area.find('[data-testid="answer-degraded"]').exists()).toBe(true)
    expect(area.text()).not.toContain("基于通用知识")
  })

  // 回归守护：有资料增强时来源和默认折叠的诊断区仍可访问。
  it("资料增强回答保留来源和默认折叠的检索详情", async () => {
    const area = await showAnswer(generalResponse({
      answer_mode: "rag",
      retrieval_status: "matched",
      results: [makeResult()],
    }))

    expect(area.find('[data-testid="source-doc-name"]').text()).toBe("线性代数讲义.pdf")
    expect(area.find('[data-testid="retrieval-details-toggle"]').attributes("aria-expanded")).toBe("false")
    expect(area.text()).not.toContain("基于通用知识")
  })

  // 回归守护：缺少新增字段的旧浏览器记录仍使用原有来源展示，不能被误判为 general。
  it("旧格式回答保持来源展示兼容", async () => {
    const area = await showAnswer(makeResponse())

    expect(area.find('[data-testid="source-list"]').exists()).toBe(true)
    expect(area.find('[data-testid="citation-stats"]').text()).toContain("引用 1 个分块")
    expect(area.text()).not.toContain("基于通用知识")
  })
})
