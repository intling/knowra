<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue"

import { uploadFile } from "../../api/uploads"
import { searchChunks, type SearchResponse } from "../../api/search"
import { createLogger, getRingBuffer } from "../../shared/logger"
import { useChatStore, type ChatBubble } from "../../stores/chat"
import ChatInput, { type AttachedFile } from "../../components/ChatInput.vue"
import AnswerPanel from "../../components/AnswerPanel.vue"
import RetrievalDetails from "../../components/chat/RetrievalDetails.vue"
import SourceList from "../../components/chat/SourceList.vue"
import WelcomeView from "../../components/chat/WelcomeView.vue"
import UserMessage from "../../components/chat/UserMessage.vue"
import ChatTopNav from "../../components/chat/ChatTopNav.vue"

/** Lazy logger — getRingBuffer() is only available after main.ts initLogger(). */
let _logger: ReturnType<typeof createLogger> | null = null
function log() {
  if (!_logger) _logger = createLogger("components:ChatArea", getRingBuffer())
  return _logger
}

// ── Store ──────────────────────────────────────────────────────────────────

const chatStore = useChatStore()

// ── State ──────────────────────────────────────────────────────────────────

const query = ref("")
const topK = ref(5)
const files = ref<AttachedFile[]>([])
const fileInputRef = ref<HTMLInputElement | null>(null)
const chatInputRef = ref<InstanceType<typeof ChatInput> | null>(null)
const scrollRef = ref<HTMLElement | null>(null)

/** 主动发送后把最新一轮问答滚入视野；回答异步返回时不滚动。 */
async function revealTurn(bubbleId: string) {
  await nextTick()
  const container = scrollRef.value
  const el = container?.querySelector<HTMLElement>(`[data-turn-id="${bubbleId}"]`)
  if (!container || !el) return
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false
  // 只滚动消息容器本身；scrollIntoView 会连带滚动 overflow-hidden 的外层壳
  const top = el.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop - 16
  container.scrollTo?.({ top: Math.max(0, top), behavior: reduce ? "auto" : "smooth" })
}
const forceReplace = ref(false)

/** 标记已触发自动命名的 store 对话 ID，避免重复调用 */
let autoTitledForStoreId: string | null = null

let nextBubbleId = 0

// ── Bubbles (store-backed, 响应式) ─────────────────────────────────────────

/** 当前活跃对话的气泡列表，源自 store 持久化数据。
 *  切换对话时自动跟随 activeConversation 变化。 */
const bubbles = computed<ChatBubble[]>(() => {
  const conv = chatStore.activeConversation
  if (!conv) return []
  return conv.bubbles
})

/** 当前活跃对话是否处于“等待响应”状态（存在 response/error 均为 null 的在途气泡）。
 *  从气泡持久化数据派生，而非组件局部状态，因此切换对话后仍能正确反映加载态，
 *  并让输入框保持加载样式、发送按钮保持禁用。 */
const loading = computed(() =>
  bubbles.value.some((bubble) => !bubble.response && !bubble.error),
)

/** 当前在途气泡的加载阶段（searching/generating）。
 *  同样从气泡持久化数据派生，切换对话后能恢复正确阶段文案。 */
const loadingStage = computed<"searching" | "generating" | null>(() => {
  const pending = bubbles.value.find((bubble) => !bubble.response && !bubble.error)
  return pending?.stage ?? null
})

// ── 切换对话时重置本地 UI 状态 ────────────────────────────────────────────

watch(
  () => chatStore.activeConversationId,
  (newId, oldId) => {
    if (newId !== oldId) {
      query.value = ""
      files.value = []
      nextBubbleId = 0
      autoTitledForStoreId = null
    }
  },
)

// ── Computed ───────────────────────────────────────────────────────────────

const hasBubbles = computed(() => bubbles.value.length > 0)
const showWelcome = computed(() => !hasBubbles.value && !loading.value)

/** 从最近一次有模型信息的对话响应中提取模型名称，供顶栏展示。 */
const currentModelName = computed(() => {
  for (let i = bubbles.value.length - 1; i >= 0; i--) {
    const model = bubbles.value[i]?.response?.chat_model
    if (model) return model
  }
  return null
})

// ── Helpers ────────────────────────────────────────────────────────────────

function generateBubbleId(): string {
  return `${Date.now()}-${(nextBubbleId++).toString(36)}`
}

/** 从已有气泡列表中提取对话历史，用于查询重写的指代词消解。
 *
 *  每个已完成的气泡产生两条消息：user（查询）+ assistant（回答）。
 *  跳过无响应的气泡（如发送中或出错的气泡）。
 */
function buildHistory(previousBubbles: ChatBubble[]): Record<string, unknown>[] {
  const history: Record<string, unknown>[] = []
  for (const bubble of previousBubbles) {
    if (!bubble.response) continue
    history.push({ role: "user", content: bubble.query })
    history.push({ role: "assistant", content: bubble.response.answer })
  }
  return history
}

