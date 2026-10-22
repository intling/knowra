import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("../shared/logger", () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))

const { LEGACY_DEFAULT_USER_ID, useChatStore } = await import("./chat")

const LEGACY_KEY = "knowra:chat"
const keyOf = (userId: string) => `knowra:chat:v2:${userId}`

function persisted(title: string, id = "c-1") {
  return JSON.stringify({
    conversations: [
      {
        id,
        title,
        messages: [],
        bubbles: [],
        createdAt: "2026-10-01T00:00:00.000Z",
        updatedAt: "2026-10-01T00:00:00.000Z",
      },
    ],
    activeConversationId: id,
  })
}

describe("chat store 按用户隔离", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  // 测试：未绑定用户时不读取任何历史（包括旧版公共键），也不写入存储。
  it("未绑定用户时为空且不持久化", () => {
    localStorage.setItem(LEGACY_KEY, persisted("旧公共对话"))
    const store = useChatStore()

    expect(store.conversations).toEqual([])
    store.addConversation("临时对话")
    expect(
      Object.keys(localStorage).filter((k) => k.startsWith("knowra:chat:v2:")),
    ).toEqual([])
  })

  // 测试：绑定用户后只读写该用户的键；切换到另一用户看不到前者对话，切回可恢复。
  it("bindUser 按用户读写并在切换时隔离", () => {
    const store = useChatStore()

    store.bindUser("alice")
    store.addConversation("Alice 的对话")
    store.bindUser("bob")
    expect(store.conversations).toEqual([])
    store.addConversation("Bob 的对话")

    store.bindUser("alice")
    expect(store.conversations.map((c) => c.title)).toEqual(["Alice 的对话"])
    expect(
      JSON.parse(localStorage.getItem(keyOf("bob"))!).conversations[0].title,
    ).toBe("Bob 的对话")
  })

  // 测试：解绑（退出/会话失效）清空内存中的对话和活跃对话，但保留该用户的本地历史。
  it("bindUser(null) 清空内存但保留持久化历史", () => {
    const store = useChatStore()
    store.bindUser("alice")
    store.addConversation("Alice 的对话")

    store.bindUser(null)

    expect(store.conversations).toEqual([])
    expect(store.activeConversationId).toBeNull()
    expect(store.ownerId).toBeNull()
    expect(localStorage.getItem(keyOf("alice"))).toContain("Alice 的对话")
  })

  // 测试：旧版公共键不会被导入任意新账号，也不会被删除。
  it("旧版 knowra:chat 不导入普通账号", () => {
    localStorage.setItem(LEGACY_KEY, persisted("旧公共对话"))
    const store = useChatStore()

    store.bindUser("new-user")

    expect(store.conversations).toEqual([])
    expect(localStorage.getItem(LEGACY_KEY)).not.toBeNull()
  })

  // 测试：只有被认领的旧默认用户首次绑定时迁移旧公共键，并删除旧键防止再次导入。
  it("旧默认用户首次绑定时迁移旧历史", () => {
    localStorage.setItem(LEGACY_KEY, persisted("旧公共对话"))
    const store = useChatStore()

    store.bindUser(LEGACY_DEFAULT_USER_ID)

    expect(LEGACY_DEFAULT_USER_ID).toBe("00000000-0000-0000-0000-000000000001")
    expect(store.conversations.map((c) => c.title)).toEqual(["旧公共对话"])
    expect(localStorage.getItem(LEGACY_KEY)).toBeNull()
    expect(localStorage.getItem(keyOf(LEGACY_DEFAULT_USER_ID))).toContain(
      "旧公共对话",
    )
  })

  // 测试：旧默认用户已有新键时不覆盖其新历史。
  it("旧默认用户已有新历史时不覆盖", () => {
    localStorage.setItem(LEGACY_KEY, persisted("旧公共对话", "old"))
    localStorage.setItem(
      keyOf(LEGACY_DEFAULT_USER_ID),
      persisted("新历史", "new"),
    )
    const store = useChatStore()

    store.bindUser(LEGACY_DEFAULT_USER_ID)

    expect(store.conversations.map((c) => c.title)).toEqual(["新历史"])
  })

  // 测试：账号切换后旧账号在途请求迟到的 updateBubble 被忽略，不写入新账号的对话或存储。
  it("切换账号后忽略旧身份的迟到响应", () => {
    const store = useChatStore()
    store.bindUser("alice")
    const conv = store.addConversation("Alice 的对话")
    store.addBubble(conv.id, {
      id: "b-1",
      query: "Alice 的问题",
      topK: 5,
      fileNames: [],
      response: null,
      error: null,
      stage: "searching",
    })
    store.bindUser("bob")

    store.updateBubble(conv.id, "b-1", { error: "迟到的结果", stage: null })

    expect(store.conversations).toEqual([])
    expect(localStorage.getItem(keyOf("bob")) ?? "").not.toContain("Alice")
  })
})
