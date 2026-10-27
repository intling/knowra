<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from "vue"

import { uploadFile } from "../../api/uploads"
import { searchChunks, type SearchResponse } from "../../api/search"
import { createLogger, getRingBuffer } from "../../shared/logger"
import { useUserStore } from "../../stores/user"
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
const userStore = useUserStore()
const canUpload = computed(() => userStore.hasPermission("knowledge:write"))

// ── State ──────────────────────────────────────────────────────────────────

const query = ref("")
const topK = ref(5)
const files = ref<AttachedFile[]>([])
const fileInputRef = ref<HTMLInputElement | null>(null)
const chatInputRef = ref<InstanceType<typeof ChatInput> | null>(null)
const scrollRef = ref<HTMLElement | null>(null)

/** 主动发送时显示最新一轮；后续增量仅在消息容器贴近底部时跟随。 */
async function revealTurn(bubbleId: string) {
  await nextTick()
  const container = scrollRef.value
  const el = container?.querySelector<HTMLElement>(
    `[data-turn-id="${bubbleId}"]`,
  )
  if (!container || !el) return
  const reduce =
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false
  // 只滚动消息容器本身；scrollIntoView 会连带滚动 overflow-hidden 的外层壳
  const top =
    el.getBoundingClientRect().top -
    container.getBoundingClientRect().top +
    container.scrollTop -
    16
  container.scrollTo?.({
    top: Math.max(0, top),
    behavior: reduce ? "auto" : "smooth",
  })
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

const pendingBubble = computed(() =>
  bubbles.value.find((bubble) => !bubble.error && (bubble.stage || !bubble.response)),
)
const loading = computed(() => Boolean(pendingBubble.value))
const loadingStage = computed(() => pendingBubble.value?.stage ?? null)

const requests = new Map<AbortController, () => ChatBubble | undefined>()
watch(
  [
    () => chatStore.ownerId,
    () => chatStore.conversations.flatMap((conversation) =>
      conversation.bubbles.map((bubble) => `${conversation.id}:${bubble.id}`)),
  ],
  () => {
    for (const [controller, findBubble] of requests) {
      if (!findBubble()) controller.abort()
    }
  },
)
onUnmounted(() => {
  for (const controller of requests.keys()) controller.abort()
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
function buildHistory(
  previousBubbles: ChatBubble[],
): Record<string, unknown>[] {
  const history: Record<string, unknown>[] = []
  for (const bubble of previousBubbles) {
    if (!bubble.response || bubble.stage) continue
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
  if (!canUpload.value) return
  fileInputRef.value?.click()
}

function handleFileChange(event: Event) {
  if (!canUpload.value) return
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
    attachedFile.error = error instanceof Error ? error.message : "上传失败"
    log().warn("文件上传失败", {
      fileName: file.name,
      error: attachedFile.error,
    })
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
  if (
    isFirstMessage &&
    trimmed.length > 0 &&
    autoTitledForStoreId !== conversationId
  ) {
    chatStore.autoTitleConversation(conversationId, trimmed)
    autoTitledForStoreId = conversationId
  }

  query.value = ""
  files.value = []
  void revealTurn(bubbleId)

  const controller = new AbortController()
  const ownerId = chatStore.ownerId
  const findBubble = () => chatStore.ownerId === ownerId
    ? chatStore.conversations.find((conversation) => conversation.id === conversationId)
      ?.bubbles.find((item) => item.id === bubbleId)
    : undefined
  requests.set(controller, findBubble)
  let streamedResponse: SearchResponse | null = null
  let pendingText = ""
  let frame: number | null = null

  function updateStream(response: SearchResponse) {
    const container = scrollRef.value
    const previousTop = container?.scrollTop ?? 0
    const follow = chatStore.activeConversationId === conversationId && container &&
      container.scrollHeight - previousTop - container.clientHeight < 96
    chatStore.updateBubble(conversationId, bubbleId, {
      response, stage: "generating",
    }, false)
    if (follow) void nextTick(() => {
      if (!controller.signal.aborted && chatStore.activeConversationId === conversationId &&
          container.scrollTop >= previousTop) {
        container.scrollTop = container.scrollHeight
      }
    })
  }

  function flushDelta() {
    if (frame !== null) cancelAnimationFrame(frame)
    frame = null
    if (!pendingText || !streamedResponse || !findBubble()) return
    streamedResponse = { ...streamedResponse, answer: streamedResponse.answer + pendingText }
    pendingText = ""
    updateStream(streamedResponse)
  }

  function finishWithError(message: string) {
    flushDelta()
    const current = findBubble()
    if (!current) return
    const partial = current.response?.answer.trim() ? current.response : null
    chatStore.updateBubble(conversationId, bubbleId, {
      response: partial ? { ...partial, answer_incomplete: true } : null,
      error: partial ? null : message,
      stage: null,
    })
  }
  controller.signal.addEventListener("abort", () => {
    finishWithError("本次回答已中断，请重新发送问题。")
  }, { once: true })
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
    }, {
      signal: controller.signal,
      onEvent(event) {
        if (controller.signal.aborted || !findBubble()) return
        if (event.type === "status") {
          chatStore.updateBubble(conversationId, bubbleId, { stage: event.stage }, false)
        } else if (event.type === "metadata") {
          streamedResponse = event.response
          updateStream(streamedResponse)
        } else {
          pendingText += event.delta
          if (frame === null) frame = requestAnimationFrame(flushDelta)
        }
      },
    })
    if (controller.signal.aborted || !findBubble()) return
    flushDelta()

    // 更新气泡：写入 API 响应数据
    chatStore.updateBubble(conversationId, bubbleId, {
      response,
      error: null,
      stage: null,
    })

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
    const message = error instanceof Error ? error.message : "未知错误"
    finishWithError(message)
    log().warn("搜索请求失败", { query: queryForApi, error: message })
  } finally {
    if (frame !== null) cancelAnimationFrame(frame)
    requests.delete(controller)
  }
}
</script>

<template>
  <section class="paper-atmosphere flex min-h-0 flex-1 flex-col">
    <ChatTopNav :model-name="currentModelName" />

    <div
      ref="scrollRef"
      data-testid="chat-scroll"
      class="flex-1 overflow-y-auto scrollbar-thin"
    >
      <div class="main-container pt-4 pb-8">
        <Transition name="welcome-fade" appear>
          <WelcomeView
            v-if="showWelcome"
            :can-upload="canUpload"
            @upload="handleAddFiles"
            @pick-suggestion="handlePickSuggestion"
          />
        </Transition>

        <TransitionGroup
          v-if="hasBubbles"
          name="message-fade"
          tag="div"
          class="space-y-10 pt-4"
        >
          <div
            v-for="bubble in bubbles"
            :key="bubble.id"
            :data-turn-id="bubble.id"
            class="scroll-mt-4 space-y-5"
          >
            <UserMessage
              :content="bubble.query"
              :file-names="bubble.fileNames"
            />

            <!-- 等待回答：阶段文案显示在回答位置，并由读屏播报 -->
            <div
              v-if="!bubble.response && !bubble.error"
              class="flex gap-3 sm:gap-4"
            >
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
                  {{
                    bubble.stage === "generating"
                      ? "正在生成回答…"
                      : "正在检索资料…"
                  }}
                </p>
                <div
                  class="mt-3 space-y-2 motion-safe:animate-pulse"
                  aria-hidden="true"
                >
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
              <p class="mt-0.5 text-sm text-red-800 [overflow-wrap:anywhere]">
                {{ bubble.error }}
              </p>
              <p class="mt-1 text-xs text-red-700/80">
                请稍后重新发送这个问题。
              </p>
            </div>

            <template v-if="bubble.response">
              <AnswerPanel
                :answer-mode="bubble.response.answer_mode"
                :streaming="bubble.stage === 'generating'"
                :answer="bubble.response.answer"
                :answer-incomplete="bubble.response.answer_incomplete"
                :answer-tokens="bubble.response.answer_tokens"
                :chat-model="bubble.response.chat_model"
                :total-results="bubble.response.results.length"
                :document-count="citedDocumentCount(bubble.response)"
                :generation-error="bubble.response.generation_error"
              />
              <div class="space-y-3 pl-10 sm:pl-11">
                <p v-if="bubble.response.retrieval_status === 'unavailable'" role="status" class="text-xs text-ink-muted">
                  检索暂不可用，请稍后重试以核对资料。
                </p>
                <p v-if="bubble.response.answer_mode === 'summary' && bubble.response.summary_coverage" class="text-xs text-ink-muted">
                  {{ bubble.response.summary_coverage.truncated ? "基于部分资料总结" : "资料总结" }}
                  · 已提供给模型 {{ bubble.response.summary_coverage.included_document_count }} / {{ bubble.response.summary_coverage.document_count }} 份资料，
                  {{ bubble.response.summary_coverage.included_chunks }} / {{ bubble.response.summary_coverage.total_chunks }} 个片段
                </p>
                <SourceList
                  v-if="!bubble.response.answer_mode || bubble.response.answer_mode === 'rag' || bubble.response.answer_mode === 'summary'"
                  :results="bubble.response.results"
                  :summary="bubble.response.answer_mode === 'summary'"
                />
                <RetrievalDetails
                  v-if="!bubble.response.answer_mode || bubble.response.answer_mode === 'rag'"
                  :response="bubble.response"
                />
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
          :can-upload="canUpload"
          :loading="loading"
          :loading-stage="loadingStage"
          :files="files"
          @send="handleSend"
          @add-files="handleAddFiles"
          @remove-file="handleRemoveFile"
        />
        <p class="mt-1.5 text-center text-[11px] text-ink-faint">
          可直接提问，上传资料可增强回答；资料结论请核对来源原文。
        </p>
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
