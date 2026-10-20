/**
 * ChatArea 集成（重构 RED + 回归守护）
 *
 * 使用真实 Pinia chat store 与真实子组件，只 mock 网络 API（search / uploads）与 logger。
 * 标注「回归守护」的用例描述已有且必须保留的行为，它们在 RED 阶段即通过，
 * 用于在重构中防止丢失功能；其余用例针对新交互，RED 阶段必须失败。
 */
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import type { SearchResponse } from "../../../api/search"
import { makeResponse, makeResult } from "../../../__tests__/fixtures/search"
import { useChatStore } from "../../../stores/chat"

vi.mock("../../../shared/logger", () => ({
  createLogger: () => ({ debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))

const mockSearchChunks = vi.fn()
const mockUploadFile = vi.fn()

vi.mock("../../../api/search", () => ({
  searchChunks: (...args: unknown[]) => mockSearchChunks(...args),
}))

vi.mock("../../../api/uploads", () => ({
  uploadFile: (...args: unknown[]) => mockUploadFile(...args),
}))

let wrapper: VueWrapper | null = null

async function mountArea() {
  const { default: ChatArea } = await import("../ChatArea.vue")
  wrapper = mount(ChatArea, { attachTo: document.body })
  await flushPromises()
  return wrapper
}

async function ask(w: VueWrapper, text: string) {
  const textarea = w.find('[data-testid="chat-input"]')
  await textarea.setValue(text)
  await textarea.trigger("keydown", { key: "Enter" })
}

/** 返回一个可在测试中手动 resolve 的 searchChunks 结果。 */
function deferredSearch() {
  let resolve!: (r: SearchResponse) => void
  mockSearchChunks.mockReturnValueOnce(new Promise<SearchResponse>((r) => (resolve = r)))
  return (r: SearchResponse) => resolve(r)
}

describe("ChatArea 欢迎页交互", () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    mockSearchChunks.mockReset()
    mockUploadFile.mockReset()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ""
  })

  // 验证点击推荐问题只把文本填入输入框并聚焦，不发起检索请求
  it("点击推荐问题填入输入框并聚焦，不发送", async () => {
    const w = await mountArea()

    const suggestion = w.find('[data-testid="welcome-suggestion"]')
    expect(suggestion.exists(), "欢迎页应渲染推荐问题").toBe(true)
    const expected = suggestion.text()
    await suggestion.trigger("click")
    await flushPromises()

    const textarea = w.find<HTMLTextAreaElement>('[data-testid="chat-input"]')
    expect(textarea.element.value).toBe(expected)
    expect(document.activeElement).toBe(textarea.element)
    expect(mockSearchChunks).not.toHaveBeenCalled()
    expect(w.find('[data-testid="welcome-view"]').exists()).toBe(true)
  })

  // 验证欢迎页「上传资料」复用同一个隐藏 file input，打开系统文件选择器
  it("点击欢迎页上传按钮打开文件选择器", async () => {
    const w = await mountArea()

    const input = w.find<HTMLInputElement>('input[type="file"]').element
    const clickSpy = vi.spyOn(input, "click")
    const upload = w.find('[data-testid="welcome-upload"]')
    expect(upload.exists(), "欢迎页应渲染上传资料按钮").toBe(true)
    await upload.trigger("click")

    expect(clickSpy).toHaveBeenCalledTimes(1)
    expect(mockSearchChunks).not.toHaveBeenCalled()
  })

  // 回归守护：选择文件后调用上传接口，并在输入框 chip 上显示上传成功
  it("（回归守护）选择文件后上传并显示成功状态", async () => {
    mockUploadFile.mockResolvedValue({ id: "up-1" })
    const w = await mountArea()

    const input = w.find<HTMLInputElement>('input[type="file"]')
    const file = new File(["hello"], "讲义.pdf", { type: "application/pdf" })
    Object.defineProperty(input.element, "files", { value: [file], configurable: true })
    await input.trigger("change")
    await flushPromises()

    expect(mockUploadFile).toHaveBeenCalledWith(file, false)
    expect(w.find('[data-testid="file-chip-success"]').exists()).toBe(true)
  })

  // 回归守护：上传失败时 chip 显示错误信息
  it("（回归守护）上传失败时显示错误信息", async () => {
    mockUploadFile.mockRejectedValue(new Error("文件过大，超过 50MB 限制"))
    const w = await mountArea()

    const input = w.find<HTMLInputElement>('input[type="file"]')
    const file = new File(["x"], "巨大.pdf", { type: "application/pdf" })
    Object.defineProperty(input.element, "files", { value: [file], configurable: true })
    await input.trigger("change")
    await flushPromises()

    expect(w.find('[data-testid="file-chip-error"]').exists()).toBe(true)
    expect(w.text()).toContain("文件过大，超过 50MB 限制")
  })
})

