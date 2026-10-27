import { flushPromises, mount, type VueWrapper } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import type { SearchResponse } from "../../../api/search"
import { makeResponse } from "../../../__tests__/fixtures/search"
import { makeUser } from "../../../__tests__/fixtures/users"
import { useChatStore } from "../../../stores/chat"
import { useUserStore } from "../../../stores/user"
import ChatArea from "../ChatArea.vue"

vi.mock("../../../shared/logger", () => ({
  createLogger: () => ({ debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))
const search = vi.fn()
vi.mock("../../../api/search", () => ({
  searchChunks: (...args: unknown[]) => search(...args),
}))
vi.mock("../../../api/uploads", () => ({ uploadFile: vi.fn() }))

type StreamEvent =
  | { type: "status"; stage: "searching" | "generating" }
  | { type: "metadata"; response: SearchResponse }
  | { type: "delta"; delta: string }

type StreamOptions = { onEvent: (event: StreamEvent) => void; signal: AbortSignal }
let wrapper: VueWrapper | null = null
let finish: ((response: SearchResponse) => void) | null = null

async function startAnswer() {
  let reject!: (reason: Error) => void
  search.mockReturnValueOnce(new Promise<SearchResponse>((resolve, fail) => {
    finish = resolve
    reject = fail
  }))
  wrapper = mount(ChatArea, { attachTo: document.body })
  await flushPromises()
  const input = wrapper.find('[data-testid="chat-input"]')
  await input.setValue("什么是特征值")
  await input.trigger("keydown", { key: "Enter" })
  await flushPromises()
  const options = search.mock.calls[0]?.[1] as StreamOptions | undefined
  expect(options?.onEvent, "主对话应订阅流式事件，而不是等待整段回答").toBeTypeOf("function")
  expect(options?.signal, "主对话应持有可以取消的连接").toBeInstanceOf(AbortSignal)
  return {
    area: wrapper,
    emit: options!.onEvent,
    signal: options!.signal,
    reject,
    complete: (response: SearchResponse) => finish!(response),
  }
}

async function deliver(emit: (event: StreamEvent) => void, text = "特征值满足 **Av = λv**。") {
  emit({ type: "metadata", response: makeResponse({ answer: "", answer_tokens: null }) })
  emit({ type: "delta", delta: text })
  await flushPromises()
}

async function expectInputReady(area: VueWrapper) {
  const input = area.find('[data-testid="chat-input"]')
  expect(input.attributes("disabled")).toBeUndefined()
  await input.setValue("继续解释特征值")
  expect(area.find('[data-testid="send-button"]').attributes("disabled")).toBeUndefined()
}
beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  const user = useUserStore()
  user.currentUser = makeUser("member")
  user.status = "authenticated"
  useChatStore().bindUser(user.currentUser.id)
  search.mockReset()
  finish = null
})

afterEach(async () => {
  finish?.(makeResponse())
  await flushPromises()
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ""
  vi.restoreAllMocks()
})

describe("ChatArea 流式回答", () => {
  // 验证真实阶段事件立即更新提示，元信息先于首个 token 到达时不显示空回答假象。
  it("按服务端事件切换生成提示，首段前保留等待状态", async () => {
    const { area, emit } = await startAnswer()
    emit({ type: "status", stage: "generating" })
    await flushPromises()
    expect(area.find('[data-testid="answer-pending"]').text()).toContain("正在生成回答")
    emit({ type: "metadata", response: makeResponse({ answer: "", answer_tokens: null }) })
    await flushPromises()
    expect(area.text()).toContain("正在生成回答")
    expect(area.text()).not.toContain("AI 未生成回答")
    expect(area.find('[data-testid="send-button"]').attributes("disabled")).toBeDefined()
  })

  // 验证模型未结束时已渲染真实 Markdown 和来源，生成光标可见且不能重复发送。
  it("增量到达后即时显示正文、来源与生成状态", async () => {
    const { area, emit, complete } = await startAnswer()
    await deliver(emit)
    await vi.waitFor(() => expect(area.find('[data-testid="answer-content"]').text())
      .toContain("特征值满足"))
    expect(area.find('[data-testid="answer-content"] strong').text()).toBe("Av = λv")
    expect(area.find('[data-testid="source-list"]').exists()).toBe(true)
    expect(area.find('[data-testid="streaming-cursor"]').exists()).toBe(true)
    expect(area.find('[data-testid="answer-panel"]').attributes("aria-busy")).toBe("true")
    expect(area.find('[data-testid="send-button"]').attributes("disabled")).toBeDefined()
    expect(area.find('[data-testid="token-stats"]').exists()).toBe(false)

    complete(makeResponse({ answer: "特征值满足 **Av = λv**。" }))
    await flushPromises()
    expect(area.find('[data-testid="streaming-cursor"]').exists()).toBe(false)
    await expectInputReady(area)
    expect(area.find('[data-testid="token-total"]').text()).toContain("700")
  })

  // 验证增量断流保留正文和来源，显示尚未完成提示，而非用整个请求失败覆盖正文。
  it("连接中断后保留已有正文和来源并恢复输入", async () => {
    const { area, emit, reject } = await startAnswer()
    await deliver(emit, "已经生成的正文。")
    reject(new Error("连接中断，请重试。"))
    await flushPromises()
    expect(area.find('[data-testid="answer-content"]').text()).toContain("已经生成的正文")
    expect(area.find('[data-testid="source-list"]').exists()).toBe(true)
    expect(area.find('[data-testid="answer-incomplete"]').text()).toContain("回答尚未完成")
    await expectInputReady(area)
    expect(area.find('[data-testid="streaming-cursor"]').exists()).toBe(false)
  })

  // 验证仅到达元信息就失败时展示明确请求错误，不伪装成空回答或遗留永久加载。
  it("正文出现前失败仍显示明确原因", async () => {
    const { area, emit, reject } = await startAnswer()
    emit({ type: "metadata", response: makeResponse({ answer: "", answer_tokens: null }) })
    reject(new Error("模型暂不可用，请稍后重试。"))
    await flushPromises()
    expect(area.text()).toContain("模型暂不可用")
    await expectInputReady(area)
    expect(area.find('[data-testid="streaming-cursor"]').exists()).toBe(false)
  })

  // 验证切换对话后迟到的增量只写原对话，不污染当前新对话。
  it("切换对话后增量仍只属于原对话", async () => {
    const { area, emit, complete } = await startAnswer()
    const store = useChatStore()
    const originalId = store.activeConversationId!
    await deliver(emit, "第一段")
    const other = store.addConversation("另一个对话")
    emit({ type: "delta", delta: "，第二段" })
    await flushPromises()
    expect(store.activeConversationId).toBe(other.id)
    expect(area.text()).not.toContain("第一段")
    expect(store.activeConversation?.bubbles).toEqual([])
    complete(makeResponse({ answer: "第一段，第二段" }))
    await flushPromises()
    store.setActiveConversation(originalId)
    await flushPromises()
    expect(area.find('[data-testid="answer-content"]').text()).toBe("第一段，第二段")
  })

  // 验证页面卸载、删除原对话和身份解绑均关闭请求，迟到事件不能重建旧数据。
  it.each(["unmount", "delete", "identity"])("工作区变化时取消连接（%s）", async (action) => {
    const { area, emit, signal } = await startAnswer()
    const store = useChatStore()
    const originalId = store.activeConversationId!
    await deliver(emit, "旧用户正文")
    if (action === "unmount") area.unmount()
    else if (action === "delete") store.deleteConversation(originalId)
    else store.bindUser("another-user")
    await flushPromises()
    expect(signal.aborted, "失效工作区必须停止接收模型输出").toBe(true)
    emit({ type: "delta", delta: "不能写回的新内容" })
    await flushPromises()
    if (action !== "unmount") expect(store.conversations).toEqual([])
  })

  // 验证来源元信息先到达时也保留贴底跟随，用户已向上阅读时保持原位置。
  it.each([true, false])("元信息更新保留阅读位置（原先贴底=%s）", async (atBottom) => {
    const { area, emit } = await startAnswer()
    const container = area.find<HTMLElement>('[data-testid="chat-scroll"]').element
    let height = 600
    Object.defineProperties(container, {
      scrollHeight: { get: () => height, configurable: true },
      clientHeight: { value: 300, configurable: true },
    })
    container.scrollTop = atBottom ? 300 : 0
    emit({ type: "metadata", response: makeResponse({ answer: "", answer_tokens: null }) })
    height = 1000
    await flushPromises()
    expect(container.scrollTop).toBe(atBottom ? 1000 : 0)
  })

  // 验证一次流内多个 token 不逐个同步写入 localStorage，完成后仍持久化最终正文。
  it("连续增量合并更新且仅持久化最终回答", async () => {
    const { emit, complete } = await startAnswer()
    emit({ type: "metadata", response: makeResponse({ answer: "", answer_tokens: null }) })
    await flushPromises()
    const save = vi.spyOn(Storage.prototype, "setItem")
    for (const delta of ["第", "一", "段", "。", "第", "二", "段", "。"]) {
      emit({ type: "delta", delta })
    }
    await flushPromises()
    expect(save.mock.calls.length, "token 到达应只更新内存，避免每次序列化整份历史").toBeLessThan(8)
    complete(makeResponse({ answer: "第一段。第二段。" }))
    await flushPromises()
    expect(localStorage.getItem(`knowra:chat:v2:${useChatStore().ownerId}`)).toContain("第一段。第二段。")
  })
})
