import { defineStore } from "pinia"

import type { SearchResponse } from "../api/search"
import { createLogger, getRingBuffer } from "../shared/logger"

/** Lazy logger — getRingBuffer() is only available after main.ts initLogger(). */
let _logger: ReturnType<typeof createLogger> | null = null
function log() {
  if (!_logger) _logger = createLogger("stores:chat", getRingBuffer())
  return _logger
}

// ── Types ──────────────────────────────────────────────────────────────────

export interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  createdAt: string
}

/** ChatBubble — 单轮对话气泡的完整数据，用于 ChatArea 渲染与持久化 */
export interface ChatBubble {
  id: string
  query: string
  topK: number
  fileNames: string[]
  response: SearchResponse | null
  error: string | null
}

export interface Conversation {
  id: string
  title: string
  messages: Message[]
  /** 对话气泡列表（ChatArea 渲染数据），持久化以支持历史回溯 */
  bubbles: ChatBubble[]
  createdAt: string
  updatedAt: string
}

interface ChatState {
  conversations: Conversation[]
  activeConversationId: string | null
}

interface PersistedChatData {
  conversations: Conversation[]
  activeConversationId: string | null
}

// ── Helpers ────────────────────────────────────────────────────────────────

const STORAGE_KEY = "knowra:chat"

/** 自动提炼对话标题的最大字符数（中文约 15-18 字） */
const AUTO_TITLE_MAX_LENGTH = 18

/** 常见问题前缀模式，提炼标题时会被移除 */
const QUERY_PREFIX_PATTERNS: (string | RegExp)[] = [
  /^请(帮我?|你|问|告诉我|解释|介绍|描述|总结|概括|梳理|列举|列出|比较|分析|说明)/,
  /^(帮我|你来|麻烦你?|能不能|可以|可不可以|能否)(帮我?|你)?/,
  /^(如何|怎么|怎样|怎么样|为什么|什么是?|是什么|是谁|哪个|哪一[个种])/,
  /^(我想(知道|了解|问|要|看看|查|查询|搜索|找))|(我要(知道|了解|问|查|搜索))/,
  /^(告诉我|解释一下|讲一下|说一下|描述一下|介绍一下)/,
  /^(请?)(搜索|查找|查询|帮我查|帮我搜索)/,
  /^(关于|对于|针对|有关)/,
]

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

function nowISO(): string {
  return new Date().toISOString()
}

/**
 * 从用户第一条消息内容智能提炼对话标题。
 *
 * 处理流程：
 * 1. 折叠所有空白字符为单空格
 * 2. 移除常见问句前缀（"请帮我"、"如何"、"怎么" 等）
 * 3. 截断至 AUTO_TITLE_MAX_LENGTH 并追加省略号
 * 4. 若提炼后为空，返回空字符串（调用方回退到时间戳命名）
 */
export function autoTitleFromMessage(content: string): string {
  // 1. 折叠空白
  let cleaned = content.replace(/\s+/g, " ").trim()
  if (!cleaned) return ""

  // 2. 移除常见前缀（按顺序尝试，匹配则移除）
  for (const pattern of QUERY_PREFIX_PATTERNS) {
    const match = cleaned.match(pattern)
    if (match && match.index === 0) {
      cleaned = cleaned.slice(match[0].length).trim()
      break // 只移除第一个匹配的前缀
    }
  }

  // 3. 移除末尾标点
  cleaned = cleaned.replace(/[？?！!。，,、；;：:….]+$/g, "").trim()

  if (!cleaned) return ""

  // 4. 截断
  if (cleaned.length <= AUTO_TITLE_MAX_LENGTH) return cleaned
  return cleaned.slice(0, AUTO_TITLE_MAX_LENGTH) + "…"
}

/** 生成时间戳回退标题（如 "7月29日 14:30"） */
function timestampTitle(): string {
  const d = new Date()
  const month = d.getMonth() + 1
  const day = d.getDate()
  const hours = d.getHours().toString().padStart(2, "0")
  const minutes = d.getMinutes().toString().padStart(2, "0")
  return `${month}月${day}日 ${hours}:${minutes}`
}

function loadFromStorage(): PersistedChatData {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { conversations: [], activeConversationId: null }

    const parsed = JSON.parse(raw) as PersistedChatData

    // 验证数据结构
    if (!Array.isArray(parsed.conversations)) {
      log().warn("localStorage 对话数据格式异常（conversations 非数组），重置为空列表", {
        module_name: "chat-store",
      })
      return { conversations: [], activeConversationId: null }
    }

    // 迁移旧数据：为缺少 bubbles 字段的对话补全
    const migrated = parsed.conversations.map((c) => ({
      ...c,
      bubbles: Array.isArray((c as unknown as Record<string, unknown>).bubbles)
        ? (c as unknown as Record<string, unknown>).bubbles
        : [],
    })) as Conversation[]

    return {
      conversations: migrated,
      activeConversationId: parsed.activeConversationId ?? null,
    }
  } catch (error) {
    log().warn("localStorage 对话数据解析失败，重置为空列表", {
      module_name: "chat-store",
      error: error instanceof Error ? error.message : String(error),
    })
    return { conversations: [], activeConversationId: null }
  }
}

