<!--
  @deprecated 此组件已在 Phase 1 布局重构中被 ChatArea 替代。
  核心逻辑已迁移至 `front/src/components/layout/ChatArea.vue`。
  保留此文件以维持现有测试通过，后续清理时会移除。
-->

<script setup lang="ts">
import { computed, ref } from "vue"

import { searchChunks, type SearchResponse } from "../api/search"
import { createLogger, getRingBuffer } from "../shared/logger"
import AnswerPanel from "../components/AnswerPanel.vue"
import ChatInput from "../components/ChatInput.vue"
import PromptPreview from "../components/PromptPreview.vue"
import ResultsPanel from "../components/ResultsPanel.vue"

/** Lazy logger — getRingBuffer() is only available after main.ts initLogger(). */
let _logger: ReturnType<typeof createLogger> | null = null
function log() {
  if (!_logger) _logger = createLogger("views:Chat", getRingBuffer())
  return _logger
}

// ── Types ──

interface Conversation {
  id: string
  query: string
  topK: number
  response: SearchResponse | null
  error: string | null
}

// ── State ──

const query = ref("")
const topK = ref(5)
const loading = ref(false)
const loadingStage = ref<"searching" | "generating" | null>(null)
const conversations = ref<Conversation[]>([])

let nextId = 0
let loadingTimer: ReturnType<typeof setTimeout> | null = null

// ── Computed ──

const hasConversations = computed(() => conversations.value.length > 0)


// ── Actions ──

function transitionLoadingStage(stage: "searching" | "generating") {
  loadingStage.value = stage
}

async function handleSend() {
  const trimmed = query.value.trim()
  if (trimmed.length === 0 || loading.value) return

  const convId = String(nextId++)
  const conv: Conversation = {
    id: convId,
    query: trimmed,
    topK: topK.value,
    response: null,
    error: null,
  }
  conversations.value.push(conv)

  // 🛡️ 从响应式数组中获取 Proxy 包装后的对象，确保后续属性赋值触发 Vue 响应式更新
  const reactiveConv = conversations.value.find((c) => c.id === convId)!

  query.value = ""
  loading.value = true
  loadingStage.value = "searching"

  // Transition to "generating" after 2s for UX feedback
  loadingTimer = setTimeout(() => {
    transitionLoadingStage("generating")
  }, 2000)

  log().info("发送搜索请求", { query: trimmed, topK: topK.value })

  try {
    const response = await searchChunks({
      query: trimmed,
      top_k: topK.value,
    })
    reactiveConv.response = response
    log().info("搜索请求完成", {
      query: trimmed,
      resultCount: response.results.length,
      hasAnswer: response.answer.length > 0,
    })
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "未知错误"
    reactiveConv.error = message
    log().warn("搜索请求失败", { query: trimmed, error: message })
  } finally {
    clearLoadingTimer()
    loading.value = false
    loadingStage.value = null
  }
}

function clearLoadingTimer() {
  if (loadingTimer !== null) {
    clearTimeout(loadingTimer)
    loadingTimer = null
  }
}
</script>

<template>
  <section class="min-h-[calc(100vh-7rem)] bg-neutral-50 pb-36">
    <div class="mx-auto w-full max-w-3xl px-4 py-8 sm:py-12">
      <!-- Page header -->
      <div class="mb-8">
        <p class="text-sm font-medium text-neutral-500">对话召回验证</p>
        <h1 class="font-display mt-2 text-2xl font-semibold tracking-normal text-neutral-900 sm:text-3xl">
          对话验证
        </h1>
        <p class="mt-2 text-sm leading-6 text-neutral-500">
          输入自然语言问题，跨所有已向量化文档进行语义搜索，AI 将基于检索结果生成带来源引用的回答。
        </p>
      </div>

      <!-- Empty state -->
      <div
        v-if="!hasConversations && !loading"
        data-testid="chat-empty-state"
        class="flex flex-col items-center justify-center py-20 text-center"
      >
        <div
          class="flex size-16 items-center justify-center rounded-2xl bg-neutral-100 text-neutral-400"
          aria-hidden="true"
        >
          <svg
            class="size-8"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path
              d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"
            />
            <path d="M8 10h.01M12 10h.01M16 10h.01" />
          </svg>
        </div>
        <h2 class="font-display mt-5 text-lg font-semibold text-neutral-800">
          开始对话
        </h2>
        <p class="mt-2 max-w-sm text-sm leading-6 text-neutral-500">
          无需选文档，直接输入问题即可获取 AI 回答。系统将自动搜索所有已向量化的知识库内容。
        </p>
      </div>

      <!-- Conversation history -->
      <div
        v-if="hasConversations"
        class="space-y-8"
      >
        <div
          v-for="conv in conversations"
          :key="conv.id"
          class="space-y-4"
        >
          <!-- User question -->
          <div class="flex justify-end">
            <div
              class="max-w-[85%] rounded-xl rounded-br-sm bg-neutral-900 px-4 py-2.5 text-sm leading-6 text-white"
            >
              {{ conv.query }}
            </div>
          </div>

          <!-- Error state -->
          <div
            v-if="conv.error && !conv.response"
            data-testid="chat-error"
            class="rounded-xl border border-red-200 bg-red-50 p-4"
          >
            <p class="text-sm font-medium text-red-800">请求失败</p>
            <p class="mt-1 text-sm text-red-600">{{ conv.error }}</p>
          </div>

          <!-- Answer panel -->
          <AnswerPanel
            v-if="conv.response"
            :answer="conv.response.answer"
            :answer-tokens="conv.response.answer_tokens"
            :chat-model="conv.response.chat_model"
            :total-results="conv.response.results.length"
            :document-count="conv.response.searched_document_count"
            :generation-error="conv.response.generation_error"
          />

          <!-- Results panel -->
          <ResultsPanel
            v-if="conv.response && conv.response.results.length > 0"
            :results="conv.response.results"
            :searched-document-count="conv.response.searched_document_count"
            :total-searched="conv.response.total_searched"
            :search-time-ms="conv.response.search_time_ms"
          />

          <!-- Prompt preview panel -->
          <PromptPreview
            v-if="conv.response && conv.response.prompt_messages.length > 0"
            :messages="conv.response.prompt_messages"
          />
        </div>
      </div>

      <!-- Loading skeleton for current request -->
      <!-- Note: user question bubble is already rendered in conversation history above;
           only show the answer skeleton to avoid a duplicate bubble. -->
      <div
        v-if="loading && hasConversations"
        class="space-y-4"
      >
        <!-- Answer skeleton -->
        <div class="animate-pulse rounded-lg border border-neutral-200 bg-white p-5 shadow-sm">
          <div class="mb-3 h-4 w-20 rounded bg-neutral-200" />
          <div class="space-y-2">
            <div class="h-3 w-full rounded bg-neutral-100" />
            <div class="h-3 w-5/6 rounded bg-neutral-100" />
            <div class="h-3 w-4/6 rounded bg-neutral-100" />
          </div>
        </div>
      </div>
    </div>

    <!-- Fixed bottom input -->
    <ChatInput
      v-model:model-value="query"
      v-model:top-k="topK"
      :loading="loading"
      :loading-stage="loadingStage"
      @send="handleSend"
    />
  </section>
</template>
