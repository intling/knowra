import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { useChatStore } from "./chat"
import { makeResponse } from "../__tests__/fixtures/search"

vi.mock("../shared/logger", () => ({
  createLogger: () => ({ debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})

describe("流式历史恢复", () => {
  // 验证刷新后残留的在途记录解除加载，有正文则保留并标为未完成，无正文则解释中断原因。
  it.each([false, true])("刷新恢复未结束的回答（已有正文=%s）", (hasAnswer) => {
    const store = useChatStore()
    store.bindUser("alice")
    const conversation = store.addConversation("流式对话")
    store.addBubble(conversation.id, {
      id: "stream-bubble",
      query: "什么是特征值",
      topK: 5,
      fileNames: [],
      response: hasAnswer ? makeResponse({ answer: "已经生成的正文", answer_tokens: null }) : null,
      error: null,
      stage: "generating",
    })
    setActivePinia(createPinia())
    const restored = useChatStore()
    restored.bindUser("alice")
    const bubble = restored.activeConversation!.bubbles[0]!
    expect(bubble.stage, "已失去连接的历史记录不能永久阻止下一次发送").toBeNull()
    if (hasAnswer) {
      expect(bubble.response?.answer).toBe("已经生成的正文")
      expect(bubble.response?.answer_incomplete).toBe(true)
      expect(bubble.response?.results).toHaveLength(1)
    } else {
      expect(bubble.error).toMatch(/中断|重新发送/)
    }
  })

  // 回归守护：完整的旧记录不被恢复逻辑误判为中断，不改写其他身份的历史。
  it("已完成的旧记录保持兼容与按用户隔离", () => {
    const store = useChatStore()
    store.bindUser("alice")
    const conversation = store.addConversation("已完成")
    const response = makeResponse()
    store.addBubble(conversation.id, {
      id: "complete-bubble", query: "什么是特征值", topK: 5, fileNames: [],
      response, error: null, stage: null,
    })
    store.bindUser("bob")
    expect(store.conversations).toEqual([])
    store.bindUser("alice")
    expect(store.activeConversation!.bubbles[0]!.response).toEqual(response)
    expect(store.activeConversation!.bubbles[0]!.error).toBeNull()
  })
})