function saveToStorage(state: ChatState): void {
  try {
    const data: PersistedChatData = {
      conversations: state.conversations,
      activeConversationId: state.activeConversationId,
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
  } catch (error) {
    log().error("localStorage 对话数据保存失败", {
      module_name: "chat-store",
      error: error instanceof Error ? error.message : String(error),
    })
  }
}

// ── Store ──────────────────────────────────────────────────────────────────

export const useChatStore = defineStore("chat", {
  state: (): ChatState => {
    const persisted = loadFromStorage()
    return {
      conversations: persisted.conversations,
      activeConversationId: persisted.activeConversationId,
    }
  },

  getters: {
    /** 当前活跃的完整对话对象 */
    activeConversation(state): Conversation | null {
      if (!state.activeConversationId) return null
      return state.conversations.find((c) => c.id === state.activeConversationId) ?? null
    },

    /** 非活跃的历史对话列表（时间倒序） */
    historyConversations(state): Conversation[] {
      return state.conversations.filter((c) => c.id !== state.activeConversationId)
    },
  },

  actions: {
    /** 创建新对话，标题为空（UI 显示"新对话…"占位），自动设为活跃对话 */
    addConversation(title?: string): Conversation {
      const now = nowISO()
      const conversation: Conversation = {
        id: generateId(),
        title: title || "",
        messages: [],
        bubbles: [],
        createdAt: now,
        updatedAt: now,
      }

      // 新对话插入列表头部（时间倒序）
      this.conversations.unshift(conversation)
      this.activeConversationId = conversation.id

      saveToStorage(this.$state)
      log().info("创建新对话", { conversationId: conversation.id, title: conversation.title || "(空)" })

      return conversation
    },

    /** 删除指定对话，若删除的是活跃对话则清除活跃状态 */
    deleteConversation(id: string): void {
      const index = this.conversations.findIndex((c) => c.id === id)
      if (index === -1) {
        log().warn("尝试删除不存在的对话", { conversationId: id })
        return
      }

      this.conversations.splice(index, 1)

      if (this.activeConversationId === id) {
        this.activeConversationId = null
      }

      saveToStorage(this.$state)
      log().info("删除对话", { conversationId: id })
    },

    /** 重命名指定对话标题，空标题不生效 */
    renameConversation(id: string, title: string): void {
      if (!title || title.trim().length === 0) return

      const conversation = this.conversations.find((c) => c.id === id)
      if (!conversation) {
        log().warn("尝试重命名不存在的对话", { conversationId: id })
        return
      }

      conversation.title = title
      conversation.updatedAt = nowISO()

      saveToStorage(this.$state)
      log().info("重命名对话", { conversationId: id, title })
    },

    /**
     * 使用首条消息内容自动提炼对话标题。
     * 仅在标题为空（初始状态）时生效，已命名过的对话不会被覆盖。
     * 若提炼结果为空，回退到时间戳命名。
     */
    autoTitleConversation(id: string, content: string): void {
      const conversation = this.conversations.find((c) => c.id === id)
      if (!conversation) return

      // 仅在标题为空（初始状态）时才自动提炼
      if (conversation.title !== "" && conversation.title !== "新对话") return

      const autoTitle = autoTitleFromMessage(content)
      conversation.title = autoTitle || timestampTitle()
      conversation.updatedAt = nowISO()

      saveToStorage(this.$state)
      log().info("自动提炼对话标题", { conversationId: id, title: conversation.title })
    },

    /** 设置当前活跃对话，传入 null 清除活跃状态 */
    setActiveConversation(id: string | null): void {
      this.activeConversationId = id
      saveToStorage(this.$state)
      log().info("切换活跃对话", { conversationId: id })
    },

    // ── ChatBubble CRUD ────────────────────────────────────────────────────

    /** 向指定对话追加一个气泡 */
    addBubble(conversationId: string, bubble: ChatBubble): void {
      const conversation = this.conversations.find((c) => c.id === conversationId)
      if (!conversation) {
        log().warn("尝试向不存在的对话添加气泡", { conversationId })
        return
      }

      conversation.bubbles.push(bubble)
      conversation.updatedAt = nowISO()
      saveToStorage(this.$state)
    },

    /** 更新指定对话中的某个气泡（按 id 匹配） */
    updateBubble(conversationId: string, bubbleId: string, updates: Partial<ChatBubble>): void {
      const conversation = this.conversations.find((c) => c.id === conversationId)
      if (!conversation) {
        log().warn("尝试更新不存在的对话气泡", { conversationId, bubbleId })
        return
      }

      const bubble = conversation.bubbles.find((b) => b.id === bubbleId)
      if (!bubble) {
        log().warn("尝试更新不存在的气泡", { conversationId, bubbleId })
        return
      }

      Object.assign(bubble, updates)
      conversation.updatedAt = nowISO()
      saveToStorage(this.$state)
    },

    /** 清空指定对话的所有气泡（切换对话时不会自动清空） */
    clearBubbles(conversationId: string): void {
      const conversation = this.conversations.find((c) => c.id === conversationId)
      if (!conversation) {
        log().warn("尝试清空不存在对话的气泡", { conversationId })
        return
      }

      conversation.bubbles = []
      conversation.updatedAt = nowISO()
      saveToStorage(this.$state)
    },
  },
})