describe("ChatArea 问答流", () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    mockSearchChunks.mockReset()
    mockUploadFile.mockReset()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ""
  })

  // 验证等待期间在回答位置显示「正在检索资料…」并通过 aria-live 播报，发送按钮禁用
  it("检索阶段在回答占位区显示阶段文案并禁用发送", async () => {
    const resolve = deferredSearch()
    const w = await mountArea()

    await ask(w, "什么是特征值")
    await flushPromises()

    const pending = w.find('[data-testid="answer-pending"]')
    expect(pending.exists(), "等待回答时应渲染 answer-pending 占位").toBe(true)
    expect(pending.text()).toContain("正在检索资料…")
    expect(pending.attributes("role")).toBe("status")
    expect(pending.attributes("aria-live")).toBe("polite")
    expect(w.find('[data-testid="send-button"]').attributes("disabled")).toBeDefined()

    resolve(makeResponse())
    await flushPromises()
    expect(w.find('[data-testid="answer-pending"]').exists()).toBe(false)
  })

  // 验证生成阶段（持久化的 stage=generating）显示「正在生成回答…」，切换回该对话也能恢复
  it("生成阶段显示「正在生成回答…」", async () => {
    const store = useChatStore()
    const conv = store.addConversation("等待中的对话")
    store.addBubble(conv.id, {
      id: "b1",
      query: "什么是特征值",
      topK: 5,
      fileNames: [],
      response: null,
      error: null,
      stage: "generating",
    })
    const w = await mountArea()

    expect(w.find('[data-testid="answer-pending"]').text()).toContain("正在生成回答…")
  })

  // 验证回答后来源列表直接可见，并紧跟在回答之后、检索详情之前
  it("回答下方直接显示来源列表，顺序为 回答 → 来源 → 检索详情", async () => {
    mockSearchChunks.mockResolvedValue(makeResponse())
    const w = await mountArea()

    await ask(w, "什么是特征值")
    await flushPromises()

    expect(w.find('[data-testid="source-list"]').exists()).toBe(true)
    expect(w.find('[data-testid="source-doc-name"]').text()).toBe("线性代数讲义.pdf")
    const html = w.html()
    const answerAt = html.indexOf('data-testid="answer-content"')
    const sourcesAt = html.indexOf('data-testid="source-list"')
    const detailsAt = html.indexOf('data-testid="retrieval-details-toggle"')
    expect(answerAt).toBeGreaterThan(-1)
    expect(sourcesAt).toBeGreaterThan(answerAt)
    expect(detailsAt).toBeGreaterThan(sourcesAt)
  })

  // 验证技术诊断默认收纳：检索详情折叠，检索结果/提示词面板不直接出现在对话流
  it("检索详情默认折叠，诊断面板不直接展示", async () => {
    mockSearchChunks.mockResolvedValue(makeResponse())
    const w = await mountArea()

    await ask(w, "什么是特征值")
    await flushPromises()

    const toggle = w.find('[data-testid="retrieval-details-toggle"]')
    expect(toggle.exists(), "回答下方应渲染检索详情入口").toBe(true)
    expect(toggle.attributes("aria-expanded")).toBe("false")
    expect(w.find('[data-testid="results-toggle"]').exists()).toBe(false)
    expect(w.find('[data-testid="prompt-toggle"]').exists()).toBe(false)
  })

  // 验证引用统计按本轮结果去重的文档数计算，而不是「被搜索文档数」
  it("引用统计按引用文档去重计数", async () => {
    mockSearchChunks.mockResolvedValue(
      makeResponse({
        searched_document_count: 3,
        results: [
          makeResult({ rank: 1, chunk_id: "a1", parsed_document_id: "doc-a" }),
          makeResult({ rank: 2, chunk_id: "a2", parsed_document_id: "doc-a", sequence_index: 13 }),
        ],
      }),
    )
    const w = await mountArea()

    await ask(w, "什么是特征值")
    await flushPromises()

    const stats = w.find('[data-testid="citation-stats"]').text()
    expect(stats).toContain("引用 2 个分块")
    expect(stats).toContain("来自 1 个文档")
  })

  // 验证零结果时明确提示回答缺少资料依据
  it("零结果时显示无资料依据提示", async () => {
    mockSearchChunks.mockResolvedValue(
      makeResponse({ results: [], answer: "根据现有文档内容，无法回答此问题。" }),
    )
    const w = await mountArea()

    await ask(w, "宇宙的尽头是什么")
    await flushPromises()

    expect(w.find('[data-testid="sources-empty"]').exists()).toBe(true)
  })

  // 回归守护：请求失败时显示具体错误原因
  it("（回归守护）请求失败显示具体错误", async () => {
    mockSearchChunks.mockRejectedValue(new Error("检索服务暂不可用（503）"))
    const w = await mountArea()

    await ask(w, "什么是特征值")
    await flushPromises()

    const error = w.find('[data-testid="chat-error"]')
    expect(error.exists()).toBe(true)
    expect(error.text()).toContain("检索服务暂不可用（503）")
  })

  // 回归守护：第二轮请求携带上一轮 history 与同一个 session_id
  it("（回归守护）多轮请求携带 history 与同一 session_id", async () => {
    mockSearchChunks
      .mockResolvedValueOnce(makeResponse({ answer: "第一轮回答" }))
      .mockResolvedValueOnce(makeResponse({ answer: "第二轮回答" }))
    const w = await mountArea()

    await ask(w, "什么是特征值")
    await flushPromises()
    await ask(w, "它有什么性质")
    await flushPromises()

    const first = mockSearchChunks.mock.calls[0]![0] as Record<string, unknown>
    const second = mockSearchChunks.mock.calls[1]![0] as Record<string, unknown>
    expect(second.session_id).toBe(first.session_id)
    expect(second.history).toEqual([
      { role: "user", content: "什么是特征值" },
      { role: "assistant", content: "第一轮回答" },
    ])
  })

  // 回归守护：设置弹层中的 Top-K 影响下一次请求
  it("（回归守护）Top-K 设置影响下一次请求", async () => {
    mockSearchChunks.mockResolvedValue(makeResponse())
    const w = await mountArea()

    await w.find('[data-testid="settings-button"]').trigger("click")
    await w.find("#topk-slider").setValue(10)
    await ask(w, "什么是特征值")
    await flushPromises()

    expect((mockSearchChunks.mock.calls[0]![0] as Record<string, unknown>).top_k).toBe(10)
  })

  // 回归守护：空输入不能发送
  it("（回归守护）空输入按 Enter 不发送", async () => {
    const w = await mountArea()

    await ask(w, "   ")
    await flushPromises()

    expect(mockSearchChunks).not.toHaveBeenCalled()
    expect(w.find('[data-testid="send-button"]').attributes("disabled")).toBeDefined()
  })
})

