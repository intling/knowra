<script setup lang="ts">
import { computed, ref, watch } from "vue"

import { uploadFile } from "../../api/uploads"
import { searchChunks, type SearchResponse } from "../../api/search"
import { createLogger, getRingBuffer } from "../../shared/logger"
import { useChatStore, type ChatBubble } from "../../stores/chat"
import ChatInput, { type AttachedFile } from "../../components/ChatInput.vue"
import AnswerPanel from "../../components/AnswerPanel.vue"
import PromptPreview from "../../components/PromptPreview.vue"
import ResultsPanel from "../../components/ResultsPanel.vue"
import RewritePanel from "../../components/RewritePanel.vue"
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
const loading = ref(false)
const loadingStage = ref<"searching" | "generating" | null>(null)
const files = ref<AttachedFile[]>([])
const fileInputRef = ref<HTMLInputElement | null>(null)

/** 标记已触发自动命名的 store 对话 ID，避免重复调用 */
let autoTitledForStoreId: string | null = null

let nextBubbleId = 0
let loadingTimer: ReturnType<typeof setTimeout> | null = null

// ── Bubbles (store-backed, 响应式) ─────────────────────────────────────────

/** 当前活跃对话的气泡列表，源自 store 持久化数据。
 *  切换对话时自动跟随 activeConversation 变化。 */
const bubbles = computed<ChatBubble[]>(() => {
  const conv = chatStore.activeConversation
  if (!conv) return []
  return conv.bubbles
})

// ── 切换对话时重置本地 UI 状态 ────────────────────────────────────────────

watch(
  () => chatStore.activeConversationId,
  (newId, oldId) => {
    if (newId !== oldId) {
      query.value = ""
      files.value = []
      loading.value = false
      loadingStage.value = null
      nextBubbleId = 0
      autoTitledForStoreId = null
      clearLoadingTimer()
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

function clearLoadingTimer() {
  if (loadingTimer !== null) {
    clearTimeout(loadingTimer)
    loadingTimer = null
  }
}

/** 确保存在活跃对话（防御：无活跃对话时自动创建） */
function ensureActiveConversation(): string {
  if (chatStore.activeConversationId) return chatStore.activeConversationId
  const conv = chatStore.addConversation()
  return conv.id
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
    await uploadFile(file)
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

function transitionLoadingStage(stage: "searching" | "generating") {
  loadingStage.value = stage
}

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
  loading.value = true
  loadingStage.value = "searching"

  // Transition to "generating" after 2s for UX feedback
  loadingTimer = setTimeout(() => {
    transitionLoadingStage("generating")
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
    chatStore.updateBubble(conversationId, bubbleId, { response, error: null })

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
    chatStore.updateBubble(conversationId, bubbleId, { error: message })
    log().warn("搜索请求失败", { query: queryForApi, error: message })
  } finally {
    clearLoadingTimer()
    loading.value = false
    loadingStage.value = null
  }
}
</script>

<template>
  <section class="flex min-h-0 flex-1 flex-col">
    <!-- ── 顶部导航栏：显示当前对话模型 ── -->
    <ChatTopNav :model-name="currentModelName" />

    <!-- ── 内容滚动区域 ── -->
    <div class="flex-1 overflow-y-auto scrollbar-thin">
      <div class="main-container py-6">
        <!-- WelcomeView: empty state -->
        <Transition name="welcome-fade" appear>
          <WelcomeView v-if="showWelcome" />
        </Transition>

        <!-- Conversation history (store-backed, 支持跨会话回溯) -->
        <TransitionGroup
          v-if="hasBubbles"
          name="message-fade"
          tag="div"
          class="space-y-6"
        >
          <div
            v-for="bubble in bubbles"
            :key="bubble.id"
            class="space-y-4"
          >
            <!-- User message bubble -->
            <UserMessage :content="bubble.query" :file-names="bubble.fileNames" />

            <!-- Error state -->
            <div
              v-if="bubble.error && !bubble.response"
              data-testid="chat-error"
              class="rounded-lg border border-red-200 bg-red-50 p-4"
            >
              <p class="text-sm font-medium text-red-800">请求失败</p>
              <p class="mt-1 text-sm text-red-600">{{ bubble.error }}</p>
            </div>

            <!-- Rewrite panel (above AnswerPanel) -->
            <RewritePanel
              v-if="bubble.response"
              :rewrite-info="bubble.response.rewrite_info"
            />

            <!-- Answer panel -->
            <AnswerPanel
              v-if="bubble.response"
              :answer="bubble.response.answer"
              :answer-tokens="bubble.response.answer_tokens"
              :chat-model="bubble.response.chat_model"
              :total-results="bubble.response.results.length"
              :document-count="bubble.response.searched_document_count"
              :generation-error="bubble.response.generation_error"
            />

            <!-- Results panel -->
            <ResultsPanel
              v-if="bubble.response && bubble.response.results.length > 0"
              :results="bubble.response.results"
              :searched-document-count="bubble.response.searched_document_count"
              :total-searched="bubble.response.total_searched"
              :search-time-ms="bubble.response.search_time_ms"
            />

            <!-- Prompt preview panel -->
            <PromptPreview
              v-if="bubble.response && bubble.response.prompt_messages.length > 0"
              :messages="bubble.response.prompt_messages"
            />
          </div>
        </TransitionGroup>

        <!-- Loading skeleton for current request -->
        <div
          v-if="loading && hasBubbles"
          class="space-y-3"
        >
          <div class="mb-3 h-4 w-20 rounded bg-neutral-200" />
          <div class="space-y-2">
            <div class="h-3 w-full rounded bg-neutral-100" />
            <div class="h-3 w-5/6 rounded bg-neutral-100" />
            <div class="h-3 w-4/6 rounded bg-neutral-100" />
          </div>
        </div>
      </div>
    </div>

    <!-- Hidden file input -->
    <input
      ref="fileInputRef"
      type="file"
      multiple
      class="hidden"
      @change="handleFileChange"
    />

    <!-- ── 底部输入区：sticky 固定在底部，与内容区宽度严格一致 ── -->
    <div class="sticky bottom-0 z-10">
      <div class="main-container py-3">
        <ChatInput
          v-model:model-value="query"
          v-model:top-k="topK"
          :loading="loading"
          :loading-stage="loadingStage"
          :files="files"
          @send="handleSend"
          @add-files="handleAddFiles"
          @remove-file="handleRemoveFile"
        />
      </div>
    </div>
  </section>
</template>

<style scoped>
/* ── 统一宽度约束：内容区 & 底部输入区共用 ── */
.main-container {
  max-width: 900px;
  width: 100%;
  margin: 0 auto;
  padding-left: 1.5rem;
  padding-right: 1.5rem;
}

@media (max-width: 767px) {
  .main-container {
    max-width: 100%;
    padding-left: 0.75rem;
    padding-right: 0.75rem;
  }
}

/* ── 消息淡入动画 ── */
.message-fade-enter-active {
  transition: opacity 0.4s ease-out, transform 0.4s ease-out;
}
.message-fade-leave-active {
  transition: opacity 0.25s ease-in, transform 0.25s ease-in;
}
.message-fade-enter-from {
  opacity: 0;
  transform: translateY(12px);
}
.message-fade-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
.message-fade-move {
  transition: transform 0.3s ease;
}

/* ── 欢迎页淡入动画 ── */
.welcome-fade-enter-active {
  transition: opacity 0.5s ease-out, transform 0.5s ease-out;
}
.welcome-fade-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
</style>
