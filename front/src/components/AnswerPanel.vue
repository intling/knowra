<script setup lang="ts">
import { computed, ref } from "vue"
import { marked } from "marked"
import DOMPurify from "dompurify"

import type { AnswerTokens } from "../api/search"

const props = withDefaults(
  defineProps<{
    answer?: string
    answerTokens?: AnswerTokens | null
    chatModel?: string | null
    totalResults?: number
    documentCount?: number
    generationError?: string | null
  }>(),
  {
    answer: "",
    answerTokens: null,
    chatModel: null,
    totalResults: 0,
    documentCount: 0,
    generationError: null,
  },
)

const copyLabel = ref("复制")

const renderedMarkdown = computed(() => {
  if (!props.answer) return ""
  const raw = marked.parse(props.answer, { async: false }) as string
  return DOMPurify.sanitize(raw)
})

const isDegraded = computed(
  () => props.generationError !== null && (!props.answer || props.answer.length === 0),
)

async function handleCopy() {
  try {
    await navigator.clipboard.writeText(props.answer)
    copyLabel.value = "已复制"
    setTimeout(() => {
      copyLabel.value = "复制"
    }, 2000)
  } catch {
    copyLabel.value = "复制失败"
    setTimeout(() => {
      copyLabel.value = "复制"
    }, 2000)
  }
}
</script>

<template>
  <div class="rounded-xl border border-zinc-200 bg-white shadow-sm">
    <!-- Header -->
    <div
      class="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-100 px-5 py-3"
    >
      <h3 class="text-sm font-semibold text-zinc-700">
        <span class="mr-1.5" aria-hidden="true">🤖</span>AI 回答
      </h3>
      <div class="flex items-center gap-2">
        <span
          v-if="chatModel"
          class="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-500"
        >
          {{ chatModel }}
        </span>
        <button
          data-testid="copy-answer-button"
          class="rounded-lg border border-zinc-200 px-2.5 py-1 text-xs text-zinc-500 transition hover:border-zinc-400 hover:text-zinc-700"
          type="button"
          :disabled="!answer"
          @click="handleCopy"
        >
          {{ copyLabel }}
        </button>
      </div>
    </div>

    <!-- Degraded state: generation error without answer -->
    <div
      v-if="isDegraded"
      data-testid="answer-degraded"
      class="px-5 py-4"
    >
      <div class="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
        <p class="text-sm font-medium text-amber-800">AI 回答生成失败</p>
        <p class="mt-1 text-xs text-amber-600">
          {{ generationError }}
        </p>
        <p class="mt-2 text-xs text-amber-500">
          以下为检索到的相关内容，您仍可查看检索结果了解上下文。
        </p>
      </div>
    </div>

    <!-- Chat disabled state -->
    <div
      v-else-if="generationError === 'Chat generation is disabled'"
      data-testid="answer-disabled"
      class="px-5 py-4"
    >
      <div class="rounded-lg border border-zinc-200 bg-zinc-50 px-4 py-3">
        <p class="text-sm text-zinc-600">
          {{ answer || "AI 回答生成功能未启用，请联系管理员配置对话模型。" }}
        </p>
      </div>
    </div>

    <!-- Answer content -->
    <div
      v-else-if="answer"
      class="px-5 py-4"
    >
      <!-- eslint-disable vue/no-v-html -->
      <div
        data-testid="answer-content"
        class="prose prose-sm max-w-none overflow-x-auto prose-zinc prose-headings:text-zinc-900 prose-p:text-zinc-700 prose-a:text-blue-600 prose-a:break-all prose-strong:text-zinc-900 prose-code:rounded prose-code:bg-zinc-100 prose-code:px-1 prose-code:py-0.5 prose-code:text-sm prose-code:font-normal prose-pre:bg-zinc-950 prose-pre:text-zinc-100"
        v-html="renderedMarkdown"
      ></div>
      <!-- eslint-enable vue/no-v-html -->

      <!-- Stats footer -->
      <div
        class="mt-4 flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-zinc-100 pt-3 text-xs text-zinc-400"
      >
        <!-- Citation stats -->
        <span data-testid="citation-stats" class="inline-flex items-center gap-1">
          <svg class="size-3.5" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" stroke-linecap="round" />
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" stroke-linecap="round" />
          </svg>
          引用 {{ totalResults }} 个分块 · 来自 {{ documentCount }} 个文档
        </span>

        <!-- Token stats -->
        <span
          v-if="answerTokens"
          data-testid="token-stats"
          class="inline-flex items-center gap-1"
        >
          <svg class="size-3.5" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 6v6l4 2" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          Token: {{ answerTokens.prompt_tokens }} prompt + {{ answerTokens.completion_tokens }} completion = {{ answerTokens.total_tokens }} total
        </span>
      </div>
    </div>

    <!-- Empty state: no answer yet -->
    <div
      v-else
      class="flex items-center justify-center px-5 py-10"
    >
      <p class="text-sm text-zinc-400">等待 AI 回答生成...</p>
    </div>
  </div>
</template>