describe("ChatArea 发送后滚动", () => {
  const scrollSpy = vi.fn()
  const intoViewSpy = vi.fn()

  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    mockSearchChunks.mockReset()
    scrollSpy.mockReset()
    intoViewSpy.mockReset()
    Element.prototype.scrollTo = scrollSpy as unknown as Element["scrollTo"]
    // scrollIntoView 会连带滚动 overflow-hidden 的外层壳（顶栏被滚出视口），不得使用
    Element.prototype.scrollIntoView = intoViewSpy
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ""
  })

  // 验证主动发送后只滚动消息容器（不连带滚动外层壳），使最新一轮问答（含新问题与等待占位）进入视野
  it("发送追问后消息容器滚动到最新一轮问答", async () => {
    mockSearchChunks.mockResolvedValueOnce(makeResponse({ answer: "第一轮回答" }))
    const resolveSecond = deferredSearch()
    const w = await mountArea()

    await ask(w, "什么是特征值")
    await flushPromises()
    await ask(w, "它有什么性质")
    await flushPromises()

    expect(scrollSpy).toHaveBeenCalled()
    const container = scrollSpy.mock.contexts.at(-1) as HTMLElement
    expect(container.dataset.testid).toBe("chat-scroll")
    expect(scrollSpy.mock.calls.at(-1)![0]).toHaveProperty("top")
    const turns = container.querySelectorAll("[data-turn-id]")
    expect(turns[turns.length - 1]!.textContent).toContain("它有什么性质")
    expect(turns[turns.length - 1]!.textContent).toContain("正在检索资料…")
    expect(intoViewSpy).not.toHaveBeenCalled()
    resolveSecond(makeResponse())
    await flushPromises()
  })

  // 验证异步回答返回时不再强制滚动，避免把向上翻阅的读者拉回底部
  it("回答返回时不再额外滚动", async () => {
    const resolve = deferredSearch()
    const w = await mountArea()

    await ask(w, "什么是特征值")
    await flushPromises()
    const callsAfterSend = scrollSpy.mock.calls.length
    resolve(makeResponse())
    await flushPromises()

    expect(callsAfterSend).toBeGreaterThan(0)
    expect(scrollSpy.mock.calls.length).toBe(callsAfterSend)
  })
})