/** 确保存在活跃对话（防御：无活跃对话时自动创建） */
function ensureActiveConversation(): string {
  if (chatStore.activeConversationId) return chatStore.activeConversationId
  const conv = chatStore.addConversation()
  return conv.id
}

/** 本轮回答实际引用的文档数（按 parsed_document_id 去重）。 */
function citedDocumentCount(response: SearchResponse): number {
  return new Set(response.results.map((r) => r.parsed_document_id)).size
}

/** 推荐问题：只填入输入框并聚焦，由用户确认后发送。 */
async function handlePickSuggestion(text: string) {
  query.value = text
  await nextTick()
  chatInputRef.value?.focus()
}

// ── File handling ──────────────────────────────────────────────────────────

function handleAddFiles() {
  fileInputRef.value?.click()
}

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const selectedFiles = input.files
  if (!selectedFiles || selectedFiles.length === 0) return

  for (let i = 0; i < selectedFiles.length; i++) {
    const file = selectedFiles[i]!
    const attachedFile: AttachedFile = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
      name: file.name,
      size: file.size,
      status: "pending",
    }
    files.value.push(attachedFile)
    uploadAttachedFile(attachedFile.id, file)
  }

  input.value = ""
}

async function uploadAttachedFile(id: string, file: File) {
  const attachedFile = files.value.find((f) => f.id === id)
  if (!attachedFile) return

  attachedFile.status = "uploading"

  try {
    await uploadFile(file, forceReplace.value)
    attachedFile.status = "uploaded"
    log().info("文件上传成功", { fileName: file.name })
  } catch (error) {
    attachedFile.status = "error"
    attachedFile.error =
      error instanceof Error ? error.message : "上传失败"
    log().warn("文件上传失败", { fileName: file.name, error: attachedFile.error })
  }
}

function handleRemoveFile(id: string) {
  const index = files.value.findIndex((f) => f.id === id)
  if (index !== -1) {
    files.value.splice(index, 1)
  }
}

// ── Send ───────────────────────────────────────────────────────────────────

async function handleSend() {
  const trimmed = query.value.trim()
  const hasUploadedFiles = files.value.some((f) => f.status === "uploaded")
  if ((trimmed.length === 0 && !hasUploadedFiles) || loading.value) return

  // 确保存在活跃对话
  const conversationId = ensureActiveConversation()
  const isFirstMessage = bubbles.value.length === 0

  const bubbleId = generateBubbleId()
  const attachedFileNames = files.value
    .filter((f) => f.status === "uploaded")
    .map((f) => f.name)

  const bubble: ChatBubble = {
    id: bubbleId,
    query: trimmed || "总结归纳文档的关键信息",
    topK: topK.value,
    fileNames: attachedFileNames,
    response: null,
    error: null,
    stage: "searching",
  }

  // 持久化气泡到 store（立即反映到 UI，Optimistic UI）
  chatStore.addBubble(conversationId, bubble)

  // 首条消息 → 立即用用户输入乐观生成标题（不阻塞发送）
  if (isFirstMessage && trimmed.length > 0 && autoTitledForStoreId !== conversationId) {
    chatStore.autoTitleConversation(conversationId, trimmed)
    autoTitledForStoreId = conversationId
  }

  query.value = ""
  files.value = []
  void revealTurn(bubbleId)

  // Transition to "generating" after 2s for UX feedback。
  //  写入气泡的 stage 字段（而非组件局部状态），这样即使切换对话，
  //  该在途气泡的阶段也能被正确持久化并恢复。
  setTimeout(() => {
    const conv = chatStore.conversations.find((c) => c.id === conversationId)
    const pending = conv?.bubbles.find((b) => b.id === bubbleId)
    if (pending && !pending.response && !pending.error) {
      chatStore.updateBubble(conversationId, bubbleId, { stage: "generating" })
    }
  }, 2000)

  const queryForApi = trimmed || "总结归纳文档的关键信息"
  log().info("发送搜索请求", { query: queryForApi, topK: topK.value })

  // 构建对话历史（当前气泡之前的所有已完成气泡），用于查询重写的指代词消解
  const history = buildHistory(bubbles.value.slice(0, -1))

  try {
    const response: SearchResponse = await searchChunks({
      query: queryForApi,
      top_k: topK.value,
      session_id: conversationId,
      ...(history.length > 0 ? { history } : {}),
    })

    // 更新气泡：写入 API 响应数据
    chatStore.updateBubble(conversationId, bubbleId, { response, error: null, stage: null })

    // AI 响应回来后，若标题仍为空/默认值，用 AI 回答内容二次提炼
    if (isFirstMessage && response.answer.length > 0) {
      const conv = chatStore.conversations.find((c) => c.id === conversationId)
      if (conv && (conv.title === "" || conv.title === "新对话")) {
        chatStore.autoTitleConversation(conversationId, response.answer)
      }
    }

    log().info("搜索请求完成", {
      query: queryForApi,
      resultCount: response.results.length,
      hasAnswer: response.answer.length > 0,
    })
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "未知错误"
    chatStore.updateBubble(conversationId, bubbleId, { error: message, stage: null })
    log().warn("搜索请求失败", { query: queryForApi, error: message })
  }
}
</script>

<template>
  <section class="paper-atmosphere flex min-h-0 flex-1 flex-col">
    <ChatTopNav :model-name="currentModelName" />

    <div ref="scrollRef" data-testid="chat-scroll" class="flex-1 overflow-y-auto scrollbar-thin">
      <div class="main-container pt-4 pb-8">
        <Transition name="welcome-fade" appear>
          <WelcomeView
            v-if="showWelcome"
            @upload="handleAddFiles"
            @pick-suggestion="handlePickSuggestion"
          />
        </Transition>

        <TransitionGroup v-if="hasBubbles" name="message-fade" tag="div" class="space-y-10 pt-4">
          <div
            v-for="bubble in bubbles"
            :key="bubble.id"
            :data-turn-id="bubble.id"
            class="scroll-mt-4 space-y-5"
          >
            <UserMessage :content="bubble.query" :file-names="bubble.fileNames" />

            <!-- 等待回答：阶段文案显示在回答位置，并由读屏播报 -->
            <div v-if="!bubble.response && !bubble.error" class="flex gap-3 sm:gap-4">
              <span
                class="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md bg-brand-700/85 font-display text-sm font-semibold text-white"
                aria-hidden="true"
                >知</span
              >
              <div class="min-w-0 flex-1">
                <p
                  data-testid="answer-pending"
                  role="status"
                  aria-live="polite"
                  class="text-sm text-ink-muted"
                >
                  {{ bubble.stage === "generating" ? "正在生成回答…" : "正在检索资料…" }}
                </p>
                <div class="mt-3 space-y-2 motion-safe:animate-pulse" aria-hidden="true">
                  <div class="h-2.5 w-full rounded bg-paper-deep" />
                  <div class="h-2.5 w-5/6 rounded bg-paper-deep" />
                  <div class="h-2.5 w-3/5 rounded bg-paper-deep" />
                </div>
              </div>
            </div>

            <div
              v-if="bubble.error && !bubble.response"
              data-testid="chat-error"
              role="alert"
              class="ml-10 rounded-[var(--radius-button)] border-l-2 border-red-600 bg-red-50/70 px-3.5 py-2.5 sm:ml-11"
            >
              <p class="text-sm font-medium text-red-900">请求失败</p>
              <p class="mt-0.5 text-sm text-red-800 [overflow-wrap:anywhere]">{{ bubble.error }}</p>
              <p class="mt-1 text-xs text-red-700/80">请稍后重新发送这个问题。</p>
            </div>

            <template v-if="bubble.response">
              <AnswerPanel
                :answer="bubble.response.answer"
                :answer-tokens="bubble.response.answer_tokens"
                :chat-model="bubble.response.chat_model"
                :total-results="bubble.response.results.length"
                :document-count="citedDocumentCount(bubble.response)"
                :generation-error="bubble.response.generation_error"
              />
              <div class="space-y-3 pl-10 sm:pl-11">
                <SourceList :results="bubble.response.results" />
                <RetrievalDetails :response="bubble.response" />
              </div>
            </template>
          </div>
        </TransitionGroup>
      </div>
    </div>

    <input
      ref="fileInputRef"
      type="file"
      multiple
      class="hidden"
      aria-hidden="true"
      tabindex="-1"
      @change="handleFileChange"
    />

    <div class="shrink-0 bg-gradient-to-t from-paper via-paper to-paper/0 pt-2">
      <div class="main-container pb-3 sm:pb-4">
        <ChatInput
          ref="chatInputRef"
          v-model:model-value="query"
          v-model:top-k="topK"
          v-model:force-replace="forceReplace"
          :loading="loading"
          :loading-stage="loadingStage"
          :files="files"
          @send="handleSend"
          @add-files="handleAddFiles"
          @remove-file="handleRemoveFile"
        />
        <p class="mt-1.5 text-center text-[11px] text-ink-faint">回答依据你的资料生成，请以来源原文为准。</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* 内容列与输入区共用同一宽度，左右对齐 */
.main-container {
  width: 100%;
  max-width: 47.5rem;
  margin: 0 auto;
  padding-left: 1.5rem;
  padding-right: 1.5rem;
}

@media (max-width: 767px) {
  .main-container {
    padding-left: 0.75rem;
    padding-right: 0.75rem;
  }
}

.message-fade-enter-active {
  transition:
    opacity 0.2s ease-out,
    transform 0.2s ease-out;
}
.message-fade-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.welcome-fade-enter-active {
  transition: opacity 0.3s ease-out;
}
.welcome-fade-enter-from {
  opacity: 0;
}
</style>
